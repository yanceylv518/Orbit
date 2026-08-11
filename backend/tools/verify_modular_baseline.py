"""Verify the MODULAR-1 TB4 zero-change baseline without writing runtime state."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND / "src"))

from orbit.application.strategy_catalog import TB4_DEFINITION  # noqa: E402
from orbit.domain.strategy.trend_basket_runner import tb4_spec_fingerprint  # noqa: E402
from orbit.infrastructure.persistence.trend_forward_ledger import TrendForwardLedger  # noqa: E402


DEFAULT_BASELINE = ROOT / "config" / "architecture" / "modular1_runtime_baseline.v1.json"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_baseline(
    baseline_path: Path = DEFAULT_BASELINE,
    *,
    runtime_dir: Path | None = None,
    require_runtime: bool = False,
) -> dict[str, Any]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if baseline.get("protocol") != "ORBIT_MODULAR1_RUNTIME_BASELINE_V1":
        raise RuntimeError("invalid MODULAR-1 baseline protocol")

    failures: list[str] = []
    tb4 = baseline["tb4"]
    actual_spec = tb4_spec_fingerprint()
    actual_definition = TB4_DEFINITION.definition_hash
    if actual_spec != tb4["spec_sha256"]:
        failures.append(f"TB4 spec changed: {actual_spec}")
    if actual_definition != tb4["definition_hash"]:
        failures.append(f"TB4 definition changed: {actual_definition}")

    verified_files: dict[str, str] = {}
    for relative, expected in baseline["protected_files"].items():
        path = ROOT / relative
        if not path.is_file():
            failures.append(f"protected file missing: {relative}")
            continue
        actual = file_sha256(path)
        verified_files[relative] = actual
        if actual != expected:
            failures.append(f"protected file changed: {relative} ({actual})")

    runtime_path = runtime_dir or ROOT / tb4["paper_data_dir"]
    ledger = TrendForwardLedger(runtime_path)
    runtime: dict[str, Any] = {
        "path": str(runtime_path),
        "present": ledger.manifest_path.is_file(),
    }
    if ledger.manifest_path.is_file():
        manifest = ledger.manifest()
        status = ledger.status()
        runtime.update({
            "manifest_sha256": manifest["manifest_sha256"],
            "spec_sha256": manifest.get("spec_sha256"),
            "event_count": status["event_count"],
            "head_hash": status["head_hash"],
        })
        if manifest.get("spec_sha256") != tb4["spec_sha256"]:
            failures.append("TB4 runtime manifest uses a different frozen spec")
    elif require_runtime:
        failures.append(f"TB4 runtime manifest not found: {ledger.manifest_path}")

    result = {
        "protocol": baseline["protocol"],
        "accepted_design": baseline["accepted_design"],
        "source_commit": baseline["source_commit"],
        "spec_sha256": actual_spec,
        "definition_hash": actual_definition,
        "protected_files": verified_files,
        "runtime": runtime,
        "failures": failures,
    }
    if failures:
        raise RuntimeError("; ".join(failures))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument("--require-runtime", action="store_true")
    args = parser.parse_args()
    try:
        result = verify_baseline(
            args.baseline,
            runtime_dir=args.runtime_dir,
            require_runtime=args.require_runtime,
        )
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"MODULAR_BASELINE_FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    print("MODULAR_BASELINE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
