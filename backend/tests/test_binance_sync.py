import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.infrastructure.exchange import binance_snapshots
from orbit.infrastructure.exchange.binance_snapshots import BinanceSnapshotFetcher
from orbit.infrastructure.credentials.account_connection import VaultAccountConnectionInspector
from orbit.infrastructure.credentials.local_vault import LocalCredentialVault


class FakeBinanceFuturesClient:
    @classmethod
    def from_account(cls, account, vault):
        return cls()

    def account_information(self):
        return {
            "totalWalletBalance": "100.5",
            "totalMarginBalance": "104.5",
            "availableBalance": "80.25",
            "totalUnrealizedProfit": "4",
            "totalInitialMargin": "20",
            "assets": [
                {
                    "asset": "USDT",
                    "walletBalance": "100.5",
                    "marginBalance": "104.5",
                    "availableBalance": "80.25",
                    "unrealizedProfit": "4",
                }
            ],
        }

    def position_risk(self):
        return [
            {
                "symbol": "BTCUSDT",
                "positionSide": "LONG",
                "positionAmt": "0.01",
                "entryPrice": "60000",
                "breakEvenPrice": "60010",
                "markPrice": "61000",
                "unRealizedProfit": "10",
                "liquidationPrice": "40000",
                "notional": "610",
                "marginAsset": "USDT",
                "initialMargin": "20",
                "maintMargin": "2",
                "adl": 1,
                "updateTime": 1,
            },
            {
                "symbol": "XRPUSDT",
                "positionSide": "LONG",
                "positionAmt": "10",
                "entryPrice": "1",
                "breakEvenPrice": "1",
                "markPrice": "1.1",
                "unRealizedProfit": "1",
                "liquidationPrice": "0.1",
                "notional": "11",
                "marginAsset": "USDT",
                "initialMargin": "1",
                "maintMargin": "0.1",
                "adl": 0,
                "updateTime": 1,
            },
        ]

    def position_mode(self):
        return {"dualSidePosition": True}


class BinanceSnapshotFetcherTest(unittest.TestCase):
    def fetcher(self):
        vault = LocalCredentialVault()
        return BinanceSnapshotFetcher(vault, VaultAccountConnectionInspector(vault))

    def test_missing_credentials_is_safe(self):
        account = {"id": "acc_001", "account_label": "Main"}
        result = self.fetcher().sync_account(account, {"symbols": ["BTCUSDT"]})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "missing_credentials")
        self.assertFalse(result["api_key_present"])
        self.assertFalse(result["secret_present"])

    def test_sync_normalizes_hedge_mode_and_strategy_positions(self):
        account = {
            "id": "acc_001",
            "account_label": "Main",
            "api_key_ref": "env:ORBIT_TEST_BINANCE_KEY",
            "secret_ref": "env:ORBIT_TEST_BINANCE_SECRET",
            "hedge_mode_required": True,
        }

        with patch.dict(
            os.environ,
            {"ORBIT_TEST_BINANCE_KEY": "key", "ORBIT_TEST_BINANCE_SECRET": "secret"},
            clear=False,
        ), patch.object(binance_snapshots, "BinanceFuturesClient", FakeBinanceFuturesClient):
            result = self.fetcher().sync_account(
                account,
                {"symbols": ["BTCUSDT"]},
                mock_data_enabled=True,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "synced")
        self.assertTrue(result["position_mode"]["dual_side_position"])
        self.assertTrue(result["position_mode"]["hedge_mode_ok"])
        self.assertEqual(result["total_wallet_balance"], 100.5)
        self.assertEqual([item["symbol"] for item in result["positions"]], ["BTCUSDT"])


if __name__ == "__main__":
    unittest.main()
