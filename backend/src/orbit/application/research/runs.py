from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from threading import Lock, RLock, Thread
import time
from typing import Any, Callable
from uuid import uuid4

from orbit.application.research.protocols import build_candidate, protocol_templates
from orbit.application.research.candidates import canonical_json
from orbit.application.r0_shortline_screen import validate_training_report, verify_frozen_context
from orbit.infrastructure.persistence.dataset_job_lock import DatasetJobLock


FETCH_INTERVALS = {"1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"}
ACTIVE_RUN_STATUSES = {"queued", "running", "cancelling"}


class ResearchRunCancelled(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return False
        try:
            exit_code = ctypes.c_ulong()
            readable = ctypes.windll.kernel32.GetExitCodeProcess(
                process, ctypes.byref(exit_code)
            )
            return bool(readable) and exit_code.value == 259
        finally:
            ctypes.windll.kernel32.CloseHandle(process)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


class CachedToolEvaluator:
    """Runs only allow-listed research tools against catalogued cache files."""

    def __init__(
        self,
        project_root: Path,
        calibration_dir: Path,
        *,
        shortline_enabled: bool = True,
        shortline_min_free_gb: float = 15.0,
        shortline_verify_sample_symbols: int = 3,
        disk_usage: Callable[[Path], Any] = shutil.disk_usage,
    ):
        self.project_root = project_root
        self.calibration_dir = calibration_dir
        self.tools_dir = project_root / "backend" / "tools"
        self.shortline_root = calibration_dir / "shortline-data-v1"
        self.research_dir = project_root / "var" / "research"
        self.r0_spec = project_root / "config" / "research" / "r0_shortline_screen.v2.json"
        self.shortline_enabled = shortline_enabled
        self.shortline_min_free_bytes = int(shortline_min_free_gb * 1024 ** 3)
        self.shortline_verify_sample_symbols = shortline_verify_sample_symbols
        self._disk_usage = disk_usage
        self._process_lock = RLock()
        self._active_process: subprocess.Popen[str] | None = None
        self._active_run_id: str | None = None
        self._dataset_lock: DatasetJobLock | None = None
        self._cancelled_runs: set[str] = set()

    def r0_status(self) -> dict[str, Any]:
        context = verify_frozen_context(self.r0_spec, self.shortline_root)
        training_path, training = self._latest_valid_training(context)
        external_training = self._active_external_training() if training is None else None
        marker = self.research_dir / "r0_lockbox_opened.json"
        lockbox_paths = sorted(self.research_dir.glob("r0_lockbox*v2*.json"))
        lockbox_report = self._read_json(lockbox_paths[-1]) if lockbox_paths else None
        return {
            "protocol": context["contract"]["protocol"],
            "contract_sha256": context["contract_sha256"],
            "dataset_fingerprint": context["manifest"]["dataset_fingerprint"],
            "training_report_path": str(training_path) if training_path else None,
            "training_report": training,
            "training_complete": training is not None,
            "training_passed": bool(training and training.get("lockbox_authorized_families")),
            "training_active": external_training is not None,
            "external_training": external_training,
            "lockbox_opened": marker.exists(),
            "lockbox_report": lockbox_report,
            "lockbox_confirmation_phrase": "打开一次性锁箱",
        }

    def reserve_r0(self, run_id: str) -> dict[str, Any]:
        context = verify_frozen_context(self.r0_spec, self.shortline_root)
        if self._active_external_training() is not None:
            raise RuntimeError("R-0 training is already running outside the page")
        with self._process_lock:
            if self._dataset_lock is not None or self._active_process is not None:
                raise RuntimeError("another data or research task is already active")
            lock = DatasetJobLock(self.shortline_root, owner="orbit-ui-r0", run_id=run_id)
            holder = lock.acquire()
            self._dataset_lock = lock
            self._active_run_id = run_id
        return {
            "contract_sha256": context["contract_sha256"],
            "dataset_fingerprint": context["manifest"]["dataset_fingerprint"],
            "lock_holder": {key: holder.get(key) for key in ("owner", "run_id", "pid", "started_at")},
        }

    def run_r0(
        self,
        phase: str,
        run_id: str,
        on_progress: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        normalized = phase.lower()
        if normalized not in {"training", "lockbox"}:
            raise ValueError("unsupported R-0 phase")
        with self._process_lock:
            if self._dataset_lock is None or self._active_run_id != run_id:
                raise RuntimeError("R-0 task does not hold the dataset lock")
            token = self._dataset_lock.token
        self.research_dir.mkdir(parents=True, exist_ok=True)
        progress_path = self.research_dir / f"r0_ui_{run_id}_progress.json"
        checkpoint_dir = self.research_dir / "r0-ui-checkpoints" / normalized
        output = self.research_dir / f"r0_{normalized}_ui_v2.json"
        command = [
            sys.executable,
            str(self.tools_dir / "screen_r0_shortline.py"),
            "--root", str(self.shortline_root),
            "--spec", str(self.r0_spec),
            "--lock-owner-token", token,
            "train" if normalized == "training" else "lockbox",
        ]
        if normalized == "training":
            command.extend(["--out", str(output)])
        else:
            context = verify_frozen_context(self.r0_spec, self.shortline_root)
            training_path, training = self._latest_valid_training(context)
            if not training_path or not training or not training.get("lockbox_authorized_families"):
                raise RuntimeError("training did not authorize opening the lockbox")
            command.extend([
                "--training-report", str(training_path),
                "--out", str(output),
                "--confirm-open-lockbox",
            ])
        command.extend(["--progress-state", str(progress_path), "--checkpoint-dir", str(checkpoint_dir)])
        try:
            self._run_r0_process(command, run_id, progress_path, on_progress)
            report = self._read_json(output)
            if not report:
                raise RuntimeError("R-0 task completed without a report")
            return {
                "report_path": str(output),
                "research_verdict": report.get("verdict"),
            }
        finally:
            with self._process_lock:
                self._cancelled_runs.discard(run_id)
                self._active_process = None
                self._active_run_id = None
                if self._dataset_lock is not None:
                    self._dataset_lock.release()
                    self._dataset_lock = None

    def cancel_r0(self, run_id: str) -> None:
        with self._process_lock:
            self._cancelled_runs.add(run_id)
            if self._active_run_id == run_id and self._active_process is not None:
                self._active_process.terminate()

    def _run_r0_process(
        self,
        command: list[str],
        run_id: str,
        progress_path: Path,
        on_progress: Callable[[dict[str, Any]], None],
    ) -> None:
        with self._process_lock:
            process = subprocess.Popen(
                command, cwd=self.project_root, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
            )
            self._active_process = process
        last_progress = ""
        while process.poll() is None:
            with self._process_lock:
                cancelled = run_id in self._cancelled_runs
            if cancelled:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise ResearchRunCancelled("R-0 training was cancelled; checkpoints were retained")
            try:
                raw = progress_path.read_text(encoding="utf-8")
                if raw != last_progress:
                    on_progress(json.loads(raw))
                    last_progress = raw
            except (OSError, json.JSONDecodeError):
                pass
            time.sleep(0.75)
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            raise RuntimeError((stderr or stdout or "R-0 task failed").strip()[-2000:])
        try:
            on_progress(json.loads(progress_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass

    def _latest_valid_training(self, context: dict[str, Any]):
        for path in reversed(sorted(self.research_dir.glob("r0_training*v2*.json"))):
            payload = self._read_json(path)
            if not payload:
                continue
            try:
                validate_training_report(context, payload)
            except RuntimeError:
                continue
            return path, payload
        return None, None

    def _active_external_training(self) -> dict[str, Any] | None:
        marker = self._read_json(self.research_dir / "r0_external_training.json")
        if not marker:
            return None
        try:
            pid = int(marker.get("worker_pid") or marker.get("pid") or 0)
        except (TypeError, ValueError):
            return None
        if pid <= 0:
            return None
        if not process_alive(pid):
            return None
        return {
            "pid": pid,
            "started_at": marker.get("started_at"),
            "source": "cli",
            "progress_available": False,
        }

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def reserve_shortline_dataset(self, run_id: str) -> dict[str, Any]:
        if not self.shortline_enabled:
            raise RuntimeError("DATA-1R page tasks are disabled by runtime configuration")
        self.shortline_root.mkdir(parents=True, exist_ok=True)
        usage = self._disk_usage(self.shortline_root)
        if int(usage.free) < self.shortline_min_free_bytes:
            required_gb = self.shortline_min_free_bytes / 1024 ** 3
            free_gb = int(usage.free) / 1024 ** 3
            raise RuntimeError(
                f"DATA-1R requires at least {required_gb:.1f} GB free; only {free_gb:.1f} GB available"
            )
        with self._process_lock:
            if self._dataset_lock is not None:
                raise RuntimeError("another DATA-1R task is already reserved")
            lock = DatasetJobLock(self.shortline_root, owner="orbit-ui", run_id=run_id)
            holder = lock.acquire()
            self._dataset_lock = lock
            self._active_run_id = run_id
        return {
            "lock_holder": {
                key: holder.get(key) for key in ("owner", "run_id", "pid", "started_at")
            },
            "disk_free_bytes_at_start": int(usage.free),
            "disk_required_bytes": self.shortline_min_free_bytes,
        }

    def evaluate(self, candidate: dict[str, Any], datasets: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
        temp_dir = self.calibration_dir / ".research_tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_output = temp_dir / f"{run_id}.json"
        if temp_output.exists():
            raise RuntimeError("research temporary output already exists")
        command = self._command(candidate, datasets, temp_output)
        try:
            completed = subprocess.run(
                command,
                cwd=self.project_root,
                capture_output=True,
                check=False,
                text=True,
                timeout=60 * 30,
            )
            if completed.returncode != 0:
                message = (completed.stderr or completed.stdout or "research tool failed").strip()
                raise RuntimeError(message[-2000:])
            report = json.loads(temp_output.read_text(encoding="utf-8"))
            if not isinstance(report, dict):
                raise RuntimeError("research tool did not produce a JSON object")
            return report
        finally:
            temp_output.unlink(missing_ok=True)

    def fetch_dataset(self, request: dict[str, Any], run_id: str) -> str:
        temp_dir = self.calibration_dir / ".research_tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_output = temp_dir / f"{run_id}.json"
        symbol = request["symbol"]
        if request["kind"] == "funding":
            dataset_id = f"{symbol}_{run_id}_funding"
            command = [
                sys.executable,
                str(self.tools_dir / "fetch_funding.py"),
                "--symbol", symbol,
                "--days", str(request["days"]),
                "--out", str(temp_output),
            ]
        else:
            interval = request["interval"]
            dataset_id = f"{symbol}_{interval}_{run_id}_ohlc"
            command = [
                sys.executable,
                str(self.tools_dir / "fetch_klines.py"),
                "--symbol", symbol,
                "--interval", interval,
                "--days", str(request["days"]),
                "--ohlc",
                "--out", str(temp_output),
            ]
        try:
            completed = subprocess.run(
                command,
                cwd=self.project_root,
                capture_output=True,
                check=False,
                text=True,
                timeout=60 * 30,
            )
            if completed.returncode != 0:
                message = (completed.stderr or completed.stdout or "dataset fetch failed").strip()
                raise RuntimeError(message[-2000:])
            payload = json.loads(temp_output.read_text(encoding="utf-8"))
            if not isinstance(payload, list) or not payload:
                raise RuntimeError("dataset fetch returned no rows")
            final_path = self.calibration_dir / f"{dataset_id}.json"
            with final_path.open("xb") as target:
                target.write(temp_output.read_bytes())
            return dataset_id
        finally:
            temp_output.unlink(missing_ok=True)

    def build_shortline_dataset(
        self,
        request: dict[str, Any],
        run_id: str,
        on_progress: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        workers = int(request["workers"])
        tool = str(self.tools_dir / "shortline_dataset.py")
        with self._process_lock:
            if self._dataset_lock is None or self._active_run_id != run_id:
                raise RuntimeError("DATA-1R task does not hold the dataset lock")
            lock_token = self._dataset_lock.token
        base = [
            sys.executable, tool, "--root", str(self.shortline_root),
            "--lock-owner-token", lock_token,
        ]
        phases = (
            ("index", [*base, "index"], 2, 15),
            (
                "download",
                [
                    *base, "sync", "--confirm-full-download",
                    "--workers", str(workers),
                ],
                15,
                75,
            ),
            ("build", [*base, "build"], 75, 92),
            (
                "verify",
                [
                    *base, "verify-batch", "--sample-symbols",
                    str(self.shortline_verify_sample_symbols),
                ],
                92,
                99,
            ),
        )
        try:
            for phase, command, start_progress, end_progress in phases:
                self._run_shortline_phase(
                    command,
                    run_id=run_id,
                    phase=phase,
                    start_progress=start_progress,
                    end_progress=end_progress,
                    on_progress=on_progress,
                )
            manifest_path = self.shortline_root / "manifest.json"
            quality_path = self.shortline_root / "quality_report.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            if manifest.get("dataset_state") != "COMPLETE":
                raise RuntimeError("full shortline build did not produce a COMPLETE dataset")
            return {
                "dataset_id": self.shortline_root.name,
                "dataset_state": manifest["dataset_state"],
                "dataset_fingerprint": manifest["dataset_fingerprint"],
                "quality_report_sha256": manifest["quality_report_sha256"],
                "contract_count": quality.get("contract_count"),
                "partition_count": quality.get("partition_count"),
            }
        finally:
            with self._process_lock:
                self._cancelled_runs.discard(run_id)
                if self._active_run_id == run_id:
                    self._active_process = None
                    self._active_run_id = None
                if self._dataset_lock is not None:
                    self._dataset_lock.release()
                    self._dataset_lock = None

    def cancel_shortline_dataset(self, run_id: str) -> None:
        with self._process_lock:
            self._cancelled_runs.add(run_id)
            if self._active_run_id == run_id and self._active_process is not None:
                self._active_process.terminate()
            elif self._active_run_id == run_id and self._dataset_lock is not None:
                self._dataset_lock.release()
                self._dataset_lock = None
                self._active_run_id = None

    def _run_shortline_phase(
        self,
        command: list[str],
        *,
        run_id: str,
        phase: str,
        start_progress: int,
        end_progress: int,
        on_progress: Callable[[dict[str, Any]], None],
    ) -> None:
        with self._process_lock:
            if run_id in self._cancelled_runs:
                raise ResearchRunCancelled("dataset task was cancelled")
            if self._active_process is not None:
                raise RuntimeError("another DATA-1R process is already active")
            process = subprocess.Popen(
                command,
                cwd=self.project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self._active_process = process
            self._active_run_id = run_id
        last_snapshot: tuple[Any, ...] | None = None
        try:
            while process.poll() is None:
                with self._process_lock:
                    cancelled = run_id in self._cancelled_runs
                if cancelled:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    raise ResearchRunCancelled("dataset task was cancelled")
                detail = self._shortline_phase_detail(phase)
                fraction = float(detail.pop("fraction", 0.0))
                progress = start_progress + int((end_progress - start_progress) * fraction)
                snapshot = (
                    progress,
                    detail.get("completed_items"),
                    detail.get("total_items"),
                    detail.get("current_item"),
                )
                if snapshot != last_snapshot:
                    on_progress({"phase": phase, "progress": progress, **detail})
                    last_snapshot = snapshot
                time.sleep(0.75)
            stdout, stderr = process.communicate()
            with self._process_lock:
                if run_id in self._cancelled_runs:
                    raise ResearchRunCancelled("dataset task was cancelled")
            if process.returncode != 0:
                message = (stderr or stdout or f"DATA-1R {phase} failed").strip()
                raise RuntimeError(message[-2000:])
            on_progress({
                "phase": phase,
                "progress": end_progress,
                "message": self._phase_completed_message(phase),
            })
        finally:
            with self._process_lock:
                if self._active_process is process:
                    self._active_process = None
                    self._active_run_id = None

    def _shortline_phase_detail(self, phase: str) -> dict[str, Any]:
        filename = {
            "index": "archive_index_state.json",
            "download": "sync_state.json",
            "build": "build_state.json",
            "verify": "verification_state.json",
        }[phase]
        path = self.shortline_root / "metadata" / filename
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"fraction": 0.0, "message": self._phase_running_message(phase)}
        if phase == "index":
            completed = len(state.get("completed_symbols") or [])
            total = int(state.get("total_symbols") or 0)
            current = state.get("current_symbol")
        elif phase == "download":
            completed = int(state.get("completed_count") or 0)
            total = int(state.get("selected_files") or 0)
            recent = state.get("recent_files") or []
            current = recent[-1] if recent else None
        elif phase == "build":
            completed = int(state.get("completed_symbols") or 0)
            total = int(state.get("total_symbols") or 0)
            current = state.get("current_symbol")
        else:
            completed = int(state.get("completed_samples") or 0)
            total = int(state.get("total_samples") or 0)
            current = state.get("current_item")
        return {
            "fraction": completed / total if total else 0.0,
            "completed_items": completed,
            "total_items": total,
            "current_item": current,
            "completed_bytes": int(state.get("completed_bytes") or 0),
            "total_bytes": int(state.get("total_bytes") or 0),
            "error_count": int(state.get("error_count") or 0),
            "recent_logs": list(state.get("recent_logs") or [])[-5:],
            "message": self._phase_running_message(phase),
        }

    @staticmethod
    def _phase_running_message(phase: str) -> str:
        return {
            "index": "正在枚举历史合约与月份",
            "download": "正在校验并下载15分钟K线与资金费率",
            "build": "正在构建1小时、4小时和质量报告",
            "verify": "正在与 Binance 原生1小时、4小时归档抽样核对",
        }[phase]

    @staticmethod
    def _phase_completed_message(phase: str) -> str:
        return {
            "index": "全市场历史索引完成",
            "download": "原始数据下载完成",
            "build": "派生数据与质量报告完成",
            "verify": "原生聚合抽样核对完成",
        }[phase]

    def _command(
        self,
        candidate: dict[str, Any],
        datasets: list[dict[str, Any]],
        output: Path,
    ) -> list[str]:
        protocol = candidate["protocol"]
        parameters = candidate["parameters"]
        costs = candidate["costs"]
        thresholds = candidate["thresholds"]
        paths = {item["id"]: self.calibration_dir / f"{item['id']}.json" for item in datasets}
        if protocol == "M0":
            command = [sys.executable, str(self.tools_dir / "analyze_reversion_horizon.py")]
            for item in datasets:
                command.extend(["--dataset", f"{self._dataset_name(item)},{paths[item['id']]}"])
            for horizon in parameters["holding_ticks"]:
                command.extend(["--horizon", str(horizon)])
            command.extend([
                "--a-pct", str(parameters["a_pct"]),
                "--theta-pct", str(parameters["theta_pct"]),
                "--cost-pct", str(costs["roundtrip_pct"]),
            ])
        elif protocol == "F1":
            command = [sys.executable, str(self.tools_dir / "screen_funding_carry.py")]
            for item in datasets:
                command.extend(["--dataset", f"{self._dataset_name(item)},{paths[item['id']]}"])
            command.extend([
                "--entry-exit-cost-pct", str(costs["entry_exit_pct"]),
                "--rebalance-cost-pct-per-day", str(costs["rebalance_pct_per_day"]),
            ])
        elif protocol in {"G1", "G2"}:
            script = "screen_extreme_funding.py" if protocol == "G1" else "screen_funding_relative_strength.py"
            command = [sys.executable, str(self.tools_dir / script)]
            for market, pair in self._paired_datasets(datasets).items():
                command.extend([
                    "--dataset",
                    f"{market},{paths[pair['funding']['id']]},{paths[pair['candles']['id']]}",
                ])
            command.extend(["--cost-pct", str(costs["roundtrip_pct"])])
            if protocol == "G1":
                command.extend(["--required-markets", str(thresholds["required_markets"])])
            else:
                command.extend(["--min-market-appearances", str(thresholds["min_market_appearances"])])
        else:
            raise ValueError("unsupported research protocol")
        return [*command, "--json-output", str(output)]

    @staticmethod
    def _dataset_name(item: dict[str, Any]) -> str:
        return ":".join(part for part in (item.get("market"), item.get("interval")) if part) or item["id"]

    @staticmethod
    def _paired_datasets(datasets: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
        pairs: dict[str, dict[str, dict[str, Any]]] = {}
        for item in datasets:
            kind = "funding" if item["kind"] == "funding" else "candles"
            pairs.setdefault(str(item["market"]), {})[kind] = item
        return dict(sorted(pairs.items()))


class ResearchWorkflowService:
    def __init__(
        self,
        catalog: Any,
        run_ledger: Any,
        evaluator: Any,
        submitter: Callable[[Callable[[], None]], None] | None = None,
    ):
        self.catalog = catalog
        self.run_ledger = run_ledger
        self.evaluator = evaluator
        self._submitter = submitter or self._submit_daemon
        self._lock = Lock()
        self._recover_interrupted_runs()

    def templates(self) -> list[dict[str, Any]]:
        return protocol_templates()

    def create_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        dataset_ids = payload.get("dataset_ids")
        if not isinstance(dataset_ids, list) or not all(isinstance(item, str) for item in dataset_ids):
            raise ValueError("dataset_ids must be a list of dataset ids")
        datasets = self.catalog.datasets_by_ids(dataset_ids)
        candidate = build_candidate(payload, datasets, now_iso())
        return self.catalog.registry.append(candidate)

    def create_run(self, candidate_id: str, open_lockbox: bool = False) -> dict[str, Any]:
        with self._lock:
            candidate = self.catalog.candidate(candidate_id)
            if not candidate:
                raise ValueError("research candidate not found")
            if candidate["status"] != "frozen":
                raise ValueError("only newly frozen candidates can be run from the UI")
            active = [item for item in self.run_ledger.runs() if item["status"] in ACTIVE_RUN_STATUSES]
            if active:
                raise RuntimeError("another research run is already active")
            previous = self.run_ledger.for_candidate(candidate["id"])
            if open_lockbox and any(item.get("lockbox_opened_at") for item in previous):
                raise RuntimeError("candidate lockbox has already been opened")
            run_id = f"run_{uuid4().hex[:16]}"
            created_at = now_iso()
            event = {
                "id": run_id,
                "candidate_id": candidate["id"],
                "candidate_hash": candidate["frozen_hash"],
                "protocol": candidate["protocol"],
                "status": "queued",
                "progress": 0,
                "created_at": created_at,
                "updated_at": created_at,
                "lockbox_opened_at": created_at if open_lockbox else None,
            }
            self.run_ledger.append(event)
            self._submitter(lambda: self._execute(run_id))
            return self.run_ledger.get(run_id) or event

    def create_dataset_fetch(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = self._validate_fetch(payload)
        with self._lock:
            active = [item for item in self.run_ledger.runs() if item["status"] in ACTIVE_RUN_STATUSES]
            if active:
                raise RuntimeError("another research run is already active")
            run_id = f"run_{uuid4().hex[:16]}"
            created_at = now_iso()
            event = {
                "id": run_id,
                "job_type": "dataset_fetch",
                "candidate_id": "DATASET",
                "candidate_hash": hashlib.sha256(canonical_json(request)).hexdigest(),
                "protocol": "FETCH_FUNDING" if request["kind"] == "funding" else "FETCH_KLINES",
                "request": request,
                "status": "queued",
                "progress": 0,
                "created_at": created_at,
                "updated_at": created_at,
                "lockbox_opened_at": None,
            }
            self.run_ledger.append(event)
            self._submitter(lambda: self._execute(run_id))
            return self.run_ledger.get(run_id) or event

    def create_shortline_dataset_build(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirm_full_download") is not True:
            raise ValueError("full DATA-1R download requires explicit confirmation")
        try:
            workers = int(payload.get("workers", 4))
        except (TypeError, ValueError) as exc:
            raise ValueError("download workers must be an integer") from exc
        if not 1 <= workers <= 8:
            raise ValueError("download workers must be between 1 and 8")
        request = {"confirm_full_download": True, "workers": workers}
        with self._lock:
            active = [item for item in self.run_ledger.runs() if item["status"] in ACTIVE_RUN_STATUSES]
            if active:
                raise RuntimeError("another research run is already active")
            run_id = f"run_{uuid4().hex[:16]}"
            reservation = self.evaluator.reserve_shortline_dataset(run_id)
            created_at = now_iso()
            event = {
                "id": run_id,
                "job_type": "shortline_dataset",
                "candidate_id": "DATASET",
                "candidate_hash": hashlib.sha256(canonical_json(request)).hexdigest(),
                "protocol": "DATA1R_FULL",
                "request": request,
                "status": "queued",
                "phase": "queued",
                "progress": 0,
                "created_at": created_at,
                "updated_at": created_at,
                "lockbox_opened_at": None,
                **reservation,
            }
            try:
                self.run_ledger.append(event)
                self._submitter(lambda: self._execute(run_id))
            except Exception:
                self.evaluator.cancel_shortline_dataset(run_id)
                raise
            return self.run_ledger.get(run_id) or event

    def r0_status(self) -> dict[str, Any]:
        status = self.evaluator.r0_status()
        runs = [item for item in self.run_ledger.runs() if item.get("job_type") in {"r0_training", "r0_lockbox"}]
        return {**status, "runs": runs, "latest_run": runs[0] if runs else None}

    def create_r0_run(self, phase: str, confirmation: str = "") -> dict[str, Any]:
        normalized = str(phase).strip().lower()
        if normalized not in {"training", "lockbox"}:
            raise ValueError("R-0 phase must be training or lockbox")
        with self._lock:
            active = [item for item in self.run_ledger.runs() if item["status"] in ACTIVE_RUN_STATUSES]
            if active:
                raise RuntimeError("another research run is already active")
            status = self.evaluator.r0_status()
            if normalized == "training" and status.get("training_active"):
                raise RuntimeError("R-0 training is already running outside the page")
            if normalized == "training" and status["training_complete"]:
                raise RuntimeError("R-0 training report already exists")
            if normalized == "lockbox":
                if confirmation != status["lockbox_confirmation_phrase"]:
                    raise ValueError("lockbox confirmation phrase does not match")
                if not status["training_passed"]:
                    raise RuntimeError("training did not authorize opening the lockbox")
                if status["lockbox_opened"]:
                    raise RuntimeError("R-0 lockbox has already been opened")
            run_id = f"run_{uuid4().hex[:16]}"
            reservation = self.evaluator.reserve_r0(run_id)
            created_at = now_iso()
            event = {
                "id": run_id,
                "job_type": f"r0_{normalized}",
                "candidate_id": "R0-V2",
                "candidate_hash": reservation["contract_sha256"],
                "protocol": "ORBIT_R0_SHORTLINE_SCREEN_V2",
                "status": "queued",
                "phase": "queued",
                "progress": 0,
                "created_at": created_at,
                "updated_at": created_at,
                "lockbox_opened_at": created_at if normalized == "lockbox" else None,
                **reservation,
            }
            try:
                self.run_ledger.append(event)
                self._submitter(lambda: self._execute(run_id))
            except Exception:
                self.evaluator.cancel_r0(run_id)
                raise
            return self.run_ledger.get(run_id) or event

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            run = self.run_ledger.get(run_id)
            if not run:
                raise ValueError("research run not found")
            if run.get("job_type") not in {"shortline_dataset", "r0_training"}:
                raise ValueError("only data updates or R-0 training can be cancelled")
            if run["status"] not in ACTIVE_RUN_STATUSES:
                raise RuntimeError("DATA-1R download task is not active")
            if run.get("job_type") == "shortline_dataset":
                self.evaluator.cancel_shortline_dataset(run_id)
            else:
                self.evaluator.cancel_r0(run_id)
            cancelled_at = now_iso()
            self.run_ledger.append({
                **self._identity(run),
                "status": "cancelling",
                "message": "正在安全停止；已完成进度会保留，下次按原契约继续",
                "updated_at": cancelled_at,
            })
            return self.run_ledger.get(run_id) or run

    def runs(self) -> list[dict[str, Any]]:
        return self.run_ledger.runs()

    def run(self, run_id: str) -> dict[str, Any] | None:
        return self.run_ledger.get(run_id)

    def _execute(self, run_id: str) -> None:
        run = self.run_ledger.get(run_id)
        if not run:
            return
        started_at = now_iso()
        self.run_ledger.append({
            **self._identity(run),
            "status": "running",
            "progress": 1 if run.get("job_type") == "shortline_dataset" else 10,
            **({"phase": "starting", "message": "正在启动 DATA-1R 数据任务"}
               if run.get("job_type") == "shortline_dataset" else {}),
            "started_at": started_at,
            "updated_at": started_at,
        })
        try:
            if run.get("job_type") == "dataset_fetch":
                dataset_id = self.evaluator.fetch_dataset(run["request"], run_id)
                completed_at = now_iso()
                self.run_ledger.append({
                    **self._identity(run),
                    "status": "succeeded",
                    "progress": 100,
                    "dataset_id": dataset_id,
                    "completed_at": completed_at,
                    "updated_at": completed_at,
                })
                return
            if run.get("job_type") == "shortline_dataset":
                result = self.evaluator.build_shortline_dataset(
                    run["request"],
                    run_id,
                    lambda detail: self._record_progress(run, detail),
                )
                completed_at = now_iso()
                self.run_ledger.append({
                    **self._identity(run),
                    **result,
                    "status": "succeeded",
                    "phase": "complete",
                    "progress": 100,
                    "message": "DATA-1R 全市场研究数据集已完成",
                    "completed_at": completed_at,
                    "updated_at": completed_at,
                })
                return
            if run.get("job_type") in {"r0_training", "r0_lockbox"}:
                phase = "training" if run["job_type"] == "r0_training" else "lockbox"
                result = self.evaluator.run_r0(
                    phase, run_id, lambda detail: self._record_progress(run, detail),
                )
                completed_at = now_iso()
                self.run_ledger.append({
                    **self._identity(run),
                    **result,
                    "status": "succeeded",
                    "phase": "complete",
                    "progress": 100,
                    "message": "R-0 训练完成" if phase == "training" else "R-0 锁箱评估完成",
                    "completed_at": completed_at,
                    "updated_at": completed_at,
                })
                return
            candidate = self.catalog.candidate(run["candidate_id"])
            if not candidate or candidate["frozen_hash"] != run["candidate_hash"]:
                raise RuntimeError("frozen candidate fingerprint no longer matches")
            dataset_ids = candidate["matrix"]["dataset_ids"]
            datasets = self.catalog.datasets_by_ids(dataset_ids)
            expected_hashes = candidate["matrix"]["dataset_sha256"]
            if any(item["sha256"] != expected_hashes.get(item["id"]) for item in datasets):
                raise RuntimeError("cached dataset fingerprint changed after candidate freeze")
            report = self.evaluator.evaluate(candidate, datasets, run_id)
            verdict = self._verdict(candidate, report)
            result_id = f"{candidate['id'].lower()}_{run_id}"
            result_path = self.catalog.calibration_dir / f"{result_id}.json"
            enriched = {
                **report,
                "protocol": report.get("protocol") or candidate["protocol"],
                "candidate_id": candidate["id"],
                "candidate_frozen_hash": candidate["frozen_hash"],
                "run_id": run_id,
                "generated_at": now_iso(),
                "verdict": verdict,
            }
            result_path.parent.mkdir(parents=True, exist_ok=True)
            with result_path.open("x", encoding="utf-8", newline="\n") as target:
                json.dump(enriched, target, ensure_ascii=False, indent=2)
                target.write("\n")
            completed_at = now_iso()
            self.run_ledger.append({
                **self._identity(run),
                "status": "succeeded",
                "progress": 100,
                "result_id": result_id,
                "verdict": verdict,
                "completed_at": completed_at,
                "updated_at": completed_at,
            })
        except ResearchRunCancelled as exc:
            cancelled_at = now_iso()
            self.run_ledger.append({
                **self._identity(run),
                "status": "cancelled",
                "message": str(exc),
                "completed_at": cancelled_at,
                "updated_at": cancelled_at,
            })
        except Exception as exc:
            failed_at = now_iso()
            self.run_ledger.append({
                **self._identity(run),
                "status": "failed",
                "progress": 100,
                "error": str(exc)[:2000],
                "completed_at": failed_at,
                "updated_at": failed_at,
            })

    def _recover_interrupted_runs(self) -> None:
        for run in self.run_ledger.runs():
            if run["status"] not in ACTIVE_RUN_STATUSES:
                continue
            recovered_at = now_iso()
            self.run_ledger.append({
                **self._identity(run),
                "status": "failed",
                "phase": "interrupted",
                "progress": int(run.get("progress") or 0),
                "resumable": run.get("job_type") in {"shortline_dataset", "r0_training"},
                "message": "服务重启中断了任务；已完成文件保留，可重新启动续校",
                "error": "research process restarted before the task completed",
                "completed_at": recovered_at,
                "updated_at": recovered_at,
            })

    def _record_progress(self, run: dict[str, Any], detail: dict[str, Any]) -> None:
        timestamp = now_iso()
        accumulated: dict[str, Any] = {}
        latest = detail.get("latest_parameter_report")
        if isinstance(latest, dict):
            current = self.run_ledger.get(run["id"]) or {}
            reports = list(current.get("parameter_reports_progress") or [])
            reports = [item for item in reports if item.get("parameter_id") != latest.get("parameter_id")]
            reports.append(latest)
            accumulated["parameter_reports_progress"] = reports
        self.run_ledger.append({
            **self._identity(run),
            "status": "running",
            "updated_at": timestamp,
            **accumulated,
            **detail,
        })

    @staticmethod
    def _validate_fetch(payload: dict[str, Any]) -> dict[str, Any]:
        symbol = str(payload.get("symbol", "")).strip().upper()
        kind = str(payload.get("kind", "")).strip().lower()
        interval = str(payload.get("interval", "")).strip().lower()
        try:
            days = int(payload.get("days", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError("fetch days must be an integer") from exc
        if not re.fullmatch(r"[A-Z0-9]{2,16}USDT", symbol):
            raise ValueError("symbol must be a USDT perpetual market")
        if kind not in {"ohlc", "funding"}:
            raise ValueError("dataset kind must be ohlc or funding")
        if kind == "ohlc" and interval not in FETCH_INTERVALS:
            raise ValueError("unsupported kline interval")
        if not 1 <= days <= 2000:
            raise ValueError("fetch days must be between 1 and 2000")
        return {"symbol": symbol, "kind": kind, "interval": interval if kind == "ohlc" else None, "days": days}

    @staticmethod
    def _identity(run: dict[str, Any]) -> dict[str, Any]:
        return {key: run[key] for key in ("id", "candidate_id", "candidate_hash", "protocol", "created_at")}

    @staticmethod
    def _verdict(candidate: dict[str, Any], report: dict[str, Any]) -> str:
        if candidate["protocol"] == "M0":
            positive = sum(float(item.get("expected_value_pct", 0)) > 0 for item in report.get("reports", []))
            passed = positive >= int(candidate["thresholds"]["required_positive_combinations"])
        else:
            passed = bool(report.get("stage_admitted"))
        return "PASS" if passed else "FAIL"

    @staticmethod
    def _submit_daemon(callback: Callable[[], None]) -> None:
        Thread(target=callback, daemon=True, name="orbit-research-run").start()
