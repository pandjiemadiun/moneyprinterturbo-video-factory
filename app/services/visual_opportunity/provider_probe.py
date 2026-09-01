"""Provider probing layer.

Probes the actual configured stock-footage providers (Pexels, Pixabay,
Coverr) for visual candidates and records observed evidence.

Reuses the existing material provider implementations.

Each candidate is now relevance-checked against its visual concept and
the original topic. Only candidates that are genuinely relevant to the
topic's visual concepts count toward producibility.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from app.models.schema import MaterialInfo, VideoAspect
from app.services.visual_opportunity.models import (
    CandidateRejectionReason,
    ProviderAvailability,
    VisualCandidate,
)
from app.services.visual_opportunity.relevance import (
    RelevanceLevel,
    compute_candidate_relevance,
    compute_query_topic_relevance,
)

# Target output is 9:16 portrait short-form video
_TARGET_WIDTH = 1080
_TARGET_HEIGHT = 1920

# Minimum acceptable source dimensions for reframing eligibility
_MIN_REFRAME_WIDTH = 1920
_MIN_REFRAME_HEIGHT = 1080

# Minimum usable resolution (below this, reject)
_MIN_USABLE_WIDTH = 480
_MIN_USABLE_HEIGHT = 480

# How many sample candidates to retain per provider/query
_MAX_SAMPLE_CANDIDATES = 5


def _extract_dimensions(info: MaterialInfo) -> tuple[int, int]:
    """Extract width/height from a MaterialInfo's source_info."""
    w, h = 0, 0
    if info.source_info:
        rendition = info.source_info.get("rendition", {})
        w = int(rendition.get("width", 0) or 0)
        h = int(rendition.get("height", 0) or 0)
    return w, h


def _extract_metadata(info: MaterialInfo) -> dict[str, Any]:
    """Extract relevance-checking metadata from a MaterialInfo."""
    if not info.source_info:
        return {}
    return {
        "title": info.source_info.get("title"),
        "description": info.source_info.get("description"),
        "tags": info.source_info.get("tags", []),
        "category": info.source_info.get("category"),
        "source_page": info.source_info.get("source_page"),
    }


def _classify_candidate(info: MaterialInfo) -> VisualCandidate:
    """Classify a provider candidate into portrait/landscape/reject."""
    w, h = _extract_dimensions(info)

    candidate = VisualCandidate(
        provider=info.provider or "unknown",
        asset_id=_extract_asset_id(info),
        source_url=_extract_source_url(info),
        width=w,
        height=h,
        duration=info.duration or 0,
    )

    # Determine orientation
    if w > 0 and h > 0:
        if h > w:
            candidate.is_portrait = True
        elif w > h:
            candidate.is_landscape = True
        else:
            candidate.is_square = True

    # Quality gate
    if w > 0 and h > 0:
        if w < _MIN_USABLE_WIDTH or h < _MIN_USABLE_HEIGHT:
            candidate.rejection_reason = CandidateRejectionReason.LOW_RESOLUTION
            return candidate

    # For portrait target: landscape must be reframable
    if candidate.is_landscape:
        if w >= _MIN_REFRAME_WIDTH and h >= _MIN_REFRAME_HEIGHT:
            candidate.is_reframable = True
        else:
            candidate.rejection_reason = CandidateRejectionReason.UNABLE_TO_REFRAME
            return candidate

    if candidate.is_portrait:
        pass  # native portrait — always usable if resolution ok

    if candidate.is_square:
        pass  # square can be cropped either way

    return candidate


def _extract_asset_id(info: MaterialInfo) -> str:
    if info.source_info:
        aid = info.source_info.get("asset_id")
        if aid:
            return str(aid)
    return info.url or ""


def _extract_source_url(info: MaterialInfo) -> str:
    if info.source_info:
        page = info.source_info.get("source_page")
        if page:
            return str(page)
    return info.url or ""


