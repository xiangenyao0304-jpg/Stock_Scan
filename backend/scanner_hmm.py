"""HMM 市场择时 + 多因子技术形态打分 多市场选股系统 (A 股 / 港股 / 美股)."""

from __future__ import annotations

import json
import logging
import os
import pickle
import threading
import time
from typing import Any, Literal
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Protocol

import akshare as ak
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---- 常量配置 -----------------------------------------------------------

Market = Literal["a", "hk", "us", "themes"]
MARKETS: tuple[Market, ...] = ("a", "hk", "us", "themes")

MAIN_BOARD_PREFIXES: tuple[str, ...] = ("600", "601", "603", "605", "000", "001", "002")
EXCLUDE_PREFIXES: tuple[str, ...] = ("688", "300")  # 科创板, 创业板
MIN_LISTING_DAYS = 60
LOOKBACK_DAYS = 60  # 评分用: 4 因子最长 20 日 BOLL, 60 足够
CACHE_ROWS = 250  # 缓存保留 ~250 交易日 (约 1 年), 滚动更新
INDEX_LOOKBACK_DAYS = 500
HMM_STATES = 3
SCORE_THRESHOLD = 7.5
STATE_LABELS = {0: "熊市", 1: "震荡市", 2: "牛市"}

# 各市场宏观基准指数
INDEX_SYMBOL: dict[Market, str] = {
    "a": "sh000001",   # 上证指数
    "hk": "HSTECH",    # 恒生科技指数
    "us": ".INX",      # 标普 500 (sina)
    "themes": ".INX",  # 主题股全部为美股, 沿用标普 500 做宏观择时
}

# 各市场友好名 (日志用)
MARKET_LABEL: dict[Market, str] = {
    "a": "A 股",
    "hk": "港股",
    "us": "美股",
    "themes": "主题股",
}

CACHE_DIR = Path(os.environ.get("STOCKS_SCAN_CACHE", "/var/lib/stocks_scan/cache"))
RESULTS_DIR = CACHE_DIR / "results"
UNIVERSES_DIR = Path(__file__).resolve().parent / "universes"
DEFAULT_MAX_WORKERS = 24
STALE_BACKFILL_DAYS = 3  # 超过 N 天没更新则走全量回源
CACHE_FRESH_SECONDS = 12 * 3600  # 文件 mtime 12h 内视为新鲜, 跳过任何回源
_cache_lock = threading.Lock()


def _validate_market(market: str) -> Market:
    if market not in MARKETS:
        raise ValueError(f"unknown market: {market!r} (expect a/hk/us)")
    return market  # type: ignore[return-value]


# ---- 数据抽象层 ---------------------------------------------------------

class StockDataFetcher(Protocol):
    """可替换的数据源接口."""
    market: Market

    def get_stock_list(self) -> pd.DataFrame: ...

    def get_daily(self, code: str, days: int) -> pd.DataFrame: ...

    def get_index_daily(self, symbol: str, days: int) -> pd.DataFrame: ...


def _prefix_symbol_a(code: str) -> str:
    """将 A 股纯数字代码转换为 akshare 新浪接口格式."""
    code = str(code).zfill(6)
    if code.startswith(("6", "9")):
        return f"sh{code}"
    return f"sz{code}"


def _normalize_hk(code: str) -> str:
    """HK 代码标准化为 5 位 (akshare 通用规则)."""
    s = str(code).strip().lstrip("0")
    if not s:
        s = "0"
    return s.zfill(5)


def _normalize_us(code: str) -> str:
    return str(code).strip().upper()


def _cache_path(code: str, market: Market) -> Path:
    _validate_market(market)
    if market == "a":
        name = f"{str(code).zfill(6)}.pkl"
    elif market == "hk":
        name = f"{_normalize_hk(code)}.pkl"
    else:
        name = f"{_normalize_us(code)}.pkl"
    return CACHE_DIR / market / name


