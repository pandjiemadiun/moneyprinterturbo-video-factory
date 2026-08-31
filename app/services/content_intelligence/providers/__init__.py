"""Provider Registry.

Manages all content intelligence data providers.
Handles provider registration, health monitoring, and multi-provider aggregation.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from app.services.content_intelligence.models import (
    RawSignal,
)
from app.services.content_intelligence.provider_base import (
    ContentProvider,
    ProviderHealth,
    ProviderStatus,
)
from app.services.content_intelligence.providers.google_news import (
    GoogleNewsProvider,
)
from app.services.content_intelligence.providers.hackernews import (
    HackerNewsProvider,
)


class ProviderRegistry:
    """Registry for managing content intelligence data providers.

    Handles provider registration, fetching, health monitoring,
    and multi-provider signal aggregation.
    """

    def __init__(self):
        self._providers: dict[str, ContentProvider] = {}

    def register(self, provider: ContentProvider) -> None:
        """Register a provider."""
        self._providers[provider.provider_id] = provider
        logger.info(
            f"Registered content intelligence provider: "
            f"{provider.provider_id} ({provider.provider_name})"
        )

    def unregister(self, provider_id: str) -> None:
        """Unregister a provider."""
        if provider_id in self._providers:
            del self._providers[provider_id]
            logger.info(f"Unregistered provider: {provider_id}")

    def get_provider(self, provider_id: str) -> Optional[ContentProvider]:
        """Get a provider by ID."""
        return self._providers.get(provider_id)

    @property
    def providers(self) -> dict[str, ContentProvider]:
        """Get all registered providers."""
        return dict(self._providers)

    @property
    def enabled_providers(self) -> dict[str, ContentProvider]:
        """Get all enabled providers."""
        return {
            k: v for k, v in self._providers.items() if v.enabled
        }

    def fetch_all(
        self,
        geo: str = "ID",
        language: str = "id",
        category: str = "general",
        max_signals_per_provider: int = 20,
    ) -> tuple[list[RawSignal], dict[str, ProviderHealth]]:
        """Fetch signals from all enabled providers.

        Args:
            geo: Geographic region
            language: Language code
            category: Content category
            max_signals_per_provider: Maximum signals per provider

        Returns:
            Tuple of (all signals, provider health dict)
        """
        all_signals: list[RawSignal] = []
        health_results: dict[str, ProviderHealth] = {}

        for provider_id, provider in self.enabled_providers.items():
            try:
                signals = provider.fetch(
                    geo=geo,
                    language=language,
                    category=category,
                    max_signals=max_signals_per_provider,
                )
                all_signals.extend(signals)
                health_results[provider_id] = provider.health()
            except Exception as e:
                logger.warning(
                    f"Provider {provider_id} failed during fetch_all: {e}"
                )
                health = provider.health()
                health.status = ProviderStatus.OFFLINE
                health.record_failure(str(e))
                health_results[provider_id] = health

        # Log summary
        successful = sum(
            1 for h in health_results.values()
            if h.status in (ProviderStatus.LIVE, ProviderStatus.STALE)
        )
        failed = len(health_results) - successful
        logger.info(
            f"Provider fetch summary: {len(all_signals)} total signals, "
            f"{successful} providers OK, {failed} failed"
        )

        return all_signals, health_results

    def get_health_summary(self) -> dict[str, ProviderHealth]:
        """Get health status for all providers."""
        return {
            provider_id: provider.health()
            for provider_id, provider in self._providers.items()
        }

    def create_default_registry(
        self,
        enable_google_news: bool = True,
        enable_hackernews: bool = True,
        geo: str = "ID",
        language: str = "id",
    ) -> "ProviderRegistry":
        """Create a registry with default providers.

        Args:
            enable_google_news: Whether to enable Google News RSS
            enable_hackernews: Whether to enable Hacker News
            geo: Default geographic region
            language: Default language

        Returns:
            Configured ProviderRegistry
        """
        if enable_google_news:
            self.register(GoogleNewsProvider(enabled=True, geo=geo, language=language))

        if enable_hackernews:
            self.register(HackerNewsProvider(enabled=True))

        return self


def create_provider_registry(
    enable_google_news: bool = True,
    enable_hackernews: bool = True,
    geo: str = "ID",
    language: str = "id",
) -> ProviderRegistry:
    """Factory function to create a default provider registry."""
    registry = ProviderRegistry()
    registry.create_default_registry(
        enable_google_news=enable_google_news,
        enable_hackernews=enable_hackernews,
        geo=geo,
        language=language,
    )
    return registry
