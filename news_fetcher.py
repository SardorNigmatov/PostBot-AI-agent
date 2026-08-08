"""
AI/IT yangiliklarini ochiq RSS/Atom manbalaridan oladigan modul.

Asosiy xususiyatlar:
- tashqi API kaliti talab qilmaydi;
- HTTP timeout va User-Agent ishlatadi;
- RSS ichidagi HTML ni oddiy matnga aylantiradi;
- noto'g'ri/malformed feedlarni log qiladi;
- eski, takroriy va ishlatilgan yangiliklarni filtrlab beradi;
- sinxron va asinxron interfeyslarni taqdim etadi.
"""

import asyncio
import calendar
import logging
import re
import socket
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

import feedparser

from config import NEWS_KEYWORDS, NEWS_RSS_FEEDS
from db import is_news_used

logger = logging.getLogger(__name__)


RSS_REQUEST_TIMEOUT_SECONDS = 15
RSS_MAX_RESPONSE_BYTES = 3 * 1024 * 1024
RSS_MAX_ENTRIES_PER_FEED = 25
RSS_MAX_NEWS_AGE_DAYS = 30
RSS_TITLE_MAX_CHARS = 400
RSS_SUMMARY_MAX_CHARS = 2500

RSS_USER_AGENT = (
    "Mozilla/5.0 (compatible; ML-Engineer-Telegram-Bot/1.0; "
    "+https://t.me/ml_enginner)"
)

TRACKING_QUERY_KEYS = frozenset(
    {
        "fbclid",
        "gclid",
        "dclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "ref",
        "ref_src",
        "source",
    }
)


class RSSFetchError(RuntimeError):
    """RSS manbasini olish yoki o'qishdagi boshqariladigan xato."""


class _HTMLTextExtractor(HTMLParser):
    """RSS summary ichidagi HTML teglarni xavfsiz oddiy matnga aylantiradi."""

    BLOCK_TAGS = frozenset(
        {
            "p",
            "div",
            "section",
            "article",
            "header",
            "footer",
            "aside",
            "li",
            "ul",
            "ol",
            "br",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "blockquote",
        }
    )

    IGNORED_TAGS = frozenset({"script", "style", "noscript", "svg"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized_tag = tag.lower()

        if normalized_tag in self.IGNORED_TAGS:
            self._ignored_depth += 1
            return

        if self._ignored_depth == 0 and normalized_tag in self.BLOCK_TAGS:
            self._parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()

        if normalized_tag in self.IGNORED_TAGS:
            if self._ignored_depth > 0:
                self._ignored_depth -= 1
            return

        if self._ignored_depth == 0 and normalized_tag in self.BLOCK_TAGS:
            self._parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def _strip_html(value: Any) -> str:
    """HTML yoki oddiy matnni tozalangan bir qatorli matnga aylantiradi."""
    if value is None:
        return ""

    raw_text = str(value)

    parser = _HTMLTextExtractor()
    try:
        parser.feed(raw_text)
        parser.close()
        text = parser.get_text()
    except Exception:
        logger.debug("RSS HTML parser xatosi; regex fallback ishlatildi.")
        text = re.sub(r"<[^>]+>", " ", raw_text)

    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _truncate_text(text: str, max_chars: int) -> str:
    """Matnni so'z o'rtasida kesmasdan taxminiy maksimal uzunlikka tushiradi."""
    normalized = re.sub(r"\s+", " ", text).strip()

    if len(normalized) <= max_chars:
        return normalized

    shortened = normalized[: max_chars + 1]
    last_space = shortened.rfind(" ")

    if last_space >= int(max_chars * 0.7):
        shortened = shortened[:last_space]
    else:
        shortened = shortened[:max_chars]

    return shortened.rstrip(" ,.;:-") + "…"


def _normalize_url(value: Any) -> str | None:
    """
    RSS entry URL manzilini tekshiradi va tracking parametrlarni olib tashlaydi.
    """
    if value is None:
        return None

    raw_url = str(value).strip()
    if not raw_url:
        return None

    parsed = urlparse(raw_url)

    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None

    filtered_query: list[tuple[str, str]] = []

    for key, query_value in parse_qsl(
        parsed.query,
        keep_blank_values=True,
    ):
        lowered_key = key.lower()

        if lowered_key.startswith("utm_"):
            continue

        if lowered_key in TRACKING_QUERY_KEYS:
            continue

        filtered_query.append((key, query_value))

    normalized_path = parsed.path or "/"

    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            normalized_path,
            parsed.params,
            urlencode(filtered_query, doseq=True),
            "",
        )
    )


