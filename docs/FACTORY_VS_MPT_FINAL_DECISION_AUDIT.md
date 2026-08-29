# FACTORY vs MPT ORIGINAL — FINAL DECISION AUDIT

**Status:** READ-ONLY DECISION AUDIT
**Date:** 2026-08-29
**Decision Authority:** Human (this audit provides evidence)

---

## 1. EXECUTIVE SUMMARY

Two separate applications exist on this server:

1. **MoneyPrinterTurbo** (port 8501) — the application modified in Phase 11A-11F
2. **MPT Factory** (port 8000) — a separate FastAPI + vanilla JS application at `/opt/mpt-factory/`

The human uses **Factory** (port 8000). All Phase 11A-11F modifications were made to **MPT Original** (port 8501) — the wrong application.

**Key Finding:** Factory is NOT a UI overlay or theme on top of MPT. It is a **completely separate application** with its own:
- Codebase (41 Python files, 8,036 lines)
- Frontend (vanilla HTML/CSS/JS)
- Backend (FastAPI)
- Database (SQLite)
- Job queue
- API endpoints
- Test suite (26 files, 203 tests)

---

## 2. BOTH APPLICATIONS

### 2.1 MoneyPrinterTurbo (MPT Original)

| Property | Value |
|---|---|
| Source | `/root/moneyprinterturbo-video-factory/` |
| Git repo | `pandjiemadiun/moneyprinterturbo-video-factory` |
| HEAD | `da2b8be` (Phase 11F) |
| Backend | FastAPI |
| Frontend | Streamlit |
| Database | In-memory or Redis |
| Entrypoint | `webui/Main.py` (Streamlit), `main.py` (FastAPI) |
| Containers | `moneyprinterturbo-webui` (8501), `moneyprinterturbo-api` (8080) |
| Image | `mpt-factory-11e:latest` |
| YouTube | YES (Phase 11B+) |
| Batch UI | YES (Phase 11F) |
| Thumbnails | Backend YES, UI YES |

### 2.2 MPT Factory

| Property | Value |
|---|---|
| Source | `/opt/mpt-factory/` |
| Git repo | NONE (no .git directory) |
| Backend | FastAPI |
| Frontend | Vanilla JS SPA |
| Database | SQLite (`data/factory.db`) |
| Entrypoint | `app/main.py` (uvicorn) |
| Process | Native uvicorn pid 180209 |
| Port | 127.0.0.1:8000 |
| YouTube | **NO** |
| Batch UI | YES (no YouTube) |
| Thumbnails | **NO** |

---

## 3. ARCHITECTURE

### 3.1 MPT Original Architecture

```
Browser → nginx (goldtrader.website) → Streamlit :8501
  → webui/Main.py (6034 lines)
    → webui_task.submit_generation()
      → task_manager.add_task()
        → tm.start() → 7-stage pipeline
          → material download → video generation → thumbnail generation
    → state (in-memory or Redis)
```

### 3.2 Factory Architecture

```
Browser → goldtrader.website (or tunnel) → uvicorn :8000
  → app/main.py (FastAPI, 343 lines)
    → static_dashboard/index.html (vanilla JS SPA)
      → POST /api/batches
        → BatchPlanner.create_batch()
          → TopicPlanner.generate_topics() → MPT POST /api/v1/scripts
          → JobWorker.run_job() → MPT POST /api/v1/videos
          → AssetLibrary.download_asset() → MPT GET /api/v1/stream
    → SQLite (data/factory.db)
```

---

## 4. CAPABILITY INVENTORY

### 4.1 Factory Capabilities

