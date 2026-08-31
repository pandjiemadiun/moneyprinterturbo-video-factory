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
    provider_base.py         - Provider abstraction interface
    providers/
        __init__.py          - Provider registry
        google_news.py       - Google News RSS provider
        hackernews.py        - Hacker News API provider
    trend_radar.py           - Trend Radar: collect, normalize, deduplicate
    opportunity_miner.py     - Opportunity Mining: trends -> opportunities
    viral_analyzer.py       - Viral Pattern Analysis
    scorer.py                - Deterministic Opportunity Scoring
    hypothesis.py            - Trend -> Content Hypothesis generation
    pipeline.py              - End-to-end pipeline orchestration
```

### Data Flow

```
Real Providers (Google News RSS, Hacker News)
    ↓
RawSignal (with provenance, timestamps, confidence)
    ↓
TrendRadar (normalize, deduplicate, detect trends)
    ↓
OpportunityMiner (mine content opportunities)
    ↓
ViralAnalyzer (detect viral patterns)
    ↓
OpportunityScorer (deterministic scoring)
    ↓
HypothesisGenerator (generate content hypotheses)
    ↓
API Response + Frontend Dashboard
```

---

## 2. PROVIDERS

### 2.1 Google News RSS (`google_news.py`)

- **Source:** Google News RSS feeds (https://news.google.com/rss)
- **Type:** RSS feed (no API key required)
- **Coverage:** Indonesian (ID) and international news
- **Categories:** general, technology, business, sports, entertainment, health, science
- **Freshness:** Real pubDate timestamps from RSS
- **Provenance:** Source name, URL, publication date preserved
- **Status:** LIVE (tested 2026-08-31)

### 2.2 Hacker News (`hackernews.py`)

- **Source:** Hacker News API (https://github.com/HackerNews/API)
- **Type:** REST API (no API key required)
- **Coverage:** Global technology news
- **Stories:** Top, new, best
- **Freshness:** Real timestamps from API
- **Provenance:** Score, comment count, author, URL preserved
- **Status:** LIVE (tested 2026-08-31)

### 2.3 Provider Registry

- Manages multiple providers
- Handles failure isolation (one provider failing doesn't break others)
- Health monitoring with success rate tracking
- Partial-success behavior

---

## 3. PROVIDER CANDIDATES INVESTIGATED

| Source | Status | Reason |
|--------|--------|--------|
| Google News RSS | **ENABLED** | Works, free, real data, Indonesian support |
| Hacker News API | **ENABLED** | Works, free, real data, tech focus |
| Google Trends RSS | Rejected | Returns 404 |
| Reddit | Rejected | Returns 403 (blocked) |
| Wikipedia Views | Rejected | Returns 403 |
| GitHub Trending | Rejected | API unavailable |
| Ars Technica RSS | Available | Works, but similar to HN |
| TechCrunch RSS | Available | Works, but similar to HN |
| Detik.com RSS | Available | Works, but similar to Google News |
| CNBC Indonesia RSS | Available | Works, but similar to Google News |
| BBC News RSS | Available | Works, but similar to Google News |

---

## 4. CAPABILITIES

### 4.1 Trend Radar (`trend_radar.py`)

- Collects trend/content signals from registered providers
- Normalizes source data into canonical form
- Deduplicates equivalent signals by canonical key
- Identifies emerging/relevant topics
- Retains source attribution (sources, providers)
- Retains timestamps (first_observed, latest_observed)
- Supports freshness scoring (exponential decay, 24h half-life)
- Produces structured `Trend` objects with strength, confidence, freshness

### 4.2 Opportunity Mining (`opportunity_miner.py`)

- Transforms trend signals into content opportunities
- Each opportunity answers: topic, rationale, audience, angle, timeliness, evidence
- Uses deterministic heuristics for category classification and angle generation
- Optional LLM enhancement for angle refinement
- Avoids simply copying trend titles

### 4.3 Viral Pattern Analysis (`viral_analyzer.py`)

- Detects patterns: hook structures, emotional framing, curiosity gaps,
  list structures, problem/solution, controversy/debate, recurring themes
- All patterns retain evidence with `is_observed` flag
- Distinguishes OBSERVED DATA (is_observed=True) from MODEL INFERENCE (is_observed=False)
- Optional LLM for deeper semantic analysis (marked as inference)
- Handles malformed LLM responses gracefully

### 4.4 Opportunity Scoring (`scorer.py`)

- Deterministic, inspectable scoring with 8 dimensions
- Each dimension has a clear formula and explanation
- Total score is a weighted sum (weights normalized to sum to 1.0)
- Scores are NOT LLM-generated numbers
- Full explainability: every dimension has an explanation string

### 4.5 Trend -> Content Hypothesis (`hypothesis.py`)

- Converts high-quality opportunities into structured `ContentHypothesis` objects
- Contains: topic, audience, angle, hook, promise, format, evidence,
  score, confidence, keywords, rationale
- `to_script_prompt()` method for downstream compatibility
- Optional LLM enhancement for creative fields (hook, promise)
- Falls back to deterministic heuristics if LLM unavailable

---

## 5. INTEGRATION

### API Endpoints

- `POST /api/v1/content-intelligence/analyze` - Run full pipeline with providers
- `POST /api/v1/content-intelligence/hypotheses` - Generate hypotheses only

### Request Fields

- `topics`: List of user-provided topics (when not using providers)
- `use_providers`: Boolean to fetch from external providers
- `geo`: Geographic region (default: "ID")
- `language`: Language code (default: "id")
- `category`: Content category (default: "general")
- `max_signals_per_provider`: Max signals per provider (default: 20)

### Response Fields

- `trends`: List of trend objects with source classification
- `opportunities`: List of opportunity objects with scores
- `patterns`: List of viral pattern objects
- `hypotheses`: List of content hypothesis objects
- `provider_health`: Health status of each provider
- `data_source_summary`: Summary of data sources used
- `total_raw_signals`: Total signals collected
- `fetched_at`: ISO timestamp of when data was fetched

### Frontend

- Navigation: "Intelligence" tab in the top bar
- Provider status display (LIVE/RECENT/STALE/OFFLINE)
- Trend dashboard with source classification
- Opportunity view with scores and explanations
- Hypothesis view with hooks, promises, formats
- Controls: refresh, provider selection, geography, language, category

---

## 6. FRESHNESS MODEL

Freshness is classified based on the time difference between when the data was observed (published) and when it was fetched:

| Classification | Threshold | Meaning |
|---------------|-----------|---------|
| LIVE | < 5 minutes | Just published |
| RECENT | < 1 hour | Published within the last hour |
| STALE | < 24 hours | Published within the last day |
| UNKNOWN | N/A | No timestamp available |

Freshness is calculated from real timestamps provided by the source (pubDate for RSS, time for Hacker News), not from `datetime.now()`.

---

## 7. PROVENANCE MODEL

Every external signal preserves:

- `provider`: Provider ID (e.g., "google_news_rss")
- `provider_name`: Human-readable name
- `source`: Source type (rss, social)
- `observed_at`: When the content was published/observed
- `fetched_at`: When the data was fetched by our system
- `source_url`: URL to the original content
- `source_name`: Name of the original source
- `geo`: Geographic context
- `language`: Language context

The system distinguishes:
- **OBSERVED**: Data directly from external sources (real timestamps, real content)
- **DERIVED**: Computed from observed data (trend strength, freshness scores)
- **INFERRED**: Generated by heuristics or LLMs (angles, patterns, hypotheses)

---

## 8. FAILURE BEHAVIOR

### Single Provider Failure
- Other providers continue to work
- Failed provider's health status updated to OFFLINE
- Pipeline succeeds with partial data

### All Providers Fail
- Pipeline returns explicit error: "no_provider_signals"
- No fabricated data is generated
- Frontend shows appropriate error message

### Timeout Handling
- Per-provider timeout (default: 15 seconds)
- Timeout logged and recorded in health status
- Pipeline continues with remaining providers

---

## 9. TESTS

**Test files:**
- `test/services/test_content_intelligence.py` (77 tests)
- `test/services/test_providers.py` (40 tests)

**Coverage:**
- Provider unit tests (parsing, health, failure modes)
- Aggregation tests (duplicate signals, multi-provider)
- Freshness tests (LIVE/RECENT/STALE classification)
- Failure isolation tests
- API integration tests
- Frontend rendering tests

---

## 10. PRODUCTION SAFETY

| Item | Status |
|------|--------|
| Production data | UNCHANGED |
| Config | UNCHANGED |
| Database/state | UNCHANGED |
| Secrets | UNCHANGED (no API keys needed) |
| Unrelated behavior | UNCHANGED |

---

## 11. KNOWN LIMITATIONS

1. **Rate limits:** Google News RSS and Hacker News have no official rate limits, but excessive requests may be throttled
2. **Geographic coverage:** Google News RSS supports ID; Hacker News is global
3. **Language:** Google News RSS supports Indonesian; Hacker News is English-only
4. **No persistence:** Results are computed on-demand with no caching layer
5. **LLM is optional:** Enhanced features require LLM configuration
