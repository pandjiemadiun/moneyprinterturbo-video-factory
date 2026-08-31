"""Trend -> Content Hypothesis — structured hypothesis generation.

Converts high-quality opportunities into structured content hypotheses.

A hypothesis contains enough information for downstream content generation
to act on it:
- topic
- audience
- angle
- proposed hook
- content promise
- format
- supporting trend evidence
- viral pattern evidence
- opportunity score
- confidence
- suggested search/content keywords
- rationale

The hypothesis is structured data, not merely free-form text.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from loguru import logger

from app.services.content_intelligence.models import (
    ContentHypothesis,
    ContentOpportunity,
    Trend,
    ViralPattern,
    _stable_id,
)


_MAX_LLM_RETRIES = 3


def _select_format(category: str) -> str:
    """Select a default short-video format based on category."""
    format_map = {
        "technology": "listicle",
        "health": "explainer",
        "finance": "storytelling",
        "relationships": "advice",
        "productivity": "listicle",
        "education": "explainer",
        "entertainment": "compilation",
    }
    return format_map.get(category, "explainer")


def _extract_keywords_from_trend(trend: Optional[Trend]) -> list[str]:
    """Extract search keywords from a trend."""
    if trend is None:
        return []
    keywords: list[str] = []
    topic = trend.topic.lower()
    tokens = re.findall(r"[a-z0-9]+", topic)
    stop_words = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
        "for", "of", "with", "by", "is", "are", "was", "were", "be",
        "this", "that", "it", "its", "how", "why", "what", "when",
    }
    for token in tokens:
        if token not in stop_words and len(token) > 2:
            keywords.append(token)
    return keywords[:5]


def _generate_hook_heuristic(topic: str, angle: str) -> str:
    """Generate a heuristic hook when LLM is unavailable."""
    if "?" in topic:
        return topic
    if topic.lower().startswith(("why ", "how ", "what ")):
        return topic
    return f"The truth about {topic} you need to know"


def _generate_promise_heuristic(topic: str, angle: str) -> str:
    """Generate a heuristic content promise when LLM is unavailable."""
    return f"Discover {angle}"


class HypothesisGenerator:
    """Generate structured content hypotheses from opportunities.

    Uses deterministic heuristics for core fields, with optional LLM
    enhancement for creative fields (hook, promise) when available.
    LLM-generated fields are distinguishable from deterministic ones.
    """

    def __init__(self, llm_client=None, min_score: float = 0.0):
        """Initialize with an optional LLM client and minimum score threshold."""
        self._llm_client = llm_client
        self._min_score = min_score

    def generate_hypothesis(
        self,
        opportunity: ContentOpportunity,
        trend: Optional[Trend] = None,
        patterns: Optional[list[ViralPattern]] = None,
    ) -> Optional[ContentHypothesis]:
        """Generate a structured content hypothesis from an opportunity.

        Returns None if the opportunity doesn't meet the minimum score threshold.
        """
        score_total = (
            opportunity.score.total if opportunity.score else 0.0
        )
        if score_total < self._min_score:
            logger.debug(
                f"opportunity {opportunity.opportunity_id} score "
                f"{score_total:.3f} below threshold {self._min_score}; skipping"
            )
            return None
        category = opportunity.metadata.get("category", "general")
        fmt = _select_format(category)
        hook = _generate_hook_heuristic(opportunity.topic, opportunity.angle)
        promise = _generate_promise_heuristic(
            opportunity.topic, opportunity.angle
        )
        if self._llm_client is not None:
            llm_creative = self._enhance_creative_with_llm(opportunity)
            if llm_creative:
                if llm_creative.get("hook"):
                    hook = llm_creative["hook"]
                if llm_creative.get("promise"):
                    promise = llm_creative["promise"]
        trend_evidence = list(opportunity.evidence)
        if trend is not None:
            trend_evidence.append(
                f"trend_strength={trend.strength:.2f}, "
                f"freshness={trend.freshness:.2f}"
            )
        viral_evidence: list[str] = []
        if patterns:
            for p in patterns:
                viral_evidence.append(
                    f"{p.pattern_type.value}: {p.name} "
                    f"(confidence={p.confidence:.2f})"
                )
        keywords = _extract_keywords_from_trend(trend)
        keywords.extend(opportunity.metadata.get("extra_keywords", []))
        keywords = list(dict.fromkeys(keywords))
        confidence = (
            opportunity.score.total * 0.7 + opportunity.metadata.get(
                "trend_confidence", 0.5
            ) * 0.3
        ) if opportunity.score else 0.5
        confidence = max(0.0, min(1.0, confidence))
        return ContentHypothesis(
            hypothesis_id=_stable_id(
                opportunity.canonical_key
                if hasattr(opportunity, "canonical_key")
                else opportunity.topic,
                str(opportunity.opportunity_id),
            ),
            topic=opportunity.topic,
            audience=opportunity.audience,
            angle=opportunity.angle,
            proposed_hook=hook,
            content_promise=promise,
            format=fmt,
            trend_evidence=trend_evidence,
            viral_pattern_evidence=viral_evidence,
            opportunity_score=opportunity.score,
            confidence=round(confidence, 4),
            keywords=keywords[:10],
            rationale=opportunity.rationale,
            metadata={
                "source_opportunity_id": opportunity.opportunity_id,
                "category": category,
                "llm_enhanced": self._llm_client is not None,
            },
        )

    def generate_hypotheses(
        self,
        opportunities: list[ContentOpportunity],
        trends: Optional[list[Trend]] = None,
        patterns: Optional[list[ViralPattern]] = None,
    ) -> list[ContentHypothesis]:
        """Generate hypotheses from a list of opportunities.

        Only opportunities above the minimum score threshold produce hypotheses.
        """
        if not opportunities:
            return []
        trend_map: dict[str, Trend] = {}
        if trends:
            for trend in trends:
                trend_map[trend.canonical_key] = trend
        hypotheses: list[ContentHypothesis] = []
        for opportunity in opportunities:
            trend = None
            if opportunity.supporting_trends:
                for t in trends or []:
                    if t.trend_id in opportunity.supporting_trends:
                        trend = t
                        break
            if trend is None and trends:
                topic_key = opportunity.topic.lower().strip()
                trend = trend_map.get(topic_key)
            hypothesis = self.generate_hypothesis(
                opportunity, trend, patterns
            )
            if hypothesis is not None:
                hypotheses.append(hypothesis)
        hypotheses.sort(
            key=lambda h: h.confidence, reverse=True
        )
        logger.info(
            f"generated {len(hypotheses)} hypotheses from "
            f"{len(opportunities)} opportunities"
        )
        return hypotheses

    def _enhance_creative_with_llm(
        self, opportunity: ContentOpportunity
    ) -> Optional[dict[str, str]]:
        """Use LLM to enhance creative fields (hook, promise).

        Returns None if LLM is unavailable or returns invalid output.
        LLM-generated fields are marked in metadata as llm_enhanced.
        """
        if self._llm_client is None:
            return None
        prompt = (
            "Given a short-video content opportunity:\n"
            f"- Topic: {opportunity.topic}\n"
            f"- Angle: {opportunity.angle}\n"
            f"- Audience: {opportunity.audience}\n"
            f"- Category: {opportunity.metadata.get('category', 'general')}\n\n"
            "Generate a compelling hook (one sentence, max 15 words) "
            "and a content promise (one sentence, max 15 words).\n\n"
            "Return a JSON object with exactly these keys:\n"
            '- "hook": the proposed hook\n'
            '- "promise": the content promise\n\n'
            "Return ONLY the JSON object, no other text."
        )
        for attempt in range(_MAX_LLM_RETRIES):
            try:
                response = self._llm_client.generate(prompt)
                if not response:
                    continue
                cleaned = response.strip()
                if cleaned.startswith("```"):
                    cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
                    cleaned = re.sub(r"\s*```$", "", cleaned)
                data = json.loads(cleaned)
                if not isinstance(data, dict):
                    logger.warning("LLM creative response is not a JSON object")
                    continue
                result: dict[str, str] = {}
                hook = str(data.get("hook", "")).strip()
                promise = str(data.get("promise", "")).strip()
                if hook:
                    result["hook"] = hook[:200]
                if promise:
                    result["promise"] = promise[:200]
                if result:
                    return result
            except json.JSONDecodeError as exc:
                logger.warning(
                    f"LLM creative response is not valid JSON "
                    f"(attempt {attempt + 1}): {exc}"
                )
            except Exception as exc:
                logger.warning(
                    f"LLM creative enhancement failed "
                    f"(attempt {attempt + 1}): {exc}"
                )
        return None
