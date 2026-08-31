"""Content Intelligence API controller.

Provides endpoints for running the Content Intelligence pipeline and
retrieving structured content hypotheses ready for downstream content
generation.
"""

from fastapi import Depends, Request

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.schema import (
    ContentIntelligenceRequest,
    ContentIntelligenceResponse,
)
from app.services import content_intelligence as ci
from app.utils import utils

router = new_router(dependencies=[Depends(base.verify_token)])


def _trend_to_dict(trend) -> dict:
    return {
        "trend_id": trend.trend_id,
        "topic": trend.topic,
        "sources": [s.value for s in trend.sources],
        "providers": trend.providers,
        "signal_count": trend.signal_count,
        "confidence": trend.confidence,
        "strength": trend.strength,
        "freshness": trend.freshness,
        "first_observed": trend.first_observed.isoformat(),
        "latest_observed": trend.latest_observed.isoformat(),
        "evidence": trend.evidence,
    }


def _opportunity_to_dict(opp) -> dict:
    return {
        "opportunity_id": opp.opportunity_id,
        "topic": opp.topic,
        "audience": opp.audience,
        "angle": opp.angle,
        "timeliness": opp.timeliness,
        "rationale": opp.rationale,
        "evidence": opp.evidence,
        "score_total": opp.score.total if opp.score else None,
        "score_explanation": (
            opp.score.explanation if opp.score else None
        ),
        "score_dimensions": [
            {
                "dimension": d.dimension.value,
                "score": d.score,
                "weight": d.weight,
                "explanation": d.explanation,
            }
            for d in (opp.score.dimensions if opp.score else [])
        ],
    }


def _pattern_to_dict(pattern) -> dict:
    return {
        "pattern_type": pattern.pattern_type.value,
        "name": pattern.name,
        "description": pattern.description,
        "confidence": pattern.confidence,
        "evidence": [
            {
                "description": e.description,
                "is_observed": e.is_observed,
                "source": e.source,
                "confidence": e.confidence,
            }
            for e in pattern.evidence
        ],
    }


def _hypothesis_to_dict(hyp) -> dict:
    return {
        "hypothesis_id": hyp.hypothesis_id,
        "topic": hyp.topic,
        "audience": hyp.audience,
        "angle": hyp.angle,
        "proposed_hook": hyp.proposed_hook,
        "content_promise": hyp.content_promise,
        "format": hyp.format,
        "confidence": hyp.confidence,
        "keywords": hyp.keywords,
        "rationale": hyp.rationale,
        "trend_evidence": hyp.trend_evidence,
        "viral_pattern_evidence": hyp.viral_pattern_evidence,
        "score_total": (
            hyp.opportunity_score.total if hyp.opportunity_score else None
        ),
        "created_at": hyp.created_at.isoformat(),
    }


@router.post(
    "/content-intelligence/analyze",
    response_model=ContentIntelligenceResponse,
    summary="Run the Content Intelligence pipeline",
)
def analyze_content_intelligence(
    request: Request, body: ContentIntelligenceRequest
):
    """Run the complete Content Intelligence pipeline on the given topics.

    The pipeline:
    1. Detects trends from input topics
    2. Mines content opportunities
    3. Analyzes viral patterns
    4. Scores opportunities deterministically
    5. Generates structured content hypotheses

    Returns all intermediate and final outputs for full traceability.
    """
    pipeline = ci.ContentIntelligencePipeline()
    result = pipeline.run_from_texts(body.topics)
    return utils.get_response(
        200,
        {
            "trends": [_trend_to_dict(t) for t in result.trends],
            "opportunities": [
                _opportunity_to_dict(o) for o in result.opportunities
            ],
            "patterns": [_pattern_to_dict(p) for p in result.patterns],
            "hypotheses": [
                _hypothesis_to_dict(h) for h in result.hypotheses
            ],
            "success": result.success,
            "errors": result.errors,
        },
    )


@router.post(
    "/content-intelligence/hypotheses",
    response_model=ContentIntelligenceResponse,
    summary="Generate content hypotheses from topics",
)
def generate_hypotheses(request: Request, body: ContentIntelligenceRequest):
    """Generate content hypotheses (convenience endpoint).

    Same as /analyze but only returns the final hypotheses.
    """
    pipeline = ci.ContentIntelligencePipeline()
    result = pipeline.run_from_texts(body.topics)
    return utils.get_response(
        200,
        {
            "trends": [],
            "opportunities": [],
            "patterns": [],
            "hypotheses": [
                _hypothesis_to_dict(h) for h in result.hypotheses
            ],
            "success": result.success,
            "errors": result.errors,
        },
    )
