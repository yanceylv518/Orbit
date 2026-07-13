import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.domain.calibration.history import exclude_latest_candles, parse_candles, parse_funding


class CalibrationHistoryTest(unittest.TestCase):
    def test_legacy_close_row_remains_supported(self):
        candle = parse_candles([[123, 101.5]])[0]
        self.assertEqual((candle.open, candle.high, candle.low, candle.close), (101.5, 101.5, 101.5, 101.5))

    def test_ohlc_object_is_parsed(self):
        candle = parse_candles([{
            "close_time_ms": 123, "open": 100, "high": 103, "low": 99, "close": 102,
        }])[0]
        self.assertEqual((candle.open, candle.high, candle.low, candle.close), (100, 103, 99, 102))

    def test_funding_accepts_binance_and_normalized_shapes(self):
        points = parse_funding([
            {"fundingTime": 200, "fundingRate": "0.0001"},
            {"funding_time_ms": 100, "funding_rate": -0.0002},
        ])
        self.assertEqual([point.funding_time_ms for point in points], [100, 200])

    def test_exclude_latest_candles_keeps_older_unseen_period(self):
        candles = parse_candles([[index, 100 + index] for index in range(10)])
        older = exclude_latest_candles(candles, 4)

        self.assertEqual(len(older), 6)
        self.assertEqual(older[-1].close_time_ms, 5)


if __name__ == "__main__":
    unittest.main()
