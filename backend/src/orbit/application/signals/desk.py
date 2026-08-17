from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Callable

from orbit.infrastructure.persistence.signal_ledger import AppendOnlySignalLedger, canonical_json
from orbit.application.signals.configuration import (
    apply_values,
    configuration_values,
    effective_spec,
    public_configuration,
    scope_version,
    validate_values,
)


INTERACTION_MANIFEST = {
    "protocol": "ORBIT_SIG2_INTERACTION_LEDGER_V1",
    "write_model": "APPEND_ONLY_SHA256_CHAIN",
    "signal_source": "ORBIT_SIG1_SIGNAL_SERVICE_V1",
    "cooldown_after_stop_minutes": 240,
    "constraints": ["STOP_REQUIRED", "NO_AVERAGING_DOWN", "COOLDOWN_AFTER_STOP", "SIGNAL_REQUIRED"],
}

SIGNAL_FAMILY_PRESENTATION = {
    "BREAKOUT_MOMENTUM": {
        "name": "放量突破", "summary": "价格冲出近期区间且成交明显活跃时发出提醒。",
        "indicators": [["通道高点", "近期已收盘价格的最高位置。"], ["成交量比", "当前成交额相对历史窗口的放大倍数。"], ["趋势强度", "用方向对齐的价格变化排序机会。"]],
        "exclusions": ["交易性未达门槛或 K 线不完整时不动作。", "收盘未突破通道高点或放量不足时不动作。", "超过每日处理上限的信号仍入账和模拟，不推送。"],
        "steps": [["收盘", "只读取完整 15 分钟 K 线。"], ["准入", "按 30 日成交性选出可处理市场。"], ["命中", "检查通道突破与成交量。"], ["入账", "全部信号进入模拟账。"], ["推送", "仅对限额内机会发送提醒。"]],
    },
    "OVERSOLD_REBOUND": {
        "name": "高位回调", "summary": "寻找仍在上升趋势、从高位急跌后开始企稳的市场。",
        "indicators": [["短期跌幅", "衡量观察窗口内的急跌。"], ["长周期方向", "只在允许的大级别状态中观察回调。"], ["双重高点", "同时检查中期崩塌和急跌起点。"]],
        "exclusions": ["长周期不是允许状态时不动作。", "距中期高点回撤达崩塌上限时不动作。", "急跌起点本就远离近期高点时不动作。", "超过每日处理上限的信号仍入账和模拟，不推送。"],
        "steps": [["收盘", "只读取完整 15 分钟 K 线。"], ["准入", "检查交易性与长周期方向。"], ["防崩塌", "先检查中期和起点高位保护。"], ["企稳", "急跌后收盘不再走弱才命中。"], ["入账与推送", "全量记录，限额内推送。"]],
    },
    "SUSTAINED_STRENGTH": {
        "name": "持续强势", "summary": "寻找价格与成交持续配合、方向没有转弱的市场。",
        "indicators": [["趋势强度", "要求方向对齐强度达到设定分位。"], ["持续量比", "近期均量相对基准均量不能转弱。"], ["距高点比例", "价格必须仍在高位区域。"]],
        "exclusions": ["长周期不向上时不动作。", "趋势强度、持续量比或高位距离任一不达标时不动作。", "同币种冷却期内不重复提醒。", "超过每日处理上限的信号仍入账和模拟，不推送。"],
        "steps": [["收盘", "只读取完整 15 分钟 K 线。"], ["方向", "先检查长周期是否向上。"], ["持续性", "检查强度、量能和高位距离。"], ["冷却", "已提醒币种在冷却期内不重复。"], ["入账与推送", "全量记录，限额内推送。"]],
    },
}


