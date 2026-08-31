"""Viral Pattern Analysis — structured pattern detection.

Analyzes available content signals for patterns such as:
- hook structures
- topic patterns
- emotional framing
- curiosity gaps
- list structures
- problem/solution structures
- controversy/debate patterns
- storytelling patterns
- recurring themes
- title patterns
- audience intent

Patterns must retain evidence and/or confidence. The implementation
distinguishes OBSERVED DATA from MODEL INFERENCE.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Optional

from loguru import logger

from app.services.content_intelligence.models import (
    ContentOpportunity,
    NormalizedSignal,
    PatternEvidence,
    Trend,
    ViralPattern,
    ViralPatternType,
)


_HOOK_PATTERNS = [
    (r"^(why|how|what|when|where|who)\b", "question_hook"),
    (r"^\d+\s+(things?|ways?|reasons?|tips?|secrets?|facts?)", "list_hook"),
    (r"\b(you won't believe|you need to know|the truth about|stop everything)\b", "shock_hook"),
    (r"\b(this is why|here's why|the reason is)\b", "explanation_hook"),
    (r"\b(never|always|don't|stop|avoid)\b", "imperative_hook"),
]

_EMOTIONAL_WORDS = {
    "positive": [
        "amazing", "incredible", "beautiful", "love", "happy", "joy",
        "inspiring", "brilliant", "fantastic", "wonderful", "perfect",
        "best", "great", "awesome", "exciting", "surprising",
    ],
    "negative": [
        "terrible", "horrible", "hate", "angry", "sad", "fear",
        "worst", "disgusting", "shocking", "devastating", "alarming",
        "dangerous", "warning", "crisis", "disaster",
    ],
    "curiosity": [
        "secret", "hidden", "unknown", "mystery", "revealed",
        "surprising", "unexpected", "unbelievable", "mind-blowing",
        "little-known", "untold", "behind the scenes",
    ],
}


def _detect_hook_structure(topic: str) -> Optional[ViralPattern]:
    """Detect hook structures in a topic string."""
    topic_lower = topic.lower()
    for pattern, hook_name in _HOOK_PATTERNS:
        if re.search(pattern, topic_lower):
            return ViralPattern(
                pattern_type=ViralPatternType.HOOK_STRUCTURE,
                name=f"{hook_name}_detected",
                description=f"Topic starts with a {hook_name.replace('_', ' ')} pattern",
                evidence=[
                    PatternEvidence(
                        description=f"Matched pattern: {pattern}",
                        is_observed=True,
                        source="hook_detection",
                        confidence=0.8,
                    )
                ],
                confidence=0.7,
            )
    return None


def _detect_emotional_framing(topic: str) -> Optional[ViralPattern]:
    """Detect emotional framing in a topic."""
    topic_lower = topic.lower()
    detected: list[tuple[str, str]] = []
    for emotion, words in _EMOTIONAL_WORDS.items():
        for word in words:
            if word in topic_lower:
                detected.append((emotion, word))
    if not detected:
        return None
    evidence = [
        PatternEvidence(
            description=f"Detected {emotion} word: '{word}'",
            is_observed=True,
            source="emotional_framing_detection",
            confidence=0.75,
        )
        for emotion, word in detected
    ]
    emotions_found = sorted(set(e[0] for e in detected))
    return ViralPattern(
        pattern_type=ViralPatternType.EMOTIONAL_FRAMING,
        name=f"emotional_framing_{'_'.join(emotions_found)}",
        description=f"Topic uses emotional framing: {', '.join(emotions_found)}",
        evidence=evidence,
        confidence=min(0.9, 0.5 + 0.1 * len(evidence)),
    )


def _detect_curiosity_gap(topic: str) -> Optional[ViralPattern]:
    """Detect curiosity gap patterns in a topic."""
    topic_lower = topic.lower()
    curiosity_markers = [
        r"\?",
        r"\bwhy\b",
        r"\bhow (to|do|does|can|will)\b",
        r"\bwhat (happens|is|are|if|would)\b",
        r"\bthe (truth|secret|reason|real)\b",
        r"\byou (don't|didn't|won't|need to) know\b",
        r"\bthings? you (don't|didn't|should)\b",
    ]
    matches: list[str] = []
    for pattern in curiosity_markers:
        if re.search(pattern, topic_lower):
            matches.append(pattern)
    if not matches:
        return None
    evidence = [
        PatternEvidence(
            description=f"Matched curiosity marker: {m}",
            is_observed=True,
            source="curiosity_gap_detection",
            confidence=0.7,
        )
        for m in matches
    ]
    return ViralPattern(
        pattern_type=ViralPatternType.CURIOSITY_GAP,
        name="curiosity_gap_detected",
        description="Topic creates a curiosity gap that invites clicks",
        evidence=evidence,
        confidence=min(0.85, 0.5 + 0.1 * len(evidence)),
    )


def _detect_list_structure(topic: str) -> Optional[ViralPattern]:
    """Detect list/numbered structures in a topic."""
    topic_lower = topic.lower()
    list_match = re.search(
        r"^(\d+)\s+(things?|ways?|reasons?|tips?|secrets?|facts?|ideas?|steps?)",
        topic_lower,
    )
    if list_match:
        count = list_match.group(1)
        noun = list_match.group(2)
        return ViralPattern(
            pattern_type=ViralPatternType.LIST_STRUCTURE,
            name="list_structure_detected",
            description=f"Topic uses a {count}-item list structure",
            evidence=[
                PatternEvidence(
                    description=f"List pattern: {count} {noun}",
                    is_observed=True,
                    source="list_structure_detection",
                    confidence=0.85,
                )
            ],
            confidence=0.8,
        )
    return None


def _detect_problem_solution(topic: str) -> Optional[ViralPattern]:
    """Detect problem/solution framing in a topic."""
    topic_lower = topic.lower()
    problem_markers = [
        r"\b(fix|solve|solution|problem|issue|mistake|error|struggle)\b",
        r"\b(how to (fix|solve|overcome|deal with))\b",
        r"\b(stop (doing|making|feeling))\b",
    ]
    solution_markers = [
        r"\b(solution|answer|fix|remedy|cure|hack|trick)\b",
        r"\b(here's how|this is how|you can)\b",
    ]
    has_problem = any(re.search(p, topic_lower) for p in problem_markers)
    has_solution = any(re.search(p, topic_lower) for p in solution_markers)
    if has_problem or has_solution:
        evidence = []
        if has_problem:
            evidence.append(
                PatternEvidence(
                    description="Problem marker detected",
                    is_observed=True,
                    source="problem_solution_detection",
                    confidence=0.7,
                )
            )
        if has_solution:
            evidence.append(
                PatternEvidence(
                    description="Solution marker detected",
                    is_observed=True,
                    source="problem_solution_detection",
                    confidence=0.7,
                )
            )
        return ViralPattern(
            pattern_type=ViralPatternType.PROBLEM_SOLUTION,
            name="problem_solution_detected",
            description="Topic uses problem/solution framing",
            evidence=evidence,
            confidence=0.7,
        )
    return None


def _detect_controversy(topic: str) -> Optional[ViralPattern]:
    """Detect controversy/debate patterns in a topic."""
    topic_lower = topic.lower()
    controversy_markers = [
        r"\b(controversy|debate|argument|disagree|vs\.?|versus)\b",
        r"\b(wrong|myth|misconception|lie|truth)\b",
        r"\b(actually|in reality|the real truth)\b",
        r"\b(never|always)\b.+\b(but|however|yet)\b",
    ]
    matches: list[str] = []
    for pattern in controversy_markers:
        if re.search(pattern, topic_lower):
            matches.append(pattern)
    if not matches:
        return None
    evidence = [
        PatternEvidence(
            description=f"Matched controversy marker: {m}",
            is_observed=True,
            source="controversy_detection",
            confidence=0.65,
        )
        for m in matches
    ]
    return ViralPattern(
        pattern_type=ViralPatternType.CONTROVERSY_DEBATE,
        name="controversy_detected",
        description="Topic uses controversy or debate framing",
        evidence=evidence,
        confidence=min(0.8, 0.5 + 0.1 * len(evidence)),
    )


class ViralAnalyzer:
    """Analyze content signals for viral patterns.

    Uses deterministic pattern detection heuristics. Optionally uses an
    LLM for deeper semantic analysis when available. LLM-generated patterns
    are clearly marked as inference (not observed data).
    """

    def __init__(self, llm_client=None):
        """Initialize with an optional LLM client for semantic analysis."""
        self._llm_client = llm_client

    def analyze_trends(
        self, trends: list[Trend]
    ) -> list[ViralPattern]:
        """Analyze a list of trends for viral patterns.

        Returns a list of detected patterns with evidence.
        """
        if not trends:
            return []
        patterns: list[ViralPattern] = []
        for trend in trends:
            topic_patterns = self._analyze_topic(trend.topic)
            patterns.extend(topic_patterns)
        patterns.extend(self._detect_recurring_themes(trends))
        return patterns

    def analyze_opportunities(
        self, opportunities: list[ContentOpportunity]
    ) -> list[ViralPattern]:
        """Analyze content opportunities for viral patterns."""
        if not opportunities:
            return []
        patterns: list[ViralPattern] = []
        for opp in opportunities:
            topic_patterns = self._analyze_topic(opp.topic)
            patterns.extend(topic_patterns)
        return patterns

    def _analyze_topic(self, topic: str) -> list[ViralPattern]:
        """Run all deterministic pattern detectors on a single topic."""
        patterns: list[ViralPattern] = []
        detectors = [
            _detect_hook_structure,
            _detect_emotional_framing,
            _detect_curiosity_gap,
            _detect_list_structure,
            _detect_problem_solution,
            _detect_controversy,
        ]
        for detector in detectors:
            try:
                result = detector(topic)
                if result is not None:
                    patterns.append(result)
            except Exception as exc:
                logger.warning(
                    f"pattern detector {detector.__name__} failed: {exc}"
                )
        if self._llm_client is not None:
            llm_patterns = self._analyze_with_llm(topic)
            patterns.extend(llm_patterns)
        return patterns

    def _detect_recurring_themes(
        self, trends: list[Trend]
    ) -> list[ViralPattern]:
        """Detect recurring themes across multiple trends."""
        if len(trends) < 2:
            return []
        categories: list[str] = []
        for trend in trends:
            topic_lower = trend.topic.lower()
            for emotion, words in _EMOTIONAL_WORDS.items():
                for word in words:
                    if word in topic_lower:
                        categories.append(emotion)
            if re.search(r"^\d+\s+", topic_lower):
                categories.append("list_structure")
            if re.search(r"^(why|how|what)\b", topic_lower):
                categories.append("question_hook")
        if not categories:
            return []
        counter = Counter(categories)
        patterns: list[ViralPattern] = []
        for theme, count in counter.most_common():
            if count >= 2:
                evidence = [
                    PatternEvidence(
                        description=f"Theme '{theme}' appears in {count} trends",
                        is_observed=True,
                        source="recurring_theme_detection",
                        confidence=min(0.9, 0.5 + 0.1 * count),
                    )
                ]
                patterns.append(
                    ViralPattern(
                        pattern_type=ViralPatternType.RECURRING_THEME,
                        name=f"recurring_theme_{theme}",
                        description=f"Recurring theme detected: {theme}",
                        evidence=evidence,
                        confidence=min(0.85, 0.5 + 0.1 * count),
                    )
                )
        return patterns

    def _analyze_with_llm(self, topic: str) -> list[ViralPattern]:
        """Use LLM for deeper semantic pattern analysis.

        LLM-generated patterns are marked as inference (is_observed=False).
        Returns empty list if LLM is unavailable or returns invalid output.
        """
        if self._llm_client is None:
            return []
        prompt = (
            f"Analyze the following short-video topic for viral patterns.\n"
            f"Topic: {topic}\n\n"
            f"Return a JSON array of patterns. Each pattern object must have:\n"
            f'- "type": one of: hook_structure, topic_pattern, emotional_framing, '
            f'curiosity_gap, list_structure, problem_solution, controversy_debate, '
            f'storytelling, recurring_theme, title_pattern, audience_intent\n'
            f'- "name": short identifier\n'
            f'- "description": one sentence\n'
            f'- "confidence": number between 0 and 1\n\n'
            f"Return ONLY the JSON array, no other text."
        )
        try:
            response = self._llm_client.generate(prompt)
            if not response:
                return []
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            data = json.loads(cleaned)
            if not isinstance(data, list):
                logger.warning("LLM pattern response is not a JSON array")
                return []
            patterns: list[ViralPattern] = []
            valid_types = {t.value for t in ViralPatternType}
            for item in data:
                if not isinstance(item, dict):
                    continue
                ptype = item.get("type", "")
                if ptype not in valid_types:
                    continue
                try:
                    pattern = ViralPattern(
                        pattern_type=ViralPatternType(ptype),
                        name=str(item.get("name", "llm_pattern")),
                        description=str(item.get("description", "")),
                        evidence=[
                            PatternEvidence(
                                description=str(
                                    item.get("description", "")
                                ),
                                is_observed=False,
                                source="llm_inference",
                                confidence=float(
                                    item.get("confidence", 0.5)
                                ),
                            )
                        ],
                        confidence=float(item.get("confidence", 0.5)),
                    )
                    patterns.append(pattern)
                except (ValueError, TypeError) as exc:
                    logger.debug(f"skipping invalid LLM pattern: {exc}")
            return patterns
        except json.JSONDecodeError as exc:
            logger.warning(f"LLM pattern response is not valid JSON: {exc}")
        except Exception as exc:
            logger.warning(f"LLM pattern analysis failed: {exc}")
        return []
