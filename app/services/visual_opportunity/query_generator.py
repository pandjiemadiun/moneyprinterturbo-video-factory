"""Visual query generation.

Transforms a candidate topic into a set of visual search queries
suitable for stock-footage providers.

The mechanism is primarily deterministic. An optional LLM can be used
for semantic expansion, but its output is validated and explicitly
marked as inferred.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.visual_opportunity.models import VisualConcept

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "this", "that",
    "these", "those", "it", "its", "your", "my", "our", "their", "his",
    "her", "yang", "dengan", "untuk", "dari", "pada", "di", "ke", "adalah",
    "atau", "juga", "tidak", "ada", "sudah", "bisa", "akan", "top", "best",
    "how", "why", "what", "when", "where", "which", "who", "about",
}

# Category → concrete visual nouns (deterministic expansion)
_CATEGORY_VISUAL_MAP: dict[str, list[str]] = {
    "technology": [
        "technology", "computer", "smartphone", "robot", "artificial intelligence",
        "digital", "coding", "laptop", "data", "innovation",
    ],
    "health": [
        "health", "fitness", "exercise", "yoga", "running", "medical",
        "wellness", "nutrition", "doctor", "hospital",
    ],
    "finance": [
        "finance", "money", "business", "stock market", "investment",
        "banking", "economy", "budget", "savings", "entrepreneur",
    ],
    "relationships": [
        "love", "couple", "family", "friendship", "wedding",
        "together", "heart", "romance", "people", "communication",
    ],
    "productivity": [
        "productivity", "workspace", "time management", "organization",
        "planning", "success", "goal", "motivation", "focus", "office",
    ],
    "education": [
        "education", "learning", "school", "student", "book",
        "study", "teacher", "classroom", "knowledge", "training",
    ],
    "entertainment": [
        "entertainment", "music", "concert", "movie", "game",
        "celebration", "festival", "dance", "performance", "fun",
    ],
    "sports": [
        "sports", "football", "basketball", "swimming", "cycling",
        "athlete", "competition", "running", "gym", "match",
    ],
    "science": [
        "science", "laboratory", "research", "chemistry", "physics",
        "space", "nature", "experiment", "biology", "technology",
    ],
    "general": [
        "nature", "landscape", "city", "ocean", "mountain",
        "forest", "sunset", "people", "business", "technology",
    ],
}


def _canonicalize(text: str) -> str:
    """Normalize text for deduplication."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_meaningful_terms(topic: str, max_terms: int = 5) -> list[str]:
    """Extract meaningful terms from a topic, dropping stopwords."""
    canonical = _canonicalize(topic)
    tokens = canonical.split()
    meaningful = [t for t in tokens if t not in _STOPWORDS and len(t) > 2]
    # Preserve original order, deduplicate
    seen: set[str] = set()
    result: list[str] = []
    for t in meaningful:
        if t not in seen:
            seen.add(t)
            result.append(t)
            if len(result) >= max_terms:
                break
    return result


def generate_visual_queries(
    topic: str,
    category: str = "general",
    max_queries: int = 10,
    llm_client: Any = None,
) -> list[VisualConcept]:
    """Generate visual search queries from a topic.

    Deterministic core + optional LLM expansion (marked as inferred).
    """
    concepts: list[VisualConcept] = []
    seen_terms: set[str] = set()

    def _add(term: str, source: str) -> None:
        canonical = _canonicalize(term)
        if not canonical or canonical in seen_terms or len(canonical) < 2:
            return
        seen_terms.add(canonical)
        concepts.append(
            VisualConcept(
                concept_id=f"vc_{len(concepts) + 1:03d}",
                term=term.strip().lower(),
                source=source,
                parent_topic=topic,
            )
        )

    # 1. Original topic (always retained)
    _add(topic, "topic")

    # 2. Meaningful sub-terms from the topic
    for term in _extract_meaningful_terms(topic, max_terms=4):
        _add(term, "topic")

    # 3. Category-based visual expansion
    cat_key = category.lower() if category.lower() in _CATEGORY_VISUAL_MAP else "general"
    for visual_noun in _CATEGORY_VISUAL_MAP.get(cat_key, []):
        if len(concepts) >= max_queries:
            break
        _add(visual_noun, "category")

    # 4. LLM semantic expansion (optional, marked as inferred)
    if llm_client is not None and len(concepts) < max_queries:
        try:
            llm_terms = _llm_expand_visual_terms(topic, category, llm_client)
            for term in llm_terms:
                if len(concepts) >= max_queries:
                    break
                _add(term, "inferred")
        except Exception:
            pass  # LLM expansion is best-effort

    return concepts[:max_queries]


def _llm_expand_visual_terms(
    topic: str, category: str, llm_client: Any, max_terms: int = 5
) -> list[str]:
    """Use LLM to expand a topic into visual terms.

    Output is validated: limited count, deduplicated, malformed rejected.
    """
    prompt = (
        f"Topic: {topic}\n"
        f"Category: {category}\n"
        f"Generate up to {max_terms} concrete visual search terms for stock footage. "
        f"Each term should be a simple noun or short phrase describing something "
        f"visually filmable (objects, places, activities, scenes). "
        f"Return one term per line, no numbers, no bullets."
    )
    response = llm_client.generate(prompt)
    if not response:
        return []

    terms: list[str] = []
    for line in response.split("\n"):
        term = line.strip().strip("-•*0123456789. ")
        canonical = _canonicalize(term)
        if not canonical or len(canonical) < 2 or len(canonical) > 40:
            continue
        if canonical not in {_canonicalize(t) for t in terms}:
            terms.append(term)
            if len(terms) >= max_terms:
                break
    return terms
