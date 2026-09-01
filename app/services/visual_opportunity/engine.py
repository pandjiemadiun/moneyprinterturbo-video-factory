"""Visual Opportunity Engine — main orchestrator.

Bridges the Content Intelligence pipeline with real provider probing
to produce visual-feasibility-aware opportunity assessments.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.services.visual_opportunity.models import (
    ProviderAvailability,
    VisualConcept,
    VisualFeasibilityStatus,
    VisualOpportunityAssessment,
)
from app.services.visual_opportunity.provider_probe import (
    get_configured_providers,
    probe_provider,
)
from app.services.visual_opportunity.query_generator import generate_visual_queries
from app.services.visual_opportunity.scorer import (
    apply_production_gate,
    compute_visual_feasibility,
)

# Default providers to probe (in order)
DEFAULT_PROVIDERS = ["pexels", "pixabay", "coverr"]

# How many top opportunities to assess visually (budget control)
DEFAULT_MAX_OPPORTUNITIES = 5

# Cache TTL for visual assessments (seconds)
CACHE_TTL_SECONDS = 1800  # 30 minutes


def _make_cache_key(topic: str, category: str) -> str:
    raw = f"vo:{topic.lower().strip()}:{category.lower().strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class VisualOpportunityEngine:
    """Orchestrates visual feasibility assessment.

    For each candidate opportunity:
      1. Generate visual search queries
      2. Probe configured providers
      3. Compute visual feasibility score
      4. Apply production gate
    """

    def __init__(
        self,
        providers: list[str] | None = None,
        max_opportunities: int = DEFAULT_MAX_OPPORTUNITIES,
        max_queries_per_topic: int = 6,
        minimum_duration: int = 3,
        llm_client: Any = None,
        cache: Any = None,
    ):
        self.providers = providers or DEFAULT_PROVIDERS
        self.max_opportunities = max_opportunities
        self.max_queries_per_topic = max_queries_per_topic
        self.minimum_duration = minimum_duration
        self.llm_client = llm_client
        self._cache = cache  # optional dict-like cache

    def assess_topic(
        self,
        topic: str,
        category: str = "general",
        force_refresh: bool = False,
    ) -> VisualOpportunityAssessment:
        """Assess visual feasibility for a single topic."""
        assessment = VisualOpportunityAssessment(
            assessment_id=_stable_assessment_id(topic, topic),
            topic=topic,
        )

        # Check cache
        cache_key = _make_cache_key(topic, category)
        if not force_refresh and self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                cached.is_cached = True
                return cached

        # 1. Generate visual queries
        concepts = generate_visual_queries(
            topic=topic,
            category=category,
            max_queries=self.max_queries_per_topic,
            llm_client=self.llm_client,
        )
        assessment.concepts = concepts

        # 2. Probe providers
        configured = get_configured_providers()
        providers_to_use = [p for p in self.providers if p in configured]
        if not providers_to_use:
            providers_to_use = configured  # fall back to whatever is configured

        provider_availability: list[ProviderAvailability] = []
        provider_health: dict[str, str] = {}

        for concept in concepts:
            for provider in providers_to_use:
                pa = probe_provider(
                    provider=provider,
                    query=concept.term,
                    minimum_duration=self.minimum_duration,
                    llm_client=self.llm_client,
                )
                provider_availability.append(pa)
                provider_health[provider] = pa.status

        assessment.provider_availability = provider_availability
        assessment.provider_health = provider_health

        # 3. Compute score
        score = compute_visual_feasibility(concepts, provider_availability)
        assessment.feasibility_score = score

        # 4. Aggregate totals
        assessment.total_usable = sum(p.usable_count for p in provider_availability)
        assessment.total_native_portrait = sum(
            p.native_portrait_count for p in provider_availability
        )
        assessment.total_reframable_landscape = sum(
            p.reframable_landscape_count for p in provider_availability
        )
        assessment.total_rejected = sum(p.rejected_count for p in provider_availability)

        # 5. Scene coverage
        covered = 0
        for concept in concepts:
            term = concept.term.lower()
            for pa in provider_availability:
                if pa.usable_count > 0 and term in pa.query.lower():
                    covered += 1
                    break
        assessment.concepts_with_material = covered
        assessment.concepts_without_material = len(concepts) - covered

        # 6. Apply production gate
        assessment.status = apply_production_gate(
            score=score,
            total_usable=assessment.total_usable,
            total_native_portrait=assessment.total_native_portrait,
            total_reframable_landscape=assessment.total_reframable_landscape,
            provider_availability=provider_availability,
        )

        assessment.checked_at = datetime.now(timezone.utc)

        # Store in cache
        if self._cache is not None:
            self._cache[cache_key] = assessment

        return assessment

    def assess_opportunities(
        self,
        topics: list[str],
        category: str = "general",
        force_refresh: bool = False,
    ) -> list[VisualOpportunityAssessment]:
        """Assess visual feasibility for multiple topics."""
        assessments: list[VisualOpportunityAssessment] = []
        for topic in topics[: self.max_opportunities]:
            assessment = self.assess_topic(
                topic=topic,
                category=category,
                force_refresh=force_refresh,
            )
            assessments.append(assessment)
        return assessments


def _stable_assessment_id(topic: str, extra: str = "") -> str:
    raw = f"{topic.lower().strip()}:{extra}"
    return "vo_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def create_visual_opportunity_engine(
    providers: list[str] | None = None,
    max_opportunities: int = DEFAULT_MAX_OPPORTUNITIES,
    llm_client: Any = None,
    cache: Any = None,
) -> VisualOpportunityEngine:
    """Factory function."""
    return VisualOpportunityEngine(
        providers=providers,
        max_opportunities=max_opportunities,
        llm_client=llm_client,
        cache=cache,
    )
