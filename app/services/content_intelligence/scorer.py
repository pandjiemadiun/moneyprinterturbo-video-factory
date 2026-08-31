"""Opportunity Scoring — deterministic, inspectable scoring.

Implements deterministic, inspectable scoring. At minimum considers:
- trend strength
- freshness
- audience relevance
- content demand
- competition/saturation where measurable
- production feasibility
- viral potential
- monetization relevance where appropriate

Scores are NOT an unexplained LLM-generated number. The system explains
why an opportunity received its score. Uses normalized scores.
"""

from __future__ import annotations

import math
from typing import Optional

from loguru import logger

from app.services.content_intelligence.models import (
    ContentOpportunity,
    DimensionScore,
    OpportunityScore,
    ScoreDimension,
    Trend,
    ViralPattern,
)


DEFAULT_WEIGHTS: dict[ScoreDimension, float] = {
    ScoreDimension.TREND_STRENGTH: 0.20,
    ScoreDimension.FRESHNESS: 0.15,
    ScoreDimension.AUDIENCE_RELEVANCE: 0.15,
    ScoreDimension.CONTENT_DEMAND: 0.15,
    ScoreDimension.COMPETITION: 0.10,
    ScoreDimension.PRODUCTION_FEASIBILITY: 0.10,
    ScoreDimension.VIRAL_POTENTIAL: 0.10,
    ScoreDimension.MONETIZATION: 0.05,
}


def _normalize_weights(
    weights: dict[ScoreDimension, float],
) -> dict[ScoreDimension, float]:
    """Normalize weights so they sum to 1.0."""
    total = sum(weights.values())
    if total <= 0:
        count = len(weights)
        return {k: 1.0 / count for k in weights}
    return {k: v / total for k, v in weights.items()}


def _score_audience_relevance(opportunity: ContentOpportunity) -> DimensionScore:
    """Score audience relevance based on opportunity metadata.

    Higher when the audience is specific and the category is well-defined.
    """
    category = opportunity.metadata.get("category", "general")
    audience = opportunity.audience.lower() if opportunity.audience else ""
    specific_audience_keywords = [
        "enthusiasts", "professionals", "students", "adults",
        "learners", "creators", "beginners", "parents", "entrepreneurs",
    ]
    specificity = 0.5
    for keyword in specific_audience_keywords:
        if keyword in audience:
            specificity = 0.8
            break
    if category != "general":
        specificity = min(1.0, specificity + 0.1)
    evidence = [f"category={category}", f"audience={opportunity.audience}"]
    return DimensionScore(
        dimension=ScoreDimension.AUDIENCE_RELEVANCE,
        score=round(specificity, 4),
        weight=DEFAULT_WEIGHTS[ScoreDimension.AUDIENCE_RELEVANCE],
        explanation=(
            f"Audience specificity={specificity:.2f} based on category "
            f"'{category}' and audience '{opportunity.audience}'"
        ),
        evidence=evidence,
    )


def _score_content_demand(trend: Optional[Trend]) -> DimensionScore:
    """Score content demand based on trend signal volume and source diversity."""
    if trend is None:
        return DimensionScore(
            dimension=ScoreDimension.CONTENT_DEMAND,
            score=0.3,
            weight=DEFAULT_WEIGHTS[ScoreDimension.CONTENT_DEMAND],
            explanation="No trend data available; defaulting to low demand",
            evidence=["no_trend_data"],
        )
    signal_score = min(1.0, math.log1p(trend.signal_count) / math.log1p(10))
    source_score = min(1.0, len(trend.sources) / 3.0)
    score = 0.6 * signal_score + 0.4 * source_score
    evidence = [
        f"signal_count={trend.signal_count}",
        f"source_count={len(trend.sources)}",
    ]
    return DimensionScore(
        dimension=ScoreDimension.CONTENT_DEMAND,
        score=round(score, 4),
        weight=DEFAULT_WEIGHTS[ScoreDimension.CONTENT_DEMAND],
        explanation=(
            f"Demand={score:.2f} from signal volume ({trend.signal_count}) "
            f"and source diversity ({len(trend.sources)} sources)"
        ),
        evidence=evidence,
    )


def _score_competition(opportunity: ContentOpportunity) -> DimensionScore:
    """Score competition/saturation.

    Inversely related to how generic the topic is. Niche topics score higher
    (lower competition). This is a heuristic proxy since we don't have direct
    competition data.
    """
    topic = opportunity.topic.lower()
    generic_topics = [
        "life", "love", "happiness", "success", "motivation",
        "inspiration", "funny", "amazing", "best", "top",
    ]
    is_generic = any(word in topic for word in generic_topics)
    category = opportunity.metadata.get("category", "general")
    if is_generic:
        score = 0.3
        explanation = "Topic uses generic terms; likely high competition"
    elif category != "general":
        score = 0.6
        explanation = f"Niche category '{category}' suggests moderate competition"
    else:
        score = 0.45
        explanation = "Topic competition level is uncertain"
    return DimensionScore(
        dimension=ScoreDimension.COMPETITION,
        score=round(score, 4),
        weight=DEFAULT_WEIGHTS[ScoreDimension.COMPETITION],
        explanation=explanation,
        evidence=[f"category={category}", f"is_generic={is_generic}"],
    )


