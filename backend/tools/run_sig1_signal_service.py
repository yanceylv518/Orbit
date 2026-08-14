"""Run one SIG-1 scan or the deployable 15-minute signal-service loop."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.sig1_signal_service import Sig1SignalService  # noqa: E402
from orbit.domain.calibration.r0_shortline import ShortlineCandle  # noqa: E402
from orbit.infrastructure.credentials.factory import create_credential_vault  # noqa: E402
from orbit.infrastructure.exchange.kline_feed import BinanceKlineFeed  # noqa: E402
from orbit.infrastructure.notifications.pushover import PushoverNotifier  # noqa: E402
from orbit.infrastructure.persistence.signal_ledger import AppendOnlySignalLedger  # noqa: E402


SPEC_PATH = PROJECT_ROOT / "config/signals/sig1.v1.json"
DEFAULT_CONFIG = PROJECT_ROOT / "config.local.json"
INTERVAL_MS = 900_000


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", default=str(SPEC_PATH))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--ledger-directory")
    parser.add_argument("--pushover-token-ref")
    parser.add_argument("--pushover-user-ref")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--poll-delay-seconds", type=float, default=5)
    args = parser.parse_args()

    spec_path = Path(args.spec).resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    _verify_spec(spec)
    runtime_config = json.loads(Path(args.config).resolve().read_text(encoding="utf-8"))
    vault = create_credential_vault(runtime_config)
    notifications = spec["notifications"]
    token_reference = args.pushover_token_ref or notifications["api_token_reference"]
    user_reference = args.pushover_user_ref or notifications["user_key_reference"]
    _verify_credential_reference(token_reference, "Pushover API token")
    _verify_credential_reference(user_reference, "Pushover user key")
    notifier = PushoverNotifier(
        vault,
        api_token_reference=token_reference,
        user_key_reference=user_reference,
    )
    directory = Path(
        args.ledger_directory or PROJECT_ROOT / spec["persistence"]["default_directory"]
    ).resolve()
    ledger = AppendOnlySignalLedger(directory)
    ledger.open(
        {
            "protocol": "ORBIT_SIG1_LEDGER_MANIFEST_V1",
            "signal_protocol": spec["protocol"],
            "spec_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest(),
            "live_trading_authorized": False,
        }
    )
    service = Sig1SignalService(spec, ledger, notifier)
    source = BinanceSig1Source(BinanceKlineFeed(), spec, service)
    while True:
        result = source.scan_once()
        print(json.dumps(result | {"service": service.status()}, ensure_ascii=False), flush=True)
        if not args.loop:
            break
        now_ms = int(time.time() * 1000)
        next_boundary_ms = (now_ms // INTERVAL_MS + 1) * INTERVAL_MS
        time.sleep(max(1.0, (next_boundary_ms - now_ms) / 1000 + args.poll_delay_seconds))


class BinanceSig1Source:
    def __init__(self, feed, spec, service, *, workers: int = 8, clock=time.time):
        self.feed = feed
        self.spec = spec
        self.service = service
        self.workers = workers
        self.clock = clock
        self._universe_day = None
        self._daily_volumes: dict[str, list[float]] = {}

    def scan_once(self) -> dict[str, Any]:
        now_ms = int(self.clock() * 1000)
        day = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        if day != self._universe_day:
            self._refresh_universe()
            self._universe_day = day
        minimum = float(
            self.spec["market"]["liquidity"]["minimum_median_daily_quote_volume_usdt"]
        )
        qualified = {
            symbol
            for symbol, values in self._daily_volumes.items()
            if len(values) == 3 and statistics.median(values) >= minimum
        }
        symbols = sorted(qualified | self.service.required_symbols())
        windows = self._intraday_windows(symbols, qualified)
        close_time_ms = now_ms // INTERVAL_MS * INTERVAL_MS - 1
        result = self.service.process_closed_candle(
            windows, close_time_ms, processed_at_ms=now_ms
        )
        return result | {
            "qualified_market_count": len(qualified),
            "tracked_trade_symbol_count": len(symbols - qualified),
        }

    def _refresh_universe(self) -> None:
        symbols = self.feed.perpetual_symbols()
        volumes: dict[str, list[float]] = {}
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(self.feed.closed_klines, symbol, "1d", 3): symbol
                for symbol in symbols
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    rows = future.result()
                except Exception:
                    continue
                values = [float(row["quote_volume"]) for row in rows]
                if len(values) == 3:
                    volumes[symbol] = values
        self._daily_volumes = volumes

    def _intraday_windows(self, symbols, qualified):
        result = {}
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(self.feed.closed_klines, symbol, "15m", 320): symbol
                for symbol in symbols
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    rows = future.result()
                except Exception:
                    continue
                result[symbol] = {
                    "candles": [
                        ShortlineCandle(
                            open_time_ms=int(row["open_time"]),
                            close_time_ms=int(row["close_time"]),
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            quote_volume=float(row["quote_volume"]),
                        )
                        for row in rows
                    ],
                    "daily_quote_volumes": self._daily_volumes.get(symbol, [])
                    if symbol in qualified
                    else [],
                }
        return result


def _verify_spec(spec: dict[str, Any]) -> None:
    if spec["protocol"] != "ORBIT_SIG1_SIGNAL_SERVICE_V1":
        raise RuntimeError("unsupported SIG-1 protocol")
    if spec["discipline"]["live_trading_authorized"]:
        raise RuntimeError("SIG-1 must not authorize live trading")
    if not spec["discipline"]["notification_is_side_effect_only"]:
        raise RuntimeError("SIG-1 notification must remain a side effect")
    for field in ("api_token_reference", "user_key_reference"):
        _verify_credential_reference(str(spec["notifications"][field]), f"SIG-1 {field}")


def _verify_credential_reference(reference: str, label: str) -> None:
    if not str(reference).startswith(("env:", "dpapi:", "aesgcm:")):
        raise RuntimeError(f"{label} must be a credential-vault reference")


if __name__ == "__main__":
    main()
