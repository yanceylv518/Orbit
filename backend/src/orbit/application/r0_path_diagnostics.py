from __future__ import annotations

from collections import defaultdict
import hashlib
import math
from pathlib import Path
from statistics import median
from typing import Any, Callable, Mapping, Sequence

from orbit.domain.calibration.history import FundingPoint
from orbit.domain.calibration.r0_shortline import ShortlineCandle, simulate_symbol_events


R0_DIAG_PROTOCOL = "ORBIT_R0_PATH_DIAGNOSTIC_V1"


def assert_training_reproduced(
    baseline: Mapping[str, Any], reproduced: Mapping[str, Any],
) -> None:
    """Fail closed unless the unmodified estimator reproduces every baseline field."""
    if dict(reproduced) != dict(baseline):
        raise ValueError("R0-DIAG reproduction differs from the frozen training report")


def create_path_diagnostic_report(
    context: Mapping[str, Any],
    baseline_report: Mapping[str, Any],
    symbols: Sequence[str],
    market_loader: Callable[[str], tuple[Sequence[ShortlineCandle], Sequence[FundingPoint]]],
    *,
    tier_at: Callable[[str, int], str | None],
    diagnostics_at: Callable[[str, int], Mapping[str, str] | None] | None,
    baseline_report_sha256: str,
    focus_parameter_ids: Sequence[str],
) -> dict[str, Any]:
    """Create a read-only path report for the three frozen >=10% oversold rows."""
    contract = context["contract"]
    end_ms = int(contract["sample_split"]["training_end_ms"])
    costs = {
        str(item["tier"]): float(item["round_trip"])
        for item in contract["execution"]["costs_pct_per_side_by_tier"]
    }
    focus_ids = list(focus_parameter_ids)
    selected_by_id = {
        str(item["parameter_id"]): item
        for item in baseline_report.get("parameter_reports") or []
    }
    selected = [selected_by_id[item] for item in focus_ids if item in selected_by_id]
    eligible = [
        item for item in baseline_report.get("parameter_reports") or []
        if item.get("family_id") == "OVERSOLD_REBOUND"
        and str(item.get("parameters", {}).get("minimum_drop_fraction")) in {"0.10", "0.1"}
    ]
    if (
        len(selected) != 3
        or len(set(focus_ids)) != 3
        or any(item not in eligible for item in selected)
    ):
        raise ValueError("R0-DIAG requires the three frozen focus combinations")

    event_sets: list[list[dict[str, Any]]] = [[] for _ in selected]
    ordered_symbols = sorted(symbols)
    for symbol in ordered_symbols:
        candles, funding = market_loader(symbol)
        for index, parameter in enumerate(selected):
            event_sets[index].extend(simulate_symbol_events(
                symbol,
                candles,
                funding,
                str(parameter["definition_id"]),
                parameter["parameters"],
                tier_at=tier_at,
                diagnostics_at=diagnostics_at,
                evaluation_start_ms=0,
                evaluation_end_ms=end_ms,
                round_trip_cost_pct_by_tier=costs,
                include_path_diagnostics=True,
            ))
    rows = []
    for parameter, events in zip(selected, event_sets):
        expected_count = int(parameter["summary"]["event_count"])
        expected_mean = float(parameter["summary"]["mean_net_return_pct"])
        actual_mean = _mean(events, "net_return_pct")
        if len(events) != expected_count or actual_mean is None or abs(actual_mean - expected_mean) > 1e-12:
            raise ValueError("R0-DIAG event reproduction differs from the frozen parameter report")
        rows.append({
            "parameter_id": parameter["parameter_id"],
            "family_id": parameter["family_id"],
            "definition_id": parameter["definition_id"],
            "parameters": parameter["parameters"],
            "event_count": len(events),
            "actual_mean_net_return_pct": actual_mean,
            "answers": summarize_path_answers(events),
            "scatter": [_scatter_row(event) for event in events],
        })
    return {
        "protocol": R0_DIAG_PROTOCOL,
        "purpose": "MEASURE_HUMAN_MANAGEMENT_POTENTIAL_WITHOUT_CHANGING_R0_VERDICT",
        "contract_sha256": context["contract_sha256"],
        "dataset_fingerprint": context["manifest"]["dataset_fingerprint"],
        "baseline_report_sha256": baseline_report_sha256,
        "baseline_verdict": baseline_report.get("verdict"),
        "lockbox_opened": False,
        "selection_or_gate_effect": "NONE",
        "focus": "OVERSOLD_REBOUND_MINIMUM_DROP_10_PERCENT",
        "parameter_reports": rows,
    }


