from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from threading import Lock, Thread
from typing import Any, Callable
from uuid import uuid4

from orbit.application.research.protocols import build_candidate, protocol_templates
from orbit.application.research.candidates import canonical_json


FETCH_INTERVALS = {"1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CachedToolEvaluator:
    """Runs only allow-listed research tools against catalogued cache files."""

    def __init__(self, project_root: Path, calibration_dir: Path):
        self.project_root = project_root
        self.calibration_dir = calibration_dir
        self.tools_dir = project_root / "backend" / "tools"

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
            active = [item for item in self.run_ledger.runs() if item["status"] in {"queued", "running"}]
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
            active = [item for item in self.run_ledger.runs() if item["status"] in {"queued", "running"}]
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
            "progress": 10,
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
            if run["status"] not in {"queued", "running"}:
                continue
            recovered_at = now_iso()
            self.run_ledger.append({
                **self._identity(run),
                "status": "failed",
                "progress": 100,
                "error": "research process restarted before the task completed",
                "completed_at": recovered_at,
                "updated_at": recovered_at,
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
