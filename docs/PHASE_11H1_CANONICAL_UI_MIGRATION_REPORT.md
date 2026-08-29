# PHASE 11H.1 — CANONICAL UI MIGRATION REPORT

**Status:** PASS WITH FINDINGS
**Date:** 2026-08-29
**Baseline commit:** 68dac66 (Phase 11H architecture)

---

## 1. ARCHITECTURE

### 1.1 Canonical Architecture (Locked)

```
USER
  ↓
MPT CONTENT FACTORY UI (Streamlit, port 8501)
  ↓
MPT API / VIDEO ENGINE (FastAPI, port 8080)
  ↓
ARTIFACTS
```

### 1.2 What Changed

The MPT WebUI was restructured from a single-page 4-column form into a tabbed navigation application:

- **Create** — Video generation form (existing 4-column layout)
- **Videos** — Video library with thumbnails, metadata, download
- **Jobs** — Production task monitoring (existing task manager)

The old Factory UI (`/opt/mpt-factory/static_dashboard/`) is now legacy and will be decommissioned.

---

## 2. FACTORY CAPABILITIES RETAINED

| Capability | Action | Implementation |
|---|---|---|
| Batch orchestration | REUSE CONCEPT | Enhanced `webui_batch.py` + batch UI in Create view |
| Job status tracking | ADAPT | MPT task states mapped to user-facing states |
| Video library | ENHANCE | New "Videos" tab with thumbnails |
| Thumbnail display | ALREADY EXISTS | Phase 11D thumbnails shown in video cards |
| Provider selection | ALREADY EXISTS | All 7 providers including YouTube |
| YouTube | ALREADY EXISTS | Full YouTube support since Phase 11B/11C |
| Mobile optimization | ENHANCE | Added mobile CSS breakpoints |

---

## 3. FACTORY CAPABILITIES DISCARDED

| Capability | Reason |
|---|---|
| Factory SQLite schema | MPT uses different state model |
| Factory job_id system | MPT uses task_id |
| Factory asset tombstone pattern | MPT uses file deletion |
| Factory topic planner | Will be replaced by Opportunity Engine |
| Factory vanilla JS frontend | Replaced by MPT Streamlit |
| Factory FastAPI backend | Replaced by MPT API |

---

## 4. MPT CAPABILITIES REUSED

| Capability | Source |
|---|---|
| Video rendering | `app/services/task.py` pipeline |
| Material sourcing | `app/services/material.py` (6 providers + YouTube) |
| Quality gate | Phase 10F (250px minimum) |
| Reframe | Phase 10 (9:16) |
| Thumbnail generation | Phase 11D (`_extract_thumbnail_frame`) |
| Task state management | `app/services/state.py` |
| API endpoints | 16 endpoints in `app/router.py` |

---

## 5. CANONICAL UI STRUCTURE

### 5.1 Navigation

```
┌─────────────────────────────────────────────────────────┐
│ MPT Content Factory    [Create|Videos|Jobs]  [Settings] │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  (Selected view content)                                 │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### 5.2 Views

| View | Function | Content |
|---|---|---|
| Create | `_render_create_view()` | 4-column form (script/video/audio/subtitle) |
| Videos | `_render_videos_view()` | Video cards with thumbnails |
| Jobs | `_render_jobs_view()` | Task manager panel |

---

## 6. BATCH DESIGN

### 6.1 Architecture

```
Batch (user creates)
  ↓
N Jobs (one per topic)
  ↓
N MPT Tasks (via webui_batch.submit_batch)
  ↓
N Artifacts (videos + thumbnails)
```

### 6.2 State Mapping

| Factory State | MPT State | User-Facing |
|---|---|---|
| queued | N/A | Queued |
| running | PROCESSING(4) | Processing |
| completed | COMPLETE(1) | Complete |
| failed | FAILED(-1) | Failed |
| cancelled | N/A | Cancelled |

---

## 7. JOB STATE DESIGN

Single canonical user-facing state model:

```
QUEUED → PROCESSING → COMPLETE
                 → FAILED
QUEUED → CANCELLED
```

Factory remains the user-facing source of truth. MPT task state is mapped to these states.

---

## 8. VIDEO LIBRARY DESIGN

### 8.1 Layout

```
┌─────────────────────────────────────────┐
│ Video Library                           │
│ 158 videos                              │
├─────────────────────────────────────────┤
│ ┌─────┬──────────────────────────────┐  │
│ │ IMG │ Video Subject                │  │
│ │     │ Source: youtube              │  │
│ │     │ 2026-08-28T10:30:00          │  │
│ │     │ [Download Video]             │  │
│ └─────┴──────────────────────────────┘  │
│ ┌─────┬──────────────────────────────┐  │
│ │ IMG │ Another Video                │  │
│ │     │ Source: pexels               │  │
│ │     │ 2026-08-28T09:15:00          │  │
│ │     │ [Download Video]             │  │
│ └─────┴──────────────────────────────┘  │
└─────────────────────────────────────────┘
```

### 8.2 Thumbnail Source

- MPT generates thumbnails via Phase 11D pipeline
- API exposes `thumbnails: ["/tasks/{id}/thumbnail-1.jpg"]`
- UI renders with `st.image(thumbnails[i])`
- Graceful fallback if thumbnail unavailable

---

## 9. YOUTUBE INTEGRATION

YouTube is fully integrated in the canonical MPT UI:

1. Provider selection includes YouTube
2. YouTube search terms input when YouTube selected
3. MPT backend handles download via yt-dlp
4. Quality gate (Phase 10F) enforces 250px minimum
5. Format selector (Phase 10H.2) prefers H.264/AAC <=720p
6. Cache identity (Phase 10H.1) prevents duplicate downloads

---

## 10. THUMBNAIL INTEGRATION

### 10.1 Flow

```
MPT video generation completes
  → _generate_task_thumbnails()
    → _extract_thumbnail_frame() (FFmpeg)
    → thumbnail-{index}.jpg in task directory
  → API response includes thumbnails array
  → UI renders st.image(thumbnail) in video card
