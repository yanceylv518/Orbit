from pathlib import Path

import pytest

from orbit.application.signals.desk import SignalDeskService
from orbit.infrastructure.persistence.signal_ledger import AppendOnlySignalLedger


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
    return SignalDeskService(tmp_path / "sig1", tmp_path / "sig2")


def test_missing_signal_service_is_an_honest_empty_state(tmp_path):
    result = SignalDeskService(tmp_path / "sig1", tmp_path / "sig2").snapshot(day="2026-08-14")
    assert result["health"]["status"] == "NOT_DEPLOYED"
    assert result["signals"] == []


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
