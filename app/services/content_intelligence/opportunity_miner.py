"""Opportunity Mining — transform trend signals into content opportunities.

Transforms trend signals into content opportunities. An opportunity answers:
- What topic can be created?
- Why is it worth creating?
- Who is the likely audience?
- What content angle is available?
- What makes the opportunity timely?
- What evidence supports it?

Avoids simply copying trend titles. The system identifies angles and gaps
where possible.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from loguru import logger

from app.services.content_intelligence.models import (
    ContentOpportunity,
    NormalizedSignal,
    Trend,
    ViralPattern,
    _stable_id,
)


_MAX_LLM_RETRIES = 3


def _classify_topic_category(topic: str) -> str:
    """Heuristic classification of a topic into a broad content category."""
    topic_lower = topic.lower()
    categories = {
        "technology": [
            "ai", "artificial intelligence", "tech", "software", "app",
            "robot", "machine learning", "gadget", "computer", "digital",
            "crypto", "blockchain", "vr", "automation",
        ],
        "health": [
            "health", "fitness", "diet", "mental health", "sleep",
            "exercise", "nutrition", "wellness", "yoga", "meditation",
            "weight", "anxiety", "stress",
        ],
        "finance": [
            "money", "finance", "invest", "stock", "budget", "saving",
            "wealth", "income", "debt", "credit", "economy", "trading",
            "financial", "rich", "poor",
        ],
        "relationships": [
            "relationship", "love", "dating", "marriage", "friend",
            "social", "family", "parent", "divorce", "trust", "lonely",
        ],
        "productivity": [
            "productivity", "habit", "focus", "time management",
            "procrastination", "goal", "routine", "motivation",
            "success", "career", "work",
        ],
        "education": [
            "learn", "education", "study", "school", "student",
            "teacher", "course", "knowledge", "skill", "language",
        ],
        "entertainment": [
            "movie", "music", "game", "celebrity", "show", "concert",
            "fashion", "art", "travel", "food", "recipe",
        ],
    }
    for category, keywords in categories.items():
        for keyword in keywords:
            if keyword in topic_lower:
                return category
    return "general"


def _infer_audience(category: str, topic: str) -> str:
    """Infer likely audience based on topic category."""
    audience_map = {
        "technology": "tech enthusiasts and early adopters",
        "health": "health-conscious adults",
        "finance": "adults interested in personal finance",
        "relationships": "adults navigating social dynamics",
        "productivity": "professionals and students",
        "education": "learners and educators",
        "entertainment": "general entertainment audience",
        "general": "general audience",
    }
    return audience_map.get(category, "general audience")


def _generate_angle(category: str, topic: str) -> str:
    """Generate a content angle based on topic category.

    This is a deterministic heuristic, not an LLM call, to avoid simply
    copying trend titles.
    """
    angle_map = {
        "technology": f"how {topic} is changing everyday life",
        "health": f"practical {topic} strategies backed by evidence",
        "finance": f"what {topic} means for ordinary people",
        "relationships": f"the hidden psychology behind {topic}",
        "productivity": f"actionable {topic} techniques that work",
        "education": f"a beginner-friendly breakdown of {topic}",
        "entertainment": f"the most surprising things about {topic}",
        "general": f"a fresh perspective on {topic}",
    }
    return angle_map.get(category, f"a fresh perspective on {topic}")


class OpportunityMiner:
    """Transform trend signals into content opportunities.

    Uses deterministic heuristics for initial opportunity generation,
    with optional LLM enhancement for angle refinement when an LLM
    provider is available.
    """

    def __init__(self, llm_client=None):
        """Initialize with an optional LLM client for angle enhancement.

        The llm_client must expose a ``generate(prompt) -> str`` method.
        If None, the miner operates purely on deterministic heuristics.
        """
        self._llm_client = llm_client

    def mine_opportunities(
        self,
        trends: list[Trend],
        patterns: Optional[list[ViralPattern]] = None,
    ) -> list[ContentOpportunity]:
        """Mine content opportunities from detected trends.

        Each trend yields at most one opportunity. Weak trends (below
        ``min_strength``) may be rejected if they lack supporting evidence.
        """
        if not trends:
            logger.info("opportunity miner: no trends provided")
            return []
        opportunities: list[ContentOpportunity] = []
        seen_topics: set[str] = set()
        for trend in trends:
            if trend.canonical_key in seen_topics:
                continue
            if trend.strength < 0.05 and trend.signal_count < 2:
                logger.debug(
                    f"skipping weak trend: {trend.topic} "
                    f"(strength={trend.strength})"
                )
                continue
            opportunity = self._build_opportunity(trend, patterns)
            if opportunity is not None:
                opportunities.append(opportunity)
                seen_topics.add(trend.canonical_key)
        logger.info(
            f"opportunity miner: produced {len(opportunities)} opportunities "
            f"from {len(trends)} trends"
        )
        return opportunities

    def _build_opportunity(
        self,
        trend: Trend,
        patterns: Optional[list[ViralPattern]] = None,
    ) -> Optional[ContentOpportunity]:
        """Build a single ContentOpportunity from a Trend."""
        category = _classify_topic_category(trend.topic)
        audience = _infer_audience(category, trend.topic)
        angle = _generate_angle(category, trend.topic)
        if self._llm_client is not None:
            enhanced_angle = self._enhance_angle_with_llm(trend, angle)
            if enhanced_angle:
                angle = enhanced_angle
        evidence = list(trend.evidence)
        if trend.signal_count > 1:
            evidence.append(
                f"observed {trend.signal_count} times across "
                f"{len(trend.sources)} source(s)"
            )
        if trend.freshness >= 0.7:
            timeliness = "trending now (high freshness)"
        elif trend.freshness >= 0.3:
            timeliness = "recently emerging"
        else:
            timeliness = "evergreen topic with residual interest"
        rationale = (
            f"'{trend.topic}' is a {category} topic with "
            f"strength={trend.strength:.2f} and freshness={trend.freshness:.2f}. "
            f"The angle '{angle}' addresses {audience}."
        )
        return ContentOpportunity(
            opportunity_id=_stable_id(
                trend.canonical_key, str(trend.latest_observed.timestamp())
            ),
            topic=trend.topic,
            rationale=rationale,
            audience=audience,
            angle=angle,
            timeliness=timeliness,
            evidence=evidence,
            supporting_trends=[trend.trend_id],
            metadata={
                "category": category,
                "trend_strength": trend.strength,
                "trend_freshness": trend.freshness,
                "trend_confidence": trend.confidence,
                "trend_signal_count": trend.signal_count,
                "trend_sources": [s.value for s in trend.sources],
            },
        )

    def _enhance_angle_with_llm(
        self, trend: Trend, fallback_angle: str
    ) -> Optional[str]:
        """Optionally refine the content angle using an LLM.

        Returns None if the LLM is unavailable or returns invalid output.
        Never fabricates an angle if the LLM fails.
        """
        if self._llm_client is None:
            return None
        prompt = (
            f"Given the trending topic '{trend.topic}' in the "
            f"{_classify_topic_category(trend.topic)} category, "
            f"suggest one concise content angle (one sentence, max 20 words) "
            f"that is engaging for short-video audiences. "
            f"Return ONLY the angle text, nothing else."
        )
        try:
            response = self._llm_client.generate(prompt)
            if not response:
                return None
            cleaned = response.strip().strip('"').strip("'")
            if len(cleaned) > 200:
                cleaned = cleaned[:200]
            if cleaned:
                return cleaned
        except Exception as exc:
            logger.warning(
                f"LLM angle enhancement failed for '{trend.topic}': {exc}"
            )
        return None
