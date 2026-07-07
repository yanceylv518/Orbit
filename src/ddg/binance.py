from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import base64
import ctypes
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


FAPI_BASE_URL = "https://fapi.binance.com"
FAPI_TESTNET_BASE_URL = "https://demo-fapi.binance.com"


class BinanceError(RuntimeError):
    pass


class BinanceConfigError(BinanceError):
    pass


class CredentialError(BinanceConfigError):
    pass


DPAPI_PREFIX = "dpapi:"
ENV_PREFIX = "env:"
DPAPI_ENTROPY = b"dynamic-dual-grid-v1-binance-credentials"


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_ulong),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _dpapi_protect(value: str) -> str:
    if not _is_windows():
        raise CredentialError("Local encrypted credential storage requires Windows DPAPI.")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    input_blob, input_buffer = _blob(value.encode("utf-8"))
    entropy_blob, entropy_buffer = _blob(DPAPI_ENTROPY)
    output_blob = _DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(output_blob),
    )
    _ = (input_buffer, entropy_buffer)
    if not ok:
        raise CredentialError("Failed to encrypt Binance credential with Windows DPAPI.")
    try:
        raw = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        return DPAPI_PREFIX + base64.b64encode(raw).decode("ascii")
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _dpapi_unprotect(ref: str) -> str:
    if not _is_windows():
        raise CredentialError("Local encrypted credential storage requires Windows DPAPI.")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    raw = base64.b64decode(ref.removeprefix(DPAPI_PREFIX).encode("ascii"))
    input_blob, input_buffer = _blob(raw)
    entropy_blob, entropy_buffer = _blob(DPAPI_ENTROPY)
    output_blob = _DataBlob()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(output_blob),
    )
    _ = (input_buffer, entropy_buffer)
    if not ok:
        raise CredentialError("Failed to decrypt Binance credential with Windows DPAPI.")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData).decode("utf-8")
    finally:
        kernel32.LocalFree(output_blob.pbData)


def protect_credential(value: str) -> str:
    return _dpapi_protect(value)


def env_value(ref: str | None) -> str | None:
    if not ref:
        return None
    if ref.startswith(DPAPI_PREFIX):
        return _dpapi_unprotect(ref)
    name = ref.removeprefix(ENV_PREFIX)
    return os.environ.get(name)


def env_name(ref: str | None) -> str | None:
    if not ref:
        return None
    if ref.startswith(DPAPI_PREFIX):
        return "account_credential"
    return ref.removeprefix(ENV_PREFIX)


def fingerprint(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


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
        self.credentials = BinanceCredentials(api_key, api_secret, fingerprint(api_key) or "")
        self.base_url = FAPI_TESTNET_BASE_URL if testnet else FAPI_BASE_URL
        self.recv_window = recv_window
        self.timeout = timeout

    @classmethod
    def from_account(cls, account: dict[str, Any]) -> "BinanceFuturesClient":
        return cls(
            env_value(account.get("api_key_ref")),
            env_value(account.get("secret_ref")),
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


def account_can_connect(account: dict[str, Any]) -> dict[str, Any]:
    error = None
    try:
        key = env_value(account.get("api_key_ref"))
        secret = env_value(account.get("secret_ref"))
    except CredentialError as exc:
        key = None
        secret = None
        error = str(exc)
    return {
        "api_key_env": env_name(account.get("api_key_ref")),
        "secret_env": env_name(account.get("secret_ref")),
        "api_key_present": bool(key),
        "secret_present": bool(secret),
        "api_key_fingerprint": fingerprint(key),
        "credential_error": error,
    }


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