class SignalDeskService:
    """SIG-2 command/read model over immutable SIG-1 and interaction ledgers."""

    def __init__(
        self,
        ledger_directory: Path,
        interaction_directory: Path | None = None,
        *,
        vault: Any | None = None,
        notifier_factory: Callable[..., Any] | None = None,
        account_repository: Any | None = None,
        binding_reader: Callable[[], list[dict[str, Any]]] | None = None,
        gateway_factory: Callable[[dict[str, Any]], Any] | None = None,
        replay_service: Any | None = None,
        spec: dict[str, Any] | None = None,
        clock_ms: Callable[[], int] | None = None,
    ):
        self.ledger_directory = ledger_directory
        self.interaction_directory = interaction_directory or ledger_directory.parent / "sig2"
        self.vault = vault
        self.notifier_factory = notifier_factory
        self.account_repository = account_repository
        self.binding_reader = binding_reader or (lambda: [])
        self.gateway_factory = gateway_factory
        self.replay_service = replay_service
        self.spec = spec or {}
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def snapshot(self, *, day: str | None = None, limit: int = 200) -> dict[str, Any]:
        selected_day = day or self._clock_day()
        source = self._read_source(selected_day)
        if source["health"]["status"] == "NOT_DEPLOYED":
            try:
                interactions = self._read_interactions()
            except Exception:
                interactions = []
            source["operations"] = self._operations(interactions, source["health"], [])
            return source
        if source["health"]["status"] == "LEDGER_ERROR":
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
            source["discipline"] = self._discipline(all_rows, [])
            source["review"] = self._review(all_rows)
            source["health"].update(
                {"status": "LEDGER_ERROR", "error_type": type(exc).__name__, "error_scope": "SIG2_INTERACTIONS"}
            )
            source["alerts"] = [self._alert("INTERACTION_LEDGER_ERROR", "CRITICAL", "账本", "人工留痕账本校验失败", "为保护证据，人工决定和成交入口已关闭。", self.clock_ms())]
            source["alert_summary"] = self._alert_summary(source["alerts"])
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
        family_rankings: dict[str, dict[str, int]] = {}
        for family in {str(row.get("family_id")) for row in all_rows}:
            ranked = sorted((row for row in all_rows if str(row.get("family_id")) == family), key=lambda row: -float(row.get("trend_strength_96") or 0))
            family_rankings[family] = {row["signal_id"]: index + 1 for index, row in enumerate(ranked)}
        for row in all_rows:
            row["decision"] = self._public_event(decisions.get(row["signal_id"])) or None
            row["manual_execution"] = self._public_event(executions.get(row["signal_id"])) or None
            row["expires_at_ms"] = int(row["signal_time_ms"]) + 30 * 60_000
            row["expired"] = self.clock_ms() > row["expires_at_ms"]
            row["trend_strength_rank"] = family_rankings[str(row.get("family_id"))][row["signal_id"]]
            row["trend_strength_rank_total"] = len(family_rankings[str(row.get("family_id"))])
        source["signals"] = all_rows[: max(1, min(int(limit), 1000))]
        source["summary"] = self._summary(all_rows)
        source["discipline"] = self._discipline(all_rows, interactions)
        active_cooldowns = {(row["symbol"], row["direction"]): row for row in source["discipline"].get("cooldowns", [])}
        for row in all_rows:
            cooldown = active_cooldowns.get((row["symbol"], row["direction"]))
            row["action_block"] = ({"reason": "COOLDOWN_AFTER_STOP", "until_ms": cooldown["until_ms"]} if cooldown else ({"reason": "DAILY_LOSS_CIRCUIT", "until_ms": None} if source["discipline"]["circuit_breaker_active"] else None))
        source["review"] = self._review(all_rows)
        source["operations"] = self._operations(interactions, source["health"], all_rows)
        source["alerts"] = self._alerts(source.pop("_source_alerts", []), interactions, source["health"], source["discipline"], source["operations"])
        source["alert_summary"] = self._alert_summary(source["alerts"])
        source["interaction_ledger"] = {
            "event_count": len(interactions),
            "append_only": True,
        }
        return source

    def configure_pushover(self, *, api_token: str, user_key: str, enabled: bool, actor: str) -> dict[str, Any]:
        if self.vault is None:
            raise ValueError("服务器凭证库不可用，无法保存 Pushover 配置")
        if not api_token.strip() or not user_key.strip():
            raise ValueError("请同时填写 Pushover API Token 和 User Key")
        token_ref = self.vault.protect(api_token.strip())
        user_ref = self.vault.protect(user_key.strip())
        self._interaction_ledger().append({
            "event_type": "PUSHOVER_CONFIGURATION_CHANGED",
            "recorded_at_ms": self.clock_ms(),
            "enabled": bool(enabled),
            "api_token_reference": token_ref,
            "user_key_reference": user_ref,
            "api_token_fingerprint": self.vault.fingerprint(api_token.strip()),
            "user_key_fingerprint": self.vault.fingerprint(user_key.strip()),
            "actor": actor,
        })
        return self.snapshot()

    def test_pushover(self, *, actor: str) -> dict[str, Any]:
        config = self._latest_event("PUSHOVER_CONFIGURATION_CHANGED")
        if not config or self.notifier_factory is None:
            raise ValueError("请先保存 Pushover 配置")
        try:
            result = self.notifier_factory(
                api_token_reference=config["api_token_reference"],
                user_key_reference=config["user_key_reference"],
            ).send({"title": "Orbit 测试通知", "message": "Pushover 配置可用。", "priority": 0})
        except Exception as exc:
            self._interaction_ledger().append({"event_type": "PUSHOVER_TEST_FAILED", "recorded_at_ms": self.clock_ms(), "error_type": type(exc).__name__, "actor": actor})
            raise ValueError(f"测试通知发送失败：{type(exc).__name__}") from exc
        self._interaction_ledger().append({"event_type": "PUSHOVER_TEST_SUCCEEDED", "recorded_at_ms": self.clock_ms(), "actor": actor})
        return {"ok": True, "status": result.get("status", "DELIVERED")}

    def set_service_enabled(self, *, enabled: bool, actor: str) -> dict[str, Any]:
        self._interaction_ledger().append({"event_type": "SIGNAL_SERVICE_CONTROL_CHANGED", "recorded_at_ms": self.clock_ms(), "enabled": bool(enabled), "actor": actor})
        return self.snapshot()

    def set_family_enabled(self, *, family_id: str, enabled: bool, reason: str | None, actor: str) -> dict[str, Any]:
        allowed = {"BREAKOUT_MOMENTUM", "OVERSOLD_REBOUND", "SUSTAINED_STRENGTH"}
        if family_id not in allowed:
            raise ValueError("未知的信号类型")
        explanation = str(reason or "").strip()
        if not enabled and not explanation:
            raise ValueError("停用信号时必须填写原因")
        self._interaction_ledger().append({
            "event_type": "SIGNAL_FAMILY_CONTROL_CHANGED",
            "recorded_at_ms": self.clock_ms(), "family_id": family_id,
            "enabled": bool(enabled), "reason": explanation or None, "actor": actor,
        })
        return self.snapshot()

    def update_configuration(self, *, values: dict[str, Any], note: str | None, actor: str) -> dict[str, Any]:
        interactions = self._read_interactions()
        current = effective_spec(self.spec, interactions)
        clean = validate_values(values, current)
        old_values = configuration_values(current)
        changed = {
            key: {"old": old_values.get(key), "new": value}
            for key, value in clean.items()
            if old_values.get(key) != value
        }
        if not changed:
            raise ValueError("这些参数与当前生效值相同，无需保存")
        revision = sum(event.get("event_type") in {"SIGNAL_CONFIGURATION_CHANGED", "SIGNAL_FAMILY_CONTROL_CHANGED"} for event in interactions) + 1
        self._interaction_ledger().append({
            "event_type": "SIGNAL_CONFIGURATION_CHANGED",
            "recorded_at_ms": self.clock_ms(),
            "revision": revision,
            "scope_version": scope_version(revision),
            "values": {key: row["new"] for key, row in changed.items()},
            "changes": changed,
            "note": str(note or "").strip() or None,
            "actor": actor,
        })
        return self.snapshot()

    def replay(self, *, days: int, preview_values: dict[str, Any] | None = None) -> dict[str, Any]:
        if days not in {7, 30}:
            raise ValueError("回放时间只能选择过去 7 天或 30 天")
        if self.replay_service is None:
            raise ValueError("服务器历史回放服务尚未配置")
        interactions = self._read_interactions()
        active = effective_spec(self.spec, interactions)
        revision = sum(event.get("event_type") in {"SIGNAL_CONFIGURATION_CHANGED", "SIGNAL_FAMILY_CONTROL_CHANGED"} for event in interactions)
        active["scope_version"] = scope_version(revision)
        end_ms = self.clock_ms() // 900_000 * 900_000 - 1
        baseline = self.replay_service.replay(active, days=days, end_time_ms=end_ms)
        preview = None
        comparison = None
        if preview_values:
            clean = validate_values(preview_values, active)
            candidate = deepcopy(active)
            apply_values(candidate, clean)
            preview = self.replay_service.replay(candidate, days=days, end_time_ms=end_ms)
            comparison = self._replay_comparison(baseline, preview)
        return {"protocol": "ORBIT_SIGNAL_REPLAY_V1", "days": days, "baseline": baseline, "preview": preview, "comparison": comparison, "saved": False, "discipline_notice": "历史回放不预测未来。规则变更的真实效果，由信号模拟账在未来数据上裁决。"}

    @staticmethod
    def _replay_comparison(before, after):
        identity = lambda row: (row.get("symbol"), row.get("family_id"), row.get("signal_time_ms"), row.get("direction"))
        before_rows = {identity(row): row for row in before.get("signals", [])}
        after_rows = {identity(row): row for row in after.get("signals", [])}
        return {
            "before": before.get("summary", {}), "after": after.get("summary", {}),
            "added": [after_rows[key] for key in sorted(after_rows.keys() - before_rows.keys())],
            "removed": [before_rows[key] for key in sorted(before_rows.keys() - after_rows.keys())],
        }

    def bind_account(self, *, account_id: str | None, actor: str) -> dict[str, Any]:
        value = str(account_id or "").strip()
        if value:
            if self.account_repository is None or not self.account_repository.account_by_id(value):
                raise ValueError("所选账户不存在")
            conflict = next((row for row in self.binding_reader() if row.get("exchange_account_id") == value and row.get("status") in {"ACTIVE", "STOPPING"}), None)
            if conflict:
                raise ValueError("该账户已绑定 TB4 自动执行。信号服务必须使用物理隔离的独立子账户")
        self._interaction_ledger().append({"event_type": "SIGNAL_ACCOUNT_BINDING_CHANGED", "recorded_at_ms": self.clock_ms(), "account_id": value or None, "actor": actor})
        return self.snapshot()

    def request_discipline_change(self, *, setting: str, value: Any, actor: str) -> dict[str, Any]:
        allowed = {"daily_loss_limit_r", "consecutive_loss_limit"}
        if setting not in allowed:
            raise ValueError("该纪律参数不允许在页面放宽")
        effective_at = self.clock_ms() + 24 * 60 * 60_000
        self._interaction_ledger().append({"event_type": "DISCIPLINE_CHANGE_REQUESTED", "recorded_at_ms": self.clock_ms(), "setting": setting, "value": value, "effective_at_ms": effective_at, "actor": actor})
        return {"ok": True, "effective_at_ms": effective_at}

    def sync_bound_account(self, account_id: str, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        operations = self._operations(self._read_interactions(), {}, [])
        if operations["binding"]["account_id"] != account_id:
            return {"status": "NOT_BOUND"}
        conflict = next((row for row in self.binding_reader() if row.get("exchange_account_id") == account_id and row.get("status") in {"ACTIVE", "STOPPING"}), None)
        if conflict:
            return {"status": "BINDING_CONFLICT", "reason": "ACCOUNT_USED_BY_TB4"}
        if self.account_repository is None or self.gateway_factory is None:
            return {"status": "UNAVAILABLE"}
        account = self.account_repository.account_by_id(account_id)
        if not account:
            return {"status": "ACCOUNT_MISSING"}
        gateway = self.gateway_factory(account)
        source = self._read_source(self._clock_day())
        signals = source.get("_all_signals", [])
        taken = {row["signal_id"]: row for row in signals if (self._decision_for(row["signal_id"]) or {}).get("decision") == "TAKEN"}
        symbols = sorted({row["symbol"] for row in signals})
        imported = 0; outside = 0; paired = 0
        for symbol in symbols:
            trades = sorted(gateway.user_trades(symbol), key=lambda row: int(row.get("time") or 0))
            consumed: dict[str, dict[str, Any]] = {}
            for signal in [row for row in taken.values() if row["symbol"] == symbol and not any(e.get("event_type") == "MANUAL_EXECUTION_RECORDED" for e in self._events_for(row["signal_id"]))]:
                decision = self._decision_for(signal["signal_id"]) or {}
                entry = next((trade for trade in trades if self._trade_is_entry(trade, signal) and int(signal["signal_time_ms"]) <= int(trade.get("time") or 0) <= int(signal["signal_time_ms"]) + 30 * 60_000), None)
                if entry is None: continue
                exit_trade = next((trade for trade in trades if int(trade.get("time") or 0) > int(entry.get("time") or 0) and self._trade_is_exit(trade, signal)), None)
                if exit_trade is None: continue
                entry_price = float(entry.get("price") or 0); exit_price = float(exit_trade.get("price") or 0)
                stop = float(decision.get("stop_price") or signal["suggested_stop_price"])
                sign = 1.0 if signal["direction"] == "LONG" else -1.0
                pnl = sign * (exit_price - entry_price); risk = abs(entry_price - stop)
                entry_id = str(entry.get("id") or entry.get("tradeId")); exit_id = str(exit_trade.get("id") or exit_trade.get("tradeId"))
                self._interaction_ledger().append({"event_type": "MANUAL_EXECUTION_RECORDED", "recorded_at_ms": self.clock_ms(), "signal_id": signal["signal_id"], "account_id": account_id, "entry_trade_ids": [entry_id], "exit_trade_ids": [exit_id], "entry_price": entry_price, "exit_price": exit_price, "exited_at_ms": int(exit_trade.get("time") or 0), "exit_reason": "STOP" if float(exit_trade.get("realizedPnl") or 0) < 0 and abs(exit_price - stop) / max(stop, 1e-12) < 0.003 else "ACCOUNT_CLOSE", "gross_return_pct": pnl / entry_price * 100, "realized_r": pnl / risk if risk else 0, "source": "BINANCE_AUTO_PAIR"})
                consumed[entry_id] = signal; consumed[exit_id] = signal; paired += 1
            for trade in trades:
                trade_id = str(trade.get("id") or trade.get("tradeId") or "")
                if not trade_id or self._trade_imported(account_id, trade_id):
                    continue
                matched = consumed.get(trade_id)
                self._interaction_ledger().append({
                    "event_type": "ACCOUNT_TRADE_PAIRED" if matched else "OUTSIDE_SIGNAL_TRADE_DETECTED",
                    "recorded_at_ms": self.clock_ms(), "account_id": account_id, "trade_id": trade_id,
                    "signal_id": matched.get("signal_id") if matched else None, "symbol": symbol,
                    "side": trade.get("side"), "position_side": trade.get("positionSide"),
                    "trade_time_ms": int(trade.get("time") or 0), "price": float(trade.get("price") or 0),
                    "quantity": float(trade.get("qty") or 0), "realized_pnl": float(trade.get("realizedPnl") or 0),
                })
                imported += 1; outside += int(not matched)
        for position in (snapshot or {}).get("positions", []):
            symbol = str(position.get("symbol") or ""); amount = float(position.get("position_amt") or 0)
            direction = str(position.get("position_side") or ("LONG" if amount > 0 else "SHORT")).upper()
            planned = any(row["symbol"] == symbol and row["direction"] == direction for row in taken.values())
            position_key = f"position:{symbol}:{direction}:{position.get('update_time') or 'current'}"
            if not planned and not self._trade_imported(account_id, position_key):
                self._interaction_ledger().append({"event_type": "OUTSIDE_SIGNAL_TRADE_DETECTED", "recorded_at_ms": self.clock_ms(), "account_id": account_id, "trade_id": position_key, "signal_id": None, "symbol": symbol, "position_side": direction, "quantity": abs(amount), "source": "OPEN_POSITION_RECONCILIATION"})
                outside += 1
        return {"status": "SYNCED", "imported_count": imported, "paired_execution_count": paired, "outside_signal_count": outside}

    def record_decision(
        self, *, signal_id: str, decision: str, reason: str | None, stop_price: float | None,
        entry_price: float | None, actor: str,
    ) -> dict[str, Any]:
        decision = decision.upper()
        if decision not in {"TAKEN", "SKIPPED"}:
            raise ValueError("decision must be TAKEN or SKIPPED")
        signal = self._signal(signal_id)
        if self.clock_ms() > int(signal["signal_time_ms"]) + 30 * 60_000:
            raise ValueError("信号已超过 30 分钟有效期，不能补标记")
        if self._candidate_scope(signal) != "INCLUDED":
            raise ValueError("该信号不在当日 30 条人工候选范围内，只保留模拟记录")
        existing = self._events_for(signal_id)
        if any(row.get("event_type") == "SIGNAL_DECISION_RECORDED" for row in existing):
            raise ValueError("该信号已经做过决定，追加账本不允许覆盖")
        if decision == "TAKEN":
            if self._discipline([], self._read_interactions())["circuit_breaker_active"]:
                raise ValueError("当日连续亏损/亏损限额熔断中，暂时不能登记新交易")
            if stop_price is None:
                raise ValueError("做了的信号必须同时记录止损价")
            actual_entry = float(entry_price if entry_price is not None else signal["reference_entry_price"])
            self._validate_stop(signal["direction"], actual_entry, float(stop_price))
            self._validate_cooldown(signal)
        event = {
            "event_type": "SIGNAL_DECISION_RECORDED",
            "recorded_at_ms": self.clock_ms(),
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
            "recorded_at_ms": self.clock_ms(),
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
            if manifest.get("protocol") not in {"ORBIT_SIG1_SIGNAL_SERVICE_V1", "ORBIT_SIG1_LEDGER_MANIFEST_V1"}:
                raise RuntimeError("SIG-1 manifest protocol mismatch")
            if manifest.get("protocol") == "ORBIT_SIG1_LEDGER_MANIFEST_V1" and manifest.get("signal_protocol") != "ORBIT_SIG1_SIGNAL_SERVICE_V1":
                raise RuntimeError("SIG-1 signal protocol mismatch")
            records = AppendOnlySignalLedger(self.ledger_directory).read_all()
        except Exception as exc:
            payload = self._empty(selected_day, "LEDGER_ERROR")
            payload["health"].update({"manifest_exists": True, "error_type": type(exc).__name__})
            return payload
        signals: dict[str, dict[str, Any]] = {}; trades: dict[str, dict[str, Any]] = {}
        pushes: dict[str, dict[str, Any]] = {}; scopes: dict[str, dict[str, Any]] = {}; latest_scan = None
        source_alerts: list[dict[str, Any]] = []
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
            if event_type in {"PUSH_FAILED", "PUSH_RETRY_EXHAUSTED", "PUSH_SUCCEEDED"}: source_alerts.append(self._public_event(event))
        scope = scopes.get(selected_day, {}); included = set(scope.get("included_signal_ids", [])); truncated = set(scope.get("truncated_signal_ids", []))
        rows = []
        for signal in signals.values():
            if signal.get("signal_day_utc") != selected_day: continue
            sid = signal["signal_id"]
            rows.append({**signal, "candidate_scope": "INCLUDED" if sid in included else "TRUNCATED" if sid in truncated else "PENDING_SCOPE", "simulation": self._public_event(trades.get(sid, {"status": "WAITING_ENTRY"})), "push": self._public_event(pushes.get(sid)) or None})
        rows.sort(key=lambda row: (-int(row.get("signal_time_ms", 0)), -float(row.get("trend_strength_96", 0)), str(row.get("signal_id", ""))))
        selected_date = datetime.strptime(selected_day, "%Y-%m-%d").date()
        rolling_cutoff = selected_date - timedelta(days=29)
        rolling_30d_by_family: dict[str, int] = {}
        recent_samples_by_family: dict[str, list[dict[str, Any]]] = {}
        rolling_signals_by_family: dict[str, list[dict[str, Any]]] = {}
        for signal in sorted(signals.values(), key=lambda item: -int(item.get("signal_time_ms", 0))):
            family = str(signal.get("family_id") or signal.get("family") or signal.get("type") or "")
            signal_day = datetime.strptime(str(signal.get("signal_day_utc")), "%Y-%m-%d").date()
            if rolling_cutoff <= signal_day <= selected_date:
                rolling_30d_by_family[family] = rolling_30d_by_family.get(family, 0) + 1
                rolling_signals_by_family.setdefault(family, []).append(signal)
            samples = recent_samples_by_family.setdefault(family, [])
            if family and len(samples) < 6 and signal.get("chart_before"):
                trade = self._public_event(trades.get(signal["signal_id"], {"status": "WAITING_ENTRY"}))
                samples.append({**self._public_event(signal), "simulation": trade})
        performance = {}
        for family, family_signals in rolling_signals_by_family.items():
            closed = []
            for signal in family_signals:
                trade = trades.get(signal["signal_id"], {})
                if trade.get("status") == "CLOSED" and trade.get("realized_r") is not None:
                    closed.append((int(trade.get("exited_at_ms") or signal.get("signal_time_ms") or 0), float(trade["realized_r"])))
            running_total = 0.0
            curve = []
            for recorded_at_ms, realized_r in sorted(closed):
                running_total += realized_r
                curve.append({"recorded_at_ms": recorded_at_ms, "cumulative_r": round(running_total, 8)})
            performance[family] = {
                "signal_count": len(family_signals),
                "closed_count": len(closed),
                "open_count": len(family_signals) - len(closed),
                "realized_r_total": round(running_total, 8),
                "wins": sum(realized_r > 0 for _, realized_r in closed),
                "losses": sum(realized_r <= 0 for _, realized_r in closed),
                "curve": curve,
            }
        return {"protocol": "ORBIT_SIGNAL_DESK_V2", "day_utc": selected_day, "health": {"status": "RUNNING" if latest_scan else "WAITING_FIRST_SCAN", "manifest_exists": True, "events_exists": events_path.exists(), "event_count": len(records), "head_hash": records[-1]["record_hash"] if records else "0" * 64, "latest_recorded_at_ms": latest_recorded_at_ms, "latest_scan": self._public_event(latest_scan), "error_type": None}, "rolling_30d_by_family": rolling_30d_by_family, "rolling_30d_daily_average_by_family": {family: round(count / 30, 2) for family, count in rolling_30d_by_family.items()}, "rolling_30d_performance_by_family": performance, "recent_samples_by_family": recent_samples_by_family, "_all_signals": rows, "_source_alerts": source_alerts}

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

    def _discipline(self, rows, interactions=None):
        interactions = self._read_interactions() if interactions is None else interactions
        cooldowns = []
        now = self.clock_ms()
        for event in interactions:
            if event.get("event_type") != "MANUAL_EXECUTION_RECORDED" or event.get("exit_reason") != "STOP": continue
            try: signal = self._signal(event["signal_id"])
            except ValueError: continue
            until = int(event.get("exited_at_ms") or 0) + 240 * 60_000
            if until > now: cooldowns.append({"symbol": signal["symbol"], "direction": signal["direction"], "until_ms": until})
        outside = [event for event in interactions if event.get("event_type") == "OUTSIDE_SIGNAL_TRADE_DETECTED"]
        loss_runs = 0
        for event in reversed([e for e in interactions if e.get("event_type") == "MANUAL_EXECUTION_RECORDED"]):
            if float(event.get("realized_r") or 0) >= 0: break
            loss_runs += 1
        current_day = self._clock_day()
        daily_r = sum(float(e.get("realized_r") or 0) for e in interactions if e.get("event_type") == "MANUAL_EXECUTION_RECORDED" and datetime.fromtimestamp(int(e.get("exited_at_ms") or 0) / 1000, tz=timezone.utc).strftime("%Y-%m-%d") == current_day)
        circuit = loss_runs >= 3 or daily_r <= -3
        return {"stop_attached": "ENFORCED", "averaging_down": "BLOCKED", "cooldown_after_stop_minutes": 240, "cooldown_symbols": sorted({f'{r["symbol"]} {r["direction"]}' for r in cooldowns}), "cooldowns": cooldowns, "outside_signal_trade": "BLOCKED", "outside_signal_count": len(outside), "consecutive_losses": loss_runs, "consecutive_loss_limit": 3, "daily_realized_r": daily_r, "daily_loss_limit_r": -3, "circuit_breaker_active": circuit, "relaxation_delay_hours": 24}

    def _operations(self, interactions, health, rows):
        def latest(kind):
            return next((event for event in reversed(interactions) if event.get("event_type") == kind), None)
        push = latest("PUSHOVER_CONFIGURATION_CHANGED") or {}
        control = latest("SIGNAL_SERVICE_CONTROL_CHANGED") or {}
        binding = latest("SIGNAL_ACCOUNT_BINDING_CHANGED") or {}
        latest_scan_ms = (health.get("latest_scan") or {}).get("recorded_at_ms") or health.get("latest_recorded_at_ms")
        now = self.clock_ms()
        stale = latest_scan_ms is None or now - int(latest_scan_ms) > 30 * 60_000
        push_failures = sum(event.get("event_type") in {"PUSHOVER_TEST_FAILED", "SERVICE_SCAN_FAILED"} for event in interactions)
        pending = [self._public_event(event) for event in interactions if event.get("event_type") == "DISCIPLINE_CHANGE_REQUESTED" and int(event.get("effective_at_ms") or 0) > now]
        latest_family = {}
        for event in interactions:
            if event.get("event_type") == "SIGNAL_FAMILY_CONTROL_CHANGED":
                latest_family[str(event.get("family_id"))] = event
        revision = sum(event.get("event_type") in {"SIGNAL_CONFIGURATION_CHANGED", "SIGNAL_FAMILY_CONTROL_CHANGED"} for event in interactions)
        active_spec = effective_spec(self.spec, interactions)
        active_spec["scope_version"] = scope_version(revision)
        family_controls = {}
        definitions = {
            family_id: {"enabled": True}
            for family_id in ("BREAKOUT_MOMENTUM", "OVERSOLD_REBOUND", "SUSTAINED_STRENGTH")
        }
        definitions.update(active_spec.get("signals") or {})
        for family_id, definition in definitions.items():
            event = latest_family.get(family_id) or {}
            family_controls[family_id] = {
                "enabled": bool(event.get("enabled", definition.get("enabled", True))),
                "disabled_reason": event.get("reason") if event and not event.get("enabled") else None,
                "changed_at_ms": event.get("recorded_at_ms"),
            }
        notifications = active_spec.get("notifications", {})
        market = active_spec.get("market", {})
        bound_account_id = binding.get("account_id")
        binding_conflict = bool(bound_account_id and any(row.get("exchange_account_id") == bound_account_id and row.get("status") in {"ACTIVE", "STOPPING"} for row in self.binding_reader()))
        return {
            "service": {"enabled": bool(control.get("enabled", False)), "running": bool(control.get("enabled", False)) and not stale, "last_scan_at_ms": latest_scan_ms, "market_data_fresh": not stale, "error_count": push_failures + int(health.get("status") == "LEDGER_ERROR")},
            "pushover": {"configured": bool(push.get("api_token_reference") and push.get("user_key_reference")), "enabled": bool(push.get("enabled", False)), "api_token_fingerprint": push.get("api_token_fingerprint"), "user_key_fingerprint": push.get("user_key_fingerprint"), "today_sent": sum((row.get("push") or {}).get("event_type") == "PUSH_SUCCEEDED" for row in rows), "daily_limit": notifications.get("daily_success_limit", 3)},
            "binding": {"account_id": bound_account_id, "optional": True, "conflict": binding_conflict, "purpose": "只用于真实成交自动配对，不参与信号扫描或模拟"},
            "parameters": {"liquidity_threshold_usdt": (market.get("liquidity") or {}).get("minimum_median_daily_quote_volume_usdt", 2000000), "liquidity_lookback_complete_utc_days": (market.get("liquidity") or {}).get("lookback_complete_utc_days", 30), "candidate_limit": (active_spec.get("workload") or {}).get("daily_candidate_limit", 30), "push_thresholds": notifications.get("trend_strength_minimum_by_family", {}), "signal_interval": market.get("signal_interval", "15m")},
            "family_controls": family_controls,
            "strategy_families": deepcopy(SIGNAL_FAMILY_PRESENTATION),
            "latest_round": {
                "market_count": int((health.get("latest_scan") or {}).get("market_window_count") or 0),
                "detected_count": int((health.get("latest_scan") or {}).get("detected_signal_count") or 0),
                "new_signal_count": int((health.get("latest_scan") or {}).get("new_signal_count") or 0),
            },
            "configuration": public_configuration(active_spec, revision),
            "scope_version": active_spec["scope_version"],
            "pending_discipline_changes": pending,
            "backup": {"required_paths": [str(self.ledger_directory), str(self.interaction_directory)]},
        }

    def _alerts(self, source_events, interactions, health, discipline, operations):
        alerts = []
        latest_heartbeat = max((int(event.get("recorded_at_ms") or 0) for event in interactions if event.get("event_type") == "SERVICE_HEARTBEAT"), default=0)
        latest_test_success = max((int(event.get("recorded_at_ms") or 0) for event in interactions if event.get("event_type") == "PUSHOVER_TEST_SUCCEEDED"), default=0)
        push_success_by_signal = {}
        for event in source_events:
            if event.get("event_type") == "PUSH_SUCCEEDED":
                push_success_by_signal[event.get("signal_id")] = max(int(event.get("recorded_at_ms") or 0), push_success_by_signal.get(event.get("signal_id"), 0))
        for event in source_events:
            if event.get("event_type") == "PUSH_SUCCEEDED": continue
            recorded = int(event.get("recorded_at_ms") or 0); signal_id = str(event.get("signal_id") or "未知信号")
            recovered = push_success_by_signal.get(event.get("signal_id"), 0) > recorded
            exhausted = event.get("event_type") == "PUSH_RETRY_EXHAUSTED"
            alerts.append(self._alert(f'{event.get("event_type")}:{signal_id}:{recorded}', "ERROR" if exhausted else "WARNING", "推送", "手机推送重试耗尽" if exhausted else "手机推送失败", f"信号 {signal_id} 未能发送到手机。", recorded, "RECOVERED" if recovered else "ACTIVE"))
        for event in interactions:
            kind = event.get("event_type"); recorded = int(event.get("recorded_at_ms") or 0)
            if kind == "SERVICE_SCAN_FAILED":
                alerts.append(self._alert(f"SERVICE_SCAN_FAILED:{recorded}", "ERROR", "服务", "信号扫描失败", f"扫描任务发生 {event.get('error_type') or '未知错误'}。", recorded, "RECOVERED" if latest_heartbeat > recorded else "ACTIVE"))
            elif kind == "PUSHOVER_TEST_FAILED":
                alerts.append(self._alert(f"PUSHOVER_TEST_FAILED:{recorded}", "WARNING", "推送", "测试通知失败", f"Pushover 返回 {event.get('error_type') or '未知错误'}。", recorded, "RECOVERED" if latest_test_success > recorded else "ACTIVE"))
            elif kind == "OUTSIDE_SIGNAL_TRADE_DETECTED":
                alerts.append(self._alert(f"OUTSIDE_SIGNAL_TRADE:{event.get('trade_id')}:{recorded}", "WARNING", "账户", "发现计划外交易", f"{event.get('symbol') or '未知标的'} 的成交或持仓未匹配到正式信号。", recorded))
        now = self.clock_ms()
        service = operations.get("service", {})
        if service.get("enabled") and not service.get("market_data_fresh"):
            alerts.append(self._alert("MARKET_DATA_STALE", "ERROR", "行情", "行情或扫描已超时", "最近 30 分钟没有新的成功扫描，请检查 Binance 网络与信号服务日志。", int(service.get("last_scan_at_ms") or now)))
        if service.get("enabled") and not operations.get("pushover", {}).get("configured"):
            alerts.append(self._alert("PUSHOVER_NOT_CONFIGURED", "WARNING", "推送", "手机推送尚未配置", "信号仍会进入网页，但无法发送到手机。", now))
        binding = operations.get("binding", {})
        if binding.get("conflict"):
            alerts.append(self._alert("ACCOUNT_BINDING_CONFLICT", "CRITICAL", "账户", "成交对照账户与 TB4 冲突", f"账户 {binding.get('account_id')} 已被 TB4 使用，自动成交配对已停止。", now))
        if discipline.get("circuit_breaker_active"):
            alerts.append(self._alert("DISCIPLINE_CIRCUIT_BREAKER", "CRITICAL", "纪律", "当日交易熔断已触发", f"连续亏损 {discipline.get('consecutive_losses', 0)} 笔，当日累计 {discipline.get('daily_realized_r', 0):.2f}R。", now))
        for cooldown in discipline.get("cooldowns", []):
            alerts.append(self._alert(f'COOLDOWN:{cooldown["symbol"]}:{cooldown["direction"]}', "WARNING", "纪律", "止损后冷静期", f'{cooldown["symbol"]} {cooldown["direction"]} 在解禁前不能登记新交易。', now, "ACTIVE", cooldown.get("until_ms")))
        alerts.sort(key=lambda row: (row["status"] != "ACTIVE", -int(row.get("recorded_at_ms") or 0)))
        return alerts[:200]

    @staticmethod
    def _alert(alert_id, severity, category, title, message, recorded_at_ms, status="ACTIVE", until_ms=None):
        return {"alert_id": alert_id, "severity": severity, "category": category, "title": title, "message": message, "recorded_at_ms": int(recorded_at_ms or 0), "status": status, "until_ms": until_ms}

    @staticmethod
    def _alert_summary(alerts):
        active = [row for row in alerts if row.get("status") == "ACTIVE"]
        return {"total": len(alerts), "active": len(active), "critical": sum(row.get("severity") == "CRITICAL" for row in active), "error": sum(row.get("severity") == "ERROR" for row in active), "warning": sum(row.get("severity") == "WARNING" for row in active)}

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

    def _latest_event(self, event_type):
        return next((row for row in reversed(self._read_interactions()) if row.get("event_type") == event_type), None)

    def _clock_day(self) -> str:
        return datetime.fromtimestamp(self.clock_ms() / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

    def _decision_for(self, signal_id):
        return next((row for row in reversed(self._read_interactions()) if row.get("event_type") == "SIGNAL_DECISION_RECORDED" and row.get("signal_id") == signal_id), None)

    def _trade_imported(self, account_id, trade_id):
        return any(row.get("account_id") == account_id and row.get("trade_id") == trade_id for row in self._read_interactions())

    @staticmethod
    def _match_trade(trade, signals):
        side = str(trade.get("side") or "").upper(); position = str(trade.get("positionSide") or "").upper()
        timestamp = int(trade.get("time") or 0); symbol = str(trade.get("symbol") or "").upper()
        candidates = [signal for signal in signals if signal["symbol"] == symbol and int(signal["signal_time_ms"]) <= timestamp <= int(signal["signal_time_ms"]) + 30 * 60_000 and ((signal["direction"] == "LONG" and (position == "LONG" or side == "BUY")) or (signal["direction"] == "SHORT" and (position == "SHORT" or side == "SELL")))]
        return min(candidates, key=lambda row: abs(timestamp - int(row["signal_time_ms"])), default=None)

    @staticmethod
    def _trade_is_entry(trade, signal):
        side = str(trade.get("side") or "").upper(); position = str(trade.get("positionSide") or "").upper()
        return (signal["direction"] == "LONG" and side == "BUY" and position in {"", "BOTH", "LONG"}) or (signal["direction"] == "SHORT" and side == "SELL" and position in {"", "BOTH", "SHORT"})

    @staticmethod
    def _trade_is_exit(trade, signal):
        side = str(trade.get("side") or "").upper(); position = str(trade.get("positionSide") or "").upper()
        return (signal["direction"] == "LONG" and side == "SELL" and position in {"", "BOTH", "LONG"}) or (signal["direction"] == "SHORT" and side == "BUY" and position in {"", "BOTH", "SHORT"})

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
        health = {"status": status, "manifest_exists": False, "events_exists": False, "event_count": 0, "head_hash": None, "latest_recorded_at_ms": None, "latest_scan": None, "error_type": None}
        return {"protocol": "ORBIT_SIGNAL_DESK_V2", "day_utc": day, "health": health, "summary": {"signal_count": 0, "included_count": 0, "truncated_count": 0, "taken_count": 0, "skipped_count": 0, "undecided_count": 0, "open_count": 0, "closed_count": 0, "push_succeeded_count": 0, "realized_r_total": 0.0}, "discipline": {"stop_attached": "ENFORCED", "averaging_down": "BLOCKED", "cooldown_after_stop_minutes": 240, "cooldown_symbols": [], "outside_signal_trade": "BLOCKED", "outside_signal_count": 0}, "review": {}, "signals": [], "operations": self._operations([], health, []), "alerts": [], "alert_summary": {"total": 0, "active": 0, "critical": 0, "error": 0, "warning": 0}}

    @staticmethod
    def _public_event(event):
        if not event: return {}
        return {key: value for key, value in event.items() if key not in {"provider_request_id", "actor"}}
