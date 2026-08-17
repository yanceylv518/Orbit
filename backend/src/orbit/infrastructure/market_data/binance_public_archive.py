from __future__ import annotations

import csv
import hashlib
import io
import os
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
import re
import time
from typing import Any, Callable, Iterator
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

from orbit.domain.calibration.shortline_dataset import ArchiveCandle, parse_archive_candle


ARCHIVE_BASE_URL = "https://data.binance.vision"
S3_LIST_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
KLINE_PREFIX = "data/futures/um/monthly/klines/"
FUNDING_PREFIX = "data/futures/um/monthly/fundingRate/"
DAILY_KLINE_PREFIX = "data/futures/um/daily/klines/"
KLINE_KEY_RE = re.compile(
    r"^data/futures/um/monthly/klines/(?P<symbol>[A-Z0-9]+USDT)/15m/"
    r"(?P=symbol)-15m-(?P<month>\d{4}-\d{2})\.zip$"
)
FUNDING_KEY_RE = re.compile(
    r"^data/futures/um/monthly/fundingRate/(?P<symbol>[A-Z0-9]+USDT)/"
    r"(?P=symbol)-fundingRate-(?P<month>\d{4}-\d{2})\.zip$"
)
DAILY_KLINE_KEY_RE = re.compile(
    r"^data/futures/um/daily/klines/(?P<symbol>[A-Z0-9]+USDT)/15m/"
    r"(?P=symbol)-15m-(?P<date>\d{4}-\d{2}-\d{2})\.zip$"
)


