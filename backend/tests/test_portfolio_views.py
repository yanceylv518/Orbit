import unittest

from orbit.application.portfolio_views import PortfolioViewService


class FakeAccountDirectory:
    def business_users(self):
        return [{
            "id": "user_001",
            "name": "Test User",
            "email": "test@example.com",
            "role": "user",
            "status": "active",
        }]


class FakeSnapshots:
    def __init__(self, snapshots):
        self.snapshots = snapshots

    def all(self):
        return self.snapshots

    def get(self, account_id):
        return self.snapshots.get(account_id)


class FakeEvents:
    def __init__(self, risks=None):
        self.risks = risks or []

    def strategy_events(self):
        return [{
            "exchange_account_id": "acc_001",
            "timestamp": "2026-07-10T10:00:00Z",
        }]

    def risk_events(self):
        return self.risks


class PortfolioViewServiceTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "exchange_accounts": [{
                "id": "acc_001",
                "user_id": "user_001",
                "account_label": "Primary",
                "exchange": "binance",
                "market_type": "futures",
                "status": "active",
            }],
        }
        self.snapshot = {
            "status": "synced",
            "total_margin_balance": "1020",
            "total_unrealized_profit": "20",
            "positions": [{
                "symbol": "BTCUSDT",
                "position_side": "SHORT",
                "position_amt": "-0.1",
                "notional": "-6000",
                "mark_price": "60000",
                "entry_price": "59000",
                "unrealized_profit": "-100",
            }],
        }
        self.service = PortfolioViewService(
            self.config,
            {
                "id": "strategy_001",
                "strategy_name": "Dynamic Dual Grid",
                "strategy_version": "1",
                "mode": "plan_only",
            },
            FakeAccountDirectory(),
            FakeSnapshots({"acc_001": self.snapshot}),
            FakeEvents(),
            mock_data_enabled=False,
        )

    def test_real_position_and_portfolio_totals(self):
        rows = self.service.real_symbol_views()
        totals = self.service.real_portfolio_totals()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["short_qty"], 0.1)
        self.assertEqual(rows[0]["gross_exposure"], 6000.0)
        self.assertEqual(totals["total_budget"], 1000.0)
        self.assertEqual(totals["total_equity"], 1020.0)
        self.assertEqual(totals["today_pnl_pct"], 2.0)

    def test_admin_overview_keeps_user_account_ownership(self):
        overview = self.service.admin_overview(self.service.real_symbol_views())

        self.assertEqual(overview["users"][0]["account_count"], 1)
        self.assertEqual(overview["users"][0]["total_equity"], 1020.0)
        self.assertEqual(overview["accounts"][0]["user_id"], "user_001")
        self.assertEqual(overview["accounts"][0]["symbols"], ["BTCUSDT"])
        self.assertEqual(overview["accounts"][0]["last_event_at"], "2026-07-10T10:00:00Z")

    def test_info_decision_block_does_not_raise_portfolio_risk_status(self):
        self.service.event_history = FakeEvents([{
            "exchange_account_id": "acc_001",
            "timestamp": "2026-07-10T11:00:00Z",
            "risk_level": "info",
            "risk_type": "REGIME_TRENDING_BLOCKED",
        }])

        summary = self.service.strategy_summary([], {}, running=False)
        overview = self.service.admin_overview(self.service.real_symbol_views())

        self.assertEqual(summary["risk_status"], "normal")
        self.assertEqual(overview["accounts"][0]["risk_status"], "normal")
        self.assertIsNone(overview["accounts"][0]["last_risk_at"])


if __name__ == "__main__":
    unittest.main()
