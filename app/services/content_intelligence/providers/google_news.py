"""Google News RSS Provider.

Fetches real-time news from Google News RSS feeds.
Supports multiple geographic regions and categories.

Data source: Google News RSS (https://news.google.com/rss)
- Free, no API key required
- Returns real, fresh news articles
- Supports geo/language filtering
- Provides pubDate timestamps for freshness tracking
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional

import requests
from loguru import logger

from app.services.content_intelligence.models import (
    RawSignal,
    TrendSource,
)
from app.services.content_intelligence.provider_base import (
    ContentProvider,
    ProviderCapability,
    ProviderHealth,
    ProviderStatus,
)


# Google News RSS endpoint templates
RSS_ENDPOINTS = {
    "general_id": "https://news.google.com/rss?hl={language}&gl={geo}&ceid={geo}:{language}",
    "general": "https://news.google.com/rss?hl={language}&gl={geo}&ceid={geo}:{language}",
    "world": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pWVXlnQVAB?hl={language}&gl={geo}&ceid={geo}:{language}",
    "technology": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pWVXlnQVAB?hl={language}&gl={geo}&ceid={geo}:{language}",
    "business": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB?hl={language}&gl={geo}&ceid={geo}:{language}",
    "sports": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtVnVHZ0pWVXlnQVAB?hl={language}&gl={geo}&ceid={geo}:{language}",
    "entertainment": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtVnVHZ0pWVXlnQVAB?hl={language}&gl={geo}&ceid={geo}:{language}",
    "health": "https://news.google.com/rss/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtVnVHZ0pWVXlnQVAB?hl={language}&gl={geo}&ceid={geo}:{language}",
    "science": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pWVXlnQVAB?hl={language}&gl={geo}&ceid={geo}:{language}",
}

# Default geo/language mappings
DEFAULT_GEO = "ID"
DEFAULT_LANGUAGE = "id"

# Request timeout in seconds
REQUEST_TIMEOUT = 15


def _parse_rfc822_date(date_str: str) -> Optional[datetime]:
    """Parse RFC 822 date format from RSS feeds."""
    if not date_str:
        return None
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        pass
    return None


def _extract_cdata(text: str) -> str:
    """Extract text from CDATA section if present."""
    if not text:
        return ""
    text = text.strip()
    if text.startswith("<![CDATA[") and text.endswith("]]>"):
        text = text[9:-3]
    return text.strip()


class GoogleNewsProvider(ContentProvider):
    """Provider for Google News RSS feeds.

    Fetches real news from Google News RSS and normalizes into RawSignal objects.
    Supports Indonesian and international news with category filtering.
    """

    def __init__(
        self,
        enabled: bool = True,
        timeout: int = REQUEST_TIMEOUT,
        geo: str = DEFAULT_GEO,
        language: str = DEFAULT_LANGUAGE,
    ):
        self._enabled = enabled
        self._timeout = timeout
        self._default_geo = geo
        self._default_language = language
        self._health = ProviderHealth(
            provider_id=self.provider_id,
        )

    @property
    def provider_id(self) -> str:
        return "google_news_rss"

    @property
    def provider_name(self) -> str:
        return "Google News RSS"

    @property
    def enabled(self) -> bool:
        return self._enabled

    def capabilities(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            supports_geo=True,
            supports_language=True,
            supports_categories=True,
            supported_geos=["ID", "US", "GB", "AU", "MY", "SG"],
            supported_languages=["id", "en"],
            supported_categories=[
                "general", "world", "technology", "business",
                "sports", "entertainment", "health", "science",
            ],
            requires_credentials=False,
            rate_limit_notes="No official rate limit; be respectful with request frequency",
            data_type="news",
        )

    def fetch(
        self,
        geo: str = "ID",
        language: str = "id",
        category: str = "general",
        max_signals: int = 20,
    ) -> list[RawSignal]:
        """Fetch news from Google News RSS.

        Args:
            geo: Geographic region (e.g., 'ID', 'US')
            language: Language code (e.g., 'id', 'en')
            category: News category
            max_signals: Maximum number of signals to return

        Returns:
            List of RawSignal objects with real news data.
        """
        if not self._enabled:
            return []

        start_time = time.time()
        signals: list[RawSignal] = []

        try:
            url = self._build_url(geo, language, category)
            logger.debug(f"Fetching Google News RSS: {url}")

            response = requests.get(
                url,
                timeout=self._timeout,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; ContentIntelligence/1.0)",
                    "Accept": "application/xml, text/xml, */*",
                },
            )
            response.raise_for_status()

            signals = self._parse_feed(response.text, geo, language, max_signals)
            elapsed_ms = (time.time() - start_time) * 1000
            self._health.record_success(len(signals), elapsed_ms)

            logger.info(
                f"Google News RSS: fetched {len(signals)} signals "
                f"for geo={geo}, lang={language}, category={category} "
                f"({elapsed_ms:.0f}ms)"
            )

        except requests.exceptions.Timeout:
            elapsed_ms = (time.time() - start_time) * 1000
            self._health.record_failure("Request timeout")
            logger.warning(f"Google News RSS timeout after {elapsed_ms:.0f}ms")

        except requests.exceptions.HTTPError as e:
            self._health.record_failure(f"HTTP {e.response.status_code if e.response else 'unknown'}")
            logger.warning(f"Google News RSS HTTP error: {e}")

        except Exception as e:
            self._health.record_failure(str(e))
            logger.warning(f"Google News RSS fetch failed: {e}")

        return signals

    def health(self) -> ProviderHealth:
        """Return current health status."""
        if not self._enabled:
            self._health.status = ProviderStatus.DISABLED
        elif self._health.total_requests == 0:
            self._health.status = ProviderStatus.UNKNOWN
        elif self._health.success_rate >= 0.8:
            self._health.status = ProviderStatus.LIVE
        elif self._health.success_rate >= 0.5:
            self._health.status = ProviderStatus.STALE
        else:
            self._health.status = ProviderStatus.OFFLINE
        return self._health

    def _build_url(self, geo: str, language: str, category: str) -> str:
        """Build the RSS URL for the given parameters."""
        category_key = category if category in RSS_ENDPOINTS else "general"
        template = RSS_ENDPOINTS.get(category_key, RSS_ENDPOINTS["general"])
        return template.format(geo=geo, language=language)

    def _parse_feed(
        self,
        xml_content: str,
        geo: str,
        language: str,
        max_signals: int,
        category: str = "general",
    ) -> list[RawSignal]:
        """Parse RSS XML content into RawSignal objects."""
        signals: list[RawSignal] = []

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            logger.warning(f"Failed to parse Google News RSS XML: {e}")
            return signals

        # Find all item elements
        channel = root.find(".//channel")
        if channel is None:
            return signals

        items = channel.findall("item")
        fetched_at = datetime.now(timezone.utc)

        for item in items[:max_signals]:
            try:
                title_elem = item.find("title")
                link_elem = item.find("link")
                pub_date_elem = item.find("pubDate")
                source_elem = item.find("source")
                description_elem = item.find("description")

                title = _extract_cdata(title_elem.text) if title_elem is not None and title_elem.text else ""
                if not title:
                    continue

                link = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
                source_name = _extract_cdata(source_elem.text) if source_elem is not None and source_elem.text else ""

                # Parse publication date for freshness
                pub_date_str = pub_date_elem.text if pub_date_elem is not None else None
                observed_at = _parse_rfc822_date(pub_date_str) if pub_date_str else fetched_at
                if observed_at is None:
                    observed_at = fetched_at

                # Build evidence list
                evidence = []
                if source_name:
                    evidence.append(f"source={source_name}")
                if pub_date_str:
                    evidence.append(f"published={pub_date_str}")
                if link:
                    evidence.append(f"url={link}")

                signal = RawSignal(
                    source=TrendSource.RSS,
                    topic=title,
                    observed_at=observed_at,
                    provider=self.provider_id,
                    confidence=0.8,
                    raw_payload={
                        "link": link,
                        "source_name": source_name,
                        "pub_date": pub_date_str,
                        "category": category,
                    },
                    metadata={
                        "provider_name": self.provider_name,
                        "geo": geo,
                        "language": language,
                        "category": category,
                        "fetched_at": fetched_at.isoformat(),
                        "source_url": link,
                        "source_name": source_name,
                    },
                )
                signals.append(signal)

            except Exception as e:
                logger.debug(f"Failed to parse RSS item: {e}")
                continue

        return signals
