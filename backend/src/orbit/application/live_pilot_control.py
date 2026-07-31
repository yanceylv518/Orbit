from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import re
from typing import Any, Mapping


LIVE_PILOT_PROTOCOL = "LIVE_SMALL_CONTROL_V3"
LIVE_ACTIVATION_PHRASE = "ENABLE LIVE SMALL V3"
LIVE_CHECKLIST_PROTOCOL = "LIVE_SMALL_EXECUTION_CHECKLIST_V3"
LIVE_EXPOSURE_MULTIPLIER = 3.0
LIVE_INITIAL_LEVERAGE = 3
LIVE_MARGIN_TYPE = "ISOLATED"
EPOCH_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{5,63}$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_live_pilot_control(runtime: Mapping[str, Any]) -> dict[str, Any]:
    trend = dict(runtime.get("trend_forward") or {})
    account_id = str(trend.get("live_account_id") or "").strip()
    # The persisted control record is the only authority allowed to enable live
    # execution. A deployment config may contain a legacy V1/V2 switch, but it
    # must never silently authorize the materially different V3 risk profile.
    enabled = False
    return {
        "protocol": LIVE_PILOT_PROTOCOL,
        "version": 3,
        "status": "ACTIVE" if enabled else ("CONFIGURED" if account_id else "DRAFT"),
        "forward_enabled": bool(trend.get("enabled", False)),
        "live_account_id": account_id,
        "live_capital_usdt": float(trend.get("live_capital_usdt", 500)),
        "exposure_multiplier": LIVE_EXPOSURE_MULTIPLIER,
        "initial_leverage": LIVE_INITIAL_LEVERAGE,
        "margin_type": LIVE_MARGIN_TYPE,
        "quantity_tolerance_pct": float(trend.get("quantity_tolerance_pct", 1.0)),
        "max_snapshot_age_seconds": int(trend.get("max_snapshot_age_seconds", 120)),
        "max_order_notional_usdt": float(trend.get("max_order_notional_usdt", 150)),
        "round_gross_multiplier": float(trend.get("round_gross_multiplier", 1.1)),
        "auto_execution_enabled": enabled,
        "execution_epoch": str(trend.get("auto_execution_epoch") or "").strip(),
        "rules_fetched_at": None,
        "last_preflight": None,
        "updated_at": now_iso(),
        "updated_by": "bootstrap",
    }


def normalize_live_pilot_control(
    value: Mapping[str, Any] | None,
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    control = default_live_pilot_control(runtime)
    legacy_or_mismatched = False
    if value:
        legacy_or_mismatched = (
            value.get("protocol") != LIVE_PILOT_PROTOCOL
            or float(value.get("exposure_multiplier") or 0) != LIVE_EXPOSURE_MULTIPLIER
            or int(value.get("initial_leverage") or 0) != LIVE_INITIAL_LEVERAGE
            or str(value.get("margin_type") or "").upper() != LIVE_MARGIN_TYPE
        )
        control.update(deepcopy(dict(value)))
    control["protocol"] = LIVE_PILOT_PROTOCOL
    control["version"] = max(3, int(control.get("version") or 3))
    control["exposure_multiplier"] = LIVE_EXPOSURE_MULTIPLIER
    control["initial_leverage"] = LIVE_INITIAL_LEVERAGE
    control["margin_type"] = LIVE_MARGIN_TYPE
    control["live_account_id"] = str(control.get("live_account_id") or "").strip()
    control["execution_epoch"] = str(control.get("execution_epoch") or "").strip()
    control["auto_execution_enabled"] = bool(control.get("auto_execution_enabled", False))
    control["forward_enabled"] = bool(control.get("forward_enabled", False))
    if legacy_or_mismatched:
        control["auto_execution_enabled"] = False
        control["execution_epoch"] = ""
        control["last_preflight"] = None
        control["status"] = "CONFIGURED" if control["live_account_id"] else "DRAFT"
        control["updated_at"] = now_iso()
        control["updated_by"] = "protocol-v3-migration"
    return control


def validate_epoch(value: str) -> str:
    epoch = str(value or "").strip()
    if not EPOCH_PATTERN.fullmatch(epoch):
        raise ValueError("执行批次只能使用 6-64 位小写字母、数字、点、下划线或连字符。")
    return epoch


def project_preflight(checks: list[dict[str, Any]]) -> dict[str, Any]:
    passed = all(
        bool(item.get("ok")) or not bool(item.get("required", True))
        for item in checks
    )
    return {
        "protocol": "LIVE_SMALL_PREFLIGHT_V3",
        "status": "PASS" if passed else "FAIL",
        "passed": passed,
        "deferred_count": sum(
            not bool(item.get("ok")) and not bool(item.get("required", True))
            for item in checks
        ),
        "checked_at": now_iso(),
        "checks": checks,
    }
