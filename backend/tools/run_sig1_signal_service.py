"""Run one SIG-1 scan or the deployable 15-minute signal-service loop."""
from __future__ import annotations

import argparse
from collections import Counter
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
from orbit.application.signals.desk import INTERACTION_MANIFEST  # noqa: E402
from orbit.application.signals.configuration import apply_values, scope_version  # noqa: E402
from orbit.domain.calibration.r0_shortline import ShortlineCandle  # noqa: E402
from orbit.infrastructure.credentials.factory import create_credential_vault  # noqa: E402
from orbit.infrastructure.exchange.kline_feed import BinanceKlineFeed, BinanceWeightLimiter, MarketFeedError  # noqa: E402
from orbit.infrastructure.notifications.pushover import PushoverNotifier  # noqa: E402
from orbit.infrastructure.persistence.signal_ledger import AppendOnlySignalLedger  # noqa: E402


SPEC_PATH = PROJECT_ROOT / "config/signals/sig1.v1.json"
DEFAULT_CONFIG = PROJECT_ROOT / "config.local.json"
INTERVAL_MS = 900_000
FOUR_HOUR_MS = 14_400_000


class ScanDataUnavailable(RuntimeError):
    def __init__(self, summary: dict[str, Any]):
        self.summary = summary
        attempted = int(summary.get("attempted_market_count", 0))
        failed = int(summary.get("failed_market_count", 0))
        cause = str(summary.get("primary_failure_label") or "数据不足")
        super().__init__(f"{attempted} 个市场中 {failed} 个取数失败，主因 {cause}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", default=str(SPEC_PATH))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--ledger-directory")
    parser.add_argument("--interaction-directory")
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
    signal_runtime = (runtime_config.get("runtime") or {}).get("signals") or {}
    if signal_runtime.get("public_base_url"):
        notifications["deep_link_base_url"] = str(signal_runtime["public_base_url"])
    interaction_directory = Path(args.interaction_directory or PROJECT_ROOT / signal_runtime.get("interaction_ledger_directory", "var/signals/sig2")).resolve()
    control_ledger = AppendOnlySignalLedger(interaction_directory)
    control_ledger.open(INTERACTION_MANIFEST)
    controls = _runtime_controls(control_ledger)
    token_reference = args.pushover_token_ref or controls.get("api_token_reference") or notifications["api_token_reference"]
    user_reference = args.pushover_user_ref or controls.get("user_key_reference") or notifications["user_key_reference"]
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
    fetch = spec["market"].get("data_fetch") or {}
    limiter = BinanceWeightLimiter(int(fetch.get("weight_budget_per_minute", 1200)))
    source = BinanceSig1Source(BinanceKlineFeed(limiter=limiter), spec, service, workers=int(fetch.get("maximum_concurrency", 8)))
    active_configuration_revision = -1
    while True:
        controls = _runtime_controls(control_ledger)
        service.spec["notifications"]["enabled"] = bool(controls.get("pushover_enabled", False))
        for family, enabled in (controls.get("family_enabled") or {}).items():
            if family in service.spec.get("signals", {}):
                service.spec["signals"][family]["enabled"] = bool(enabled)
        apply_values(service.spec, controls.get("configuration_values") or {})
        service.spec["scope_version"] = scope_version(int(controls.get("configuration_revision", 0)))
        if int(controls.get("configuration_revision", 0)) != active_configuration_revision:
            source._universe_day = None
            active_configuration_revision = int(controls.get("configuration_revision", 0))
        if controls.get("api_token_reference") and controls.get("user_key_reference"):
            service.notifier = PushoverNotifier(vault, api_token_reference=controls["api_token_reference"], user_key_reference=controls["user_key_reference"])
        if not controls.get("service_enabled", False):
            print(json.dumps({"status": "DISABLED", "reason": "signal service switch is off"}, ensure_ascii=False), flush=True)
            if not args.loop: break
            time.sleep(max(1.0, args.poll_delay_seconds))
            continue
        try:
            result = source.scan_once()
            recovered = _recovered_failure(control_ledger)
            control_ledger.append({"event_type": "SERVICE_HEARTBEAT", "recorded_at_ms": int(time.time() * 1000), "status": "RUNNING"})
            if recovered and service.notifier is not None:
                try:
                    service.notifier.send({"title": "Orbit 信号服务已恢复", "message": f"扫描已恢复；此前故障：{recovered.get('message') or recovered.get('error_type')}", "priority": 0})
                except Exception:
                    pass
            print(json.dumps(result | {"service": service.status()}, ensure_ascii=False), flush=True)
        except Exception as exc:
            now_ms = int(time.time() * 1000)
            failure = _failure_event(exc, now_ms)
            control_ledger.append(failure)
            try:
                if service.notifier is not None and _should_notify_failure(control_ledger, failure, now_ms):
                    service.notifier.send({"title": "Orbit 信号服务故障", "message": failure["message"], "priority": 1})
            except Exception:
                pass
            if not args.loop:
                raise
        if not args.loop:
            break
        now_ms = int(time.time() * 1000)
        next_boundary_ms = (now_ms // INTERVAL_MS + 1) * INTERVAL_MS
        time.sleep(max(1.0, (next_boundary_ms - now_ms) / 1000 + args.poll_delay_seconds))


def _runtime_controls(ledger: AppendOnlySignalLedger) -> dict[str, Any]:
    result = {"service_enabled": False, "pushover_enabled": False, "family_enabled": {}, "configuration_values": {}, "configuration_revision": 0}
    for record in ledger.read_all():
        event = record["payload"]
        if event.get("event_type") == "SIGNAL_SERVICE_CONTROL_CHANGED":
            result["service_enabled"] = bool(event.get("enabled"))
        elif event.get("event_type") == "PUSHOVER_CONFIGURATION_CHANGED":
            result.update({"pushover_enabled": bool(event.get("enabled")), "api_token_reference": event.get("api_token_reference"), "user_key_reference": event.get("user_key_reference")})
        elif event.get("event_type") == "SIGNAL_FAMILY_CONTROL_CHANGED":
            result["family_enabled"][str(event.get("family_id"))] = bool(event.get("enabled"))
            result["configuration_revision"] += 1
        elif event.get("event_type") == "SIGNAL_CONFIGURATION_CHANGED":
            result["configuration_values"].update(event.get("values") or {})
            result["configuration_revision"] += 1
    return result


class BinanceSig1Source:
    def __init__(self, feed, spec, service, *, workers: int = 8, clock=time.time):
        self.feed = feed
        self.spec = spec
        self.service = service
        self.workers = workers
        self.clock = clock
        self._universe_day = None
        self._daily_volumes: dict[str, list[float]] = {}
        self._candle_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._last_failure_counts: Counter[str] = Counter()
        self._universe_failure_counts: Counter[str] = Counter()
        self._universe_attempted = 0
        self._truncated_market_count = 0

    def scan_once(self) -> dict[str, Any]:
        now_ms = int(self.clock() * 1000)
        day = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        if day != self._universe_day:
            self._refresh_universe()
            self._universe_day = day
        minimum_markets = int(self.spec["market"]["minimum_simultaneously_eligible_markets"])
        if len(self._daily_volumes) < minimum_markets and self._universe_failure_counts:
            self._last_failure_counts = Counter(self._universe_failure_counts)
            raise ScanDataUnavailable(self._failure_summary(self._universe_attempted, len(self._daily_volumes)))
        minimum = float(
            self.spec["market"]["liquidity"]["minimum_median_daily_quote_volume_usdt"]
        )
        qualified_rows = [
            (symbol, statistics.median(values))
            for symbol, values in self._daily_volumes.items()
            if len(values) == int(self.spec["market"]["liquidity"]["lookback_complete_utc_days"])
            and statistics.median(values) >= minimum
        ]
        qualified_rows.sort(key=lambda row: (-row[1], row[0]))
        maximum = int(self.spec["market"].get("maximum_tracked_markets", 300))
        self._truncated_market_count = max(0, len(qualified_rows) - maximum)
        qualified = {symbol for symbol, _volume in qualified_rows[:maximum]}
        symbol_set = qualified | self.service.required_symbols()
        windows = self._intraday_windows(sorted(symbol_set), qualified)
        if len(qualified) >= int(self.spec["market"]["minimum_simultaneously_eligible_markets"]) and len(windows) < int(self.spec["market"]["minimum_simultaneously_eligible_markets"]):
            raise ScanDataUnavailable(self._failure_summary(len(symbol_set), len(windows)))
        close_time_ms = now_ms // INTERVAL_MS * INTERVAL_MS - 1
        result = self.service.process_closed_candle(
            windows, close_time_ms, processed_at_ms=now_ms,
            scan_metadata={"qualified_market_count": len(qualified), "truncated_market_count": self._truncated_market_count, "fetch_failure_counts": dict(self._last_failure_counts)},
        )
        return result | {
            "qualified_market_count": len(qualified),
            "tracked_trade_symbol_count": len(symbol_set - qualified),
            "truncated_market_count": self._truncated_market_count,
            "fetch_failure_counts": dict(self._last_failure_counts),
        }

    def _refresh_universe(self) -> None:
        symbols = self.feed.perpetual_symbols()
        volumes: dict[str, list[float]] = {}
        failures: Counter[str] = Counter()
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(
                    self.feed.closed_klines, symbol, "1d",
                    int(self.spec["market"]["liquidity"]["lookback_complete_utc_days"]),
                ): symbol
                for symbol in symbols
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    rows = future.result()
                except Exception as exc:
                    failures[self._failure_category(exc)] += 1
                    continue
                values = [float(row["quote_volume"]) for row in rows]
                if len(values) == int(self.spec["market"]["liquidity"]["lookback_complete_utc_days"]):
                    volumes[symbol] = values
        self._daily_volumes = volumes
        self._universe_attempted = len(symbols)
        self._universe_failure_counts = failures

    def _intraday_windows(self, symbols, qualified):
        result = {}
        failures: Counter[str] = Counter()
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(self._market_window, symbol): symbol
                for symbol in symbols
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    intraday_rows, long_cycle_rows = future.result()
                except Exception as exc:
                    failures[self._failure_category(exc)] += 1
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
                        for row in intraday_rows
                    ],
                    "long_cycle_candles": [
                        ShortlineCandle(
                            open_time_ms=int(row["open_time"]), close_time_ms=int(row["close_time"]),
                            open=float(row["open"]), high=float(row["high"]), low=float(row["low"]),
                            close=float(row["close"]), quote_volume=float(row["quote_volume"]),
                        ) for row in long_cycle_rows
                    ],
                    "daily_quote_volumes": self._daily_volumes.get(symbol, [])
                    if symbol in qualified
                    else [],
                }
        self._last_failure_counts = failures
        return result

    def _market_window(self, symbol):
        required_15m = self._required_15m_history()
        intraday = self._cached_klines(symbol, "15m", required_15m)
        long_cycle = self._cached_klines(symbol, "4h", 361)
        if len(intraday) < required_15m or len(long_cycle) < 361:
            raise ValueError("completed kline history is insufficient")
        return intraday, long_cycle

    def _required_15m_history(self) -> int:
        signals = self.spec.get("signals", {})
        oversold = signals.get("OVERSOLD_REBOUND") or {}
        strength = signals.get("SUSTAINED_STRENGTH") or {}
        return max(1440, int(oversold.get("collapse_lookback_days", 14)) * 96, int(oversold.get("pullback_start_high_lookback_days", 3)) * 96, int(strength.get("long_volume_days", 10)) * 96)

    def _cached_klines(self, symbol: str, interval: str, maximum: int):
        key = (symbol, interval)
        cached = self._candle_cache.get(key, [])
        interval_ms = INTERVAL_MS if interval == "15m" else FOUR_HOUR_MS
        now_ms = int(self.clock() * 1000)
        expected_close = now_ms // interval_ms * interval_ms - 1
        if cached and interval == "4h" and int(cached[-1]["close_time"]) >= expected_close:
            return cached[-maximum:]
        rows = self.feed.closed_klines(symbol, interval, maximum if not cached else 3)
        rows = [row for row in rows if int(row["close_time"]) <= now_ms]
        if cached and rows:
            overlap = {int(row["close_time"]) for row in cached} & {int(row["close_time"]) for row in rows}
            first_new = min((int(row["close_time"]) for row in rows if int(row["close_time"]) > int(cached[-1]["close_time"])), default=None)
            gap = first_new is not None and first_new - int(cached[-1]["close_time"]) > interval_ms
            if gap or (not overlap and int(rows[-1]["close_time"]) > int(cached[-1]["close_time"])):
                rows = self.feed.closed_klines(symbol, interval, maximum)
        merged = {int(row["close_time"]): row for row in cached}
        merged.update({int(row["close_time"]): row for row in rows if int(row["close_time"]) <= now_ms})
        result = [merged[key] for key in sorted(merged)][-maximum:]
        self._candle_cache[key] = result
        return result

    @staticmethod
    def _failure_category(exc: Exception) -> str:
        if isinstance(exc, MarketFeedError):
            return exc.category
        if isinstance(exc, TimeoutError):
            return "TIMEOUT"
        return "DATA_INSUFFICIENT" if isinstance(exc, (IndexError, ValueError)) else "UNKNOWN"

    def _failure_summary(self, attempted: int, succeeded: int) -> dict[str, Any]:
        counts = Counter(self._last_failure_counts)
        missing = max(0, attempted - succeeded - sum(counts.values()))
        if missing:
            counts["DATA_INSUFFICIENT"] += missing
        primary = counts.most_common(1)[0][0] if counts else "DATA_INSUFFICIENT"
        labels = {"RATE_LIMIT": "HTTP 429/418 限频", "TIMEOUT": "请求超时", "HTTP_ERROR": "HTTP 错误", "NETWORK_ERROR": "网络错误", "DATA_INSUFFICIENT": "数据不足", "UNKNOWN": "未知取数错误"}
        return {"attempted_market_count": attempted, "successful_market_count": succeeded, "failed_market_count": max(0, attempted - succeeded), "failure_counts": dict(counts), "primary_failure": primary, "primary_failure_label": labels.get(primary, primary)}