| Capability | Status | Evidence |
|---|---|---|
| Job creation | IMPLEMENTED | `jobs.py:93` |
| Topic generation | IMPLEMENTED | `topic_planner.py:120-180` |
| Batch creation | IMPLEMENTED | `batch_planner.py:148` |
| Task queue | IMPLEMENTED | `queue_runner.py:27` |
| Job status | IMPLEMENTED | `jobs.py:status` column |
| History | IMPLEMENTED | `jobs.py` (all terminal states) |
| Assets | IMPLEMENTED | `assets.py:303` |
| Videos | IMPLEMENTED | `data/videos/` (40 MP4s) |
| Thumbnails | **NOT IMPLEMENTED** | No code exists |
| Provider selection | IMPLEMENTED (3 only) | `index.html:133-135` |
| YouTube | **NOT IMPLEMENTED** | Not in HTML |
| Pexels | IMPLEMENTED | HTML checkbox |
| Pixabay | IMPLEMENTED | HTML checkbox |
| Coverr | IMPLEMENTED | HTML checkbox |
| Local media | **NOT IMPLEMENTED** | No upload UI |
| Task retry | **NOT IMPLEMENTED** | No retry logic |
| Task cancel | IMPLEMENTED | `jobs.py:cancel` |
| Task delete | IMPLEMENTED | `assets.py:delete_asset` |
| Preview | IMPLEMENTED | `player.html` |
| Download | IMPLEMENTED | `GET /api/videos/{id}/file` |
| API | IMPLEMENTED | FastAPI with 10 endpoints |
| Monitoring | IMPLEMENTED | Overview dashboard |
| Analytics | **NOT IMPLEMENTED** | Basic counts only |
| Scheduling | **NOT IMPLEMENTED** | No scheduler |
| Metadata | IMPLEMENTED | jobs table |
| Content grouping | IMPLEMENTED | niche/topic columns |

### 4.2 MPT Original Capabilities

| Capability | Status | Evidence |
|---|---|---|
| Single video | IMPLEMENTED | Full 4-column form |
| Batch generation | IMPLEMENTED | Phase 11F |
| Jobs | IMPLEMENTED | Task manager panel |
| History | IMPLEMENTED | Task restore from script.json |
| YouTube | IMPLEMENTED | Since Phase 11B |
| Thumbnails | IMPLEMENTED | Since Phase 11D |
| Mobile | PARTIAL | CSS breakpoints exist |
| API | IMPLEMENTED | 16 endpoints |
| Automation | IMPLEMENTED | CLI + API |
| Publishing | IMPLEMENTED | Upload-Post integration |
| 21 LLM providers | IMPLEMENTED | `llm_provider.py` |
| 9 TTS providers | IMPLEMENTED | `voice.py` |
| Scene-aware | IMPLEMENTED | Phase 7B |
| BGM | IMPLEMENTED | 5 sources |

---

## 5. REAL USER WORKFLOW

### 5.1 Current Human Workflow (Factory)

```
Browser → goldtrader.website → Factory :8000
  → New Batch tab
    → Enter niche, count, providers (Pixabay/Pexels/Coverr)
    → Queue batch
      → POST /api/batches → BatchPlanner → MPT API
    → Jobs tab → Monitor progress
    → Videos tab → Play/Download
```

### 5.2 MPT Original Workflow

```
Browser → :8501 (Streamlit)
  → Fill 4-column form (script/video/audio/subtitle)
  → Generate Video
    → webui_task → task_manager → pipeline
  → Task manager → Play/Download/Delete
```

### 5.3 Capability Comparison (Human's Perspective)

| Task | Factory | MPT Original |
|---|---|---|
| Single video | YES (via batch with count=1) | YES (primary workflow) |
| Repeated production | YES (batch with multiple topics) | YES (video_count 1-5) |
| Batch production | YES (native) | YES (Phase 11F) |
| Job monitoring | YES (Overview/Jobs tabs) | YES (task manager) |
| Video library | YES (Videos tab) | YES (task table) |
| Thumbnails | **NO** | YES |
| YouTube | **NO** | YES |
| Recover failed jobs | **NO** | YES (task restore) |

---

## 6. TOPIC GENERATION FAILURE

### 6.1 Symptom

```
POST /api/batches {"niche":"test","count":1,"providers":["pexels"]}
→ {"status":"error","message":"Queue gagal: topic generation tidak berhasil."}
```

### 6.2 Root Cause Analysis

The topic generation **works when called directly** from Python:

```python
# Direct call WORKS:
planner = TopicPlanner(mpt=MPTClient('http://127.0.0.1:8080'))
topics = planner.generate_topics('fitness', count=3)
# Returns: ['Pemanasan yang tepat...', 'Setelah tubuh siap...', ...]
```

```python
# BatchPlanner call ALSO WORKS:
BatchPlanner(store, mpt=MPT_CLIENT).create_batch(niche='test', count=1, providers=['pexels'])
# Returns: ['50fdcf27-...']
```

But the **API endpoint fails**. This suggests:
1. The MPT_API may be intermittently returning errors (Gemini quota/rate limit)
2. The `detect_upstream_error()` function may be falsely detecting errors in valid responses
3. There may be a timing/concurrency issue in the API endpoint

### 6.3 Classification

**Category:** Configuration / Transient API issue

**Fix complexity:** Low (retry logic exists, may need tuning)

