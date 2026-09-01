"""Content Factory API controller."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, Request

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.schema import (
    ContentFactoryProduceRequest,
    ContentFactoryProduceResponseData,
    ContentFactoryResponse,
)
from app.services.content_factory import (
    ProductionResult,
    create_content_factory,
)

router = new_router(dependencies=[Depends(base.verify_token)])


@router.post("/content-factory/produce", response_model=ContentFactoryResponse)
async def produce_video(
    request: Request, body: ContentFactoryProduceRequest
) -> ContentFactoryResponse:
    """Produce a video from a validated visual opportunity.

    The opportunity must have passed the VISUALLY_PRODUCIBLE gate.
    The factory builds a production specification and submits it
    through the existing MPT task pipeline.
    """
    errors: list[str] = []
    result_data = ContentFactoryProduceResponseData()

    try:
        factory = create_content_factory()

        # Reconstruct assessment-like object from request.
        assessment = _build_assessment_from_request(body)

        result: ProductionResult = factory.produce(
            assessment=assessment,
            language=body.language,
            video_aspect=body.video_aspect,
            preferred_providers=body.preferred_providers,
        )

        result_data.task_id = result.task_id
        result_data.spec_id = result.spec_id
        result_data.status = result.status
        result_data.message = result.message
        result_data.success = result.success
        result_data.errors = result.errors
    except Exception as e:
        errors.append(f"content factory production failed: {e}")
        result_data.status = "failed"
        result_data.message = str(e)

    return ContentFactoryResponse(
        data=result_data
    )


def _build_assessment_from_request(body: Any) -> Any:
    """Reconstruct an assessment-like object from the request.

    The visual gate status is computed server-side from the scores.
    The frontend CANNOT bypass the gate by sending a fake status.
    """
    from app.services.visual_opportunity.models import (
        VisualConcept,
        VisualFeasibilityStatus,
        VisualFeasibilityScore,
        VisualOpportunityAssessment,
    )

    # Compute gate status server-side from scores.
    # This prevents the frontend from bypassing the gate.
    status = _compute_gate_status(
        visual_feasibility_score=body.visual_feasibility_score,
        relevance_confidence=body.relevance_confidence,
    )

    assessment = VisualOpportunityAssessment(
        topic=body.topic,
        status=status,
    )

    # Reconstruct concepts.
    concepts = []
    for vc in body.visual_concepts:
        concepts.append(
            VisualConcept(
                concept_id=vc.get("concept_id", ""),
                term=vc.get("concept", ""),
                source=vc.get("source", "topic"),
                parent_topic=body.topic,
            )
        )
    assessment.concepts = concepts

    # Reconstruct feasibility score.
    assessment.feasibility_score = VisualFeasibilityScore(
        total=body.visual_feasibility_score,
    )
    assessment.relevance_confidence = body.relevance_confidence

    return assessment


def _compute_gate_status(
    visual_feasibility_score: float,
    relevance_confidence: float,
) -> Any:
    """Compute the visual gate status from scores.

    Mirrors the thresholds used in the Phase 12 scorer.
    """
    from app.services.visual_opportunity.models import VisualFeasibilityStatus

    # PRODUCIBLE requires both sufficient score AND relevance.
    if visual_feasibility_score >= 0.6 and relevance_confidence >= 0.35:
        return VisualFeasibilityStatus.VISUALLY_PRODUCIBLE
    elif visual_feasibility_score >= 0.3 and relevance_confidence >= 0.2:
        return VisualFeasibilityStatus.VISUALLY_LIMITED
    elif visual_feasibility_score > 0:
        return VisualFeasibilityStatus.NOT_VISUALLY_PRODUCIBLE
    return VisualFeasibilityStatus.CHECK_FAILED
