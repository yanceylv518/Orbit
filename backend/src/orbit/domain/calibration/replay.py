from __future__ import annotations

from collections import Counter
from copy import deepcopy
from decimal import Decimal
from typing import Any, Sequence

from orbit.domain.calibration.history import FundingPoint, MarketCandle
from orbit.domain.strategy.engine import EventEngine, d, q


def event_family(event_type: str) -> str:
    for prefix in ("PROFIT_TRANSFER", "LOSS_SIDE_REDUCTION", "POSITION_RECOVERY", "POSITION_REBUILD"):
        if event_type.startswith(prefix):
            return prefix
    return event_type or "UNKNOWN"


def strategy_variant(strategy_config: dict[str, Any], variant: str) -> dict[str, Any]:
    config = deepcopy(strategy_config)
    events = config["strategy"]["events"]
    if variant == "full":
        return config
    if variant == "profit_transfer_reduce_only":
        events["profit_transfer"]["sizing"]["use_realized_profit_ratio_for_loss_side"] = 0
    elif variant == "no_profit_transfer":
        events["profit_transfer"]["enabled"] = False
    elif variant == "no_recovery":
        events["position_recovery"]["enabled"] = False
    elif variant == "no_loss_reduction":
        events["loss_side_reduction"]["enabled"] = False
    elif variant == "profit_transfer_only":
        events["loss_side_reduction"]["enabled"] = False
        events["position_recovery"]["enabled"] = False
    elif variant == "trend_reduction_only":
        events["profit_transfer"]["enabled"] = False
        events["position_recovery"]["enabled"] = False
    elif variant == "neutralize_counter_trend_skew":
        events["loss_side_reduction"]["sizing"]["neutralize_counter_trend_skew_only"] = True
    elif variant == "neutral_hold":
        events["profit_transfer"]["enabled"] = False
        events["loss_side_reduction"]["enabled"] = False
        events["position_recovery"]["enabled"] = False
    else:
        raise ValueError(f"unknown strategy variant: {variant}")
    return config