class ArchiveError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArchiveObject:
    key: str
    size: int
    last_modified: str
    etag: str | None
    kind: str
    symbol: str
    month: str

    @property
    def url(self) -> str:
        return f"{ARCHIVE_BASE_URL}/{urllib.parse.quote(self.key, safe='/')}"

    @property
    def checksum_url(self) -> str:
        return f"{self.url}.CHECKSUM"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class BinancePublicArchiveIndex:
    """Read-only S3 ListObjectsV2 client for historical and delisted contracts."""

    def __init__(
        self,
        *,
        opener: Callable[..., Any] = urllib.request.urlopen,
        list_url: str = S3_LIST_URL,
    ):
        self.opener = opener
        self.list_url = list_url

    def list_objects(self, prefix: str) -> Iterator[dict[str, Any]]:
        yield from self._list(prefix, include_objects=True)

    def list_common_prefixes(self, prefix: str) -> Iterator[str]:
        for item in self._list(prefix, delimiter="/", include_objects=False):
            yield str(item["prefix"])

    def _list(
        self,
        prefix: str,
        *,
        delimiter: str | None = None,
        include_objects: bool,
    ) -> Iterator[dict[str, Any]]:
        token: str | None = None
        while True:
            query = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
            if delimiter:
                query["delimiter"] = delimiter
            if token:
                query["continuation-token"] = token
            url = f"{self.list_url}?{urllib.parse.urlencode(query)}"
            payload = _read_response(self.opener, url)
            try:
                root = ET.fromstring(payload)
            except ET.ParseError as exc:
                raise ArchiveError("Binance archive index returned invalid XML") from exc
            namespace = ""
            if root.tag.startswith("{"):
                namespace = root.tag.split("}", 1)[0] + "}"
            if include_objects:
                for node in root.findall(f"{namespace}Contents"):
                    key = _xml_text(node, f"{namespace}Key")
                    if not key.endswith(".zip"):
                        continue
                    yield {
                        "key": key,
                        "size": int(_xml_text(node, f"{namespace}Size")),
                        "last_modified": _xml_text(node, f"{namespace}LastModified"),
                        "etag": (_xml_optional(node, f"{namespace}ETag") or "").strip('"') or None,
                    }
            else:
                for node in root.findall(f"{namespace}CommonPrefixes"):
                    yield {"prefix": _xml_text(node, f"{namespace}Prefix")}
            truncated = _xml_text(root, f"{namespace}IsTruncated").lower() == "true"
            if not truncated:
                break
            token = _xml_optional(root, f"{namespace}NextContinuationToken")
            if not token:
                raise ArchiveError("truncated Binance archive listing omitted continuation token")

    def discover(self, *, include_funding: bool = True) -> list[ArchiveObject]:
        objects = []
        for symbol in self.discover_symbols():
            objects.extend(self.discover_symbol(symbol, include_funding=include_funding))
        return sorted(objects, key=lambda item: (item.symbol, item.month, item.kind))

    def discover_symbols(self) -> list[str]:
        result = []
        for prefix in self.list_common_prefixes(KLINE_PREFIX):
            relative = prefix.removeprefix(KLINE_PREFIX).strip("/")
            if re.fullmatch(r"[A-Z0-9]+USDT", relative):
                result.append(relative)
        return sorted(set(result))

    def discover_symbol(self, symbol: str, *, include_funding: bool = True) -> list[ArchiveObject]:
        normalized = symbol.upper().strip()
        if not re.fullmatch(r"[A-Z0-9]+USDT", normalized):
            raise ArchiveError(f"invalid USD-M perpetual symbol: {symbol}")
        objects = self._discover_kind(
            f"{KLINE_PREFIX}{normalized}/15m/", KLINE_KEY_RE, "KLINE_15M",
        )
        if include_funding:
            objects.extend(self._discover_kind(
                f"{FUNDING_PREFIX}{normalized}/", FUNDING_KEY_RE, "FUNDING",
            ))
        return sorted(objects, key=lambda item: (item.month, item.kind))

    def discover_daily_symbols(self) -> list[str]:
        result = []
        for prefix in self.list_common_prefixes(DAILY_KLINE_PREFIX):
            relative = prefix.removeprefix(DAILY_KLINE_PREFIX).strip("/")
            if re.fullmatch(r"[A-Z0-9]+USDT", relative):
                result.append(relative)
        return sorted(set(result))

    def discover_daily_symbol_month(self, symbol: str, month: str) -> list[ArchiveObject]:
        normalized = symbol.upper().strip()
        if not re.fullmatch(r"[A-Z0-9]+USDT", normalized):
            raise ArchiveError(f"invalid USD-M perpetual symbol: {symbol}")
        if not re.fullmatch(r"\d{4}-\d{2}", month):
            raise ArchiveError(f"invalid archive month: {month}")
        prefix = f"{DAILY_KLINE_PREFIX}{normalized}/15m/{normalized}-15m-{month}-"
        result = []
        for item in self.list_objects(prefix):
            match = DAILY_KLINE_KEY_RE.fullmatch(item["key"])
            if not match:
                continue
            result.append(ArchiveObject(
                key=item["key"], size=item["size"],
                last_modified=item["last_modified"], etag=item["etag"],
                kind="KLINE_15M_DAILY", symbol=normalized, month=match.group("date"),
            ))
        return sorted(result, key=lambda item: item.month)

    def _discover_kind(
        self,
        prefix: str,
        pattern: re.Pattern[str],
        kind: str,
    ) -> list[ArchiveObject]:
        result = []
        for item in self.list_objects(prefix):
            match = pattern.fullmatch(item["key"])
            if not match:
                continue
            result.append(ArchiveObject(
                key=item["key"], size=item["size"],
                last_modified=item["last_modified"], etag=item["etag"],
                kind=kind, symbol=match.group("symbol"), month=match.group("month"),
            ))
        return result


