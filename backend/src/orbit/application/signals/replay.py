from __future__ import annotations

from bisect import bisect_right
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import statistics
from typing import Any

from orbit.application.sig1_signal_service import Sig1SignalService
from orbit.domain.calibration.r0_shortline import ShortlineCandle
from orbit.domain.signals.sig1 import daily_workload_scope, detect_sig1_signals
from orbit.infrastructure.market_data.binance_public_archive import iter_kline_zip


DAY_MS = 86_400_000
INTERVAL_MS = 900_000


class SignalReplayService:
    def __init__(self, dataset_root: Path):
        self.dataset_root = dataset_root

    def replay(self, spec: dict[str, Any], *, days: int, end_time_ms: int) -> dict[str, Any]:
        start_time_ms = end_time_ms - days * DAY_MS + 1
        manifest_path = self.dataset_root / "manifest.json"
        if not manifest_path.is_file():
            return self._gap(days, start_time_ms, end_time_ms, "服务器历史数据仓尚未建立。")
        cutoff = int(json.loads(manifest_path.read_text(encoding="utf-8")).get("dataset_cutoff_ms") or 0)
        if cutoff < end_time_ms:
            available = datetime.fromtimestamp(cutoff / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if cutoff else "无"
            return self._gap(days, start_time_ms, end_time_ms, f"历史数据只到 {available}，未覆盖所选结束时间。", cutoff)
        histories = self._load_histories(start_time_ms, end_time_ms, spec)
        if len(histories) < int(spec["market"]["minimum_simultaneously_eligible_markets"]):
            return self._gap(days, start_time_ms, end_time_ms, "满足完整历史与流动性要求的市场不足，无法完整回放。", cutoff)
        signals = self._detect(histories, spec, start_time_ms, end_time_ms)
        self._mark_scope(signals, int(spec["workload"]["daily_candidate_limit"]))
        return {"status": "READY", "days": days, "start_time_ms": start_time_ms, "end_time_ms": end_time_ms, "dataset_cutoff_ms": cutoff, "data_gap": None, "signals": signals, "summary": self._summary(signals)}

    def _load_histories(self, start_ms, end_ms, spec):
        warmup_15m = max(14 * 96, int(spec["signals"]["SUSTAINED_STRENGTH"]["long_volume_days"]) * 96, 288) * INTERVAL_MS
        warmup_4h = 361 * 4 * 60 * 60_000
        histories = {}
        for directory in sorted((self.dataset_root / "raw/klines/15m").glob("*")):
            if not directory.is_dir():
                continue
            symbol = directory.name
            candles = self._load_15m(symbol, start_ms - warmup_15m, end_ms + 32 * INTERVAL_MS)
            long_cycle = self._load_jsonl(symbol, "4h", start_ms - warmup_4h, end_ms)
            daily = self._load_daily(symbol, start_ms - 35 * DAY_MS, end_ms)
            if candles and long_cycle and daily:
                histories[symbol] = {"candles": candles, "long_cycle": long_cycle, "daily": daily}
        return histories

    def _detect(self, histories, spec, start_ms, end_ms):
        result = []
        replay_spec = deepcopy(spec)
        replay_spec["market"]["minimum_simultaneously_eligible_markets"] = 1
        lookback_days = int(spec["market"]["liquidity"]["lookback_complete_utc_days"])
        liquidity_minimum = float(spec["market"]["liquidity"]["minimum_median_daily_quote_volume_usdt"])
        eligible_counts = {}
        first_day = start_ms // DAY_MS * DAY_MS
        last_day = end_ms // DAY_MS * DAY_MS
        for day_start in range(first_day, last_day + DAY_MS, DAY_MS):
            eligible_counts[day_start] = sum(
                len(values := [value for close_ms, value in history["daily"] if close_ms < day_start][-lookback_days:]) == lookback_days
                and statistics.median(values) >= liquidity_minimum
                for history in histories.values()
            )
        for symbol, history in histories.items():
            candles = history["candles"]
            close_times = [row.close_time_ms for row in candles]
            cycle_times = [row.close_time_ms for row in history["long_cycle"]]
            for signal_index, candle in enumerate(candles):
                timestamp = candle.close_time_ms
                if timestamp < start_ms or timestamp > end_ms:
                    continue
                day_start = timestamp // DAY_MS * DAY_MS
                if eligible_counts.get(day_start, 0) < int(spec["market"]["minimum_simultaneously_eligible_markets"]):
                    continue
                volumes = [value for close_ms, value in history["daily"] if close_ms < day_start][-lookback_days:]
                if len(volumes) != lookback_days:
                    continue
                cycle_index = bisect_right(cycle_times, timestamp)
                window = {symbol: {"candles": candles[max(0, signal_index - 1439): signal_index + 1], "long_cycle_candles": history["long_cycle"][max(0, cycle_index - 361):cycle_index], "daily_quote_volumes": volumes}}
                for signal in detect_sig1_signals(window, timestamp, replay_spec):
                    if signal["symbol"] == symbol:
                        result.append(self._outcome(signal, candles, signal_index, close_times))
        return sorted(result, key=lambda row: (row["signal_time_ms"], row["signal_id"]))

    @staticmethod
    def _outcome(signal, candles, signal_index, close_times):
        following = candles[signal_index + 1: signal_index + 34]
        direction = signal["direction"]
        entry_candle = following[0] if following else None
        entry = float(entry_candle.open) if entry_candle else float(signal["reference_entry_price"])
        risk = float(signal["initial_risk_price"])
        sign = 1 if direction == "LONG" else -1
        favorable = max([0.0] + [sign * (float(row.high if sign > 0 else row.low) - entry) / risk for row in following])
        adverse = min([0.0] + [sign * (float(row.low if sign > 0 else row.high) - entry) / risk for row in following])
        opened = {"entry_time_ms": int(entry_candle.open_time_ms) if entry_candle else signal["signal_time_ms"] + 1, "entry_price": entry, "initial_risk_price": risk, "stop_price": entry - sign * risk, "time_exit_open_time_ms": (int(entry_candle.open_time_ms) if entry_candle else signal["signal_time_ms"] + 1) + 32 * INTERVAL_MS}
        mechanical = Sig1SignalService._virtual_exit({"opened": opened, "direction": direction}, following)
        return signal | {"chart_after": (mechanical or {}).get("chart_after", []), "outcome": {"maximum_favorable_r": favorable, "maximum_adverse_r": adverse, "mechanical_r": (mechanical or {}).get("realized_r"), "exit_reason": (mechanical or {}).get("exit_reason")}}

    @staticmethod
    def _mark_scope(signals, limit):
        by_day = {}
        for row in signals:
            by_day.setdefault(row["signal_day_utc"], []).append(row)
        for rows in by_day.values():
            scope = daily_workload_scope(rows, limit)
            included = set(scope["included_signal_ids"])
            for row in rows:
                row["candidate_scope"] = "INCLUDED" if row["signal_id"] in included else "TRUNCATED"

    @staticmethod
    def _summary(signals):
        families = {}
        symbols = {}
        for row in signals:
            families[row["family_id"]] = families.get(row["family_id"], 0) + 1
            symbols[row["symbol"]] = symbols.get(row["symbol"], 0) + 1
        return {"total": len(signals), "truncated": sum(row.get("candidate_scope") == "TRUNCATED" for row in signals), "by_family": families, "by_symbol": symbols}

    def _load_15m(self, symbol, start_ms, end_ms):
        rows = []
        for path in sorted((self.dataset_root / "raw/klines/15m" / symbol).glob("*.zip")):
            for item in iter_kline_zip(path):
                if start_ms <= item.close_time_ms <= end_ms:
                    rows.append(ShortlineCandle(item.open_time_ms, item.close_time_ms, float(item.open), float(item.high), float(item.low), float(item.close), float(item.quote_volume)))
        return rows

    def _load_jsonl(self, symbol, interval, start_ms, end_ms):
        rows = []
        for path in sorted((self.dataset_root / "derived" / interval / symbol).glob("*.jsonl.gz")):
            with gzip.open(path, "rt", encoding="utf-8") as source:
                for line in source:
                    row = json.loads(line)
                    if row.get("status") != "COMPLETE" or row.get("close") is None:
                        continue
                    close_ms = int(row.get("close_time_ms", row.get("close_time")))
                    if start_ms <= close_ms <= end_ms:
                        rows.append(ShortlineCandle(int(row.get("open_time_ms", row.get("open_time"))), close_ms, float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]), float(row.get("quote_volume", 0))))
        return rows

    def _load_daily(self, symbol, start_ms, end_ms):
        rows = []
        for path in sorted((self.dataset_root / "derived/daily_liquidity" / symbol).glob("*.jsonl.gz")):
            with gzip.open(path, "rt", encoding="utf-8") as source:
                for line in source:
                    row = json.loads(line); close_ms = int(row["day_close_time_ms"])
                    if row.get("status") == "COMPLETE" and row.get("quote_volume") is not None and start_ms <= close_ms <= end_ms:
                        rows.append((close_ms, float(row["quote_volume"])))
        return rows

    @staticmethod
    def _gap(days, start_ms, end_ms, message, cutoff=None):
        return {"status": "DATA_GAP", "days": days, "start_time_ms": start_ms, "end_time_ms": end_ms, "dataset_cutoff_ms": cutoff, "data_gap": message, "signals": [], "summary": {"total": 0, "truncated": 0, "by_family": {}, "by_symbol": {}}}