def _failure_event(exc: Exception, recorded_at_ms: int) -> dict[str, Any]:
    summary = exc.summary if isinstance(exc, ScanDataUnavailable) else {"primary_failure": BinanceSig1Source._failure_category(exc), "failed_market_count": 0, "attempted_market_count": 0, "failure_counts": {}}
    message = str(exc) if isinstance(exc, ScanDataUnavailable) else f"扫描失败：{summary['primary_failure']}"
    return {"event_type": "SERVICE_SCAN_FAILED", "recorded_at_ms": recorded_at_ms, "error_type": summary["primary_failure"], "message": message, **summary}


def _should_notify_failure(ledger: AppendOnlySignalLedger, failure: dict[str, Any], now_ms: int, repeat_ms: int = 3_600_000) -> bool:
    previous = [record["payload"] for record in ledger.read_all() if record["payload"].get("event_type") == "SERVICE_SCAN_FAILED" and int(record["payload"].get("recorded_at_ms", 0)) < now_ms]
    if not previous:
        return True
    latest = previous[-1]
    return latest.get("error_type") != failure.get("error_type") or now_ms - int(latest.get("recorded_at_ms", 0)) >= repeat_ms


def _recovered_failure(ledger: AppendOnlySignalLedger) -> dict[str, Any] | None:
    latest_failure = None
    latest_heartbeat_ms = 0
    for record in ledger.read_all():
        event = record["payload"]
        if event.get("event_type") == "SERVICE_SCAN_FAILED":
            latest_failure = event
        elif event.get("event_type") == "SERVICE_HEARTBEAT":
            latest_heartbeat_ms = max(latest_heartbeat_ms, int(event.get("recorded_at_ms", 0)))
    if latest_failure and int(latest_failure.get("recorded_at_ms", 0)) > latest_heartbeat_ms:
        return latest_failure
    return None


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
