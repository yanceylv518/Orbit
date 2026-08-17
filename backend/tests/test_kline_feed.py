import json
import time
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from orbit.infrastructure.exchange.kline_feed import BinanceKlineFeed, BinanceWeightLimiter, MarketFeedError


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
    def test_weight_limiter_waits_until_next_window_when_budget_is_exhausted(self):
        now = [0.0]
        waits = []
        limiter = BinanceWeightLimiter(2, clock=lambda: now[0], sleeper=lambda seconds: (waits.append(seconds), now.__setitem__(0, now[0] + seconds)))
        limiter.acquire(2)
        limiter.acquire(1)
        self.assertEqual(waits, [60.0])

    def test_weight_limiter_skips_requests_during_exchange_ban(self):
        limiter = BinanceWeightLimiter(10, clock=lambda: 100.0, sleeper=lambda _seconds: self.fail("must not wait through a ban"))
        limiter.backoff(75)
        with self.assertRaises(MarketFeedError) as raised:
            limiter.acquire(1)
        self.assertEqual(raised.exception.category, "RATE_LIMIT")

    def test_rate_limit_honors_retry_after_and_does_not_retry_request(self):
        class Limiter:
            def __init__(self): self.backoffs = []
            def acquire(self, _weight): pass
            def backoff(self, seconds): self.backoffs.append(seconds)
        limiter = Limiter()
        calls = []
        error = HTTPError("https://example.test", 429, "limited", {"Retry-After": "75"}, BytesIO(b'{"code":-1003}'))
        def fail_once(*_args, **_kwargs):
            calls.append(1)
            raise error
        with patch("orbit.infrastructure.exchange.kline_feed.urlopen", fail_once):
            with self.assertRaises(MarketFeedError) as raised:
                BinanceKlineFeed(limiter=limiter).closed_klines("BTCUSDT", "15m", 3)
        self.assertEqual(len(calls), 1)
        self.assertEqual(raised.exception.category, "RATE_LIMIT")
        self.assertEqual(limiter.backoffs, [75.0])

    def test_large_history_is_paged_without_shortening_requested_window(self):
        calls = []
        def row(index):
            return [index, "1", "1", "1", "1", "1", index, "1", 1, "0", "0", "0"]
        def paged(request, timeout):
            query = parse_qs(urlparse(request.full_url).query)
            calls.append(query)
            return FakeResponse([row(index) for index in (range(101, 1601) if "endTime" not in query else range(0, 101))])
        with patch("orbit.infrastructure.exchange.kline_feed.urlopen", paged):
            result = BinanceKlineFeed().closed_klines("BTCUSDT", "15m", 1600)
        self.assertEqual(len(result), 1600)
        self.assertEqual(len(calls), 2)
        self.assertIn("endTime", calls[1])

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
