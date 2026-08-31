"""Data models for the Content Intelligence module.

These models enforce a clear separation between:
- raw external signals
- normalized signals
- detected trends
- opportunities
- pattern analysis
- scores
- hypotheses

Every field that represents observed evidence is distinguishable from
model inference through the ``evidence`` and ``inference`` patterns.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _stable_id(*parts: str) -> str:
    """Generate a stable deterministic ID from string parts."""
    combined = "|".join(parts)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]


class TrendSource(str, Enum):
    """Canonical trend signal sources."""
    MANUAL = "manual"
    PROVIDER = "provider"
    WEB_SEARCH = "web_search"
    RSS = "rss"
    SOCIAL = "social"


@dataclass
class RawSignal:
    """A single raw content signal from an external source.

    This is the earliest representation — straight from a provider with
    minimal processing. Source-specific payloads live in ``raw_payload``.
    """
    source: TrendSource
    topic: str
    observed_at: datetime = field(default_factory=_utcnow)
    raw_payload: dict[str, Any] = field(default_factory=dict)
    provider: str = ""
    confidence: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be between 0 and 1, got {self.confidence}"
            )


@dataclass
class NormalizedSignal:
    """A normalized, deduplication-ready signal.

    ``canonical_key`` is the deduplication key (lowercase, stripped,
    punctuation-normalized). ``original_topics`` preserves the raw input
    for attribution.
    """
    canonical_key: str
    original_topic: str
    source: TrendSource
    observed_at: datetime
    provider: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    signal_id: str = ""

    def __post_init__(self):
        if not self.signal_id:
            self.signal_id = _stable_id(
                self.canonical_key, self.source.value, self.provider
            )


@dataclass
class Trend:
    """A detected trend aggregated from one or more normalized signals.

    A trend must contain sufficient information to explain what is trending,
    where the signal came from, when it was observed, why it is considered
    a trend, and supporting evidence.
    """
    trend_id: str
    topic: str
    canonical_key: str
    sources: list[TrendSource] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)
    first_observed: datetime = field(default_factory=_utcnow)
    latest_observed: datetime = field(default_factory=_utcnow)
    signal_count: int = 0
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.0
    strength: float = 0.0
    freshness: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be between 0 and 1, got {self.confidence}"
            )


class ViralPatternType(str, Enum):
    """Types of viral patterns that can be detected."""
    HOOK_STRUCTURE = "hook_structure"
    TOPIC_PATTERN = "topic_pattern"
    EMOTIONAL_FRAMING = "emotional_framing"
    CURIOSITY_GAP = "curiosity_gap"
    LIST_STRUCTURE = "list_structure"
    PROBLEM_SOLUTION = "problem_solution"
    CONTROVERSY_DEBATE = "controversy_debate"
    STORYTELLING = "storytelling"
    RECURRING_THEME = "recurring_theme"
    TITLE_PATTERN = "title_pattern"
    AUDIENCE_INTENT = "audience_intent"


@dataclass
class PatternEvidence:
    """A single piece of evidence for a viral pattern.

    ``is_observed`` distinguishes OBSERVED DATA (True) from
    MODEL INFERENCE (False).
    """
    description: str
    is_observed: bool
    source: str = ""
    confidence: float = 0.5

    def __post_init__(self):
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be between 0 and 1, got {self.confidence}"
            )


@dataclass
class ViralPattern:
    """A detected viral pattern with evidence.

    Patterns must retain evidence and/or confidence. The implementation
    distinguishes observed data from model inference via PatternEvidence.is_observed.
    """
    pattern_type: ViralPatternType
    name: str
    description: str
    evidence: list[PatternEvidence] = field(default_factory=list)
    confidence: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be between 0 and 1, got {self.confidence}"
            )

    @property
    def observed_evidence(self) -> list[PatternEvidence]:
        """Return only observed (non-inference) evidence."""
        return [e for e in self.evidence if e.is_observed]

    @property
    def inference_evidence(self) -> list[PatternEvidence]:
        """Return only model inference evidence."""
        return [e for e in self.evidence if not e.is_observed]


class ScoreDimension(str, Enum):
    """Dimensions used in opportunity scoring."""
    TREND_STRENGTH = "trend_strength"
    FRESHNESS = "freshness"
    AUDIENCE_RELEVANCE = "audience_relevance"
    CONTENT_DEMAND = "content_demand"
    COMPETITION = "competition"
    PRODUCTION_FEASIBILITY = "production_feasibility"
    VIRAL_POTENTIAL = "viral_potential"
    MONETIZATION = "monetization"


@dataclass
class DimensionScore:
    """Score for a single dimension with explanation."""
    dimension: ScoreDimension
    score: float
    weight: float
    explanation: str
    evidence: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(
                f"score must be between 0 and 1, got {self.score}"
            )
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError(
                f"weight must be between 0 and 1, got {self.weight}"
            )

    @property
    def weighted_score(self) -> float:
        return self.score * self.weight


@dataclass
class OpportunityScore:
    """Deterministic, inspectable opportunity score.

    Scores are NOT an unexplained LLM-generated number. Each dimension
    has a clear explanation, and the total is a weighted sum.
    """
    total: float
    dimensions: list[DimensionScore] = field(default_factory=list)
    explanation: str = ""
    scored_at: datetime = field(default_factory=_utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentOpportunity:
    """A content opportunity mined from trend signals.

    An opportunity answers:
    - What topic can be created?
    - Why is it worth creating?
    - Who is the likely audience?
    - What content angle is available?
    - What makes the opportunity timely?
    - What evidence supports it?
    """
    opportunity_id: str
    topic: str
    rationale: str
    audience: str
    angle: str
    timeliness: str
    evidence: list[str] = field(default_factory=list)
    supporting_trends: list[str] = field(default_factory=list)
    score: Optional[OpportunityScore] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentHypothesis:
    """A structured content hypothesis ready for downstream content generation.

    Contains enough information for downstream content generation to act on it.
    This is structured data, not merely free-form text.
    """
    hypothesis_id: str
    topic: str
    audience: str
    angle: str
    proposed_hook: str
    content_promise: str
    format: str
    trend_evidence: list[str] = field(default_factory=list)
    viral_pattern_evidence: list[str] = field(default_factory=list)
    opportunity_score: Optional[OpportunityScore] = None
    confidence: float = 0.5
    keywords: list[str] = field(default_factory=list)
    rationale: str = ""
    created_at: datetime = field(default_factory=_utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be between 0 and 1, got {self.confidence}"
            )

    def to_script_prompt(self) -> str:
        """Convert the hypothesis into a prompt usable by the existing script generator."""
        parts = [f"Topic: {self.topic}"]
        if self.angle:
            parts.append(f"Angle: {self.angle}")
        if self.proposed_hook:
            parts.append(f"Hook: {self.proposed_hook}")
        if self.content_promise:
            parts.append(f"Promise: {self.content_promise}")
        if self.audience:
            parts.append(f"Audience: {self.audience}")
        return ". ".join(parts)
