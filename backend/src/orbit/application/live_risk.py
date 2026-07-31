from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Sequence


LIVE_SMALL_DRAWDOWN_LIMIT = Decimal("0.30")


def live_small_drawdown_projection(
    observations: Sequence[Mapping[str, Any]],
) -> dict[str, float | None]:
    """Project the two LIVE-SMALL drawdowns from the append-only equity series."""
    if not observations:
        return {
            "live_drawdown_pct": None,
            "paper_drawdown_pct": None,
            "stop_threshold_pct": float(LIVE_SMALL_DRAWDOWN_LIMIT * 100),
        }
    live = [Decimal(str(item["live_equity_usdt"])) for item in observations]
    paper = [Decimal(str(item["paper_equity"])) for item in observations]
    live_peak = max(live)
    paper_peak = max(paper)
    live_drawdown = (
        (live_peak - live[-1]) / live_peak
        if live_peak > 0 else Decimal("1")
    )
    paper_drawdown = (
        (paper_peak - paper[-1]) / paper_peak
        if paper_peak > 0 else Decimal("1")
    )
    return {
        "live_drawdown_pct": float(live_drawdown * 100),
        "paper_drawdown_pct": float(paper_drawdown * 100),
        "stop_threshold_pct": float(LIVE_SMALL_DRAWDOWN_LIMIT * 100),
    }


def live_small_drawdown_stop_reason(
    observations: Sequence[Mapping[str, Any]],
) -> str | None:
    if not observations:
        return "EQUITY_BASELINE_MISSING"
    projection = live_small_drawdown_projection(observations)
    live_pct = Decimal(str(projection["live_drawdown_pct"]))
    paper_pct = Decimal(str(projection["paper_drawdown_pct"]))
    threshold_pct = LIVE_SMALL_DRAWDOWN_LIMIT * 100
    if live_pct >= threshold_pct:
        return f"LIVE_DRAWDOWN_{float(live_pct):.4f}_PCT"
    if paper_pct >= threshold_pct:
        return f"PAPER_DRAWDOWN_{float(paper_pct):.4f}_PCT"
    return None