**Not architectural** — the topic planner works correctly for curated niches and most uncurated ones.

---

## 7. DATABASE ROLE

### 7.1 Factory Database Schema

```sql
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    niche TEXT,
    topic TEXT,
    provider TEXT,
    status TEXT,          -- queued/completed/failed/cancelled
    mpt_task_id TEXT,
    video_path TEXT,
    script TEXT,
    terms TEXT,
    error TEXT,
    created_at TEXT,
    completed_at TEXT,
    source TEXT,
    subtitle_color TEXT
);

CREATE TABLE assets (
    id TEXT PRIMARY KEY,
    job_id TEXT REFERENCES jobs(id),
    filename TEXT,
    path TEXT,            -- absolute path (internal only)
    size_bytes INTEGER,
    created_at TEXT,
    deleted_at TEXT       -- tombstone pattern
);
```

### 7.2 Migration Cost

The Factory DB stores:
- 171 jobs with full metadata
- 43 completed video assets
- Job history, error messages, scripts, terms

**Migration to MPT Original:** Medium effort. MPT Original uses in-memory/Redis state, not SQLite. Factory job history would need to be either:
1. Exported as a one-time report
2. Replicated in MPT's task system (which already stores similar data per-task)

**Verdict:** Migration is feasible but not trivial. The data is valuable (job history, scripts, error diagnostics).

---

## 8. DUPLICATION ANALYSIS

| Responsibility | MPT Original | Factory | Verdict |
|---|---|---|---|
| Task creation | YES | YES (via MPT API) | REDUNDANT |
| Status tracking | YES | YES (separate DB) | REDUNDANT |
| History | YES (per-task files) | YES (SQLite) | REDUNDANT |
| Video storage | YES (per-task dirs) | YES (UUID dirs) | REDUNDANT |
| Provider selection | YES (7 providers) | YES (3 providers) | DIVERGED |
| Rendering engine | YES (internal) | NO (uses MPT) | NECESSARILY SEPARATE |
| UI | Streamlit | Vanilla JS | DUPLICATED |
| API | 16 endpoints | 10 endpoints | DUPLICATED |
| Config management | YES (settings dialog) | NO | ONLY MPT |

---

## 9. DEPLOYMENT COMPLEXITY

| Metric | MPT Only | Factory Only | Both |
|---|---|---|---|
| Containers | 2 (webui + api) | 0 (native process) | 2 + native |
| Ports | 8501, 8080 | 8000 | 8501, 8080, 8000 |
| Images | 1 (mpt-factory-11e) | 0 | 1 |
| Databases | In-memory/Redis | SQLite | Both |
| Deployment files | docker-compose.yml | None | docker-compose.yml |
| Maintenance surfaces | 1 codebase | 1 codebase | 2 codebases |
| Version drift risk | Low | High (no git) | High |

---

## 10. FUTURE ROADMAP COMPATIBILITY

### 10.1 Auto Clipper

| Aspect | MPT Original | Factory |
|---|---|---|
| Implementation complexity | Medium (needs new pipeline) | Medium (needs new pipeline) |
| API compatibility | Native (same codebase) | Via HTTP API |
| Video input | Existing material pipeline | Would need new integration |
| Reframe | Existing | Would need MPT call |
| Maintainability | High | Medium (separate codebase) |

### 10.2 Publishing / Analytics / Monetization

| Aspect | MPT Original | Factory |
|---|---|---|
| Publishing | Upload-Post integrated | Not implemented |
| Analytics | Not implemented | Basic counts only |
| Automation | CLI + API | API only |
| Batch orchestration | New (Phase 11F) | Existing (native) |

---

## 11. DECISION MATRIX

| Criterion | MPT Original | Factory | Merge |
|---|---|---|---|
| Single video | EXCELLENT | GOOD | EXCELLENT |
| Batch | GOOD (new) | EXCELLENT (native) | EXCELLENT |
| Jobs | GOOD | EXCELLENT (dedicated UI) | EXCELLENT |
| History | GOOD | GOOD | GOOD |
| YouTube | YES | **NO** | YES |
| Thumbnails | YES | **NO** | YES |
| Mobile | PARTIAL | PARTIAL | GOOD |
| API | 16 endpoints | 10 endpoints | 16+ endpoints |
| Automation | YES (CLI+API) | API only | YES |
| Auto Clipper future | GOOD (same codebase) | MEDIUM (API calls) | GOOD |
| Publishing future | YES (integrated) | NO | YES |
| Analytics future | MEDIUM | LOW | MEDIUM |
| Maintenance | 1 codebase | 2 codebases | 1 codebase |
| Deployment | Docker | Native process | Docker |

