from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import sys
import tempfile
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.domain.calibration.history import FundingPoint
from orbit.domain.calibration.r0_shortline import (
    HistoricalUniverseResolver,
    ShortlineCandle,
    apply_gates,
    breakout_direction,
    daily_block_bootstrap_interval,
    frozen_parameter_grid,
    oversold_direction,
    measure_event_path,
    select_training_candidates,
    simple_atr,
    simulate_symbol_events,
    summarize_events,
)
from orbit.domain.calibration.shortline_dataset import DAY_MS, RAW_INTERVAL_MS
from orbit.application.r0_shortline_screen import (
    R0ScreenError,
    lockbox_report,
    training_report,
    validate_training_report,
    verify_frozen_context,
)

sys.path.insert(0, str(BACKEND_ROOT / "tools"))
from screen_r0_shortline import claim_lockbox_once


ROOT = BACKEND_ROOT.parent
CONTRACT = json.loads(
    (ROOT / "config" / "research" / "r0_shortline_screen.v2.json").read_text(
        encoding="utf-8"
    )
)


def candles(closes, *, start=0, opens=None, highs=None, lows=None, volumes=None):
    opens = opens or closes
    highs = highs or [max(open_, close) for open_, close in zip(opens, closes)]
    lows = lows or [min(open_, close) for open_, close in zip(opens, closes)]
    volumes = volumes or [100.0] * len(closes)
    return [
        ShortlineCandle(
            start + index * RAW_INTERVAL_MS,
            start + (index + 1) * RAW_INTERVAL_MS - 1,
            float(opens[index]), float(highs[index]), float(lows[index]),
            float(close), float(volumes[index]),
        )
        for index, close in enumerate(closes)
    ]


def event(value, *, day="2024-01-01", year=2024, tier="HIGH", symbol="A"):
    return {
        "entry_day_utc": day,
        "entry_year_utc": year,
        "tier": tier,
        "symbol": symbol,
        "net_return_pct": value,
    }


