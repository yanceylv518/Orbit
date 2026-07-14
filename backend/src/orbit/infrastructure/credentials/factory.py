from __future__ import annotations

import os
import sys
from typing import Any, Mapping

from orbit.application.ports.credential_vault import CredentialVault, CredentialVaultError
from orbit.infrastructure.credentials.aesgcm_vault import AesGcmCredentialVault
from orbit.infrastructure.credentials.local_vault import LocalCredentialVault


def create_credential_vault(
    config: dict[str, Any],
    *,
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> CredentialVault:
    settings = config.get("runtime", {}).get("credentials", {})
    driver = str(settings.get("driver", "auto")).strip().lower()
    current_platform = platform or sys.platform
    if driver == "auto":
        driver = "dpapi" if current_platform.startswith("win") else "aesgcm"
    if driver == "dpapi":
        if not current_platform.startswith("win"):
            raise CredentialVaultError("The DPAPI credential vault is available on Windows only.")
        return LocalCredentialVault()
    if driver == "aesgcm":
        return AesGcmCredentialVault(
            master_key_env=str(settings.get("master_key_env", "ORBIT_CREDENTIAL_MASTER_KEY")),
            environ=environ if environ is not None else os.environ,
        )
    raise CredentialVaultError(f"Unsupported credential vault driver: {driver}")
