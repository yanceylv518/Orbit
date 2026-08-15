from pathlib import Path

import pytest

from orbit.application.signals.desk import SignalDeskService
from orbit.infrastructure.persistence.signal_ledger import AppendOnlySignalLedger


class FakeVault:
    def protect(self, value): return f"vault:{value[::-1]}"
    def fingerprint(self, value): return f"fp-{value[-3:]}"


class FakeNotifier:
    def __init__(self, sent): self.sent = sent
    def send(self, payload): self.sent.append(payload); return {"status": "DELIVERED", "request_id": "req-1"}


class FakeAccounts:
    def __init__(self): self.items = {"signal-sub": {"id": "signal-sub"}, "tb4": {"id": "tb4"}}
    def account_by_id(self, account_id): return self.items.get(account_id)


class FakeGateway:
    def user_trades(self, symbol):
        return [
            {"id": 11, "symbol": symbol, "side": "BUY", "positionSide": "LONG", "time": 1786665700000, "price": "100", "qty": "1", "realizedPnl": "0"},
            {"id": 12, "symbol": symbol, "side": "SELL", "positionSide": "LONG", "time": 1786669300000, "price": "108", "qty": "1", "realizedPnl": "8"},
            {"id": 13, "symbol": symbol, "side": "BUY", "positionSide": "LONG", "time": 1786680000000, "price": "110", "qty": "1", "realizedPnl": "0"},
        ]


def _signal(signal_id="sig-1", *, day="2026-08-14", direction="LONG", signal_time_ms=1786665600000):
    chart = [
        {
            "open_time_ms": 1786622400000 + index * 900_000,
            "open": 88 + index * 0.24,
            "high": 88.8 + index * 0.24,
            "low": 87.5 + index * 0.24,
            "close": 88.35 + index * 0.24 + (0.2 if index % 3 else -0.1),
            "quote_volume": 2_000_000 + index * 40_000 if index < 47 else 11_000_000,
        }
        for index in range(48)
    ]
    return {
        "signal_id": signal_id,
        "signal_day_utc": day,
        "signal_time_ms": signal_time_ms,
        "symbol": "SOLUSDT",
        "direction": direction,
        "family_id": "BREAKOUT_MOMENTUM",
        "reference_entry_price": 100.0,
        "suggested_stop_price": 96.0 if direction == "LONG" else 104.0,
        "initial_risk_price": 4.0,
        "trend_strength_96": 3.2,
        "reason": {"relative_quote_volume": 4.5},
        "chart_before": chart,
    }


def _service(tmp_path: Path, signals=None):
    source = AppendOnlySignalLedger(tmp_path / "sig1")
    source.open({"protocol": "ORBIT_SIG1_SIGNAL_SERVICE_V1"})
    for item in signals or [_signal()]:
        source.append({"event_type": "SIGNAL_DETECTED", "recorded_at_ms": item["signal_time_ms"], "signal": item})
        source.append({"event_type": "SIM_TRADE_PLANNED", "recorded_at_ms": item["signal_time_ms"], "signal_id": item["signal_id"]})
    source.append({"event_type": "DAILY_SCOPE_RECONCILED", "recorded_at_ms": 1786665600000, "signal_day_utc": "2026-08-14", "included_signal_ids": [s["signal_id"] for s in signals or [_signal()]], "truncated_signal_ids": []})
    return SignalDeskService(tmp_path / "sig1", tmp_path / "sig2", clock_ms=lambda: 1786665700000)


def test_missing_signal_service_is_an_honest_empty_state(tmp_path):
    result = SignalDeskService(tmp_path / "sig1", tmp_path / "sig2").snapshot(day="2026-08-14")
    assert result["health"]["status"] == "NOT_DEPLOYED"
    assert result["signals"] == []
    assert result["operations"]["parameters"] == {
        "liquidity_threshold_usdt": 200000000,
        "candidate_limit": 30,
        "push_thresholds": {},
        "signal_interval": "15m",
    }


def test_snapshot_projects_rolling_counts_and_recent_real_sample(tmp_path):
    signals = [
        _signal("recent", day="2026-08-14"),
        _signal("within-window", day="2026-07-20"),
        _signal("outside-window", day="2026-07-15"),
    ]
    result = _service(tmp_path, signals).snapshot(day="2026-08-14")
    assert result["rolling_30d_by_family"]["BREAKOUT_MOMENTUM"] == 2
    assert result["recent_samples_by_family"]["BREAKOUT_MOMENTUM"]["signal_id"] == "recent"
    assert result["recent_samples_by_family"]["BREAKOUT_MOMENTUM"]["chart_before"]


