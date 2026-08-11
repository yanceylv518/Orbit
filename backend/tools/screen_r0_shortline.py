"""Run the frozen R-0 shortline estimator without touching trading systems."""

from __future__ import annotations

import argparse
import atexit
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.r0_shortline_screen import (  # noqa: E402
    R0ScreenError,
    lockbox_report,
    training_report,
    validate_training_report,
    verify_frozen_context,
)
from orbit.domain.calibration.history import FundingPoint  # noqa: E402
from orbit.domain.calibration.r0_shortline import (  # noqa: E402
    HistoricalUniverseResolver,
    ShortlineCandle,
)
from orbit.infrastructure.market_data.binance_public_archive import (  # noqa: E402
    iter_funding_zip,
    iter_kline_zip,
)
from orbit.infrastructure.persistence.atomic_file import replace_with_retry  # noqa: E402
from orbit.infrastructure.persistence.dataset_job_lock import DatasetJobLock  # noqa: E402


DEFAULT_SPEC = PROJECT_ROOT / "config" / "research" / "r0_shortline_screen.v2.json"
DEFAULT_ROOT = PROJECT_ROOT / "var" / "calibration" / "shortline-data-v1"
MONTH_IN_NAME = re.compile(r"-(\d{4}-\d{2})(?:\.zip|\.jsonl\.gz)$")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--spec", default=str(DEFAULT_SPEC))
    parser.add_argument("--lock-owner-token")
    commands = parser.add_subparsers(dest="command", required=True)
    train = commands.add_parser("train", help="Evaluate only the frozen training period")
    train.add_argument("--out", required=True)
    train.add_argument("--progress-state")
    train.add_argument("--checkpoint-dir")
    lockbox = commands.add_parser("lockbox", help="Open the one-time frozen lockbox")
    lockbox.add_argument("--training-report", required=True)
    lockbox.add_argument("--out", required=True)
    lockbox.add_argument(
        "--marker", default=str(PROJECT_ROOT / "var" / "research" / "r0_lockbox_opened.json"),
    )
    lockbox.add_argument("--confirm-open-lockbox", action="store_true")
    lockbox.add_argument("--progress-state")
    lockbox.add_argument("--checkpoint-dir")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if args.lock_owner_token:
        DatasetJobLock.validate_token(root, args.lock_owner_token)
    else:
        direct_lock = DatasetJobLock(root, owner="r0-cli", run_id=args.command)
        direct_lock.acquire()
        atexit.register(direct_lock.release)
    context = verify_frozen_context(Path(args.spec).resolve(), root)
    contract = context["contract"]
    split = contract["sample_split"]
    progress = _progress_reporter(
        Path(args.progress_state).resolve() if args.progress_state else None,
        phase=args.command.upper(),
        contract_sha256=context["contract_sha256"],
        dataset_fingerprint=context["manifest"]["dataset_fingerprint"],
    )

    if args.command == "train":
        _require_absent(Path(args.out))
        end_ms = int(contract["sample_split"]["training_end_ms"])
        symbols, resolver = _prepare_universe(root, contract, maximum_time_ms=end_ms)
        report = training_report(
            context,
            symbols,
            _market_loader(root, minimum_time_ms=None, maximum_time_ms=end_ms),
            tier_at=resolver.tier_at,
            diagnostics_at=resolver.diagnostics_at,
            progress_callback=progress,
            checkpoint_dir=Path(args.checkpoint_dir).resolve() if args.checkpoint_dir else None,
        )
        _write_exclusive(Path(args.out), report)
    else:
        if not args.confirm_open_lockbox:
            parser.error("lockbox requires --confirm-open-lockbox")
        training_path = Path(args.training_report).resolve()
        _require_absent(Path(args.out))
        training = json.loads(training_path.read_text(encoding="utf-8"))
        validate_training_report(context, training)
        if not any(training.get("selected_candidates", {}).values()):
            raise R0ScreenError("training failed; lockbox remains unopened")
        marker = Path(args.marker).resolve()
        claim_lockbox_once(marker, {
            "protocol": "ORBIT_R0_LOCKBOX_OPEN_V2",
            "contract_sha256": context["contract_sha256"],
            "dataset_fingerprint": context["manifest"]["dataset_fingerprint"],
            "training_report_sha256": _sha256(training_path),
        })
        symbols, resolver = _prepare_universe(
            root, contract, maximum_time_ms=int(split["lockbox_end_ms"]),
        )
        start_ms = int(split["lockbox_start_ms"])
        report = lockbox_report(
            context,
            training,
            symbols,
            _market_loader(
                root,
                minimum_time_ms=start_ms - 2 * 24 * 60 * 60 * 1000,
                maximum_time_ms=int(split["lockbox_end_ms"]),
            ),
            tier_at=resolver.tier_at,
            diagnostics_at=resolver.diagnostics_at,
            progress_callback=progress,
            checkpoint_dir=Path(args.checkpoint_dir).resolve() if args.checkpoint_dir else None,
        )
        _write_exclusive(Path(args.out), report)
    progress({"phase": "complete", "progress": 100, "verdict": report["verdict"]})
    print(json.dumps({
        "phase": report["phase"], "verdict": report["verdict"],
        "output": str(Path(args.out).resolve()),
    }, ensure_ascii=False))