def _entry_summary(entry: Mapping[str, Any]) -> str:
    """summary/description bo'lmasa Atom content maydonidan matn oladi."""
    candidates: list[Any] = [
        entry.get("summary"),
        entry.get("description"),
    ]

    content_items = entry.get("content")
    if isinstance(content_items, list):
        for item in content_items:
            if isinstance(item, Mapping):
                candidates.append(item.get("value"))

    for candidate in candidates:
        cleaned = _strip_html(candidate)
        if cleaned:
            return _truncate_text(cleaned, RSS_SUMMARY_MAX_CHARS)

    return ""


def _entry_title(entry: Mapping[str, Any]) -> str:
    title = _strip_html(entry.get("title"))
    return _truncate_text(title, RSS_TITLE_MAX_CHARS)


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Qisqa kalitlar uchun word boundary ishlatadi."""
    escaped = re.escape(keyword.strip().lower())

    if not escaped:
        return re.compile(r"(?!x)x")

    return re.compile(
        rf"(?<![a-z0-9]){escaped}(?![a-z0-9])",
        flags=re.IGNORECASE,
    )


KEYWORD_PATTERNS = tuple(
    _keyword_pattern(str(keyword)) for keyword in NEWS_KEYWORDS if str(keyword).strip()
)


def _is_relevant(
    entry: Mapping[str, Any],
    feed_is_ai_specific: bool,
) -> bool:
    if feed_is_ai_specific:
        return True

    searchable_text = " ".join(
        filter(
            None,
            (
                _entry_title(entry),
                _entry_summary(entry),
                _strip_html(entry.get("tags")),
            ),
        )
    ).lower()

    return any(pattern.search(searchable_text) for pattern in KEYWORD_PATTERNS)


def _published_timestamp(entry: Mapping[str, Any]) -> float:
    """Feedparser tomonidan parse qilingan sanani UTC Unix timestampga aylantiradi."""
    parsed_time = (
        entry.get("published_parsed")
        or entry.get("updated_parsed")
        or entry.get("created_parsed")
    )

    if parsed_time is None:
        return 0.0

    try:
        return float(calendar.timegm(parsed_time))
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _is_recent_enough(timestamp: float) -> bool:
    """Sanasi mavjud entry juda eski bo'lsa chiqarib tashlaydi."""
    if timestamp <= 0:
        return True

    cutoff = datetime.now(timezone.utc) - timedelta(days=RSS_MAX_NEWS_AGE_DAYS)
    return timestamp >= cutoff.timestamp()


def _download_feed(url: str) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": RSS_USER_AGENT,
            "Accept": (
                "application/rss+xml, application/atom+xml, "
                "application/xml, text/xml, */*;q=0.5"
            ),
        },
        method="GET",
    )

    try:
        with urlopen(
            request,
            timeout=RSS_REQUEST_TIMEOUT_SECONDS,
        ) as response:
            status = getattr(response, "status", 200)

            if status is not None and not 200 <= int(status) < 300:
                raise RSSFetchError(f"RSS server HTTP {status} status qaytardi.")

            content_length_header = response.headers.get("Content-Length")
            if content_length_header:
                try:
                    content_length = int(content_length_header)
                except ValueError:
                    content_length = 0

                if content_length > RSS_MAX_RESPONSE_BYTES:
                    raise RSSFetchError("RSS javobi ruxsat etilgan hajmdan katta.")

            payload = response.read(RSS_MAX_RESPONSE_BYTES + 1)

    except HTTPError as exc:
        raise RSSFetchError(f"HTTP xatosi: {exc.code} {exc.reason}") from exc
    except (URLError, socket.timeout, TimeoutError, OSError) as exc:
        raise RSSFetchError(f"Tarmoq xatosi: {exc}") from exc

    if not payload:
        raise RSSFetchError("RSS server bo'sh javob qaytardi.")

    if len(payload) > RSS_MAX_RESPONSE_BYTES:
        raise RSSFetchError("RSS javobi ruxsat etilgan hajmdan katta.")

    return payload


