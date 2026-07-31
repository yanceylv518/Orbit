import unittest
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.infrastructure.credentials.account_connection import VaultAccountConnectionInspector
from orbit.infrastructure.credentials.local_vault import LocalCredentialVault
from orbit.application.ports.credential_vault import CredentialVaultError
from orbit.infrastructure.exchange.binance import BinanceFuturesClient


class FailingResolveVault(LocalCredentialVault):
    def resolve(self, reference):
        raise CredentialVaultError("cannot decrypt")


class RecordingBinanceClient(BinanceFuturesClient):
    def __init__(self):
        super().__init__("key", "secret", testnet=False)
        self.calls = []

    def signed_request(self, method, path, params=None):
        self.calls.append((method, path, params))
        return {"ok": True}

    def public_request(self, method, path, params=None):
        self.calls.append((method, path, params))
        return {"symbol": "BTCUSDT", "price": "65000.10"}


class CredentialAdapterTest(unittest.TestCase):
    def test_fingerprint_is_short_and_stable(self):
        vault = LocalCredentialVault()
        self.assertEqual(vault.fingerprint("abc"), vault.fingerprint("abc"))
        self.assertEqual(len(vault.fingerprint("abc")), 16)

    def test_account_connection_flags_use_env_refs(self):
        account = {
            "api_key_ref": "env:DDG_TEST_MISSING_KEY",
            "secret_ref": "env:DDG_TEST_MISSING_SECRET",
        }
        status = VaultAccountConnectionInspector(LocalCredentialVault()).inspect(account)
        self.assertFalse(status["api_key_present"])
        self.assertFalse(status["secret_present"])
        self.assertEqual(status["api_key_env"], "DDG_TEST_MISSING_KEY")

    def test_account_connection_reports_vault_errors(self):
        account = {"api_key_ref": "dpapi:key", "secret_ref": "dpapi:secret"}

        status = VaultAccountConnectionInspector(FailingResolveVault()).inspect(account)

        self.assertFalse(status["api_key_present"])
        self.assertFalse(status["secret_present"])
        self.assertEqual(status["credential_error"], "cannot decrypt")

    def test_account_preparation_uses_signed_binance_controls(self):
        client = RecordingBinanceClient()

        client.change_position_mode(dual_side=False)
        client.change_leverage("btcusdt", 1)

        self.assertEqual(client.calls, [
            (
                "POST",
                "/fapi/v1/positionSide/dual",
                {"dualSidePosition": "false"},
            ),
            (
                "POST",
                "/fapi/v1/leverage",
                {"symbol": "BTCUSDT", "leverage": 1},
            ),
        ])

    def test_symbol_configuration_uses_dedicated_account_endpoint(self):
        client = RecordingBinanceClient()
        client.signed_request = lambda method, path, params=None: (
            client.calls.append((method, path, params))
            or [{"symbol": "BTCUSDT", "leverage": 1}]
        )

        payload = client.symbol_configuration("btcusdt")

        self.assertEqual(payload[0]["leverage"], 1)
        self.assertEqual(client.calls, [
            (
                "GET",
                "/fapi/v1/symbolConfig",
                {"symbol": "BTCUSDT"},
            ),
        ])

    def test_invalid_leverage_is_rejected_before_exchange_request(self):
        client = RecordingBinanceClient()

        with self.assertRaises(ValueError):
            client.change_leverage("BTCUSDT", 0)

        self.assertEqual(client.calls, [])

    def test_ticker_price_uses_public_futures_endpoint(self):
        client = RecordingBinanceClient()

        payload = client.ticker_price("btcusdt")

        self.assertEqual(payload["price"], "65000.10")
        self.assertEqual(client.calls, [
            (
                "GET",
                "/fapi/v1/ticker/price",
                {"symbol": "BTCUSDT"},
            ),
        ])


if __name__ == "__main__":
    unittest.main()
