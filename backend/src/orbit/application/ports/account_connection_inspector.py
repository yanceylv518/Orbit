from __future__ import annotations

from typing import Any, Protocol


class AccountConnectionInspector(Protocol):
    def inspect(self, account: dict[str, Any]) -> dict[str, Any]:
        ...