class R0ShortlineEstimatorTests(unittest.TestCase):
    def test_machine_contract_expands_to_exactly_two_frozen_eight_item_grids(self):
        grid = frozen_parameter_grid(CONTRACT)

        self.assertEqual(len(grid), 16)
        self.assertEqual(sum(item["family_id"] == "BREAKOUT_MOMENTUM" for item in grid), 8)
        self.assertEqual(sum(item["family_id"] == "OVERSOLD_REBOUND" for item in grid), 8)

    def test_breakout_channel_and_relative_volume_exclude_current_candle(self):
        rows = candles(
            [99.0, 99.0, 101.0],
            highs=[100.0, 100.0, 102.0],
            lows=[98.0, 98.0, 99.0],
            volumes=[1.0, 100.0, 100.0],
        )

        self.assertEqual(breakout_direction(
            rows, 2, channel_lookback=2, volume_lookback=2,
            minimum_relative_volume=1.5,
        ), 1)

    def test_oversold_drop_and_stabilization_have_frozen_direction(self):
        rows = candles([100.0, 94.0, 95.0], opens=[100.0, 95.0, 94.5])

        self.assertEqual(oversold_direction(
            rows, 2, return_lookback=2, minimum_drop_fraction=0.05,
        ), 1)
        falling = candles([100.0, 96.0, 94.0], opens=[100.0, 97.0, 95.0])
        self.assertEqual(oversold_direction(
            falling, 2, return_lookback=2, minimum_drop_fraction=0.05,
        ), 0)

    def test_next_open_entry_and_open_after_complete_holding_candles_exit(self):
        rows = self._oversold_fixture(exit_open=103.0)
        result = simulate_symbol_events(
            "TESTUSDT", rows, [], "S1_DROP_STABILIZATION",
            {"return_lookback_candles": 16, "minimum_drop_fraction": "0.05", "holding_candles": 2},
            tier_at=lambda *_: "HIGH", evaluation_start_ms=0,
            evaluation_end_ms=rows[-1].close_time_ms,
            round_trip_cost_pct_by_tier={"HIGH": 0.16},
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["entry_price"], rows[18].open)
        self.assertEqual(result[0]["exit_price"], rows[20].open)
        self.assertEqual(result[0]["entry_time_ms"], rows[18].open_time_ms)
        self.assertEqual(result[0]["exit_time_ms"], rows[20].open_time_ms)

    def test_simple_atr_and_gap_stop_use_worse_open(self):
        rows = self._oversold_fixture(exit_open=100.0)
        rows[18] = deepcopy(rows[18])
        rows[19] = ShortlineCandle(
            rows[19].open_time_ms, rows[19].close_time_ms,
            80.0, 82.0, 79.0, 81.0, 100.0,
        )
        result = simulate_symbol_events(
            "TESTUSDT", rows, [], "S1_DROP_STABILIZATION",
            {"return_lookback_candles": 16, "minimum_drop_fraction": "0.05", "holding_candles": 2},
            tier_at=lambda *_: "HIGH", evaluation_start_ms=0,
            evaluation_end_ms=rows[-1].close_time_ms,
            round_trip_cost_pct_by_tier={"HIGH": 0.16},
        )

        self.assertGreater(simple_atr(rows, 17), 0)
        self.assertEqual(result[0]["exit_reason"], "STOP_GAP")
        self.assertEqual(result[0]["exit_price"], 80.0)

    def test_path_diagnostic_measures_h_and_2h_without_changing_event_return(self):
        rows = self._oversold_fixture(exit_open=103.0)
        rows += candles(
            [106.0, 108.0, 104.0, 102.0],
            start=len(rows) * RAW_INTERVAL_MS,
            opens=[103.0, 106.0, 108.0, 104.0],
            highs=[107.0, 110.0, 109.0, 105.0],
            lows=[102.0, 105.0, 103.0, 101.0],
        )
        args = dict(
            tier_at=lambda *_: "HIGH", evaluation_start_ms=0,
            evaluation_end_ms=rows[-1].close_time_ms,
            round_trip_cost_pct_by_tier={"HIGH": 0.16},
        )
        plain = simulate_symbol_events(
            "TESTUSDT", rows, [], "S1_DROP_STABILIZATION",
            {"return_lookback_candles": 16, "minimum_drop_fraction": "0.05", "holding_candles": 2},
            **args,
        )[0]
        diagnosed = simulate_symbol_events(
            "TESTUSDT", rows, [], "S1_DROP_STABILIZATION",
            {"return_lookback_candles": 16, "minimum_drop_fraction": "0.05", "holding_candles": 2},
            include_path_diagnostics=True, **args,
        )[0]

        self.assertEqual(
            {key: value for key, value in diagnosed.items() if key != "path_diagnostics"},
            plain,
        )
        self.assertGreater(
            diagnosed["path_diagnostics"]["holding_2h"]["mfe_pct"],
            diagnosed["path_diagnostics"]["holding_h"]["mfe_pct"],
        )
        self.assertEqual(diagnosed["path_diagnostics"]["holding_2h"]["mfe_bar"], 4)

    def test_stop_path_is_truncated_but_counterfactual_detects_later_new_high(self):
        rows = candles(
            [100.0, 98.0, 90.0, 112.0],
            opens=[100.0, 100.0, 90.0, 91.0],
            highs=[101.0, 101.0, 92.0, 115.0],
            lows=[99.0, 97.0, 85.0, 90.0],
        )
        result = measure_event_path(
            rows,
            entry_index=0,
            holding_candles=2,
            direction=1,
            entry_price=100.0,
            atr=5.0,
            stop_price=90.0,
            exit_reason="STOP_GAP",
            exit_time_ms=rows[1].open_time_ms,
            evaluation_end_ms=rows[-1].close_time_ms,
        )

        self.assertEqual(result["stop_bar"], 2)
        self.assertLess(result["executed"]["mfe_pct"], result["holding_2h"]["mfe_pct"])
        self.assertTrue(result["stop_then_new_mfe_2h"])

    def test_2h_path_is_null_when_observation_crosses_available_boundary(self):
        rows = candles([100.0, 101.0, 102.0])
        result = measure_event_path(
            rows,
            entry_index=0,
            holding_candles=2,
            direction=1,
            entry_price=100.0,
            atr=1.0,
            stop_price=98.0,
            exit_reason="TIME",
            exit_time_ms=rows[2].open_time_ms,
            evaluation_end_ms=rows[-1].close_time_ms,
        )

        self.assertIsNotNone(result["holding_h"])
        self.assertIsNone(result["holding_2h"])

    def test_same_symbol_events_do_not_overlap(self):
        rows = self._oversold_fixture(exit_open=100.0) + self._oversold_fixture(
            exit_open=100.0, start=21 * RAW_INTERVAL_MS,
        )
        result = simulate_symbol_events(
            "TESTUSDT", rows, [], "S1_DROP_STABILIZATION",
            {"return_lookback_candles": 16, "minimum_drop_fraction": "0.05", "holding_candles": 2},
            tier_at=lambda *_: "HIGH", evaluation_start_ms=0,
            evaluation_end_ms=rows[-1].close_time_ms,
            round_trip_cost_pct_by_tier={"HIGH": 0.16},
        )

        for previous, current in zip(result, result[1:]):
            self.assertGreaterEqual(current["signal_time_ms"], previous["exit_time_ms"])

    def test_event_is_discarded_when_required_candle_sequence_has_a_gap(self):
        rows = self._oversold_fixture(exit_open=100.0)
        del rows[5]

        result = simulate_symbol_events(
            "TESTUSDT", rows, [], "S1_DROP_STABILIZATION",
            {"return_lookback_candles": 16, "minimum_drop_fraction": "0.05", "holding_candles": 2},
            tier_at=lambda *_: "HIGH", evaluation_start_ms=0,
            evaluation_end_ms=rows[-1].close_time_ms,
            round_trip_cost_pct_by_tier={"HIGH": 0.16},
        )

        self.assertEqual(result, [])

    def test_v2_universe_uses_all_qualified_contracts_and_dynamic_thirds(self):
        symbols = ["AUSDT", "BUSDT", "CUSDT", "DUSDT", "EUSDT"]
        contracts = [self._contract(symbol, listed_at_ms=0) for symbol in symbols]
        daily_values = {
            "AUSDT": [10, 60, 70, 80],
            "BUSDT": [10, 50, 50, 60],
            "CUSDT": [10, 40, 35, 31],
            "DUSDT": [10, 32, 31, 30],
            "EUSDT": [10, 30, 30, 30],
        }
        liquidity = {
            symbol: self._liquidity_rows(values) for symbol, values in daily_values.items()
        }
        resolver = self._v2_resolver(contracts, liquidity)
        signal_time = 4 * DAY_MS

        self.assertEqual([resolver.tier_at(symbol, signal_time) for symbol in symbols], [
            "HIGH", "HIGH", "MEDIUM", "MEDIUM", "LOW",
        ])
        self.assertEqual(
            resolver.diagnostics_at("AUSDT", signal_time),
            {"volume_trend_3d": "STRICTLY_INCREASING", "listing_age": "LE_30_DAYS"},
        )
        self.assertEqual(
            resolver.diagnostics_at("BUSDT", signal_time)["volume_trend_3d"],
            "NOT_STRICTLY_INCREASING",
        )

    def test_v2_universe_excludes_entire_snapshot_when_fewer_than_three_qualify(self):
        symbols = ["AUSDT", "BUSDT"]
        contracts = [self._contract(symbol, listed_at_ms=0) for symbol in symbols]
        liquidity = {symbol: self._liquidity_rows([10, 40, 50, 60]) for symbol in symbols}
        resolver = self._v2_resolver(contracts, liquidity)

        self.assertIsNone(resolver.tier_at("AUSDT", 4 * DAY_MS))
        self.assertIsNone(resolver.tier_at("BUSDT", 4 * DAY_MS))

    def test_v2_universe_has_no_30_day_listing_filter_and_honors_delisting(self):
        symbols = ["NEWUSDT", "BUSDT", "CUSDT"]
        contracts = [self._contract(symbol, listed_at_ms=0) for symbol in symbols]
        contracts[0]["delisted_at_ms"] = 5 * DAY_MS
        contracts[0]["status"] = "DELISTED"
        liquidity = {symbol: self._liquidity_rows([10, 40, 50, 60, 70]) for symbol in symbols}
        resolver = self._v2_resolver(contracts, liquidity)

        self.assertIsNotNone(resolver.tier_at("NEWUSDT", 4 * DAY_MS))
        self.assertIsNone(resolver.tier_at("NEWUSDT", 5 * DAY_MS))

    def test_funding_boundaries_signs_and_tier_costs(self):
        rows = self._oversold_fixture(exit_open=103.0)
        entry = rows[18].open_time_ms
        exit_ = rows[20].open_time_ms
        funding = [
            FundingPoint(entry, 0.10),
            FundingPoint(entry + 1, 0.001),
            FundingPoint(exit_, 0.002),
            FundingPoint(exit_ + 1, 0.10),
        ]
        high = simulate_symbol_events(
            "TESTUSDT", rows, funding, "S1_DROP_STABILIZATION",
            {"return_lookback_candles": 16, "minimum_drop_fraction": "0.05", "holding_candles": 2},
            tier_at=lambda *_: "HIGH", evaluation_start_ms=0,
            evaluation_end_ms=rows[-1].close_time_ms,
            round_trip_cost_pct_by_tier={"HIGH": 0.16},
        )[0]
        low = simulate_symbol_events(
            "TESTUSDT", rows, funding, "S1_DROP_STABILIZATION",
            {"return_lookback_candles": 16, "minimum_drop_fraction": "0.05", "holding_candles": 2},
            tier_at=lambda *_: "LOW", evaluation_start_ms=0,
            evaluation_end_ms=rows[-1].close_time_ms,
            round_trip_cost_pct_by_tier={"LOW": 0.40},
        )[0]
        medium = simulate_symbol_events(
            "TESTUSDT", rows, funding, "S1_DROP_STABILIZATION",
            {"return_lookback_candles": 16, "minimum_drop_fraction": "0.05", "holding_candles": 2},
            tier_at=lambda *_: "MEDIUM", evaluation_start_ms=0,
            evaluation_end_ms=rows[-1].close_time_ms,
            round_trip_cost_pct_by_tier={"MEDIUM": 0.25},
        )[0]

        self.assertAlmostEqual(high["funding_return_pct"], -0.3)
        self.assertAlmostEqual(medium["cost_pct"], 0.25)
        self.assertAlmostEqual(high["net_return_pct"] - low["net_return_pct"], 0.24)

    def test_short_position_receives_positive_funding(self):
        rows = candles(
            [100.0] * 96 + [90.0, 90.0, 89.0],
            opens=[100.0] * 96 + [95.0, 90.0, 89.0],
            highs=[101.0] * 96 + [96.0, 91.0, 90.0],
            lows=[99.0] * 96 + [89.0, 89.0, 88.0],
            volumes=[100.0] * 96 + [200.0, 100.0, 100.0],
        )
        entry = rows[97].open_time_ms
        exit_ = rows[98].open_time_ms
        result = simulate_symbol_events(
            "TESTUSDT", rows, [FundingPoint(entry + 1, 0.001), FundingPoint(exit_, 0.002)],
            "B1_DONCHIAN_VOLUME",
            {"channel_lookback_candles": 32, "minimum_relative_quote_volume": "1.5", "holding_candles": 1},
            tier_at=lambda *_: "HIGH", evaluation_start_ms=0,
            evaluation_end_ms=rows[-1].close_time_ms,
            round_trip_cost_pct_by_tier={"HIGH": 0.16},
        )

        self.assertEqual(result[0]["direction"], "SHORT")
        self.assertAlmostEqual(result[0]["funding_return_pct"], 0.3)

    def test_utc_day_block_bootstrap_is_reproducible_and_keeps_day_blocks(self):
        rows = [
            event(10, day="2024-01-01"), event(-10, day="2024-01-01"),
            event(2, day="2024-01-02"),
        ]

        first = daily_block_bootstrap_interval(rows, samples=200, seed=7)
        second = daily_block_bootstrap_interval(rows, samples=200, seed=7)
        ungrouped = [dict(item, entry_day_utc=f"day-{index}") for index, item in enumerate(rows)]
        self.assertEqual(first, second)
        self.assertNotEqual(first, daily_block_bootstrap_interval(ungrouped, samples=200, seed=7))

    def test_summary_outputs_each_tier_year_symbol_and_honest_gate(self):
        rows = [
            event(1, tier=tier, symbol=symbol, year=year, day=f"{year}-01-{day:02d}")
            for year in (2022, 2023, 2024)
            for tier in ("HIGH", "MEDIUM", "LOW")
            for symbol in ("A", "B")
            for day in range(1, 3)
        ]
        summary = summarize_events(rows, bootstrap_samples=50)
        gates = deepcopy(CONTRACT["statistics"]["training_gates"])
        gates.update({
            "minimum_events_total": 1, "minimum_events_per_tier": 1,
            "minimum_distinct_symbols": 1, "minimum_calendar_years_with_100_events": 3,
        })

        self.assertEqual(set(summary["by_tier"]), {"HIGH", "MEDIUM", "LOW"})
        self.assertEqual(set(summary["by_year"]), {"2022", "2023", "2024"})
        self.assertEqual(set(summary["by_symbol"]), {"A", "B"})
        self.assertTrue(apply_gates(summary, gates)["passed"])

    def test_candidate_selection_uses_frozen_order_and_training_fail_is_none(self):
        base = {
            "family_id": "BREAKOUT_MOMENTUM", "definition_id": "B1_DONCHIAN_VOLUME",
            "parameters": {"holding_candles": 16},
            "summary": {"bootstrap_mean_ci_low": 0.1, "mean_net_return_pct": 0.2, "event_count": 600},
            "gate": {"passed": True},
        }
        better = deepcopy(base)
        better["parameters"] = {"holding_candles": 32}
        better["summary"]["bootstrap_mean_ci_low"] = 0.2
        failed = deepcopy(base)
        failed["family_id"] = "OVERSOLD_REBOUND"
        failed["gate"] = {"passed": False}

        selected = select_training_candidates([base, better, failed])

        self.assertEqual(selected["BREAKOUT_MOMENTUM"]["parameters"], {"holding_candles": 32})
        self.assertIsNone(selected["OVERSOLD_REBOUND"])

    def test_context_mismatch_fails_before_any_estimator_data_read(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec = root / "spec.json"
            spec.write_bytes(
                (ROOT / "config" / "research" / "r0_shortline_screen.v2.json").read_bytes()
            )
            dataset = root / "dataset"
            dataset.mkdir()
            (dataset / "manifest.json").write_text(json.dumps({
                "protocol": "ORBIT_SHORTLINE_DATASET_V1", "entries": [],
                "dataset_fingerprint": "wrong",
            }), encoding="utf-8")
            (dataset / "quality_report.json").write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(R0ScreenError, "dataset contract mismatch"):
                verify_frozen_context(spec, dataset)

    def test_training_failure_does_not_call_lockbox_market_loader(self):
        failed_report = self._failed_training_report()
        called = []

        with self.assertRaisesRegex(R0ScreenError, "must not be read"):
            lockbox_report(
                self._context(), failed_report, ["TESTUSDT"],
                lambda symbol: called.append(symbol),
                tier_at=lambda *_: "HIGH", bootstrap_samples=10,
            )

        self.assertEqual(called, [])

    def test_training_orchestrator_reports_every_frozen_parameter_without_lockbox(self):
        context = self._context()
        rows = self._oversold_fixture(exit_open=103.0)
        report = training_report(
            context,
            ["TESTUSDT"],
            lambda _: (rows, []),
            tier_at=lambda *_: "HIGH",
            diagnostics_at=lambda *_: {
                "volume_trend_3d": "NOT_STRICTLY_INCREASING",
                "listing_age": "LE_30_DAYS",
            },
            bootstrap_samples=10,
        )

        self.assertEqual(report["phase"], "TRAINING")
        self.assertEqual(len(report["parameter_reports"]), 16)
        self.assertEqual(report["verdict"], "TRAINING_FAIL")
        self.assertEqual(report["lockbox_authorized_families"], [])
        for item in report["parameter_reports"]:
            self.assertIn("by_tier", item["summary"])
            self.assertIn("by_year", item["summary"])
            self.assertIn("by_symbol", item["summary"])
            self.assertIn("by_volume_trend_3d", item["summary"])
            self.assertIn("by_listing_age", item["summary"])

    def test_v2_missing_event_diagnostics_fail_closed(self):
        context = self._context()
        rows = self._oversold_fixture(exit_open=103.0)
        rows += candles([103.0] * 20, start=len(rows) * RAW_INTERVAL_MS)

        with self.assertRaisesRegex(R0ScreenError, "diagnostic is missing or invalid"):
            training_report(
                context,
                ["TESTUSDT"],
                lambda _: (rows, []),
                tier_at=lambda *_: "HIGH",
                diagnostics_at=lambda *_: None,
                bootstrap_samples=10,
            )

    def test_ui_progress_checkpoints_resume_and_match_fresh_training(self):
        context = self._context()
        rows = self._oversold_fixture(exit_open=103.0)
        rows += candles([103.0] * 20, start=len(rows) * RAW_INTERVAL_MS)
        diagnostics = lambda *_: {
            "volume_trend_3d": "NOT_STRICTLY_INCREASING",
            "listing_age": "LE_30_DAYS",
        }
        progress = []
        calls = []
        with tempfile.TemporaryDirectory() as temp:
            checkpoint = Path(temp)
            first = training_report(
                context, ["TESTUSDT"],
                lambda symbol: (calls.append(symbol) or (rows, [])),
                tier_at=lambda *_: "HIGH", diagnostics_at=diagnostics,
                bootstrap_samples=10, progress_callback=progress.append,
                checkpoint_dir=checkpoint,
            )
            second = training_report(
                context, ["TESTUSDT"],
                lambda symbol: self.fail(f"checkpoint did not resume: {symbol}"),
                tier_at=lambda *_: "HIGH", diagnostics_at=diagnostics,
                bootstrap_samples=10, checkpoint_dir=checkpoint,
            )

        self.assertEqual(calls, ["TESTUSDT"])
        self.assertEqual(first, second)
        self.assertTrue(any(item.get("completed_symbols") == 1 for item in progress))
        self.assertEqual(
            [item["completed_combinations"] for item in progress if item["phase"] == "evaluate"],
            list(range(1, 17)),
        )

    def test_tampered_training_selection_is_rejected(self):
        report = self._failed_training_report()
        report["selected_candidates"]["OVERSOLD_REBOUND"] = {
            "family_id": "OVERSOLD_REBOUND", "definition_id": "S1_DROP_STABILIZATION",
            "parameters": {}, "parameter_id": "forged",
        }

        with self.assertRaisesRegex(R0ScreenError, "selection was changed"):
            validate_training_report(self._context(), report)

    def test_lockbox_marker_can_only_be_created_once(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "opened.json"
            claim_lockbox_once(marker, {"dataset_fingerprint": "frozen"})

            with self.assertRaisesRegex(R0ScreenError, "already been opened"):
                claim_lockbox_once(marker, {"dataset_fingerprint": "frozen"})

    @staticmethod
    def _contract(symbol, *, listed_at_ms):
        return {
            "symbol": symbol,
            "listed_at_ms": listed_at_ms,
            "first_open_time_ms": listed_at_ms,
            "last_close_time_ms": 100 * DAY_MS,
            "delisted_at_ms": None,
            "status": "TRADING",
            "status_method": "TEST",
            "history_complete": True,
        }

    @staticmethod
    def _liquidity_rows(values):
        return [{
            "day_open_time_ms": day * DAY_MS,
            "day_close_time_ms": (day + 1) * DAY_MS - 1,
            "status": "COMPLETE",
            "quote_volume": str(value * 1_000_000),
        } for day, value in enumerate(values)]

    @staticmethod
    def _v2_resolver(contracts, liquidity):
        return HistoricalUniverseResolver(
            contracts,
            liquidity,
            min_history_days=0,
            liquidity_lookback_days=3,
            minimum_volume="30000000",
            limit=None,
            tiering={
                "method": "DYNAMIC_EQUAL_THIRDS_BY_LIQUIDITY_RANK",
                "ordered_tiers": ["HIGH", "MEDIUM", "LOW"],
                "remainder_allocation": "HIGH_THEN_MEDIUM",
                "minimum_qualified_contracts": 3,
                "insufficient_qualified_contracts_policy": "EXCLUDE_ENTIRE_SNAPSHOT",
            },
        )

    @staticmethod
    def _context():
        return {
            "contract": CONTRACT,
            "contract_sha256": "contract",
            "manifest": {"dataset_fingerprint": "dataset", "quality_report_sha256": "quality"},
        }

    @classmethod
    def _failed_training_report(cls):
        failed = {
            "family_id": "OVERSOLD_REBOUND", "definition_id": "S1_DROP_STABILIZATION",
            "parameters": {"holding_candles": 8}, "parameter_id": "failed",
            "summary": {"bootstrap_mean_ci_low": -1, "mean_net_return_pct": -1, "event_count": 0},
            "gate": {"passed": False},
        }
        return {
            "protocol": "ORBIT_R0_SHORTLINE_SCREEN_V2", "phase": "TRAINING",
            "contract_sha256": "contract", "dataset_fingerprint": "dataset",
            "parameter_reports": [failed],
            "selected_candidates": {"OVERSOLD_REBOUND": None},
        }

    @staticmethod
    def _oversold_fixture(exit_open, start=0):
        closes = [100.0] * 16 + [94.0, 95.0, 96.0, 97.0, exit_open]
        opens = [100.0] * 16 + [95.0, 94.5, 96.0, 97.0, exit_open]
        highs = [value + 0.5 for value in map(max, zip(opens, closes))]
        lows = [value - 0.5 for value in map(min, zip(opens, closes))]
        return candles(closes, start=start, opens=opens, highs=highs, lows=lows)


if __name__ == "__main__":
    unittest.main()
