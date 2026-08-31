"""Tests for Content Intelligence data providers.

Tests provider contracts, parsing, health monitoring, and failure handling.
"""

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.content_intelligence.models import (
    RawSignal,
    TrendSource,
)
from app.services.content_intelligence.provider_base import (
    ContentProvider,
    ProviderCapability,
    ProviderHealth,
    ProviderStatus,
    Freshness,
    _classify_freshness,
)
from app.services.content_intelligence.providers.google_news import (
    GoogleNewsProvider,
    _extract_cdata,
    _parse_rfc822_date,
)
from app.services.content_intelligence.providers.hackernews import (
    HackerNewsProvider,
)
from app.services.content_intelligence.providers import (
    ProviderRegistry,
    create_provider_registry,
)


class TestProviderBase(unittest.TestCase):
    """Tests for provider base classes."""

    def test_classify_freshness_live(self):
        now = datetime.now(timezone.utc)
        result = _classify_freshness(now, now)
        self.assertEqual(result, Freshness.LIVE)

    def test_classify_freshness_recent(self):
        now = datetime.now(timezone.utc)
        observed = now - timedelta(minutes=30)
        result = _classify_freshness(observed, now)
        self.assertEqual(result, Freshness.RECENT)

    def test_classify_freshness_stale(self):
        now = datetime.now(timezone.utc)
        observed = now - timedelta(hours=2)
        result = _classify_freshness(observed, now)
        self.assertEqual(result, Freshness.STALE)

    def test_classify_freshness_very_stale(self):
        now = datetime.now(timezone.utc)
        observed = now - timedelta(days=2)
        result = _classify_freshness(observed, now)
        self.assertEqual(result, Freshness.STALE)

    def test_provider_health_success_rate(self):
        health = ProviderHealth(provider_id="test")
        self.assertEqual(health.success_rate, 0.0)
        health.record_success(5, 100.0)
        self.assertEqual(health.success_rate, 1.0)
        health.record_failure("error")
        self.assertAlmostEqual(health.success_rate, 0.5)

    def test_provider_health_record_success(self):
        health = ProviderHealth(provider_id="test")
        health.record_success(10, 200.0)
        self.assertEqual(health.total_requests, 1)
        self.assertEqual(health.total_signals, 10)
        self.assertIsNotNone(health.last_success_at)
        self.assertEqual(health.average_response_time_ms, 200.0)

    def test_provider_health_record_failure(self):
        health = ProviderHealth(provider_id="test")
        health.record_failure("Connection error")
        self.assertEqual(health.total_requests, 1)
        self.assertEqual(health.total_failures, 1)
        self.assertIsNotNone(health.last_failure_at)
        self.assertEqual(health.last_error, "Connection error")


