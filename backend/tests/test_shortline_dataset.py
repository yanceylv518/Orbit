import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.shortline_dataset import (
    ShortlineDatasetBuilder,
    load_jsonl_gzip,
    write_archive_index,
)
from orbit.application.research.catalog import ResearchCatalogService
from orbit.domain.calibration.shortline_dataset import (
    AggregatedCandle,
    ContractMetadata,
    aggregate_candles,
    compare_native_aggregate,
    parse_archive_candle,
    universe_at,
)
from orbit.infrastructure.market_data.binance_public_archive import (
    ArchiveDownloader,
    ArchiveError,
    ArchiveObject,
    BinancePublicArchiveIndex,
    iter_kline_zip,
)


INTERVAL_MS = 15 * 60 * 1000


def candle_row(open_time, *, price="10", volume="2", quote_volume="20"):
    return [
        open_time, price, str(Decimal(price) + 1), str(Decimal(price) - 1), price,
        volume, open_time + INTERVAL_MS - 1, quote_volume, 3, "1", "10", "0",
    ]


class ShortlineDatasetDomainTests(unittest.TestCase):
    def test_1h_and_4h_aggregation_are_exact(self):
        candles = [
            parse_archive_candle(candle_row(i * INTERVAL_MS, price=str(10 + i)))
            for i in range(16)
        ]

        hourly = aggregate_candles(candles, "1h")
        four_hour = aggregate_candles(candles, "4h")[0]

        self.assertEqual(len(hourly), 4)
        self.assertTrue(all(item.status == "COMPLETE" for item in hourly))
        self.assertEqual(hourly[0].open, "10")
        self.assertEqual(hourly[0].close, "13")
        self.assertEqual(hourly[0].high, "14")
        self.assertEqual(hourly[0].volume, "8")
        self.assertEqual(four_hour.close, "25")
        self.assertEqual(four_hour.quote_volume, "320")
        self.assertEqual(four_hour.trade_count, 48)

    def test_missing_child_produces_non_tradable_incomplete_bar(self):
        candles = [
            parse_archive_candle(candle_row(i * INTERVAL_MS))
            for i in (0, 1, 3)
        ]

        result = aggregate_candles(candles, "1h")[0]

        self.assertEqual(result.status, "INCOMPLETE")
        self.assertEqual(result.missing_open_times_ms, (2 * INTERVAL_MS,))
        self.assertIsNone(result.close)
        self.assertIsNone(result.quote_volume)

    def test_large_gap_is_counted_without_unbounded_timestamp_expansion(self):
        candles = [
            parse_archive_candle(candle_row(0)),
            parse_archive_candle(candle_row(10_000 * INTERVAL_MS)),
        ]
        from orbit.domain.calibration.shortline_dataset import validate_candle_sequence

        quality = validate_candle_sequence(candles)

        self.assertEqual(quality["missing_count"], 9_999)
        self.assertEqual(len(quality["missing_open_times_ms"]), 1_000)
        self.assertTrue(quality["missing_samples_truncated"])

    def test_native_comparison_requires_exact_ohlcv_and_trade_fields(self):
        candles = [parse_archive_candle(candle_row(i * INTERVAL_MS)) for i in range(4)]
        derived = aggregate_candles(candles, "1h")
        native = [[0, "10", "11", "9", "10", "8", 3_599_999, "80", 12, "4", "40", "0"]]

        passed = compare_native_aggregate(derived, native)
        native[0][4] = "10.1"
        failed = compare_native_aggregate(derived, native)

        self.assertTrue(passed["passed"])
        self.assertFalse(failed["passed"])
        self.assertEqual(failed["mismatches"][0]["open_time_ms"], 0)

        missing = compare_native_aggregate(derived, [])
        self.assertFalse(missing["passed"])
        self.assertEqual(missing["missing_in_native"], [0])

        incomplete = AggregatedCandle(
            open_time_ms=3_600_000, close_time_ms=7_199_999, interval="1h",
            status="INCOMPLETE", observed_children=2, expected_children=4,
            missing_open_times_ms=(5_400_000, 6_300_000),
        )
        native_partial = [
            [0, "10", "11", "9", "10", "8", 3_599_999, "80", 12, "4", "40", "0"],
            [3_600_000, "10", "11", "9", "10", "4", 7_199_999, "40", 6, "2", "20", "0"],
        ]
        partial_result = compare_native_aggregate([*derived, incomplete], native_partial)
        self.assertTrue(partial_result["passed"])
        self.assertEqual(partial_result["native_for_incomplete_derived"], [3_600_000])

    def test_luna_exists_before_delisting_and_not_after(self):
        listed = _ms("2021-01-01T00:00:00Z")
        # Exact boundary observed from the official final 15m archive sample.
        delisted = 1_652_425_200_000
        contracts = [ContractMetadata(
            symbol="LUNAUSDT", listed_at_ms=listed, first_open_time_ms=listed,
            last_close_time_ms=delisted - 1, delisted_at_ms=delisted,
            status="DELISTED", status_method="ARCHIVE_STALENESS_HEURISTIC",
        )]

        before = universe_at(_ms("2022-05-12T00:00:00Z"), contracts, min_history_days=30)
        after = universe_at(_ms("2022-05-14T00:00:00Z"), contracts, min_history_days=30)

        self.assertEqual(before, ["LUNAUSDT"])
        self.assertEqual(after, [])

    def test_universe_liquidity_uses_only_days_closed_before_timestamp(self):
        listed = _ms("2021-01-01T00:00:00Z")
        contract = ContractMetadata(
            symbol="TESTUSDT", listed_at_ms=listed, first_open_time_ms=listed,
            last_close_time_ms=_ms("2021-03-01T00:00:00Z") - 1,
            delisted_at_ms=None, status="TRADING", status_method="TEST",
        )
        query_time = _ms("2021-02-01T12:00:00Z")
        liquidity = {"TESTUSDT": [
            {"day_close_time_ms": query_time - 1, "status": "COMPLETE", "quote_volume": "100"},
            {"day_close_time_ms": query_time + 1, "status": "COMPLETE", "quote_volume": "999999"},
        ]}

        result = universe_at(
            query_time, [contract], min_history_days=1, liquidity_by_symbol=liquidity,
            liquidity_lookback_days=1, min_median_quote_volume="101",
        )

        self.assertEqual(result, [])


