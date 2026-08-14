import json
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from orbit.infrastructure.exchange.kline_feed import BinanceKlineFeed


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class BinanceKlineFeedTest(unittest.TestCase):
    def test_closed_klines_include_quote_volume(self):
        now = int(time.time() * 1000)
        row = [0, "1", "2", "0.5", "1.5", "10", now - 1, "12345", 1, "0", "0", "0"]
        with patch("orbit.infrastructure.exchange.kline_feed.urlopen", lambda request, timeout: FakeResponse([row])):
            result = BinanceKlineFeed().closed_klines("BTCUSDT", "15m", 1)
        self.assertEqual(result[0]["quote_volume"], 12345.0)

    def test_perpetual_symbols_exclude_non_usdt_and_inactive_contracts(self):
        payload = {
            "symbols": [
                {"symbol": "BTCUSDT", "status": "TRADING", "contractType": "PERPETUAL", "quoteAsset": "USDT"},
                {"symbol": "ETHUSDT_2601", "status": "TRADING", "contractType": "CURRENT_QUARTER", "quoteAsset": "USDT"},
                {"symbol": "BTCUSDC", "status": "TRADING", "contractType": "PERPETUAL", "quoteAsset": "USDC"},
                {"symbol": "OLDUSDT", "status": "SETTLING", "contractType": "PERPETUAL", "quoteAsset": "USDT"},
            ]
        }
        with patch("orbit.infrastructure.exchange.kline_feed.urlopen", lambda request, timeout: FakeResponse(payload)):
            self.assertEqual(BinanceKlineFeed().perpetual_symbols(), ["BTCUSDT"])

    def test_funding_rates_use_open_closed_time_window(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            return FakeResponse([
                {"fundingTime": 100, "fundingRate": "0.1"},
                {"fundingTime": 200, "fundingRate": "0.2"},
                {"fundingTime": 301, "fundingRate": "0.3"},
            ])

        with patch("orbit.infrastructure.exchange.kline_feed.urlopen", fake_urlopen):
            rows = BinanceKlineFeed().funding_rates("BTCUSDT", 100, 300)

        query = parse_qs(urlparse(captured["url"]).query)
        self.assertEqual(query["startTime"], ["101"])
        self.assertEqual(query["endTime"], ["300"])
        self.assertEqual(rows, [{"funding_time_ms": 200, "funding_rate": 0.2}])


if __name__ == "__main__":
    unittest.main()
