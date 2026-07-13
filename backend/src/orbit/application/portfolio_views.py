from __future__ import annotations

from decimal import Decimal
from typing import Any

from orbit.domain.strategy.engine import d


class PortfolioViewService:
    """Builds account, position and strategy read models from runtime repositories."""

    def __init__(
        self,
        config: dict[str, Any],
        strategy: dict[str, Any],
        account_directory: Any,
        account_snapshots: Any,
        event_history: Any,
        *,
        mock_data_enabled: bool,
    ) -> None:
        self.config = config
        self.strategy = strategy
        self.account_directory = account_directory
        self.account_snapshots = account_snapshots
        self.event_history = event_history
        self.mock_data_enabled = mock_data_enabled

    def runtime_symbols(
        self,
        symbol_states: dict[str, dict[str, Any]],
        account_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        if self.mock_data_enabled:
            return [self.symbol_view(symbol, state) for symbol, state in symbol_states.items()]
        return self.real_symbol_views(account_ids)

    def real_symbol_views(self, account_ids: set[str] | None = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        account_by_id = {
            account["id"]: account
            for account in self.config.get("exchange_accounts", [])
        }
        for account_id, snapshot in self.account_snapshots.all().items():
            if account_ids is not None and account_id not in account_ids:
                continue
            if snapshot.get("status") != "synced" and not snapshot.get("ok"):
                continue
            for position in snapshot.get("positions") or []:
                symbol = position.get("symbol")
                if not symbol:
                    continue
                qty = float(position.get("position_amt") or 0)
                notional = float(position.get("notional") or 0)
                mark_price = float(position.get("mark_price") or 0)
                entry_price = float(position.get("entry_price") or 0)
                pnl = float(position.get("unrealized_profit") or 0)
                side = str(position.get("position_side") or "BOTH").upper()
                is_short = side == "SHORT" or qty < 0
                long_qty = abs(qty) if not is_short else 0
                short_qty = abs(qty) if is_short else 0
                account = account_by_id.get(account_id, {})
                rows.append({
                    "symbol": symbol,
                    "account_id": account_id,
                    "account_label": account.get("account_label", account_id),
                    "state": "REAL_POSITION",
                    "price": mark_price or entry_price,
                    "base_price": entry_price or mark_price,
                    "move_pct": ((mark_price / entry_price) - 1) * 100 if mark_price and entry_price else 0,
                    "high_since_base": mark_price or entry_price,
                    "low_since_base": mark_price or entry_price,
                    "long_qty": long_qty,
                    "short_qty": short_qty,
                    "base_qty": 0,
                    "long_entry_price": entry_price if long_qty else 0,
                    "short_entry_price": entry_price if short_qty else 0,
                    "long_unrealized_pnl": pnl if long_qty else 0,
                    "short_unrealized_pnl": pnl if short_qty else 0,
                    "unrealized_pnl": pnl,
                    "realized_pnl": 0,
                    "fee_total": 0,
                    "slippage_total": 0,
                    "funding_total": 0,
                    "net_exposure": notional,
                    "gross_exposure": abs(notional),
                    "equity": pnl,
                    "budget_usdt": 0,
                    "profit_transfer_count": 0,
                    "loss_side_reduce_count": 0,
                    "recovery_count": 0,
                    "source": "binance",
                })
        return sorted(rows, key=lambda item: (item["account_label"], item["symbol"], item["short_qty"] > 0))

    def real_account_totals(self, account_id: str) -> dict[str, float | bool]:
        snapshot = self.account_snapshots.get(account_id) or {}
        if snapshot.get("status") != "synced" and not snapshot.get("ok"):
            return {
                "has_real_data": False,
                "total_equity": 0.0,
                "today_pnl": 0.0,
                "today_pnl_pct": 0.0,
                "total_budget": 0.0,
            }
        total_equity = float(snapshot.get("total_margin_balance") or snapshot.get("total_wallet_balance") or 0)
        today_pnl = float(snapshot.get("total_unrealized_profit") or 0)
        basis = total_equity - today_pnl
        return {
            "has_real_data": True,
            "total_equity": total_equity,
            "today_pnl": today_pnl,
            "today_pnl_pct": (today_pnl / basis * 100) if basis else 0.0,
            "total_budget": basis,
        }

    def real_portfolio_totals(self, account_ids: set[str] | None = None) -> dict[str, float]:
        totals = {
            "total_budget": 0.0,
            "total_equity": 0.0,
            "today_pnl": 0.0,
            "today_pnl_pct": 0.0,
            "total_unrealized": 0.0,
            "total_realized": 0.0,
            "total_fees": 0.0,
            "total_slippage": 0.0,
            "max_drawdown": 0.0,
        }
        for account in self.config.get("exchange_accounts", []):
            account_id = account["id"]
            if account_ids is not None and account_id not in account_ids:
                continue
            account_totals = self.real_account_totals(account_id)
            if not account_totals["has_real_data"]:
                continue
            totals["total_budget"] += float(account_totals["total_budget"])
            totals["total_equity"] += float(account_totals["total_equity"])
            totals["today_pnl"] += float(account_totals["today_pnl"])
            totals["total_unrealized"] += float(account_totals["today_pnl"])
        totals["today_pnl_pct"] = (
            totals["today_pnl"] / totals["total_budget"] * 100
            if totals["total_budget"]
            else 0.0
        )
        return totals

    @staticmethod
    def symbol_view(symbol: str, state: dict[str, Any]) -> dict[str, Any]:
        price = d(state["last_price"])
        base = d(state["base_price"])
        return {
            "symbol": symbol,
            "state": state["state"],
            "price": float(price),
            "base_price": float(base),
            "move_pct": float((price / base - Decimal("1")) * Decimal("100")),
            "high_since_base": float(d(state["high_since_base"])),
            "low_since_base": float(d(state["low_since_base"])),
            "long_qty": float(d(state["long_qty"])),
            "short_qty": float(d(state["short_qty"])),
            "base_qty": float(d(state["base_qty"])),
            "long_entry_price": float(d(state["long_entry_price"])),
            "short_entry_price": float(d(state["short_entry_price"])),
            "long_unrealized_pnl": float(d(state["long_unrealized_pnl"])),
            "short_unrealized_pnl": float(d(state["short_unrealized_pnl"])),
            "unrealized_pnl": float(d(state["long_unrealized_pnl"]) + d(state["short_unrealized_pnl"])),
            "realized_pnl": float(d(state["realized_pnl"])),
            "fee_total": float(d(state["fee_total"])),
            "slippage_total": float(d(state["slippage_total"])),
            "funding_total": float(d(state["funding_total"])),
            "net_exposure": float(d(state.get("net_exposure", "0"))),
            "gross_exposure": float(d(state.get("gross_exposure", "0"))),
            "equity": float(d(state.get("equity", state["budget_usdt"]))),
            "budget_usdt": float(d(state["budget_usdt"])),
            "profit_transfer_count": int(state.get("profit_transfer_count_in_trend", 0)),
            "loss_side_reduce_count": int(state.get("loss_side_reduce_count_in_trend", 0)),
            "recovery_count": int(state.get("recovery_count_in_trend", 0)),
        }

    @staticmethod
    def totals(symbols: list[dict[str, Any]]) -> dict[str, float]:
        total_budget = sum(item["budget_usdt"] for item in symbols)
        total_equity = sum(item["equity"] for item in symbols)
        return {
            "total_budget": total_budget,
            "total_equity": total_equity,
            "today_pnl": total_equity - total_budget,
            "today_pnl_pct": ((total_equity / total_budget) - 1) * 100 if total_budget else 0,
            "total_unrealized": sum(item["unrealized_pnl"] for item in symbols),
            "total_realized": sum(item["realized_pnl"] for item in symbols),
            "total_fees": sum(item["fee_total"] for item in symbols),
            "total_slippage": sum(item["slippage_total"] for item in symbols),
            "max_drawdown": min(0, min((item["equity"] - item["budget_usdt"] for item in symbols), default=0)),
        }

    def strategy_summary(
        self,
        symbols: list[dict[str, Any]],
        totals: dict[str, float],
        *,
        running: bool,
        account_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        display_totals = totals if self.mock_data_enabled else self.real_portfolio_totals(account_ids)
        status = self.strategy.get("status", "running" if running else "paused")
        if running and status in ("paused", "emergency_stopped"):
            status = "running"
        if not running and status == "running":
            status = "paused"
        if not self.mock_data_enabled:
            status = "read_only"
        material_risks = self.material_risk_events()
        return {
            "id": self.strategy["id"],
            "scope": "system",
            "name": self.strategy["strategy_name"],
            "version": self.strategy["strategy_version"],
            "mode": "read_only" if not self.mock_data_enabled else self.strategy["mode"],
            "status": status,
            "symbol_count": len(symbols),
            "symbols": [item["symbol"] for item in symbols],
            "today_pnl": display_totals["today_pnl"],
            "today_pnl_pct": display_totals["today_pnl_pct"],
            "total_equity": display_totals["total_equity"],
            "risk_status": "normal" if not material_risks else "watch",
        }

    def material_risk_events(self) -> list[dict[str, Any]]:
        return [
            risk for risk in self.event_history.risk_events()
            if str(risk.get("risk_level") or "").lower() != "info"
        ]

    def admin_overview(self, symbols: list[dict[str, Any]]) -> dict[str, Any]:
        business_users = self.account_directory.business_users()
        user_by_id = {user["id"]: user for user in business_users}
        account_rows = []
        for account in self.config["exchange_accounts"]:
            user = user_by_id.get(account["user_id"])
            if not user:
                continue
            account_totals = self.real_account_totals(account["id"])
            account_risks = [
                risk for risk in self.material_risk_events()
                if risk.get("exchange_account_id") == account["id"]
            ]
            account_events = [
                event for event in self.event_history.strategy_events()
                if event.get("exchange_account_id") == account["id"]
            ]
            account_rows.append({
                "user_id": user["id"],
                "user_name": user.get("name", user["id"]),
                "account_id": account["id"],
                "account_label": account.get("account_label", account["id"]),
                "exchange": account.get("exchange", "-"),
                "market_type": account.get("market_type", "-"),
                "testnet": bool(account.get("testnet", False)),
                "dry_run": bool(account.get("dry_run", False)),
                "hedge_mode_required": bool(account.get("hedge_mode_required", account.get("hedge_mode_enabled", False))),
                "account_status": account.get("status", "active"),
                "symbols": sorted({
                    item["symbol"] for item in symbols
                    if item.get("account_id") == account["id"]
                }),
                "total_budget": float(account_totals["total_budget"]),
                "total_equity": float(account_totals["total_equity"]),
                "today_pnl": float(account_totals["today_pnl"]),
                "risk_status": "watch" if account_risks else "normal",
                "last_event_at": account_events[0]["timestamp"] if account_events else None,
                "last_risk_at": account_risks[0]["timestamp"] if account_risks else None,
            })

        user_rows = []
        for user in business_users:
            accounts = [item for item in account_rows if item["user_id"] == user["id"]]
            user_rows.append({
                "user_id": user["id"],
                "user_name": user.get("name", user["id"]),
                "email": user.get("email"),
                "role": user.get("role", "user"),
                "status": user.get("status", "active"),
                "account_count": len(accounts),
                "total_equity": sum(float(account["total_equity"]) for account in accounts),
                "today_pnl": sum(float(account["today_pnl"]) for account in accounts),
                "risk_status": "watch" if any(account["risk_status"] == "watch" for account in accounts) else "normal",
            })
        return {
            "users": user_rows,
            "accounts": account_rows,
            "permissions": {
                "can_view_all_accounts": True,
                "can_emergency_stop": True,
                "can_resume_dry_run": True,
                "can_view_secret": False,
            },
        }
