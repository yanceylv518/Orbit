from __future__ import annotations

from typing import Any

from orbit.application.ports.account_connection_inspector import AccountConnectionInspector
from orbit.application.ports.credential_vault import CredentialVault
from orbit.domain.strategy.engine import now_iso
from orbit.infrastructure.exchange.binance import (
    BinanceConfigError,
    BinanceError,
    BinanceFuturesClient,
    normalize_account_snapshot,
    normalize_positions,
)


class BinanceSnapshotFetcher:
    def __init__(self, vault: CredentialVault, connection_inspector: AccountConnectionInspector):
        self.vault = vault
        self.connection_inspector = connection_inspector

    def sync_account(
        self,
        account: dict[str, Any],
        strategy: dict[str, Any],
        *,
        mock_data_enabled: bool = False,
    ) -> dict[str, Any]:
        account_id = account["id"]
        connection = self.connection_inspector.inspect(account)
        snapshot: dict[str, Any] = {
            "ok": False,
            "account_id": account_id,
            "account_label": account.get("account_label", account_id),
            "testnet": bool(account.get("testnet", True)),
            "dry_run": bool(account.get("dry_run", True)),
            "api_key_present": connection["api_key_present"],
            "secret_present": connection["secret_present"],
            "api_key_fingerprint": connection["api_key_fingerprint"] or account.get("api_key_fingerprint"),
            "synced_at": now_iso(),
        }

        if not connection["api_key_present"] or not connection["secret_present"]:
            snapshot["status"] = "missing_credentials"
            snapshot["error"] = "缺少 Binance API Key 或 Secret。请在账户页配置。"
            return snapshot

        try:
            client = BinanceFuturesClient.from_account(account, self.vault)
            account_payload = client.account_information()
            positions_payload = client.position_risk()
            position_mode = client.position_mode()
            snapshot.update(normalize_account_snapshot(account, account_payload))
            snapshot["synced_at"] = now_iso()
            snapshot["ok"] = True
            snapshot["status"] = "synced"
            snapshot["position_mode"] = {
                "dual_side_position": bool(position_mode.get("dualSidePosition")),
                "hedge_mode_required": bool(
                    account.get("hedge_mode_required", account.get("hedge_mode_enabled", False))
                ),
            }
            snapshot["position_mode"]["hedge_mode_ok"] = (
                not snapshot["position_mode"]["hedge_mode_required"]
                or snapshot["position_mode"]["dual_side_position"]
            )
            symbols = strategy.get("symbols", []) if mock_data_enabled else None
            snapshot["positions"] = normalize_positions(positions_payload, symbols)
        except (BinanceConfigError, BinanceError) as exc:
            snapshot["status"] = "error"
            snapshot["error"] = str(exc)

        return snapshot
