from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Any


PBKDF2_ITERATIONS = 260_000


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    )
    return salt, base64.b64encode(digest).decode("ascii")


def verify_password(password: str, salt: str | None, password_hash: str | None) -> bool:
    if not salt or not password_hash:
        return False
    _, candidate = hash_password(password, salt)
    return hmac.compare_digest(candidate, password_hash)


def api_key_fingerprint(api_key: str | None) -> str | None:
    if not api_key:
        return None
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


def sanitize_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "name": user.get("name", user["id"]),
        "email": user.get("email"),
        "role": user.get("role", "user"),
        "status": user.get("status", "active"),
    }