def _cache_load(code: str, market: Market) -> pd.DataFrame | None:
    p = _cache_path(code, market)
    if not p.exists():
        return None
    try:
        with p.open("rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _cache_store(code: str, df: pd.DataFrame, market: Market) -> None:
    try:
        with _cache_lock:
            path = _cache_path(code, market)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".pkl.tmp")
            with tmp.open("wb") as f:
                pickle.dump(df, f, protocol=pickle.HIGHEST_PROTOCOL)
            tmp.replace(path)
    except Exception as e:
        logger.debug("cache store failed %s/%s: %s", market, code, e)


def save_result(kind: str, data: Any, market: Market = "a") -> None:
    """持久化默认参数扫描结果, 供页面首屏直接读取."""
    _validate_market(market)
    try:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        final_name = f"{kind}_{market}.json"
        tmp = RESULTS_DIR / f".{final_name}.tmp"
        final = RESULTS_DIR / final_name
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, default=str)
        tmp.replace(final)
    except Exception as e:
        logger.warning("save_result %s/%s failed: %s", market, kind, e)


def load_result(kind: str, market: Market = "a") -> Any | None:
    _validate_market(market)
    p = RESULTS_DIR / f"{kind}_{market}.json"
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_cached_daily(code: str, days: int, market: Market = "a") -> pd.DataFrame | None:
    """只读缓存, 不做任何网络请求. 供扫描端使用."""
    df = _cache_load(code, market)
    if df is None or df.empty:
        return None
    return df.tail(days).reset_index(drop=True)


def _last_trading_day() -> pd.Timestamp:
    return pd.Timestamp.now().normalize()


# ---- Universe 加载 ------------------------------------------------------

def _load_universe_json(name: str) -> pd.DataFrame:
    path = UNIVERSES_DIR / name
    with path.open("r", encoding="utf-8") as f:
        doc = json.load(f)
    rows = doc.get("stocks", [])
    if not rows:
        return pd.DataFrame(columns=["code", "name"])
    df = pd.DataFrame(rows)
    return df[["code", "name"]].copy()


# ---- Spot 批量查询 ------------------------------------------------------

def _fetch_spot_a() -> dict[str, dict]:
    try:
        df = ak.stock_zh_a_spot_em()
    except Exception as e:
        logger.warning("A spot fetch failed: %s", e)
        return {}
    if df is None or df.empty:
        return {}
    today = _last_trading_day()
    out: dict[str, dict] = {}
    for _, r in df.iterrows():
        try:
            code = str(r["代码"]).zfill(6)
            close = float(r["最新价"])
            open_ = float(r["今开"])
            high = float(r["最高"])
            low = float(r["最低"])
            volume = float(r["成交量"])
        except (KeyError, ValueError, TypeError):
            continue
        if not np.isfinite(close) or close <= 0:
            continue
        out[code] = {
            "date": today, "open": open_, "high": high, "low": low,
            "close": close, "volume": volume,
        }
    return out


def _fetch_spot_hk() -> dict[str, dict]:
    try:
        df = ak.stock_hk_spot_em()
    except Exception as e:
        logger.warning("HK spot fetch failed: %s", e)
        return {}
    if df is None or df.empty:
        return {}
    today = _last_trading_day()
    out: dict[str, dict] = {}
    for _, r in df.iterrows():
        try:
            code = _normalize_hk(str(r["代码"]))
            close = float(r["最新价"])
            open_ = float(r["今开"])
            high = float(r["最高"])
            low = float(r["最低"])
            volume = float(r["成交量"])
        except (KeyError, ValueError, TypeError):
            continue
        if not np.isfinite(close) or close <= 0:
            continue
        out[code] = {
            "date": today, "open": open_, "high": high, "low": low,
            "close": close, "volume": volume,
        }
    return out


