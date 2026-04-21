"""
多市场动能扫盘雷达 - 后端服务 (A 股 / 港股 / 美股)
FastAPI + AkShare
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Literal

import akshare as ak
import numpy as np
import pandas as pd
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("scan-radar")


# =========================================================================
#   Config
# =========================================================================

LOOKBACK_DAYS = 150          # 拉取天数（用于指标预热）
EVAL_WINDOW = 40             # 评估窗口
MAX_WORKERS = 24             # 并发线程 (纯缓存扫描, 可开高)
REQUEST_TIMEOUT = 15
BBAND_LOW_QUANTILE = 0.50    # 布林带带宽"近半年低位区间"的分位数

Market = Literal["a", "hk", "us", "themes"]
MARKETS: tuple[Market, ...] = ("a", "hk", "us", "themes")


def _validate_market(value: str) -> Market:
    if value not in MARKETS:
        raise HTTPException(status_code=400, detail=f"unknown market: {value!r}")
    return value  # type: ignore[return-value]


# =========================================================================
#   FastAPI app
# =========================================================================

app = FastAPI(title="多市场动能扫盘雷达 API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================================
#   Schemas
# =========================================================================

SignalType = Literal["看涨", "看跌"]


class ScanItem(BaseModel):
    code: str
    name: str
    price: float
    signal_type: SignalType


class KlineBar(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    ma5: float | None = None
    ma20: float | None = None
    ma50: float | None = None
    ma200: float | None = None
    upper_band: float | None = None
    middle_band: float | None = None
    lower_band: float | None = None
    macd_dif: float | None = None
    macd_dea: float | None = None
    macd_hist: float | None = None
    smf_intermediate: float | None = None
    smf_short: float | None = None
    smf_momentum: float | None = None
    mf_bull_cluster: bool = False
    mf_bear_cluster: bool = False
    mf_bull_confirm: bool = False
    mf_bear_confirm: bool = False


class KlineDivergence(BaseModel):
    kind: Literal["bull", "bear"]
    from_time: str
    to_time: str
    from_value: float
    to_value: float
    from_price: float
    to_price: float


class KlineResponse(BaseModel):
    bars: list[KlineBar]
    divergences: list[KlineDivergence]


class MomentumConfig(BaseModel):
    bull_enabled: bool = True
    bear_enabled: bool = True
    trend_enabled: bool = True
    squeeze_enabled: bool = True
    price_enabled: bool = True
    volume_enabled: bool = True
    macd_enabled: bool = True
    bb_low_quantile: float = Field(default=0.50, ge=0.05, le=0.95)
    bull_trend_ratio: float = Field(default=0.55, ge=0.1, le=1.0)
    bear_trend_ratio: float = Field(default=0.45, ge=0.1, le=1.0)
    price_above_mid_tolerance: float = Field(default=0.98, ge=0.8, le=1.1)
    bull_volume_ratio: float = Field(default=0.90, ge=0.1, le=3.0)
    macd_zero_tolerance: float = Field(default=0.03, ge=0.001, le=0.2)
    bear_volume_ratio: float = Field(default=0.95, ge=0.1, le=3.0)


class HmmScanConfig(BaseModel):
    bullish_alignment_enabled: bool = True
    bullish_alignment_weight: float = Field(default=2.5, ge=0.0, le=10.0)
    boll_breakout_enabled: bool = True
    boll_breakout_weight: float = Field(default=3.0, ge=0.0, le=10.0)
    macd_cross_enabled: bool = True
    macd_cross_weight: float = Field(default=2.0, ge=0.0, le=10.0)
    volume_burst_enabled: bool = True
    volume_burst_weight: float = Field(default=2.5, ge=0.0, le=10.0)
    volume_burst_multiplier: float = Field(default=1.5, ge=1.0, le=5.0)
    mf_bottom_cluster_enabled: bool = True
    mf_bottom_cluster_weight: float = Field(default=3.5, ge=0.0, le=10.0)
    mf_bottom_cluster_threshold: float = Field(default=20.0, ge=5.0, le=50.0)
    score_threshold: float = Field(default=7.5, ge=0.0, le=20.0)
    skip_regime_check: bool = False
    limit: int | None = Field(default=None, ge=1, le=5000)


# =========================================================================
#   数据拉取（含重试） — 仅用于 K 线缓存未命中时的兜底
# =========================================================================

def _prefixed_a(code: str) -> str:
    c = code.strip()
    if c.startswith(("sh", "sz", "bj")):
        return c
    if c.startswith(("6", "9")):
        return f"sh{c}"
    if c.startswith(("0", "3", "2")):
        return f"sz{c}"
    if c.startswith(("4", "8")):
        return f"bj{c}"
    return f"sh{c}"


def _normalize_hk(code: str) -> str:
    s = str(code).strip().lstrip("0")
    if not s:
        s = "0"
    return s.zfill(5)


def _normalize_us(code: str) -> str:
    return str(code).strip().upper()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def fetch_stock_hist(code: str, market: Market = "a", days: int = LOOKBACK_DAYS) -> pd.DataFrame:
    """按市场调度的日线拉取. 仅作为 K 线接口缓存未命中时的兜底."""
    if market == "a":
        end = datetime.today()
        start = end - timedelta(days=int(days * 1.8) + 30)
        df = ak.stock_zh_a_daily(
            symbol=_prefixed_a(code),
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="qfq",
        )
    elif market == "hk":
        try:
            df = ak.stock_hk_daily(symbol=_normalize_hk(code), adjust="qfq")
        except Exception:
            df = ak.stock_hk_daily(symbol=_normalize_hk(code))
    else:  # us 或 themes (主题股全部为美股)
        try:
            df = ak.stock_us_daily(symbol=_normalize_us(code), adjust="qfq")
        except Exception:
            df = ak.stock_us_daily(symbol=_normalize_us(code))

    if df is None or df.empty:
        raise RuntimeError(f"空数据: {market}/{code}")

    df = df.rename(columns={c: c.lower() for c in df.columns})
    keep = ["date", "open", "close", "high", "low", "volume"]
    missing = [c for c in keep if c not in df.columns]
    if missing:
        raise RuntimeError(f"缺少列 {missing}: {market}/{code}")
    df = df[keep].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df = df.tail(days).reset_index(drop=True)
    return df


# =========================================================================
#   指标计算
# =========================================================================

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """追加 MA20/MA50、布林带(20,2)、MACD(12,26,9) 列。"""
    out = df.copy()
    close = out["close"]

    out["ma5"] = close.rolling(window=5, min_periods=5).mean()
    out["ma20"] = close.rolling(window=20, min_periods=20).mean()
    out["ma50"] = close.rolling(window=50, min_periods=50).mean()
    out["ma200"] = close.rolling(window=200, min_periods=1).mean()

    mid = close.rolling(window=20, min_periods=20).mean()
    std = close.rolling(window=20, min_periods=20).std(ddof=0)
    out["middle_band"] = mid
    out["upper_band"] = mid + 2 * std
    out["lower_band"] = mid - 2 * std
    out["bb_width"] = (out["upper_band"] - out["lower_band"]) / mid.replace(0, np.nan)

    ema_fast = close.ewm(span=12, adjust=False).mean()
    ema_slow = close.ewm(span=26, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=9, adjust=False).mean()
    out["macd_dif"] = dif
    out["macd_dea"] = dea
    out["macd_hist"] = (dif - dea) * 2

    def _fast_k(period: int) -> pd.Series:
        ll = out["low"].rolling(period).min()
        hh = out["high"].rolling(period).max()
        denom = (hh - ll).replace(0, np.nan)
        return 100 * (close - ll) / denom

    out["smf_intermediate"] = _fast_k(31).rolling(5).mean()
    out["smf_short"] = _fast_k(3).rolling(2).mean()

    low_s, high_s = out["low"], out["high"]
    min1 = pd.concat([low_s, low_s.shift(1)], axis=1).min(axis=1)
    min2 = pd.concat(
        [low_s, low_s.shift(1), low_s.shift(2), low_s.shift(3)], axis=1
    ).min(axis=1)
    max1 = pd.concat(
        [high_s, high_s.shift(1), high_s.shift(2), high_s.shift(3)], axis=1
    ).max(axis=1)
    denom_m = (max1 - min2).replace(0, np.nan)
    out["smf_momentum"] = 100 * (close - min1) / denom_m

    inter_s = out["smf_intermediate"]
    near_s = out["smf_short"]
    bull_cluster = (inter_s <= 20) & (near_s <= 20)
    bear_cluster = (inter_s >= 80) & (near_s >= 80)
    out["mf_bull_cluster"] = bull_cluster.fillna(False)
    out["mf_bear_cluster"] = bear_cluster.fillna(False)

    bull_cluster_recent = bull_cluster.rolling(10, min_periods=1).max().fillna(0).astype(bool)
    bear_cluster_recent = bear_cluster.rolling(10, min_periods=1).max().fillna(0).astype(bool)
    high_prev = out["high"].shift(1).rolling(3, min_periods=1).max()
    low_prev = out["low"].shift(1).rolling(3, min_periods=1).min()
    out["mf_bull_confirm"] = (
        bull_cluster_recent & (~bull_cluster) & (close > high_prev)
    ).fillna(False)
    out["mf_bear_confirm"] = (
        bear_cluster_recent & (~bear_cluster) & (close < low_prev)
    ).fillna(False)

    return out


def detect_mf_divergences(df: pd.DataFrame, left: int = 2, right: int = 2) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    n = len(df)
    if n < left + right + 2:
        return []

    near = df["smf_short"]
    high = df["high"]
    low = df["low"]
    date = df["date"]

    pivots_high: list[int] = []
    pivots_low: list[int] = []
    for i in range(left, n - right):
        window_near = near.iloc[i - left : i + right + 1]
        if pd.isna(near.iloc[i]):
            continue
        if near.iloc[i] == window_near.max() and near.iloc[i] > near.iloc[i - 1]:
            pivots_high.append(i)
        if near.iloc[i] == window_near.min() and near.iloc[i] < near.iloc[i - 1]:
            pivots_low.append(i)

    out: list[dict[str, Any]] = []
    if len(pivots_high) >= 2:
        a, b = pivots_high[-2], pivots_high[-1]
        if high.iloc[b] > high.iloc[a] and near.iloc[b] < near.iloc[a]:
            out.append({
                "kind": "bear",
                "from_time": date.iloc[a].strftime("%Y-%m-%d"),
                "to_time": date.iloc[b].strftime("%Y-%m-%d"),
                "from_value": float(round(near.iloc[a], 4)),
                "to_value": float(round(near.iloc[b], 4)),
                "from_price": float(round(high.iloc[a], 4)),
                "to_price": float(round(high.iloc[b], 4)),
            })
    if len(pivots_low) >= 2:
        a, b = pivots_low[-2], pivots_low[-1]
        if low.iloc[b] < low.iloc[a] and near.iloc[b] > near.iloc[a]:
            out.append({
                "kind": "bull",
                "from_time": date.iloc[a].strftime("%Y-%m-%d"),
                "to_time": date.iloc[b].strftime("%Y-%m-%d"),
                "from_value": float(round(near.iloc[a], 4)),
                "to_value": float(round(near.iloc[b], 4)),
                "from_price": float(round(low.iloc[a], 4)),
                "to_price": float(round(low.iloc[b], 4)),
            })
    return out


# =========================================================================
#   双向模型判定
# =========================================================================

def classify_signal(df: pd.DataFrame, cfg: MomentumConfig | None = None) -> SignalType | None:
    cfg = cfg or MomentumConfig()
    if len(df) < 120:
        return None

    recent = df.tail(EVAL_WINDOW).copy()
    last = df.iloc[-1]
    prev = df.iloc[-2]

    if recent[["ma20", "ma50", "middle_band", "macd_dif", "macd_dea"]].isna().any().any():
        return None

    chg = recent["close"].diff()
    up_vol = recent.loc[chg > 0, "volume"].sum()
    down_vol = recent.loc[chg < 0, "volume"].sum()

    bb_hist = df["bb_width"].tail(120).dropna()
    if bb_hist.empty:
        return None
    bb_low_threshold = bb_hist.quantile(cfg.bb_low_quantile)
    squeeze_val = bool(last["bb_width"] <= bb_low_threshold)
    squeeze = squeeze_val if cfg.squeeze_enabled else True

    ma20_above_ma50_ratio = float((recent["ma20"] > recent["ma50"]).mean())
    ma20_slope = recent["ma20"].iloc[-1] - recent["ma20"].iloc[-5]
    ma_dead_cross = bool(last["ma20"] < last["ma50"] and prev["ma20"] >= prev["ma50"])

    if cfg.bull_enabled:
        trend_bull = (ma20_above_ma50_ratio >= cfg.bull_trend_ratio) if cfg.trend_enabled else True
        price_above_mid = (
            last["close"] >= last["middle_band"] * cfg.price_above_mid_tolerance
        ) if cfg.price_enabled else True
        volume_ok = (up_vol >= down_vol * cfg.bull_volume_ratio) if cfg.volume_enabled else True
        if cfg.macd_enabled:
            macd_zero_zone = abs(last["macd_dif"]) <= last["close"] * cfg.macd_zero_tolerance
            macd_cross_up = last["macd_dif"] > last["macd_dea"]
            macd_ok = macd_zero_zone or macd_cross_up
        else:
            macd_ok = True
        if trend_bull and squeeze and price_above_mid and volume_ok and macd_ok:
            return "看涨"

    if cfg.bear_enabled:
        trend_bear = (
            ma20_slope < 0 or ma_dead_cross or ma20_above_ma50_ratio < cfg.bear_trend_ratio
        ) if cfg.trend_enabled else True
        price_under_mid = last["close"] < last["middle_band"]
        price_break_low = last["close"] < last["lower_band"]
        price_bear = (price_under_mid or price_break_low) if cfg.price_enabled else True
        macd_bear = (last["macd_dif"] < last["macd_dea"]) if cfg.macd_enabled else True
        if cfg.volume_enabled:
            down_days = recent[chg < 0]
            up_days = recent[chg > 0]
            volume_bear = (
                not down_days.empty
                and not up_days.empty
                and down_days["volume"].mean() >= up_days["volume"].mean() * cfg.bear_volume_ratio
            )
        else:
            volume_bear = True
        if trend_bear and squeeze and price_bear and macd_bear and volume_bear:
            return "看跌"

    return None


# =========================================================================
#   并发扫描
# =========================================================================

def scan_one(
    code: str,
    name: str,
    market: Market = "a",
    cfg: MomentumConfig | None = None,
) -> dict[str, Any] | None:
    """纯缓存扫描. 若缓存缺失则跳过该股票 (依赖 warm_cache 填充)."""
    try:
        from scanner_hmm import load_cached_daily
        df = load_cached_daily(code, LOOKBACK_DAYS, market)
        if df is None or df.empty or len(df) < 120:
            return None
        last_date = pd.to_datetime(df["date"].iloc[-1])
        if (datetime.now() - last_date).days > 10:
            return None
        df = compute_indicators(df)
        signal = classify_signal(df, cfg)
        if signal is None:
            return None
        return {
            "code": code,
            "name": name,
            "price": float(round(df["close"].iloc[-1], 2)),
            "signal_type": signal,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("扫描失败 %s/%s(%s): %s", market, code, name, exc)
        return None


# =========================================================================
#   Routes
# =========================================================================

@app.get("/")
def root():
    return {"service": "多市场动能扫盘雷达", "markets": list(MARKETS)}


def _run_momentum_scan(cfg: MomentumConfig, market: Market = "a") -> list[dict[str, Any]]:
    """纯缓存 + 指定市场全池动能扫盘."""
    from scanner_hmm import get_universe
    universe = get_universe(market)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(scan_one, row["code"], row["name"], market, cfg): row["code"]
            for _, row in universe.iterrows()
        }
        for fut in as_completed(futures):
            item = fut.result()
            if item:
                results.append(item)
    results.sort(key=lambda x: (x["signal_type"] != "看涨", x["code"]))
    logger.info("[%s] 扫描完成：%d / %d", market, len(results), len(universe))
    return results


_MOMENTUM_DEFAULT_DUMP = MomentumConfig().model_dump()


def _is_default_momentum(cfg: MomentumConfig) -> bool:
    return cfg.model_dump() == _MOMENTUM_DEFAULT_DUMP


@app.get("/api/scan", response_model=list[ScanItem])
def api_scan(market: str = Query("a")):
    """默认参数: 优先返回落盘结果, 缺失才即时扫描."""
    m = _validate_market(market)
    from scanner_hmm import load_result, save_result
    cached = load_result("momentum_default", m)
    if cached is not None:
        return cached
    result = _run_momentum_scan(MomentumConfig(), m)
    save_result("momentum_default", result, m)
    return result


@app.post("/api/scan", response_model=list[ScanItem])
def api_scan_post(
    cfg: MomentumConfig = Body(default_factory=MomentumConfig),
    market: str = Query("a"),
):
    m = _validate_market(market)
    from scanner_hmm import load_result, save_result
    if _is_default_momentum(cfg):
        cached = load_result("momentum_default", m)
        if cached is not None:
            return cached
    result = _run_momentum_scan(cfg, m)
    if _is_default_momentum(cfg):
        save_result("momentum_default", result, m)
    return result


@app.get("/api/kline", response_model=KlineResponse)
def api_kline(
    code: str = Query(..., min_length=1, max_length=16),
    market: str = Query("a"),
):
    m = _validate_market(market)
    from scanner_hmm import load_cached_daily
    try:
        df = load_cached_daily(code, LOOKBACK_DAYS, m)
        if df is None or len(df) < 60:
            df = fetch_stock_hist(code, market=m, days=LOOKBACK_DAYS)
        df = compute_indicators(df)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"数据拉取失败: {exc}") from exc

    def _num(v: Any) -> float | None:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        return float(round(v, 4))

    def _flag(v: Any) -> bool:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return False
        return bool(v)

    bars: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        bars.append({
            "time": row["date"].strftime("%Y-%m-%d"),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
            "ma5": _num(row.get("ma5")),
            "ma20": _num(row.get("ma20")),
            "ma50": _num(row.get("ma50")),
            "ma200": _num(row.get("ma200")),
            "upper_band": _num(row.get("upper_band")),
            "middle_band": _num(row.get("middle_band")),
            "lower_band": _num(row.get("lower_band")),
            "macd_dif": _num(row.get("macd_dif")),
            "macd_dea": _num(row.get("macd_dea")),
            "macd_hist": _num(row.get("macd_hist")),
            "smf_intermediate": _num(row.get("smf_intermediate")),
            "smf_short": _num(row.get("smf_short")),
            "smf_momentum": _num(row.get("smf_momentum")),
            "mf_bull_cluster": _flag(row.get("mf_bull_cluster")),
            "mf_bear_cluster": _flag(row.get("mf_bear_cluster")),
            "mf_bull_confirm": _flag(row.get("mf_bull_confirm")),
            "mf_bear_confirm": _flag(row.get("mf_bear_confirm")),
        })

    divergences = detect_mf_divergences(df)
    return {"bars": bars, "divergences": divergences}


def _run_hmm_scan(cfg: HmmScanConfig, market: Market = "a") -> dict[str, Any]:
    from scanner_hmm import ScoreConfig, format_report, run_scan

    score_cfg = ScoreConfig.from_dict(cfg.model_dump(exclude={"limit"}))
    try:
        regime, results = run_scan(market=market, universe_limit=cfg.limit, config=score_cfg)
    except Exception as e:
        logger.exception("HMM 扫描失败")
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "market": market,
        "regime": {
            "state": regime.state,
            "label": regime.label,
            "proceed": regime.proceed,
            "probabilities": regime.probabilities,
        },
        "results": [
            {"code": r.code, "name": r.name, "score": r.score, "signals": r.signals}
            for r in results
        ],
        "report": format_report(regime, results, market=market),
    }


_HMM_DEFAULT_DUMP = HmmScanConfig().model_dump()


def _is_default_hmm(cfg: HmmScanConfig) -> bool:
    return cfg.model_dump() == _HMM_DEFAULT_DUMP


@app.get("/api/hmm_scan")
def api_hmm_scan(
    market: str = Query("a"),
    limit: int | None = Query(None, ge=1, le=5000),
):
    """默认参数: 优先返回落盘结果. limit 仅用于调试."""
    m = _validate_market(market)
    from scanner_hmm import load_result, save_result
    if limit is None:
        cached = load_result("hmm_default", m)
        if cached is not None:
            return cached
    result = _run_hmm_scan(HmmScanConfig(limit=limit), m)
    if limit is None:
        save_result("hmm_default", result, m)
    return result


@app.post("/api/hmm_scan")
def api_hmm_scan_post(
    cfg: HmmScanConfig = Body(default_factory=HmmScanConfig),
    market: str = Query("a"),
):
    m = _validate_market(market)
    from scanner_hmm import load_result, save_result
    if _is_default_hmm(cfg):
        cached = load_result("hmm_default", m)
        if cached is not None:
            return cached
    result = _run_hmm_scan(cfg, m)
    if _is_default_hmm(cfg):
        save_result("hmm_default", result, m)
    return result


@app.post("/api/warm_cache")
def api_warm_cache(market: str = Query("a")):
    """手动触发指定市场缓存刷新."""
    m = _validate_market(market)
    from scanner_hmm import warm_cache
    try:
        return warm_cache(m)
    except Exception as e:
        logger.exception("warm_cache failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
