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
        config["runtime"]["research"] = {
            "calibration_dir": str(tmp_path / "calibration"),
            "registry_path": str(tmp_path / "research" / "registry.jsonl"),
            "run_ledger_path": str(tmp_path / "research" / "runs.jsonl"),
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

    async def test_admin_can_read_research_catalog_candidates_and_results(self):
        tmp, api = self.make_api(login_required=False)
        try:
            calibration_dir = api.state.orbit.research_catalog.calibration_dir
            calibration_dir.mkdir(parents=True)
            (calibration_dir / "BTCUSDT_4h_ohlc.json").write_text(
                json.dumps([{"open_time": 1000, "close": "10"}]),
                encoding="utf-8",
            )
            (calibration_dir / "g2_result.json").write_text(
                json.dumps({"protocol": "G2", "verdict": "NO_GO"}),
                encoding="utf-8",
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=api),
                base_url="http://testserver",
            ) as client:
                datasets = await client.get("/api/research/datasets")
                candidates = await client.get("/api/research/candidates")
                candidate = await client.get("/api/research/candidates/g2")
                result = await client.get("/api/research/results/g2_result")
                missing = await client.get("/api/research/results/missing")

            self.assertEqual(datasets.status_code, 200)
            self.assertEqual(datasets.json()["count"], 1)
            self.assertEqual(candidates.status_code, 200)
            self.assertEqual(candidates.json()["count"], 4)
            self.assertEqual(candidate.json()["id"], "G2")
            self.assertEqual(result.json()["verdict"], "NO_GO")
            self.assertEqual(missing.status_code, 404)
        finally:
            tmp.cleanup()

    async def test_admin_can_freeze_and_run_cached_research_candidate(self):
        tmp, api = self.make_api(login_required=False)
        try:
            calibration_dir = api.state.orbit.research_catalog.calibration_dir
            calibration_dir.mkdir(parents=True)
            (calibration_dir / "BTCUSDT_1h_ohlc.json").write_text(
                json.dumps([[1000, 10], [2000, 11]]),
                encoding="utf-8",
            )

            class Evaluator:
                def evaluate(self, candidate, datasets, run_id):
                    return {"reports": [{"market": "BTCUSDT", "expected_value_pct": -0.1}]}

                def fetch_dataset(self, request, run_id):
                    return f"{request['symbol']}_{run_id}_{request['kind']}"

            workflow = api.state.orbit.research_workflow
            workflow.evaluator = Evaluator()
            workflow._submitter = lambda callback: callback()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=api),
                base_url="http://testserver",
            ) as client:
                templates = await client.get("/api/research/templates")
                created = await client.post("/api/research/candidates", json={
                    "id": "M0-API",
                    "name": "API candidate",
                    "protocol": "M0",
                    "dataset_ids": ["BTCUSDT_1h_ohlc"],
                })
                duplicate = await client.post("/api/research/candidates", json={
                    "id": "M0-API",
                    "name": "Replacement",
                    "protocol": "M0",
                    "dataset_ids": ["BTCUSDT_1h_ohlc"],
                })
                run = await client.post("/api/research/runs", json={"candidate_id": "M0-API"})
                fetch = await client.post("/api/research/datasets/fetch", json={
                    "symbol": "ETHUSDT",
                    "kind": "funding",
                    "days": 90,
                })
                runs = await client.get("/api/research/runs")
                result = await client.get(f"/api/research/results/{run.json()['result_id']}")

            self.assertEqual(templates.status_code, 200)
            self.assertEqual(templates.json()["count"], 4)
            self.assertEqual(created.status_code, 201)
            self.assertEqual(created.json()["status"], "frozen")
            self.assertEqual(duplicate.status_code, 409)
            self.assertEqual(run.status_code, 202)
            self.assertEqual(run.json()["status"], "succeeded")
            self.assertEqual(run.json()["verdict"], "FAIL")
            self.assertEqual(fetch.status_code, 202)
            self.assertEqual(fetch.json()["status"], "succeeded")
            self.assertEqual(runs.json()["count"], 2)
            self.assertEqual(result.status_code, 200)
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
