"""Visual Opportunity Engine API controller."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, Request

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.schema import (
    ProviderAvailabilitySchema,
    VisualFeasibilityScoreSchema,
    VisualOpportunityAssessmentSchema,
    VisualOpportunityRequest,
    VisualOpportunityResponse,
    VisualOpportunityResponseData,
)
from app.services.visual_opportunity import (
    VisualOpportunityAssessment,
    VisualOpportunityEngine,
    create_visual_opportunity_engine,
)

router = new_router(dependencies=[Depends(base.verify_token)])


def _score_to_schema(score) -> VisualFeasibilityScoreSchema:
    return VisualFeasibilityScoreSchema(
        total=score.total,
        quantity_score=score.quantity_score,
        provider_diversity_score=score.provider_diversity_score,
        portrait_readiness_score=score.portrait_readiness_score,
        resolution_sufficiency_score=score.resolution_sufficiency_score,
        scene_diversity_score=score.scene_diversity_score,
        provider_health_score=score.provider_health_score,
        explanation=score.explanation,
        component_weights=dict(score.component_weights or {}),
        scored_at=score.scored_at.isoformat() if score.scored_at else "",
    )


def _pa_to_schema(pa) -> ProviderAvailabilitySchema:
    sample_urls = [c.source_url for c in pa.sample_candidates if c.source_url]
    return ProviderAvailabilitySchema(
        provider=pa.provider,
        query=pa.query,
        status=pa.status,
        error_message=pa.error_message,
        raw_count=pa.raw_count,
        usable_count=pa.usable_count,
        native_portrait_count=pa.native_portrait_count,
        reframable_landscape_count=pa.reframable_landscape_count,
        rejected_count=pa.rejected_count,
        rejection_reasons=dict(pa.rejection_reasons),
        sample_source_urls=sample_urls[:5],
        checked_at=pa.checked_at.isoformat() if pa.checked_at else "",
        is_cached=pa.is_cached,
        response_time_ms=round(pa.response_time_ms, 1),
    )


def _assessment_to_schema(
    a: VisualOpportunityAssessment,
) -> VisualOpportunityAssessmentSchema:
    return VisualOpportunityAssessmentSchema(
        assessment_id=a.assessment_id,
        topic=a.topic,
        status=a.status.value,
        feasibility_score=_score_to_schema(a.feasibility_score),
        concepts=[c.term for c in a.concepts],
        provider_availability=[_pa_to_schema(pa) for pa in a.provider_availability],
        total_usable=a.total_usable,
        total_native_portrait=a.total_native_portrait,
        total_reframable_landscape=a.total_reframable_landscape,
        total_rejected=a.total_rejected,
        concepts_with_material=a.concepts_with_material,
        concepts_without_material=a.concepts_without_material,
        provider_health=dict(a.provider_health),
        checked_at=a.checked_at.isoformat() if a.checked_at else "",
        is_cached=a.is_cached,
    )


@router.post("/visual-opportunity/analyze", response_model=VisualOpportunityResponse)
async def analyze_visual_opportunity(
    request: Request, body: VisualOpportunityRequest
) -> VisualOpportunityResponse:
    """Assess visual feasibility for one or more topics."""
    errors: list[str] = []
    assessments: list[VisualOpportunityAssessmentSchema] = []

    try:
        # Cap the number of topics to assess to avoid provider hammering
        # and API timeouts. 5 topics is a reasonable default for a single request.
        max_assess = min(len(body.topics), 8) if body.topics else 5
        engine = create_visual_opportunity_engine(
            providers=body.providers,
            max_opportunities=max_assess,
        )
        engine.max_queries_per_topic = body.max_queries_per_topic

        results = engine.assess_opportunities(
            topics=body.topics,
            category=body.category,
            force_refresh=body.force_refresh,
        )
        assessments = [_assessment_to_schema(a) for a in results]
    except Exception as e:
        errors.append(f"visual opportunity analysis failed: {e}")

    return VisualOpportunityResponse(
        data=VisualOpportunityResponseData(
            assessments=assessments,
            success=len(errors) == 0,
            errors=errors,
            checked_at=datetime.now(timezone.utc).isoformat(),
        )
    )
