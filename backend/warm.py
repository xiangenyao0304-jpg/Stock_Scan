"""每日定时入口: 按市场增量刷新日线缓存, 并重跑默认参数扫描 (动能 + HMM).

CLI:
    python warm.py --market a        # A 股 (默认)
    python warm.py --market hk       # 港股
    python warm.py --market us       # 美股
    python warm.py --market themes   # 主题股 (9 大主题成分池)
    python warm.py --market all      # 依次跑四个市场

由 launchd 每日按各市场收盘时间触发, 结果落盘到 RESULTS_DIR/{kind}_{market}.json
供前端首屏直接读取.
非交易日 spot 为空时只会跳过 warm, 不会重跑扫描.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime

from scanner_hmm import (
    MARKETS,
    Market,
    ScoreConfig,
    format_report,
    run_scan,
    save_result,
    warm_cache,
)


def _refresh_default_scans(market: Market) -> dict:
    """用默认参数重跑两种扫描, 结果落盘. 失败不阻塞整体."""
    from main import MomentumConfig, _run_momentum_scan

    out: dict = {}

    try:
        momentum = _run_momentum_scan(MomentumConfig(), market)
        save_result("momentum_default", momentum, market)
        out["momentum_hits"] = len(momentum)
        logging.info("[%s] momentum default cached: %d hits", market, len(momentum))
    except Exception:
        logging.exception("[%s] momentum default scan failed", market)
        out["momentum_error"] = True

    try:
        regime, results = run_scan(market=market, config=ScoreConfig())
        payload = {
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
        save_result("hmm_default", payload, market)
        out["hmm_hits"] = len(results)
        logging.info("[%s] hmm default cached: %d hits", market, len(results))
    except Exception:
        logging.exception("[%s] hmm default scan failed", market)
        out["hmm_error"] = True

    return out


def _run_one(market: Market) -> dict:
    warm_out = warm_cache(market)
    scan_out: dict = {}
    if warm_out.get("reason") != "no_spot":
        scan_out = _refresh_default_scans(market)
    return {"warm": warm_out, "scan": scan_out}


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    parser = argparse.ArgumentParser(description="warm stocks scan cache + rerun default scans")
    parser.add_argument(
        "--market", "-m",
        default="a",
        choices=[*MARKETS, "all"],
        help="target market (a/hk/us/themes/all); default 'a'",
    )
    args = parser.parse_args()

    if args.market == "all":
        report = {m: _run_one(m) for m in MARKETS}
    else:
        report = {args.market: _run_one(args.market)}

    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
