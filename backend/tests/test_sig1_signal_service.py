from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from orbit.application.sig1_signal_service import Sig1SignalService
from orbit.application.signals.replay import SignalReplayService
from orbit.domain.calibration.r0_shortline import ShortlineCandle
from orbit.domain.signals.sig1 import detect_sig1_signals
from orbit.infrastructure.persistence.signal_ledger import AppendOnlySignalLedger
from backend.tools.run_sig1_signal_service import BinanceSig1Source


MS = 900_000
ROOT = Path(__file__).parents[2]


def spec():
    return json.loads((ROOT / "config/signals/sig1.v1.json").read_text(encoding="utf-8"))


def long_cycle(state="UP"):
    if state == "UP":
        closes = [100 + index * 0.1 for index in range(361)]
    elif state == "DOWN":
        closes = [200 - index * 0.1 for index in range(361)]
    else:
        closes = [100 + (index % 2) for index in range(361)]
    return [{"close": close} for close in closes]


def breakout_window(symbol: str, *, start_ms: int = 0, count: int = 101, stop_next=False):
    rows = []
    for index in range(count):
        price = 100 + index * 0.001
        rows.append(
            ShortlineCandle(
                open_time_ms=start_ms + index * MS,
                close_time_ms=start_ms + (index + 1) * MS - 1,
                open=price,
                high=price + 0.05,
                low=price - 0.05,
                close=price + 0.01,
                quote_volume=1_000,
            )
        )
    signal = rows[100]
    rows[100] = ShortlineCandle(
        signal.open_time_ms,
        signal.close_time_ms,
        100.1,
        111,
        100,
        110,
        5_000,
    )
    if stop_next:
        rows.append(
            ShortlineCandle(
                start_ms + 101 * MS,
                start_ms + 102 * MS - 1,
                110,
                110.1,
                80,
                90,
                1_000,
            )
        )
    return {
        "candles": rows,
        "daily_quote_volumes": [3_000_000] * 30,
        "long_cycle_candles": long_cycle(),
    }


def neutral_window(*, start_ms=0):
    rows = []
    for index in range(101):
        price = 100 + (index % 2) * 0.01
        rows.append(
            ShortlineCandle(
                start_ms + index * MS,
                start_ms + (index + 1) * MS - 1,
                price,
                price + 1,
                price - 1,
                price,
                1_000,
            )
        )
    return {"candles": rows, "daily_quote_volumes": [3_000_000] * 30, "long_cycle_candles": long_cycle("RANGE")}


def oversold_window(*, start_ms=0):
    window = neutral_window(start_ms=start_ms)
    rows = window["candles"]
    rows[84] = ShortlineCandle(rows[84].open_time_ms, rows[84].close_time_ms, 100, 101, 99, 100, 1_000)
    for index in range(85, 100):
        close = 99 - (index - 85) * 0.8
        rows[index] = ShortlineCandle(
            rows[index].open_time_ms, rows[index].close_time_ms,
            close + 0.2, close + 0.5, close - 0.5, close, 1_000,
        )
    rows[100] = ShortlineCandle(
        rows[100].open_time_ms, rows[100].close_time_ms, 87.9, 89.5, 87.5, 89, 1_000,
    )
    window["long_cycle_candles"] = long_cycle("UP")
    return window


def sustained_window(*, start_ms=0, count=1344):
    rows = []
    for index in range(count):
        price = 50 + index * 0.03
        volume = 2_000 if index >= count - 288 else 1_000
        rows.append(ShortlineCandle(start_ms + index * MS, start_ms + (index + 1) * MS - 1, price, price + 0.05, price - 0.05, price + 0.02, volume))
    return {"candles": rows, "daily_quote_volumes": [3_000_000] * 30, "long_cycle_candles": long_cycle("UP")}


class FakeNotifier:
    def __init__(self, failures=0):
        self.failures = failures
        self.messages = []

    def send(self, message):
        self.messages.append(message)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("injected delivery failure")
        return {"request_id": f"request-{len(self.messages)}"}


class FakeScanFeed:
    def closed_klines(self, symbol, interval, limit):
        return []


class FakeScanService:
    def required_symbols(self):
        return {"TRACKUSDT"}

    def process_closed_candle(self, windows, signal_close_time_ms, *, processed_at_ms):
        return {"processed_market_count": len(windows)}


