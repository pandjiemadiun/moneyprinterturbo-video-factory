# PHASE 11F.0 — FACTORY UI/API PARITY AUDIT

**Status:** PASS WITH FINDINGS
**Date:** 2026-08-29
**Baseline commit:** 428746b (Phase 11 deployment)

---

## 1. CURRENT ARCHITECTURE

### 1.1 Application Structure

```
webui/
  Main.py (5907 lines) — single-page Streamlit app
  styles.css (439 lines) — responsive CSS with mobile breakpoints
  i18n/ — 10 language translation files
  .streamlit/config.toml — Streamlit browser config
```

**There is NO separate "Factory" UI.** The application IS MoneyPrinterTurbo. The term "Factory" in project documentation refers to the batch/content-factory workflow concept, not a separate UI component.

### 1.2 Entry Point

```
webui/Main.py:5907 → _render_application()
  → st.columns(4) layout:
    [0] _render_script_settings() — subject, language, script, keywords
    [1] _render_video_settings() — source, concat, transitions, aspect, clips
    [2] _render_audio_settings() — voice, TTS, BGM
    [3] _render_subtitle_settings() — subtitle controls
  → _render_generation_controls() — validation + submit
```

### 1.3 Backend Architecture

```
WebUI → webui_task.submit_generation() → _task_manager.add_task()
  → tm.start() → _run_pipeline()
    → generate_script → generate_terms → generate_audio → generate_subtitle
    → get_video_materials → generate_final_videos → generate_thumbnails
    → cross_post scheduling
```

---

## 2. FACTORY UI → BACKEND FLOW

### 2.1 Provider Selection Flow

```
_render_video_settings() (Main.py:3661)
  → video_sources hardcoded list (7 providers)
  → stable_selectbox() renders dropdown
  → params.video_source = selected value
  → _set_runtime_config() persists choice
```

### 2.2 Batch Service Flow (NOT WIRED)

```
webui_batch.submit_batch() (EXISTS but NOT IMPORTED in Main.py)
  → For each topic: webui_task.submit_generation(task_id, params)
  → Returns batch_id
  → Status derived from individual task states
```

### 2.3 Task Parameter Construction

```
_render_generation_controls() (Main.py:5531-5852)
  → 11 sequential validation checks
  → webui_task.submit_generation(params)
    → params.model_copy(deep=True)
    → sm.state.update_task(task_id, PROCESSING, 0)
    → _task_manager.add_task(_run_generation, ...)
```

---

## 3. SUPPORTED BACKEND PROVIDERS

### 3.1 Backend Material Service (material.py)

| Provider | Search Function | Download Function | Status |
|---|---|---|---|
| Pexels | `search_videos_pexels()` | `save_video()` | WORKING |
| Pixabay | `search_videos_pixabay()` | `save_video()` | WORKING |
| Coverr | `search_videos_coverr()` | `save_video()` | WORKING |
| YouTube | `search_videos_youtube()` | `save_video_youtube()` | WORKING (Phase 10H) |
| WaveSpeed | `generate_videos_wavespeed()` | N/A (AI generation) | WORKING |
| LoomLoom | `LoomLoomVideoBackend` | N/A (cloud render) | WORKING |
| Local | N/A (file upload) | N/A | WORKING |

### 3.2 Backend Provider Map (material.py:1767-1779)

```python
provider = "pexels"
remote_search_videos = search_videos_pexels
if source == "pixabay": ...
elif source == "coverr": ...
elif source == "youtube": ...    # ← Phase 11B added this branch
```

---

## 4. PROVIDERS EXPOSED BY FACTORY UI

### 4.1 Main UI Dropdown (Main.py:3661-3669)

```python
video_sources = [
    (tr("Pexels"), "pexels"),
    (tr("Pixabay"), "pixabay"),
    (tr("Coverr"), "coverr"),
    (tr("YouTube"), "youtube"),           # ← PRESENT (Phase 11B)
    (tr("WaveSpeed AI Video"), "wavespeed"),
    (tr("Shengsuan Cloud AI Video"), "loomloom"),
    (tr("Local file"), "local"),
]
```

