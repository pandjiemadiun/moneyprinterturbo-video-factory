"""Trend Radar — collect, normalize, and deduplicate content signals.

The Trend Radar abstraction collects trend/content signals from available
sources, normalizes source data, deduplicates equivalent signals, identifies
emerging/relevant topics, retains source attribution, retains timestamps,
supports freshness, and produces structured trend objects.

A trend record contains sufficient information to explain:
- what is trending
- where the signal came from
- when it was observed
- why it is considered a trend
- supporting evidence
- confidence/reliability where available

Do not fabricate trend data. If a provider is unavailable, represent that
state explicitly.
"""

from __future__ import annotations

import re
import string
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from loguru import logger

from app.services.content_intelligence.models import (
    NormalizedSignal,
    RawSignal,
    Trend,
    TrendSource,
    _stable_id,
    _utcnow,
)


_FRESHNESS_HALF_LIFE_HOURS = 24.0


def _canonicalize(text: str) -> str:
    """Produce a stable, deduplication-ready canonical key from a topic string.

    Normalizes case, collapses whitespace, removes punctuation, and strips
    filler words so that equivalent topics map to the same key.
    """
    if not text:
        return ""
    value = text.lower().strip()
    value = re.sub(r"[^\w\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    filler = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
        "for", "of", "with", "by", "is", "are", "was", "were", "be",
        "been", "being", "have", "has", "had", "do", "does", "did",
        "will", "would", "could", "should", "may", "might", "shall",
        "can", "this", "that", "these", "those", "it", "its", "about",
    }
    tokens = [t for t in value.split() if t and t not in filler]
    return " ".join(tokens)


def _compute_freshness(
    latest_observed: datetime,
    reference_time: Optional[datetime] = None,
) -> float:
    """Compute a freshness score in [0, 1] based on recency.

    Uses exponential decay with a configurable half-life so that more
    recent signals score higher. Signals older than ~5 half-lives score ~0.
    """
    if reference_time is None:
        reference_time = _utcnow()
    if latest_observed.tzinfo is None:
        latest_observed = latest_observed.replace(tzinfo=timezone.utc)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)
    age = (reference_time - latest_observed).total_seconds()
    if age < 0:
        age = 0
    decay = 0.5 ** (age / (_FRESHNESS_HALF_LIFE_HOURS * 3600))
    return max(0.0, min(1.0, decay))


