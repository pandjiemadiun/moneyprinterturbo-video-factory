"""Visual feasibility scoring.

Deterministic, explainable, bounded scoring of visual feasibility
for a content opportunity.

All component scores are bounded [0, 1]. The total is a weighted sum
also bounded [0, 1].

Weights are documented and configurable.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.visual_opportunity.models import (
    ProviderAvailability,
    VisualConcept,
    VisualFeasibilityScore,
    VisualFeasibilityStatus,
)

# --- Scoring weights (must sum to 1.0) ---
WEIGHT_QUANTITY = 0.25
WEIGHT_PROVIDER_DIVERSITY = 0.20
WEIGHT_PORTRAIT_READINESS = 0.20
WEIGHT_RESOLUTION_SUFFICIENCY = 0.10
WEIGHT_SCENE_DIVERSITY = 0.15
WEIGHT_PROVIDER_HEALTH = 0.10

DEFAULT_WEIGHTS = {
    "quantity": WEIGHT_QUANTITY,
    "provider_diversity": WEIGHT_PROVIDER_DIVERSITY,
    "portrait_readiness": WEIGHT_PORTRAIT_READINESS,
    "resolution_sufficiency": WEIGHT_RESOLUTION_SUFFICIENCY,
    "scene_diversity": WEIGHT_SCENE_DIVERSITY,
    "provider_health": WEIGHT_PROVIDER_HEALTH,
}

# --- Production gate thresholds ---
# Minimum total score (0-100) for each status
GATE_PRODUCIBLE_MIN_SCORE = 60.0
GATE_LIMITED_MIN_SCORE = 30.0

# Minimum usable candidates for PRODUCIBLE
GATE_PRODUCIBLE_MIN_USABLE = 8
GATE_LIMITED_MIN_USABLE = 3

# For PRODUCIBLE: need native portrait OR enough reframable landscape
GATE_PRODUCIBLE_MIN_PORTRAIT = 2
GATE_PRODUCIBLE_MIN_REFRAMABLE = 4


def compute_quantity_score(total_usable: int) -> float:
    """Score based on total usable candidate quantity.

    Saturates at 30 usable candidates (diminishing returns beyond).
    """
    if total_usable <= 0:
        return 0.0
    import math
    # Log scale: reaches ~1.0 around 30 candidates
    return min(1.0, math.log1p(total_usable) / math.log1p(30))


def compute_provider_diversity_score(
    provider_availability: list[ProviderAvailability],
) -> float:
    """Score based on how many providers returned usable results."""
    if not provider_availability:
        return 0.0
    providers_with_usable = sum(
        1 for p in provider_availability if p.usable_count > 0
    )
    # Max providers is typically 3 (Pexels, Pixabay, Coverr)
    return min(1.0, providers_with_usable / 3.0)


def compute_portrait_readiness_score(
    total_usable: int,
    total_native_portrait: int,
    total_reframable_landscape: int,
) -> float:
    """Score based on portrait readiness.

    Native portrait is preferred; reframable landscape is secondary.
    """
    if total_usable <= 0:
        return 0.0
    portrait_ratio = total_native_portrait / total_usable
    reframable_ratio = total_reframable_landscape / total_usable

    # Strong native portrait coverage is ideal
    native_score = min(1.0, total_native_portrait / 6.0)
    # Reframable landscape provides a backup
    reframable_score = min(1.0, total_reframable_landscape / 8.0)

    return 0.6 * native_score + 0.2 * reframable_score + 0.2 * portrait_ratio


def compute_resolution_sufficiency_score(
    provider_availability: list[ProviderAvailability],
) -> float:
    """Score based on resolution sufficiency of usable candidates.

    Since only usable candidates pass the resolution gate, this
    reflects what fraction of raw candidates were usable (resolution ok).
    """
    total_raw = sum(p.raw_count for p in provider_availability)
    total_usable = sum(p.usable_count for p in provider_availability)
    if total_raw <= 0:
        return 0.0
    return min(1.0, total_usable / total_raw)


def compute_scene_diversity_score(
    concepts: list[VisualConcept],
    provider_availability: list[ProviderAvailability],
) -> float:
    """Score based on how many visual concepts have material coverage."""
    if not concepts:
        return 0.0
    # A concept is "covered" if any provider returned usable results for a
    # query that contains the concept term (approximate matching)
    covered = 0
    concept_terms = {c.term.lower().strip() for c in concepts}
    for concept_term in concept_terms:
        for pa in provider_availability:
            if pa.usable_count > 0:
                # Check if this provider's query relates to the concept
                q = pa.query.lower()
                if concept_term in q or any(
                    token in q for token in concept_term.split() if len(token) > 2
                ):
                    covered += 1
                    break
    return min(1.0, covered / len(concepts))


def compute_provider_health_score(
    provider_availability: list[ProviderAvailability],
) -> float:
    """Score based on provider response health."""
    if not provider_availability:
        return 0.0
    healthy = sum(1 for p in provider_availability if p.status == "OK")
    return min(1.0, healthy / len(provider_availability))


def compute_visual_feasibility(
    concepts: list[VisualConcept],
    provider_availability: list[ProviderAvailability],
) -> VisualFeasibilityScore:
    """Compute the full visual feasibility score.

    Deterministic: same inputs always produce same output.
    Bounded: all values in [0, 1].
    Explainable: each component has a documented weight and formula.
    """
    total_usable = sum(p.usable_count for p in provider_availability)
    total_native_portrait = sum(p.native_portrait_count for p in provider_availability)
    total_reframable_landscape = sum(
        p.reframable_landscape_count for p in provider_availability
    )

    quantity = compute_quantity_score(total_usable)
    diversity = compute_provider_diversity_score(provider_availability)
    portrait = compute_portrait_readiness_score(
        total_usable, total_native_portrait, total_reframable_landscape
    )
    resolution = compute_resolution_sufficiency_score(provider_availability)
    scene = compute_scene_diversity_score(concepts, provider_availability)
    health = compute_provider_health_score(provider_availability)

    total = (
        WEIGHT_QUANTITY * quantity
        + WEIGHT_PROVIDER_DIVERSITY * diversity
        + WEIGHT_PORTRAIT_READINESS * portrait
        + WEIGHT_RESOLUTION_SUFFICIENCY * resolution
        + WEIGHT_SCENE_DIVERSITY * scene
        + WEIGHT_PROVIDER_HEALTH * health
    )
    total = max(0.0, min(1.0, total))

    explanation = _build_explanation(
        total_usable, total_native_portrait, total_reframable_landscape,
        quantity, diversity, portrait, resolution, scene, health,
        len(provider_availability),
    )

    return VisualFeasibilityScore(
        total=round(total, 4),
        quantity_score=round(quantity, 4),
        provider_diversity_score=round(diversity, 4),
        portrait_readiness_score=round(portrait, 4),
        resolution_sufficiency_score=round(resolution, 4),
        scene_diversity_score=round(scene, 4),
        provider_health_score=round(health, 4),
        explanation=explanation,
        component_weights=dict(DEFAULT_WEIGHTS),
        scored_at=datetime.now(timezone.utc),
    )


def _build_explanation(
    total_usable: int,
    total_native_portrait: int,
    total_reframable_landscape: int,
    quantity: float,
    diversity: float,
    portrait: float,
    resolution: float,
    scene: float,
    health: float,
    num_providers: int,
) -> str:
    """Build a human-readable explanation of the score."""
    parts: list[str] = []

    if total_usable > 0:
        parts.append(
            f"{total_usable} usable candidates found "
            f"across {num_providers} provider(s)"
        )
        if total_native_portrait > 0:
            parts.append(f"{total_native_portrait} native portrait")
        if total_reframable_landscape > 0:
            parts.append(f"{total_reframable_landscape} reframable landscape")
    else:
        parts.append("no usable candidates found")

    healthy_count = round(health * num_providers)
    parts.append(f"{healthy_count}/{num_providers} providers healthy")

    return "; ".join(parts) + "."


def apply_production_gate(
    score: VisualFeasibilityScore,
    total_usable: int,
    total_native_portrait: int,
    total_reframable_landscape: int,
    provider_availability: list[ProviderAvailability],
) -> VisualFeasibilityStatus:
    """Apply the hard production feasibility gate.

    Returns one of:
      VISUALLY_PRODUCIBLE — passes all minimum thresholds
      VISUALLY_LIMITED     — some material but below ideal
      NOT_VISUALLY_PRODUCIBLE — insufficient material
      CHECK_FAILED         — all providers failed
    """
    # Check if ALL providers failed
    all_failed = (
        len(provider_availability) > 0
        and all(p.status != "OK" for p in provider_availability)
    )
    if all_failed:
        return VisualFeasibilityStatus.CHECK_FAILED

    score_100 = score.total * 100

    # VISUALLY_PRODUCIBLE: passes all minimum thresholds
    if (
        score_100 >= GATE_PRODUCIBLE_MIN_SCORE
        and total_usable >= GATE_PRODUCIBLE_MIN_USABLE
        and (
            total_native_portrait >= GATE_PRODUCIBLE_MIN_PORTRAIT
            or total_reframable_landscape >= GATE_PRODUCIBLE_MIN_REFRAMABLE
        )
    ):
        return VisualFeasibilityStatus.VISUALLY_PRODUCIBLE

    # VISUALLY_LIMITED: some material but below ideal
    if (
        score_100 >= GATE_LIMITED_MIN_SCORE
        and total_usable >= GATE_LIMITED_MIN_USABLE
    ):
        return VisualFeasibilityStatus.VISUALLY_LIMITED

    return VisualFeasibilityStatus.NOT_VISUALLY_PRODUCIBLE