### 4.2 Validation List (Main.py:5587-5595)

```python
if params.video_source not in [
    "pexels", "pixabay", "coverr", "youtube",
    "wavespeed", "loomloom", "local",
]:
```

### 4.3 Parity Status

| Provider | Backend | UI Dropdown | Validation | Parity |
|---|---|---|---|---|
| Pexels | YES | YES | YES | FULL |
| Pixabay | YES | YES | YES | FULL |
| Coverr | YES | YES | YES | FULL |
| YouTube | YES | YES | YES | FULL |
| WaveSpeed | YES | YES | YES | FULL |
| LoomLoom | YES | YES | YES | FULL |
| Local | YES | YES | YES | FULL |

**All 7 backend providers are exposed in the UI. Provider parity is FULL.**

---

## 5. EXACT PARITY GAPS

### 5.1 YouTube Integration Gap

**Status: NO GAP in main UI.** YouTube is fully integrated in the main single-video UI (Phase 11B/11C).

**Gap: No YouTube in batch workflow.** The batch service (`webui_batch.py`) can accept YouTube as a source (it passes through `video_source` param), but there is NO batch creation UI to exercise this.

### 5.2 Thumbnail Integration Gap

**Status: Backend has thumbnails (Phase 11D), UI does NOT display them.**

| Capability | Backend | UI |
|---|---|---|
| Thumbnail generation | YES (video.py:1539) | N/A |
| Thumbnail storage | YES (task state) | N/A |
| Thumbnail API exposure | YES (URI conversion) | N/A |
| Thumbnail display | N/A | **NO** |

The video library (`_render_task_table`) shows only:
- Status label
- Updated time
- Subject
- Progress percentage
- Action buttons (play, open, regenerate, delete)

**No thumbnail preview. No video poster. No visual thumbnail grid.**

### 5.3 Video Library Gap

| Capability | Status | Notes |
|---|---|---|
| Play | YES | st.video() player |
| Download | YES | st.download_button() |
| Delete | YES | With busy-state protection |
| Task status | YES | Labels: Complete/Processing/Failed |
| Thumbnail | **NO** | Not displayed |
| YouTube source metadata | **NO** | Not shown |
| Batch association | **NO** | No batch concept in UI |
| Error detail drill-down | **PARTIAL** | Error shown in generation snapshot, not task table |
| Video count indicator | **NO** | video_count > 1 not shown |

### 5.4 Batch Workflow Gap

| Capability | Backend | UI |
|---|---|---|
| Batch creation | YES (webui_batch.py) | **NO** |
| Batch status tracking | YES (get_batch_status) | **NO** |
| Batch task grouping | YES (task_ids list) | **NO** |
| Batch progress | YES (derived) | **NO** |
| Per-task error drill-down | YES (per-task state) | **NO** |

---

## 6. YOUTUBE INTEGRATION GAP ANALYSIS

### 6.1 What Exists

- YouTube in main UI dropdown (Phase 11B)
- YouTube help text and dynamic labels (Phase 11C)
- YouTube validation (empty query check)
- YouTube progress descriptions
- YouTube error message translation
- YouTube backend provider (Phase 10H)
- YouTube format selector (Phase 10H.2)
- YouTube cache identity (Phase 10H.1)

### 6.2 What's Missing

| Gap | Impact | Phase |
|---|---|---|
| No batch YouTube creation | Can't create multiple YouTube videos at once | 11F |
| No YouTube search results preview | User can't see what was found | Future |
| No YouTube metadata display | Can't see video title/channel in library | 11F |
| No YouTube cookies configuration | Some videos may fail to download | Future |

---

## 7. THUMBNAIL INTEGRATION GAP ANALYSIS

