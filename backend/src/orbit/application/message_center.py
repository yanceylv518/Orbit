from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any, Callable
from uuid import uuid4


class MessageCenter:
    """Append-only in-app messages with a separate append-only read ledger."""

    LEVELS = {"error", "important", "info"}
    TYPES = {"system", "signal", "data", "execution", "risk", "configuration"}

    def __init__(self, directory: Path, notifier: Any | None = None, push_important: bool = False):
        self.directory = directory
        self.messages_path = directory / "messages.jsonl"
        self.reads_path = directory / "message_reads.jsonl"
        self.notifier = notifier
        self.push_important = push_important
        self._lock = RLock()

    def append(self, *, level: str, kind: str, title: str, summary: str,
               detail: str = "", link: str = "", source_id: str = "",
               occurred_at: str | None = None) -> dict[str, Any]:
        if level not in self.LEVELS or kind not in self.TYPES:
            raise ValueError("invalid message level or type")
        row = {
            "id": uuid4().hex,
            "level": level,
            "kind": kind,
            "title": str(title),
            "summary": str(summary),
            "detail": str(detail or summary),
            "link": str(link),
            "source_id": str(source_id),
            "occurred_at": occurred_at or datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._write(self.messages_path, row)
        should_push = level == "error" or (level == "important" and self.push_important)
        if should_push and self.notifier is not None:
            try:
                self.notifier.send({"title": row["title"], "message": row["detail"], "priority": 1 if level == "error" else 0})
                row["pushed"] = True
            except Exception as exc:
                row["pushed"] = False
                row["push_error"] = str(exc)
        return row

    def list(self, *, kind: str = "", level: str = "", limit: int = 100) -> dict[str, Any]:
        rows = list(reversed(self._read(self.messages_path)))
        reads = {row["message_id"] for row in self._read(self.reads_path) if row.get("action") == "read"}
        if kind:
            rows = [row for row in rows if row.get("kind") == kind]
        if level:
            rows = [row for row in rows if row.get("level") == level]
        items = [{**row, "read": row["id"] in reads} for row in rows[:limit]]
        all_rows = self._read(self.messages_path)
        return {"items": items, "unread_count": sum(row["id"] not in reads for row in all_rows)}

    def mark_read(self, message_id: str) -> None:
        if not any(row.get("id") == message_id for row in self._read(self.messages_path)):
            raise KeyError(message_id)
        self._write(self.reads_path, {"message_id": message_id, "action": "read", "at": datetime.now(timezone.utc).isoformat()})

    def mark_all_read(self) -> None:
        read = {row.get("message_id") for row in self._read(self.reads_path)}
        for row in self._read(self.messages_path):
            if row["id"] not in read:
                self._write(self.reads_path, {"message_id": row["id"], "action": "read", "at": datetime.now(timezone.utc).isoformat()})

    @staticmethod
    def _read(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _write(self, path: Path, row: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

