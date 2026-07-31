from __future__ import annotations

import hashlib
import json
import threading
import time
from decimal import Decimal, ROUND_DOWN
from typing import Any, Callable, Mapping

from orbit.application.live_reconciliation import LiveReconciliationService
from orbit.application.live_risk import live_small_drawdown_stop_reason
from orbit.domain.strategy.trend_basket_runner import TB4_SPEC


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class LiveExecutionService:
    """LIVE-SMALL V2 executor whose sole instruction source is the TB4 checklist."""

    def __init__(
        self,
        *,
        enabled: bool,
        execution_epoch: str,
        live_account_id: str,
        accounts: Any,
        account_snapshots: Any,
        trend_forward_snapshot: Callable[[], dict[str, Any]],
        gateway_factory: Callable[[dict[str, Any]], Any],
        execution_ledger: Any,
        equity_ledger: Any,
        reconciliation_snapshot: Callable[[], dict[str, Any]],
        max_snapshot_age_seconds: int = 120,
        max_order_notional_usdt: float = 150,
        round_gross_multiplier: float = 1.1,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.execution_epoch = str(execution_epoch or "").strip()
        self.live_account_id = str(live_account_id or "").strip()
        self.accounts = accounts
        self.account_snapshots = account_snapshots
        self.trend_forward_snapshot = trend_forward_snapshot
        self.gateway_factory = gateway_factory
        self.execution_ledger = execution_ledger
        self.equity_ledger = equity_ledger
        self.reconciliation_snapshot = reconciliation_snapshot
        self.max_snapshot_age_ms = int(max_snapshot_age_seconds) * 1000
        self.max_order_notional = Decimal(str(max_order_notional_usdt))
        self.round_gross_multiplier = Decimal(str(round_gross_multiplier))
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._order_gate = threading.Lock()
        if self.max_snapshot_age_ms <= 0:
            raise ValueError("max_snapshot_age_seconds must be positive")
        if self.max_order_notional <= 0:
            raise ValueError("max_order_notional_usdt must be positive")
        if self.round_gross_multiplier <= 0:
            raise ValueError("round_gross_multiplier must be positive")

    def execute_due(
        self,
        sync_account: Callable[[str], Mapping[str, Any]],
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"status": "DISABLED", "executed": False}
        rebalance_time = 0
        try:
            if self.execution_epoch:
                stopped, stop_reason = self.execution_ledger.stopped(
                    self.execution_epoch
                )
                if stopped:
                    return {
                        "status": "EMERGENCY_STOPPED",
                        "executed": False,
                        "reason": stop_reason,
                    }
                incomplete = self.execution_ledger.incomplete_round(
                    self.execution_epoch
                )
                if incomplete is not None:
                    reason = f"INCOMPLETE_ROUND_{incomplete}"
                    self.execution_ledger.append(self._event(
                        "PROTOCOL_STOP", rebalance_time, reason=reason,
                    ))
                    return {
                        "status": "PROTOCOL_STOP",
                        "executed": False,
                        "reason": reason,
                    }
                violation = self.execution_ledger.protocol_violation(
                    self.execution_epoch, set(TB4_SPEC.symbols),
                )
                if violation:
                    self.execution_ledger.append(self._event(
                        "PROTOCOL_VIOLATION", rebalance_time, reason=violation,
                    ))
                    return {
                        "status": "PROTOCOL_VIOLATION",
                        "executed": False,
                        "reason": violation,
                    }
        except Exception as exc:
            return {
                "status": "DATA_INTEGRITY_ERROR",
                "executed": False,
                "reason": str(exc),
            }
        trend = self.trend_forward_snapshot()
        checklist = trend.get("execution_checklist") or {}
        rebalance_time = int(checklist.get("rebalance_time_ms") or 0)
        reason = self._static_gate(checklist)
        if reason:
            return self._reject(rebalance_time, reason)
        if self.execution_ledger.round_consumed(self.execution_epoch, rebalance_time):
            return {"status": "ALREADY_CONSUMED", "executed": False}

        try:
            before = dict(sync_account(self.live_account_id))
        except Exception as exc:
            return self._reject(rebalance_time, f"ACCOUNT_SYNC_FAILED: {exc}")
        reason = self._account_gate(before)
        if reason:
            return self._reject(rebalance_time, reason)
        protocol_stop = self._drawdown_stop()
        if protocol_stop:
            self.execution_ledger.append(self._event(
                "PROTOCOL_STOP", rebalance_time, reason=protocol_stop,
            ))
            return {"status": "PROTOCOL_STOP", "executed": False, "reason": protocol_stop}

        rows = list(checklist.get("rows") or [])
        checklist_sha = canonical_hash(checklist)
        intents, results = self._build_intents(rows, before.get("positions") or [])
        limit_reason = self._limit_violation(checklist, intents)
        if limit_reason:
            return self._reject(rebalance_time, limit_reason)

        self.execution_ledger.append(self._event(
            "ROUND_STARTED",
            rebalance_time,
            checklist_sha256=checklist_sha,
            checklist_rows={
                str(row["symbol"]): canonical_hash(row) for row in rows
            },
            order_count=len(intents),
        ))
        try:
            gateway = self.gateway_factory(
                self.accounts.account_by_id(self.live_account_id)
            )
        except Exception as exc:
            gateway = None
            gateway_error = str(exc)
        else:
            gateway_error = None
        for intent in intents:
            if gateway is None:
                row_result = dict(intent) | {
                    "status": "ORDER_FAILED",
                    "executed_quantity": 0.0,
                    "average_price": 0.0,
                    "slippage_bps": None,
                    "fee": 0.0,
                    "fee_assets": [],
                    "error": gateway_error,
                }
                self.execution_ledger.append(self._event(
                    "ORDER_RESULT",
                    rebalance_time,
                    symbol=intent["symbol"],
                    checklist_row_sha256=intent["checklist_row_sha256"],
                    order_intent={
                        "source": "FROZEN_TB4_CHECKLIST",
                        "checklist_sha256": checklist_sha,
                        "params": None,
                    },
                    exchange_response=None,
                    trades=[],
                    result=row_result,
                    error=gateway_error,
                ))
            else:
                row_result = self._execute_one(
                    gateway, rebalance_time, checklist_sha, intent,
                )
            results.append(row_result)

        try:
            after = dict(sync_account(self.live_account_id))
            reconciliation = self.reconciliation_snapshot()
            post_sync_error = None
        except Exception as exc:
            after = {}
            reconciliation = None
            post_sync_error = str(exc)
        report = self._report(
            rebalance_time,
            checklist_sha,
            results,
            reconciliation,
            after,
            post_sync_error,
        )
        self.execution_ledger.append(self._event(
            "ROUND_COMPLETED", rebalance_time, report=report,
        ))
        return {"status": report["status"], "executed": True, "report": report}

    def emergency_stop(self, *, actor: str, reason: str) -> dict[str, Any]:
        reason = str(reason or "").strip()
        if not reason:
            return {"ok": False, "error": "急停原因不能为空。"}
        if not self.execution_epoch:
            return {"ok": False, "error": "自动执行 epoch 未配置。"}
        with self._order_gate:
            self.execution_ledger.append({
                "protocol": "LIVE_SMALL_EXECUTION_V1",
                "event_type": "EMERGENCY_STOP",
                "execution_epoch": self.execution_epoch,
                "recorded_at_ms": self.now_ms(),
                "actor": actor,
                "reason": reason,
            })
        return {"ok": True, "status": "EMERGENCY_STOPPED", "reason": reason}

    def snapshot(self) -> dict[str, Any]:
        try:
            violation = (
                self.execution_ledger.protocol_violation(
                    self.execution_epoch, set(TB4_SPEC.symbols),
                )
                if self.execution_epoch else None
            )
            stopped, reason = (
                self.execution_ledger.stopped(self.execution_epoch)
                if self.execution_epoch else (False, None)
            )
            incomplete = (
                self.execution_ledger.incomplete_round(self.execution_epoch)
                if self.execution_epoch else None
            )
            return {
                "protocol": "LIVE_SMALL_EXECUTION_V1",
                "enabled": self.enabled,
                "execution_epoch": self.execution_epoch or None,
                "account_id": self.live_account_id or None,
                "status": (
                    "PROTOCOL_VIOLATION" if violation
                    else "INCOMPLETE_ROUND" if incomplete is not None
                    else "EMERGENCY_STOPPED" if stopped
                    else "ENABLED" if self.enabled
                    else "DISABLED"
                ),
                "stop_reason": violation or (
                    f"INCOMPLETE_ROUND_{incomplete}"
                    if incomplete is not None else reason
                ),
                "latest_report": (
                    self.execution_ledger.latest_report(self.execution_epoch)
                    if self.execution_epoch else None
                ),
                "ledger": self.execution_ledger.status(),
            }
        except Exception as exc:
            return {
                "protocol": "LIVE_SMALL_EXECUTION_V1",
                "enabled": False,
                "status": "DATA_INTEGRITY_ERROR",
                "stop_reason": str(exc),
                "latest_report": None,
                "ledger": {"status": "INVALID", "error": str(exc)},
            }

    def reports(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return completed execution reports newest first without mutating the ledger."""
        bounded_limit = max(1, min(int(limit), 200))
        reports: list[dict[str, Any]] = []
        for record in reversed(self.execution_ledger.read_all()):
            payload = record["payload"]
            if payload.get("event_type") != "ROUND_COMPLETED":
                continue
            report = dict(payload.get("report") or {})
            report["recorded_at_ms"] = payload.get("recorded_at_ms")
            reports.append(report)
            if len(reports) >= bounded_limit:
                break
        return reports

    def configure(
        self,
        *,
        enabled: bool,
        execution_epoch: str,
        live_account_id: str,
        max_snapshot_age_seconds: int | None = None,
        max_order_notional_usdt: float | None = None,
        round_gross_multiplier: float | None = None,
    ) -> None:
        """Apply an administrator-approved runtime control version.

        The order gate prevents activation changes while an individual order
        is being submitted.  Active epochs are never silently replaced.
        """
        next_epoch = str(execution_epoch or "").strip()
        next_account = str(live_account_id or "").strip()
        next_snapshot_age_ms = self.max_snapshot_age_ms
        next_order_notional = self.max_order_notional
        next_round_multiplier = self.round_gross_multiplier
        if max_snapshot_age_seconds is not None:
            value = int(max_snapshot_age_seconds)
            if value <= 0:
                raise ValueError("max_snapshot_age_seconds must be positive")
            next_snapshot_age_ms = value * 1000
        if max_order_notional_usdt is not None:
            value = Decimal(str(max_order_notional_usdt))
            if value <= 0:
                raise ValueError("max_order_notional_usdt must be positive")
            next_order_notional = value
        if round_gross_multiplier is not None:
            value = Decimal(str(round_gross_multiplier))
            if value <= 0:
                raise ValueError("round_gross_multiplier must be positive")
            next_round_multiplier = value
        with self._order_gate:
            if self.enabled and self.execution_epoch and next_epoch != self.execution_epoch:
                raise RuntimeError("active execution epoch cannot be replaced")
            self.enabled = bool(enabled)
            self.execution_epoch = next_epoch
            self.live_account_id = next_account
            self.max_snapshot_age_ms = next_snapshot_age_ms
            self.max_order_notional = next_order_notional
            self.round_gross_multiplier = next_round_multiplier

    def _static_gate(self, checklist: Mapping[str, Any]) -> str | None:
        if not self.execution_epoch:
            return "EXECUTION_EPOCH_NOT_CONFIGURED"
        if not self.live_account_id:
            return "LIVE_ACCOUNT_NOT_CONFIGURED"
        account = self.accounts.account_by_id(self.live_account_id)
        if not account:
            return "LIVE_ACCOUNT_NOT_FOUND"
        if account.get("status") != "active":
            return "LIVE_ACCOUNT_NOT_ACTIVE"
        if bool(account.get("testnet")):
            return "TESTNET_ACCOUNT_REJECTED"
        if bool(account.get("dry_run", True)):
            return "DRY_RUN_ACCOUNT_REJECTED"
        if checklist.get("status") != "READY":
            return "CHECKLIST_NOT_READY"
        rows = list(checklist.get("rows") or [])
        symbols = [str(row.get("symbol") or "") for row in rows]
        if (
            checklist.get("protocol") != "LIVE_SMALL_EXECUTION_CHECKLIST_V1"
            or len(symbols) != len(set(symbols))
            or set(symbols) != set(TB4_SPEC.symbols)
        ):
            return "CHECKLIST_UNIVERSE_MISMATCH"
        if bool(checklist.get("rules_stale")):
            return "EXCHANGE_RULES_STALE"
        return None

    def _account_gate(self, snapshot: Mapping[str, Any]) -> str | None:
        if snapshot.get("status") != "synced":
            return "ACCOUNT_NOT_SYNCED"
        mode = snapshot.get("position_mode") or {}
        if bool(mode.get("dual_side_position")):
            return "HEDGE_MODE_REJECTED"
        try:
            synced_at = LiveReconciliationService._timestamp_ms(snapshot.get("synced_at"))
        except Exception:
            return "ACCOUNT_SNAPSHOT_TIME_INVALID"
        if self.now_ms() - synced_at > self.max_snapshot_age_ms:
            return "ACCOUNT_SNAPSHOT_STALE"
        return None

    def _drawdown_stop(self) -> str | None:
        try:
            observations = self.equity_ledger.observations(self.live_account_id)
        except Exception as exc:
            return f"EQUITY_LEDGER_INVALID: {exc}"
        return live_small_drawdown_stop_reason(observations)

    def _build_intents(
        self,
        rows: list[Mapping[str, Any]],
        positions: list[Mapping[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        actual = LiveReconciliationService._actual_quantities(positions)
        intents: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        for row in rows:
            symbol = str(row["symbol"])
            target = Decimal(str(row.get("signed_target_quantity") or 0))
            current = actual.get(symbol, Decimal("0"))
            delta = target - current
            step = Decimal(str(row.get("quantity_step") or 0))
            quantity = (
                (abs(delta) / step).to_integral_value(rounding=ROUND_DOWN) * step
                if step > 0 else Decimal("0")
            )
            close = Decimal(str(row.get("close_price") or 0))
            notional = quantity * close
            base = {
                "symbol": symbol,
                "target_quantity": float(target),
                "actual_before_quantity": float(current),
                "requested_quantity": float(quantity),
                "reference_price": float(close),
                "checklist_row_sha256": canonical_hash(row),
            }
            if quantity <= 0 or quantity < Decimal(str(row.get("min_quantity") or 0)):
                results.append(base | {"status": "SKIPPED_DUST"})
                continue
            if notional < Decimal(str(row.get("min_notional_usdt") or 0)):
                results.append(base | {"status": "SKIPPED_BELOW_MIN"})
                continue
            intents.append(base | {
                "side": "BUY" if delta > 0 else "SELL",
                "notional_usdt": float(notional),
                "quantity_step": str(row.get("quantity_step")),
            })
        return intents, results

    def _limit_violation(
        self,
        checklist: Mapping[str, Any],
        intents: list[Mapping[str, Any]],
    ) -> str | None:
        oversized = [
            item["symbol"] for item in intents
            if Decimal(str(item["notional_usdt"])) > self.max_order_notional
        ]
        if oversized:
            return f"MAX_ORDER_NOTIONAL_EXCEEDED: {','.join(oversized)}"
        total = sum(
            (Decimal(str(item["notional_usdt"])) for item in intents),
            Decimal("0"),
        )
        target_gross = Decimal(str(
            (checklist.get("summary") or {}).get("target_gross_notional_usdt") or 0
        ))
        if total > target_gross * self.round_gross_multiplier:
            return "MAX_ROUND_NOTIONAL_EXCEEDED"
        return None

    def _execute_one(
        self,
        gateway: Any,
        rebalance_time: int,
        checklist_sha: str,
        intent: Mapping[str, Any],
    ) -> dict[str, Any]:
        symbol = str(intent["symbol"])
        epoch_tag = hashlib.sha256(
            self.execution_epoch.encode("utf-8")
        ).hexdigest()[:6]
        client_order_id = (
            f"orb{rebalance_time:x}{epoch_tag}{symbol[:10].lower()}"
        )[:36]
        params = {
            "symbol": symbol,
            "side": intent["side"],
            "positionSide": "BOTH",
            "type": "MARKET",
            "quantity": format(Decimal(str(intent["requested_quantity"])), "f"),
            "newClientOrderId": client_order_id,
            "newOrderRespType": "RESULT",
        }
        order_intent = {
            "source": "FROZEN_TB4_CHECKLIST",
            "checklist_sha256": checklist_sha,
            "params": params,
        }
        response = None
        trades: list[dict[str, Any]] = []
        trade_query_error = None
        try:
            with self._order_gate:
                stopped, stop_reason = self.execution_ledger.stopped(
                    self.execution_epoch
                )
                if stopped:
                    raise RuntimeError(f"EMERGENCY_STOPPED: {stop_reason}")
                response = gateway.place_order(params)
            order_id = response.get("orderId")
            if order_id is not None:
                try:
                    trades = gateway.user_trades(symbol, order_id)
                except Exception as exc:
                    trade_query_error = str(exc)
            executed = Decimal(str(response.get("executedQty") or 0))
            avg_price = Decimal(str(response.get("avgPrice") or 0))
            if trades:
                trade_qty = sum(
                    (Decimal(str(item.get("qty") or 0)) for item in trades),
                    Decimal("0"),
                )
                trade_quote = sum(
                    (
                        Decimal(str(item.get("qty") or 0))
                        * Decimal(str(item.get("price") or 0))
                        for item in trades
                    ),
                    Decimal("0"),
                )
                if trade_qty > 0:
                    executed = trade_qty
                    avg_price = trade_quote / trade_qty
            fee = sum(
                (Decimal(str(item.get("commission") or 0)) for item in trades),
                Decimal("0"),
            )
            requested = Decimal(str(intent["requested_quantity"]))
            step = Decimal(str(intent["quantity_step"]))
            status = (
                "ORDER_FAILED" if executed <= 0
                else "EXECUTED_MATCH" if abs(requested - executed) <= step
                else "PARTIAL_FILL"
            )
            reference = Decimal(str(intent["reference_price"]))
            signed_slippage = (
                (avg_price - reference) / reference * 10_000
                * (Decimal("1") if intent["side"] == "BUY" else Decimal("-1"))
                if reference > 0 and avg_price > 0 else Decimal("0")
            )
            result = dict(intent) | {
                "status": status,
                "client_order_id": client_order_id,
                "order_id": order_id,
                "executed_quantity": float(executed),
                "average_price": float(avg_price),
                "slippage_bps": float(signed_slippage),
                "fee": float(fee),
                "fee_assets": sorted({
                    str(item.get("commissionAsset"))
                    for item in trades if item.get("commissionAsset")
                }),
                "error": (
                    f"USER_TRADES_QUERY_FAILED: {trade_query_error}"
                    if trade_query_error else None
                ),
            }
            ledger_payload = self._event(
                "ORDER_RESULT",
                rebalance_time,
                symbol=symbol,
                checklist_row_sha256=intent["checklist_row_sha256"],
                order_intent=order_intent,
                exchange_response=response,
                trades=trades,
                result=result,
            )
        except Exception as exc:
            result = dict(intent) | {
                "status": "ORDER_FAILED",
                "client_order_id": client_order_id,
                "executed_quantity": 0.0,
                "average_price": 0.0,
                "slippage_bps": None,
                "fee": 0.0,
                "fee_assets": [],
                "error": str(exc),
            }
            ledger_payload = self._event(
                "ORDER_RESULT",
                rebalance_time,
                symbol=symbol,
                checklist_row_sha256=intent["checklist_row_sha256"],
                order_intent=order_intent,
                exchange_response=response,
                trades=[],
                result=result,
                error=str(exc),
            )
        self.execution_ledger.append(ledger_payload)
        return result

    def _report(
        self,
        rebalance_time: int,
        checklist_sha: str,
        rows: list[dict[str, Any]],
        reconciliation: Mapping[str, Any] | None,
        after: Mapping[str, Any],
        post_sync_error: str | None,
    ) -> dict[str, Any]:
        attempted = [row for row in rows if row["status"] not in {
            "SKIPPED_DUST", "SKIPPED_BELOW_MIN",
        }]
        matched = sum(row["status"] == "EXECUTED_MATCH" for row in attempted)
        failed = sum(row["status"] in {"ORDER_FAILED", "PARTIAL_FILL"} for row in attempted)
        evidence_errors = sum(bool(row.get("error")) for row in attempted)
        return {
            "protocol": "LIVE_SMALL_EXECUTION_REPORT_V1",
            "status": (
                "COMPLETED"
                if not failed and not evidence_errors and not post_sync_error
                else "COMPLETED_WITH_ERRORS"
            ),
            "execution_epoch": self.execution_epoch,
            "account_id": self.live_account_id,
            "rebalance_time_ms": rebalance_time,
            "checklist_sha256": checklist_sha,
            "rows": rows,
            "attempted_count": len(attempted),
            "matched_count": matched,
            "failed_count": failed,
            "evidence_error_count": evidence_errors,
            "success_ratio": matched / len(attempted) if attempted else 1.0,
            "post_sync_at": after.get("synced_at"),
            "post_sync_error": post_sync_error,
            "position_reconciliation": (
                reconciliation.get("positions") if reconciliation else None
            ),
        }

    def _reject(self, rebalance_time: int, reason: str) -> dict[str, Any]:
        if self.execution_epoch and rebalance_time > 0 and not self.execution_ledger.round_consumed(
            self.execution_epoch, rebalance_time,
        ):
            self.execution_ledger.append(self._event(
                "ROUND_REJECTED", rebalance_time, reason=reason,
            ))
        return {"status": "REJECTED", "executed": False, "reason": reason}

    def _event(self, event_type: str, rebalance_time: int, **values: Any) -> dict[str, Any]:
        return {
            "protocol": "LIVE_SMALL_EXECUTION_V1",
            "event_type": event_type,
            "execution_epoch": self.execution_epoch,
            "account_id": self.live_account_id,
            "rebalance_time_ms": int(rebalance_time),
            "recorded_at_ms": self.now_ms(),
        } | values
