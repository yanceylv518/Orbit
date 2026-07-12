"""拉取 Binance 主网公共 K 线并缓存为 JSON（无需 API 密钥）。

用法：
  python backend/tools/fetch_klines.py --symbol BTCUSDT --interval 1h --days 90
输出：
  var/calibration/{symbol}_{interval}.json  （[[close_time_ms, close], ...]）
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.infrastructure.exchange.kline_feed import INTERVAL_MS, BinanceKlineFeed  # noqa: E402


def fetch_history(symbol: str, interval: str, days: int, *, spot_mirror: bool = False) -> list[list[float]]:
    """spot_mirror=True 时走 data-api.binance.vision 现货公共镜像。

    合约主网 fapi 对部分数据中心 IP 返回 451；π̂/几何标定只需要收盘价形态，
    现货与永续价格高度一致，用现货镜像标定是可接受的近似。
    """
    feed = BinanceKlineFeed()
    base_url = "https://data-api.binance.vision" if spot_mirror else feed.base_url
    path = "/api/v3/klines" if spot_mirror else "/fapi/v1/klines"
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 86_400_000
    rows: list[list[float]] = []
    cursor = start_ms
    while cursor < end_ms:
        import urllib.parse
        import urllib.request

        query = urllib.parse.urlencode({
            "symbol": symbol,
            "interval": interval,
            "startTime": cursor,
            "limit": 1000 if spot_mirror else 1500,
        })
        with urllib.request.urlopen(f"{base_url}{path}?{query}", timeout=15) as response:
            batch = json.loads(response.read().decode("utf-8"))
        if not batch:
            break
        for row in batch:
            close_time = int(row[6])
            if close_time <= end_ms:
                rows.append([close_time, float(row[4])])
        cursor = int(batch[-1][6]) + 1
        if len(batch) < (1000 if spot_mirror else 1500):
            break
        time.sleep(0.3)  # 限频礼貌间隔
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--interval", default="1h", choices=sorted(INTERVAL_MS))
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--out", default=None)
    parser.add_argument("--spot-mirror", action="store_true", help="经 data-api.binance.vision 现货镜像拉取（fapi 被 451 时用）")
    args = parser.parse_args()

    rows = fetch_history(args.symbol.upper(), args.interval, args.days, spot_mirror=args.spot_mirror)
    out = Path(args.out) if args.out else (
        BACKEND_ROOT.parent / "var" / "calibration" / f"{args.symbol.upper()}_{args.interval}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows), encoding="utf-8")
    print(f"saved {len(rows)} klines -> {out}")


if __name__ == "__main__":
    main()
