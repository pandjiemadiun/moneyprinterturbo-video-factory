"""Visual relevance checking.

Implements a deterministic, explainable relevance gate that determines
whether a provider result is genuinely useful for a visual concept
and, by extension, for the original topic.

Relevance is computed in layers:

  Layer 1 — Provider metadata matching
    Title, description, tags, URL slug vs. the search query.

  Layer 2 — Deterministic lexical/concept matching
    Token overlap between query and topic concepts.
    Penalty for generic-only matches.

  Layer 3 — Optional semantic LLM evaluation
    Only when an LLM client is available.
    Never fabricates an answer; deterministic fallback when unavailable.

Every candidate is classified as:
  STRONG_RELEVANCE   — directly supports the visual concept
  PARTIAL_RELEVANCE  — tangentially related
  WEAK_RELEVANCE     — minimal connection
  IRRELEVANT         — no meaningful connection
  UNKNOWN            — insufficient evidence to decide

UNKNOWN never counts as strong evidence.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from app.services.visual_opportunity.models import VisualCandidate, VisualConcept


class RelevanceLevel(str, Enum):
    """Relevance classification for a provider result."""

    STRONG_RELEVANCE = "STRONG_RELEVANCE"
    PARTIAL_RELEVANCE = "PARTIAL_RELEVANCE"
    WEAK_RELEVANCE = "WEAK_RELEVANCE"
    IRRELEVANT = "IRRELEVANT"
    UNKNOWN = "UNKNOWN"


# Thresholds for classifying a continuous relevance score.
_STRONG_THRESHOLD = 0.75
_PARTIAL_THRESHOLD = 0.45
_WEAK_THRESHOLD = 0.20

# Generic terms that, on their own, do not strongly connect a result
# to a specific topic. These receive a relevance penalty unless the
# result metadata provides specific connecting evidence.
_GENERIC_TERMS: set[str] = {
    "people", "person", "man", "woman", "child", "group", "crowd",
    "city", "urban", "building", "street", "road", "town",
    "landscape", "nature", "outdoor", "scenery", "view",
    "forest", "tree", "trees", "plant", "plants", "flower",
    "sky", "cloud", "clouds", "sun", "sunrise", "sunset",
    "water", "river", "lake", "pond", "rain", "snow",
    "business", "office", "work", "working", "meeting",
    "technology", "computer", "digital", "data", "screen",
    "background", "texture", "abstract", "pattern", "design",
    "light", "lights", "dark", "night", "dramatic", "cinematic",
    "closeup", "close-up", "slow motion", "slowmotion", "timelapse",
    "aerial", "drone", "footage", "video", "clip", "b-roll", "broll",
    "walking", "running", "standing", "sitting", "talking",
    "happy", "sad", "emotion", "feeling", "lifestyle",
    "modern", "beautiful", "amazing", "incredible", "stunning",
}

# Penalty applied when a query consists only of generic terms.
_GENERIC_QUERY_PENALTY = 0.3

# Bonus when result metadata specifically matches the query.
_METADATA_MATCH_BONUS = 0.25


def _tokenize(text: str) -> set[str]:
    """Tokenize text into lowercase alphabetic tokens."""
    if not text:
        return set()
    return set(re.findall(r"[a-z]+", text.lower()))


def _canonicalize(text: str) -> str:
    """Normalize text for comparison."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def classify_relevance(score: float) -> RelevanceLevel:
    """Classify a continuous relevance score into a level."""
    if score >= _STRONG_THRESHOLD:
        return RelevanceLevel.STRONG_RELEVANCE
    if score >= _PARTIAL_THRESHOLD:
        return RelevanceLevel.PARTIAL_RELEVANCE
    if score >= _WEAK_THRESHOLD:
        return RelevanceLevel.WEAK_RELEVANCE
    if score > 0.0:
        return RelevanceLevel.IRRELEVANT
    return RelevanceLevel.UNKNOWN


