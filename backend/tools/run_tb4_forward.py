"""Initialize or continuously run the frozen TB4 paper forward test."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import time


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.trend_forward import TrendForwardService  # noqa: E402
from orbit.application.trend_forward_market import TrendForwardMarketDriver  # noqa: E402
from orbit.infrastructure.exchange.kline_feed import BinanceKlineFeed  # noqa: E402
from orbit.infrastructure.persistence.trend_forward_ledger import TrendForwardLedger  # noqa: E402


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
    ).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="var/forward/tb4")
    parser.add_argument("--base-url", default="https://fapi.binance.com")
    parser.add_argument("--initialize", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    protocol_path = ROOT / "docs" / "design" / "TB4_FORWARD.md"
    service = TrendForwardService(TrendForwardLedger(data_dir))
    driver = TrendForwardMarketDriver(
        BinanceKlineFeed(base_url=args.base_url), service,
    )
    if args.initialize:
        snapshot = driver.initialize(
            code_commit=git_commit(),
            protocol_sha256=file_sha256(protocol_path),
        )
        print(f"TB4 initialized: {snapshot['manifest_sha256']}")
    if not service.ledger.manifest():
        parser.error("TB4 is not initialized; run once with --initialize")
    if args.once:
        print(driver.poll_once())
        return
    while True:
        try:
            result = driver.poll_once()
            if result["ticks"]:
                print(f"TB4 appended {result['ticks']} close(s)", flush=True)
        except Exception as exc:
            print(f"TB4 poll error: {exc}", file=sys.stderr, flush=True)
        time.sleep(max(10.0, args.poll_seconds))


if __name__ == "__main__":
    main()