class ShortlineArchiveTests(unittest.TestCase):
    def test_s3_index_paginates_and_keeps_delisted_symbol(self):
        pages = [
            _listing_xml(
                ["data/futures/um/monthly/klines/LUNAUSDT/15m/LUNAUSDT-15m-2022-04.zip"],
                truncated=True, token="next token",
            ),
            _listing_xml(
                ["data/futures/um/monthly/klines/LUNAUSDT/15m/LUNAUSDT-15m-2022-05.zip"],
                truncated=False,
            ),
        ]
        opener = QueueOpener(pages)

        objects = BinancePublicArchiveIndex(opener=opener).discover_symbol(
            "LUNAUSDT", include_funding=False,
        )

        self.assertEqual({item.symbol for item in objects}, {"LUNAUSDT"})
        self.assertEqual({item.month for item in objects}, {"2022-04", "2022-05"})
        self.assertIn("continuation-token=next+token", opener.urls[1])

    def test_symbol_discovery_uses_common_prefixes(self):
        payload = (
            "<ListBucketResult xmlns=\"http://s3.amazonaws.com/doc/2006-03-01/\">"
            "<IsTruncated>false</IsTruncated>"
            "<CommonPrefixes><Prefix>data/futures/um/monthly/klines/LUNAUSDT/</Prefix>"
            "</CommonPrefixes><CommonPrefixes><Prefix>data/futures/um/monthly/klines/BTCUSDT/</Prefix>"
            "</CommonPrefixes></ListBucketResult>"
        ).encode()

        symbols = BinancePublicArchiveIndex(opener=QueueOpener([payload])).discover_symbols()

        self.assertEqual(symbols, ["BTCUSDT", "LUNAUSDT"])

    def test_downloader_resumes_and_verifies_official_checksum(self):
        payload = b"zip-content"
        checksum = hashlib.sha256(payload).hexdigest()
        opener = DownloadOpener(payload, checksum)
        item = ArchiveObject(
            key="data/futures/um/monthly/klines/LUNAUSDT/15m/LUNAUSDT-15m-2022-04.zip",
            size=len(payload), last_modified="", etag=None, kind="KLINE_15M",
            symbol="LUNAUSDT", month="2022-04",
        )
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "file.zip"
            destination.with_name("file.zip.part").write_bytes(payload[:3])

            first = ArchiveDownloader(opener=opener, attempts=1).download(item, destination)
            second = ArchiveDownloader(opener=opener, attempts=1).download(item, destination)

            self.assertEqual(first["status"], "DOWNLOADED")
            self.assertEqual(second["status"], "UNCHANGED")
            self.assertEqual(destination.read_bytes(), payload)
            self.assertIn("bytes=3-", opener.ranges)

    def test_zip_reader_rejects_path_traversal_members(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "unsafe.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("../rows.csv", "1,2,3")
            with self.assertRaisesRegex(ArchiveError, "unsafe"):
                list(iter_kline_zip(path))


class ShortlineDatasetBuilderTests(unittest.TestCase):
    def test_build_is_idempotent_and_catalog_registers_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            calibration = Path(temp) / "var" / "calibration"
            root = calibration / "shortline-data-v1"
            raw = root / "raw" / "klines" / "15m" / "LUNAUSDT"
            raw.mkdir(parents=True)
            _write_kline_zip(
                raw / "LUNAUSDT-15m-2022-04.zip",
                [candle_row(i * INTERVAL_MS) for i in range(16)],
            )
            write_archive_index(root / "metadata" / "archive_index.json", [ArchiveObject(
                key="data/futures/um/monthly/klines/LUNAUSDT/15m/LUNAUSDT-15m-2022-04.zip",
                size=(raw / "LUNAUSDT-15m-2022-04.zip").stat().st_size,
                last_modified="2022-05-01T00:00:00Z", etag=None,
                kind="KLINE_15M", symbol="LUNAUSDT", month="2022-04",
            )], scope="ALL_USDT_PERPETUAL")
            builder = ShortlineDatasetBuilder(root)

            first = builder.build(dataset_cutoff_ms=_ms("2026-01-01T00:00:00Z"))
            second = builder.build(dataset_cutoff_ms=_ms("2026-01-01T00:00:00Z"))
            catalog = ResearchCatalogService(calibration, NullRegistry()).datasets()

            self.assertEqual(
                first["manifest"]["dataset_fingerprint"],
                second["manifest"]["dataset_fingerprint"],
            )
            self.assertEqual(first["quality_report"]["report_sha256"], second["quality_report"]["report_sha256"])
            self.assertEqual(first["contracts"][0]["symbol"], "LUNAUSDT")
            self.assertEqual(first["contracts"][0]["status"], "DELISTED")
            self.assertTrue(first["contracts"][0]["history_complete"])
            derived = load_jsonl_gzip(
                root / "derived" / "4h" / "LUNAUSDT" / "LUNAUSDT-4h-2022-04.jsonl.gz"
            )
            self.assertEqual(derived[0]["status"], "COMPLETE")
            registered = next(item for item in catalog if item["id"] == "shortline-data-v1")
            self.assertEqual(registered["sha256"], first["manifest"]["dataset_fingerprint"])
            self.assertEqual(
                registered["quality_report_sha256"], first["quality_report"]["report_sha256"],
            )

            verification = {
                "symbol": "LUNAUSDT", "month": "2022-04", "interval": "1h",
                "compared": 1, "mismatches": [], "passed": True,
            }
            report = builder.record_native_verification(verification)
            repeated = builder.record_native_verification(verification)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(report["report_sha256"], repeated["report_sha256"])
            self.assertEqual(len(repeated["samples"]), 1)
            self.assertIn(
                "NATIVE_AGGREGATE_VERIFICATION",
                {item["kind"] for item in manifest["entries"]},
            )

    def test_complete_build_rejects_missing_indexed_partitions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "shortline-data-v1"
            raw = root / "raw" / "klines" / "15m" / "LUNAUSDT"
            raw.mkdir(parents=True)
            path = raw / "LUNAUSDT-15m-2022-05.zip"
            _write_kline_zip(path, [candle_row(i * INTERVAL_MS) for i in range(4)])
            objects = [ArchiveObject(
                key=f"data/futures/um/monthly/klines/LUNAUSDT/15m/LUNAUSDT-15m-2022-{month}.zip",
                size=1, last_modified="", etag=None, kind="KLINE_15M",
                symbol="LUNAUSDT", month=f"2022-{month}",
            ) for month in ("04", "05")]
            write_archive_index(
                root / "metadata" / "archive_index.json", objects,
                scope="ALL_USDT_PERPETUAL",
            )

            with self.assertRaisesRegex(Exception, "not downloaded"):
                ShortlineDatasetBuilder(root).build()
            partial = ShortlineDatasetBuilder(root).build(allow_partial=True)

            self.assertEqual(partial["quality_report"]["dataset_state"], "PARTIAL")
            self.assertFalse(partial["contracts"][0]["history_complete"])
            self.assertEqual(
                universe_at(_ms("2022-05-01T01:00:00Z"), partial["contracts"], min_history_days=0),
                [],
            )

    def test_archive_index_is_deterministic(self):
        item = ArchiveObject(
            key="data/futures/um/monthly/klines/LUNAUSDT/15m/LUNAUSDT-15m-2022-04.zip",
            size=1, last_modified="2022-05-01T00:00:00Z", etag="etag",
            kind="KLINE_15M", symbol="LUNAUSDT", month="2022-04",
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "archive_index.json"
            first = write_archive_index(path, [item])
            first_bytes = path.read_bytes()
            second = write_archive_index(path, [item])

            self.assertEqual(first["objects_sha256"], second["objects_sha256"])
            self.assertEqual(first_bytes, path.read_bytes())


class NullRegistry:
    def ensure(self, candidates):
        return None

    def all(self):
        return []


class BytesResponse(io.BytesIO):
    def __init__(self, payload, *, status=200):
        super().__init__(payload)
        self.status = status

    def getcode(self):
        return self.status


class QueueOpener:
    def __init__(self, pages):
        self.pages = list(pages)
        self.urls = []

    def __call__(self, request, timeout=60):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        self.urls.append(url)
        return BytesResponse(self.pages.pop(0))


class DownloadOpener:
    def __init__(self, payload, checksum):
        self.payload = payload
        self.checksum = checksum
        self.ranges = []

    def __call__(self, request, timeout=60):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url.endswith(".CHECKSUM"):
            return BytesResponse(f"{self.checksum}  file.zip\n".encode())
        header = request.headers.get("Range") if hasattr(request, "headers") else None
        if header:
            self.ranges.append(header)
            offset = int(header.split("=")[1].split("-")[0])
            return BytesResponse(self.payload[offset:], status=206)
        return BytesResponse(self.payload)


def _write_kline_zip(path, rows):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerows(rows)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(path.with_suffix(".csv").name, buffer.getvalue())


def _listing_xml(keys, *, truncated, token=None):
    contents = "".join(
        f"<Contents><Key>{key}</Key><LastModified>2022-05-01T00:00:00Z</LastModified>"
        f"<ETag>\"etag\"</ETag><Size>123</Size></Contents>"
        for key in keys
    )
    next_token = f"<NextContinuationToken>{token}</NextContinuationToken>" if token else ""
    return (
        f"<ListBucketResult xmlns=\"http://s3.amazonaws.com/doc/2006-03-01/\">"
        f"<IsTruncated>{str(truncated).lower()}</IsTruncated>{contents}{next_token}</ListBucketResult>"
    ).encode()


def _ms(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 1000)


if __name__ == "__main__":
    unittest.main()
