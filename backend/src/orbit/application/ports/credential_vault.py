from __future__ import annotations

from typing import Protocol


class CredentialVaultError(RuntimeError):
    pass


class CredentialVault(Protocol):
    def protect(self, value: str) -> str:
        ...

    def resolve(self, reference: str | None) -> str | None:
        ...

    def fingerprint(self, value: str | None) -> str | None:
        ...

    def reference_name(self, reference: str | None) -> str | None:
        ...