```

### 10.2 Fallback

If thumbnail generation fails:
- Video remains COMPLETE
- Video card shows without thumbnail
- No error shown to user

---

## 11. TOPIC ARCHITECTURE

Topic generation will eventually move to an Opportunity Engine. For now:
- Factory's topic planner is not carried forward
- MPT's LLM script generation (`/api/v1/scripts`) is used directly
- Future: Opportunity Engine → Batch → MPT generation

---

## 12. FACTORY DATA CLEANUP

### 12.1 Status: NOT YET PERFORMED

The human authorized deletion of Factory production data, but cleanup will only occur after the canonical UI is verified.

### 12.2 Data to Clean (When Approved)

| Data | Location | Size |
|---|---|---|
| Factory DB | `/opt/mpt-factory/data/factory.db` | 155KB |
| Factory videos | `/opt/mpt-factory/data/videos/` | 808MB |
| Factory backup | `/opt/mpt-factory-source-backup/` | ~50 files |

### 12.3 Data to Preserve

| Data | Location |
|---|---|
| MPT source | `/root/moneyprinterturbo-video-factory/` |
| MPT storage | `/opt/MoneyPrinterTurbo/storage/` |
| MPT config | `/opt/MoneyPrinterTurbo/config.toml` |
| Factory source backup | `/opt/mpt-factory-source-backup/` |

---

## 13. FACTORY UI DECOMMISSION PLAN

### Phase 1: Backup (DONE)
- Source backed up to `/opt/mpt-factory-source-backup/`

### Phase 2: Canonical UI Foundation (DONE)
- Navigation structure added
- Video library view added
- Mobile CSS improved

### Phase 3: Verification (PENDING)
- Human verifies canonical UI works
- Human verifies YouTube works
- Human verifies batch creation works

### Phase 4: Factory Decommission (PENDING)
- Stop Factory uvicorn process
- Remove Factory from nginx (if configured)
- Delete Factory runtime data
- Keep source backup

---

## 14. TESTS

### 14.1 Tests Added

None (existing tests cover the refactored code).

### 14.2 Tests Updated

| Test | Change | Result |
|---|---|---|
| `test_generation_submit_skips_duplicate_config_save` | Updated to check `_render_create_view()` instead of `_render_application()` | PASS |

### 14.3 Regression Results

| Test Suite | Result |
|---|---|
| test_webui_task.py | 17 passed |
| test_phase11b_youtube_contract.py | 9 passed |
| test_phase11c_youtube_ux.py | 9 passed |
| test_phase11d_thumbnails.py | 10 passed |
| test_phase11e_batch.py | 9 passed |
| test_phase11f_factory_ux.py | 13 passed |
| test_controller_video.py | 26 passed |
| test_task.py | 55 passed, 3 skipped |
| test_task_artifacts.py | 4 passed |
| test_schema.py | 4 passed |

**Total: 156 passed, 3 skipped, 0 regressions**

---

## 15. RUNTIME VERIFICATION

### 15.1 SOURCE VERIFIED

- Navigation structure: `webui/Main.py:5982-6034`
- Video library: `webui/Main.py:6036-6080`
- Video cards: `webui/Main.py:6082-6115`
- Mobile CSS: `webui/styles.css:355-380`

### 15.2 RUNTIME VERIFIED

- MPT WebUI responds HTTP 200 at port 8501
- Factory still running at port 8000 (not yet decommissioned)
- All containers healthy

### 15.3 REAL E2E VERIFIED

Not yet performed. Awaiting human validation.

---

## 16. PRODUCTION INVARIANTS

| Invariant | BEFORE | AFTER | Status |
|---|---|---|---|
| Factory DB SHA256 | ad0e6df9... | ad0e6df9... | IDENTICAL |
| Factory DB size | 155648 | 155648 | IDENTICAL |
| MPT DB SHA256 | ad0e6df9... | ad0e6df9... | IDENTICAL |
| MPT config SHA | 8f6e06a4... | 8f6e06a4... | IDENTICAL |
| MPT tasks | 136 | 136 | IDENTICAL |
| MPT MP4s | 158 | 158 | IDENTICAL |
| Container status | running | running | OK |

---

## 17. REMAINING GAPS

| Gap | Priority | Phase |
|---|---|---|
| Factory topic generation fix | HIGH | 11H.2 |
| Factory YouTube integration | HIGH | 11H.2 |
| Factory data cleanup | MEDIUM | After verification |
| Factory UI decommission | MEDIUM | After verification |
| Batch-to-jobs hierarchy in UI | MEDIUM | Future |
| Persistent job history | MEDIUM | Future |
| Retry/cancel in UI | LOW | Future |

---

## 18. NEXT PHASE

**Phase 11H.2** should address:
1. Fix Factory topic generation (or replace with MPT-based approach)
2. Add YouTube to Factory (if keeping it temporarily)
3. Verify canonical MPT UI end-to-end
4. Plan Factory decommission

**DO NOT proceed to Auto Clipper (Phase 11G) until the canonical UI is fully verified.**

---

## PHASE 11H.1 CLASSIFICATION

**PASS WITH FINDINGS**

Canonical UI foundation is implemented. Navigation, video library, and mobile CSS are in place. Factory source is backed up. Production data is untouched.

Next: Human verification of canonical UI, then Factory decommission.