class TestGoogleNewsProvider(unittest.TestCase):
    """Tests for Google News RSS provider."""

    def test_provider_id(self):
        provider = GoogleNewsProvider()
        self.assertEqual(provider.provider_id, "google_news_rss")

    def test_provider_name(self):
        provider = GoogleNewsProvider()
        self.assertEqual(provider.provider_name, "Google News RSS")

    def test_enabled_default(self):
        provider = GoogleNewsProvider()
        self.assertTrue(provider.enabled)

    def test_disabled_provider(self):
        provider = GoogleNewsProvider(enabled=False)
        self.assertFalse(provider.enabled)
        signals = provider.fetch()
        self.assertEqual(signals, [])

    def test_capabilities(self):
        provider = GoogleNewsProvider()
        caps = provider.capabilities()
        self.assertTrue(caps.supports_geo)
        self.assertTrue(caps.supports_language)
        self.assertTrue(caps.supports_categories)
        self.assertIn("ID", caps.supported_geos)
        self.assertIn("id", caps.supported_languages)
        self.assertFalse(caps.requires_credentials)

    def test_health_initial(self):
        provider = GoogleNewsProvider()
        health = provider.health()
        self.assertEqual(health.status, ProviderStatus.UNKNOWN)

    def test_parse_rfc822_date(self):
        dt = _parse_rfc822_date("Mon, 31 Aug 2026 00:32:53 GMT")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 8)
        self.assertEqual(dt.day, 31)

    def test_parse_rfc822_date_none(self):
        dt = _parse_rfc822_date(None)
        self.assertIsNone(dt)

    def test_parse_rfc822_date_empty(self):
        dt = _parse_rfc822_date("")
        self.assertIsNone(dt)

    def test_extract_cdata_plain(self):
        result = _extract_cdata("Plain text")
        self.assertEqual(result, "Plain text")

    def test_extract_cdata_wrapped(self):
        result = _extract_cdata("<![CDATA[Some content]]>")
        self.assertEqual(result, "Some content")

    def test_extract_cdata_none(self):
        result = _extract_cdata(None)
        self.assertEqual(result, "")

    def test_parse_feed_valid_xml(self):
        provider = GoogleNewsProvider()
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <item>
                    <title>Test News Title</title>
                    <link>https://example.com/news</link>
                    <pubDate>Mon, 31 Aug 2026 00:32:53 GMT</pubDate>
                    <source url="https://example.com">Example News</source>
                </item>
            </channel>
        </rss>"""
        signals = provider._parse_feed(xml, "ID", "id", 10, category="general")
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].topic, "Test News Title")
        self.assertEqual(signals[0].source, TrendSource.RSS)
        self.assertEqual(signals[0].provider, "google_news_rss")
        self.assertEqual(signals[0].metadata.get("geo"), "ID")
        self.assertEqual(signals[0].metadata.get("source_name"), "Example News")

    def test_parse_feed_empty_xml(self):
        provider = GoogleNewsProvider()
        signals = provider._parse_feed("", "ID", "id", 10)
        self.assertEqual(signals, [])

    def test_parse_feed_invalid_xml(self):
        provider = GoogleNewsProvider()
        signals = provider._parse_feed("<invalid>", "ID", "id", 10)
        self.assertEqual(signals, [])

    def test_parse_feed_no_items(self):
        provider = GoogleNewsProvider()
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel></channel></rss>"""
        signals = provider._parse_feed(xml, "ID", "id", 10)
        self.assertEqual(signals, [])

    def test_parse_feed_max_signals(self):
        provider = GoogleNewsProvider()
        items = ""
        for i in range(10):
            items += f"<item><title>News {i}</title><link>https://example.com/{i}</link></item>"
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel>{items}</channel></rss>"""
        signals = provider._parse_feed(xml, "ID", "id", 5)
        self.assertEqual(len(signals), 5)

    def test_parse_feed_preserves_timestamps(self):
        provider = GoogleNewsProvider()
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <item>
                    <title>Test</title>
                    <pubDate>Mon, 31 Aug 2026 00:32:53 GMT</pubDate>
                </item>
            </channel>
        </rss>"""
        signals = provider._parse_feed(xml, "ID", "id", 10)
        self.assertEqual(len(signals), 1)
        self.assertIsNotNone(signals[0].observed_at)


class TestHackerNewsProvider(unittest.TestCase):
    """Tests for Hacker News provider."""

    def test_provider_id(self):
        provider = HackerNewsProvider()
        self.assertEqual(provider.provider_id, "hackernews")

    def test_provider_name(self):
        provider = HackerNewsProvider()
        self.assertEqual(provider.provider_name, "Hacker News")

    def test_enabled_default(self):
        provider = HackerNewsProvider()
        self.assertTrue(provider.enabled)

    def test_disabled_provider(self):
        provider = HackerNewsProvider(enabled=False)
        self.assertFalse(provider.enabled)
        signals = provider.fetch()
        self.assertEqual(signals, [])

    def test_capabilities(self):
        provider = HackerNewsProvider()
        caps = provider.capabilities()
        self.assertFalse(caps.supports_geo)
        self.assertFalse(caps.supports_language)
        self.assertFalse(caps.supports_categories)
        self.assertFalse(caps.requires_credentials)
        self.assertEqual(caps.data_type, "tech_news")

    def test_fetch_story_details(self):
        provider = HackerNewsProvider()
        fetched_at = datetime.now(timezone.utc)
        signals = provider._fetch_story_details(
            [12345],
            fetched_at,
            5,
        )
        # May be empty if API fails, but should not crash
        self.assertIsInstance(signals, list)


