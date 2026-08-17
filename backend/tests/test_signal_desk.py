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


class FakeReplay:
    def replay(self, contract, *, days, end_time_ms):
        volume = float(contract["signals"]["BREAKOUT_MOMENTUM"]["minimum_relative_quote_volume"])
        rows = [_signal("same")]
        if volume < 2:
            rows.append(_signal("added", signal_time_ms=1786665601000))
        return {"status": "READY", "signals": rows, "summary": {"total": len(rows), "truncated": 0, "by_family": {"BREAKOUT_MOMENTUM": len(rows)}, "by_symbol": {"SOLUSDT": len(rows)}}}


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
    import json
    contract = json.loads((Path(__file__).parents[2] / "config/signals/sig1.v1.json").read_text(encoding="utf-8"))
    return SignalDeskService(tmp_path / "sig1", tmp_path / "sig2", spec=contract, clock_ms=lambda: 1786665700000)


def test_missing_signal_service_is_an_honest_empty_state(tmp_path):
    result = SignalDeskService(tmp_path / "sig1", tmp_path / "sig2").snapshot(day="2026-08-14")
    assert result["health"]["status"] == "NOT_DEPLOYED"
    assert result["signals"] == []
    assert result["operations"]["parameters"] == {
        "liquidity_threshold_usdt": 2000000,
        "liquidity_lookback_complete_utc_days": 30,
        "maximum_tracked_markets": 300,
        "truncated_market_count": 0,
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
    assert result["recent_samples_by_family"]["BREAKOUT_MOMENTUM"][0]["signal_id"] == "recent"
    assert result["recent_samples_by_family"]["BREAKOUT_MOMENTUM"][0]["chart_before"]
    performance = result["rolling_30d_performance_by_family"]["BREAKOUT_MOMENTUM"]
    assert performance == {"signal_count": 2, "closed_count": 0, "open_count": 2, "realized_r_total": 0.0, "wins": 0, "losses": 0, "curve": []}
    assert result["rolling_30d_daily_average_by_family"]["BREAKOUT_MOMENTUM"] == 0.07


def test_family_read_model_keeps_six_samples_and_real_closed_results(tmp_path):
    signals = [_signal(f"sig-{index}", signal_time_ms=1786665600000 + index * 1000) for index in range(7)]
    service = _service(tmp_path, signals)
    ledger = AppendOnlySignalLedger(tmp_path / "sig1")
    ledger.append({"event_type": "SIM_TRADE_CLOSED", "recorded_at_ms": 1786665700000, "signal_id": "sig-0", "exited_at_ms": 1786665700000, "realized_r": 1.25, "chart_after": []})
    result = service.snapshot(day="2026-08-14")
    assert len(result["recent_samples_by_family"]["BREAKOUT_MOMENTUM"]) == 6
    performance = result["rolling_30d_performance_by_family"]["BREAKOUT_MOMENTUM"]
    assert performance["closed_count"] == 1
    assert performance["open_count"] == 6
    assert performance["realized_r_total"] == 1.25
    assert performance["wins"] == 1
    assert performance["curve"] == [{"recorded_at_ms": 1786665700000, "cumulative_r": 1.25}]
    presentation = result["operations"]["strategy_families"]["BREAKOUT_MOMENTUM"]
    assert presentation["name"] == "放量突破"
    assert any("入账" in row and "不推送" in row for row in presentation["exclusions"])
    assert presentation["thesis"]
    assert presentation["tradeFlow"]


def test_latest_round_is_split_by_family_and_never_invents_missing_counts(tmp_path):
    service = _service(tmp_path)
    ledger = AppendOnlySignalLedger(tmp_path / "sig1")
    ledger.append({
        "event_type": "SCAN_COMPLETED", "recorded_at_ms": 1786665600100,
        "signal_close_time_ms": 1786665600000, "market_window_count": 218,
        "detected_signal_count": 4, "new_signal_count": 1,
        "detected_by_family": {"BREAKOUT_MOMENTUM": 2, "OVERSOLD_REBOUND": 2, "SUSTAINED_STRENGTH": 0},
        "new_by_family": {"BREAKOUT_MOMENTUM": 1, "OVERSOLD_REBOUND": 0, "SUSTAINED_STRENGTH": 0},
    })
    result = service.snapshot(day="2026-08-14")
    breakout = result["operations"]["latest_round_by_family"]["BREAKOUT_MOMENTUM"]
    oversold = result["operations"]["latest_round_by_family"]["OVERSOLD_REBOUND"]
    assert breakout["available"] is True
    assert breakout["complete_family_counts"] is True
    assert breakout["market_count"] == 218
    assert breakout["detected_count"] == 2
    assert breakout["recorded_count"] == 1
    assert oversold["detected_count"] == 2
    assert oversold["recorded_count"] == 0

    old = _service(tmp_path / "old")
    old_ledger = AppendOnlySignalLedger(tmp_path / "old" / "sig1")
    old_ledger.append({"event_type": "SCAN_COMPLETED", "recorded_at_ms": 1786665600100, "signal_close_time_ms": 1786665600000, "market_window_count": 10, "detected_signal_count": 1, "new_signal_count": 1})
    old_round = old.snapshot(day="2026-08-14")["operations"]["latest_round_by_family"]["BREAKOUT_MOMENTUM"]
    assert old_round["complete_family_counts"] is False
    assert old_round["detected_count"] is None


def test_family_disable_requires_reason_and_reason_is_audited_and_visible(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(ValueError, match="必须填写原因"):
        service.set_family_enabled(family_id="OVERSOLD_REBOUND", enabled=False, reason="", actor="admin")
    result = service.set_family_enabled(family_id="OVERSOLD_REBOUND", enabled=False, reason="研究显示下行阶段无效", actor="admin")
    control = result["operations"]["family_controls"]["OVERSOLD_REBOUND"]
    assert control["enabled"] is False
    assert control["disabled_reason"] == "研究显示下行阶段无效"
    events = service._read_interactions()
    assert events[-1]["event_type"] == "SIGNAL_FAMILY_CONTROL_CHANGED"
    assert events[-1]["actor"] == "admin"


def test_configuration_change_is_validated_audited_and_immediately_visible(tmp_path):
    service = _service(tmp_path)
    result = service.update_configuration(
        values={"pullback_start_days": 5, "breakout_volume": 2.5},
        note="扩大急跌起点观察窗口",
        actor="admin",
    )
    configuration = result["operations"]["configuration"]
    values = {row["key"]: row["value"] for row in configuration["fields"]}
    assert values["pullback_start_days"] == 5
    assert values["collapse_days"] == 14
    assert values["strength_high_days"] == 14
    assert configuration["revision"] == 1
    assert configuration["scope_version"] == "SIG3B_SCOPE_V1"
    event = service._read_interactions()[-1]
    assert event["changes"]["pullback_start_days"] == {"old": 3, "new": 5}
    assert event["note"] == "扩大急跌起点观察窗口"
    assert event["actor"] == "admin"


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"pullback_start_days": 0}, "允许范围"),
        ({"collapse_days": "不是数字"}, "必须填写数字"),
        ({"strength_short_volume_days": 10, "strength_long_volume_days": 3}, "必须小于"),
    ],
)
def test_configuration_rejects_invalid_human_inputs(tmp_path, values, message):
    with pytest.raises(ValueError, match=message):
        _service(tmp_path).update_configuration(values=values, note=None, actor="admin")