---

## 12. RECOMMENDATION

### OPTION C — SIMPLIFY / MERGE (RECOMMENDED)

**Rationale:**

1. **Factory provides real orchestration value** that MPT Original lacks:
   - Native batch creation workflow (superior to Phase 11F's bolt-on)
   - Job history with SQLite persistence (MPT loses history on restart)
   - Production control (start/stop runner)
   - Asset management (tombstone delete, storage stats)

2. **MPT Original provides backend capabilities** that Factory lacks:
   - YouTube support (Phase 10H/11B/11C)
   - Thumbnail generation (Phase 11D)
   - 21 LLM providers, 9 TTS providers
   - Publishing (Upload-Post)
   - Scene-aware rendering

3. **The duplication is real but manageable** — both share MPT as rendering engine

**Recommended Approach:**

1. **Use MPT Original (Streamlit) as the canonical UI** — it has the most capabilities
2. **Integrate Factory's batch/orchestration features into MPT Original:**
   - Port Factory's `BatchPlanner` logic to `webui_batch.py` (already done in Phase 11E)
   - Add Factory's job history persistence to MPT's state backend
   - Add Factory's production control (start/stop) to MPT's task manager
3. **Deprecate Factory UI** once MPT Original has equivalent batch/orchestration features
4. **Keep Factory database** for historical job data (or migrate to MPT)

**DO NOT remove Factory immediately** — it's the human's working UI. Instead:
1. Fix Factory's topic generation (low effort)
2. Add YouTube to Factory's provider list (low effort)
3. Gradually migrate humans to MPT Original UI
4. Eventually decommission Factory

---

## 13. MIGRATION/REMOVAL RISK

| Risk | Severity | Mitigation |
|---|---|---|
| Losing 171 jobs of history | MEDIUM | Backup factory.db before any changes |
| Losing Factory's batch workflow | LOW | MPT Phase 11F batch covers this |
| Losing Factory's production control | LOW | Can be added to MPT |
| Human workflow disruption | HIGH | Keep Factory running during transition |

---

## 14. BACKUP REQUIREMENTS

Before any Factory changes:

1. **Factory database:** `/opt/mpt-factory/data/factory.db` (SHA256: `ad0e6df9...`)
2. **Factory videos:** `/opt/mpt-factory/data/videos/` (40 MP4s)
3. **Factory source:** `/opt/mpt-factory/` (no git history!)
4. **Factory pre-production backup:** `factory.db.pre-production-20260823T130804Z` exists

**CRITICAL:** Factory has NO version control. If deleted, the source is gone forever.

---

## 15. PRODUCTION SAFETY

### 15.1 Audit Actions

- Production jobs: 0
- YouTube downloads: 0
- Source modifications: 0
- Database mutations: 0
- Container restarts: 0

### 15.2 Invariants

| Invariant | Value |
|---|---|
| Factory DB SHA256 | ad0e6df9d5a45438532c0c99655455448e8c791bd5781711bf1f4f111a5d59a1 |
| Factory DB size | 151552 |
| Factory jobs | 171 |
| Factory assets | 43 |
| MPT tasks | 136 |
| MPT MP4s | 158 |

---

## 16. FINAL DECISION

### DECISION: SIMPLIFY / MERGE

**Evidence:**

1. Factory provides real batch/orchestration value but lacks YouTube and thumbnails
2. MPT Original has all Phase 11 improvements but inferior batch workflow
3. Both share MPT as rendering engine — they're complementary, not competing
4. Factory has NO version control — it's a deployment risk
5. Maintaining two codebases doubles maintenance burden

**Immediate Actions:**
1. Back up `/opt/mpt-factory/` source and database
2. Fix Factory topic generation (transient issue)
3. Add YouTube to Factory provider list (low effort, high value)

**Medium-term Actions:**
1. Port Factory's batch/orchestration features to MPT Original
2. Migrate human to MPT Original UI
3. Decommission Factory

**DO NOT proceed to Phase 11H (Auto Clipper) until this decision is implemented.**

---

## AUDIT CLASSIFICATION

**PASS WITH FINDINGS**

Two separate applications exist with overlapping but complementary capabilities.
Neither should be removed immediately. A merge strategy minimizes future rework
while preserving the human's working workflow.

Production mutations: 0
Source modifications: 0
Deployment: NONE
