from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]


def load_config(path: str | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else ROOT / "config.local.json"
    if not config_path.exists():
        config_path = ROOT / "config" / "config.sample.json"
    with config_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def get_nested(source: dict[str, Any], path: str, default: Any = None) -> Any:
    node: Any = source
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node
