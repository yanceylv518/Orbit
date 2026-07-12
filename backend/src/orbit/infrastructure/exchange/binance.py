from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from orbit.application.ports.credential_vault import CredentialVault


FAPI_BASE_URL = "https://fapi.binance.com"
FAPI_TESTNET_BASE_URL = "https://demo-fapi.binance.com"


class BinanceError(RuntimeError):
    pass


class BinanceConfigError(BinanceError):
    pass


def dec(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


@dataclass
class BinanceCredentials:
    api_key: str
    api_secret: str
    api_key_fingerprint: str


class BinanceFuturesClient:
    def __init__(
        self,
        api_key: str | None,
        api_secret: str | None,
        *,
        testnet: bool = True,
        recv_window: int = 5000,
        timeout: float = 8,
    ):
        if not api_key or not api_secret:
            raise BinanceConfigError("Binance API key/secret environment variables are missing.")
        api_key_fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
        self.credentials = BinanceCredentials(api_key, api_secret, api_key_fingerprint)
        self.base_url = FAPI_TESTNET_BASE_URL if testnet else FAPI_BASE_URL
        self.recv_window = recv_window
        self.timeout = timeout

    @classmethod
    def from_account(cls, account: dict[str, Any], vault: CredentialVault) -> "BinanceFuturesClient":
        return cls(
            vault.resolve(account.get("api_key_ref")),
            vault.resolve(account.get("secret_ref")),
            testnet=bool(account.get("testnet", True)),
        )

    def account_information(self) -> dict[str, Any]:
        return self.signed_request("GET", "/fapi/v3/account")

    def position_risk(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params = {"symbol": symbol} if symbol else {}
        payload = self.signed_request("GET", "/fapi/v3/positionRisk", params)
        if not isinstance(payload, list):
            raise BinanceError("Unexpected positionRisk response.")
        return payload

    def position_mode(self) -> dict[str, Any]:
        return self.signed_request("GET", "/fapi/v1/positionSide/dual")

    def exchange_info(self, symbol: str | None = None) -> dict[str, Any]:
        params = {"symbol": symbol} if symbol else {}
        return self.public_request("GET", "/fapi/v1/exchangeInfo", params)

    def test_order(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.signed_request("POST", "/fapi/v1/order/test", params)

    def place_order(self, params: dict[str, Any]) -> dict[str, Any]:
        """真实下单。调用方必须已通过 OrderExecutionService 的全部闸门。"""
        return self.signed_request("POST", "/fapi/v1/order", params)

    def signed_request(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        params.setdefault("recvWindow", self.recv_window)
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(params)
        signature = hmac.new(
            self.credentials.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        body = f"{query}&signature={signature}".encode("utf-8")
        headers = {
            "X-MBX-APIKEY": self.credentials.api_key,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if method.upper() == "GET":
            return self.request(method, f"{path}?{body.decode('utf-8')}", headers=headers)
        return self.request(method, path, body=body, headers=headers)

    def public_request(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        query = urlencode({k: v for k, v in (params or {}).items() if v is not None})
        suffix = f"?{query}" if query else ""
        return self.request(method, f"{path}{suffix}")

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers or {},
            method=method.upper(),
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise BinanceError(f"Binance HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise BinanceError(f"Binance network error: {exc.reason}") from exc


def normalize_account_snapshot(account: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    assets = payload.get("assets", [])
    return {
        "account_id": account["id"],
        "exchange": account.get("exchange", "binance"),
        "testnet": bool(account.get("testnet", True)),
        "dry_run": bool(account.get("dry_run", True)),
        "total_wallet_balance": float(dec(payload.get("totalWalletBalance"))),
        "total_margin_balance": float(dec(payload.get("totalMarginBalance"))),
        "available_balance": float(dec(payload.get("availableBalance"))),
        "total_unrealized_profit": float(dec(payload.get("totalUnrealizedProfit"))),
        "total_initial_margin": float(dec(payload.get("totalInitialMargin"))),
        "assets": [
            {
                "asset": item.get("asset"),
                "wallet_balance": float(dec(item.get("walletBalance"))),
                "margin_balance": float(dec(item.get("marginBalance"))),
                "available_balance": float(dec(item.get("availableBalance"))),
                "unrealized_profit": float(dec(item.get("unrealizedProfit"))),
            }
            for item in assets
            if dec(item.get("walletBalance")) != 0 or dec(item.get("marginBalance")) != 0
        ],
        "synced_at": int(time.time() * 1000),
    }


def normalize_positions(positions: list[dict[str, Any]], symbols: list[str] | None = None) -> list[dict[str, Any]]:
    symbol_set = set(symbols or [])
    result = []
    for item in positions:
        symbol = item.get("symbol")
        qty = dec(item.get("positionAmt"))
        notional = dec(item.get("notional"))
        if symbol_set and symbol not in symbol_set:
            continue
        if qty == 0 and notional == 0:
            continue
        result.append({
            "symbol": symbol,
            "position_side": item.get("positionSide"),
            "position_amt": float(qty),
            "entry_price": float(dec(item.get("entryPrice"))),
            "break_even_price": float(dec(item.get("breakEvenPrice"))),
            "mark_price": float(dec(item.get("markPrice"))),
            "unrealized_profit": float(dec(item.get("unRealizedProfit"))),
            "liquidation_price": float(dec(item.get("liquidationPrice"))),
            "notional": float(notional),
            "margin_asset": item.get("marginAsset"),
            "initial_margin": float(dec(item.get("initialMargin"))),
            "maint_margin": float(dec(item.get("maintMargin"))),
            "adl": item.get("adl"),
            "update_time": item.get("updateTime"),
        })
    return result