class TestProviderRegistry(unittest.TestCase):
    """Tests for provider registry."""

    def test_register_provider(self):
        registry = ProviderRegistry()
        provider = GoogleNewsProvider()
        registry.register(provider)
        self.assertIn("google_news_rss", registry.providers)

    def test_unregister_provider(self):
        registry = ProviderRegistry()
        provider = GoogleNewsProvider()
        registry.register(provider)
        registry.unregister("google_news_rss")
        self.assertNotIn("google_news_rss", registry.providers)

    def test_get_provider(self):
        registry = ProviderRegistry()
        provider = GoogleNewsProvider()
        registry.register(provider)
        result = registry.get_provider("google_news_rss")
        self.assertEqual(result.provider_id, "google_news_rss")

    def test_enabled_providers(self):
        registry = ProviderRegistry()
        registry.register(GoogleNewsProvider(enabled=True))
        registry.register(HackerNewsProvider(enabled=False))
        enabled = registry.enabled_providers
        self.assertIn("google_news_rss", enabled)
        self.assertNotIn("hackernews", enabled)

    def test_create_default_registry(self):
        registry = create_provider_registry(
            enable_google_news=True,
            enable_hackernews=True,
        )
        self.assertIn("google_news_rss", registry.providers)
        self.assertIn("hackernews", registry.providers)

    def test_create_registry_google_only(self):
        registry = create_provider_registry(
            enable_google_news=True,
            enable_hackernews=False,
        )
        self.assertIn("google_news_rss", registry.providers)
        self.assertNotIn("hackernews", registry.providers)

    def test_fetch_all_with_failure(self):
        registry = ProviderRegistry()
        # Add a failing provider
        failing = MagicMock(spec=ContentProvider)
        failing.provider_id = "failing"
        failing.enabled = True
        failing.fetch.side_effect = ConnectionError("API down")
        failing.health.return_value = ProviderHealth(
            provider_id="failing",
            status=ProviderStatus.OFFLINE,
        )
        registry.register(failing)

        # Add a working provider
        working = MagicMock(spec=ContentProvider)
        working.provider_id = "working"
        working.enabled = True
        working.fetch.return_value = [
            RawSignal(
                source=TrendSource.RSS,
                topic="Test",
                provider="working",
            )
        ]
        working.health.return_value = ProviderHealth(
            provider_id="working",
            status=ProviderStatus.LIVE,
        )
        registry.register(working)

        signals, health = registry.fetch_all()
        self.assertEqual(len(signals), 1)
        self.assertIn("failing", health)
        self.assertIn("working", health)


class TestProviderFailureIsolation(unittest.TestCase):
    """Tests for provider failure isolation."""

    def test_one_provider_fails_others_succeed(self):
        """When one provider fails, others should still contribute signals."""
        registry = ProviderRegistry()

        # Failing provider
        failing = MagicMock(spec=ContentProvider)
        failing.provider_id = "failing"
        failing.enabled = True
        failing.fetch.side_effect = ConnectionError("API down")
        failing.health.return_value = ProviderHealth(
            provider_id="failing",
            status=ProviderStatus.OFFLINE,
        )
        registry.register(failing)

        # Working provider
        working = MagicMock(spec=ContentProvider)
        working.provider_id = "working"
        working.enabled = True
        working.fetch.return_value = [
            RawSignal(source=TrendSource.RSS, topic="Test", provider="working")
        ]
        working.health.return_value = ProviderHealth(
            provider_id="working",
            status=ProviderStatus.LIVE,
        )
        registry.register(working)

        signals, health = registry.fetch_all()
        self.assertEqual(len(signals), 1)
        self.assertEqual(health["failing"].status, ProviderStatus.OFFLINE)
        self.assertEqual(health["working"].status, ProviderStatus.LIVE)

    def test_all_providers_fail_returns_empty(self):
        """When all providers fail, should return empty signals."""
        registry = ProviderRegistry()

        for i in range(3):
            failing = MagicMock(spec=ContentProvider)
            failing.provider_id = f"failing_{i}"
            failing.enabled = True
            failing.fetch.side_effect = ConnectionError("API down")
            failing.health.return_value = ProviderHealth(
                provider_id=f"failing_{i}",
                status=ProviderStatus.OFFLINE,
            )
            registry.register(failing)

        signals, health = registry.fetch_all()
        self.assertEqual(len(signals), 0)
        self.assertEqual(len(health), 3)


if __name__ == "__main__":
    unittest.main()