def _score_production_feasibility(
    opportunity: ContentOpportunity,
) -> DimensionScore:
    """Score production feasibility.

    Topics that are concrete and visual are more feasible for short-video
    production than abstract topics.
    """
    category = opportunity.metadata.get("category", "general")
    topic = opportunity.topic.lower()
    high_feasibility_categories = {
        "technology", "health", "finance", "productivity", "education",
    }
    abstract_topics = [
        "meaning of life", "philosophy", "consciousness", "existence",
        "spirituality", "metaphysics",
    ]
    if any(word in topic for word in abstract_topics):
        score = 0.3
        explanation = "Abstract topic; harder to visualize for short video"
    elif category in high_feasibility_categories:
        score = 0.8
        explanation = f"Category '{category}' is highly visualizable"
    else:
        score = 0.6
        explanation = f"Category '{category}' has moderate production feasibility"
    return DimensionScore(
        dimension=ScoreDimension.PRODUCTION_FEASIBILITY,
        score=round(score, 4),
        weight=DEFAULT_WEIGHTS[ScoreDimension.PRODUCTION_FEASIBILITY],
        explanation=explanation,
        evidence=[f"category={category}"],
    )


def _score_viral_potential(
    patterns: Optional[list[ViralPattern]],
) -> DimensionScore:
    """Score viral potential based on detected viral patterns.

    More high-confidence patterns = higher viral potential.
    Only observed patterns contribute strongly; inference patterns contribute less.
    """
    if not patterns:
        return DimensionScore(
            dimension=ScoreDimension.VIRAL_POTENTIAL,
            score=0.4,
            weight=DEFAULT_WEIGHTS[ScoreDimension.VIRAL_POTENTIAL],
            explanation="No viral patterns detected; defaulting to moderate potential",
            evidence=["no_patterns"],
        )
    observed_patterns = [
        p for p in patterns if p.observed_evidence
    ]
    inference_patterns = [
        p for p in patterns if p.inference_evidence and not p.observed_evidence
    ]
    observed_score = min(1.0, len(observed_patterns) / 3.0)
    inference_score = min(0.5, len(inference_patterns) / 4.0)
    score = 0.7 * observed_score + 0.3 * inference_score
    avg_confidence = (
        sum(p.confidence for p in patterns) / len(patterns)
        if patterns else 0.0
    )
    score = 0.8 * score + 0.2 * avg_confidence
    evidence = [
        f"observed_patterns={len(observed_patterns)}",
        f"inference_patterns={len(inference_patterns)}",
        f"avg_confidence={avg_confidence:.2f}",
    ]
    return DimensionScore(
        dimension=ScoreDimension.VIRAL_POTENTIAL,
        score=round(min(1.0, score), 4),
        weight=DEFAULT_WEIGHTS[ScoreDimension.VIRAL_POTENTIAL],
        explanation=(
            f"Viral potential={score:.2f} from {len(observed_patterns)} observed "
            f"and {len(inference_patterns)} inference patterns"
        ),
        evidence=evidence,
    )


def _score_monetization(opportunity: ContentOpportunity) -> DimensionScore:
    """Score monetization relevance.

    Categories like finance, technology, and education tend to have higher
    monetization potential.
    """
    category = opportunity.metadata.get("category", "general")
    high_monetization = {"finance", "technology", "education", "productivity"}
    medium_monetization = {"health", "relationships"}
    if category in high_monetization:
        score = 0.8
        explanation = f"Category '{category}' has high monetization potential"
    elif category in medium_monetization:
        score = 0.6
        explanation = f"Category '{category}' has moderate monetization potential"
    else:
        score = 0.4
        explanation = f"Category '{category}' has uncertain monetization potential"
    return DimensionScore(
        dimension=ScoreDimension.MONETIZATION,
        score=round(score, 4),
        weight=DEFAULT_WEIGHTS[ScoreDimension.MONETIZATION],
        explanation=explanation,
        evidence=[f"category={category}"],
    )