def summarize_path_answers(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(events)
    profitable = [item for item in rows if float(item["net_return_pct"]) > 0]
    stopped = [item for item in rows if item["path_diagnostics"]["stopped"]]
    years: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in rows:
        years[str(item["entry_year_utc"])].append(item)
    return {
        "mfe_vs_actual_return": {
            "median_mfe_h_pct": _path_median(rows, "holding_h", "mfe_pct"),
            "median_mfe_2h_pct": _path_median(rows, "holding_2h", "mfe_pct"),
            "median_actual_net_return_pct": _median_value(rows, "net_return_pct"),
            "mean_actual_net_return_pct": _mean(rows, "net_return_pct"),
        },
        "mae_before_profitable_exit": {
            "profitable_event_count": len(profitable),
            "median_executed_mae_pct": _path_median(profitable, "executed", "mae_pct"),
            "share_mae_ge_1pct": _share_path(profitable, "executed", "mae_pct", 1.0),
            "share_mae_ge_2pct": _share_path(profitable, "executed", "mae_pct", 2.0),
            "share_mae_ge_2atr": _share_path(profitable, "executed", "mae_atr", 2.0),
        },
        "mfe_arrival": {
            "median_bar_h": _path_median(rows, "holding_h", "mfe_bar"),
            "p25_bar_h": _path_percentile(rows, "holding_h", "mfe_bar", 0.25),
            "p75_bar_h": _path_percentile(rows, "holding_h", "mfe_bar", 0.75),
            "median_bar_2h": _path_median(rows, "holding_2h", "mfe_bar"),
        },
        "stop_then_new_high": {
            "stopped_event_count": len(stopped),
            "observed_to_h_count": _count_boolean(stopped, "stop_then_new_mfe_h"),
            "share_of_stops_h": _share_boolean(stopped, "stop_then_new_mfe_h"),
            "observed_to_2h_count": _count_boolean(stopped, "stop_then_new_mfe_2h"),
            "share_of_stops_2h": _share_boolean(stopped, "stop_then_new_mfe_2h"),
        },
        "by_year": {
            year: {
                "event_count": len(items),
                "mean_actual_net_return_pct": _mean(items, "net_return_pct"),
                "median_mfe_h_pct": _path_median(items, "holding_h", "mfe_pct"),
                "median_mae_h_pct": _path_median(items, "holding_h", "mae_pct"),
                "median_mfe_2h_pct": _path_median(items, "holding_2h", "mfe_pct"),
                "median_mae_2h_pct": _path_median(items, "holding_2h", "mae_pct"),
                "stop_then_new_high_2h_share": _share_boolean(
                    [item for item in items if item["path_diagnostics"]["stopped"]],
                    "stop_then_new_mfe_2h",
                ),
            }
            for year, items in sorted(years.items())
        },
    }


def write_path_diagnostic_svgs(report: Mapping[str, Any], directory: Path) -> list[str]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for item in report["parameter_reports"]:
        short_id = hashlib.sha256(item["parameter_id"].encode()).hexdigest()[:10]
        scatter_path = directory / f"r0_diag_{short_id}_mfe_mae.svg"
        distribution_path = directory / f"r0_diag_{short_id}_distributions.svg"
        scatter_path.write_text(_scatter_svg(item), encoding="utf-8")
        distribution_path.write_text(_distribution_svg(item), encoding="utf-8")
        written.extend([str(scatter_path), str(distribution_path)])
    return written


def _scatter_row(event: Mapping[str, Any]) -> dict[str, Any]:
    path = event["path_diagnostics"]
    return {
        "symbol": event["symbol"], "entry_time_ms": event["entry_time_ms"],
        "entry_year_utc": event["entry_year_utc"], "exit_reason": event["exit_reason"],
        "net_return_pct": event["net_return_pct"],
        "mfe_h_pct": path["holding_h"]["mfe_pct"] if path["holding_h"] else None,
        "mae_h_pct": path["holding_h"]["mae_pct"] if path["holding_h"] else None,
        "mfe_2h_pct": path["holding_2h"]["mfe_pct"] if path["holding_2h"] else None,
        "mae_2h_pct": path["holding_2h"]["mae_pct"] if path["holding_2h"] else None,
        "mfe_bar_h": path["holding_h"]["mfe_bar"] if path["holding_h"] else None,
        "mae_bar_h": path["holding_h"]["mae_bar"] if path["holding_h"] else None,
        "mfe_bar_2h": path["holding_2h"]["mfe_bar"] if path["holding_2h"] else None,
        "mae_bar_2h": path["holding_2h"]["mae_bar"] if path["holding_2h"] else None,
        "stop_then_new_mfe_h": path["stop_then_new_mfe_h"],
        "stop_then_new_mfe_2h": path["stop_then_new_mfe_2h"],
    }


def _scatter_svg(item: Mapping[str, Any]) -> str:
    points = [row for row in item["scatter"] if row["mfe_2h_pct"] is not None]
    width, height, left, top, plot_w, plot_h = 960, 620, 82, 54, 820, 480
    max_x = max([float(row["mae_2h_pct"]) for row in points] + [1.0])
    max_y = max([float(row["mfe_2h_pct"]) for row in points] + [1.0])
    circles = []
    for row in points:
        x = left + min(float(row["mae_2h_pct"]) / max_x, 1) * plot_w
        y = top + plot_h - min(float(row["mfe_2h_pct"]) / max_y, 1) * plot_h
        color = "#ef6c75" if row["exit_reason"].startswith("STOP") else "#4ea1ff"
        circles.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2.2" fill="{color}" fill-opacity="0.38"/>')
    return _svg_shell(width, height, f"MFE / MAE 路径散点 · {item['parameter_id']}", f"MAE 2H (%)，最大 {max_x:.2f}", f"MFE 2H (%)，最大 {max_y:.2f}", "".join(circles), left, top, plot_w, plot_h)


def _distribution_svg(item: Mapping[str, Any]) -> str:
    points = [row for row in item["scatter"] if row["mfe_2h_pct"] is not None]
    width, height = 1120, 700
    excursion_metrics = [
        ("MFE H", [float(row["mfe_h_pct"]) for row in points], "#4ea1ff"),
        ("MFE 2H", [float(row["mfe_2h_pct"]) for row in points], "#76d5a6"),
        ("MAE H", [float(row["mae_h_pct"]) for row in points], "#f0b35a"),
        ("MAE 2H", [float(row["mae_2h_pct"]) for row in points], "#ef6c75"),
    ]
    arrival_metrics = [
        ("MFE 到达 K 线 H", [float(row["mfe_bar_h"]) for row in points], "#4ea1ff"),
        ("MFE 到达 K 线 2H", [float(row["mfe_bar_2h"]) for row in points], "#76d5a6"),
        ("MAE 到达 K 线 H", [float(row["mae_bar_h"]) for row in points], "#f0b35a"),
        ("MAE 到达 K 线 2H", [float(row["mae_bar_2h"]) for row in points], "#ef6c75"),
    ]
    bars = []
    _append_histogram_panel(
        bars, excursion_metrics, left=58, top=78, panel_width=500,
        bin_count=20, title="浮盈 / 浮亏幅度分布（%）",
    )
    _append_histogram_panel(
        bars, arrival_metrics, left=590, top=78, panel_width=500,
        bin_count=20, title="浮盈 / 浮亏到达时间分布（第几根 K 线）",
    )
    body = "".join(bars)
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="#0b1423"/><text x="48" y="34" fill="#f3f7ff" font-size="18" font-family="sans-serif">路径幅度与到达时间分布 · {item["parameter_id"]}</text>{body}</svg>\n'


def _append_histogram_panel(body, metrics, *, left, top, panel_width, bin_count, title):
    maximum = max([max(values) for _, values, _ in metrics if values] + [1.0])
    body.append(f'<text x="{left}" y="{top - 18}" fill="#c9d5e8" font-size="15">{title}</text>')
    body.append(f'<rect x="{left}" y="{top}" width="{panel_width}" height="530" fill="#0f1c2f" stroke="#2a3d59"/>')
    plot_left = left + 16
    bar_slot = (panel_width - 32) / bin_count
    for series, (label, values, color) in enumerate(metrics):
        counts = [0] * bin_count
        for value in values:
            counts[min(int(value / maximum * bin_count), bin_count - 1)] += 1
        max_count = max(counts + [1])
        baseline = top + 112 + series * 124
        body.append(f'<text x="{plot_left}" y="{baseline - 76}" fill="#c9d5e8" font-size="13">{label}</text>')
        for index, count in enumerate(counts):
            x = plot_left + index * bar_slot
            bar_height = count / max_count * 68
            body.append(f'<rect x="{x:.2f}" y="{baseline - bar_height:.2f}" width="{max(bar_slot - 3, 1):.2f}" height="{bar_height:.2f}" fill="{color}" fill-opacity="0.78"/>')
    unit = "%" if "%" in title else " 根"
    body.append(f'<text x="{plot_left}" y="{top + 516}" fill="#8393aa" font-size="12">横轴 0–{maximum:.2f}{unit}；每行纵轴独立归一化。</text>')


def _svg_shell(width, height, title, x_label, y_label, body, left, top, plot_w, plot_h):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="#0b1423"/><text x="48" y="30" fill="#f3f7ff" font-size="18" font-family="sans-serif">{title}</text><rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" fill="#0f1c2f" stroke="#2a3d59"/><line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#60728c"/><line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#60728c"/>{body}<text x="{left + plot_w / 2}" y="{height - 28}" text-anchor="middle" fill="#9badc4" font-size="13">{x_label}</text><text x="20" y="{top + plot_h / 2}" transform="rotate(-90 20 {top + plot_h / 2})" text-anchor="middle" fill="#9badc4" font-size="13">{y_label}</text><circle cx="710" cy="28" r="5" fill="#4ea1ff"/><text x="720" y="32" fill="#9badc4" font-size="12">时间退出</text><circle cx="810" cy="28" r="5" fill="#ef6c75"/><text x="820" y="32" fill="#9badc4" font-size="12">止损退出</text></svg>\n'


def _mean(rows, key):
    values = [float(item[key]) for item in rows]
    return sum(values) / len(values) if values else None


def _median_value(rows, key):
    values = [float(item[key]) for item in rows]
    return median(values) if values else None


def _path_values(rows, horizon, key):
    values = []
    for item in rows:
        path = item["path_diagnostics"].get(horizon)
        if path is not None:
            values.append(float(path[key]))
    return values


def _path_median(rows, horizon, key):
    values = _path_values(rows, horizon, key)
    return median(values) if values else None


def _path_percentile(rows, horizon, key, q):
    values = sorted(_path_values(rows, horizon, key))
    if not values:
        return None
    position = (len(values) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def _share_path(rows, horizon, key, threshold):
    values = _path_values(rows, horizon, key)
    return sum(value >= threshold for value in values) / len(values) if values else None


def _boolean_values(rows, key):
    return [item["path_diagnostics"][key] for item in rows if item["path_diagnostics"].get(key) is not None]


def _count_boolean(rows, key):
    return len(_boolean_values(rows, key))


def _share_boolean(rows, key):
    values = _boolean_values(rows, key)
    return sum(bool(value) for value in values) / len(values) if values else None
