from __future__ import annotations

import json
import unittest
from urllib.error import URLError

from orbit.infrastructure.notifications.pushover import PushoverDeliveryError, PushoverNotifier


class FakeVault:
    def __init__(self):
        self.resolved = []

    def resolve(self, reference):
        self.resolved.append(reference)
        return {
            "env:ORBIT_PUSHOVER_API_TOKEN": "super-secret-token",
            "env:ORBIT_PUSHOVER_USER_KEY": "super-secret-user",
        }.get(reference)


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps({"status": 1, "request": "safe-request-id"}).encode("utf-8")


class Sig1PushoverTests(unittest.TestCase):
    def test_credentials_are_resolved_only_for_delivery_and_not_returned(self):
        vault = FakeVault()
        captured = {}

        def opener(request, timeout):
            captured["body"] = request.data.decode("utf-8")
            return FakeResponse()

        notifier = PushoverNotifier(
            vault,
            api_token_reference="env:ORBIT_PUSHOVER_API_TOKEN",
            user_key_reference="env:ORBIT_PUSHOVER_USER_KEY",
            opener=opener,
        )
        result = notifier.send({"title": "Orbit", "message": "signal"})
        self.assertEqual(len(vault.resolved), 2)
        self.assertIn("super-secret-token", captured["body"])
        self.assertNotIn("super-secret-token", str(result))
        self.assertNotIn("super-secret-user", str(result))

    def test_network_error_is_sanitized(self):
        def opener(request, timeout):
            raise URLError("super-secret-token")

        notifier = PushoverNotifier(
            FakeVault(),
            api_token_reference="env:ORBIT_PUSHOVER_API_TOKEN",
            user_key_reference="env:ORBIT_PUSHOVER_USER_KEY",
            opener=opener,
        )
        with self.assertRaises(PushoverDeliveryError) as raised:
            notifier.send({"title": "Orbit", "message": "signal"})
        self.assertNotIn("super-secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
