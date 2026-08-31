"""Hacker News Provider.

Fetches real-time tech news from the Hacker News API.
Provides engagement metrics (score, comments) for trend strength.

Data source: Hacker News API (https://github.com/HackerNews/API)
- Free, no API key required
- Returns real, fresh stories
- Provides score (upvotes) and descendants (comment count)
- Provides timestamps for freshness tracking
"""

from __future__ import annotations

import time
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


# Hacker News API endpoints
HN_BASE_URL = "https://hacker-news.firebaseio.com/v0"
HN_ENDPOINTS = {
    "top": f"{HN_BASE_URL}/topstories.json",
    "new": f"{HN_BASE_URL}/newstories.json",
    "best": f"{HN_BASE_URL}/beststories.json",
}

# Request timeout in seconds
REQUEST_TIMEOUT = 15

# Maximum stories to fetch IDs for (then filter)
MAX_STORY_IDS = 50


class HackerNewsProvider(ContentProvider):
    """Provider for Hacker News API.

    Fetches real tech news from Hacker News and normalizes into RawSignal objects.
    Uses story score and comment count as confidence/signal strength indicators.
    """

    def __init__(
        self,
        enabled: bool = True,
        timeout: int = REQUEST_TIMEOUT,
        story_type: str = "top",
    ):
        self._enabled = enabled
        self._timeout = timeout
        self._story_type = story_type if story_type in HN_ENDPOINTS else "top"
        self._health = ProviderHealth(
            provider_id=self.provider_id,
        )

    @property
    def provider_id(self) -> str:
        return "hackernews"

    @property
    def provider_name(self) -> str:
        return "Hacker News"

    @property
    def enabled(self) -> bool:
        return self._enabled

    def capabilities(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            supports_geo=False,
            supports_language=False,
            supports_categories=False,
            supported_geos=["global"],
            supported_languages=["en"],
            supported_categories=["technology"],
            requires_credentials=False,
            rate_limit_notes="No rate limit; be respectful with request frequency",
            data_type="tech_news",
        )

    def fetch(
        self,
        geo: str = "global",
        language: str = "en",
        category: str = "technology",
        max_signals: int = 20,
    ) -> list[RawSignal]:
        """Fetch stories from Hacker News.

        Args:
            geo: Ignored (HN is global)
            language: Ignored (HN is English)
            category: Ignored (HN is technology-focused)
            max_signals: Maximum number of signals to return

        Returns:
            List of RawSignal objects with real HN data.
        """
        if not self._enabled:
            return []

        start_time = time.time()
        signals: list[RawSignal] = []

        try:
            story_ids = self._fetch_story_ids()
            if not story_ids:
                self._health.record_failure("No story IDs returned")
                return signals

            fetched_at = datetime.now(timezone.utc)
            signals = self._fetch_story_details(
                story_ids[:max_signals],
                fetched_at,
                max_signals,
            )

            elapsed_ms = (time.time() - start_time) * 1000
            self._health.record_success(len(signals), elapsed_ms)

            logger.info(
                f"Hacker News: fetched {len(signals)} signals "
                f"({elapsed_ms:.0f}ms)"
            )

        except requests.exceptions.Timeout:
            elapsed_ms = (time.time() - start_time) * 1000
            self._health.record_failure("Request timeout")
            logger.warning(f"Hacker News timeout after {elapsed_ms:.0f}ms")

        except requests.exceptions.HTTPError as e:
            self._health.record_failure(f"HTTP {e.response.status_code if e.response else 'unknown'}")
            logger.warning(f"Hacker News HTTP error: {e}")

        except Exception as e:
            self._health.record_failure(str(e))
            logger.warning(f"Hacker News fetch failed: {e}")

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

    def _fetch_story_ids(self) -> list[int]:
        """Fetch story IDs from the HN API."""
        url = HN_ENDPOINTS[self._story_type]
        response = requests.get(url, timeout=self._timeout)
        response.raise_for_status()
        ids = response.json()
        if not isinstance(ids, list):
            return []
        return ids[:MAX_STORY_IDS]

    def _fetch_story_details(
        self,
        story_ids: list[int],
        fetched_at: datetime,
        max_signals: int,
    ) -> list[RawSignal]:
        """Fetch details for each story ID."""
        signals: list[RawSignal] = []

        for story_id in story_ids:
            if len(signals) >= max_signals:
                break

            try:
                url = f"{HN_BASE_URL}/item/{story_id}.json"
                response = requests.get(url, timeout=self._timeout)
                response.raise_for_status()
                story = response.json()

                if not story or not story.get("title"):
                    continue

                title = story.get("title", "")
                score = story.get("score", 0)
                descendants = story.get("descendants", 0)
                story_time = story.get("time", 0)
                url = story.get("url", "")
                by = story.get("by", "")

                # Convert Unix timestamp to datetime
                if story_time:
                    observed_at = datetime.fromtimestamp(story_time, tz=timezone.utc)
                else:
                    observed_at = fetched_at

                # Confidence based on engagement (score + comments)
                # Normalize: score > 100 is high confidence
                engagement = score + descendants
                confidence = min(0.95, 0.5 + (engagement / 500.0))
                confidence = max(0.5, confidence)

                # Build evidence list
                evidence = []
                if score:
                    evidence.append(f"score={score}")
                if descendants:
                    evidence.append(f"comments={descendants}")
                if by:
                    evidence.append(f"author={by}")
                if url:
                    evidence.append(f"url={url}")

                signal = RawSignal(
                    source=TrendSource.SOCIAL,
                    topic=title,
                    observed_at=observed_at,
                    provider=self.provider_id,
                    confidence=round(confidence, 4),
                    raw_payload={
                        "hn_id": story_id,
                        "score": score,
                        "descendants": descendants,
                        "time": story_time,
                        "url": url,
                        "by": by,
                    },
                    metadata={
                        "provider_name": self.provider_name,
                        "geo": "global",
                        "language": "en",
                        "category": "technology",
                        "fetched_at": fetched_at.isoformat(),
                        "source_url": url,
                        "source_name": f"Hacker News (by {by})" if by else "Hacker News",
                        "score": score,
                        "comments": descendants,
                    },
                )
                signals.append(signal)

            except requests.exceptions.HTTPError as e:
                logger.debug(f"Failed to fetch HN story {story_id}: {e}")
                continue
            except Exception as e:
                logger.debug(f"Failed to parse HN story {story_id}: {e}")
                continue

        return signals
