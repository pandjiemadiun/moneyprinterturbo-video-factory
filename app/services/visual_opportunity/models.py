"""Visual Opportunity Engine — data models.

Every field that represents observed evidence from a real provider is
explicitly distinguished from derived/heuristic values.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _stable_id(*parts: str) -> str:
    raw = "|".join(p for p in parts if p)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class VisualFeasibilityStatus(str, Enum):
    """Production gate decision for a visual opportunity."""

    VISUALLY_PRODUCIBLE = "VISUALLY_PRODUCIBLE"
    VISUALLY_LIMITED = "VISUALLY_LIMITED"
    NOT_VISUALLY_PRODUCIBLE = "NOT_VISUALLY_PRODUCIBLE"
    CHECK_FAILED = "CHECK_FAILED"


class CandidateRejectionReason(str, Enum):
    """Why a provider candidate was rejected."""

    LOW_RESOLUTION = "LOW_RESOLUTION"
    INSUFFICIENT_DURATION = "INSUFFICIENT_DURATION"
    ORIENTATION_MISMATCH = "ORIENTATION_MISMATCH"
    UNABLE_TO_REFRAME = "UNABLE_TO_REFRAME"
    INVALID_MEDIA = "INVALID_MEDIA"
    UNKNOWN = "UNKNOWN"


@dataclass
class VisualCandidate:
    """A single candidate found by a provider.

    Observed fields come directly from the provider response.
    Derived fields are explicitly marked.
    """

    # --- Observed (from provider) ---
    provider: str
    asset_id: str
    source_url: str
    width: int
    height: int
    duration: int  # seconds
    fetched_at: datetime = field(default_factory=_utcnow)

    # --- Derived ---
    is_portrait: bool = False
    is_landscape: bool = False
    is_square: bool = False
    is_reframable: bool = False
    rejection_reason: CandidateRejectionReason | None = None

    @property
    def usable(self) -> bool:
        return self.rejection_reason is None


@dataclass
class ProviderAvailability:
    """Observed availability from one provider for one query."""

    provider: str
    query: str
    status: str = "OK"  # OK | TIMEOUT | ERROR | NOT_CONFIGURED
    error_message: str = ""
    raw_count: int = 0  # total candidates returned by provider
    usable_count: int = 0  # candidates passing quality gate
    native_portrait_count: int = 0
    reframable_landscape_count: int = 0
    rejected_count: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    sample_candidates: list[VisualCandidate] = field(default_factory=list)
    checked_at: datetime = field(default_factory=_utcnow)
    is_cached: bool = False
    response_time_ms: float = 0.0


@dataclass
class VisualConcept:
    """A visual search concept derived from a topic."""

    concept_id: str = ""
    term: str = ""  # the actual search query
    source: str = ""  # topic | expansion | category | semantic
    parent_topic: str = ""


@dataclass
class VisualFeasibilityScore:
    """Deterministic, explainable visual feasibility score.

    Each component is bounded [0, 1]. The total is a weighted sum
    also bounded [0, 1].
    """

    total: float = 0.0  # [0, 1]
    quantity_score: float = 0.0
    provider_diversity_score: float = 0.0
    portrait_readiness_score: float = 0.0
    resolution_sufficiency_score: float = 0.0
    scene_diversity_score: float = 0.0
    provider_health_score: float = 0.0
    explanation: str = ""
    component_weights: dict[str, float] = field(default_factory=dict)
    scored_at: datetime = field(default_factory=_utcnow)


@dataclass
class VisualOpportunityAssessment:
    """Complete visual assessment for one content opportunity."""

    assessment_id: str = ""
    topic: str = ""
    status: VisualFeasibilityStatus = VisualFeasibilityStatus.CHECK_FAILED
    feasibility_score: VisualFeasibilityScore = field(
        default_factory=VisualFeasibilityScore
    )
    concepts: list[VisualConcept] = field(default_factory=list)
    provider_availability: list[ProviderAvailability] = field(default_factory=list)
    total_usable: int = 0
    total_native_portrait: int = 0
    total_reframable_landscape: int = 0
    total_rejected: int = 0
    concepts_with_material: int = 0
    concepts_without_material: int = 0
    provider_health: dict[str, str] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=_utcnow)
    is_cached: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
