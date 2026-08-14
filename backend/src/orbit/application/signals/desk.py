from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any

from orbit.infrastructure.persistence.signal_ledger import AppendOnlySignalLedger, canonical_json


INTERACTION_MANIFEST = {
    "protocol": "ORBIT_SIG2_INTERACTION_LEDGER_V1",
    "write_model": "APPEND_ONLY_SHA256_CHAIN",
    "signal_source": "ORBIT_SIG1_SIGNAL_SERVICE_V1",
    "cooldown_after_stop_minutes": 240,
    "constraints": ["STOP_REQUIRED", "NO_AVERAGING_DOWN", "COOLDOWN_AFTER_STOP", "SIGNAL_REQUIRED"],
}


class SignalDeskService:
    """SIG-2 command/read model over immutable SIG-1 and interaction ledgers."""

    def __init__(self, ledger_directory: Path, interaction_directory: Path | None = None):
        self.ledger_directory = ledger_directory
        self.interaction_directory = interaction_directory or ledger_directory.parent / "sig2"

    def snapshot(self, *, day: str | None = None, limit: int = 200) -> dict[str, Any]:
        selected_day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        source = self._read_source(selected_day)
        if source["health"]["status"] in {"NOT_DEPLOYED", "LEDGER_ERROR"}:
            return source
        try:
            interactions = self._read_interactions()
        except Exception as exc:
            all_rows = source.pop("_all_signals")
            for row in all_rows:
                row["decision"] = None
                row["manual_execution"] = None
            source["signals"] = all_rows[: max(1, min(int(limit), 1000))]
            source["summary"] = self._summary(all_rows)
            source["discipline"] = self._discipline(all_rows)
            source["review"] = self._review(all_rows)
            source["health"].update(
                {"status": "LEDGER_ERROR", "error_type": type(exc).__name__, "error_scope": "SIG2_INTERACTIONS"}
            )
            source["interaction_ledger"] = {"event_count": 0, "append_only": True}
            return source
        decisions: dict[str, dict[str, Any]] = {}
        executions: dict[str, dict[str, Any]] = {}
        for event in interactions:
            if event.get("event_type") == "SIGNAL_DECISION_RECORDED":
                decisions[event["signal_id"]] = event
            elif event.get("event_type") == "MANUAL_EXECUTION_RECORDED":
                executions[event["signal_id"]] = event
        all_rows = source.pop("_all_signals")
        for row in all_rows:
            row["decision"] = self._public_event(decisions.get(row["signal_id"])) or None
            row["manual_execution"] = self._public_event(executions.get(row["signal_id"])) or None
        source["signals"] = all_rows[: max(1, min(int(limit), 1000))]
        source["summary"] = self._summary(all_rows)
        source["discipline"] = self._discipline(all_rows)
        source["review"] = self._review(all_rows)
        source["interaction_ledger"] = {
            "event_count": len(interactions),
            "append_only": True,
        }
        return source

    def record_decision(
        self, *, signal_id: str, decision: str, reason: str | None, stop_price: float | None,
        entry_price: float | None, actor: str,
    ) -> dict[str, Any]:
        decision = decision.upper()
        if decision not in {"TAKEN", "SKIPPED"}:
            raise ValueError("decision must be TAKEN or SKIPPED")
        signal = self._signal(signal_id)
        if self._candidate_scope(signal) != "INCLUDED":
            raise ValueError("该信号不在当日 30 条人工候选范围内，只保留模拟记录")
        existing = self._events_for(signal_id)
        if any(row.get("event_type") == "SIGNAL_DECISION_RECORDED" for row in existing):
            raise ValueError("该信号已经做过决定，追加账本不允许覆盖")
        if decision == "TAKEN":
            if stop_price is None:
                raise ValueError("做了的信号必须同时记录止损价")
            actual_entry = float(entry_price if entry_price is not None else signal["reference_entry_price"])
            self._validate_stop(signal["direction"], actual_entry, float(stop_price))
            self._validate_cooldown(signal)
        event = {
            "event_type": "SIGNAL_DECISION_RECORDED",
            "recorded_at_ms": int(time.time() * 1000),
            "signal_id": signal_id,
            "decision": decision,
            "reason": (reason or "").strip()[:120] or None,
            "entry_price": float(entry_price) if entry_price is not None else None,
            "stop_price": float(stop_price) if stop_price is not None else None,
            "actor": actor,
        }
        self._interaction_ledger().append(event)
        return self.snapshot(day=signal["signal_day_utc"])

    def record_execution(
        self, *, signal_id: str, entry_price: float, exit_price: float, exited_at_ms: int,
        exit_reason: str, actor: str,
    ) -> dict[str, Any]:
        signal = self._signal(signal_id)
        events = self._events_for(signal_id)
        decision = next((row for row in events if row.get("event_type") == "SIGNAL_DECISION_RECORDED"), None)
        if not decision or decision.get("decision") != "TAKEN":
            raise ValueError("只能给已标记为“我做了”的信号登记成交")
        if any(row.get("event_type") == "MANUAL_EXECUTION_RECORDED" for row in events):
            raise ValueError("该信号已有实际成交，禁止覆盖或亏损加仓")
        self._validate_stop(signal["direction"], float(entry_price), float(decision["stop_price"]))
        if int(exited_at_ms) < int(signal["signal_time_ms"]):
            raise ValueError("离场时间不能早于信号时间")
        sign = 1.0 if signal["direction"] == "LONG" else -1.0
        pnl = sign * (float(exit_price) - float(entry_price))
        risk = abs(float(entry_price) - float(decision["stop_price"]))
        event = {
            "event_type": "MANUAL_EXECUTION_RECORDED",
            "recorded_at_ms": int(time.time() * 1000),
            "signal_id": signal_id,
            "entry_price": float(entry_price),
            "exit_price": float(exit_price),
            "exited_at_ms": int(exited_at_ms),
            "exit_reason": exit_reason.upper(),
            "gross_return_pct": pnl / float(entry_price) * 100,
            "realized_r": pnl / risk,
            "actor": actor,
        }
        self._interaction_ledger().append(event)
        return self.snapshot(day=signal["signal_day_utc"])

    def _read_source(self, selected_day: str) -> dict[str, Any]:
        manifest_path = self.ledger_directory / "manifest.json"
        events_path = self.ledger_directory / "events.jsonl"
        if not manifest_path.exists():
            return self._empty(selected_day, "NOT_DEPLOYED")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            stored_hash = manifest.pop("manifest_sha256", None)
            if stored_hash != hashlib.sha256(canonical_json(manifest)).hexdigest():
                raise RuntimeError("SIG-1 manifest fingerprint mismatch")
            if manifest.get("protocol") != "ORBIT_SIG1_SIGNAL_SERVICE_V1":
                raise RuntimeError("SIG-1 manifest protocol mismatch")
            records = AppendOnlySignalLedger(self.ledger_directory).read_all()
        except Exception as exc:
            payload = self._empty(selected_day, "LEDGER_ERROR")
            payload["health"].update({"manifest_exists": True, "error_type": type(exc).__name__})
            return payload
        signals: dict[str, dict[str, Any]] = {}; trades: dict[str, dict[str, Any]] = {}
        pushes: dict[str, dict[str, Any]] = {}; scopes: dict[str, dict[str, Any]] = {}; latest_scan = None
        latest_recorded_at_ms = None
        for record in records:
            event = record["payload"]; event_type = str(event.get("event_type", ""))
            latest_recorded_at_ms = event.get("recorded_at_ms") or latest_recorded_at_ms
            if event_type == "SIGNAL_DETECTED": signals[event["signal"]["signal_id"]] = dict(event["signal"])
            elif event_type == "SIM_TRADE_PLANNED": trades[event["signal_id"]] = {"status": "WAITING_ENTRY", **event}
            elif event_type == "SIM_TRADE_OPENED": trades.setdefault(event["signal_id"], {}).update({"status": "OPEN", **event})
            elif event_type == "SIM_TRADE_CLOSED": trades.setdefault(event["signal_id"], {}).update({"status": "CLOSED", **event})
            elif event_type.startswith("PUSH_"): pushes[event["signal_id"]] = dict(event)
            elif event_type == "DAILY_SCOPE_RECONCILED": scopes[event["signal_day_utc"]] = dict(event)
            elif event_type == "SCAN_COMPLETED": latest_scan = dict(event)
        scope = scopes.get(selected_day, {}); included = set(scope.get("included_signal_ids", [])); truncated = set(scope.get("truncated_signal_ids", []))
        rows = []
        for signal in signals.values():
            if signal.get("signal_day_utc") != selected_day: continue
            sid = signal["signal_id"]
            rows.append({**signal, "candidate_scope": "INCLUDED" if sid in included else "TRUNCATED" if sid in truncated else "PENDING_SCOPE", "simulation": self._public_event(trades.get(sid, {"status": "WAITING_ENTRY"})), "push": self._public_event(pushes.get(sid)) or None})
        rows.sort(key=lambda row: (-int(row.get("signal_time_ms", 0)), -float(row.get("trend_strength_96", 0)), str(row.get("signal_id", ""))))
        return {"protocol": "ORBIT_SIGNAL_DESK_V2", "day_utc": selected_day, "health": {"status": "RUNNING" if latest_scan else "WAITING_FIRST_SCAN", "manifest_exists": True, "events_exists": events_path.exists(), "event_count": len(records), "head_hash": records[-1]["record_hash"] if records else "0" * 64, "latest_recorded_at_ms": latest_recorded_at_ms, "latest_scan": self._public_event(latest_scan), "error_type": None}, "_all_signals": rows}

    def _summary(self, rows):
        closed = [row for row in rows if row["simulation"].get("status") == "CLOSED"]
        return {"signal_count": len(rows), "included_count": sum(r["candidate_scope"] == "INCLUDED" for r in rows), "truncated_count": sum(r["candidate_scope"] == "TRUNCATED" for r in rows), "taken_count": sum((r.get("decision") or {}).get("decision") == "TAKEN" for r in rows), "skipped_count": sum((r.get("decision") or {}).get("decision") == "SKIPPED" for r in rows), "undecided_count": sum(not r.get("decision") for r in rows), "open_count": sum(r["simulation"].get("status") == "OPEN" for r in rows), "closed_count": len(closed), "push_succeeded_count": sum((r.get("push") or {}).get("event_type") == "PUSH_SUCCEEDED" for r in rows), "realized_r_total": sum(float(r["simulation"].get("realized_r", 0) or 0) for r in closed)}

    def _review(self, rows):
        def book(chosen, manual=False):
            selected = [r for r in rows if chosen(r)]
            field = "manual_execution" if manual else "simulation"
            closed = [r for r in selected if (r.get(field) or {}).get("realized_r") is not None]
            return {"count": len(selected), "closed_count": len(closed), "realized_r_total": sum(float(r[field]["realized_r"]) for r in closed), "wins": sum(float(r[field]["realized_r"]) > 0 for r in closed), "losses": sum(float(r[field]["realized_r"]) <= 0 for r in closed)}
        return {"all_signal_simulation": book(lambda r: True), "chosen_signal_simulation": book(lambda r: (r.get("decision") or {}).get("decision") == "TAKEN"), "actual_manual": book(lambda r: r.get("manual_execution") is not None, True)}

    def _discipline(self, rows):
        stopped = [r for r in rows if (r.get("manual_execution") or {}).get("exit_reason") == "STOP"]
        return {"stop_attached": "ENFORCED", "averaging_down": "BLOCKED", "cooldown_after_stop_minutes": 240, "cooldown_symbols": sorted({f'{r["symbol"]} {r["direction"]}' for r in stopped}), "outside_signal_trade": "BLOCKED", "outside_signal_count": 0}

    def _signal(self, signal_id):
        if not (self.ledger_directory / "manifest.json").exists(): raise ValueError("信号服务尚不可用")
        records = AppendOnlySignalLedger(self.ledger_directory).read_all()
        for record in records:
            event = record["payload"]
            if event.get("event_type") == "SIGNAL_DETECTED" and event["signal"].get("signal_id") == signal_id: return event["signal"]
        raise ValueError("信号不存在")

    def _candidate_scope(self, signal):
        included = set(); truncated = set()
        for record in AppendOnlySignalLedger(self.ledger_directory).read_all():
            event = record["payload"]
            if event.get("event_type") == "DAILY_SCOPE_RECONCILED" and event.get("signal_day_utc") == signal["signal_day_utc"]:
                included = set(event.get("included_signal_ids", [])); truncated = set(event.get("truncated_signal_ids", []))
        if signal["signal_id"] in included: return "INCLUDED"
        if signal["signal_id"] in truncated: return "TRUNCATED"
        return "PENDING_SCOPE"

    def _validate_cooldown(self, signal):
        signal_time = int(signal["signal_time_ms"])
        cutoff = signal_time - 240 * 60_000
        for event in self._read_interactions():
            if event.get("event_type") != "MANUAL_EXECUTION_RECORDED" or event.get("exit_reason") != "STOP": continue
            try: prior = self._signal(event["signal_id"])
            except ValueError: continue
            exited_at = int(event["exited_at_ms"])
            if prior["symbol"] == signal["symbol"] and prior["direction"] == signal["direction"] and cutoff <= exited_at <= signal_time: raise ValueError("同标的同方向止损后仍在 4 小时冷却期")

    @staticmethod
    def _validate_stop(direction, entry, stop):
        if (direction == "LONG" and stop >= entry) or (direction == "SHORT" and stop <= entry): raise ValueError("止损价必须位于进场价的亏损方向")

    def _interaction_ledger(self):
        ledger = AppendOnlySignalLedger(self.interaction_directory); ledger.open(INTERACTION_MANIFEST); return ledger
    def _read_interactions(self):
        if not (self.interaction_directory / "manifest.json").exists(): return []
        ledger = AppendOnlySignalLedger(self.interaction_directory)
        ledger.open(INTERACTION_MANIFEST)
        return [row["payload"] for row in ledger.read_all()]
    def _events_for(self, signal_id): return [row for row in self._read_interactions() if row.get("signal_id") == signal_id]

    def _empty(self, day, status):
        return {"protocol": "ORBIT_SIGNAL_DESK_V2", "day_utc": day, "health": {"status": status, "manifest_exists": False, "events_exists": False, "event_count": 0, "head_hash": None, "latest_recorded_at_ms": None, "latest_scan": None, "error_type": None}, "summary": {"signal_count": 0, "included_count": 0, "truncated_count": 0, "taken_count": 0, "skipped_count": 0, "undecided_count": 0, "open_count": 0, "closed_count": 0, "push_succeeded_count": 0, "realized_r_total": 0.0}, "discipline": {"stop_attached": "ENFORCED", "averaging_down": "BLOCKED", "cooldown_after_stop_minutes": 240, "cooldown_symbols": [], "outside_signal_trade": "BLOCKED", "outside_signal_count": 0}, "review": {}, "signals": []}

    @staticmethod
    def _public_event(event):
        if not event: return {}
        return {key: value for key, value in event.items() if key not in {"provider_request_id", "actor"}}