class ArchiveDownloader:
    def __init__(
        self,
        *,
        opener: Callable[..., Any] = urllib.request.urlopen,
        attempts: int = 4,
    ):
        self.opener = opener
        self.attempts = attempts

    def download(self, item: ArchiveObject, destination: Path) -> dict[str, Any]:
        destination = destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        expected = self._official_checksum(item)
        if destination.exists() and sha256_file(destination) == expected:
            return {"path": str(destination), "sha256": expected, "status": "UNCHANGED"}
        partial = destination.with_name(destination.name + ".part")
        for attempt in range(1, self.attempts + 1):
            try:
                self._download_once(item.url, partial)
                actual = sha256_file(partial)
                if actual != expected:
                    partial.unlink(missing_ok=True)
                    raise ArchiveError(
                        f"checksum mismatch for {item.key}: expected {expected}, got {actual}"
                    )
                os.replace(partial, destination)
                return {"path": str(destination), "sha256": actual, "status": "DOWNLOADED"}
            except (OSError, TimeoutError, urllib.error.URLError, ArchiveError):
                if attempt == self.attempts:
                    raise
                time.sleep(2 ** (attempt - 1))
        raise ArchiveError(f"download failed: {item.key}")

    def _official_checksum(self, item: ArchiveObject) -> str:
        text = _read_response(self.opener, item.checksum_url).decode("utf-8", errors="strict")
        checksum = text.strip().split()[0].lower() if text.strip() else ""
        if not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ArchiveError(f"invalid official checksum for {item.key}")
        return checksum

    def _download_once(self, url: str, partial: Path) -> None:
        offset = partial.stat().st_size if partial.exists() else 0
        request = urllib.request.Request(url, headers={"Range": f"bytes={offset}-"}) if offset else url
        response = self.opener(request, timeout=60)
        try:
            status = getattr(response, "status", None) or response.getcode()
            append = offset > 0 and status == 206
            if offset and not append:
                offset = 0
            with partial.open("ab" if append else "wb") as target:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    target.write(chunk)
        finally:
            response.close()


def archive_destination(root: Path, item: ArchiveObject) -> Path:
    if item.kind in {"KLINE_15M", "KLINE_15M_DAILY"}:
        return root / "raw" / "klines" / "15m" / item.symbol / Path(item.key).name
    if item.kind == "FUNDING":
        return root / "raw" / "funding" / item.symbol / Path(item.key).name
    raise ArchiveError(f"unsupported archive object kind: {item.kind}")


def iter_kline_zip(path: Path) -> Iterator[ArchiveCandle]:
    for row in iter_csv_zip_rows(path):
        yield parse_archive_candle(row)


def iter_funding_zip(path: Path) -> Iterator[dict[str, Any]]:
    for row_number, row in enumerate(iter_csv_zip_rows(path), start=1):
        if len(row) < 3:
            raise ArchiveError(f"invalid funding row in {path.name}:{row_number}")
        yield {
            "funding_time_ms": int(row[0]),
            "funding_interval_hours": int(row[1]),
            "funding_rate": str(row[2]),
        }


def iter_csv_zip_rows(path: Path) -> Iterator[list[str]]:
    with zipfile.ZipFile(path) as archive:
        member = _single_safe_csv_member(archive)
        with archive.open(member) as source:
            text = io.TextIOWrapper(source, encoding="utf-8-sig", newline="")
            reader = csv.reader(text)
            for row_number, row in enumerate(reader, start=1):
                if not row:
                    continue
                if row_number == 1 and not str(row[0]).strip().isdigit():
                    continue
                yield row


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _single_safe_csv_member(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    members = [item for item in archive.infolist() if not item.is_dir()]
    if len(members) != 1 or not members[0].filename.lower().endswith(".csv"):
        raise ArchiveError("archive must contain exactly one CSV file")
    member_path = PurePosixPath(members[0].filename)
    if member_path.is_absolute() or ".." in member_path.parts:
        raise ArchiveError("unsafe archive member path")
    return members[0]


def _read_response(opener: Callable[..., Any], url: str) -> bytes:
    for attempt in range(1, 5):
        try:
            response = opener(url, timeout=60)
            try:
                return response.read()
            finally:
                response.close()
        except (OSError, TimeoutError, urllib.error.URLError):
            if attempt == 4:
                raise
            time.sleep(2 ** (attempt - 1))
    raise ArchiveError("archive response retries exhausted")


def _xml_text(node: ET.Element, key: str) -> str:
    child = node.find(key)
    if child is None or child.text is None:
        raise ArchiveError(f"Binance archive listing omitted {key}")
    return child.text


def _xml_optional(node: ET.Element, key: str) -> str | None:
    child = node.find(key)
    return child.text if child is not None else None
