from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from importlib.resources import files
import json
from pathlib import Path
from typing import Any, Mapping

from orbit.domain.strategy.trend_basket_runner import TB4_SPEC


DEFAULT_LIVE_CAPITAL_USDT = Decimal("500")


def load_tb4_exchange_rules(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        resource = files("orbit.config_data").joinpath("tb4_exchange_rules.json")
        payload = json.loads(resource.read_text(encoding="utf-8"))
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("protocol") != "TB4_BINANCE_USDT_FUTURES_RULES_V1":
        raise ValueError("unsupported TB4 exchange-rules protocol")
    symbols = payload.get("symbols") or {}
    if set(symbols) != set(TB4_SPEC.symbols):
        raise ValueError("TB4 exchange rules must cover the frozen 12-market universe")
    for symbol, rule in symbols.items():
        for field in ("quantity_step", "min_quantity", "min_notional_usdt"):
            if Decimal(str(rule.get(field, "0"))) <= 0:
                raise ValueError(f"{symbol} has invalid {field}")
    return payload


class TrendExecutionChecklistProjector:
    """Pure LIVE-SMALL projection from a restored frozen runner.

    The checklist intentionally uses the latest *executed rebalance target*.
    The runner's current weights drift every close and are therefore not a
    stable weekly manual-execution instruction.
    """

    def __init__(
        self,
        *,
        live_capital_usdt: Decimal | float | str = DEFAULT_LIVE_CAPITAL_USDT,
        exchange_rules: Mapping[str, Any] | None = None,
    ) -> None:
        self.live_capital_usdt = Decimal(str(live_capital_usdt))
        if self.live_capital_usdt <= 0:
            raise ValueError("live_capital_usdt must be positive")
        self.exchange_rules = deepcopy(
            dict(exchange_rules) if exchange_rules is not None else load_tb4_exchange_rules()
        )
        load_symbols = self.exchange_rules.get("symbols") or {}
        if set(load_symbols) != set(TB4_SPEC.symbols):
            raise ValueError("TB4 exchange rules must cover the frozen 12-market universe")
        for symbol, rule in load_symbols.items():
            for field in ("quantity_step", "min_quantity", "min_notional_usdt"):
                if Decimal(str(rule.get(field, "0"))) <= 0:
                    raise ValueError(f"{symbol} has invalid {field}")

    def project(self, runner: Any) -> dict[str, Any]:
        base = {
            "protocol": "LIVE_SMALL_EXECUTION_CHECKLIST_V1",
            "read_only": True,
            "live_trading": False,
            "capital_usdt": float(self.live_capital_usdt),
            "rules": {
                "protocol": self.exchange_rules["protocol"],
                "source": self.exchange_rules.get("source"),
                "fetched_at": self.exchange_rules.get("fetched_at"),
                "refresh_after_days": self.exchange_rules.get("refresh_after_days"),
            },
            "rows": [],
            "summary": self._empty_summary(),
        }
        if not runner.times:
            return base | {
                "status": "NOT_AVAILABLE",
                "reason": "TB4_FORWARD_NOT_STARTED",
                "close_time_ms": None,
                "rebalance_time_ms": None,
            }
        if not runner.rebalances:
            return base | {
                "status": "AWAITING_FIRST_REBALANCE",
                "reason": "NO_EXECUTED_REBALANCE",
                "close_time_ms": int(runner.times[-1]),
                "rebalance_time_ms": None,
                "rules_stale": self._rules_stale(int(runner.times[-1])),
            }

        latest = runner.rebalances[-1]
        previous_weights = (
            runner.rebalances[-2]["target_weights"]
            if len(runner.rebalances) > 1
            else {symbol: 0.0 for symbol in TB4_SPEC.symbols}
        )
        target_weights = latest["target_weights"]
        closes = {
            symbol: Decimal(str(runner.closes[symbol][-1]))
            for symbol in TB4_SPEC.symbols
        }
        rows = [
            self._row(
                symbol,
                Decimal(str(target_weights[symbol])),
                Decimal(str(previous_weights[symbol])),
                closes[symbol],
            )
            for symbol in TB4_SPEC.symbols
        ]
        target_gross = sum(
            (Decimal(str(row["target_notional_usdt"])) for row in rows),
            Decimal("0"),
        )
        executable_gross = sum(
            (Decimal(str(row["executable_notional_usdt"])) for row in rows),
            Decimal("0"),
        )
        target_gross_weight = sum(
            (abs(Decimal(str(row["weight"]))) for row in rows),
            Decimal("0"),
        )
        ratio = executable_gross / target_gross if target_gross > 0 else Decimal("1")
        return base | {
            "status": "READY",
            "reason": None,
            "close_time_ms": int(runner.times[-1]),
            "rebalance_time_ms": int(latest["execution_time_ms"]),
            "signal_time_ms": int(latest["signal_time_ms"]),
            "rules_stale": self._rules_stale(int(runner.times[-1])),
            "rows": rows,
            "summary": {
                "target_gross_weight": float(target_gross_weight),
                "target_gross_notional_usdt": float(target_gross),
                "executable_gross_notional_usdt": float(executable_gross),
                "executable_notional_ratio": float(ratio),
                "executable_symbols": sum(row["status"] == "EXECUTABLE" for row in rows),
                "below_minimum_symbols": sum(
                    row["status"] == "BELOW_MIN_NOTIONAL" for row in rows
                ),
                "flat_symbols": sum(row["status"] == "FLAT" for row in rows),
            },
        }

    def _row(
        self,
        symbol: str,
        weight: Decimal,
        previous_weight: Decimal,
        close: Decimal,
    ) -> dict[str, Any]:
        rule = self.exchange_rules["symbols"][symbol]
        signed_target_notional = weight * self.live_capital_usdt
        target_notional = abs(signed_target_notional)
        previous_signed_notional = previous_weight * self.live_capital_usdt
        notional_change = signed_target_notional - previous_signed_notional
        direction = "LONG" if weight > 0 else ("SHORT" if weight < 0 else "FLAT")
        step = Decimal(str(rule["quantity_step"]))
        min_quantity = Decimal(str(rule["min_quantity"]))
        min_notional = Decimal(str(rule["min_notional_usdt"]))
        raw_quantity = target_notional / close if close > 0 else Decimal("0")
        rounded_quantity = (
            (raw_quantity / step).to_integral_value(rounding=ROUND_DOWN) * step
            if raw_quantity > 0 else Decimal("0")
        )
        rounded_notional = rounded_quantity * close

        if direction == "FLAT":
            status = "FLAT"
            executable_quantity = Decimal("0")
            action = "保持 FLAT"
        elif rule.get("status") != "TRADING":
            status = "MARKET_NOT_TRADING"
            executable_quantity = Decimal("0")
            action = "市场不可交易，保持 FLAT"
        elif (
            target_notional < min_notional
            or rounded_quantity < min_quantity
            or rounded_notional < min_notional
        ):
            status = "BELOW_MIN_NOTIONAL"
            executable_quantity = Decimal("0")
            action = "低于最低下单额，保持 FLAT"
        else:
            status = "EXECUTABLE"
            executable_quantity = rounded_quantity
            action = f"调整至 {direction} {self._decimal_text(executable_quantity)}"

        executable_notional = executable_quantity * close
        signed_executable_quantity = (
            executable_quantity if direction == "LONG"
            else (-executable_quantity if direction == "SHORT" else Decimal("0"))
        )
        return {
            "symbol": symbol,
            "direction": direction,
            "weight": float(weight),
            "close_price": float(close),
            "signed_target_notional_usdt": float(signed_target_notional),
            "target_notional_usdt": float(target_notional),
            "notional_change_usdt": float(notional_change),
            "raw_target_quantity": float(raw_quantity),
            "target_quantity": float(executable_quantity),
            "signed_target_quantity": float(signed_executable_quantity),
            "executable_notional_usdt": float(executable_notional),
            "quantity_step": self._decimal_text(step),
            "min_quantity": self._decimal_text(min_quantity),
            "min_notional_usdt": float(min_notional),
            "market_status": rule.get("status"),
            "status": status,
            "action": action,
        }

    def _rules_stale(self, close_time_ms: int) -> bool:
        fetched_at = str(self.exchange_rules.get("fetched_at") or "")
        refresh_days = int(self.exchange_rules.get("refresh_after_days") or 0)
        if not fetched_at or refresh_days <= 0:
            return True
        fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        close = datetime.fromtimestamp(close_time_ms / 1000, timezone.utc)
        return (close - fetched).total_seconds() > refresh_days * 86_400

    @staticmethod
    def _empty_summary() -> dict[str, Any]:
        return {
            "target_gross_weight": 0.0,
            "target_gross_notional_usdt": 0.0,
            "executable_gross_notional_usdt": 0.0,
            "executable_notional_ratio": 0.0,
            "executable_symbols": 0,
            "below_minimum_symbols": 0,
            "flat_symbols": len(TB4_SPEC.symbols),
        }

    @staticmethod
    def _decimal_text(value: Decimal) -> str:
        return format(value, "f")