### 7.1 What Exists

- Thumbnail generation pipeline (Phase 11D)
- Thumbnail storage in task state
- Thumbnail URI conversion in API
- Thumbnail schema field (TaskStatusData)

### 7.2 What's Missing

| Gap | Impact | Phase |
|---|---|---|
| No thumbnail display in task table | No visual preview | 11F |
| No thumbnail grid view | Can't browse videos visually | 11F |
| No thumbnail fallback | Missing thumbnails not handled gracefully | 11F |
| No thumbnail lightbox/expand | Can't see full-size thumbnail | Future |

---

## 8. MOBILE UX FINDINGS

### 8.1 Current Mobile CSS (styles.css)

| Breakpoint | Target | Behavior |
|---|---|---|
| max-width: 480px | Small mobile | Brand font 1.5rem |
| max-width: 700px | Mobile | Task table → CSS Grid |
| 701-1100px | Tablet | 4-col → 2×2 grid |

### 8.2 Mobile Issues

| Issue | Severity | Location |
|---|---|---|
| 4-column form overflow | HIGH | Main.py:5874 `st.columns(4)` |
| Dense task table | MEDIUM | Main.py:998 5-column layout |
| 4 action buttons per row | MEDIUM | Main.py:1007 `st.columns(4)` |
| No mobile batch controls | HIGH | No batch UI exists |
| No thumbnail mobile layout | MEDIUM | No thumbnail display |
| Wide selectbox options | LOW | Provider dropdown fits but is long |
| Settings dialog width | MEDIUM | Dialog may overflow on small screens |

### 8.3 Streamlit Mobile Limitations

- Streamlit's native columns don't wrap — they shrink
- `layout="wide"` helps but doesn't solve mobile
- CSS Grid workaround exists for task table but not for form
- No native mobile navigation component
- Touch targets may be small (icon buttons)

---

## 9. STREAMLIT SUITABILITY ASSESSMENT

### 9.1 Can Streamlit Be Made Good Enough?

**YES, with limitations.**

| Requirement | Streamlit Capability | Verdict |
|---|---|---|
| Provider dropdown | Native selectbox | ADEQUATE |
| Batch creation form | Dynamic number_input + text_input | ADEQUATE |
| Batch status dashboard | st.progress + st.metric | ADEQUATE |
| Thumbnail grid | st.columns + st.image | ADEQUATE |
| Video cards | st.container + border | ADEQUATE |
| Mobile responsive | CSS overrides | MARGINAL |
| Real-time progress | @st.fragment polling | ADEQUATE |
| Touch-friendly controls | Limited | MARGINAL |

### 9.2 When React Would Be Needed

- Complex drag-and-drop batch reordering
- Real-time WebSocket progress (without polling)
- Native mobile app feel
- Complex video editing timeline
- Multi-touch gestures

**None of these are required for Phase 11F.**

---

## 10. RECOMMENDED MINIMAL IMPLEMENTATION

### 10.1 Batch Creation UI

```
New "Batch" tab or expander:
  [+ Add Topic] button
  Topic 1: [____________] Source: [YouTube ▼] Count: [2]
  Topic 2: [____________] Source: [YouTube ▼] Count: [1]
  Topic 3: [____________] Source: [Pexels ▼]  Count: [3]
  
  Common Settings:
  Voice: [____]  Subtitles: [x]  Aspect: [9:16]
  
  [Create Batch] → submit_batch()
```

### 10.2 Batch Monitor UI

```
Batch: 3/5 complete, 1 failed, 1 processing [=========>----] 65%

[✓] Topic 1: 2 videos [thumbnails] [play] [download]
[✓] Topic 2: 1 video [thumbnail] [play] [download]
[✗] Topic 3: Failed - "No footage found" [details] [retry]
[⟳] Topic 4: Processing 65% [progress bar]
[⧗] Topic 5: Queued
```

### 10.3 Video Library Enhancements

