from __future__ import annotations

from typing import Any, Protocol


class ExchangeSnapshotFetcher(Protocol):
    def sync_account(
        self,
        account: dict[str, Any],
        strategy: dict[str, Any],
        *,
        mock_data_enabled: bool = False,
    ) -> dict[str, Any]:
        ...