def probe_provider(
    provider: str,
    query: str,
    minimum_duration: int = 3,
    llm_client: Any = None,
    topic: str = "",
    concept_id: str = "",
) -> ProviderAvailability:
    """Probe a single provider for a single query.

    Calls the real provider API via the existing material search functions.
    Records observed evidence only — no fabrication.

    Each candidate is relevance-checked against the visual concept and
    the original topic. Only relevant candidates count toward producibility.
    """
    availability = ProviderAvailability(provider=provider, query=query)
    start = time.monotonic()

    try:
        raw_results = _call_provider_search(provider, query, minimum_duration)
    except TimeoutError:
        availability.status = "TIMEOUT"
        availability.error_message = f"{provider} request timed out"
        availability.checked_at = datetime.now(timezone.utc)
        availability.response_time_ms = (time.monotonic() - start) * 1000
        return availability
    except Exception as e:
        availability.status = "ERROR"
        availability.error_message = str(e)[:200]
        availability.checked_at = datetime.now(timezone.utc)
        availability.response_time_ms = (time.monotonic() - start) * 1000
        return availability

    availability.response_time_ms = (time.monotonic() - start) * 1000
    availability.raw_count = len(raw_results)

    # Compute query-topic relevance once per probe.
    qt_relevance = compute_query_topic_relevance(query, topic) if topic else 0.5

    rejection_counts: dict[str, int] = {}
    samples: list[VisualCandidate] = []
    relevance_counts: dict[str, int] = {}

    for info in raw_results:
        candidate = _classify_candidate(info)
        if not candidate.usable:
            availability.rejected_count += 1
            reason = candidate.rejection_reason.value if candidate.rejection_reason else "UNKNOWN"
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            continue

        # --- Relevance checking ---
        from app.services.visual_opportunity.models import VisualConcept

        concept = VisualConcept(
            concept_id=concept_id or "",
            term=query,
            source="topic",
            parent_topic=topic,
        )
        metadata = _extract_metadata(info)
        rel_score, rel_level, rel_explanation = compute_candidate_relevance(
            candidate=candidate,
            concept=concept,
            topic=topic,
            metadata=metadata,
            llm_client=llm_client,
        )

        # Store relevance on the candidate via metadata dict.
        if candidate.source_info is None:
            candidate.source_info = {}
        candidate.source_info["relevance_score"] = round(rel_score, 4)
        candidate.source_info["relevance_level"] = rel_level.value
        candidate.source_info["relevance_explanation"] = rel_explanation

        relevance_counts[rel_level.value] = relevance_counts.get(rel_level.value, 0) + 1

        # Only count relevant candidates toward producibility.
        if rel_level in (
            RelevanceLevel.STRONG_RELEVANCE,
            RelevanceLevel.PARTIAL_RELEVANCE,
        ):
            availability.usable_count += 1
            if candidate.is_portrait or candidate.is_square:
                availability.native_portrait_count += 1
            if candidate.is_reframable:
                availability.reframable_landscape_count += 1
            if len(samples) < _MAX_SAMPLE_CANDIDATES:
                samples.append(candidate)
        elif rel_level == RelevanceLevel.WEAK_RELEVANCE:
            # Weak relevance: count as usable but don't boost portrait/reframe.
            availability.usable_count += 1
            if len(samples) < _MAX_SAMPLE_CANDIDATES:
                samples.append(candidate)
        else:
            # IRRELEVANT or UNKNOWN: reject for producibility.
            availability.rejected_count += 1
            rejection_counts["IRRELEVANT_TO_TOPIC"] = (
                rejection_counts.get("IRRELEVANT_TO_TOPIC", 0) + 1
            )

    availability.rejection_reasons = rejection_counts
    availability.sample_candidates = samples
    availability.relevance_counts = relevance_counts
    availability.query_topic_relevance = round(qt_relevance, 4)
    availability.checked_at = datetime.now(timezone.utc)
    return availability


def _call_provider_search(
    provider: str, query: str, minimum_duration: int
) -> list[MaterialInfo]:
    """Call the real provider search function.

    Reuses existing material provider implementations.
    """
    from app.services import material

    if provider == "pexels":
        return material.search_videos_pexels(
            search_term=query,
            minimum_duration=minimum_duration,
            video_aspect=VideoAspect.landscape,
        )
    if provider == "pixabay":
        return material.search_videos_pixabay(
            search_term=query,
            minimum_duration=minimum_duration,
            video_aspect=VideoAspect.landscape,
        )
    if provider == "coverr":
        return material.search_videos_coverr(
            search_term=query,
            minimum_duration=minimum_duration,
            video_aspect=VideoAspect.landscape,
        )
    raise ValueError(f"Unsupported provider: {provider}")


def get_configured_providers() -> list[str]:
    """Return the list of providers that have credentials configured."""
    from app.config import config

    providers: list[str] = []
    if config.app.get("pexels_api_keys"):
        providers.append("pexels")
    if config.app.get("pixabay_api_keys"):
        providers.append("pixabay")
    if config.app.get("coverr_api_keys"):
        providers.append("coverr")
    return providers