```
Task Table with thumbnails:
[IMG] Status    Updated        Subject          Progress Actions
[IMG] Complete  2 min ago      Space documentary 100%    [▶][📁][↻][🗑]
[IMG] Failed    5 min ago      Ocean waves       30%     [▶][📁][↻][🗑]
```

### 10.4 Mobile Improvements

- Single-column form on mobile (already partially handled)
- Stacked batch topic inputs
- Thumbnail grid 2-columns on mobile
- Larger touch targets for action buttons

---

## 11. RISKS

| Risk | Impact | Mitigation |
|---|---|---|
| Batch queue overflow | HTTP 429 | Limit batch size to 20 topics |
| Mobile layout breaking | Unreadable UI | Test at 320px, 375px, 768px |
| Thumbnail loading slow | Poor UX | Lazy load + placeholder |
| Session state loss | Batch metadata lost | Acceptable for 11F; persist later |
| Config race in batch | Inconsistent settings | Each task snapshots params (existing) |

---

## 12. TESTS REQUIRED

| Test | Purpose |
|---|---|
| Batch creation creates N tasks | Verify submit_batch loop |
| Batch status derivation | Verify get_batch_status logic |
| Batch with YouTube source | Verify YouTube passthrough |
| Batch failure isolation | One failure doesn't break batch |
| Thumbnail display in UI | Verify thumbnail rendering |
| Missing thumbnail fallback | Graceful handling |
| Mobile layout at 320px | No horizontal overflow |
| Mobile layout at 768px | Tablet layout works |
| Batch size limit | Reject >20 topics |
| Existing single-video preserved | No regression |

---

## 13. API CONTRACT REUSE

### 13.1 Existing APIs That Can Be Reused

| Endpoint | Reuse For |
|---|---|
| POST /api/v1/videos | Batch task creation (loop) |
| GET /api/v1/tasks | Batch task listing |
| GET /api/v1/tasks/{id} | Per-task status |
| GET /api/v1/stream/{file} | Video playback |
| GET /api/v1/download/{file} | Video download |

### 13.2 API Changes Needed

**NONE.** All batch functionality can be implemented using existing APIs. The batch service (`webui_batch.py`) already uses `webui_task.submit_generation()` which calls the existing task pipeline.

---

## 14. CONCLUSIONS

### 14.1 Provider Parity: FULL

All 7 backend providers (including YouTube) are exposed in the main UI. There is NO provider parity gap in the single-video workflow.

### 14.2 Actual Gaps

| Gap | Priority | Complexity |
|---|---|---|
| No batch creation UI | HIGH | MEDIUM |
| No batch monitor UI | HIGH | MEDIUM |
| No thumbnail display | MEDIUM | LOW |
| No YouTube metadata display | LOW | LOW |
| Mobile form layout | MEDIUM | MEDIUM |
| Batch error drill-down | MEDIUM | LOW |

### 14.3 Streamlit Verdict

**Streamlit is adequate for Phase 11F.** No need for React migration at this time. The main limitations (mobile UX, touch targets) can be addressed with CSS overrides and careful layout design.

---

## 15. RECOMMENDED PHASE 11F IMPLEMENTATION

1. **Batch Creation Panel** — Dynamic topic list, source selection, common settings
2. **Batch Monitor Panel** — Progress dashboard, per-task status, error drill-down
3. **Thumbnail Display** — Show thumbnails in task table and batch monitor
4. **Mobile Layout** — Single-column form, stacked controls, touch-friendly buttons
5. **YouTube Metadata** — Show source info (title, channel) when available

All using existing APIs. No backend changes required.

---

## PHASE 11F.0 CLASSIFICATION

**PASS WITH FINDINGS**

Production mutations: 0
Source modifications: 0 (audit only)
Config modifications: 0
Database modifications: 0
Deployment: NONE
Git working tree: CLEAN

Next: Phase 11F implementation (approved)