def replay_event_engine(
    closes: Sequence[float],
    strategy_config: dict[str, Any],
    *,
    symbol: str = "BTCUSDT",
    budget_usdt: float = 100.0,
    close_out: bool = True,
    charge_initial_entry: bool = True,
    candle_times_ms: Sequence[int] | None = None,
    funding_points: Sequence[FundingPoint] | None = None,
    intrabar_candles: Sequence[MarketCandle] | None = None,
    intrabar_mode: str = "myopic",
) -> dict[str, Any]:
    prices = [Decimal(str(price)) for price in closes if float(price) > 0]
    if len(prices) < 2:
        raise ValueError("at least two positive closes are required")
    if candle_times_ms is not None and len(candle_times_ms) != len(closes):
        raise ValueError("candle_times_ms must match closes length")
    if intrabar_candles is not None and len(intrabar_candles) != len(closes):
        raise ValueError("intrabar_candles must match closes length")
    if intrabar_mode not in {"myopic", "fixed_ohlc", "fixed_olhc"}:
        raise ValueError("intrabar_mode must be myopic, fixed_ohlc, or fixed_olhc")
    clean_times = [
        int(candle_times_ms[index])
        for index, price in enumerate(closes)
        if float(price) > 0
    ] if candle_times_ms is not None else None

    engine = EventEngine(strategy_config)
    state = engine.initialize_symbol(symbol, prices[0], Decimal(str(budget_usdt)))
    initial_equity = d(state["budget_usdt"])
    initial_trades = []
    if charge_initial_entry:
        base_qty = d(state["base_qty"])
        state["long_qty"] = "0"
        state["short_qty"] = "0"
        engine.mark_to_market(state, prices[0])
        initial_trades.append(engine.apply_trade(
            state, prices[0], "ADD_LONG", base_qty,
            "REPLAY_INITIAL_ENTRY", "historical replay initial hedge",
        ))
        initial_trades.append(engine.apply_trade(
            state, prices[0], "ADD_SHORT", base_qty,
            "REPLAY_INITIAL_ENTRY", "historical replay initial hedge",
        ))
    equity_after_initial_entry = d(state["equity"])
    peak_equity = initial_equity
    minimum_equity = min(initial_equity, equity_after_initial_entry)
    max_drawdown = initial_equity - minimum_equity
    event_counts: Counter[str] = Counter()
    risk_counts: Counter[str] = Counter()
    trade_counts: Counter[str] = Counter()
    attribution: dict[str, dict[str, Decimal | int]] = {}
    event_count = 0
    risk_event_count = 0
    trade_count = 0
    funding_index = 0
    funding_applied = 0
    intrabar_path_counts: Counter[str] = Counter()
    sorted_funding = sorted(funding_points or (), key=lambda point: point.funding_time_ms)

    def apply_due_funding(price: Decimal, close_time_ms: int) -> None:
        nonlocal funding_index, funding_applied
        while funding_index < len(sorted_funding) and sorted_funding[funding_index].funding_time_ms <= close_time_ms:
            point = sorted_funding[funding_index]
            if clean_times is not None and point.funding_time_ms >= clean_times[0]:
                cashflow = q(
                    (d(state["short_qty"]) - d(state["long_qty"]))
                    * price * d(point.funding_rate)
                )
                state["realized_pnl"] = str(q(d(state["realized_pnl"]) + cashflow))
                state["funding_total"] = str(q(d(state["funding_total"]) + cashflow))
                engine.mark_to_market(state, price)
                funding_applied += 1
            funding_index += 1

    def run_candle_path(
        start_state: dict[str, Any],
        points: Sequence[float],
        close_price: Decimal,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        candidate_state = start_state
        candidate_events: list[dict[str, Any]] = []
        candidate_risks: list[dict[str, Any]] = []
        for point in points:
            candidate_state, events, risks = engine.on_intrabar_price(candidate_state, Decimal(str(point)))
            candidate_events.extend(events)
            candidate_risks.extend(risks)
        candidate_state, events, risks = engine.on_tick(candidate_state, close_price)
        candidate_events.extend(events)
        candidate_risks.extend(risks)
        return candidate_state, candidate_events, candidate_risks

    for price_index, price in enumerate(prices[1:], start=1):
        if intrabar_candles is None:
            state, events, risks = engine.on_tick(state, price)
        else:
            candle = intrabar_candles[price_index]
            paths = (
                ("O-H-L-C", (candle.open, candle.high, candle.low)),
                ("O-L-H-C", (candle.open, candle.low, candle.high)),
            )
            candidates = [
                (name, *run_candle_path(state, points, price))
                for name, points in paths
            ]
            if intrabar_mode == "fixed_ohlc":
                name, state, events, risks = candidates[0]
            elif intrabar_mode == "fixed_olhc":
                name, state, events, risks = candidates[1]
            else:
                name, state, events, risks = min(
                    candidates,
                    key=lambda item: (d(item[1]["equity"]), -len(item[2])),
                )
            intrabar_path_counts[name] += 1
        if clean_times is not None and sorted_funding:
            apply_due_funding(price, clean_times[price_index])
        equity = d(state["equity"])
        peak_equity = max(peak_equity, equity)
        minimum_equity = min(minimum_equity, equity)
        max_drawdown = max(max_drawdown, peak_equity - equity)
        for event in events:
            event_count += 1
            event_counts[str(event.get("event_type") or "UNKNOWN")] += 1
            family = event_family(str(event.get("event_type") or "UNKNOWN"))
            bucket = attribution.setdefault(family, {
                "events": 0,
                "trades": 0,
                "realized_pnl_usdt": Decimal("0"),
                "fee_usdt": Decimal("0"),
                "slippage_usdt": Decimal("0"),
            })
            bucket["events"] = int(bucket["events"]) + 1
            bucket["realized_pnl_usdt"] = d(bucket["realized_pnl_usdt"]) + d(event.get("realized_pnl"))
            bucket["fee_usdt"] = d(bucket["fee_usdt"]) + d(event.get("fee_total"))
            bucket["slippage_usdt"] = d(bucket["slippage_usdt"]) + d(event.get("slippage_total"))
            for trade in event.get("trades", []):
                trade_count += 1
                trade_counts[str(trade.get("action") or "UNKNOWN")] += 1
                bucket["trades"] = int(bucket["trades"]) + 1
        for risk in risks:
            risk_event_count += 1
            risk_counts[str(risk.get("risk_type") or "UNKNOWN")] += 1
            for trade in risk.get("trades", []):
                trade_count += 1
                trade_counts[str(trade.get("action") or "UNKNOWN")] += 1

    mark_equity_before_closeout = d(state["equity"])
    terminal_trades = []
    if close_out:
        final_price = prices[-1]
        if d(state["long_qty"]) > 0:
            terminal_trades.append(engine.apply_trade(
                state, final_price, "REDUCE_LONG", d(state["long_qty"]),
                "REPLAY_CLOSEOUT", "historical replay terminal closeout",
            ))
        if d(state["short_qty"]) > 0:
            terminal_trades.append(engine.apply_trade(
                state, final_price, "REDUCE_SHORT", d(state["short_qty"]),
                "REPLAY_CLOSEOUT", "historical replay terminal closeout",
            ))
    final_equity = d(state["equity"])
    minimum_equity = min(minimum_equity, final_equity)
    max_drawdown = max(max_drawdown, peak_equity - final_equity)
    realized = d(state["realized_pnl"])
    unrealized = d(state["long_unrealized_pnl"]) + d(state["short_unrealized_pnl"])
    fee_total = d(state["fee_total"])
    slippage_total = d(state["slippage_total"])
    funding_total = d(state["funding_total"])
    return {
        "symbol": symbol,
        "candles": len(prices),
        "initial_price": float(prices[0]),
        "final_price": float(prices[-1]),
        "budget_usdt": float(initial_equity),
        "initial_equity_usdt": float(initial_equity),
        "equity_after_initial_entry_usdt": float(equity_after_initial_entry),
        "initial_entry_charged": charge_initial_entry,
        "initial_entry_trade_count": len(initial_trades),
        "initial_entry_fee_usdt": float(sum(d(item["fee"]) for item in initial_trades)),
        "initial_entry_slippage_usdt": float(sum(d(item["slippage_cost"]) for item in initial_trades)),
        "final_equity_usdt": float(final_equity),
        "mark_equity_before_closeout_usdt": float(mark_equity_before_closeout),
        "terminal_closeout_enabled": close_out,
        "terminal_closeout_trade_count": len(terminal_trades),
        "terminal_closeout_realized_pnl_usdt": float(sum(d(item["realized_pnl"]) for item in terminal_trades)),
        "net_pnl_usdt": float(final_equity - initial_equity),
        "return_pct": float((final_equity / initial_equity - 1) * 100) if initial_equity else 0.0,
        "realized_pnl_usdt": float(realized),
        "unrealized_pnl_usdt": float(unrealized),
        "fee_total_usdt": float(fee_total),
        "slippage_total_usdt": float(slippage_total),
        "funding_total_usdt": float(funding_total),
        "funding_model": "historical_binance_rate_at_candle_close" if sorted_funding and clean_times else
        "unavailable_without_historical_funding_series",
        "funding_points_applied": funding_applied,
        "funding_coverage_complete": bool(
            sorted_funding and clean_times
            and sorted_funding[0].funding_time_ms <= clean_times[0] + 9 * 3_600_000
            and sorted_funding[-1].funding_time_ms >= clean_times[-1] - 9 * 3_600_000
        ),
        "intrabar_model": (
            {
                "myopic": "myopic_min_close_equity_of_OHLC_OLHC",
                "fixed_ohlc": "fixed_O_H_L_C",
                "fixed_olhc": "fixed_O_L_H_C",
            }[intrabar_mode]
            if intrabar_candles is not None else "close_only"
        ),
        "intrabar_path_counts": dict(sorted(intrabar_path_counts.items())),
        "closed_candles_processed": int(state.get("tick_count", 0)),
        "max_drawdown_usdt": float(max_drawdown),
        "max_drawdown_pct_of_budget": float(max_drawdown / initial_equity * 100) if initial_equity else 0.0,
        "minimum_equity_usdt": float(minimum_equity),
        "max_loss_from_budget_usdt": float(max(Decimal("0"), initial_equity - minimum_equity)),
        "max_loss_from_budget_pct": float(
            max(Decimal("0"), initial_equity - minimum_equity) / initial_equity * 100
        ) if initial_equity else 0.0,
        "event_count": event_count,
        "risk_event_count": risk_event_count,
        "trade_count": trade_count,
        "event_counts": dict(sorted(event_counts.items())),
        "risk_counts": dict(sorted(risk_counts.items())),
        "trade_counts": dict(sorted(trade_counts.items())),
        "event_attribution": {
            family: {
                "events": int(values["events"]),
                "trades": int(values["trades"]),
                "realized_pnl_usdt": float(d(values["realized_pnl_usdt"])),
                "fee_usdt": float(d(values["fee_usdt"])),
                "slippage_usdt": float(d(values["slippage_usdt"])),
                "gross_realized_before_fee_usdt": float(
                    d(values["realized_pnl_usdt"]) + d(values["fee_usdt"])
                ),
            }
            for family, values in sorted(attribution.items())
        },
        "stopped": state.get("state") == "STOPPED",
        "final_state": state.get("state"),
        "final_long_qty": float(d(state["long_qty"])),
        "final_short_qty": float(d(state["short_qty"])),
        "accounting_identity_error_usdt": float(final_equity - initial_equity - realized - unrealized),
    }


def replay_walk_forward(
    closes: Sequence[float],
    strategy_config: dict[str, Any],
    *,
    symbol: str,
    train_size: int,
    validation_size: int,
    step: int | None = None,
    budget_usdt: float = 100.0,
    candle_times_ms: Sequence[int] | None = None,
    funding_points: Sequence[FundingPoint] | None = None,
    intrabar_candles: Sequence[MarketCandle] | None = None,
    intrabar_mode: str = "myopic",
) -> dict[str, Any]:
    if train_size < 1 or validation_size < 2:
        raise ValueError("train_size must be positive and validation_size must be at least two")
    step = int(step or validation_size)
    folds = []
    start = 0
    while start + train_size + validation_size <= len(closes):
        validation_start = start + train_size
        validation_end = validation_start + validation_size
        report = replay_event_engine(
            closes[validation_start:validation_end],
            strategy_config,
            symbol=symbol,
            budget_usdt=budget_usdt,
            close_out=True,
            candle_times_ms=(candle_times_ms[validation_start:validation_end] if candle_times_ms else None),
            funding_points=funding_points,
            intrabar_candles=(intrabar_candles[validation_start:validation_end] if intrabar_candles else None),
            intrabar_mode=intrabar_mode,
        )
        folds.append({
            "fold": len(folds) + 1,
            "validation_start": validation_start,
            "validation_end": validation_end,
            "report": report,
        })
        start += step
    if not folds:
        raise ValueError("not enough closes for one replay fold")
    return {
        "symbol": symbol,
        "train_size": train_size,
        "validation_size": validation_size,
        "step": step,
        "folds": folds,
        "aggregate": aggregate_replay_folds(folds),
    }


def aggregate_replay_folds(folds: Sequence[dict[str, Any]]) -> dict[str, Any]:
    reports = [fold["report"] for fold in folds]
    return {
        "folds": len(folds),
        "profitable_folds": sum(1 for report in reports if report["net_pnl_usdt"] > 0),
        "stopped_folds": sum(1 for report in reports if report["stopped"]),
        "total_net_pnl_usdt": sum(float(report["net_pnl_usdt"]) for report in reports),
        "average_return_pct": sum(float(report["return_pct"]) for report in reports) / len(reports),
        "worst_fold_return_pct": min(float(report["return_pct"]) for report in reports),
        "worst_fold_drawdown_pct": max(float(report["max_drawdown_pct_of_budget"]) for report in reports),
        "total_trades": sum(int(report["trade_count"]) for report in reports),
    }


def loss_reduction_candidates(strategy_config: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    specs = (
        ("default", True, 4.0, 0.10),
        ("light_4pct", True, 4.0, 0.05),
        ("very_light_4pct", True, 4.0, 0.025),
        ("late_5pct_light", True, 5.0, 0.05),
        ("late_6pct_light", True, 6.0, 0.05),
        ("disabled", False, 4.0, 0.10),
    )
    candidates = []
    for name, enabled, trigger_pct, reduce_ratio in specs:
        config = deepcopy(strategy_config)
        loss = config["strategy"]["events"]["loss_side_reduction"]
        loss["enabled"] = enabled
        loss["trigger"]["trend_confirm_move_pct_from_base"] = trigger_pct
        loss["sizing"]["reduce_loss_side_ratio"] = reduce_ratio
        candidates.append((name, config))
    return candidates


def select_loss_reduction_candidate(
    train_closes: Sequence[float],
    strategy_config: dict[str, Any],
    *,
    symbol: str,
    budget_usdt: float,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    evaluated = []
    inner_size = len(train_closes) // 3
    if inner_size < 2:
        raise ValueError("training window is too short for inner stability folds")
    for name, config in loss_reduction_candidates(strategy_config):
        inner_folds = []
        for index in range(3):
            start = index * inner_size
            end = len(train_closes) if index == 2 else start + inner_size
            inner_folds.append({
                "fold": index + 1,
                "report": replay_event_engine(
                    train_closes[start:end], config,
                    symbol=symbol, budget_usdt=budget_usdt, close_out=True,
                ),
            })
        report = aggregate_replay_folds(inner_folds)
        reduction_events = sum(
            int(fold["report"]["event_attribution"].get("LOSS_SIDE_REDUCTION", {}).get("events", 0))
            for fold in inner_folds
        )
        eligible = name == "disabled" or reduction_events >= 3
        evaluated.append((name, config, report, eligible, reduction_events))
    pool = [item for item in evaluated if item[3]]
    selected = max(
        pool,
        key=lambda item: (
            int(item[2]["profitable_folds"]),
            float(item[2]["total_net_pnl_usdt"]),
            float(item[2]["worst_fold_return_pct"]),
            -float(item[2]["worst_fold_drawdown_pct"]),
            -int(item[2]["total_trades"]),
        ),
    )
    name, config, report, _, reduction_events = selected
    report = deepcopy(report)
    report["candidate_name"] = name
    report["inner_folds"] = 3
    report["reduction_events"] = reduction_events
    report["eligible_candidates"] = len(pool)
    report["evaluated_candidates"] = len(evaluated)
    return name, config, report


def replay_walk_forward_tuned_loss_reduction(
    closes: Sequence[float],
    strategy_config: dict[str, Any],
    *,
    symbol: str,
    train_size: int,
    validation_size: int,
    step: int | None = None,
    budget_usdt: float = 100.0,
) -> dict[str, Any]:
    step = int(step or validation_size)
    folds = []
    start = 0
    while start + train_size + validation_size <= len(closes):
        train_end = start + train_size
        validation_end = train_end + validation_size
        name, selected_config, training_report = select_loss_reduction_candidate(
            closes[start:train_end], strategy_config, symbol=symbol, budget_usdt=budget_usdt,
        )
        validation_report = replay_event_engine(
            closes[train_end:validation_end], selected_config,
            symbol=symbol, budget_usdt=budget_usdt, close_out=True,
        )
        folds.append({
            "fold": len(folds) + 1,
            "train_start": start,
            "train_end": train_end,
            "validation_end": validation_end,
            "selected_candidate": name,
            "training_report": training_report,
            "report": validation_report,
        })
        start += step
    if not folds:
        raise ValueError("not enough closes for one tuned replay fold")
    return {
        "symbol": symbol,
        "train_size": train_size,
        "validation_size": validation_size,
        "step": step,
        "folds": folds,
        "selection_counts": dict(sorted(Counter(fold["selected_candidate"] for fold in folds).items())),
        "aggregate": aggregate_replay_folds(folds),
    }


def aggregate_replay_markets(market_results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not market_results:
        raise ValueError("market_results must not be empty")
    fold_reports = [
        fold["report"]
        for market in market_results
        for fold in market["result"]["folds"]
    ]
    total_folds = len(fold_reports)
    profitable_folds = sum(1 for report in fold_reports if report["net_pnl_usdt"] > 0)
    profitable_markets = sum(
        1 for market in market_results
        if market["result"]["aggregate"]["total_net_pnl_usdt"] > 0
    )
    funding_complete = all(bool(report.get("funding_coverage_complete")) for report in fold_reports)
    total_pnl = sum(float(report["net_pnl_usdt"]) for report in fold_reports)
    required_markets = len(market_results) // 2 + 1
    required_folds = total_folds // 2 + 1
    attribution: dict[str, dict[str, float | int]] = {}
    for report in fold_reports:
        for family, values in report.get("event_attribution", {}).items():
            bucket = attribution.setdefault(family, {
                "events": 0, "trades": 0, "realized_pnl_usdt": 0.0,
                "fee_usdt": 0.0, "slippage_usdt": 0.0,
                "gross_realized_before_fee_usdt": 0.0,
            })
            for key in ("events", "trades"):
                bucket[key] = int(bucket[key]) + int(values[key])
            for key in (
                "realized_pnl_usdt", "fee_usdt", "slippage_usdt",
                "gross_realized_before_fee_usdt",
            ):
                bucket[key] = float(bucket[key]) + float(values[key])
    return {
        "markets": len(market_results),
        "folds": total_folds,
        "profitable_markets": profitable_markets,
        "required_profitable_markets": required_markets,
        "profitable_folds": profitable_folds,
        "required_profitable_folds": required_folds,
        "total_net_pnl_usdt": total_pnl,
        "average_return_pct": sum(float(report["return_pct"]) for report in fold_reports) / total_folds,
        "worst_fold_return_pct": min(float(report["return_pct"]) for report in fold_reports),
        "worst_fold_drawdown_pct": max(
            float(report["max_drawdown_pct_of_budget"]) for report in fold_reports
        ),
        "total_trades": sum(int(report["trade_count"]) for report in fold_reports),
        "funding_cashflow_total_usdt": sum(float(report["funding_total_usdt"]) for report in fold_reports),
        "funding_points_applied": sum(int(report.get("funding_points_applied", 0)) for report in fold_reports),
        "funding_complete": funding_complete,
        "event_attribution": dict(sorted(attribution.items())),
        "stage_admitted": bool(
            total_pnl > 0
            and profitable_markets >= required_markets
            and profitable_folds >= required_folds
            and funding_complete
        ),
    }


def compare_replay_variants(
    closes: Sequence[float],
    strategy_config: dict[str, Any],
    *,
    symbol: str,
    train_size: int,
    validation_size: int,
    budget_usdt: float = 100.0,
    candle_times_ms: Sequence[int] | None = None,
    funding_points: Sequence[FundingPoint] | None = None,
    intrabar_candles: Sequence[MarketCandle] | None = None,
    intrabar_mode: str = "myopic",
    variants: Sequence[str] | None = None,
) -> dict[str, Any]:
    default_names = (
        "full",
        "profit_transfer_reduce_only",
        "no_profit_transfer",
        "no_recovery",
        "no_loss_reduction",
        "profit_transfer_only",
        "trend_reduction_only",
        "neutral_hold",
    )
    names = tuple(variants or default_names)
    return {
        name: replay_walk_forward(
            closes,
            strategy_variant(strategy_config, name),
            symbol=symbol,
            train_size=train_size,
            validation_size=validation_size,
            budget_usdt=budget_usdt,
            candle_times_ms=candle_times_ms,
            funding_points=funding_points,
            intrabar_candles=intrabar_candles,
            intrabar_mode=intrabar_mode,
        )
        for name in names
    }