class OpportunityScorer:
    """Score content opportunities deterministically and explainably.

    Each dimension has a clear formula and produces an explanation.
    The total score is a weighted sum of normalized dimension scores.
    """

    def __init__(
        self,
        weights: Optional[dict[ScoreDimension, float]] = None,
    ):
        self._raw_weights = weights or DEFAULT_WEIGHTS
        self._weights = _normalize_weights(self._raw_weights)

    def score_opportunity(
        self,
        opportunity: ContentOpportunity,
        trend: Optional[Trend] = None,
        patterns: Optional[list[ViralPattern]] = None,
    ) -> OpportunityScore:
        """Score a single content opportunity.

        Returns an OpportunityScore with per-dimension breakdown and explanation.
        """
        dimensions: list[DimensionScore] = []
        dimensions.append(self._score_trend_strength(opportunity, trend))
        dimensions.append(self._score_freshness(opportunity, trend))
        dimensions.append(_score_audience_relevance(opportunity))
        dimensions.append(_score_content_demand(trend))
        dimensions.append(_score_competition(opportunity))
        dimensions.append(_score_production_feasibility(opportunity))
        dimensions.append(_score_viral_potential(patterns))
        dimensions.append(_score_monetization(opportunity))
        for dim in dimensions:
            dim.weight = self._weights.get(dim.dimension, dim.weight)
        total = sum(d.weighted_score for d in dimensions)
        total = max(0.0, min(1.0, total))
        explanation_parts = [
            f"{d.dimension.value}={d.score:.2f} (weight={d.weight:.2f})"
            for d in dimensions
        ]
        explanation = f"Total score={total:.3f}. " + "; ".join(explanation_parts)
        return OpportunityScore(
            total=round(total, 4),
            dimensions=dimensions,
            explanation=explanation,
        )

    def score_opportunities(
        self,
        opportunities: list[ContentOpportunity],
        trends: Optional[list[Trend]] = None,
        patterns: Optional[list[ViralPattern]] = None,
    ) -> list[ContentOpportunity]:
        """Score a list of opportunities, attaching scores in place.

        Returns the same list with each opportunity's ``score`` field populated.
        """
        trend_map: dict[str, Trend] = {}
        if trends:
            for trend in trends:
                trend_map[trend.canonical_key] = trend
        for opportunity in opportunities:
            trend = None
            if opportunity.supporting_trends:
                for t in trends or []:
                    if t.trend_id in opportunity.supporting_trends:
                        trend = t
                        break
            if trend is None:
                trend = trend_map.get(
                    opportunity.metadata.get("canonical_key", "")
                )
            opportunity.score = self.score_opportunity(
                opportunity, trend, patterns
            )
        return opportunities

    def rank_opportunities(
        self,
        opportunities: list[ContentOpportunity],
    ) -> list[ContentOpportunity]:
        """Return opportunities sorted by total score (descending)."""
        return sorted(
            opportunities,
            key=lambda o: o.score.total if o.score else 0.0,
            reverse=True,
        )

    def _score_trend_strength(
        self,
        opportunity: ContentOpportunity,
        trend: Optional[Trend],
    ) -> DimensionScore:
        """Score trend strength from trend data or opportunity metadata."""
        if trend is not None:
            score = trend.strength
            evidence = [
                f"trend_strength={trend.strength}",
                f"signal_count={trend.signal_count}",
            ]
            explanation = (
                f"Trend strength={score:.2f} from trend "
                f"'{trend.topic}' with {trend.signal_count} signals"
            )
        else:
            score = opportunity.metadata.get("trend_strength", 0.3)
            evidence = [f"metadata_trend_strength={score}"]
            explanation = (
                f"Trend strength={score:.2f} from opportunity metadata"
            )
        return DimensionScore(
            dimension=ScoreDimension.TREND_STRENGTH,
            score=round(score, 4),
            weight=self._weights[ScoreDimension.TREND_STRENGTH],
            explanation=explanation,
            evidence=evidence,
        )

    def _score_freshness(
        self,
        opportunity: ContentOpportunity,
        trend: Optional[Trend],
    ) -> DimensionScore:
        """Score freshness from trend data or opportunity metadata."""
        if trend is not None:
            score = trend.freshness
            evidence = [
                f"trend_freshness={trend.freshness}",
                f"latest_observed={trend.latest_observed.isoformat()}",
            ]
            explanation = (
                f"Freshness={score:.2f} based on latest observation at "
                f"{trend.latest_observed.isoformat()}"
            )
        else:
            score = opportunity.metadata.get("trend_freshness", 0.3)
            evidence = [f"metadata_trend_freshness={score}"]
            explanation = f"Freshness={score:.2f} from opportunity metadata"
        return DimensionScore(
            dimension=ScoreDimension.FRESHNESS,
            score=round(score, 4),
            weight=self._weights[ScoreDimension.FRESHNESS],
            explanation=explanation,
            evidence=evidence,
        )
