import unittest

from orbit.application.snapshot_queries import SnapshotQueryService


class FakePermissions:
    def is_admin(self, user):
        return user.get("role") == "admin"

    def capabilities(self, user):
        return {"can_view_all_accounts": self.is_admin(user)}


class FakeDirectory:
    def visible_account_ids(self, user):
        return {"acc_001"}


class FakePortfolioViews:
    def real_symbol_views(self, account_ids=None):
        return [{"symbol": "BTCUSDT", "account_id": "acc_001"}]

    def totals(self, symbols):
        return {"today_pnl": 0, "today_pnl_pct": 0, "total_equity": 0}

    def strategy_summary(self, symbols, totals, *, running, account_ids=None):
        return {"symbols": [item["symbol"] for item in symbols], "status": "read_only"}

    def global_stop_active(self):
        return True


class SnapshotQueryServiceTests(unittest.TestCase):
    def setUp(self):
        empty_repository = object()
        self.service = SnapshotQueryService(
            {"auth": {"login_required": False}},
            {},
            FakePermissions(),
            FakeDirectory(),
            empty_repository,
            empty_repository,
            empty_repository,
            empty_repository,
            empty_repository,
            empty_repository,
            empty_repository,
            FakePortfolioViews(),
            lambda: {"driver": "json"},
            lambda: {"status": "NOT_STARTED"},
            mock_data_enabled=False,
        )

    def test_public_snapshot_exposes_only_auth_state(self):
        snapshot = self.service.public_snapshot()

        self.assertFalse(snapshot["auth"]["authenticated"])
        self.assertFalse(snapshot["auth"]["login_required"])
        self.assertNotIn("users", snapshot)

    def test_business_user_projection_filters_account_scoped_data(self):
        payload = {
            "users": [{"id": "user_001"}, {"id": "user_002"}],
            "exchange_accounts": [{"id": "acc_001"}, {"id": "acc_002"}],
            "account_run_configs": [
                {"account_id": "acc_001"},
                {"account_id": "acc_002"},
            ],
            "binance_account_snapshots": {"acc_001": {}, "acc_002": {}},
            "admin_overview": {
                "users": [{"user_id": "user_001"}, {"user_id": "user_002"}],
                "accounts": [{"user_id": "user_001"}, {"user_id": "user_002"}],
            },
            "strategy_events": [{"user_id": "user_001"}, {"user_id": "user_002"}],
            "trade_events": [{"user_id": "user_001"}, {"user_id": "user_002"}],
            "risk_events": [{"user_id": None}, {"user_id": "user_002"}],
            "risk_state": {
                "global_stop": True,
                "stopped_symbols": [
                    {"account_id": "acc_001", "symbol": "BTCUSDT"},
                    {"account_id": "acc_002", "symbol": "ETHUSDT"},
                ],
                "blocked_decisions": [
                    {"exchange_account_id": "acc_001"},
                    {"exchange_account_id": "acc_002"},
                ],
            },
            "execution_plans": [
                {"account_id": "acc_001"},
                {"account_id": "acc_002"},
            ],
        }

        filtered = self.service.apply_permissions(
            payload,
            {"id": "user_001", "role": "user"},
            running=False,
        )

        self.assertEqual([item["id"] for item in filtered["exchange_accounts"]], ["acc_001"])
        self.assertEqual(list(filtered["binance_account_snapshots"]), ["acc_001"])
        self.assertEqual(filtered["execution_plans"], [{"account_id": "acc_001"}])
        self.assertEqual(filtered["risk_events"], [{"user_id": None}])
        self.assertTrue(filtered["risk_state"]["global_stop"])
        self.assertEqual(
            filtered["risk_state"]["stopped_symbols"],
            [{"account_id": "acc_001", "symbol": "BTCUSDT"}],
        )
        self.assertEqual(
            filtered["risk_state"]["blocked_decisions"],
            [{"exchange_account_id": "acc_001"}],
        )
        self.assertEqual(filtered["strategy"]["symbols"], ["BTCUSDT"])

    def test_blocked_decisions_include_only_info_level_blocked_events(self):
        rows = self.service.blocked_decision_rows([
            {"id": "blocked-status", "risk_level": "info", "status": "blocked"},
            {"id": "blocked-action", "risk_level": "info", "action_taken": "BLOCKED_NO_TRADE"},
            {"id": "material", "risk_level": "high", "status": "blocked"},
            {"id": "informational", "risk_level": "info", "status": "observed"},
        ])

        self.assertEqual([row["id"] for row in rows], ["blocked-status", "blocked-action"])

    def test_risk_state_exposes_global_stop_stopped_symbols_and_blocked_decisions(self):
        risk_state = self.service.risk_state(
            [{
                "id": "blocked",
                "risk_level": "info",
                "status": "blocked",
                "action_taken": "BLOCKED_NO_TRADE",
            }],
            [{"account_id": "acc_001", "symbol": "BTCUSDT"}],
        )

        self.assertTrue(risk_state["global_stop"])
        self.assertEqual(
            risk_state["stopped_symbols"],
            [{"account_id": "acc_001", "symbol": "BTCUSDT"}],
        )
        self.assertEqual([row["id"] for row in risk_state["blocked_decisions"]], ["blocked"])


if __name__ == "__main__":
    unittest.main()