def _stem(token: str) -> str:
    """Apply lightweight English stemming for matching.

    Handles common plural/suffix forms so that "mountain" matches
    "mountains", "running" matches "run", etc.
    """
    if not token:
        return token
    # Order matters: try longer suffixes first.
    for suffix in ("less", "ness", "ping", "king", "ting", "ding",
                   "ming", "ning", "ring", "sing", "ting", "ving",
                   "zing", "ches", "shes", "sses", "tions", "sions",
                   "ings", "ment", "ness", "able", "ible", "ful", "ous",
                   "ive", "ing", "ies", "ion", "ism", "ist", "ity",
                   "ess", "ous", "ers", "ers", "est", "ial", "ful"):
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            return token[: -len(suffix)]
    # Simple plural: remove trailing 's' for words > 3 chars.
    if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        return token[:-1]
    return token


def _stem_tokens(tokens: set[str]) -> set[str]:
    """Stem a set of tokens."""
    return {_stem(t) for t in tokens}


def compute_query_topic_relevance(query: str, topic: str) -> float:
    """Compute how relevant a search query is to the original topic.

    This is the primary gate: even a perfect provider result for a
    generic query should not strongly support an unrelated topic.

    Returns a score in [0, 1].
    """
    query_c = _canonicalize(query)
    topic_c = _canonicalize(topic)

    if not query_c or not topic_c:
        return 0.0

    # Exact match with topic → strongest signal.
    if query_c == topic_c:
        return 1.0

    # Query is a substring of topic or vice versa.
    if query_c in topic_c or topic_c in query_c:
        return 0.9

    # Token overlap analysis with stemming.
    query_tokens = _tokenize(query_c)
    topic_tokens = _tokenize(topic_c)

    if not query_tokens or not topic_tokens:
        return 0.0

    # Stem both sides for fuzzy matching.
    query_stems = _stem_tokens(query_tokens)
    topic_stems = _stem_tokens(topic_tokens)

    # How many query tokens appear in the topic (exact or stemmed)?
    exact_matches = query_tokens & topic_tokens
    stem_matches = query_stems & topic_stems
    matching = exact_matches | stem_matches

    coverage = len(matching) / len(query_tokens) if query_tokens else 0.0

    # Penalize queries that are entirely generic.
    is_generic_query = query_tokens and query_tokens.issubset(_GENERIC_TERMS)
    if is_generic_query:
        # Generic queries get at most the penalty ceiling.
        return min(coverage, _GENERIC_QUERY_PENALTY)

    # Non-generic queries with good token overlap are relevant.
    return min(1.0, coverage)


def compute_metadata_relevance(
    candidate: VisualCandidate,
    query: str,
    metadata: dict[str, Any] | None = None,
) -> float:
    """Compute relevance based on provider metadata (Layer 1).

    Checks whether the result's title, description, tags, or URL
    contain the search query terms.

    Returns a score in [0, 1].
    """
    if metadata is None:
        metadata = _extract_metadata(candidate)

    query_tokens = _tokenize(query)
    if not query_tokens:
        return 0.0

    # Collect all searchable text from metadata.
    searchable_parts: list[str] = []
    for key in ("title", "description", "tags", "category", "slug"):
        val = metadata.get(key)
        if isinstance(val, str):
            searchable_parts.append(val)
        elif isinstance(val, list):
            searchable_parts.extend(str(v) for v in val if v)
    # Also check source URL for query terms.
    if candidate.source_url:
        searchable_parts.append(candidate.source_url)

    if not searchable_parts:
        return 0.0

    searchable_text = " ".join(searchable_parts).lower()
    searchable_tokens = _tokenize(searchable_text)

    if not searchable_tokens:
        return 0.0

    matching = query_tokens & searchable_tokens
    coverage = len(matching) / len(query_tokens)

    # Boost if the full query phrase appears in the metadata.
    query_c = _canonicalize(query)
    if query_c and any(query_c in _canonicalize(p) for p in searchable_parts):
        coverage = min(1.0, coverage + _METADATA_MATCH_BONUS)

    return min(1.0, coverage)


