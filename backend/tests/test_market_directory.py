import json
from orbit.application.market_directory import MarketDirectoryService


class Response:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_args): return None
    def read(self): return json.dumps(self.payload).encode()


def test_current_directory_uses_live_exchange_and_ticker_data():
    payloads = [
        {"symbols": [{"symbol": "BTCUSDT", "contractType": "PERPETUAL", "quoteAsset": "USDT", "status": "TRADING", "onboardDate": 1}, {"symbol": "LOWUSDT", "contractType": "PERPETUAL", "quoteAsset": "USDT", "status": "TRADING", "onboardDate": 1}]},
        [{"symbol": "BTCUSDT", "quoteVolume": "90000000", "priceChangePercent": "2.5", "lastPrice": "65000", "openPrice": "63000", "highPrice": "66000", "lowPrice": "62000", "weightedAvgPrice": "64500", "volume": "1200", "count": 3200}, {"symbol": "LOWUSDT", "quoteVolume": "200", "priceChangePercent": "-1.25"}],
    ]
    service = MarketDirectoryService(opener=lambda *_args, **_kwargs: Response(payloads.pop(0)))
    result = service.current()
    assert [row["symbol"] for row in result["items"]] == ["BTCUSDT", "LOWUSDT"]
    assert result["items"][0]["scan_state"] == "扫描中"
    assert result["items"][0]["change_24h_pct"] == 2.5
    assert result["items"][0]["last_price"] == 65000
    assert result["items"][0]["trade_count_24h"] == 3200
    assert result["items"][1]["change_24h_pct"] == -1.25
    assert result["items"][1]["scan_reason"] == "24 小时成交额不足"
