from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from orbit.application.ports.credential_vault import CredentialVault


PUSHOVER_URL = "https://api.pushover.net/1/messages.json"


class PushoverDeliveryError(RuntimeError):
    pass


class PushoverNotifier:
    def __init__(
        self,
        vault: CredentialVault,
        *,
        api_token_reference: str,
        user_key_reference: str,
        endpoint: str = PUSHOVER_URL,
        timeout: float = 8,
        opener=urlopen,
    ):
        self.vault = vault
        self.api_token_reference = api_token_reference
        self.user_key_reference = user_key_reference
        self.endpoint = endpoint
        self.timeout = timeout
        self.opener = opener

    def send(self, notification: dict[str, str]) -> dict[str, Any]:
        token = self.vault.resolve(self.api_token_reference)
        user = self.vault.resolve(self.user_key_reference)
        if not token or not user:
            raise PushoverDeliveryError("Pushover credentials are unavailable in the credential vault")
        payload = urlencode(
            {key: value for key, value in {
                "token": token,
                "user": user,
                "title": str(notification["title"]),
                "message": str(notification["message"]),
                "url": notification.get("url"),
                "url_title": notification.get("url_title"),
                "priority": notification.get("priority"),
            }.items() if value is not None}
        ).encode("utf-8")
        request = Request(
            self.endpoint,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                status = int(getattr(response, "status", 200))
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise PushoverDeliveryError(f"Pushover HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise PushoverDeliveryError("Pushover network delivery failed") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PushoverDeliveryError("Pushover returned an invalid response") from exc
        if status >= 300 or int(body.get("status", 0)) != 1:
            raise PushoverDeliveryError(f"Pushover rejected the notification with HTTP {status}")
        return {"provider": "PUSHOVER", "status": "DELIVERED", "request_id": body.get("request")}
