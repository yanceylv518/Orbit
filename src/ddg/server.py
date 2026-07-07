from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from http.cookies import SimpleCookie
from urllib.parse import urlparse

from ddg.app_state import AppState


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
REPORTS = ROOT / "reports"


class DdgHandler(BaseHTTPRequestHandler):
    app: AppState

    def log_message(self, format: str, *args):  # noqa: A002
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            user = self.current_user()
            self.send_json(self.app.snapshot(user) if user else self.app.public_snapshot())
            return
        if parsed.path.startswith("/reports/"):
            self.serve_report(parsed.path)
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/login":
            payload = self.read_json()
            result = self.app.authenticate(str(payload.get("login", "")), str(payload.get("password", "")))
            if not result.get("ok"):
                self.send_json({"ok": False, "error": result.get("error", "登录失败。")}, status=401)
                return
            token = result.pop("session_token")
            cookie_name = self.cookie_name()
            self.send_json(
                {
                    "ok": True,
                    "user": result["user"],
                },
                headers={
                    "Set-Cookie": f"{cookie_name}={token}; Path=/; HttpOnly; SameSite=Strict",
                },
            )
            return
        if parsed.path == "/api/logout":
            self.app.logout(self.session_token())
            self.send_json(
                {"ok": True},
                headers={"Set-Cookie": f"{self.cookie_name()}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"},
            )
            return

        user = self.current_user()
        if not user:
            self.send_json({"ok": False, "error": "请先登录。"}, status=401)
            return

        if parsed.path == "/api/tick":
            if not self.is_admin(user):
                self.send_json(self.forbidden(), status=403)
                return
            self.app.tick_once()
            self.send_json(self.app.snapshot(user))
            return
        if parsed.path == "/api/reset":
            if not self.is_admin(user):
                self.send_json(self.forbidden(), status=403)
                return
            self.app.reset()
            self.send_json(self.app.snapshot(user))
            return
        if parsed.path == "/api/toggle":
            payload = self.read_json()
            running = bool(payload.get("running", False))
            if not self.is_admin(user):
                self.send_json(self.forbidden(), status=403)
                return
            self.app.set_running(running, actor=user["id"])
            self.send_json(self.app.snapshot(user))
            return
        if parsed.path == "/api/config/events":
            payload = self.read_json()
            event_config = payload.get("event_config", {})
            if not self.is_admin(user):
                self.send_json(self.forbidden(), status=403)
                return
            self.app.update_event_config(event_config, actor=user["id"])
            self.send_json(self.app.snapshot(user))
            return
        if parsed.path == "/api/users/upsert":
            if not self.is_admin(user):
                self.send_json(self.forbidden(), status=403)
                return
            result = self.app.upsert_business_user(self.read_json(), actor=user["id"])
            if not result.get("ok"):
                self.send_json(result, status=400)
                return
            filtered = self.app.snapshot(user)
            filtered["user_update_result"] = result
            self.send_json(filtered)
            return
        if parsed.path == "/api/accounts/upsert":
            if not self.is_admin(user):
                self.send_json(self.forbidden(), status=403)
                return
            result = self.app.upsert_exchange_account(self.read_json(), actor=user["id"])
            if not result.get("ok"):
                self.send_json(result, status=400)
                return
            filtered = self.app.snapshot(user)
            filtered["account_update_result"] = result
            self.send_json(filtered)
            return
        if parsed.path == "/api/report/daily":
            if not self.is_admin(user):
                self.send_json(self.forbidden(), status=403)
                return
            snapshot = self.app.generate_daily_report(actor=user["id"])
            filtered = self.app.snapshot(user)
            filtered["generated_report"] = snapshot.get("generated_report")
            self.send_json(filtered)
            return
        if parsed.path == "/api/binance/sync":
            payload = self.read_json()
            account_id = str(payload.get("account_id", ""))
            if not self.can_operate_account(user, account_id):
                self.send_json(
                    {"ok": False, "error": "Binance 同步只能由账户所属用户或管理员执行。"},
                    status=403,
                )
                return
            sync_result = self.app.sync_binance_account(account_id, actor=user["id"])
            filtered = self.app.snapshot(user)
            filtered["binance_sync_result"] = sync_result
            self.send_json(filtered)
            return
        if parsed.path == "/api/binance/credentials":
            payload = self.read_json()
            account_id = str(payload.get("account_id", ""))
            account = self.app.account_by_id(account_id)
            if not account or not self.can_access_account(user, account_id):
                self.send_json(
                    {"ok": False, "error": "API Key/Secret 只能由账户所属用户或管理员维护。"},
                    status=403,
                )
                return
            result = self.app.update_binance_credentials(
                account_id=account_id,
                actor=user["id"],
                api_key=str(payload.get("api_key", "")),
                api_secret=str(payload.get("api_secret", "")),
            )
            if not result.get("ok"):
                self.send_json(result, status=400)
                return
            filtered = self.app.snapshot(user)
            filtered["credential_update_result"] = result
            self.send_json(filtered)
            return
        if parsed.path == "/api/account-run-config":
            payload = self.read_json()
            account_id = str(payload.get("account_id", ""))
            if not self.can_access_account(user, account_id):
                self.send_json(self.forbidden(), status=403)
                return
            result = self.app.update_account_run_config(
                account_id=account_id,
                incoming=payload.get("run_config", {}),
                actor=user["id"],
            )
            if not result.get("ok"):
                self.send_json(result, status=400)
                return
            filtered = self.app.snapshot(user)
            filtered["account_run_config_result"] = result
            self.send_json(filtered)
            return
        if parsed.path == "/api/execution-plans/generate":
            payload = self.read_json()
            account_id = str(payload.get("account_id", "")).strip()
            if account_id:
                if not self.can_access_account(user, account_id):
                    self.send_json(self.forbidden(), status=403)
                    return
            elif not self.is_admin(user):
                self.send_json(self.forbidden(), status=403)
                return
            result = self.app.generate_execution_plans(account_id or None, actor=user["id"])
            if not result.get("ok"):
                self.send_json(result, status=400)
                return
            filtered = self.app.snapshot(user)
            filtered["execution_plan_result"] = result
            self.send_json(filtered)
            return
        if parsed.path == "/api/admin/emergency-stop":
            payload = self.read_json()
            if not self.is_admin(user):
                self.send_json(self.forbidden(), status=403)
                return
            reason = payload.get("reason")
            self.app.admin_emergency_stop(actor=user["id"], reason=reason)
            self.send_json(self.app.snapshot(user))
            return
        if parsed.path == "/api/admin/resume":
            payload = self.read_json()
            if not self.is_admin(user):
                self.send_json(self.forbidden(), status=403)
                return
            reason = payload.get("reason")
            self.app.admin_resume(actor=user["id"], reason=reason)
            self.send_json(self.app.snapshot(user))
            return
        self.send_error(404, "Not found")

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        data = self.rfile.read(length)
        return json.loads(data.decode("utf-8"))

    def send_json(self, payload: dict, status: int = 200, headers: dict[str, str] | None = None) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def cookie_name(self) -> str:
        return self.app.config.get("auth", {}).get("session_cookie_name", "ddg_session")

    def session_token(self) -> str | None:
        raw_cookie = self.headers.get("Cookie", "")
        if not raw_cookie:
            return None
        cookie = SimpleCookie()
        cookie.load(raw_cookie)
        item = cookie.get(self.cookie_name())
        return item.value if item else None

    def current_user(self) -> dict | None:
        return self.app.current_user(self.session_token())

    def is_admin(self, user: dict) -> bool:
        return user.get("role") in ("admin", "super_admin")

    def can_access_account(self, user: dict, account_id: str) -> bool:
        if self.is_admin(user):
            return True
        account = self.app.account_by_id(account_id)
        return bool(account and account.get("user_id") == user.get("id"))

    def can_operate_account(self, user: dict, account_id: str) -> bool:
        if self.is_admin(user):
            return True
        account = self.app.account_by_id(account_id)
        return bool(account and account.get("user_id") == user.get("id"))

    def forbidden(self) -> dict:
        return {"ok": False, "error": "当前用户没有权限执行此操作。"}

    def serve_static(self, request_path: str) -> None:
        path = "index.html" if request_path in ("", "/") else request_path.lstrip("/")
        target = (WEB / path).resolve()
        if not str(target).startswith(str(WEB.resolve())) or not target.exists() or not target.is_file():
            self.send_error(404, "Not found")
            return
        content = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        if target.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        if target.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def serve_report(self, request_path: str) -> None:
        rel = request_path.removeprefix("/reports/").lstrip("/")
        target = (REPORTS / rel).resolve()
        if not str(target).startswith(str(REPORTS.resolve())) or not target.exists() or not target.is_file():
            self.send_error(404, "Not found")
            return
        content = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix == ".md":
            content_type = "text/markdown; charset=utf-8"
        if target.suffix == ".svg":
            content_type = "image/svg+xml; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)


def run_server() -> None:
    app = AppState()
    app.start_background()
    host = app.config["runtime"].get("host", "127.0.0.1")
    port = int(app.config["runtime"].get("port", 8765))
    DdgHandler.app = app
    server = ThreadingHTTPServer((host, port), DdgHandler)
    print(f"Dynamic Dual Grid V1 running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()