def _parse_feed(url: str) -> Any:
    payload = _download_feed(url)
    parsed = feedparser.parse(payload)

    if getattr(parsed, "bozo", False):
        bozo_exception = getattr(parsed, "bozo_exception", None)
        logger.warning(
            "RSS to'liq valid emas (%s): %s",
            url,
            bozo_exception or "noma'lum parse xatosi",
        )

    entries = getattr(parsed, "entries", None)
    if not entries:
        logger.info("RSS entry topilmadi: %s", url)

    return parsed


def _candidate_from_entry(
    entry: Mapping[str, Any],
    *,
    source_name: str,
    feed_url: str,
    feed_is_ai_specific: bool,
) -> dict[str, Any] | None:
    link = _normalize_url(entry.get("link"))

    if link is None:
        links = entry.get("links")
        if isinstance(links, list):
            for link_item in links:
                if not isinstance(link_item, Mapping):
                    continue

                relation = str(link_item.get("rel", "alternate")).lower()
                candidate_url = _normalize_url(link_item.get("href"))

                if candidate_url and relation in {"alternate", ""}:
                    link = candidate_url
                    break

    if link is None:
        return None

    title = _entry_title(entry)
    if not title:
        logger.debug("Sarlavhasiz RSS entry tashlab yuborildi: %s", link)
        return None

    if not _is_relevant(entry, feed_is_ai_specific):
        return None

    timestamp = _published_timestamp(entry)
    if not _is_recent_enough(timestamp):
        return None

    summary = _entry_summary(entry)

    if not summary:
        summary = "RSS manbasida qisqacha tavsif berilmagan."

    return {
        "title": title,
        "summary": summary,
        "link": link,
        "source": _truncate_text(source_name, 200),
        "timestamp": timestamp,
        "feed_url": feed_url,
    }


def _candidate_sort_key(candidate: Mapping[str, Any]) -> tuple[float, str]:
    timestamp = float(candidate.get("timestamp") or 0.0)
    title = str(candidate.get("title") or "")
    return timestamp, title


def fetch_latest_news_item() -> dict[str, Any] | None:
    """
    Barcha RSS manbalarni tekshiradi va hali ishlatilmagan eng yangi AI/IT
    yangiligini qaytaradi. Topilmasa None qaytaradi.
    """
    candidates_by_url: dict[str, dict[str, Any]] = {}

    for feed_url, feed_is_ai_specific in NEWS_RSS_FEEDS:
        try:
            parsed = _parse_feed(feed_url)
        except RSSFetchError as exc:
            logger.warning(
                "RSS manbasini olishda xatolik (%s): %s",
                feed_url,
                exc,
            )
            continue
        except Exception:
            logger.exception(
                "Kutilmagan RSS xatosi: %s",
                feed_url,
            )
            continue

        source_name = (
            _strip_html(getattr(parsed, "feed", {}).get("title", ""))
            or urlparse(feed_url).netloc
        )

        entries = list(getattr(parsed, "entries", []) or [])
        for entry in entries[:RSS_MAX_ENTRIES_PER_FEED]:
            if not isinstance(entry, Mapping):
                continue

            candidate = _candidate_from_entry(
                entry,
                source_name=source_name,
                feed_url=feed_url,
                feed_is_ai_specific=bool(feed_is_ai_specific),
            )

            if candidate is None:
                continue

            link = candidate["link"]
            existing = candidates_by_url.get(link)

            if existing is None or _candidate_sort_key(candidate) > _candidate_sort_key(
                existing
            ):
                candidates_by_url[link] = candidate

    if not candidates_by_url:
        logger.info("Mavzuga mos RSS yangiligi topilmadi.")
        return None

    sorted_candidates = sorted(
        candidates_by_url.values(),
        key=_candidate_sort_key,
        reverse=True,
    )

    for candidate in sorted_candidates:
        try:
            already_used = is_news_used(candidate["link"])
        except Exception:
            logger.exception(
                "Yangilik ishlatilganini bazadan tekshirib bo'lmadi: %s",
                candidate["link"],
            )
            raise

        if already_used:
            continue

        result = dict(candidate)
        result.pop("feed_url", None)

        logger.info(
            "Yangi RSS yangiligi tanlandi: %s (%s)",
            result["title"],
            result["source"],
        )
        return result

    logger.info("Barcha mos RSS yangiliklari oldin ishlatilgan.")
    return None


async def fetch_latest_news_item_async() -> dict[str, Any] | None:
    """
    RSS va SQLite chaqiruvlarini worker threadda bajaradi, shuning uchun
    aiogram/webhook event loop bloklanmaydi.
    """
    return await asyncio.to_thread(fetch_latest_news_item)