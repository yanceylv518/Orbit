import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
import sys

import httpx


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.api.app import create_api
from orbit.bootstrap import create_app_state
from orbit.config import load_config


ROOT = Path(__file__).resolve().parents[2]


class ApiTests(unittest.IsolatedAsyncioTestCase):
    def make_api(self, *, login_required=True):
        tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(tmp.name)
        config = load_config(str(ROOT / "config" / "config.sample.json"))
        config["runtime"]["mock_data_enabled"] = False
        config["auth"]["login_required"] = login_required
        config["storage"] = {
            "driver": "json",
            "json_path": str(tmp_path / "runtime_state.json"),
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        state = create_app_state(str(config_path))
        return tmp, create_api(state)

    async def test_anonymous_state_keeps_public_contract(self):
        tmp, api = self.make_api()
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=api),
                base_url="http://testserver",
            ) as client:
                response = await client.get("/api/state")
            payload = response.json()

            self.assertEqual(response.status_code, 200)
            self.assertFalse(payload["auth"]["authenticated"])
            self.assertNotIn("users", payload)
            self.assertEqual(response.headers["cache-control"], "no-store")
        finally:
            tmp.cleanup()

    async def test_protected_route_uses_existing_error_contract(self):
        tmp, api = self.make_api()
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=api),
                base_url="http://testserver",
            ) as client:
                response = await client.post("/api/tick")

            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json(), {"ok": False, "error": "请先登录。"})
        finally:
            tmp.cleanup()

    async def test_login_sets_session_cookie_and_returns_authenticated_state(self):
        tmp, api = self.make_api()
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=api),
                base_url="http://testserver",
            ) as client:
                login = await client.post(
                    "/api/login",
                    json={"login": "admin_001", "password": "admin123456"},
                )
                state = await client.get("/api/state")

                self.assertEqual(login.status_code, 200)
                self.assertIn("orbit_session", client.cookies)
                self.assertTrue(state.json()["auth"]["authenticated"])
                self.assertEqual(state.json()["auth"]["current_user"]["id"], "admin_001")
        finally:
            tmp.cleanup()

    async def test_no_login_mode_uses_default_admin_for_control_route(self):
        tmp, api = self.make_api(login_required=False)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=api),
                base_url="http://testserver",
            ) as client:
                response = await client.post("/api/toggle", json={"running": False})

            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["auth"]["authenticated"])
            self.assertEqual(response.json()["auth"]["current_user"]["id"], "admin_001")
        finally:
            tmp.cleanup()

    async def test_admin_can_resume_stopped_symbol_through_api(self):
        tmp, api = self.make_api()
        try:
            app = api.state.orbit
            account_id = "binance_dry_run_001"
            symbol = "BTCUSDT"
            state = app.engine.initialize_symbol(symbol, Decimal("60000"), Decimal("100"))
            state.update({
                "account_id": account_id,
                "exchange_account_id": account_id,
                "state": "STOPPED",
                "long_qty": "0",
                "short_qty": "0",
                "realized_pnl": "-20",
                "last_price": "60000",
                "stopped_at": "2026-07-13T10:00:00+00:00",
            })
            app.engine.mark_to_market(state, Decimal("60000"))
            app.symbol_state_repository.replace_all({f"{account_id}::{symbol}": state})

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=api),
                base_url="http://testserver",
            ) as client:
                await client.post(
                    "/api/login",
                    json={"login": "admin_001", "password": "admin123456"},
                )
                response = await client.post(
                    "/api/admin/stopped-symbols/resume",
                    json={
                        "account_id": account_id,
                        "symbol": symbol,
                        "reason": "已复核账户权益与持仓。",
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["recovered_symbol"]["state"], "BALANCED")
            self.assertEqual(response.json()["stopped_symbols"], [])
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