def _fetch_spot_us() -> dict[str, dict]:
    try:
        df = ak.stock_us_spot_em()
    except Exception as e:
        logger.warning("US spot fetch failed: %s", e)
        return {}
    if df is None or df.empty:
        return {}
    today = _last_trading_day()
    out: dict[str, dict] = {}
    for _, r in df.iterrows():
        try:
            # 美股 spot 的代码列可能是 "代码" (纯 ticker) 或带市场前缀
            code_raw = str(r.get("代码", "")).strip()
            if not code_raw:
                continue
            # 去掉可能的 "105." / "106." 前缀
            code = code_raw.split(".")[-1].upper()
            close = float(r["最新价"])
            open_ = float(r["今开"])
            high = float(r["最高"])
            low = float(r["最低"])
            volume = float(r.get("成交量", 0) or 0)
        except (KeyError, ValueError, TypeError):
            continue
        if not np.isfinite(close) or close <= 0:
            continue
        out[code] = {
            "date": today, "open": open_, "high": high, "low": low,
            "close": close, "volume": volume,
        }
    return out


SPOT_FETCHER: dict[Market, Any] = {
    "a": _fetch_spot_a,
    "hk": _fetch_spot_hk,
    "us": _fetch_spot_us,
    "themes": _fetch_spot_us,  # 主题股全部美股, 共享 US spot 端
}


def _fetch_spot_lookup(market: Market) -> dict[str, dict]:
    _validate_market(market)
    return SPOT_FETCHER[market]()


# ---- 市场专用 Fetcher ---------------------------------------------------