class TrendRadar:
    """Collect, normalize, and deduplicate content signals into trends.

    Provider isolation: external providers are injected via ``add_provider``.
    Business logic never depends on provider-specific response formats.
    """

    def __init__(
        self,
        freshness_half_life_hours: float = _FRESHNESS_HALF_LIFE_HOURS,
        min_confidence: float = 0.0,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self._providers: list[Callable[[], list[RawSignal]]] = []
        self._freshness_half_life_hours = freshness_half_life_hours
        self._min_confidence = min_confidence
        self._clock = clock or _utcnow

    def add_provider(self, provider: Callable[[], list[RawSignal]]) -> None:
        """Register a provider callable that returns a list of RawSignals.

        Provider callables are isolated: they return RawSignal objects, and
        all normalization happens inside the radar. Provider-specific formats
        must be normalized by the provider itself before returning.
        """
        self._providers.append(provider)

    def collect_raw_signals(self) -> list[RawSignal]:
        """Collect raw signals from all registered providers.

        Provider failures are caught and logged individually so that one
        failing provider does not prevent others from contributing signals.
        Failed providers return an empty list (no fabricated data).
        """
        signals: list[RawSignal] = []
        for provider in self._providers:
            try:
                result = provider()
                if result:
                    signals.extend(result)
            except Exception as exc:
                provider_name = getattr(
                    provider, "__name__", repr(provider)
                )
                logger.warning(
                    f"trend provider {provider_name} failed: {exc}"
                )
        return signals

    def normalize_signal(self, signal: RawSignal) -> Optional[NormalizedSignal]:
        """Normalize a raw signal into a deduplication-ready form.

        Returns None if the signal cannot be normalized (empty topic).
        """
        canonical = _canonicalize(signal.topic)
        if not canonical:
            logger.debug(
                f"signal from {signal.source.value} normalized to empty key, "
                f"topic={signal.topic!r}; dropping"
            )
            return None
        evidence = []
        if signal.metadata:
            for key, value in signal.metadata.items():
                if value is not None and str(value).strip():
                    evidence.append(f"{key}={value}")
        return NormalizedSignal(
            canonical_key=canonical,
            original_topic=signal.topic.strip(),
            source=signal.source,
            observed_at=signal.observed_at,
            provider=signal.provider or signal.source.value,
            confidence=signal.confidence,
            evidence=evidence,
            metadata=dict(signal.metadata),
        )

    def normalize_signals(
        self, signals: list[RawSignal]
    ) -> list[NormalizedSignal]:
        """Normalize a list of raw signals, dropping any that fail."""
        normalized: list[NormalizedSignal] = []
        for signal in signals:
            try:
                result = self.normalize_signal(signal)
                if result is not None:
                    normalized.append(result)
            except Exception as exc:
                logger.warning(f"failed to normalize signal: {exc}")
        return normalized

    def deduplicate_signals(
        self, signals: list[NormalizedSignal]
    ) -> list[NormalizedSignal]:
        """Deduplicate signals by canonical_key, keeping the highest-confidence
        occurrence while merging evidence from all occurrences."""
        by_key: dict[str, NormalizedSignal] = {}
        for signal in signals:
            existing = by_key.get(signal.canonical_key)
            if existing is None:
                by_key[signal.canonical_key] = signal
            else:
                if signal.confidence > existing.confidence:
                    merged_evidence = list(existing.evidence)
                    for item in signal.evidence:
                        if item not in merged_evidence:
                            merged_evidence.append(item)
                    by_key[signal.canonical_key] = NormalizedSignal(
                        canonical_key=signal.canonical_key,
                        original_topic=signal.original_topic,
                        source=signal.source,
                        observed_at=signal.observed_at,
                        provider=signal.provider,
                        confidence=signal.confidence,
                        evidence=merged_evidence,
                        metadata={**existing.metadata, **signal.metadata},
                        signal_id=signal.signal_id,
                    )
                else:
                    for item in signal.evidence:
                        if item not in existing.evidence:
                            existing.evidence.append(item)
        return list(by_key.values())

    def detect_trends(
        self,
        signals: Optional[list[RawSignal]] = None,
        reference_time: Optional[datetime] = None,
    ) -> list[Trend]:
        """Detect trends from raw signals.

        If no signals are provided, collects from registered providers.
        Returns a list of Trend objects sorted by strength (descending).
        """
        if signals is None:
            signals = self.collect_raw_signals()
        if not signals:
            logger.info("trend radar: no raw signals available")
            return []
        normalized = self.normalize_signals(signals)
        if not normalized:
            logger.info("trend radar: no signals survived normalization")
            return []
        return self._aggregate_trends(normalized, reference_time)

    def _aggregate_trends(
        self,
        signals: list[NormalizedSignal],
        reference_time: Optional[datetime] = None,
    ) -> list[Trend]:
        """Aggregate normalized signals into Trend objects grouped by canonical key."""
        if reference_time is None:
            reference_time = self._clock()
        buckets: dict[str, list[NormalizedSignal]] = defaultdict(list)
        for signal in signals:
            if signal.confidence < self._min_confidence:
                continue
            buckets[signal.canonical_key].append(signal)
        trends: list[Trend] = []
        for canonical_key, group in buckets.items():
            trend = self._build_trend(canonical_key, group, reference_time)
            if trend is not None:
                trends.append(trend)
        trends.sort(key=lambda t: t.strength, reverse=True)
        return trends

    def _build_trend(
        self,
        canonical_key: str,
        signals: list[NormalizedSignal],
        reference_time: datetime,
    ) -> Optional[Trend]:
        """Build a single Trend from a group of normalized signals."""
        if not signals:
            return None
        observed_times = [s.observed_at for s in signals]
        first_observed = min(observed_times)
        latest_observed = max(observed_times)
        sources: list[TrendSource] = []
        providers: list[str] = []
        evidence: list[str] = []
        confidence_sum = 0.0
        for s in signals:
            if s.source not in sources:
                sources.append(s.source)
            if s.provider and s.provider not in providers:
                providers.append(s.provider)
            for item in s.evidence:
                if item not in evidence:
                    evidence.append(item)
            confidence_sum += s.confidence
        avg_confidence = confidence_sum / len(signals)
        freshness = _compute_freshness(
            latest_observed, reference_time
        )
        strength = self._compute_strength(
            signal_count=len(signals),
            avg_confidence=avg_confidence,
            freshness=freshness,
            source_count=len(sources),
        )
        return Trend(
            trend_id=_stable_id(canonical_key, str(latest_observed.timestamp())),
            topic=signals[0].original_topic,
            canonical_key=canonical_key,
            sources=sources,
            providers=providers,
            first_observed=first_observed,
            latest_observed=latest_observed,
            signal_count=len(signals),
            evidence=evidence,
            confidence=round(avg_confidence, 4),
            strength=round(strength, 4),
            freshness=round(freshness, 4),
        )

    def _compute_strength(
        self,
        signal_count: int,
        avg_confidence: float,
        freshness: float,
        source_count: int,
    ) -> float:
        """Compute a trend strength score in [0, 1].

        Deterministic formula:
        - signal volume contributes up to 0.3 (log-scaled, saturating at 10 signals)
        - confidence contributes up to 0.3
        - freshness contributes up to 0.25
        - multi-source diversity contributes up to 0.15
        """
        import math
        volume_score = min(1.0, math.log1p(signal_count) / math.log1p(10))
        diversity_score = min(1.0, source_count / 3.0)
        strength = (
            0.30 * volume_score
            + 0.30 * avg_confidence
            + 0.25 * freshness
            + 0.15 * diversity_score
        )
        return max(0.0, min(1.0, strength))