def test_unsaved_replay_preview_returns_diff_without_writing_configuration(tmp_path):
    service = _service(tmp_path)
    service.replay_service = FakeReplay()
    before_events = service._read_interactions()
    result = service.replay(days=7, preview_values={"breakout_volume": 1.5})
    assert result["saved"] is False
    assert result["comparison"]["before"]["total"] == 1
    assert result["comparison"]["after"]["total"] == 2
    assert [row["signal_id"] for row in result["comparison"]["added"]] == ["added"]
    assert service._read_interactions() == before_events


def test_replay_page_has_fixed_discipline_and_no_parameter_profit_ranking():
    template = (Path(__file__).parents[2] / "frontend/src/pages/SignalPage.vue").read_text(encoding="utf-8")
    assert "历史回放不预测未来。规则变更的真实效果，由信号模拟账在未来数据上裁决。" in template
    for forbidden in ("最优参数", "参数收益排行榜", "按历史收益排序"):
        assert forbidden not in template


def test_sig5_moves_parameters_to_strategy_detail_and_uses_honest_states():
    root = Path(__file__).parents[2] / "frontend/src/pages"
    signal_page = (root / "SignalPage.vue").read_text(encoding="utf-8")
    detail_page = (root / "StrategyCenterPage.vue").read_text(encoding="utf-8")
    strategy_page = (root / "StrategyPage.vue").read_text(encoding="utf-8")
    assert "信号参数配置" not in signal_page
    assert "configuration-panel" not in signal_page
    assert "familyFields" in detail_page
    assert "共用" in detail_page
    assert "const definitions" not in detail_page
    assert "未部署 / 状态未知" in detail_page
    assert "已启用但扫描超时" in strategy_page
    for page in (signal_page, detail_page, strategy_page):
        assert "TB4" not in page
    # 代号过滤不得靠字符类拆分绕过上面这条断言——后端名称已干净，兜底须删除。
    for page in (detail_page, strategy_page):
        assert "T[B]4" not in page
    # 过滤必须按后端给的 family 归属，不得匹配中文分组标签（改一次措辞就会静默清空整页）。
    assert "field.family" in detail_page
    assert 'field.group === "通用"' not in detail_page and "field.group === '通用'" not in detail_page


