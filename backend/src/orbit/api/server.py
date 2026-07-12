from __future__ import annotations

import uvicorn

from orbit.api.app import create_api
from orbit.bootstrap import create_app_state


def run_server() -> None:
    state = create_app_state()
    state.start_background()
    host = state.config["runtime"].get("host", "127.0.0.1")
    port = int(state.config["runtime"].get("port", 8765))
    uvicorn.run(create_api(state), host=host, port=port, log_level="info")
