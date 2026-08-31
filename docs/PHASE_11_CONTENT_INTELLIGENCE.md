# PHASE 11 — CONTENT INTELLIGENCE

**Status:** PASS
**Date:** 2026-08-31
**Commit:** (see git log)

---

## 1. ARCHITECTURE

Phase 11 implements the complete Content Intelligence module that transforms
current/relevant content signals into actionable content opportunities and
structured content hypotheses.

### Module Structure

```
app/services/content_intelligence/
    __init__.py              - Public API exports
    models.py                - Data models (RawSignal, Trend, Opportunity, etc.)
    trend_radar.py           - Trend Radar: collect, normalize, deduplicate
    opportunity_miner.py     - Opportunity Mining: trends -> opportunities
    viral_analyzer.py       - Viral Pattern Analysis
    scorer.py                - Deterministic Opportunity Scoring
    hypothesis.py            - Trend -> Content Hypothesis generation
    pipeline.py              - End-to-end pipeline orchestration
```

### Data Flow

```
Raw Signals -> Normalization -> Trend Detection -> Opportunity Mining
    -> Viral Pattern Analysis -> Opportunity Scoring -> Content Hypothesis
    -> Structured Output -> Ready for Content Factory
```

---

## 2. CAPABILITIES

### 2.1 Trend Radar (`trend_radar.py`)

- Collects trend/content signals from available sources via provider callables
- Normalizes source data into canonical form (`_canonicalize`)
- Deduplicates equivalent signals by canonical key
- Identifies emerging/relevant topics
- Retains source attribution (sources, providers)
- Retains timestamps (first_observed, latest_observed)
- Supports freshness scoring (exponential decay, 24h half-life)
- Produces structured `Trend` objects with strength, confidence, freshness

**Key design decisions:**
- Provider isolation: external providers are injected via `add_provider()`
- Failed providers return empty list (no fabricated data)
- Deterministic strength formula: 0.30*volume + 0.30*confidence + 0.25*freshness + 0.15*diversity

### 2.2 Opportunity Mining (`opportunity_miner.py`)

- Transforms trend signals into content opportunities
- Each opportunity answers: topic, rationale, audience, angle, timeliness, evidence
- Uses deterministic heuristics for category classification and angle generation
- Optional LLM enhancement for angle refinement
- Avoids simply copying trend titles
- Weak trends (strength < 0.05 with < 2 signals) are rejected

### 2.3 Viral Pattern Analysis (`viral_analyzer.py`)

- Detects patterns: hook structures, emotional framing, curiosity gaps,
  list structures, problem/solution, controversy/debate, recurring themes
- All patterns retain evidence with `is_observed` flag
- Distinguishes OBSERVED DATA (is_observed=True) from MODEL INFERENCE (is_observed=False)
- Optional LLM for deeper semantic analysis (marked as inference)
- Handles malformed LLM responses gracefully

### 2.4 Opportunity Scoring (`scorer.py`)

- Deterministic, inspectable scoring with 8 dimensions:
  - trend_strength, freshness, audience_relevance, content_demand,
    competition, production_feasibility, viral_potential, monetization
- Each dimension has a clear formula and explanation
- Total score is a weighted sum (weights normalized to sum to 1.0)
- Scores are NOT LLM-generated numbers
- Full explainability: every dimension has an explanation string

### 2.5 Trend -> Content Hypothesis (`hypothesis.py`)

- Converts high-quality opportunities into structured `ContentHypothesis` objects
- Contains: topic, audience, angle, hook, promise, format, evidence,
  score, confidence, keywords, rationale
- `to_script_prompt()` method for downstream compatibility
- Optional LLM enhancement for creative fields (hook, promise)
- Falls back to deterministic heuristics if LLM unavailable

---

## 3. INTEGRATION

### API Endpoints

- `POST /api/v1/content-intelligence/analyze` - Run full pipeline
- `POST /api/v1/content-intelligence/hypotheses` - Generate hypotheses only

### Integration with Existing Pipeline

The `ContentHypothesis.to_script_prompt()` method produces a prompt string
compatible with the existing `llm.build_script_prompt()` workflow. The
hypothesis `topic` maps to `VideoParams.video_subject`, and the script prompt
maps to `VideoParams.video_script_prompt`.

### Request/Response Models

- `ContentIntelligenceRequest`: topics (list of strings), min_score (0-1)
- `ContentIntelligenceResponse`: trends, opportunities, patterns, hypotheses, success, errors

---

## 4. TESTS

**Test file:** `test/services/test_content_intelligence.py`
**Test count:** 68 tests, all passing

### Coverage

- **A. Trend Radar:** valid provider, empty response, provider failure,
  duplicate trends, stale signals, timestamp handling, source attribution
- **B. Opportunity Mining:** valid trend, multiple trends, weak trend rejection,
  duplicate opportunities, evidence preservation
- **C. Viral Pattern Analysis:** valid analysis, empty input, malformed LLM response,
  observed vs inference distinction
- **D. Opportunity Scoring:** deterministic score, boundary values, missing dimensions,
  invalid dimensions, ranking, explainability
- **E. Hypothesis Generation:** valid opportunity, invalid LLM response, missing fields,
  provider failure, evidence preservation, schema validation
- **F. Integration:** complete flow, downstream compatibility, failure propagation
- **G. Regression:** fstring syntax, empty topic filtering, invalid confidence rejection

---

## 5. PRODUCTION SAFETY

| Item | Status |
|------|--------|
| Production data | UNCHANGED |
| Config | UNCHANGED |
| Database/state | UNCHANGED |
| Secrets | UNCHANGED |
| Unrelated behavior | UNCHANGED |

No production data, configuration, or unrelated modules were modified.

---

## 6. KNOWN LIMITATIONS

1. **Trend sources:** Without configured external providers (Google Trends, Twitter, etc.),
   the Trend Radar operates on manually provided signals. Provider callables can be
   registered via `add_provider()` when external APIs are available.

2. **LLM dependency:** The OpportunityMiner, ViralAnalyzer, and HypothesisGenerator
   operate on deterministic heuristics when no LLM client is provided. LLM enhancement
   is optional and gracefully degrades.

3. **Competition scoring:** Competition/saturation is estimated heuristically based on
   topic generality, not direct competition data from platforms.

4. **No persistent storage:** Trends and hypotheses are computed on-demand and not
   persisted. A future phase could add caching/persistence.

---

## 7. CODING CONVENTIONS FOLLOWED

- Reused existing LLM provider abstraction pattern
- Followed existing error handling (graceful degradation, no silent failures)
- Used dataclasses and Pydantic models for structured data
- Followed existing logging patterns (loguru)
- Matched existing test structure (unittest.TestCase with descriptive names)
- No comments added unless explaining non-obvious logic
- Provider isolation for replaceability