def claim_lockbox_once(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as target:
            json.dump(payload, target, ensure_ascii=False, sort_keys=True, indent=2)
            target.write("\n")
    except FileExistsError as exc:
        raise R0ScreenError("R-0 lockbox has already been opened") from exc


def _prepare_universe(root: Path, contract: dict[str, Any], *, maximum_time_ms: int):
    contracts, liquidity = _load_universe_inputs(root, maximum_time_ms=maximum_time_ms)
    resolver = HistoricalUniverseResolver(
        contracts,
        liquidity,
        min_history_days=int(contract["universe"]["min_history_days"]),
        liquidity_lookback_days=int(contract["universe"]["liquidity_lookback_days"]),
        minimum_volume=str(contract["universe"]["min_median_daily_quote_volume_usdt"]),
        limit=(
            int(contract["universe"]["limit"])
            if contract["universe"].get("limit") is not None else None
        ),
        tiering=contract["universe"]["tiering"],
    )
    return [str(item["symbol"]) for item in contracts], resolver


def _load_universe_inputs(
    root: Path,
    *,
    maximum_time_ms: int,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    contracts_payload = json.loads(
        (root / "metadata" / "contracts.json").read_text(encoding="utf-8")
    )
    contracts = list(contracts_payload["contracts"])
    liquidity: dict[str, list[dict[str, Any]]] = {}
    for contract in contracts:
        symbol = str(contract["symbol"])
        rows = []
        base = root / "derived" / "daily_liquidity" / symbol
        for path in sorted(base.glob("*.jsonl.gz")):
            if _archive_month(path) > _month(maximum_time_ms):
                continue
            with gzip.open(path, "rt", encoding="utf-8") as source:
                for line in source:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    if int(row["day_close_time_ms"]) <= maximum_time_ms:
                        rows.append(row)
        liquidity[symbol] = rows
    return contracts, liquidity


def _market_loader(root: Path, *, minimum_time_ms: int | None, maximum_time_ms: int):
    minimum_month = _month(minimum_time_ms) if minimum_time_ms is not None else None
    maximum_month = _month(maximum_time_ms)

    def load(symbol: str):
        candle_rows = []
        for path in sorted((root / "raw" / "klines" / "15m" / symbol).glob("*.zip")):
            month = _archive_month(path)
            if month > maximum_month or (minimum_month is not None and month < minimum_month):
                continue
            for item in iter_kline_zip(path):
                if item.open_time_ms > maximum_time_ms:
                    continue
                candle_rows.append(ShortlineCandle(
                    item.open_time_ms, item.close_time_ms,
                    float(item.open), float(item.high), float(item.low), float(item.close),
                    float(item.quote_volume),
                ))
        funding_rows = []
        for path in sorted((root / "raw" / "funding" / symbol).glob("*.zip")):
            month = _archive_month(path)
            if month > maximum_month or (minimum_month is not None and month < minimum_month):
                continue
            for item in iter_funding_zip(path):
                timestamp = int(item["funding_time_ms"])
                if timestamp <= maximum_time_ms:
                    funding_rows.append(FundingPoint(timestamp, float(item["funding_rate"])))
        return candle_rows, funding_rows

    return load


def _archive_month(path: Path) -> str:
    match = MONTH_IN_NAME.search(path.name)
    if match is None:
        raise R0ScreenError(f"cannot determine archive month: {path.name}")
    return match.group(1)


def _month(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).strftime("%Y-%m")


def _write_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as target:
            json.dump(payload, target, ensure_ascii=False, sort_keys=True, indent=2)
            target.write("\n")
    except FileExistsError as exc:
        raise R0ScreenError(f"result already exists: {path}") from exc


def _require_absent(path: Path) -> None:
    if path.exists():
        raise R0ScreenError(f"result already exists: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _progress_reporter(
    path: Path | None,
    *,
    phase: str,
    contract_sha256: str,
    dataset_fingerprint: str,
):
    def report(detail: dict[str, Any]) -> None:
        if path is None:
            return
        completed_symbols = int(detail.get("completed_symbols") or 0)
        total_symbols = int(detail.get("total_symbols") or 0)
        completed_combinations = int(detail.get("completed_combinations") or 0)
        total_combinations = int(detail.get("total_combinations") or 0)
        if detail.get("phase") == "scan":
            calculated = int(85 * completed_symbols / total_symbols) if total_symbols else 0
        elif detail.get("phase") == "evaluate":
            calculated = 85 + (
                int(14 * completed_combinations / total_combinations) if total_combinations else 0
            )
        else:
            calculated = int(detail.get("progress") or 0)
        payload = {
            "protocol": "ORBIT_R0_UI_PROGRESS_V1",
            "run_phase": phase,
            "contract_sha256": contract_sha256,
            "dataset_fingerprint": dataset_fingerprint,
            "progress": calculated,
            **detail,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        replace_with_retry(temporary, path)

    report({"phase": "starting", "progress": 0})
    return report


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError, R0ScreenError) as exc:
        raise SystemExit(f"R-0 failed: {exc}") from exc
