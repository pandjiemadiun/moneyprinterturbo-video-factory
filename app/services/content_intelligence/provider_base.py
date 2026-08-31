"""Content Intelligence Provider Infrastructure.

Provides real external data sources for the Content Intelligence module.
Each provider fetches fresh data from external APIs/RSS feeds and normalizes
them into the existing RawSignal model.

Providers:
- GoogleNewsProvider: Google News RSS feeds (ID + World + categories)
- HackerNewsProvider: Hacker News API (top/new/best stories)

All providers implement a common interface and provide health monitoring,
freshness tracking, and provenance preservation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class ProviderStatus(str, Enum):
    """Health status of a data provider."""
    LIVE = "live"
    RECENT = "recent"
    STALE = "stale"
    OFFLINE = "offline"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


class Freshness(str, Enum):
    """Data freshness classification."""
    LIVE = "live"
    RECENT = "recent"
    STALE = "stale"
    UNKNOWN = "unknown"


def _classify_freshness(
    observed_at: datetime,
    fetched_at: datetime,
    live_threshold_seconds: int = 300,
    recent_threshold_seconds: int = 3600,
    stale_threshold_seconds: int = 86400,
) -> Freshness:
    """Classify data freshness based on time difference between observation and fetch."""
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    age = (fetched_at - observed_at).total_seconds()
    if age < 0:
        age = 0
    if age <= live_threshold_seconds:
        return Freshness.LIVE
    elif age <= recent_threshold_seconds:
        return Freshness.RECENT
    elif age <= stale_threshold_seconds:
        return Freshness.STALE
    else:
        return Freshness.STALE


@dataclass
class ProviderHealth:
    """Health status of a provider."""
    provider_id: str
    status: ProviderStatus = ProviderStatus.UNKNOWN
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    last_error: str = ""
    total_requests: int = 0
    total_failures: int = 0
    total_signals: int = 0
    average_response_time_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return (self.total_requests - self.total_failures) / self.total_requests

    def record_success(self, signals_count: int, response_time_ms: float) -> None:
        self.total_requests += 1
        self.total_signals += signals_count
        self.last_success_at = datetime.now(timezone.utc)
        if self.average_response_time_ms == 0:
            self.average_response_time_ms = response_time_ms
        else:
            self.average_response_time_ms = (
                0.7 * self.average_response_time_ms + 0.3 * response_time_ms
            )

    def record_failure(self, error: str) -> None:
        self.total_requests += 1
        self.total_failures += 1
        self.last_failure_at = datetime.now(timezone.utc)
        self.last_error = str(error)[:500]


@dataclass
class ProviderCapability:
    """Capabilities of a provider."""
    provider_id: str
    provider_name: str
    supports_geo: bool = False
    supports_language: bool = False
    supports_categories: bool = False
    supported_geos: list[str] = field(default_factory=list)
    supported_languages: list[str] = field(default_factory=list)
    supported_categories: list[str] = field(default_factory=list)
    requires_credentials: bool = False
    rate_limit_notes: str = ""
    data_type: str = ""


class ContentProvider:
    """Base interface for content intelligence data providers.

    Each provider must implement fetch() to return RawSignal objects
    and health() to report its status.
    """

    @property
    def provider_id(self) -> str:
        """Unique identifier for this provider."""
        raise NotImplementedError

    @property
    def provider_name(self) -> str:
        """Human-readable name for this provider."""
        raise NotImplementedError

    @property
    def enabled(self) -> bool:
        """Whether this provider is enabled."""
        return True

    def capabilities(self) -> ProviderCapability:
        """Return the capabilities of this provider."""
        raise NotImplementedError

    def fetch(
        self,
        geo: str = "ID",
        language: str = "id",
        category: str = "general",
        max_signals: int = 20,
    ) -> list:
        """Fetch raw signals from the external source.

        Args:
            geo: Geographic region code (e.g., 'ID', 'US')
            language: Language code (e.g., 'id', 'en')
            category: Content category (e.g., 'general', 'technology')
            max_signals: Maximum number of signals to return

        Returns:
            List of RawSignal objects with preserved provenance.
        """
        raise NotImplementedError

    def health(self) -> ProviderHealth:
        """Return the current health status of this provider."""
        raise NotImplementedError
