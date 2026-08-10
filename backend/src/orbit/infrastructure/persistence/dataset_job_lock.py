from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from orbit.infrastructure.persistence.atomic_file import replace_with_retry


class DatasetJobLockBusy(RuntimeError):
    def __init__(self, holder: dict[str, Any] | None = None):
        self.holder = holder or {}
        label = self.holder.get("owner") or "another process"
        started = self.holder.get("started_at") or "unknown time"
        super().__init__(f"DATA-1R is locked by {label} since {started}")


class DatasetJobLock:
    """Cross-process lock for one DATA-1R root, with auditable holder metadata."""

    def __init__(
        self,
        root: Path,
        *,
        owner: str,
        run_id: str | None = None,
        token: str | None = None,
    ):
        self.root = root.resolve()
        self.owner = owner
        self.run_id = run_id
        self.token = token or uuid4().hex
        self.path = self.root / "metadata" / "dataset_job.lock"
        self.metadata_path = self.root / "metadata" / "dataset_job_lock.json"
        self._handle: Any | None = None

    def acquire(self) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            _lock_handle(handle)
        except OSError as exc:
            handle.close()
            raise DatasetJobLockBusy(self.read_holder(self.root)) from exc
        existing = self.read_holder(self.root)
        active_pid = int((existing or {}).get("worker_pid") or (existing or {}).get("pid") or 0)
        if existing and existing.get("token") != self.token and _pid_alive(active_pid):
            _unlock_handle(handle)
            handle.close()
            raise DatasetJobLockBusy(existing)
        self._handle = handle
        metadata = {
            "owner": self.owner,
            "run_id": self.run_id,
            "pid": os.getpid(),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "token": self.token,
        }
        _write_json(self.metadata_path, metadata)
        return metadata

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            current = self.read_holder(self.root)
            if current and current.get("token") == self.token:
                self.metadata_path.unlink(missing_ok=True)
            _unlock_handle(self._handle)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> "DatasetJobLock":
        self.acquire()
        return self

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        self.release()

    @staticmethod
    def validate_token(root: Path, token: str) -> dict[str, Any]:
        holder = DatasetJobLock.read_holder(root)
        if not holder or holder.get("token") != token:
            raise DatasetJobLockBusy(holder)
        holder = {
            **holder,
            "worker_pid": os.getpid(),
            "worker_started_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_json(root.resolve() / "metadata" / "dataset_job_lock.json", holder)
        return holder

    @staticmethod
    def read_holder(root: Path) -> dict[str, Any] | None:
        path = root.resolve() / "metadata" / "dataset_job_lock.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None


def _lock_handle(handle: Any) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_handle(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    replace_with_retry(temporary, path)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False