def compute_candidate_relevance(
    candidate: VisualCandidate,
    concept: VisualConcept,
    topic: str,
    metadata: dict[str, Any] | None = None,
    llm_client: Any = None,
) -> tuple[float, RelevanceLevel, str]:
    """Compute overall relevance of a candidate for a visual concept.

    Combines:
      - Query-topic relevance (is the search query relevant to the topic?)
      - Metadata relevance (does the result metadata match the query?)
      - Optional LLM semantic evaluation (Layer 3)

    Returns (score, level, explanation).
    """
    query = concept.term

    # Layer 1: Provider metadata relevance.
    meta_score = compute_metadata_relevance(candidate, query, metadata)
    has_metadata = metadata is not None and len(metadata) > 0

    # Layer 2: Query-topic relevance (deterministic lexical).
    qt_score = compute_query_topic_relevance(query, topic)

    # Combine: a result is only as relevant as the least relevant link.
    # If the query is generic (low qt_score), even perfect metadata match
    # cannot make it strongly relevant to the topic.
    if qt_score <= 0.0:
        combined = 0.0
    elif has_metadata and meta_score <= 0.0:
        # Metadata IS available but does NOT match the query → irrelevant.
        # The result is genuinely unrelated to what we searched for.
        combined = 0.0
    elif meta_score <= 0.0:
        # No metadata to validate; rely on query-topic relevance alone,
        # discounted because we cannot confirm the result matches.
        combined = qt_score * 0.4
    else:
        # Both signals present: geometric mean to require both.
        import math
        combined = math.sqrt(qt_score * meta_score)

    # Layer 3: Optional LLM semantic evaluation.
    llm_score: float | None = None
    if llm_client is not None:
        try:
            llm_score = _llm_evaluate_relevance(candidate, concept, topic, llm_client)
        except Exception:
            llm_score = None  # LLM is best-effort

    if llm_score is not None:
        # Weighted combination: deterministic signals + LLM inference.
        # LLM contributes at most 30% to avoid overriding hard evidence.
        combined = 0.7 * combined + 0.3 * llm_score

    combined = max(0.0, min(1.0, combined))
    level = classify_relevance(combined)
    explanation = _build_relevance_explanation(qt_score, meta_score, llm_score, level)

    return combined, level, explanation


def _llm_evaluate_relevance(
    candidate: VisualCandidate,
    concept: VisualConcept,
    topic: str,
    llm_client: Any,
) -> float | None:
    """Use LLM to evaluate relevance (Layer 3).

    Returns a score in [0, 1] or None if evaluation fails.
    """
    prompt = (
        f"Topic: {topic}\n"
        f"Visual concept: {concept.term}\n"
        f"Provider: {candidate.provider}\n"
        f"Source: {candidate.source_url}\n"
        f"On a scale of 0 to 1, how relevant is this footage to the "
        f"visual concept '{concept.term}' for a video about '{topic}'? "
        f"Return ONLY a number between 0 and 1, nothing else."
    )
    try:
        response = llm_client.generate(prompt)
    except Exception:
        return None

    if not response:
        return None

    # Extract the first number from the response.
    match = re.search(r"0?\.\d+|0|1", response.strip())
    if match:
        try:
            score = float(match.group())
            return max(0.0, min(1.0, score))
        except ValueError:
            return None
    return None


def _extract_metadata(candidate: VisualCandidate) -> dict[str, Any]:
    """Extract searchable metadata from a candidate's source_info."""
    metadata: dict[str, Any] = {}
    # The provider field itself can be a weak signal.
    if candidate.provider:
        metadata["provider"] = candidate.provider
    return metadata


def _build_relevance_explanation(
    qt_score: float,
    meta_score: float,
    llm_score: float | None,
    level: RelevanceLevel,
) -> str:
    """Build a human-readable relevance explanation."""
    parts: list[str] = []
    parts.append(f"query-topic: {qt_score:.2f}")
    if meta_score > 0:
        parts.append(f"metadata: {meta_score:.2f}")
    if llm_score is not None:
        parts.append(f"llm: {llm_score:.2f}")
    parts.append(f"verdict: {level.value}")
    return ", ".join(parts)


def is_generic_term(term: str) -> bool:
    """Check if a term is generic (not specific to any topic)."""
    canonical = _canonicalize(term)
    tokens = _tokenize(canonical)
    if not tokens:
        return True
    return tokens.issubset(_GENERIC_TERMS)


def relevance_level_to_score(level: RelevanceLevel) -> float:
    """Convert a relevance level to a numeric weight for scoring."""
    return {
        RelevanceLevel.STRONG_RELEVANCE: 1.0,
        RelevanceLevel.PARTIAL_RELEVANCE: 0.6,
        RelevanceLevel.WEAK_RELEVANCE: 0.3,
        RelevanceLevel.IRRELEVANT: 0.0,
        RelevanceLevel.UNKNOWN: 0.1,
    }.get(level, 0.0)
