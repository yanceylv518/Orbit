from __future__ import annotations

from copy import deepcopy
from typing import Any


class InMemoryAccountSnapshotRepository:
    def __init__(self, snapshots: dict[str, dict[str, Any]]):
        self.snapshots = snapshots

    def all(self) -> dict[str, dict[str, Any]]:
        return self.snapshots

    def get(self, account_id: str) -> dict[str, Any] | None:
        return self.snapshots.get(account_id)

    def save(self, account_id: str, snapshot: dict[str, Any]) -> None:
        self.snapshots[account_id] = snapshot

    def delete(self, account_id: str) -> None:
        self.snapshots.pop(account_id, None)

    def clear(self) -> None:
        self.snapshots.clear()

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return deepcopy(self.snapshots)

    def restore(self, snapshots: dict[str, dict[str, Any]]) -> None:
        self.snapshots.clear()
        self.snapshots.update(deepcopy(snapshots))
