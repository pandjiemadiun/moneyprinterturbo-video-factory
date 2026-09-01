"""Content Factory — production specification.

A ProductionSpecification is the canonical internal representation of
a video to be produced. It is derived from a validated visual
opportunity (Phase 12) and contains enough information to deterministically
create an MPT task.

Every field records its provenance:
  OBSERVED   — directly from provider/hypothesis evidence
  DERIVED    — computed from observed data
  INFERRED   — LLM-generated or heuristic
  STATIC     — from configuration/defaults
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from enum import Enum


class Provenance(str, Enum):
    """Origin of a specification field's value."""

    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    INFERRED = "INFERRED"
    STATIC = "STATIC"


@dataclass
class FieldProvenance:
    """Tracks the origin of a specification field."""

    value: Any = None
    provenance: Provenance = Provenance.STATIC
    source: str = ""


@dataclass
class VisualConceptSpec:
    """A visual concept with its provider evidence."""

    concept: str = ""
    query: str = ""
    provider: str = ""
    relevant_count: int = 0
    strong_count: int = 0
    source: str = ""  # topic | expansion | category | inferred


@dataclass
class ProductionSpecification:
    """Complete specification for producing a video from a visual opportunity.

    This is the canonical input to the Content Factory. It is derived
    entirely from a validated Phase 12 VisualOpportunityAssessment.
    """

    # --- Identity ---
    spec_id: str = ""  # deterministic hash for idempotency
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # --- Content (from hypothesis + topic) ---
    topic: str = ""
    title: str = ""
    hook: str = ""
    promise: str = ""
    format: str = ""  # e.g., "listicle", "explainer", "story"
    language: str = "id"

    # --- Script guidance ---
    keywords: list[str] = field(default_factory=list)
    script_guidance: str = ""
    scene_guidance: str = ""

    # --- Visual (from Phase 12) ---
    visual_concepts: list[VisualConceptSpec] = field(default_factory=list)
    visual_aspect: str = "portrait"  # portrait | landscape | square
    target_duration: int = 60  # seconds
    clip_duration: int = 5

    # --- Provider constraints ---
    preferred_providers: list[str] = field(
        default_factory=lambda: ["pexels", "pixabay", "coverr"]
    )

    # --- Scores ---
    opportunity_score: float = 0.0
    visual_feasibility_score: float = 0.0
    relevance_confidence: float = 0.0

    # --- Provenance tracking ---
    _provenance: dict[str, FieldProvenance] = field(default_factory=dict)

    def set_field(self, name: str, value: Any, provenance: Provenance, source: str = ""):
        """Set a field with provenance tracking."""
        setattr(self, name, value)
        self._provenance[name] = FieldProvenance(
            value=value, provenance=provenance, source=source
        )

    def get_provenance(self, name: str) -> FieldProvenance | None:
        """Get the provenance of a field."""
        return self._provenance.get(name)

    def compute_spec_id(self) -> str:
        """Compute a deterministic spec ID from topic + visual concepts.

        Used for idempotency: the same opportunity always produces
        the same spec ID, preventing duplicate production.
        """
        key_parts = [self.topic.lower().strip()]
        for vc in sorted(self.visual_concepts, key=lambda c: c.concept):
            key_parts.append(vc.concept.lower().strip())
        key = "|".join(p for p in key_parts if p)
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "spec_id": self.spec_id,
            "topic": self.topic,
            "title": self.title,
            "hook": self.hook,
            "promise": self.promise,
            "format": self.format,
            "language": self.language,
            "keywords": self.keywords,
            "visual_aspect": self.visual_aspect,
            "target_duration": self.target_duration,
            "clip_duration": self.clip_duration,
            "preferred_providers": self.preferred_providers,
            "opportunity_score": self.opportunity_score,
            "visual_feasibility_score": self.visual_feasibility_score,
            "relevance_confidence": self.relevance_confidence,
            "visual_concepts": [
                {
                    "concept": vc.concept,
                    "query": vc.query,
                    "provider": vc.provider,
                    "relevant_count": vc.relevant_count,
                    "strong_count": vc.strong_count,
                }
                for vc in self.visual_concepts
            ],
        }
