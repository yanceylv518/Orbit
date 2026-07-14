from __future__ import annotations

import base64
import ctypes
import hashlib
import os
import sys

from orbit.application.ports.credential_vault import CredentialVaultError


DPAPI_PREFIX = "dpapi:"
ENV_PREFIX = "env:"
DPAPI_ENTROPY = b"dynamic-dual-grid-v1-binance-credentials"


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_ulong),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


class LocalCredentialVault:
    def protect(self, value: str) -> str:
        if not sys.platform.startswith("win"):
            raise CredentialVaultError("Local encrypted credential storage requires Windows DPAPI.")
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        input_blob, input_buffer = self._blob(value.encode("utf-8"))
        entropy_blob, entropy_buffer = self._blob(DPAPI_ENTROPY)
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
            raise CredentialVaultError("Failed to encrypt credential with Windows DPAPI.")
        try:
            raw = ctypes.string_at(output_blob.pbData, output_blob.cbData)
            return DPAPI_PREFIX + base64.b64encode(raw).decode("ascii")
        finally:
            kernel32.LocalFree(output_blob.pbData)

    def resolve(self, reference: str | None) -> str | None:
        if not reference:
            return None
        if reference.startswith(DPAPI_PREFIX):
            return self._unprotect(reference)
        if reference.startswith("aesgcm:"):
            raise CredentialVaultError(
                "AES-GCM credential requires the aesgcm vault driver; update runtime.credentials.driver."
            )
        return os.environ.get(reference.removeprefix(ENV_PREFIX))

    def fingerprint(self, value: str | None) -> str | None:
        if not value:
            return None
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]

    def reference_name(self, reference: str | None) -> str | None:
        if not reference:
            return None
        if reference.startswith(DPAPI_PREFIX):
            return "account_credential"
        return reference.removeprefix(ENV_PREFIX)

    def _unprotect(self, reference: str) -> str:
        if not sys.platform.startswith("win"):
            raise CredentialVaultError("Local encrypted credential storage requires Windows DPAPI.")
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        raw = base64.b64decode(reference.removeprefix(DPAPI_PREFIX).encode("ascii"))
        input_blob, input_buffer = self._blob(raw)
        entropy_blob, entropy_buffer = self._blob(DPAPI_ENTROPY)
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
            raise CredentialVaultError("Failed to decrypt credential with Windows DPAPI.")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData).decode("utf-8")
        finally:
            kernel32.LocalFree(output_blob.pbData)

    def _blob(self, data: bytes) -> tuple[_DataBlob, ctypes.Array]:
        buffer = ctypes.create_string_buffer(data)
        return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer
