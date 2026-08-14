from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import time
from typing import Any, Mapping

from orbit.domain.signals.sig1 import (
    INTERVAL_MS,
    daily_workload_scope,
    detect_sig1_signals,
    notification_message,
    signal_day,
)


TERMINAL_PUSH_EVENTS = {
    "PUSH_SUCCEEDED",
    "PUSH_SKIPPED_THRESHOLD",
    "PUSH_SKIPPED_DAILY_CAP",
    "PUSH_SKIPPED_STALE",
    "PUSH_RETRY_EXHAUSTED",
    "PUSH_DISABLED",
}


class Sig1SignalService:
    def __init__(self, spec: Mapping[str, Any], ledger: Any, notifier: Any | None = None):
        self.spec = dict(spec)
        self.ledger = ledger
        self.notifier = notifier

    def process_closed_candle(
        self,
        market_windows: Mapping[str, Mapping[str, Any]],
        signal_close_time_ms: int,
        *,
        processed_at_ms: int | None = None,
    ) -> dict[str, Any]:
        processed_at = int(processed_at_ms if processed_at_ms is not None else time.time() * 1000)
        self._advance_virtual_trades(market_windows, processed_at)
        state = self._state()
        detected = detect_sig1_signals(market_windows, signal_close_time_ms, self.spec)
        fresh = [row for row in detected if row["signal_id"] not in state["signals"]]
        for signal in fresh:
            self.ledger.append_many(
                [
                    self._event("SIGNAL_DETECTED", processed_at, signal=signal),
                    self._event(
                        "SIM_TRADE_PLANNED",
                        processed_at,
                        signal_id=signal["signal_id"],
                        symbol=signal["symbol"],
                        direction=signal["direction"],
                        entry_due_open_time_ms=int(signal["signal_time_ms"]) + 1,
                        atr14=float(signal["atr14"]),
                        maximum_holding_candles=int(
                            self.spec["simulation"]["maximum_holding_candles"]
                        ),
                    ),
                ]
            )
        if fresh:
            self._reconcile_daily_scope(fresh[0]["signal_day_utc"], processed_at)
        self._deliver_notifications(signal_day(signal_close_time_ms), processed_at)
        state = self._state()
        if int(signal_close_time_ms) not in state["completed_scan_times"]:
            self.ledger.append(
                self._event(
                    "SCAN_COMPLETED",
                    processed_at,
                    signal_close_time_ms=int(signal_close_time_ms),
                    market_window_count=len(market_windows),
                    detected_signal_count=len(detected),
                    new_signal_count=len(fresh),
                )
            )
        return {
            "signal_close_time_ms": int(signal_close_time_ms),
            "new_signal_count": len(fresh),
            "new_signal_ids": [row["signal_id"] for row in fresh],
            "ledger": self.ledger.status(),
        }

    def required_symbols(self) -> set[str]:
        state = self._state()
        return {
            str(trade["symbol"])
            for trade in state["trades"].values()
            if not trade.get("closed")
        }

    def status(self) -> dict[str, Any]:
        state = self._state()
        failures = [
            payload
            for payload in state["payloads"]
            if payload.get("event_type") == "PUSH_FAILED"
        ]
        return {
            "protocol": self.spec["protocol"],
            "signal_count": len(state["signals"]),
            "open_or_pending_virtual_trade_count": sum(
                not row.get("closed") for row in state["trades"].values()
            ),
            "closed_virtual_trade_count": sum(
                bool(row.get("closed")) for row in state["trades"].values()
            ),
            "push_success_count": len(state["push_success_ids"]),
            "push_failure_count": len(failures),
            "last_push_error_type": failures[-1].get("error_type") if failures else None,
            "ledger": self.ledger.status(),
        }

    def _advance_virtual_trades(self, market_windows, processed_at):
        state = self._state()
        for signal_id, trade in sorted(state["trades"].items()):
            if trade.get("closed"):
                continue
            symbol = str(trade["symbol"])
            candles = sorted(
                list((market_windows.get(symbol) or {}).get("candles", [])),
                key=lambda row: int(row.open_time_ms),
            )
            if not candles:
                continue
            opened = trade.get("opened")
            if not opened:
                due = int(trade["entry_due_open_time_ms"])
                entry = next((row for row in candles if int(row.open_time_ms) == due), None)
                if entry is None:
                    continue
                entry_price = float(entry.open)
                risk = float(self.spec["simulation"]["initial_stop_atr_multiple"]) * float(
                    trade["atr14"]
                )
                sign = 1.0 if trade["direction"] == "LONG" else -1.0
                opened = {
                    "entry_time_ms": due,
                    "entry_price": entry_price,
                    "initial_risk_price": risk,
                    "stop_price": entry_price - sign * risk,
                    "time_exit_open_time_ms": due
                    + int(trade["maximum_holding_candles"]) * INTERVAL_MS,
                }
                self.ledger.append(
                    self._event(
                        "SIM_TRADE_OPENED",
                        processed_at,
                        signal_id=signal_id,
                        **opened,
                    )
                )
            exit_result = self._virtual_exit(trade | {"opened": opened}, candles)
            if exit_result:
                self.ledger.append(
                    self._event(
                        "SIM_TRADE_CLOSED",
                        processed_at,
                        signal_id=signal_id,
                        **exit_result,
                    )
                )

    @staticmethod
    def _virtual_exit(trade, candles):
        opened = trade["opened"]
        direction = str(trade["direction"])
        entry_price = float(opened["entry_price"])
        stop = float(opened["stop_price"])
        risk = float(opened["initial_risk_price"])
        due = int(opened["time_exit_open_time_ms"])
        for candle in candles:
            if int(candle.open_time_ms) < int(opened["entry_time_ms"]):
                continue
            exit_price = None
            reason = None
            if direction == "LONG" and float(candle.open) <= stop:
                exit_price, reason = float(candle.open), "STOP"
            elif direction == "SHORT" and float(candle.open) >= stop:
                exit_price, reason = float(candle.open), "STOP"
            elif direction == "LONG" and float(candle.low) <= stop:
                exit_price, reason = stop, "STOP"
            elif direction == "SHORT" and float(candle.high) >= stop:
                exit_price, reason = stop, "STOP"
            elif int(candle.open_time_ms) >= due:
                exit_price, reason = float(candle.open), "TIME_EXIT"
            if exit_price is None:
                continue
            sign = 1.0 if direction == "LONG" else -1.0
            pnl = sign * (exit_price - entry_price)
            return {
                "exit_time_ms": int(candle.open_time_ms),
                "exit_price": exit_price,
                "exit_reason": reason,
                "gross_return_pct": pnl / entry_price * 100,
                "realized_r": pnl / risk,
                "chart_after": [
                    {
                        "open_time_ms": int(row.open_time_ms),
                        "open": float(row.open),
                        "high": float(row.high),
                        "low": float(row.low),
                        "close": float(row.close),
                        "quote_volume": float(row.quote_volume),
                    }
                    for row in candles
                    if int(opened["entry_time_ms"]) <= int(row.open_time_ms) <= int(candle.open_time_ms)
                ],
            }
        return None

    def _reconcile_daily_scope(self, day, processed_at):
        state = self._state()
        daily = [row for row in state["signals"].values() if row["signal_day_utc"] == day]
        scope = daily_workload_scope(daily, int(self.spec["workload"]["daily_candidate_limit"]))
        digest = hashlib.sha256(
            json.dumps(scope, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if state["daily_scope_hashes"].get(day) == digest:
            return
        self.ledger.append(
            self._event(
                "DAILY_SCOPE_RECONCILED",
                processed_at,
                signal_day_utc=day,
                scope_sha256=digest,
                **scope,
            )
        )

    def _deliver_notifications(self, day, processed_at):
        notifications = self.spec["notifications"]
        state = self._state()
        signals = [row for row in state["signals"].values() if row["signal_day_utc"] == day]
        terminal = state["push_terminal_ids"]
        for signal in signals:
            if signal["signal_id"] in terminal:
                continue
            threshold = float(
                notifications["trend_strength_minimum_by_family"][signal["family_id"]]
            )
            if float(signal["trend_strength_96"]) < threshold:
                self.ledger.append(
                    self._event(
                        "PUSH_SKIPPED_THRESHOLD",
                        processed_at,
                        signal_id=signal["signal_id"],
                        trend_strength_96=float(signal["trend_strength_96"]),
                        threshold=threshold,
                    )
                )
        if not notifications.get("enabled", False):
            for signal in signals:
                if signal["signal_id"] not in self._state()["push_terminal_ids"]:
                    self.ledger.append(
                        self._event("PUSH_DISABLED", processed_at, signal_id=signal["signal_id"])
                    )
            return

        state = self._state()
        success_count = sum(
            state["signals"][signal_id]["signal_day_utc"] == day
            for signal_id in state["push_success_ids"]
            if signal_id in state["signals"]
        )
        candidates = [
            signal
            for signal in state["signals"].values()
            if signal["signal_day_utc"] == day
            and signal["signal_id"] not in state["push_terminal_ids"]
        ]
        candidates.sort(
            key=lambda row: (-float(row["trend_strength_96"]), int(row["signal_time_ms"]), row["signal_id"])
        )
        for signal in candidates:
            signal_id = signal["signal_id"]
            if processed_at - int(signal["signal_time_ms"]) > int(
                notifications["maximum_signal_age_ms"]
            ):
                self.ledger.append(
                    self._event("PUSH_SKIPPED_STALE", processed_at, signal_id=signal_id)
                )
                continue
            if success_count >= int(notifications["daily_success_limit"]):
                self.ledger.append(
                    self._event("PUSH_SKIPPED_DAILY_CAP", processed_at, signal_id=signal_id)
                )
                continue
            attempts = state["push_attempts"].get(signal_id, 0)
            if attempts >= int(notifications["maximum_attempts_per_signal"]):
                self.ledger.append(
                    self._event("PUSH_RETRY_EXHAUSTED", processed_at, signal_id=signal_id)
                )
                try:
                    if self.notifier is not None:
                        self.notifier.send({"title": "Orbit 推送通道故障", "message": f"信号 {signal_id} 连续推送失败，已停止重试。", "priority": 1})
                except Exception:
                    pass
                continue
            attempt_number = attempts + 1
            self.ledger.append(
                self._event(
                    "PUSH_ATTEMPTED",
                    processed_at,
                    signal_id=signal_id,
                    attempt_number=attempt_number,
                    provider="PUSHOVER",
                )
            )
            try:
                if self.notifier is None:
                    raise RuntimeError("notification adapter unavailable")
                message = notification_message(signal)
                deep_link_base = str(notifications.get("deep_link_base_url") or "").rstrip("/")
                if deep_link_base:
                    message |= {
                        "url": f"{deep_link_base}/#signals/{signal_id}",
                        "url_title": "在 Orbit 打开信号",
                    }
                result = self.notifier.send(message)
                self.ledger.append(
                    self._event(
                        "PUSH_SUCCEEDED",
                        processed_at,
                        signal_id=signal_id,
                        attempt_number=attempt_number,
                        provider="PUSHOVER",
                        provider_request_id=result.get("request_id"),
                    )
                )
                success_count += 1
            except Exception as exc:
                self.ledger.append(
                    self._event(
                        "PUSH_FAILED",
                        processed_at,
                        signal_id=signal_id,
                        attempt_number=attempt_number,
                        provider="PUSHOVER",
                        error_type=type(exc).__name__,
                    )
                )

    def _state(self):
        payloads = [record["payload"] for record in self.ledger.read_all()]
        signals = {}
        trades: dict[str, dict[str, Any]] = {}
        push_attempts = defaultdict(int)
        push_success_ids = set()
        push_terminal_ids = set()
        daily_scope_hashes = {}
        completed_scan_times = set()
        for payload in payloads:
            event_type = payload.get("event_type")
            if event_type == "SIGNAL_DETECTED":
                signal = dict(payload["signal"])
                signals[signal["signal_id"]] = signal
            elif event_type == "SIM_TRADE_PLANNED":
                trades[payload["signal_id"]] = dict(payload)
            elif event_type == "SIM_TRADE_OPENED":
                trades.setdefault(payload["signal_id"], {})["opened"] = {
                    key: payload[key]
                    for key in (
                        "entry_time_ms",
                        "entry_price",
                        "initial_risk_price",
                        "stop_price",
                        "time_exit_open_time_ms",
                    )
                }
            elif event_type == "SIM_TRADE_CLOSED":
                trades.setdefault(payload["signal_id"], {})["closed"] = dict(payload)
            elif event_type == "PUSH_ATTEMPTED":
                push_attempts[payload["signal_id"]] += 1
            elif event_type == "PUSH_SUCCEEDED":
                push_success_ids.add(payload["signal_id"])
                push_terminal_ids.add(payload["signal_id"])
            elif event_type in TERMINAL_PUSH_EVENTS:
                push_terminal_ids.add(payload["signal_id"])
            elif event_type == "DAILY_SCOPE_RECONCILED":
                daily_scope_hashes[payload["signal_day_utc"]] = payload["scope_sha256"]
            elif event_type == "SCAN_COMPLETED":
                completed_scan_times.add(int(payload["signal_close_time_ms"]))
        return {
            "payloads": payloads,
            "signals": signals,
            "trades": trades,
            "push_attempts": dict(push_attempts),
            "push_success_ids": push_success_ids,
            "push_terminal_ids": push_terminal_ids,
            "daily_scope_hashes": daily_scope_hashes,
            "completed_scan_times": completed_scan_times,
        }

    @staticmethod
    def _event(event_type, recorded_at_ms, **payload):
        return {
            "event_type": event_type,
            "recorded_at_ms": int(recorded_at_ms),
            **payload,
        }
