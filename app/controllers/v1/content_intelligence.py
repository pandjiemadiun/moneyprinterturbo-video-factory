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
        "data_source_classification": _classify_data_source(trend.sources),
    }


def _classify_data_source(sources: list) -> str:
    """Classify the data source type for transparency."""
    source_values = {s.value for s in sources}
    if source_values == {"manual"}:
        return "USER_INPUT"
    if "manual" in source_values and len(source_values) > 1:
        return "MIXED"
    if source_values - {"manual"}:
        return "EXTERNAL"
    return "UNKNOWN"


def _provider_health_to_dict(health) -> dict:
    """Convert ProviderHealth to API response dict."""
    return {
        "provider_id": health.provider_id,
        "status": health.status.value,
        "last_success_at": health.last_success_at.isoformat() if health.last_success_at else None,
        "last_failure_at": health.last_failure_at.isoformat() if health.last_failure_at else None,
        "last_error": health.last_error,
        "total_requests": health.total_requests,
        "total_failures": health.total_failures,
        "total_signals": health.total_signals,
        "success_rate": round(health.success_rate, 4),
        "average_response_time_ms": round(health.average_response_time_ms, 2),
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
    """Run the Content Intelligence pipeline.

    Modes:
    1. User topics mode (default): Analyzes user-provided topics
    2. Provider mode (use_providers=True): Fetches real data from external providers

    Data source transparency:
    - Trends are classified as USER_INPUT, EXTERNAL, or MIXED
    - Provider health is included when using providers
    - data_source_summary indicates whether external data was used
    """
    registry = ci.create_provider_registry(
        enable_google_news=True,
        enable_hackernews=True,
        geo=body.geo or "ID",
        language=body.language or "id",
    )
    pipeline = ci.ContentIntelligencePipeline(provider_registry=registry)

    result = pipeline.run(
        use_providers=body.use_providers,
        geo=body.geo or "ID",
        language=body.language or "id",
        category=body.category or "general",
        max_signals_per_provider=body.max_signals_per_provider or 20,
    )

    if not body.use_providers and body.topics:
        result = pipeline.run_from_texts(body.topics)

    provider_health_dict = {
        k: _provider_health_to_dict(v)
        for k, v in result.provider_health.items()
    }

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
            "data_source_summary": _build_data_source_summary(result),
            "provider_health": provider_health_dict,
            "total_raw_signals": result.total_raw_signals,
            "fetched_at": result.fetched_at.isoformat(),
        },
    )


def _build_data_source_summary(result) -> dict:
    """Build a summary of data sources for transparency."""
    all_sources = set()
    for trend in result.trends:
        for source in trend.sources:
            all_sources.add(source.value)
    return {
        "trend_sources": sorted(all_sources),
        "has_external_data": bool(all_sources - {"manual"}),
        "total_trends": len(result.trends),
        "total_opportunities": len(result.opportunities),
        "total_patterns": len(result.patterns),
        "total_hypotheses": len(result.hypotheses),
    }


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
