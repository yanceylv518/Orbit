from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping, Sequence

from orbit.domain.calibration.trend_basket import trend_performance_summary, trend_tb3_admission
from orbit.domain.strategy.trend_basket_runner import (
    FrozenTrendBasketRunner,
    TB4_SPEC,
    tb4_spec_fingerprint,
)


class TrendForwardService:
    MIN_FORWARD_DAYS = 365

    def __init__(self, ledger: Any):
        self.ledger = ledger
        self.runner = FrozenTrendBasketRunner()
        self._manifest = self.ledger.manifest()
        if self._manifest:
            self._restore()

    def initialize(
        self,
        *,
        start_time_ms: int,
        warmup_closes: Sequence[Mapping[str, Any]],
        input_fingerprints: Mapping[str, str],
        code_commit: str,
        protocol_sha256: str,
    ) -> dict[str, Any]:
        if self._manifest:
            raise RuntimeError("TB4 forward is already initialized")
        if set(input_fingerprints) != set(TB4_SPEC.symbols):
            raise ValueError("TB4 input fingerprints must cover the frozen 12-market universe")
        required = TB4_SPEC.warmup_ticks + 1
        if len(warmup_closes) < required:
            raise ValueError(f"TB4 warmup requires at least {required} synchronized closes")
        selected = list(warmup_closes[-required:])
        expected_start = int(selected[-1]["close_time_ms"]) + TB4_SPEC.interval_ms
        if int(start_time_ms) != expected_start:
            raise ValueError("TB4 start must be the first 4h close after the frozen warmup")

        candidate = FrozenTrendBasketRunner()
        for item in selected:
            candidate.on_close(
                int(item["close_time_ms"]),
                item["closes"],
                item.get("funding_rates") or {},
                record_return=False,
                allow_signal=True,
            )
        if candidate.pending is None:
            raise RuntimeError("TB4 warmup did not produce the first frozen signal")

        created_at = datetime.now(timezone.utc).isoformat()
        manifest_payload = {
            "protocol": "TB4_FORWARD_V1",
            "created_at": created_at,
            "start_time_ms": int(start_time_ms),
            "minimum_forward_days": self.MIN_FORWARD_DAYS,
            "spec_sha256": tb4_spec_fingerprint(),
            "protocol_sha256": str(protocol_sha256),
            "code_commit": str(code_commit),
            "input_fingerprints": dict(sorted(input_fingerprints.items())),
            "warmup_first_close_time_ms": int(selected[0]["close_time_ms"]),
            "warmup_last_close_time_ms": int(selected[-1]["close_time_ms"]),
            "warmup_close_count": len(selected),
        }
        self.runner = FrozenTrendBasketRunner()
        payloads = []
        for item in selected:
            result = self.runner.on_close(
                int(item["close_time_ms"]),
                item["closes"],
                item.get("funding_rates") or {},
                record_return=False,
                allow_signal=True,
            )
            payloads.append(self._close_payload(item, False, result, self.runner))
        manifest = self.ledger.initialize(manifest_payload, payloads)
        self._manifest = manifest
        return self.snapshot()

    def ingest_close(
        self,
        close_time_ms: int,
        closes: Mapping[str, float],
        funding_rates: Mapping[str, float],
    ) -> dict[str, Any]:
        if not self._manifest:
            raise RuntimeError("TB4 forward has not been initialized")
        if self.runner.times and int(close_time_ms) <= self.runner.times[-1]:
            if int(close_time_ms) == self.runner.times[-1]:
                return {"duplicate": True, "snapshot": self.snapshot()}
            raise ValueError("TB4 forward cannot ingest an older close")
        if int(close_time_ms) < int(self._manifest["start_time_ms"]):
            raise ValueError("TB4 forward evidence cannot precede the registered start")
        result = self._append_close({
            "close_time_ms": int(close_time_ms),
            "closes": dict(closes),
            "funding_rates": dict(funding_rates),
        }, record_return=True)
        return {"duplicate": False, "result": result, "snapshot": self.snapshot()}

    def snapshot(self) -> dict[str, Any]:
        if not self._manifest:
            return {
                "protocol": "TB4_FORWARD_V1",
                "status": "NOT_STARTED",
                "verdict": None,
                "parameters_mutable": False,
                "live_trading": False,
            }
        scored_periods = len(self.runner.net_returns_pct)
        elapsed_days = (
            max(0, self.runner.times[-1] - int(self._manifest["start_time_ms"]))
            / 86_400_000
            if self.runner.times else 0.0
        )
        performance = self._performance() if scored_periods else None
        mature = elapsed_days >= self.MIN_FORWARD_DAYS
        verdict = None
        if mature and performance:
            verdict = "PASS" if trend_tb3_admission(performance)["admitted"] else "FAIL"
        return {
            "protocol": "TB4_FORWARD_V1",
            "status": "MATURE" if mature else "RUNNING",
            "verdict": verdict,
            "parameters_mutable": False,
            "live_trading": False,
            "start_time_ms": self._manifest["start_time_ms"],
            "minimum_forward_days": self.MIN_FORWARD_DAYS,
            "elapsed_days": elapsed_days,
            "progress_ratio": min(1.0, elapsed_days / self.MIN_FORWARD_DAYS),
            "scored_periods": scored_periods,
            "runner": self.runner.snapshot(),
            "performance": performance,
            "ledger": self.ledger.status(),
            "manifest_sha256": self._manifest["manifest_sha256"],
            "spec_sha256": self._manifest["spec_sha256"],
        }

    def _append_close(self, item: Mapping[str, Any], *, record_return: bool) -> dict[str, Any]:
        candidate = FrozenTrendBasketRunner.from_state(self.runner.export_state())
        result = candidate.on_close(
            int(item["close_time_ms"]),
            item["closes"],
            item.get("funding_rates") or {},
            record_return=record_return,
            allow_signal=True,
        )
        self.ledger.append(self._close_payload(item, record_return, result, candidate))
        self.runner = candidate
        return result

    def _close_payload(
        self,
        item: Mapping[str, Any],
        record_return: bool,
        result: Mapping[str, Any],
        runner: FrozenTrendBasketRunner,
    ) -> dict[str, Any]:
        return {
            "type": "close",
            "close_time_ms": int(item["close_time_ms"]),
            "closes": dict(item["closes"]),
            "funding_rates": dict(item.get("funding_rates") or {}),
            "record_return": record_return,
            "executed_rebalance": result["executed_rebalance"],
            "net_return_pct": result["net_return_pct"],
            "equity": runner.equity,
            "current_drawdown_pct": runner.current_drawdown_pct,
            "performance": (
                self._performance_for(runner)
                if record_return and runner.net_returns_pct else None
            ),
            "state_sha256": self._state_hash(runner),
        }

    def _restore(self) -> None:
        if self._manifest.get("spec_sha256") != tb4_spec_fingerprint():
            raise RuntimeError("TB4 manifest does not match the frozen runner specification")
        restored = FrozenTrendBasketRunner()
        for record in self.ledger.read_all():
            payload = record["payload"]
            if payload.get("type") != "close":
                raise RuntimeError("unsupported TB4 ledger event")
            result = restored.on_close(
                int(payload["close_time_ms"]),
                payload["closes"],
                payload.get("funding_rates") or {},
                record_return=bool(payload["record_return"]),
                allow_signal=True,
            )
            if result["executed_rebalance"] != payload.get("executed_rebalance"):
                raise RuntimeError("TB4 restored rebalance differs from the append-only ledger")
            if result["net_return_pct"] != payload.get("net_return_pct"):
                raise RuntimeError("TB4 restored return differs from the append-only ledger")
            if restored.equity != payload.get("equity"):
                raise RuntimeError("TB4 restored equity differs from the append-only ledger")
            if restored.current_drawdown_pct != payload.get("current_drawdown_pct"):
                raise RuntimeError("TB4 restored drawdown differs from the append-only ledger")
            expected_performance = (
                self._performance_for(restored)
                if payload["record_return"] and restored.net_returns_pct else None
            )
            if expected_performance != payload.get("performance"):
                raise RuntimeError("TB4 restored metrics differ from the append-only ledger")
            if self._state_hash(restored) != payload.get("state_sha256"):
                raise RuntimeError("TB4 restored state fingerprint mismatch")
        self.runner = restored

    def _performance(self) -> dict[str, Any]:
        return self._performance_for(self.runner)

    @staticmethod
    def _performance_for(runner: FrozenTrendBasketRunner) -> dict[str, Any]:
        periods_per_year = 365 * 86_400_000 / TB4_SPEC.interval_ms
        summary = trend_performance_summary(
            runner.net_returns_pct,
            periods_per_year=periods_per_year,
            fold_periods=round(periods_per_year),
            rolling_window_periods=round(periods_per_year),
            rolling_step_periods=6,
        )
        summary.pop("fold_returns_pct", None)
        summary.pop("rolling_returns_pct", None)
        return summary

    @staticmethod
    def _state_hash(runner: FrozenTrendBasketRunner) -> str:
        state = {
            "spec_sha256": tb4_spec_fingerprint(),
            "snapshot": runner.snapshot(),
            "net_return_count": len(runner.net_returns_pct),
            "last_net_return_pct": (
                runner.net_returns_pct[-1] if runner.net_returns_pct else None
            ),
            "last_rebalance": runner.rebalances[-1] if runner.rebalances else None,
            "peak": runner.peak,
        }
        encoded = json.dumps(
            state, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
