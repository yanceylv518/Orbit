import json
import tempfile
import unittest
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.bootstrap import create_app_state
from orbit.config import load_config


class AppStateAdminTest(unittest.TestCase):
    def make_app(self, mock_data_enabled=False, login_required=True):
        tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(tmp.name)
        cfg = load_config(str(ROOT / "config" / "config.sample.json"))
        cfg["runtime"]["mock_data_enabled"] = mock_data_enabled
        cfg["runtime"]["auto_start"] = mock_data_enabled
        cfg["auth"]["login_required"] = login_required
        cfg["storage"] = {
            "driver": "json",
            "json_path": str(tmp_path / "runtime_state.json"),
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        app = create_app_state(str(config_path))
        return tmp, app

    def test_admin_overview_and_emergency_stop(self):
        tmp, app = self.make_app(mock_data_enabled=True)
        try:
            snapshot = app.snapshot()
            self.assertEqual(len(snapshot["admin_overview"]["users"]), 1)
            self.assertEqual(snapshot["admin_overview"]["users"][0]["user_id"], "user_001")
            self.assertNotIn("strategy_count", snapshot["admin_overview"]["users"][0])
            self.assertEqual(len(snapshot["admin_overview"]["accounts"]), 1)
            self.assertNotIn("strategy_id", snapshot["admin_overview"]["accounts"][0])

            stopped = app.admin_emergency_stop(actor="admin_001")
            self.assertFalse(stopped["running"])
            self.assertEqual(stopped["strategy"]["status"], "emergency_stopped")
            self.assertEqual(stopped["admin_overview"]["accounts"][0]["account_status"], "paused_by_admin")

            resumed = app.admin_resume(actor="admin_001")
            self.assertTrue(resumed["running"])
            self.assertEqual(resumed["strategy"]["status"], "running")
            self.assertEqual(resumed["admin_overview"]["accounts"][0]["account_status"], "active")
        finally:
            tmp.cleanup()

    def test_login_session_and_user_scope(self):
        tmp, app = self.make_app()
        try:
            login = app.authenticate("user_001", "user123456")
            self.assertTrue(login["ok"])

            user = app.current_user(login["session_token"])
            self.assertEqual(user["id"], "user_001")

            snapshot = app.snapshot(user)
            self.assertTrue(snapshot["auth"]["authenticated"])
            self.assertEqual(snapshot["auth"]["current_user"]["id"], "user_001")
            self.assertEqual(len(snapshot["users"]), 1)
            self.assertEqual(snapshot["users"][0]["id"], "user_001")
            self.assertEqual(len(snapshot["account_run_configs"]), 1)
            self.assertEqual(len(snapshot["admin_overview"]["accounts"]), 1)
            self.assertFalse(snapshot["admin_overview"]["permissions"]["can_view_all_accounts"])
            self.assertFalse(snapshot["auth"]["permissions"]["can_update_strategy"])
            self.assertFalse(snapshot["auth"]["permissions"]["can_generate_report"])
            self.assertNotIn("secret_ref", snapshot["exchange_accounts"][0])

            app.logout(login["session_token"])
            self.assertIsNone(app.current_user(login["session_token"]))
        finally:
            tmp.cleanup()

    def test_default_snapshot_keeps_internal_history_out_of_ui_payload(self):
        tmp, app = self.make_app(mock_data_enabled=True)
        try:
            app.tick_once()
            snapshot = app.snapshot(app.user_by_id("admin_001"))
            self.assertEqual(snapshot["metric_history"], [])
            self.assertEqual(snapshot["symbol_metric_history"], {})
            self.assertEqual(snapshot["trade_events"], [])

            full = app.snapshot(app.user_by_id("admin_001"), include_internal_history=True)
            self.assertGreater(len(full["metric_history"]), 0)
            self.assertGreater(len(full["symbol_metric_history"]), 0)
        finally:
            tmp.cleanup()

    def test_mock_data_disabled_starts_with_empty_runtime_symbols(self):
        tmp, app = self.make_app()
        try:
            snapshot = app.snapshot(app.user_by_id("admin_001"))
            self.assertFalse(snapshot["running"])
            self.assertEqual(snapshot["strategy"]["mode"], "read_only")
            self.assertEqual(snapshot["strategy"]["status"], "read_only")
            self.assertEqual(snapshot["symbols"], [])
            self.assertEqual(snapshot["price_history"], {})
            self.assertEqual(snapshot["strategy_events"], [])
            self.assertEqual(snapshot["daily_reports"], [])
        finally:
            tmp.cleanup()

    def test_binance_sync_missing_credentials_is_safe(self):
        tmp, app = self.make_app()
        try:
            admin_result = app.sync_binance_account("binance_dry_run_001", actor="admin_001")
            self.assertFalse(admin_result["ok"])
            self.assertEqual(admin_result["status"], "missing_credentials")

            result = app.sync_binance_account("binance_dry_run_001", actor="user_001")
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "missing_credentials")
            snapshot = app.snapshot(app.user_by_id("admin_001"))
            self.assertIn("binance_dry_run_001", snapshot["binance_account_snapshots"])
            self.assertEqual(snapshot["execution_plans"][0]["status"], "blocked")
            self.assertEqual(snapshot["execution_plans"][0]["event_type"], "SYNC_REQUIRED")
        finally:
            tmp.cleanup()

    def test_no_login_mode_uses_default_operator(self):
        tmp, app = self.make_app(login_required=False)
        try:
            user = app.current_user(None)
            self.assertIsNotNone(user)
            self.assertEqual(user["id"], "admin_001")
            snapshot = app.snapshot(user)
            self.assertTrue(snapshot["auth"]["authenticated"])
            self.assertFalse(snapshot["auth"]["login_required"])
        finally:
            tmp.cleanup()

    def test_execution_plan_generation_from_real_snapshot(self):
        tmp, app = self.make_app()
        try:
            account_id = "binance_dry_run_001"
            app.binance_account_snapshots[account_id] = {
                "ok": True,
                "status": "synced",
                "account_id": account_id,
                "synced_at": "2026-07-07T00:00:00+00:00",
                "position_mode": {
                    "dual_side_position": True,
                    "hedge_mode_required": True,
                    "hedge_mode_ok": True,
                },
                "positions": [
                    {
                        "symbol": "BTCUSDT",
                        "position_side": "LONG",
                        "position_amt": 0.01,
                        "entry_price": 60000,
                        "mark_price": 62000,
                        "unrealized_profit": 20,
                        "notional": 620,
                    },
                    {
                        "symbol": "BTCUSDT",
                        "position_side": "SHORT",
                        "position_amt": -0.01,
                        "entry_price": 62100,
                        "mark_price": 62000,
                        "unrealized_profit": -1,
                        "notional": -620,
                    },
                ],
            }

            result = app.generate_execution_plans(account_id, actor="user_001")
            self.assertTrue(result["ok"])
            plan = result["plans"][0]
            self.assertEqual(plan["event_type"], "PROFIT_TRANSFER_UP")
            self.assertEqual(plan["status"], "planned")
            self.assertEqual(plan["trigger"]["exposure_model"], "net_exposure_v1")
            self.assertEqual(plan["trigger"]["plan_state_source"], "symbol_state")
            self.assertEqual(plan["trigger"]["plan_state"], "BALANCED")
            self.assertLess(plan["trigger"]["target_net_qty"], 0)
            self.assertTrue(any(action["action"] == "REDUCE_LONG" for action in plan["actions"]))
            self.assertTrue(any(action["action"] == "ADD_SHORT" and action["status"] == "blocked" for action in plan["actions"]))
            self.assertIn("binance_dry_run_001::BTCUSDT", app.symbol_states)

            snapshot = app.snapshot(app.user_by_id("user_001"))
            self.assertEqual(snapshot["execution_plans"][0]["account_id"], account_id)
        finally:
            tmp.cleanup()

    def test_execution_plan_uses_symbol_state_to_block_unconfirmed_trend_exit(self):
        tmp, app = self.make_app()
        try:
            account_id = "binance_dry_run_001"
            app.symbol_states["BTCUSDT"] = {
                "symbol": "BTCUSDT",
                "state": "TREND_UP",
                "base_price": "60000",
                "base_qty": "0.00066666",
                "high_since_base": "62500",
                "low_since_base": "60000",
                "trend_extreme_price": "62500",
                "last_price": "62500",
                "long_qty": "0.00066666",
                "short_qty": "0.00030000",
                "long_entry_price": "60000",
                "short_entry_price": "62500",
                "budget_usdt": "100",
                "realized_pnl": "0",
                "long_unrealized_pnl": "0",
                "short_unrealized_pnl": "0",
                "fee_total": "0",
                "slippage_total": "0",
                "funding_total": "0",
                "trend_exit_candidate_count": 0,
                "profit_transfer_count_in_trend": 0,
                "loss_side_reduce_count_in_trend": 1,
                "recovery_count_in_trend": 0,
                "last_transfer_tick": -999999,
                "last_loss_reduce_tick": 1,
                "last_transfer_price": None,
                "last_loss_reduce_price": "62500",
                "tick_count": 1,
            }
            app.binance_account_snapshots[account_id] = {
                "ok": True,
                "status": "synced",
                "account_id": account_id,
                "synced_at": "2026-07-07T00:00:00+00:00",
                "position_mode": {
                    "dual_side_position": True,
                    "hedge_mode_required": True,
                    "hedge_mode_ok": True,
                },
                "positions": [
                    {
                        "symbol": "BTCUSDT",
                        "position_side": "LONG",
                        "position_amt": 0.00066666,
                        "entry_price": 60000,
                        "mark_price": 60700,
                        "unrealized_profit": 0.466662,
                        "notional": 40.466262,
                    },
                    {
                        "symbol": "BTCUSDT",
                        "position_side": "SHORT",
                        "position_amt": -0.00030000,
                        "entry_price": 62500,
                        "mark_price": 60700,
                        "unrealized_profit": 0.54,
                        "notional": -18.21,
                    },
                ],
            }

            result = app.generate_execution_plans(account_id, actor="user_001")

            self.assertTrue(result["ok"])
            plan = result["plans"][0]
            self.assertEqual(plan["event_type"], "POSITION_RECOVERY_DOWN")
            self.assertEqual(plan["status"], "blocked")
            self.assertEqual(plan["trigger"]["plan_state"], "TREND_UP")
            self.assertEqual(plan["trigger"]["event_rule"], "TREND_EXIT_NOT_CONFIRMED")
            self.assertEqual(app.symbol_states["binance_dry_run_001::BTCUSDT"]["trend_exit_candidate_count"], 1)
        finally:
            tmp.cleanup()

    def test_execution_plan_manual_confirm_and_export_are_audited(self):
        tmp, app = self.make_app()
        try:
            account_id = "binance_dry_run_001"
            app.binance_account_snapshots[account_id] = {
                "ok": True,
                "status": "synced",
                "account_id": account_id,
                "synced_at": "2026-07-07T00:00:00+00:00",
                "position_mode": {
                    "dual_side_position": True,
                    "hedge_mode_required": True,
                    "hedge_mode_ok": True,
                },
                "positions": [
                    {
                        "symbol": "BTCUSDT",
                        "position_side": "LONG",
                        "position_amt": 0.01,
                        "entry_price": 60000,
                        "mark_price": 62000,
                        "unrealized_profit": 20,
                        "notional": 620,
                    },
                    {
                        "symbol": "BTCUSDT",
                        "position_side": "SHORT",
                        "position_amt": -0.01,
                        "entry_price": 62100,
                        "mark_price": 62000,
                        "unrealized_profit": -1,
                        "notional": -620,
                    },
                ],
            }
            plan = app.generate_execution_plans(account_id, actor="user_001")["plans"][0]

            confirmed = app.confirm_execution_plan(plan["id"], actor="user_001", note="人工核对通过")
            self.assertTrue(confirmed["ok"])
            self.assertEqual(confirmed["plan"]["manual_review"]["status"], "confirmed")
            self.assertEqual(confirmed["plan"]["manual_review"]["reviewed_by"], "user_001")

            exported = app.record_execution_plan_export([plan["id"]], actor="admin_001")
            self.assertTrue(exported["ok"])
            self.assertEqual(exported["plan_count"], 1)
            self.assertEqual(exported["status_counts"]["confirmed"], 1)

            snapshot = app.snapshot(app.user_by_id("admin_001"))
            latest_actions = [item["action_type"] for item in snapshot["admin_audit_logs"][:2]]
            self.assertEqual(latest_actions, ["EXPORT_EXECUTION_PLANS", "CONFIRM_EXECUTION_PLAN"])
            self.assertEqual(snapshot["execution_plans"][0]["last_export"]["id"], exported["export_id"])
        finally:
            tmp.cleanup()

    def test_binance_credentials_can_be_set_by_owner_or_admin(self):
        if not sys.platform.startswith("win"):
            self.skipTest("Account credential encryption uses Windows DPAPI in local V1.")
        tmp, app = self.make_app()
        try:
            admin_updated = app.update_binance_credentials(
                "binance_dry_run_001",
                "admin_001",
                "admin-key",
                "admin-secret",
            )
            self.assertTrue(admin_updated["ok"])

            updated = app.update_binance_credentials(
                "binance_dry_run_001",
                "user_001",
                "test-key",
                "test-secret",
            )
            self.assertTrue(updated["ok"])

            account = app.account_by_id("binance_dry_run_001")
            self.assertTrue(account["api_key_ref"].startswith("dpapi:"))
            self.assertTrue(account["secret_ref"].startswith("dpapi:"))
            snapshot = app.snapshot(app.user_by_id("user_001"))
            account_view = snapshot["exchange_accounts"][0]
            self.assertTrue(account_view["api_key_present"])
            self.assertTrue(account_view["secret_present"])
            self.assertEqual(account_view["api_key_fingerprint"], updated["api_key_fingerprint"])
        finally:
            tmp.cleanup()

    def test_admin_can_upsert_business_user_and_exchange_account(self):
        tmp, app = self.make_app()
        try:
            forbidden = app.upsert_business_user(
                {"user_id": "user_002", "name": "新用户"},
                actor="user_001",
            )
            self.assertFalse(forbidden["ok"])

            user_result = app.upsert_business_user(
                {
                    "user_id": "user_002",
                    "name": "实盘测试用户",
                    "email": "trader@example.com",
                    "status": "active",
                },
                actor="admin_001",
            )
            self.assertTrue(user_result["ok"])
            self.assertEqual(app.user_by_id("user_002")["role"], "user")

            admin_bind = app.upsert_exchange_account(
                {
                    "account_id": "binance_admin_001",
                    "user_id": "admin_001",
                    "account_label": "Wrong Owner",
                },
                actor="admin_001",
            )
            self.assertFalse(admin_bind["ok"])

            account_result = app.upsert_exchange_account(
                {
                    "account_id": "binance_live_002",
                    "user_id": "user_002",
                    "account_label": "Binance Futures Live 002",
                    "testnet": False,
                    "dry_run": True,
                    "hedge_mode_required": True,
                    "status": "active",
                },
                actor="admin_001",
            )
            self.assertTrue(account_result["ok"])

            snapshot = app.snapshot(app.user_by_id("admin_001"))
            user_ids = {user["user_id"] for user in snapshot["admin_overview"]["users"]}
            account_ids = {account["account_id"] for account in snapshot["admin_overview"]["accounts"]}
            self.assertIn("user_002", user_ids)
            self.assertIn("binance_live_002", account_ids)
            self.assertTrue(any(cfg["account_id"] == "binance_live_002" for cfg in snapshot["account_run_configs"]))
            account_view = next(item for item in snapshot["exchange_accounts"] if item["id"] == "binance_live_002")
            self.assertNotIn("secret_ref", account_view)
            self.assertFalse(account_view["testnet"])
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