def test_every_signal_strategy_page_can_reach_its_own_and_the_shared_parameters():
    """SIG-5 打回项：币池两项曾在界面上完全不可达，突破族曾只剩 1 项。"""
    import json as json_module

    from orbit.application.signals.configuration import public_configuration

    contract = json_module.loads((Path(__file__).parents[2] / "config/signals/sig1.v1.json").read_text(encoding="utf-8"))
    fields = public_configuration(contract, 0)["fields"]
    shared = {row["key"] for row in fields if row["family"] is None} - {"daily_push_limit"}
    assert shared == {"liquidity_minimum", "liquidity_days", "maximum_tracked_markets", "daily_candidate_limit"}

    def page_keys(family):
        return {row["key"] for row in fields if row["key"] != "daily_push_limit" and (row["family"] is None or row["family"] == family)}

    assert page_keys("BREAKOUT_MOMENTUM") == shared | {"breakout_channel", "breakout_volume"}
    assert page_keys("OVERSOLD_REBOUND") == shared | {
        "pullback_drop", "pullback_return_candles", "pullback_cycle",
        "collapse_days", "collapse_drawdown", "pullback_start_days", "pullback_start_drawdown",
    }
    assert page_keys("SUSTAINED_STRENGTH") == shared | {
        "strength_quantile", "strength_short_volume_days", "strength_long_volume_days",
        "strength_volume_ratio", "strength_high_days", "strength_high_distance", "strength_cooldown_hours",
    }
    # 每一个可配置项都必须至少能在一个策略页上改到；推送上限归信号页。
    reachable = page_keys("BREAKOUT_MOMENTUM") | page_keys("OVERSOLD_REBOUND") | page_keys("SUSTAINED_STRENGTH")
    assert {row["key"] for row in fields} - reachable == {"daily_push_limit"}


def test_field_family_comes_from_the_spec_path_not_the_display_label():
    from orbit.application.signals.configuration import FIELDS, field_family

    for _, path, *_ in FIELDS:
        family = field_family(path)
        assert family == (path[1] if path[0] == "signals" else None)


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
