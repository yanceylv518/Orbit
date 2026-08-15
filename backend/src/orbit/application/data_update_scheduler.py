from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Callable


class DataUpdateScheduler:
    """UTC 01:00 daily coordinator; task execution remains delegated to the existing workflow."""

    def __init__(self, start_job: Callable[[], Any], messages: Any, *, max_attempts: int = 3, state_path: Path | None = None):
        self.start_job = start_job
        self.messages = messages
        self.max_attempts = max_attempts
        self.state_path = state_path
        self.state = {"last_success_at": None, "last_attempt_day": None, "attempts": 0, "consecutive_failed_days": 0, "next_retry_at": None}
        if state_path and state_path.exists():
            self.state.update(json.loads(state_path.read_text(encoding="utf-8")))

    def due(self, now: datetime) -> bool:
        now = now.astimezone(timezone.utc)
        retry = self.state["next_retry_at"]
        if retry and now >= datetime.fromisoformat(retry):
            return True
        return now.hour >= 1 and self.state["last_attempt_day"] != now.date().isoformat()

    def run_due(self, now: datetime) -> bool:
        if not self.due(now):
            return False
        now = now.astimezone(timezone.utc)
        day = now.date().isoformat()
        if self.state["last_attempt_day"] != day:
            self.state["last_attempt_day"], self.state["attempts"] = day, 0
        self.state["attempts"] += 1
        try:
            self.start_job()
        except Exception as exc:
            if self.state["attempts"] < self.max_attempts:
                self.state["next_retry_at"] = (now + timedelta(hours=1)).isoformat()
            else:
                self.state["next_retry_at"] = None
                self.state["consecutive_failed_days"] += 1
                self.messages.append(level="error" if self.state["consecutive_failed_days"] >= 2 else "important", kind="data", title="历史数据更新失败", summary="每日数据更新未完成", detail=str(exc), link="#data")
            self._persist()
            return False
        self.state.update(last_success_at=now.isoformat(), attempts=0, consecutive_failed_days=0, next_retry_at=None)
        self._persist()
        return True

    def _persist(self) -> None:
        if self.state_path:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
