import json
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
