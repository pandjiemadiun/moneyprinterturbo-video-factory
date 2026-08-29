# PHASE 11H.1 — FACTORY CAPABILITY MIGRATION ANALYSIS

**Date:** 2026-08-29
**Purpose:** Identify which Factory capabilities to retain, adapt, or discard

---

## Factory Capability Inventory

| # | Capability | Factory Source | MPT Equivalent | Action | Rationale |
|---|---|---|---|---|---|
| 1 | Batch orchestration | `batch_planner.py` | `webui_batch.py` (Phase 11E) | **REUSE CONCEPT** | MPT batch exists; enhance UI |
| 2 | Job creation | `jobs.py` | Task state in `state.py` | **ADAPT** | MPT needs persistent job history |
| 3 | Job status tracking | `jobs.py` status column | Task state (-1/1/4) | **ADAPT** | Map MPT states to user states |
| 4 | Progress display | `static_dashboard/app.js` | `st.progress()` in Main.py | **ALREADY EXISTS** | MPT has progress bars |
| 5 | History | `jobs.json` (all terminal states) | Task files (lost on restart) | **ADAPT** | MPT needs persistent history |
| 6 | Video library | `GET /api/videos` | Task table in Main.py | **ENHANCE** | Add dedicated library view |
| 7 | Asset management | `assets.py` | Per-task directories | **ADAPT** | Add asset metadata |
| 8 | Retry | Not implemented | Not implemented | **DEFER** | Future enhancement |
| 9 | Cancel | `jobs.py:cancel` | `state.delete_task()` | **ALREADY EXISTS** | MPT can delete tasks |
| 10 | Thumbnail display | Not implemented | `st.image()` (Phase 11D) | **ALREADY EXISTS** | MPT has thumbnails |
| 11 | Provider selection | Hardcoded HTML (3 providers) | `video_sources` (7 providers) | **ALREADY EXISTS** | MPT has all providers |
| 12 | YouTube | Not in UI | Full YouTube support | **ALREADY EXISTS** | MPT has YouTube |
| 13 | Topic generation | `topic_planner.py` | LLM `/api/v1/scripts` | **ADAPT** | Integrate into batch UI |
| 14 | Production control | `production_control.py` | Task manager | **ALREADY EXISTS** | MPT has task manager |
| 15 | Job grouping | `niche/topic` columns | No grouping | **ADAPT** | Add batch-to-jobs hierarchy |
| 16 | Mobile CSS | `app.css` (partial) | `styles.css` (Phase 11F) | **ENHANCE** | Improve MPT mobile |
| 17 | Pagination | Not implemented | Task listing has pagination | **ALREADY EXISTS** | MPT has pagination |

---

## Capabilities to RETAIN (Integrate into MPT)

### 1. Persistent Job History
- **Factory:** SQLite persists all job history across restarts
- **MPT:** State lost on restart (in-memory) or requires Redis
- **Action:** Add optional persistent job history table to MPT state

### 2. Batch-to-Jobs Hierarchy
- **Factory:** Batch → N Jobs → N MPT Tasks
- **MPT:** Flat task list
- **Action:** Add batch grouping to MPT task manager

### 3. Dedicated Video Library View
- **Factory:** `GET /api/videos` returns all assets with metadata
- **MPT:** Video player embedded in task result
- **Action:** Add dedicated "Videos" view with grid/card layout

### 4. Better Mobile Navigation
- **Factory:** Tab-based navigation (Overview/Jobs/History/Videos/Batch)
- **MPT:** Single-page 4-column form + task popover
- **Action:** Add tabbed navigation to MPT WebUI

### 5. Production Status Dashboard
- **Factory:** Overview with health/queued/running/completed/failed counts
- **MPT:** Task manager popover with tabs
- **Action:** Enhance MPT dashboard with overview cards

---

## Capabilities to DISCARD

| Capability | Reason |
|---|---|
| Factory's SQLite schema | MPT uses different state model |
| Factory's job_id system | MPT uses task_id |
| Factory's asset tombstone pattern | MPT uses file deletion |
| Factory's topic planner | Will be replaced by Opportunity Engine |
| Factory's vanilla JS frontend | Replaced by MPT Streamlit |
| Factory's FastAPI backend | Replaced by MPT API |

---

## Implementation Priority

| Priority | Capability | Complexity |
|---|---|---|
| 1 | Navigation structure | LOW |
| 2 | Video library view | MEDIUM |
| 3 | Batch-to-jobs hierarchy | MEDIUM |
| 4 | Persistent job history | MEDIUM |
| 5 | Mobile optimization | LOW |
| 6 | Dashboard overview | LOW |
| 7 | Retry/cancel | DEFER |
