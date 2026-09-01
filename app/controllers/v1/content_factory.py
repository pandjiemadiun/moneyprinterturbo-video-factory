"""Content Factory API controller."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, Request

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.schema import (
    ContentFactoryProduceRequest,
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

    This avoids requiring the full VisualOpportunityAssessment object
    to cross the API boundary. Only the fields needed for production
    are required.
    """
    from app.services.visual_opportunity.models import (
        VisualConcept,
        VisualFeasibilityStatus,
        VisualFeasibilityScore,
        VisualOpportunityAssessment,
        ProviderAvailability,
    )

    assessment = VisualOpportunityAssessment(
        topic=body.topic,
        status=VisualFeasibilityStatus.VISUALLY_PRODUCIBLE,
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