class Sig1SignalServiceTests(unittest.TestCase):
    def test_replay_uses_live_detector_and_reports_same_signals(self):
        contract = spec()
        target = 101 * MS - 1
        windows = {"BREAKUSDT": breakout_window("BREAKUSDT"), "N1USDT": neutral_window(), "N2USDT": neutral_window()}
        direct = detect_sig1_signals(windows, target, contract)
        histories = {}
        for symbol, window in windows.items():
            cycle = [ShortlineCandle((index - 361) * 14_400_000, (index - 360) * 14_400_000 - 1, row["close"], row["close"], row["close"], row["close"], 1_000) for index, row in enumerate(window["long_cycle_candles"])]
            histories[symbol] = {"candles": window["candles"], "long_cycle": cycle, "daily": [(-index * 86_400_000 - 1, 3_000_000) for index in range(1, 31)]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.json").write_text(json.dumps({"dataset_cutoff_ms": target}), encoding="utf-8")
            replay = SignalReplayService(root)
            replay._load_histories = lambda *_args: histories
            result = replay.replay(contract, days=7, end_time_ms=target)
        replayed = {(row["symbol"], row["family_id"], row["signal_time_ms"]) for row in result["signals"]}
        expected = {(row["symbol"], row["family_id"], row["signal_time_ms"]) for row in direct}
        self.assertEqual(replayed, expected)

    def test_replay_reports_dataset_gap_without_silent_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.json").write_text(json.dumps({"dataset_cutoff_ms": 100}), encoding="utf-8")
            result = SignalReplayService(root).replay(spec(), days=7, end_time_ms=200)
        self.assertEqual(result["status"], "DATA_GAP")
        self.assertIn("只到", result["data_gap"])
        self.assertEqual(result["signals"], [])

    def test_scan_once_counts_tracked_symbols_without_list_set_type_error(self):
        source = BinanceSig1Source(FakeScanFeed(), spec(), FakeScanService(), clock=lambda: 1_000)
        source._universe_day = "1970-01-01"
        source._daily_volumes = {
            symbol: [3_000_000] * 30
            for symbol in ("AAAUSDT", "BBBUSDT", "CCCUSDT")
        }

        result = source.scan_once()

        self.assertEqual(result["qualified_market_count"], 3)
        self.assertEqual(result["tracked_trade_symbol_count"], 1)
        self.assertEqual(result["processed_market_count"], 4)

    def test_detector_matches_frozen_breakout_and_oversold_scope(self):
        target = 101 * MS - 1
        windows = {
            "BREAKUSDT": breakout_window("BREAKUSDT"),
            "DROPUSDT": oversold_window(),
            "NEUTRALUSDT": neutral_window(),
        }
        signals = detect_sig1_signals(windows, target, spec())
        identities = {(row["symbol"], row["family_id"], row["direction"]) for row in signals}
        self.assertIn(("BREAKUSDT", "BREAKOUT_MOMENTUM", "LONG"), identities)
        self.assertIn(("DROPUSDT", "OVERSOLD_REBOUND", "LONG"), identities)
        self.assertEqual(len(identities), 2)
        self.assertEqual(detect_sig1_signals(dict(list(windows.items())[:2]), target, spec()), [])

    def test_oversold_is_zero_in_down_and_range_long_cycle_states(self):
        contract = spec()
        contract["market"]["minimum_simultaneously_eligible_markets"] = 1
        for state in ("DOWN", "RANGE"):
            window = oversold_window()
            window["long_cycle_candles"] = long_cycle(state)
            found = detect_sig1_signals({"TUTUSDT": window}, 101 * MS - 1, contract)
            self.assertFalse(any(row["family_id"] == "OVERSOLD_REBOUND" for row in found))

    def test_tut_collapse_replay_suppresses_oversold_at_thirty_percent_drawdown(self):
        contract = spec()
        contract["market"]["minimum_simultaneously_eligible_markets"] = 1
        window = oversold_window()
        rows = window["candles"]
        rows[84] = ShortlineCandle(rows[84].open_time_ms, rows[84].close_time_ms, 100, 100, 99, 100, 1_000)
        for index in range(85, 100):
            close = 94 - (index - 85) * 1.8
            rows[index] = ShortlineCandle(rows[index].open_time_ms, rows[index].close_time_ms, close + 0.2, close + 0.5, close - 0.5, close, 1_000)
        rows[100] = ShortlineCandle(rows[100].open_time_ms, rows[100].close_time_ms, 69, 71, 68, 70, 1_000)
        found = detect_sig1_signals({"TUTUSDT": window}, 101 * MS - 1, contract)
        self.assertFalse(any(row["family_id"] == "OVERSOLD_REBOUND" for row in found))

    def test_high_pullback_requires_drop_to_start_within_fifteen_percent_of_high(self):
        contract = spec()
        contract["market"]["minimum_simultaneously_eligible_markets"] = 1
        window = oversold_window()
        rows = window["candles"]
        rows[0] = ShortlineCandle(rows[0].open_time_ms, rows[0].close_time_ms, 119, 120, 118, 119, 1_000)
        found = detect_sig1_signals({"TUTUSDT": window}, 101 * MS - 1, contract)
        self.assertFalse(any(row["family_id"] == "OVERSOLD_REBOUND" for row in found))

    def test_sustained_strength_emits_and_same_symbol_cools_down_for_24_hours(self):
        contract = spec()
        contract["market"]["minimum_simultaneously_eligible_markets"] = 1
        contract["signals"]["SUSTAINED_STRENGTH"]["trend_strength_minimum"] = "-999"
        contract["notifications"]["enabled"] = False
        first = sustained_window()
        close = 1344 * MS - 1
        with tempfile.TemporaryDirectory() as directory:
            ledger = self._ledger(directory)
            service = Sig1SignalService(contract, ledger)
            service.process_closed_candle({"ACEUSDT": first}, close, processed_at_ms=close + 1)
            second = sustained_window(start_ms=MS)
            service.process_closed_candle({"ACEUSDT": second}, close + MS, processed_at_ms=close + MS + 1)
            detected = [row["payload"]["signal"] for row in ledger.read_all() if row["payload"]["event_type"] == "SIGNAL_DETECTED" and row["payload"]["signal"]["family_id"] == "SUSTAINED_STRENGTH"]
            self.assertEqual(len(detected), 1)
            self.assertEqual(detected[0]["scope_version"], "SIG3_SCOPE_V1")

    def test_all_signals_create_trades_even_beyond_daily_30_scope(self):
        contract = spec()
        contract["notifications"]["enabled"] = False
        windows = {f"S{index:02d}USDT": breakout_window(f"S{index:02d}USDT") for index in range(35)}
        with tempfile.TemporaryDirectory() as directory:
            ledger = self._ledger(directory)
            service = Sig1SignalService(contract, ledger)
            service.process_closed_candle(windows, 101 * MS - 1, processed_at_ms=101 * MS)
            payloads = [row["payload"] for row in ledger.read_all()]
            self.assertEqual(sum(row["event_type"] == "SIGNAL_DETECTED" for row in payloads), 35)
            self.assertEqual(sum(row["event_type"] == "SIM_TRADE_PLANNED" for row in payloads), 35)
            scope = [row for row in payloads if row["event_type"] == "DAILY_SCOPE_RECONCILED"][-1]
            self.assertEqual(len(scope["included_signal_ids"]), 30)
            self.assertEqual(len(scope["truncated_signal_ids"]), 5)

    def test_push_cap_is_three_and_resets_for_next_signal_day(self):
        contract = spec()
        contract["notifications"]["trend_strength_minimum_by_family"] = {
            "BREAKOUT_MOMENTUM": "-999",
            "OVERSOLD_REBOUND": "-999",
        }
        notifier = FakeNotifier()
        with tempfile.TemporaryDirectory() as directory:
            ledger = self._ledger(directory)
            service = Sig1SignalService(contract, ledger, notifier)
            first = {f"A{index}USDT": breakout_window(f"A{index}USDT") for index in range(5)}
            service.process_closed_candle(first, 101 * MS - 1, processed_at_ms=101 * MS)
            second_start = 86_400_000
            second = {
                f"B{index}USDT": breakout_window(f"B{index}USDT", start_ms=second_start)
                for index in range(5)
            }
            service.process_closed_candle(
                second, second_start + 101 * MS - 1,
                processed_at_ms=second_start + 101 * MS,
            )
            payloads = [row["payload"] for row in ledger.read_all()]
            self.assertEqual(sum(row["event_type"] == "PUSH_SUCCEEDED" for row in payloads), 6)
            self.assertEqual(sum(row["event_type"] == "PUSH_SKIPPED_DAILY_CAP" for row in payloads), 4)

    def test_delivery_failure_does_not_block_ledger_and_retries(self):
        contract = spec()
        contract["notifications"]["trend_strength_minimum_by_family"]["BREAKOUT_MOMENTUM"] = "-999"
        notifier = FakeNotifier(failures=1)
        windows = {
            "ONEUSDT": breakout_window("ONEUSDT"),
            "N1USDT": neutral_window(),
            "N2USDT": neutral_window(),
        }
        with tempfile.TemporaryDirectory() as directory:
            ledger = self._ledger(directory)
            service = Sig1SignalService(contract, ledger, notifier)
            service.process_closed_candle(windows, 101 * MS - 1, processed_at_ms=101 * MS)
            payloads = [row["payload"] for row in ledger.read_all()]
            self.assertTrue(any(row["event_type"] == "SIGNAL_DETECTED" for row in payloads))
            self.assertTrue(any(row["event_type"] == "SIM_TRADE_PLANNED" for row in payloads))
            self.assertTrue(any(row["event_type"] == "PUSH_FAILED" for row in payloads))
            service.process_closed_candle(windows, 101 * MS - 1, processed_at_ms=101 * MS + 1)
            self.assertEqual(service.status()["push_success_count"], 1)

    def test_virtual_trade_opens_next_candle_and_stop_uses_worse_gap(self):
        contract = spec()
        contract["notifications"]["enabled"] = False
        initial = {
            "ONEUSDT": breakout_window("ONEUSDT"),
            "N1USDT": neutral_window(),
            "N2USDT": neutral_window(),
        }
        with tempfile.TemporaryDirectory() as directory:
            ledger = self._ledger(directory)
            service = Sig1SignalService(contract, ledger)
            service.process_closed_candle(initial, 101 * MS - 1, processed_at_ms=101 * MS)
            update = {"ONEUSDT": breakout_window("ONEUSDT", stop_next=True)}
            service.process_closed_candle(update, 102 * MS - 1, processed_at_ms=102 * MS)
            payloads = [row["payload"] for row in ledger.read_all()]
            opened = next(row for row in payloads if row["event_type"] == "SIM_TRADE_OPENED")
            closed = next(row for row in payloads if row["event_type"] == "SIM_TRADE_CLOSED")
            self.assertEqual(opened["entry_time_ms"], 101 * MS)
            self.assertEqual(closed["exit_reason"], "STOP")
            self.assertLessEqual(closed["exit_price"], opened["stop_price"])
            self.assertEqual(opened["scope_version"], "SIG3_SCOPE_V1")
            self.assertEqual(closed["scope_version"], "SIG3_SCOPE_V1")

    def test_virtual_trade_uses_frozen_32_candle_time_exit(self):
        contract = spec()
        contract["notifications"]["enabled"] = False
        initial = {
            "ONEUSDT": breakout_window("ONEUSDT"),
            "N1USDT": neutral_window(),
            "N2USDT": neutral_window(),
        }
        with tempfile.TemporaryDirectory() as directory:
            ledger = self._ledger(directory)
            service = Sig1SignalService(contract, ledger)
            service.process_closed_candle(initial, 101 * MS - 1, processed_at_ms=101 * MS)
            extended = breakout_window("ONEUSDT")
            rows = extended["candles"]
            for index in range(101, 134):
                rows.append(
                    ShortlineCandle(index * MS, (index + 1) * MS - 1, 110, 110.1, 109.9, 110, 1_000)
                )
            service.process_closed_candle(
                {"ONEUSDT": extended}, 134 * MS - 1, processed_at_ms=134 * MS
            )
            closed = next(
                row["payload"] for row in ledger.read_all()
                if row["payload"]["event_type"] == "SIM_TRADE_CLOSED"
            )
            self.assertEqual(closed["exit_reason"], "TIME_EXIT")
            self.assertEqual(closed["exit_time_ms"], 133 * MS)

    def test_stop_precedes_time_exit_on_same_candle(self):
        trade = {
            "direction": "LONG",
            "opened": {
                "entry_time_ms": 0,
                "entry_price": 100.0,
                "initial_risk_price": 5.0,
                "stop_price": 95.0,
                "time_exit_open_time_ms": MS,
            },
        }
        candles = [
            ShortlineCandle(MS, 2 * MS - 1, 100, 101, 94, 98, 1_000),
        ]
        result = Sig1SignalService._virtual_exit(trade, candles)
        self.assertEqual(result["exit_reason"], "STOP")
        self.assertEqual(result["exit_price"], 95.0)

    def test_ledger_restart_recovers_and_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = self._ledger(directory)
            ledger.append({"event_type": "TEST", "recorded_at_ms": 1})
            restarted = AppendOnlySignalLedger(Path(directory))
            restarted.open({"protocol": "TEST", "spec_sha256": "abc"})
            self.assertEqual(restarted.status()["event_count"], 1)
            path = Path(directory) / "events.jsonl"
            path.write_text(path.read_text(encoding="utf-8").replace('"TEST"', '"TAMPER"'), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "fingerprint mismatch"):
                restarted.read_all()

    def test_frozen_contract_contains_no_plaintext_credentials_and_binds_rc0b(self):
        contract = spec()
        rc0b = ROOT / "docs/evidence/rc0/rc0b_volume_curve_v1_20260814.json"
        import hashlib

        self.assertEqual(contract["source_rc0b_report_sha256"], hashlib.sha256(rc0b.read_bytes()).hexdigest())
        self.assertEqual(contract["market"]["liquidity"]["minimum_median_daily_quote_volume_usdt"], 2_000_000)
        self.assertEqual(contract["market"]["liquidity"]["lookback_complete_utc_days"], 30)
        self.assertEqual(contract["signals"]["BREAKOUT_MOMENTUM"]["channel_lookback_candles"], 32)
        self.assertEqual(contract["signals"]["BREAKOUT_MOMENTUM"]["minimum_relative_quote_volume"], "2.0")
        self.assertEqual(contract["signals"]["OVERSOLD_REBOUND"]["required_long_cycle_state"], "UP")
        self.assertEqual(contract["signals"]["OVERSOLD_REBOUND"]["maximum_drawdown_from_high"], "0.30")
        self.assertEqual(contract["signals"]["OVERSOLD_REBOUND"]["pullback_start_high_lookback_days"], 3)
        self.assertEqual(contract["signals"]["OVERSOLD_REBOUND"]["maximum_start_drawdown_from_high"], "0.15")
        self.assertEqual(contract["signals"]["SUSTAINED_STRENGTH"]["trend_strength_quantile"], "0.90")
        self.assertIn("SUSTAINED_STRENGTH", contract["signals"])
        self.assertEqual(contract["workload"]["daily_candidate_limit"], 30)
        self.assertEqual(contract["event_stream_source"], "EVERY_COMPLETED_15M_CANDLE")
        self.assertFalse(
            contract["historical_reference"]["runtime_reuses_research_position_suppression"]
        )
        self.assertEqual(contract["notifications"]["daily_success_limit"], 3)
        self.assertTrue(contract["notifications"]["api_token_reference"].startswith("env:"))
        self.assertTrue(contract["notifications"]["user_key_reference"].startswith("env:"))
        report = json.loads(rc0b.read_text(encoding="utf-8"))
        families = {row["family_id"]: row for row in report["family_reports"]}
        breakout = next(
            row for row in families["BREAKOUT_MOMENTUM"]["combinations"]
            if row["liquidity_threshold_usdt"] == 200_000_000
            and row["channel_lookback_candles"] == 32
            and row["minimum_relative_quote_volume"] == 4.0
        )
        oversold = next(
            row for row in families["OVERSOLD_REBOUND"]["combinations"]
            if row["liquidity_threshold_usdt"] == 200_000_000
        )
        self.assertEqual(breakout["frequency"]["event_count"], 29_311)
        self.assertEqual(oversold["frequency"]["event_count"], 9_183)
        evidence = json.loads(
            (ROOT / "docs/evidence/sig1/sig1_scope_replay_20260814.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(evidence["rc0b_reference_event_counts"], {
            "BREAKOUT_MOMENTUM": 29_311,
            "OVERSOLD_REBOUND": 9_183,
        })
        self.assertTrue(evidence["reference_count_match"])
        self.assertEqual(evidence["runtime_event_stream_source"], "EVERY_COMPLETED_15M_CANDLE")
        self.assertFalse(evidence["runtime_reuses_research_position_suppression"])
        self.assertTrue(evidence["threshold_match"])
        self.assertFalse(evidence["lockbox_opened"])
        self.assertFalse(evidence["lockbox_data_read"])

    @staticmethod
    def _ledger(directory):
        ledger = AppendOnlySignalLedger(Path(directory))
        ledger.open({"protocol": "TEST", "spec_sha256": "abc"})
        return ledger


if __name__ == "__main__":
    unittest.main()