def test_taken_decision_requires_valid_stop_and_is_append_only(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(ValueError, match="止损"):
        service.record_decision(signal_id="sig-1", decision="TAKEN", reason=None, stop_price=None, entry_price=100, actor="admin")
    result = service.record_decision(signal_id="sig-1", decision="TAKEN", reason=None, stop_price=96, entry_price=100, actor="admin")
    assert result["summary"]["taken_count"] == 1
    assert result["discipline"]["stop_attached"] == "ENFORCED"
    with pytest.raises(ValueError, match="不允许覆盖"):
        service.record_decision(signal_id="sig-1", decision="SKIPPED", reason="changed mind", stop_price=None, entry_price=None, actor="admin")


def test_three_books_separate_all_chosen_and_actual(tmp_path):
    service = _service(tmp_path)
    service.record_decision(signal_id="sig-1", decision="TAKEN", reason=None, stop_price=96, entry_price=100, actor="admin")
    result = service.record_execution(signal_id="sig-1", entry_price=100, exit_price=108, exited_at_ms=1786670000000, exit_reason="MANUAL", actor="admin")
    assert result["review"]["all_signal_simulation"]["count"] == 1
    assert result["review"]["chosen_signal_simulation"]["count"] == 1
    assert result["review"]["actual_manual"]["count"] == 1
    assert result["review"]["actual_manual"]["realized_r_total"] == 2
    with pytest.raises(ValueError, match="禁止覆盖或亏损加仓"):
        service.record_execution(signal_id="sig-1", entry_price=99, exit_price=101, exited_at_ms=1786670100000, exit_reason="MANUAL", actor="admin")


def test_tampered_source_ledger_fails_closed(tmp_path):
    service = _service(tmp_path)
    path = tmp_path / "sig1" / "events.jsonl"
    path.write_text(path.read_text(encoding="utf-8").replace("SOLUSDT", "BTCUSDT", 1), encoding="utf-8")
    result = service.snapshot(day="2026-08-14")
    assert result["health"]["status"] == "LEDGER_ERROR"
    assert result["health"]["manifest_exists"] is True


def test_truncated_signal_cannot_be_taken_but_remains_visible(tmp_path):
    service = _service(tmp_path)
    ledger = AppendOnlySignalLedger(tmp_path / "sig1")
    ledger.append({"event_type": "DAILY_SCOPE_RECONCILED", "recorded_at_ms": 1786665601000, "signal_day_utc": "2026-08-14", "included_signal_ids": [], "truncated_signal_ids": ["sig-1"]})
    snapshot = service.snapshot(day="2026-08-14")
    assert snapshot["signals"][0]["candidate_scope"] == "TRUNCATED"
    with pytest.raises(ValueError, match="只保留模拟记录"):
        service.record_decision(signal_id="sig-1", decision="TAKEN", reason=None, stop_price=96, entry_price=100, actor="admin")


def test_same_direction_stop_enforces_four_hour_cooldown(tmp_path):
    first = _signal("sig-1", signal_time_ms=1786665600000)
    second = _signal("sig-2", signal_time_ms=1786672800000)
    service = _service(tmp_path, [first, second])
    service.record_decision(signal_id="sig-1", decision="TAKEN", reason=None, stop_price=96, entry_price=100, actor="admin")
    service.record_execution(signal_id="sig-1", entry_price=100, exit_price=96, exited_at_ms=1786669200000, exit_reason="STOP", actor="admin")
    with pytest.raises(ValueError, match="4 小时冷却期"):
        service.record_decision(signal_id="sig-2", decision="TAKEN", reason=None, stop_price=96, entry_price=100, actor="admin")


def test_tampered_interaction_ledger_fails_closed(tmp_path):
    service = _service(tmp_path)
    service.record_decision(signal_id="sig-1", decision="TAKEN", reason=None, stop_price=96, entry_price=100, actor="admin")
    path = tmp_path / "sig2" / "events.jsonl"
    path.write_text(path.read_text(encoding="utf-8").replace('"TAKEN"', '"SKIPPED"', 1), encoding="utf-8")
    result = service.snapshot(day="2026-08-14")
    assert result["health"]["status"] == "LEDGER_ERROR"
    assert result["health"]["error_scope"] == "SIG2_INTERACTIONS"
    assert result["signals"][0]["decision"] is None


def test_pushover_configuration_is_encrypted_and_testable(tmp_path):
    sent = []
    service = _service(tmp_path)
    service.vault = FakeVault()
    service.notifier_factory = lambda **_refs: FakeNotifier(sent)
    snapshot = service.configure_pushover(api_token="secret-token", user_key="secret-user", enabled=True, actor="admin")
    assert snapshot["operations"]["pushover"]["configured"] is True
    assert "secret-token" not in str(snapshot)
    assert "secret-user" not in str(snapshot)
    assert service.test_pushover(actor="admin")["ok"] is True
    assert sent[0]["title"] == "Orbit 测试通知"


def test_service_control_and_tb4_binding_guard(tmp_path):
    service = _service(tmp_path)
    service.account_repository = FakeAccounts()
    service.binding_reader = lambda: [{"exchange_account_id": "tb4", "status": "ACTIVE"}]
    with pytest.raises(ValueError, match="物理隔离"):
        service.bind_account(account_id="tb4", actor="admin")
    result = service.bind_account(account_id="signal-sub", actor="admin")
    assert result["operations"]["binding"]["account_id"] == "signal-sub"
    result = service.set_service_enabled(enabled=True, actor="admin")
    assert result["operations"]["service"]["enabled"] is True


def test_bound_account_auto_pairs_trade_and_marks_outside_trade(tmp_path):
    service = _service(tmp_path)
    service.account_repository = FakeAccounts()
    service.gateway_factory = lambda _account: FakeGateway()
    service.bind_account(account_id="signal-sub", actor="admin")
    service.record_decision(signal_id="sig-1", decision="TAKEN", reason=None, stop_price=96, entry_price=100, actor="admin")
    result = service.sync_bound_account("signal-sub")
    assert result == {"status": "SYNCED", "imported_count": 3, "paired_execution_count": 1, "outside_signal_count": 1}
    snapshot = service.snapshot(day="2026-08-14")
    assert snapshot["review"]["actual_manual"]["count"] == 1
    assert snapshot["discipline"]["outside_signal_count"] == 1


def test_bound_account_sync_fails_closed_if_tb4_claims_account_later(tmp_path):
    service = _service(tmp_path)
    service.account_repository = FakeAccounts()
    service.gateway_factory = lambda _account: FakeGateway()
    service.bind_account(account_id="signal-sub", actor="admin")
    service.binding_reader = lambda: [{"exchange_account_id": "signal-sub", "status": "ACTIVE"}]
    assert service.sync_bound_account("signal-sub") == {
        "status": "BINDING_CONFLICT",
        "reason": "ACCOUNT_USED_BY_TB4",
    }


def test_expired_signal_cannot_be_marked_taken_or_skipped(tmp_path):
    service = _service(tmp_path)
    service.clock_ms = lambda: 1786665600000 + 31 * 60_000
    for decision in ("TAKEN", "SKIPPED"):
        with pytest.raises(ValueError, match="30"):
            service.record_decision(
                signal_id="sig-1",
                decision=decision,
                reason="too late",
                stop_price=96 if decision == "TAKEN" else None,
                entry_price=100 if decision == "TAKEN" else None,
                actor="admin",
            )


def test_discipline_relaxation_waits_24_hours(tmp_path):
    now = 1786665600000
    service = _service(tmp_path)
    service.clock_ms = lambda: now
    result = service.request_discipline_change(setting="daily_loss_limit_r", value=-5, actor="admin")
    assert result["effective_at_ms"] == now + 24 * 60 * 60_000
    assert service.snapshot(day="2026-08-14")["operations"]["pending_discipline_changes"]


def test_web_alerts_preserve_failure_history_and_mark_recovery(tmp_path):
    service = _service(tmp_path)
    service.set_service_enabled(enabled=True, actor="admin")
    ledger = service._interaction_ledger()
    ledger.append({"event_type": "SERVICE_SCAN_FAILED", "recorded_at_ms": 1786665700100, "error_type": "TimeoutError"})
    failed = service.snapshot(day="2026-08-14")
    scan_alert = next(row for row in failed["alerts"] if row["alert_id"].startswith("SERVICE_SCAN_FAILED"))
    assert scan_alert["status"] == "ACTIVE"
    assert failed["alert_summary"]["error"] >= 1
    ledger.append({"event_type": "SERVICE_HEARTBEAT", "recorded_at_ms": 1786665700200, "status": "RUNNING"})
    recovered = service.snapshot(day="2026-08-14")
    scan_alert = next(row for row in recovered["alerts"] if row["alert_id"].startswith("SERVICE_SCAN_FAILED"))
    assert scan_alert["status"] == "RECOVERED"