class _BaseFetcher:
    market: Market = "a"

    def _append_spot(self, cached: pd.DataFrame, spot_today: dict) -> pd.DataFrame | None:
        if not spot_today:
            return None
        new_row = pd.DataFrame([spot_today])
        new_row["date"] = pd.to_datetime(new_row["date"])
        combined = pd.concat([cached, new_row], ignore_index=True)
        combined = combined.drop_duplicates(subset="date", keep="last")
        combined = combined.sort_values("date").reset_index(drop=True)
        return combined.tail(CACHE_ROWS).reset_index(drop=True)

    def get_daily(
        self,
        code: str,
        days: int = LOOKBACK_DAYS,
        spot_today: dict | None = None,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        cached = _cache_load(code, self.market)
        p = _cache_path(code, self.market)
        # 1. 新鲜缓存直接用
        if (
            not force_refresh
            and cached is not None
            and not cached.empty
            and p.exists()
            and (time.time() - p.stat().st_mtime) < CACHE_FRESH_SECONDS
        ):
            return cached.tail(days).reset_index(drop=True)

        # 2. 缓存过期但仍可复用 + 有 spot 数据
        today = _last_trading_day()
        if cached is not None and not cached.empty and spot_today is not None:
            last_date = pd.to_datetime(cached["date"]).max().normalize()
            if (today - last_date).days <= STALE_BACKFILL_DAYS:
                merged = self._append_spot(cached, spot_today)
                if merged is not None:
                    _cache_store(code, merged, self.market)
                    return merged.tail(days).reset_index(drop=True)

        # 3. 全量回源
        df = self._fetch_full(code)
        if df is None or df.empty:
            return cached.tail(days).reset_index(drop=True) if cached is not None else pd.DataFrame()
        _cache_store(code, df.tail(CACHE_ROWS).reset_index(drop=True), self.market)
        return df.tail(days).reset_index(drop=True)

    def _fetch_full(self, code: str) -> pd.DataFrame | None:
        raise NotImplementedError


class AShareFetcher(_BaseFetcher):
    """基于 akshare 新浪源的 A 股实现."""
    market: Market = "a"

    def get_stock_list(self) -> pd.DataFrame:
        df = ak.stock_info_a_code_name()
        df = df.rename(columns={"code": "code", "name": "name"})
        df["code"] = df["code"].astype(str).str.zfill(6)
        return df[["code", "name"]]

    def _fetch_full(self, code: str) -> pd.DataFrame | None:
        try:
            symbol = _prefix_symbol_a(code)
            raw = ak.stock_zh_a_daily(symbol=symbol, adjust="qfq")
        except Exception as e:
            logger.debug("A daily fetch failed %s: %s", code, e)
            return None
        if raw is None or raw.empty:
            return None
        raw["date"] = pd.to_datetime(raw["date"])
        return raw[["date", "open", "high", "low", "close", "volume"]].reset_index(drop=True)

    def get_index_daily(self, symbol: str | None = None,
                        days: int = INDEX_LOOKBACK_DAYS) -> pd.DataFrame:
        symbol = symbol or INDEX_SYMBOL["a"]
        raw = ak.stock_zh_index_daily(symbol=symbol)
        if raw is None or raw.empty:
            return pd.DataFrame()
        raw = raw.tail(days).reset_index(drop=True)
        raw["date"] = pd.to_datetime(raw["date"])
        return raw[["date", "open", "high", "low", "close", "volume"]]


class HKFetcher(_BaseFetcher):
    """港股实现 (akshare)."""
    market: Market = "hk"

    def get_stock_list(self) -> pd.DataFrame:
        return _load_universe_json("hstech.json")

    def _fetch_full(self, code: str) -> pd.DataFrame | None:
        sym = _normalize_hk(code)
        try:
            raw = ak.stock_hk_daily(symbol=sym, adjust="qfq")
        except Exception as e:
            logger.debug("HK daily fetch failed %s: %s", code, e)
            try:
                raw = ak.stock_hk_daily(symbol=sym)
            except Exception as e2:
                logger.debug("HK daily fetch fallback failed %s: %s", code, e2)
                return None
        if raw is None or raw.empty:
            return None
        raw = raw.rename(columns={c: c.lower() for c in raw.columns})
        raw["date"] = pd.to_datetime(raw["date"])
        keep = [c for c in ["date", "open", "high", "low", "close", "volume"] if c in raw.columns]
        return raw[keep].sort_values("date").reset_index(drop=True)

    def get_index_daily(self, symbol: str | None = None,
                        days: int = INDEX_LOOKBACK_DAYS) -> pd.DataFrame:
        symbol = symbol or INDEX_SYMBOL["hk"]
        raw = None
        try:
            raw = ak.stock_hk_index_daily_sina(symbol=symbol)
        except Exception as e:
            logger.debug("HK index sina failed %s: %s", symbol, e)
            try:
                raw = ak.stock_hk_index_daily_em(symbol=symbol)
                if raw is not None and "latest" in raw.columns:
                    raw = raw.rename(columns={"latest": "close"})
            except Exception as e2:
                logger.warning("HK index fetch failed %s: %s", symbol, e2)
                return pd.DataFrame()
        if raw is None or raw.empty:
            return pd.DataFrame()
        raw["date"] = pd.to_datetime(raw["date"])
        for col in ("open", "high", "low", "close", "volume"):
            if col not in raw.columns:
                raw[col] = np.nan
        raw = raw.tail(days).reset_index(drop=True)
        return raw[["date", "open", "high", "low", "close", "volume"]]


class USFetcher(_BaseFetcher):
    """美股实现 (akshare)."""
    market: Market = "us"

    def get_stock_list(self) -> pd.DataFrame:
        return _load_universe_json("russell1000_growth.json")

    def _fetch_full(self, code: str) -> pd.DataFrame | None:
        sym = _normalize_us(code)
        try:
            raw = ak.stock_us_daily(symbol=sym, adjust="qfq")
        except Exception as e:
            logger.debug("US daily fetch failed %s: %s", code, e)
            try:
                raw = ak.stock_us_daily(symbol=sym)
            except Exception as e2:
                logger.debug("US daily fetch fallback failed %s: %s", code, e2)
                return None
        if raw is None or raw.empty:
            return None
        raw = raw.rename(columns={c: c.lower() for c in raw.columns})
        raw["date"] = pd.to_datetime(raw["date"])
        keep = [c for c in ["date", "open", "high", "low", "close", "volume"] if c in raw.columns]
        return raw[keep].sort_values("date").reset_index(drop=True)

    def get_index_daily(self, symbol: str | None = None,
                        days: int = INDEX_LOOKBACK_DAYS) -> pd.DataFrame:
        symbol = symbol or INDEX_SYMBOL["us"]
        try:
            raw = ak.index_us_stock_sina(symbol=symbol)
        except Exception as e:
            logger.warning("US index fetch failed %s: %s", symbol, e)
            return pd.DataFrame()
        if raw is None or raw.empty:
            return pd.DataFrame()
        raw = raw.rename(columns={c: c.lower() for c in raw.columns})
        raw["date"] = pd.to_datetime(raw["date"])
        for col in ("open", "high", "low", "close", "volume"):
            if col not in raw.columns:
                raw[col] = np.nan
        raw = raw.tail(days).reset_index(drop=True)
        return raw[["date", "open", "high", "low", "close", "volume"]]


class ThemesFetcher(USFetcher):
    """主题股: 9 大主题成分池, 全部美股, 复用 US 接口."""
    market: Market = "themes"

    def get_stock_list(self) -> pd.DataFrame:
        return _load_universe_json("themes.json")


# 向后兼容: 旧名字指向 A 股 Fetcher
AkShareFetcher = AShareFetcher


def make_fetcher(market: Market) -> _BaseFetcher:
    _validate_market(market)
    if market == "a":
        return AShareFetcher()
    if market == "hk":
        return HKFetcher()
    if market == "themes":
        return ThemesFetcher()
    return USFetcher()


# ---- 股票池过滤 ---------------------------------------------------------

def filter_main_board(df: pd.DataFrame) -> pd.DataFrame:
    """仅用于 A 股: 剔除 ST/*ST, 非主板代码, 空名."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["code", "name"])
    df = df.dropna(subset=["code", "name"]).copy()
    df["code"] = df["code"].astype(str).str.zfill(6)
    mask_main = df["code"].str.startswith(MAIN_BOARD_PREFIXES)
    mask_exclude = ~df["code"].str.startswith(EXCLUDE_PREFIXES)
    mask_not_st = ~df["name"].str.contains("ST", case=False, na=False)
    return df[mask_main & mask_exclude & mask_not_st].reset_index(drop=True)


def get_universe(market: Market, fetcher: _BaseFetcher | None = None) -> pd.DataFrame:
    """返回指定市场的扫描池 (code, name)."""
    _validate_market(market)
    fetcher = fetcher or make_fetcher(market)
    raw = fetcher.get_stock_list()
    if market == "a":
        return filter_main_board(raw)
    return raw.reset_index(drop=True)


# ---- HMM 市场择时 -------------------------------------------------------

@dataclass
class MarketRegime:
    state: int
    label: str
    proceed: bool
    probabilities: list[float] = field(default_factory=list)


def detect_market_regime(index_df: pd.DataFrame) -> MarketRegime:
    """使用 GaussianHMM 判定当前市场状态."""
    try:
        from hmmlearn.hmm import GaussianHMM
    except ImportError as e:
        raise RuntimeError("请安装 hmmlearn: pip install hmmlearn") from e

    if index_df is None or len(index_df) < 60:
        raise ValueError("指数数据不足, 无法拟合 HMM")

    df = index_df.copy().sort_values("date").reset_index(drop=True)
    df["log_ret"] = np.log(df["close"] / df["close"].shift(1))
    df["vol5"] = df["log_ret"].rolling(5).var()
    df = df.dropna().reset_index(drop=True)

    X = df[["log_ret", "vol5"]].to_numpy()

    model = GaussianHMM(
        n_components=HMM_STATES,
        covariance_type="full",
        n_iter=500,
        random_state=42,
    )
    model.fit(X)
    hidden_states = model.predict(X)
    current_raw_state = int(hidden_states[-1])

    mean_returns = model.means_[:, 0]
    order = np.argsort(mean_returns)
    raw_to_canon = {int(order[0]): 0, int(order[1]): 1, int(order[2]): 2}
    current_state = raw_to_canon[current_raw_state]

    post = model.predict_proba(X)[-1]
    canon_probs = [0.0, 0.0, 0.0]
    for raw_idx, p in enumerate(post):
        canon_probs[raw_to_canon[int(raw_idx)]] = float(p)

    return MarketRegime(
        state=current_state,
        label=STATE_LABELS[current_state],
        proceed=current_state != 0,
        probabilities=canon_probs,
    )


# ---- 技术指标 -----------------------------------------------------------

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().sort_values("date").reset_index(drop=True)
    for p in (5, 10, 20):
        df[f"ma{p}"] = df["close"].rolling(p).mean()

    mid = df["close"].rolling(20).mean()
    std = df["close"].rolling(20).std(ddof=0)
    df["boll_mid"] = mid
    df["boll_upper"] = mid + 2 * std
    df["boll_lower"] = mid - 2 * std

    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["dif"] = ema12 - ema26
    df["dea"] = df["dif"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = (df["dif"] - df["dea"]) * 2

    df["vol_ma5"] = df["volume"].rolling(5).mean()

    def _fk(period: int) -> pd.Series:
        ll = df["low"].rolling(period).min()
        hh = df["high"].rolling(period).max()
        denom = (hh - ll).replace(0, np.nan)
        return 100 * (df["close"] - ll) / denom

    df["mf_inter"] = _fk(31).rolling(5).mean()
    df["mf_near"] = _fk(3).rolling(2).mean()
    low_s, high_s = df["low"], df["high"]
    min1 = pd.concat([low_s, low_s.shift(1)], axis=1).min(axis=1)
    min2 = pd.concat(
        [low_s, low_s.shift(1), low_s.shift(2), low_s.shift(3)], axis=1
    ).min(axis=1)
    max1 = pd.concat(
        [high_s, high_s.shift(1), high_s.shift(2), high_s.shift(3)], axis=1
    ).max(axis=1)
    denom_m = (max1 - min2).replace(0, np.nan)
    df["mf_mom"] = 100 * (df["close"] - min1) / denom_m
    return df


# ---- 多因子打分 ---------------------------------------------------------

@dataclass
class StockScore:
    code: str
    name: str
    score: float
    signals: list[str]


@dataclass
class ScoreConfig:
    bullish_alignment_enabled: bool = True
    bullish_alignment_weight: float = 2.5

    boll_breakout_enabled: bool = True
    boll_breakout_weight: float = 3.0

    macd_cross_enabled: bool = True
    macd_cross_weight: float = 2.0

    volume_burst_enabled: bool = True
    volume_burst_weight: float = 2.5
    volume_burst_multiplier: float = 1.5

    mf_bottom_cluster_enabled: bool = True
    mf_bottom_cluster_weight: float = 3.5
    mf_bottom_cluster_threshold: float = 20.0

    score_threshold: float = 7.5
    skip_regime_check: bool = False

    @classmethod
    def from_dict(cls, d: dict | None) -> "ScoreConfig":
        if not d:
            return cls()
        valid = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in d.items() if k in valid}
        return cls(**filtered)


def score_stock(
    df: pd.DataFrame,
    code: str,
    name: str,
    config: ScoreConfig | None = None,
) -> StockScore | None:
    cfg = config or ScoreConfig()
    if df is None or len(df) < 30:
        return None
    ind = compute_indicators(df)
    if len(ind) < 3:
        return None
    last = ind.iloc[-1]
    prev = ind.iloc[-2]
    prev2 = ind.iloc[-3]

    required = ["ma5", "ma10", "ma20", "boll_upper", "dif", "dea", "vol_ma5"]
    if ind[required].iloc[-1].isna().any() or ind[required].iloc[-2].isna().any():
        return None

    score = 0.0
    signals: list[str] = []

    if cfg.bullish_alignment_enabled and \
            (last["ma5"] > last["ma10"] > last["ma20"]) and (last["ma5"] > prev["ma5"]):
        score += cfg.bullish_alignment_weight
        signals.append("均线多头")

    if cfg.boll_breakout_enabled and last["close"] > last["boll_upper"]:
        score += cfg.boll_breakout_weight
        signals.append("BOLL突破")

    if cfg.macd_cross_enabled:
        cross_today = (last["dif"] > last["dea"]) and (prev["dif"] <= prev["dea"])
        cross_yest = (prev["dif"] > prev["dea"]) and (prev2["dif"] <= prev2["dea"])
        if cross_today or cross_yest:
            score += cfg.macd_cross_weight
            signals.append("MACD金叉")

    if cfg.volume_burst_enabled and last["vol_ma5"] \
            and last["volume"] > last["vol_ma5"] * cfg.volume_burst_multiplier:
        score += cfg.volume_burst_weight
        signals.append("量能爆发")

    if cfg.mf_bottom_cluster_enabled:
        mi, mn, mm = last.get("mf_inter"), last.get("mf_near"), last.get("mf_mom")
        thr = cfg.mf_bottom_cluster_threshold
        if (
            pd.notna(mi) and pd.notna(mn) and pd.notna(mm)
            and mi <= thr and mn <= thr and mm <= thr
        ):
            score += cfg.mf_bottom_cluster_weight
            signals.append("MF底部共振")

    return StockScore(code=code, name=name, score=round(score, 2), signals=signals)


# ---- 主流程 -------------------------------------------------------------

def _scan_one(
    code: str,
    name: str,
    market: Market,
    config: ScoreConfig | None = None,
) -> StockScore | None:
    try:
        df = load_cached_daily(code, LOOKBACK_DAYS, market)
        if df is None or df.empty or len(df) < MIN_LISTING_DAYS:
            return None
        last_date = pd.to_datetime(df["date"].iloc[-1])
        if (datetime.now() - last_date).days > 10:
            return None
        return score_stock(df, code, name, config)
    except Exception as e:
        logger.debug("scan %s/%s failed: %s", market, code, e)
        return None


def run_scan(
    market: Market = "a",
    fetcher: StockDataFetcher | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    universe_limit: int | None = None,
    config: ScoreConfig | None = None,
) -> tuple[MarketRegime, list[StockScore]]:
    """纯缓存扫描. 假定 warm_cache 已运行, 磁盘上有最新 pkl."""
    _validate_market(market)
    fetcher = fetcher or make_fetcher(market)
    cfg = config or ScoreConfig()

    index_df = fetcher.get_index_daily(INDEX_SYMBOL[market], INDEX_LOOKBACK_DAYS)
    regime = detect_market_regime(index_df)
    if not regime.proceed and not cfg.skip_regime_check:
        return regime, []

    universe = get_universe(market, fetcher)
    if universe_limit:
        universe = universe.head(universe_limit)
    logger.info("[%s] 候选池: %d", MARKET_LABEL[market], len(universe))

    results: list[StockScore] = []
    total = len(universe)
    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(_scan_one, row["code"], row["name"], market, cfg): row["code"]
            for _, row in universe.iterrows()
        }
        for fut in as_completed(futures):
            done += 1
            res = fut.result()
            if res and res.score >= cfg.score_threshold:
                results.append(res)
    logger.info("[%s] scan complete: %d/%d in %.1fs, hits=%d",
                MARKET_LABEL[market], done, total, time.time() - t0, len(results))

    results.sort(key=lambda r: r.score, reverse=True)
    return regime, results


# ---- 每日定时: 增量刷新缓存 --------------------------------------------

def _warm_one(
    fetcher: _BaseFetcher,
    code: str,
    spot_row: dict | None,
) -> bool:
    try:
        df = fetcher.get_daily(
            code,
            LOOKBACK_DAYS,
            spot_today=spot_row,
            force_refresh=True,
        )
        return df is not None and not df.empty
    except Exception as e:
        logger.debug("warm %s/%s failed: %s", fetcher.market, code, e)
        return False


def warm_cache(market: Market = "a", max_workers: int = DEFAULT_MAX_WORKERS) -> dict:
    """按市场增量刷新缓存. 拉取 spot 追加今日行到每只股票缓存."""
    _validate_market(market)
    fetcher = make_fetcher(market)
    t0 = time.time()

    logger.info("[%s] warm: 拉取候选池 ...", MARKET_LABEL[market])
    universe = get_universe(market, fetcher)
    logger.info("[%s] warm: 候选 %d 只", MARKET_LABEL[market], len(universe))

    logger.info("[%s] warm: 拉取 spot ...", MARKET_LABEL[market])
    spot_map = _fetch_spot_lookup(market)
    logger.info("[%s] warm: spot 返回 %d 只", MARKET_LABEL[market], len(spot_map))
    force_full_refresh = not spot_map
    if force_full_refresh:
        logger.warning(
            "[%s] warm: spot 为空，改为全量回源刷新缓存，避免把接口异常误判为非交易日",
            MARKET_LABEL[market],
        )

    ok, fail = 0, 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(
                _warm_one,
                fetcher,
                row["code"],
                None if force_full_refresh else spot_map.get(_spot_key(row["code"], market)),
            ): row["code"]
            for _, row in universe.iterrows()
        }
        for fut in as_completed(futures):
            if fut.result():
                ok += 1
            else:
                fail += 1
            if (ok + fail) % 300 == 0:
                logger.info("[%s] warm progress: %d/%d (ok=%d fail=%d, %.1fs)",
                            MARKET_LABEL[market], ok + fail, len(universe), ok, fail, time.time() - t0)

    dt = round(time.time() - t0, 1)
    logger.info("[%s] warm complete: ok=%d fail=%d universe=%d in %ss",
                MARKET_LABEL[market], ok, fail, len(universe), dt)
    return {
        "market": market,
        "ok": ok,
        "fail": fail,
        "universe": len(universe),
        "seconds": dt,
        "mode": "full_refresh" if force_full_refresh else "spot_incremental",
    }


def _spot_key(code: str, market: Market) -> str:
    """将 universe 里的 code 转换成 spot_map 的 key 格式."""
    if market == "a":
        return str(code).zfill(6)
    if market == "hk":
        return _normalize_hk(code)
    return _normalize_us(code)


# ---- 报告格式化 ---------------------------------------------------------

def format_report(
    regime: MarketRegime,
    results: list[StockScore],
    date: str | None = None,
    market: Market = "a",
) -> str:
    date = date or datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"📅 日期：{date}  市场：{MARKET_LABEL[market]}",
        f"🚦 宏观环境：HMM判定为 [{regime.label}]",
    ]
    if not regime.proceed:
        lines.append("⛔ 当前市场环境恶劣，停止交易")
        return "\n".join(lines)

    lines.append(f"🎯 选股结果（评分 >= {SCORE_THRESHOLD}）：")
    lines.append("")
    if not results:
        lines.append("(本日无符合条件的个股)")
        return "\n".join(lines)
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. [{r.code}] [{r.name}] - 综合评分：{r.score:.1f}")
        lines.append(f"   🔥 触发信号：{', '.join(r.signals) if r.signals else '无'}")
    return "\n".join(lines)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    regime, results = run_scan(market="a")
    print(format_report(regime, results, market="a"))


if __name__ == "__main__":
    main()
