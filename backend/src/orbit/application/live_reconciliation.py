from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Mapping

from orbit.application.live_risk import live_small_drawdown_projection


class LiveReconciliationService:
    """Read-only position reconciliation plus append-only equity observations."""

    def __init__(
        self,
        *,
        live_account_id: str,
        account_snapshots: Any,
        trend_forward_snapshot: Callable[[], dict[str, Any]],
        equity_ledger: Any,
        quantity_tolerance_pct: float = 1.0,
    ) -> None:
        self.live_account_id = str(live_account_id or "").strip()
        self.account_snapshots = account_snapshots
        self.trend_forward_snapshot = trend_forward_snapshot
        self.equity_ledger = equity_ledger
        self.quantity_tolerance_pct = Decimal(str(quantity_tolerance_pct)) / Decimal("100")
        if self.quantity_tolerance_pct < 0:
            raise ValueError("quantity_tolerance_pct cannot be negative")
        self.last_record_error: str | None = None

    def configure(self, *, live_account_id: str, quantity_tolerance_pct: float | None = None) -> None:
        self.live_account_id = str(live_account_id or "").strip()
        if quantity_tolerance_pct is not None:
            tolerance = Decimal(str(quantity_tolerance_pct)) / Decimal("100")
            if tolerance < 0:
                raise ValueError("quantity_tolerance_pct cannot be negative")
            self.quantity_tolerance_pct = tolerance

    def record_snapshot(self, account_id: str, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        if not self.live_account_id:
            return {"recorded": False, "reason": "ACCOUNT_NOT_CONFIGURED"}
        if account_id != self.live_account_id:
            return {"recorded": False, "reason": "ACCOUNT_OUT_OF_SCOPE"}
        if snapshot.get("status") != "synced":
            return {"recorded": False, "reason": "ACCOUNT_NOT_SYNCED"}
        if bool(snapshot.get("testnet")) or bool(snapshot.get("dry_run")):
            return {"recorded": False, "reason": "ACCOUNT_NOT_LIVE"}
        try:
            trend = self.trend_forward_snapshot()
        except Exception as exc:
            self.last_record_error = str(exc)
            return {"recorded": False, "reason": "PAPER_READ_ERROR", "error": str(exc)}
        checklist = trend.get("execution_checklist") or {}
        if checklist.get("status") != "READY":
            return {"recorded": False, "reason": "PAPER_NOT_READY"}
        equity = self._account_equity(snapshot)
        if equity <= 0:
            return {"recorded": False, "reason": "INVALID_ACCOUNT_EQUITY"}
        paper_equity = Decimal(str((trend.get("runner") or {}).get("equity") or 0))
        if paper_equity <= 0:
            return {"recorded": False, "reason": "INVALID_PAPER_EQUITY"}
        try:
            payload = {
                "protocol": "LIVE_SMALL_EQUITY_OBSERVATION_V1",
                "account_id": account_id,
                "synced_at_ms": self._timestamp_ms(snapshot.get("synced_at")),
                "live_equity_usdt": float(equity),
                "paper_equity": float(paper_equity),
                "paper_close_time_ms": checklist.get("close_time_ms"),
                "rebalance_time_ms": checklist.get("rebalance_time_ms"),
                "executable_notional_ratio": float(
                    (checklist.get("summary") or {}).get("executable_notional_ratio", 0)
                ),
            }
            result = self.equity_ledger.append(payload)
            self.last_record_error = None
            return {
                "recorded": not result["duplicate"],
                "duplicate": result["duplicate"],
                "reason": "DUPLICATE" if result["duplicate"] else None,
            }
        except Exception as exc:
            self.last_record_error = str(exc)
            return {"recorded": False, "reason": "LEDGER_ERROR", "error": str(exc)}

    def snapshot(self) -> dict[str, Any]:
        try:
            return self._snapshot()
        except Exception as exc:
            self.last_record_error = str(exc)
            return {
                "protocol": "LIVE_SMALL_RECONCILIATION_V1",
                "status": "DATA_INTEGRITY_ERROR",
                "read_only": True,
                "auto_correction": False,
                "account_id": self.live_account_id or None,
                "positions": None,
                "equity": {
                    "status": "DATA_INTEGRITY_ERROR",
                    "points": [],
                    "weekly_points": [],
                    "cumulative_deviation_pct": None,
                    "latest_weekly_deviation_pct": None,
                },
                "last_record_error": self.last_record_error,
                "ledger": {"status": "INVALID", "error": str(exc)},
            }

    def _snapshot(self) -> dict[str, Any]:
        if not self.live_account_id:
            return self._base("ACCOUNT_NOT_CONFIGURED")
        trend = self.trend_forward_snapshot()
        checklist = trend.get("execution_checklist") or {}
        account = self.account_snapshots.get(self.live_account_id)
        if not account:
            return self._base("AWAITING_ACCOUNT_SYNC", checklist=checklist)
        if account.get("status") != "synced":
            return self._base(
                "ACCOUNT_NOT_SYNCED", checklist=checklist,
                account_status=account.get("status"),
            )
        if bool(account.get("testnet")) or bool(account.get("dry_run")):
            return self._base(
                "ACCOUNT_NOT_LIVE", checklist=checklist,
                account_status=account.get("status"),
            )
        if checklist.get("status") != "READY":
            return self._base("PAPER_NOT_READY", checklist=checklist)

        position_result = self._reconcile_positions(checklist, account.get("positions") or [])
        equity = self._equity_projection()
        return {
            "protocol": "LIVE_SMALL_RECONCILIATION_V1",
            "status": "READY",
            "read_only": True,
            "auto_correction": False,
            "account_id": self.live_account_id,
            "account_synced_at": account.get("synced_at"),
            "quantity_tolerance_pct": float(self.quantity_tolerance_pct * 100),
            "positions": position_result,
            "equity": equity,
            "last_record_error": self.last_record_error,
            "ledger": self.equity_ledger.status(),
        }

    def _reconcile_positions(
        self,
        checklist: Mapping[str, Any],
        positions: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        actual = self._actual_quantities(positions)
        rows = []
        checklist_symbols = set()
        for target in checklist.get("rows") or []:
            symbol = str(target["symbol"])
            checklist_symbols.add(symbol)
            target_qty = Decimal(str(target.get("signed_target_quantity") or 0))
            actual_qty = actual.get(symbol, Decimal("0"))
            step = Decimal(str(target.get("quantity_step") or 0))
            tolerance = step + abs(target_qty) * self.quantity_tolerance_pct
            difference = actual_qty - target_qty
            direction_match = (
                target_qty == 0 and actual_qty == 0
                or target_qty > 0 and actual_qty > 0
                or target_qty < 0 and actual_qty < 0
            )
            if (
                target.get("status") == "BELOW_MIN_NOTIONAL"
                and abs(actual_qty) <= tolerance
            ):
                status = "EXPECTED_FLAT"
            elif direction_match and abs(difference) <= tolerance:
                status = "MATCH"
            else:
                status = "DEVIATION"
            rows.append({
                "symbol": symbol,
                "status": status,
                "target_direction": target.get("direction"),
                "target_quantity": float(target_qty),
                "actual_quantity": float(actual_qty),
                "difference_quantity": float(difference),
                "tolerance_quantity": float(tolerance),
                "direction_match": direction_match,
                "checklist_status": target.get("status"),
            })

        for symbol in sorted(set(actual) - checklist_symbols):
            quantity = actual[symbol]
            if quantity == 0:
                continue
            rows.append({
                "symbol": symbol,
                "status": "UNEXPECTED_POSITION",
                "target_direction": None,
                "target_quantity": 0.0,
                "actual_quantity": float(quantity),
                "difference_quantity": float(quantity),
                "tolerance_quantity": 0.0,
                "direction_match": False,
                "checklist_status": None,
            })

        correct = sum(row["status"] in {"MATCH", "EXPECTED_FLAT"} for row in rows)
        deviations = [
            row for row in rows
            if row["status"] in {"DEVIATION", "UNEXPECTED_POSITION"}
        ]
        return {
            "status": "MATCH" if not deviations else "DEVIATION",
            "rows": rows,
            "correct_count": correct,
            "total_count": len(rows),
            "accuracy_ratio": correct / len(rows) if rows else 1.0,
            "deviation_count": len(deviations),
            "deviations": deepcopy(deviations),
        }

    def _equity_projection(self) -> dict[str, Any]:
        observations = self.equity_ledger.observations(self.live_account_id)
        if not observations:
            return {
                "status": "NO_OBSERVATIONS",
                "points": [],
                "weekly_points": [],
                "cumulative_deviation_pct": None,
                "latest_weekly_deviation_pct": None,
                **live_small_drawdown_projection(observations),
            }
        first = observations[0]
        live_base = Decimal(str(first["live_equity_usdt"]))
        paper_base = Decimal(str(first["paper_equity"]))
        points = []
        previous_live = Decimal("1")
        previous_paper = Decimal("1")
        for item in observations:
            live_normalized = (
                Decimal(str(item["live_equity_usdt"])) / live_base
                if live_base > 0 else Decimal("0")
            )
            paper_normalized = (
                Decimal(str(item["paper_equity"])) / paper_base
                if paper_base > 0 else Decimal("0")
            )
            cumulative_deviation = (live_normalized - paper_normalized) * 100
            period_live = live_normalized / previous_live - 1 if previous_live else Decimal("0")
            period_paper = (
                paper_normalized / previous_paper - 1 if previous_paper else Decimal("0")
            )
            points.append({
                "synced_at_ms": item["synced_at_ms"],
                "live_equity_usdt": item["live_equity_usdt"],
                "paper_equity": item["paper_equity"],
                "live_normalized": float(live_normalized),
                "paper_normalized": float(paper_normalized),
                "cumulative_deviation_pct": float(cumulative_deviation),
                "period_deviation_pct": float((period_live - period_paper) * 100),
                "executable_notional_ratio": item.get("executable_notional_ratio", 0),
            })
            previous_live = live_normalized
            previous_paper = paper_normalized
        weekly_latest: dict[tuple[int, int], dict[str, Any]] = {}
        for point in points:
            iso = datetime.fromtimestamp(
                point["synced_at_ms"] / 1000,
                timezone.utc,
            ).isocalendar()
            weekly_latest[(iso.year, iso.week)] = point
        weekly_points = []
        previous_week_live = Decimal("1")
        previous_week_paper = Decimal("1")
        for (iso_year, iso_week), point in weekly_latest.items():
            live_normalized = Decimal(str(point["live_normalized"]))
            paper_normalized = Decimal(str(point["paper_normalized"]))
            live_return = (
                live_normalized / previous_week_live - 1
                if previous_week_live else Decimal("0")
            )
            paper_return = (
                paper_normalized / previous_week_paper - 1
                if previous_week_paper else Decimal("0")
            )
            weekly_points.append({
                "iso_year": iso_year,
                "iso_week": iso_week,
                "synced_at_ms": point["synced_at_ms"],
                "live_normalized": point["live_normalized"],
                "paper_normalized": point["paper_normalized"],
                "weekly_deviation_pct": float((live_return - paper_return) * 100),
            })
            previous_week_live = live_normalized
            previous_week_paper = paper_normalized
        return {
            "status": "READY",
            "points": points,
            "weekly_points": weekly_points,
            "cumulative_deviation_pct": points[-1]["cumulative_deviation_pct"],
            "latest_weekly_deviation_pct": weekly_points[-1]["weekly_deviation_pct"],
            "structural_tracking_ratio": points[-1]["executable_notional_ratio"],
            **live_small_drawdown_projection(observations),
        }

    @staticmethod
    def _actual_quantities(
        positions: list[Mapping[str, Any]],
    ) -> dict[str, Decimal]:
        result: dict[str, Decimal] = {}
        for position in positions:
            symbol = str(position.get("symbol") or "").upper()
            if not symbol:
                continue
            raw = Decimal(str(position.get("position_amt") or 0))
            side = str(position.get("position_side") or "BOTH").upper()
            if side == "LONG":
                signed = abs(raw)
            elif side == "SHORT":
                signed = -abs(raw)
            else:
                signed = raw
            result[symbol] = result.get(symbol, Decimal("0")) + signed
        return result

    @staticmethod
    def _account_equity(snapshot: Mapping[str, Any]) -> Decimal:
        margin = Decimal(str(snapshot.get("total_margin_balance") or 0))
        if margin > 0:
            return margin
        return Decimal(str(snapshot.get("total_wallet_balance") or 0))

    @staticmethod
    def _timestamp_ms(value: Any) -> int:
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
        raise ValueError("synced account snapshot is missing synced_at")

    def _base(
        self,
        status: str,
        *,
        checklist: Mapping[str, Any] | None = None,
        account_status: Any = None,
    ) -> dict[str, Any]:
        return {
            "protocol": "LIVE_SMALL_RECONCILIATION_V1",
            "status": status,
            "read_only": True,
            "auto_correction": False,
            "account_id": self.live_account_id or None,
            "account_status": account_status,
            "checklist_status": (checklist or {}).get("status"),
            "positions": None,
            "equity": self._equity_projection() if self.live_account_id else {
                "status": "NO_OBSERVATIONS",
                "points": [],
                "weekly_points": [],
                "cumulative_deviation_pct": None,
                "latest_weekly_deviation_pct": None,
                **live_small_drawdown_projection([]),
            },
            "last_record_error": self.last_record_error,
            "ledger": self.equity_ledger.status(),
        }
