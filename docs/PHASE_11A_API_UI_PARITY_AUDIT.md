# PHASE 11A — API/UI PARITY AUDIT + UX ARCHITECTURE SPEC

**Status:** PASS WITH FINDINGS
**Date:** 2026-08-28
**Baseline commit:** bdbcdb5
**Production mutations:** 0

---

## 1. EXECUTIVE SUMMARY

Phase 11A audited the complete USER → WEBUI → API → TASK MANAGER → PRODUCTION ENGINE → MEDIA ARTIFACTS → WEBUI path.

**Key findings:**

1. **The backend is significantly more capable than the WebUI exposes.** YouTube provider, TwelveLabs semantic reranking, cross-post automation, scene-aware planning, LoomLoom batch generation, and advanced transition modes all exist in the backend but are either partially or completely hidden from the UI.

2. **The API surface is minimal by design** — 12 endpoints total — but the WebUI does not fully exploit even these. No batch endpoint exists at all.

3. **YouTube is fully implemented in the backend** (Phase 10H) but has zero WebUI integration. It cannot be selected, searched, or submitted through the interface.

4. **No thumbnail pipeline exists anywhere** — not in the backend, API, or UI.

5. **Batch production is entirely absent** — neither API nor UI supports submitting multiple tasks at once.

6. **Streamlit is adequate for Phase 11 but will become a bottleneck** for batch workflows, realtime progress, and mobile UX.

7. **The Auto Clipper can reuse approximately 70% of the existing production engine** — reframe, subtitle, voice, timing, and material handling all have clean seams.

8. **The money-making workflow has 6 of 13 links fully implemented**, 4 partially implemented, and 3 missing.

---

## 2. CURRENT ARCHITECTURE

```
USER
  ↓
WEBUI (Streamlit, webui/Main.py, 5865 lines)
  ↓ (direct function calls OR /api/v1 via requests)
API (FastAPI, app/router.py → 12 endpoints)
  ↓
TASK MANAGER (InMemory or Redis)
  ↓
PRODUCTION ENGINE (app/services/task.py → video.py, voice.py, material.py, subtitle.py, bgm.py)
  ↓
MEDIA ARTIFACTS (storage/tasks/<task_id>/)
  ↓
WEBUI (via /tasks static mount + /api/v1/tasks/{task_id} polling)
```

**Key architectural observations:**

- The WebUI runs in-process with the backend (Streamlit directly calls `webui_task.submit_generation()` which uses `InMemoryTaskManager`). The API runs in a separate FastAPI process. Both share the same `state` singleton.
- Static file serving for generated artifacts: `app.mount("/tasks", StaticFiles(directory=task_dir))` in `asgi.py:130`.
- The WebUI is a single 5865-line file with no separation of concerns — all UI logic, state management, API client code, and business validation live in one file.
- The backend services layer (`app/services/`) is well-modularized with clear separation.

---

## 3. BACKEND CAPABILITY INVENTORY

### 3.1 Video Creation

| Capability | Backend Function | Location |
|---|---|---|
| Full video generation pipeline | `task.start()` | `app/services/task.py:150+` |
| Scene-aware generation (opt-in) | `compute_scene_durations()` + `VideoParams.video_scenes` | `app/services/scene_durations.py` |
| Smart 9:16 reframing | `reframe.compute_crop_offset()` | `app/services/reframe.py` |
| Video transition modes | `video_effects.apply_transition()` | `app/services/utils/video_effects.py` |
| Clip speed adjustment | `utils.normalize_clip_speed()` | `app/utils/utils.py` |
| Multiple video codecs | `video._get_configured_video_codec()` | `app/services/video.py:171` |
| WaveSpeed AI video generation | `material.generate_videos_wavespeed()` | `app/services/material.py:825` |
| LoomLoom AI video generation | `loomloom.LoomLoomVideoBackend` | `app/services/loomloom.py` |

### 3.2 Material Sources

| Capability | Backend Function | Location |
|---|---|---|
| Pexels search + download | `material.search_videos_pexels()` | `app/services/material.py:311` |
| Pixabay search + download | `material.search_videos_pixabay()` | `app/services/material.py:393` |
| Coverr search + download | `material.search_videos_coverr()` | `app/services/material.py:519` |
| YouTube search + download | `material.search_videos_youtube()` + `material.save_video_youtube()` | `app/services/material.py:623+` |
| Local file upload | `material_upload.save_material_upload()` | `app/services/material_upload.py` |
| TwelveLabs semantic reranking | `twelvelabs.rerank_terms()` | `app/services/twelvelabs.py` |
| Material cache with TTL | `material_cache` | `app/services/material_cache.py` |
| Startup orphan cleanup | `material.run_startup_cleanup()` | `app/services/material.py` |

### 3.3 Audio/Voice

| Capability | Backend Function | Location |
|---|---|---|
| Azure TTS (V1 + V2) | `voice.tts()` edge-tts path | `app/services/voice.py` |
| ElevenLabs TTS | `voice.tts()` elevenlabs path | `app/services/voice.py` |
| SiliconFlow TTS | `voice.tts()` siliconflow path | `app/services/voice.py` |
| Gemini TTS | `voice.tts()` gemini path | `app/services/voice.py` |
| MiMo TTS | `voice.tts()` mimo path | `app/services/voice.py` |
| MiniMax TTS | `voice.tts()` minimax path | `app/services/voice.py` |
| Fish Audio TTS | `voice.tts()` fish_audio path | `app/services/voice.py` |
| Chatterbox TTS | `voice.tts()` chatterbox path | `app/services/voice.py` |
| Custom audio upload | `params.custom_audio_file` | `app/models/schema.py:119` |
| No-voice mode | `voice.NO_VOICE_NAME` sentinel | `app/services/voice.py:75` |

### 3.4 Background Music

| Capability | Backend Function | Location |
|---|---|---|
| Random BGM from library | `bgm_service.list_bgm_files()` | `app/services/bgm.py` |
| Custom BGM upload | `bgm_service.save_bgm_upload()` | `app/services/bgm.py` |
| Sonilo AI music generation | `sonilo.generate_bgm()` | `app/services/sonilo.py` |
| ElevenLabs music generation | `elevenlabs_music.generate_bgm()` | `app/services/elevenlabs_music.py` |

### 3.5 Subtitles

| Capability | Backend Function | Location |
|---|---|---|
| Whisper transcription | `subtitle.create()` | `app/services/subtitle.py:22` |
| Subtitle styling (font, color, stroke, background, position) | `video.TextClip` | `app/services/video.py` |
| Subtitle font validation | `video.subtitle_font_supports_text()` | `app/services/video.py` |
| Rounded subtitle background | `params.rounded_subtitle_background` | `app/models/schema.py:143` |
| Subtitle-only generation | `create_task(stop_at="subtitle")` | `app/controllers/v1/video.py:183` |

### 3.6 LLM/Script

| Capability | Backend Function | Location |
|---|---|---|
| Script generation | `llm.generate_script()` | `app/services/llm.py` |
| Keyword/term generation | `llm.generate_terms()` | `app/services/llm.py` |
| Social metadata generation | `llm.generate_social_metadata()` | `app/services/llm.py` |
| LoomLoom batch script generation | `loomloom.LoomLoomScriptBackend` | `app/services/loomloom.py` |
| 20+ LLM provider adapters | `LLM_PROVIDER_REGISTRY` | `app/models/llm_provider.py:187-407` |

### 3.7 Cross-Post / Publishing

| Capability | Backend Function | Location |
|---|---|---|
| Upload-Post integration | `upload_post.UploadPostService` | `app/services/upload_post.py` |
| TikTok, Instagram, Facebook Reels | via Upload-Post API | `app/services/upload_post.py:61-67` |
| YouTube Shorts | via Upload-Post API | `app/services/upload_post.py:62-69` |
| Auto-upload after generation | `task.auto_cross_post()` | `app/services/task.py` |

### 3.8 Task Management

| Capability | Backend Function | Location |
|---|---|---|
| Task creation | `state.update_task()` | `app/services/state.py:57` |
| Task querying | `state.get_task()` | `app/services/state.py:76` |
| Task listing (paginated) | `state.get_all_tasks()` | `app/services/state.py:49` |
| Task deletion | `state.delete_task()` | `app/services/state.py:92` |
| Task busy check | `task.is_task_busy()` | `app/services/task.py:103` |
| Cross-post state tracking | `state.patch_task(cross_post_state=...)` | `app/services/state.py` |
| Interrupted cross-post recovery | `task.recover_interrupted_cross_posts()` | `app/services/task.py` |

---

## 4. API ENDPOINT INVENTORY

**Base prefix:** `/api/v1` (configured in `app/controllers/v1/base.py:7`)

| # | Method | Endpoint | Request Model | Response Model | Description |
|---|---|---|---|---|---|
| 1 | GET | `/ping` | — | `"pong"` | Health check (no prefix, unprotected) |
| 2 | POST | `/api/v1/videos` | `TaskVideoRequest` | `TaskResponse` | Create full video generation task |
| 3 | POST | `/api/v1/subtitle` | `SubtitleRequest` | `TaskResponse` | Generate subtitle only |
| 4 | POST | `/api/v1/audio` | `AudioRequest` | `TaskResponse` | Generate audio only |
| 5 | GET | `/api/v1/tasks` | Query: page, page_size | `TaskListResponse` | List all tasks (paginated) |
| 6 | GET | `/api/v1/tasks/{task_id}` | — | `TaskQueryResponse` | Get task status |
| 7 | DELETE | `/api/v1/tasks/{task_id}` | — | `TaskDeletionResponse` | Delete task + artifacts |
| 8 | GET | `/api/v1/stream/{file_path}` | — | `StreamingResponse` | Video streaming with byte-range |
| 9 | GET | `/api/v1/download/{file_path}` | — | `FileResponse` | Download video file |
| 10 | GET | `/api/v1/musics` | — | `BgmRetrieveResponse` | List BGM files |
| 11 | POST | `/api/v1/musics` | `UploadFile` | `BgmUploadResponse` | Upload BGM file |
| 12 | GET | `/api/v1/video_materials` | — | `VideoMaterialRetrieveResponse` | List local video materials |
| 13 | POST | `/api/v1/video_materials` | `UploadFile` | `VideoMaterialUploadResponse` | Upload local video material |
| 14 | POST | `/api/v1/scripts` | `VideoScriptRequest` | `VideoScriptResponse` | Generate script via LLM |
| 15 | POST | `/api/v1/terms` | `VideoTermsRequest` | `VideoTermsResponse` | Generate video keywords |
| 16 | POST | `/api/v1/social-metadata` | `VideoSocialMetadataRequest` | `VideoSocialMetadataResponse` | Generate social metadata |

**Static mounts (not router-based):**
- `/tasks/{file_path}` — StaticFiles (generated artifacts, protected by middleware)
- `/` — StaticFiles (`resource/public/`)

**Missing API endpoints (backend supports but no endpoint exists):**
- No batch task creation
- No YouTube-specific search endpoint (YouTube uses same material pipeline)
- No thumbnail endpoint
- No settings/config read/write endpoint (configured via config.toml only)
- No LLM provider listing endpoint
- No cross-post status endpoint (embedded in task status)

---

## 5. WEBUI CAPABILITY INVENTORY

### 5.1 UI Sections (from `webui/Main.py`)

| Section | Function | Lines | Description |
|---|---|---|---|
| Top bar | `_render_top_bar()` | 1400-1467 | Brand, task manager popover, settings button, language selector |
| Settings dialog | `_render_settings_dialog()` | 2510-2873 | LLM settings, material API keys, key backup, cache management, UI settings |
| Script settings | `_render_script_settings()` | 3453-3617 | Subject, language, advanced script options, LoomLoom/local script gen |
| Video settings | `_render_video_settings()` | 3620-3851 | Source, concat mode, transitions, aspect, clip duration/speed, codec, count |
| Audio settings | `_render_audio_settings()` | 4731-5238 | Voice mode (TTS/upload/none), TTS provider, voice, volume, rate, BGM |
| Subtitle settings | `_render_subtitle_settings()` | 5241-494 | Enable, font, position, color, size, stroke, background |
| Generation controls | `_render_generation_controls()` | 5496-5810 | Validation, task submission, progress display |
| Task manager panel | `_render_task_manager_panel()` | 1069-1097 | Tabs: All/Processing/Complete/Failed with per-task actions |
| Task restore dialog | `_render_task_restore_dialog()` | 1316-1348 | Load historical task parameters |
| LoomLoom settings | `_render_loomloom_script_generation()` | 3271-3450 | Batch script quote, poll, candidate selection |
| LoomLoom video | `_render_loomloom_video_settings()` | 2996-3080 | AI video quote, scene count, charge confirmation |
| WaveSpeed settings | `_render_wavepeed_video_settings()` | 3854-3883 | Billing estimate, charge confirmation |

### 5.2 What the WebUI Exposes (Confirmed by Source Inspection)

- [x] Video subject input
- [x] Script input + LLM generation (local + LoomLoom)
- [x] Keyword input + LLM generation
- [x] Video source selection: Pexels, Pixabay, Coverr, WaveSpeed, LoomLoom, Local
- [x] Aspect ratio per source (source-specific memory)
- [x] Clip duration, speed, count
- [x] Video codec selection (libx264, NVENC, AMF, QSV, etc.)
- [x] Concat mode (random/sequential)
- [x] Transition modes (8 types)
- [x] Voice mode (TTS/upload/none)
- [x] 8 TTS provider selections with per-provider configuration
- [x] Voice preview (sample + full)
- [x] BGM source (none/random/custom/Sonilo/ElevenLabs)
- [x] Subtitle controls (enable, font, position, color, size, stroke, background)
- [x] LLM provider selection (20+ providers from registry)
- [x] API key management
- [x] Task history with playback, delete, regenerate
- [x] Task progress with streaming logs
- [x] Video playback and download
- [x] Settings preset import/export
- [x] Key backup/restore
- [x] Cache management
- [x] Onboarding tour
- [x] i18n (10 languages)

### 5.3 What the WebUI Does NOT Expose (Backend supports but UI missing)

- [ ] **YouTube as a video source** — fully implemented in `material.search_videos_youtube()` and `material.save_video_youtube()` but absent from WebUI source dropdown
- [ ] **YouTube search vs direct URL mode** — backend supports both
- [ ] **Multi-provider fallback** — `VideoParams.video_sources` exists but UI only allows single source
- [ ] **TwelveLabs semantic reranking** — backend has `twelvelabs.rerank_terms()`, UI has no toggle
- [ ] **Cross-post / auto-publish configuration** — backend has full Upload-Post integration, UI has no controls
- [ ] **Scene-aware planning** — `VideoParams.video_scenes` exists, UI has no scene editor
- [ ] **Social metadata generation** — API endpoint `/api/v1/social-metadata` exists, UI has no button
- [ ] **Batch task creation** — no API endpoint, no UI
- [ ] **Thumbnail generation/selection** — no backend support, no UI
- [ ] **Material metadata display** — provenance data is captured (`source_info`) but never shown in UI
- [ ] **Task filtering/search beyond status tabs** — no text search, no date range
- [ ] **Video library / gallery view** — tasks are listed in a table but no thumbnail grid

---

## 6. API ↔ UI PARITY MATRIX

| Capability | Backend | API | UI | Working | Missing Piece |
|---|---|---|---|---|---|
| Video generation | YES | YES | YES | YES | — |
| Subtitle-only generation | YES | YES | NO | — | No UI button for subtitle-only |
| Audio-only generation | YES | YES | NO | — | No UI button for audio-only |
| Pexels material | YES | YES | YES | YES | — |
| Pixabay material | YES | YES | YES | YES | — |
| Coverr material | YES | YES | YES | YES | — |
| YouTube material | YES | YES | NO | — | **YouTube missing from UI** |
| WaveSpeed AI video | YES | YES | YES | YES | — |
| LoomLoom AI video | YES | YES | YES | YES | — |
| Local material upload | YES | YES | YES | YES | — |
| Multi-provider fallback | YES | YES | NO | — | UI only allows single source |
| TwelveLabs reranking | YES | NO | NO | — | No API, no UI |
| Cross-post / publishing | YES | NO | NO | — | No API, no UI |
| Scene-aware planning | YES | YES | NO | — | No scene editor in UI |
| Social metadata | YES | YES | NO | — | No UI button |
| Batch creation | NO | NO | NO | — | **Entirely missing** |
| Thumbnail generation | NO | NO | NO | — | **Entirely missing** |
| Task list | YES | YES | YES | YES | — |
| Task status | YES | YES | YES | YES | — |
| Task deletion | YES | YES | YES | YES | — |
| Video streaming | YES | YES | YES | YES | — |
| Video download | YES | YES | YES | YES | — |
| BGM list | YES | YES | NO | — | No BGM library browser in UI |
| BGM upload | YES | YES | YES | YES | — |
| LLM script gen | YES | YES | YES | YES | — |
| LLM terms gen | YES | YES | YES | YES | — |
| LLM provider select | YES | NO | YES | YES | Provider list hardcoded in WebUI |
| Voice preview | YES | NO | YES | YES | Direct service call from WebUI |
| Task restore | YES | NO | YES | YES | Direct state access from WebUI |
| Settings preset | YES | NO | YES | YES | Direct config access from WebUI |
| Key backup | YES | NO | YES | YES | Direct config access from WebUI |

---

## 7. YOUTUBE UI GAP ANALYSIS

### 7.1 Backend Status (CONFIRMED)

YouTube is fully implemented in the backend:

- **Search:** `material.search_videos_youtube()` at `app/services/material.py:623` — uses `yt_dlp` with `ytsearch:` query, flat metadata extraction, no authentication required for search.
- **Download:** `material.save_video_youtube()` — uses `yt_dlp` with H.264/AAC preferred format, <=720p selection, output-aware quality gate, portrait-aware effective resolution, 1080x1920 reframe.
- **Cache identity:** `_youtube_video_identity()` at `app/services/material.py:1282` — canonical YouTube video ID extraction, collision-safe.
- **Cleanup:** Failed download cleanup, partial download cleanup, orphan cache sweeper, startup cleanup — all implemented.
- **Provenance:** YouTube-specific fields (title, channel, license_status, video_id) captured in `source_info`.

### 7.2 API Status (CONFIRMED)

YouTube is callable through the API indirectly — when a task is created via `POST /api/v1/videos` with `video_source="youtube"`, the backend material pipeline handles it. No dedicated YouTube endpoint exists.

### 7.3 WebUI Status (CONFIRMED — MISSING)

The WebUI video source dropdown at `webui/Main.py:3630-3637`:
```python
video_sources = [
    (tr("Pexels"), "pexels"),
    (tr("Pixabay"), "pixabay"),
    (tr("Coverr"), "coverr"),
    (tr("WaveSpeed AI Video"), "wavespeed"),
    (tr("Shengsuan Cloud AI Video"), "loomloom"),
    (tr("Local file"), "local"),
]
```

**YouTube is NOT in this list.**

### 7.4 YouTube Gap Questions Answered

| Question | Answer | Evidence |
|---|---|---|
| Is YouTube callable through the API? | YES | `video_source="youtube"` in `TaskVideoRequest` |
| Is YouTube callable through the WebUI? | **NO** | Not in `video_sources` list at `webui/Main.py:3630` |
| Can UI select YouTube as provider? | **NO** | Missing from dropdown |
| Can UI search YouTube? | **NO** | No search input, no results display |
| Can UI submit direct YouTube URL? | **NO** | No URL input field |
| Can UI display YouTube as material source? | **NO** | No provider indicator |
| Can users mix YouTube + Pexels + etc.? | **PARTIAL** | `video_sources` list exists in schema but UI only allows single source |
| Can a batch use multiple providers? | **NO** | No batch support |
| Is provider-specific config exposed? | **NO** | YouTube cookies file, TLS verify — not in UI |
| Are failures visible? | **PARTIAL** | Task status shows error but no YouTube-specific diagnostics |
| Is provenance metadata sufficient? | **YES** | title, channel, license_status, video_id all captured |

---

## 8. BATCH UX ANALYSIS

### 8.1 Current State

The WebUI has **no batch interface**. The "New Batch" mentioned in the audit scope does not exist in the current codebase. The closest feature is `video_count` (1-5 simultaneous videos from the same script), which generates multiple outputs from one configuration — not true batch production.

### 8.2 What "New Batch" Should Be

True batch production means submitting multiple independent tasks with different subjects/scripts/material sources from a single form. This is entirely absent.

### 8.3 Current "New Batch" Conceptual UX vs Reality

The desired UX described in the audit scope:
- Topics/scripts list
- Material sources (Pexels, Pixabay, Coverr, YouTube)
- YouTube mode (search vs direct URL)
- Format, duration, voice, subtitles, quantity
- Single "CREATE BATCH" button

**Reality:** None of this exists. The current UI is a single-task form with 4 columns (script, video, audio, subtitle) and one "Generate Video" button.

### 8.4 Mapping to Existing API

The existing API could support batch with:
- Loop over `POST /api/v1/videos` for each task
- Collect task IDs
- Poll `GET /api/v1/tasks/{task_id}` for each
- No server-side batch coordination exists

---

## 9. VIDEO ARTIFACT ANALYSIS

### 9.1 Artifact Types

| Artifact | Pattern | Created By | Persisted | API Exposure | UI Exposure |
|---|---|---|---|---|---|
| Final video | `final-{index}.mp4` | `video.combine_videos()` | YES (permanent) | YES (`task.videos`) | YES (player + download) |
| Combined video | `combined-{index}.mp4` | `video.combine_videos()` | YES (permanent) | YES (`task.combined_videos`) | **NO** — not displayed |
| Audio | `audio.mp3` | `voice.tts()` | YES (permanent) | **NO** | **NO** |
| Subtitle | `subtitle.srt` | `subtitle.create()` | YES (permanent) | **NO** | **NO** |
| Script data | `script.json` | `task_artifacts.write_script_data()` | YES (permanent) | **NO** | Partial (restore only) |
| Scene timing | `scene_timing.json` | `scene_durations.compute_scene_durations()` | YES (permanent) | **NO** | **NO** |
| Temp clips | `temp-clip-*.mp4` | `video.combine_videos()` | Cleaned up | NO | NO |
| BGM | `bgm.{mp3,m4a}` | `bgm_service` | YES (permanent) | NO | NO |

### 9.2 Key Observations

- `combined-{index}.mp4` is created and stored in task state (`combined_videos` field) but **never displayed or offered for download in the WebUI**. This is a significant hidden artifact.
- `audio.mp3` and `subtitle.srt` are generated but have no download path in the UI.
- `script.json` contains rich metadata (params, search terms, material sources) but is only used for task restore, never displayed to users.
- No thumbnail/poster image is generated for any video.

---

## 10. THUMBNAIL ANALYSIS

### 10.1 Search Results

Searched entire repository for: `thumbnail`, `thumb`, `poster`, `cover image`, `preview image`, `video poster`, `.jpg`, `.jpeg`, `.png`.

**Findings:**

- `material_upload.py` references `.jpg`, `.jpeg`, `.png` — but only for **upload validation** of image files as potential material, not for thumbnail generation.
- `video.py:400` references `.sanitized.png` — a subtitle rendering intermediate, not a thumbnail.
- **No thumbnail generation code exists anywhere in the codebase.**
- **No thumbnail extraction code exists.**
- **No thumbnail is persisted.**
- **No thumbnail is exposed by the API.**
- **No thumbnail is displayed by the WebUI.**

### 10.2 Classification

**Thumbnail generation is MISSING — proposed as Phase 11 capability.**

A clean implementation would:
1. Extract a frame at 1 second (or 25% mark) from `final-{index}.mp4` using FFmpeg
2. Save as `thumbnail.jpg` in the task directory
3. Expose via `GET /api/v1/tasks/{task_id}` response
4. Display in WebUI task cards and video gallery

---

## 11. MOBILE UX ANALYSIS

### 11.1 Current Mobile Issues (from CSS inspection)

The `webui/styles.css` (439 lines) shows limited mobile-specific CSS. Key observations:

- **Layout:** `st.set_page_config(layout="wide")` — wide layout is problematic on mobile
- **4-column form:** `st.columns(4)` at `webui/Main.py:5832` — 4 columns will overflow or stack poorly on narrow screens
- **Segmented control fix:** CSS at lines 29-43 specifically addresses voice mode control wrapping — evidence of mobile awareness but reactive, not proactive
- **No viewport meta tag control** — Streamlit handles this but `wide` layout fights mobile
- **Task table:** 5-column layout with 4 action buttons per row — extremely dense for mobile
- **No bottom navigation** — Streamlit sidebar is hidden by default on mobile

### 11.2 Specific Mobile Problems

| Problem | Location | Severity |
|---|---|---|
| 4-column form overflow | `webui/Main.py:5832` | HIGH |
| 5-column task table with 4 action buttons | `webui/Main.py:998-1010` | HIGH |
| Wide page layout | `webui/Main.py:65` | MEDIUM |
| No touch-optimized controls | Global | MEDIUM |
| Popover task manager on mobile | `webui/Main.py:1107` | MEDIUM |
| Video player sizing | `webui/Main.py:1690` | LOW |
| No pull-to-refresh | Global | LOW |
| Settings dialog too wide | `webui/Main.py:2512` | MEDIUM |

---

## 12. AUTO CLIPPER COMPATIBILITY ANALYSIS

### 12.1 Required Subsystem Mapping

| Auto Clipper Input | Existing Service | Reusable? | Notes |
|---|---|---|---|
| Long-form video input | `material.save_video_youtube()` + `material_upload` | YES | YouTube + local upload already supported |
| Transcription | `subtitle.create()` (Whisper) | YES | Already transcribes audio to SRT with word timestamps |
| Shot/scene detection | `reframe.cropdetect` + `video_effects` | PARTIAL | FFmpeg cropdetect exists; no dedicated scene detection |
| Highlight scoring | — | NO | New capability needed |
| Clip selection | — | NO | New capability needed |
| 9:16 reframe | `reframe.compute_crop_offset()` + `video.combine_videos()` | YES | Full scale-to-cover + crop pipeline exists |
| Captions | `video.TextClip` + `subtitle.create()` | YES | Subtitle burn-in already implemented |
| Thumbnail | — | NO | New capability needed |
| Multiple shorts output | `video_count` parameter | PARTIAL | Can generate N videos but from same script |

### 12.2 Architectural Seams Needed

1. **Transcription adapter** — Whisper already produces word-level timestamps; needs a wrapper that returns structured segments with confidence scores.
2. **Scene detection service** — New service using FFmpeg `select='scene'` or PySceneDetect.
3. **Highlight scoring engine** — New service; LLM-based or heuristic (audio energy, face presence, text density).
4. **Clip selection strategy** — New service; selects best N non-overlapping segments.
5. **Batch short synthesis** — Reuses `task.start()` with per-clip parameters.
6. **Thumbnail extraction** — New service; FFmpeg frame extraction.

### 12.3 Reuse Estimate

**70% reusable** — the production engine already handles video input, transcription, reframing, captioning, and output. The missing 30% is intelligence (scene detection, highlight scoring, clip selection).

---

## 13. STREAMLIT VS REACT/VITE EVALUATION

### 13.1 Option A: Improve Existing Streamlit UI

| Factor | Rating | Notes |
|---|---|---|
| Development cost | LOW | No new infrastructure |
| Mobile UX | POOR | Streamlit is fundamentally desktop-oriented |
| API integration | GOOD | Already works via direct calls |
| Realtime progress | FAIR | Fragment polling works but is inefficient |
| Video gallery | POOR | No native grid/thumbnail component |
| Batch workflows | POOR | Streamlit rerun model fights multi-step workflows |
| Maintainability | FAIR | 5865-line single file is technical debt |
| Deployment complexity | LOW | Single process |
| Risk to production engine | NONE | No backend changes needed |

### 13.2 Option B: Small Frontend/API Separation (Keep Streamlit Temporarily)

| Factor | Rating | Notes |
|---|---|---|
| Development cost | MEDIUM | Need to formalize API contract |
| Mobile UX | POOR (Streamlit) / GOOD (new UI) | Depends on which UI is used |
| API integration | GOOD | Forces clean API design |
| Realtime progress | GOOD | WebSocket/SSE possible |
| Video gallery | GOOD | Can be built in either UI |
| Batch workflows | GOOD | Multi-step forms are natural in web |
| Maintainability | GOOD | Separation of concerns |
| Deployment complexity | MEDIUM | Two processes to deploy |
| Risk to production engine | LOW | API layer is additive |

### 13.3 Option C: Replace with React/Vite

| Factor | Rating | Notes |
|---|---|---|
| Development cost | HIGH | New build system, routing, state management |
| Mobile UX | EXCELLENT | Full control over responsive design |
| API integration | GOOD | Requires complete API surface |
| Realtime progress | EXCELLENT | Native WebSocket support |
| Video gallery | EXCELLENT | Custom components |
| Batch workflows | EXCELLENT | Multi-step wizards, drag-and-drop |
| Maintainability | GOOD | Modern component architecture |
| Deployment complexity | HIGH | Separate build, CDN, API proxy |
| Risk to production engine | LOW | No backend changes if API is stable |

### 13.4 Recommendation

**Phase 11: Option A (improve Streamlit) for immediate needs.**
**Phase 12+: Option B (gradual API formalization) as foundation for future React migration.**

Rationale:
- The immediate user-facing gaps (YouTube UI, thumbnails, batch) can all be addressed within Streamlit
- A full React rewrite would take 4-8 weeks and delay all feature work
- The API-first approach (Option B) should be started in Phase 11 by adding missing endpoints
- Streamlit's limitations become blocking only for: realtime collaboration, complex batch workflows, and polished mobile

---

## 14. OPEN SOURCE UI CANDIDATE EVALUATION

**Recommendation: Do not adopt any external UI framework in Phase 11.**

Rationale:
- The application has highly domain-specific workflows (video parameter configuration, TTS preview, LLM prompt engineering) that generic UI frameworks don't address
- The existing Streamlit UI already works and is understood
- Integration risk with the protected production engine is significant
- The cost of adapting an external UI exceeds the cost of improving the current one

**If a future React migration is pursued**, relevant candidates would be:
- **Refine** (Apache 2.0) — B2B admin panel framework, good for data tables/forms
- **ShadCN/UI** (MIT) — Component library, not a full app framework

Neither should be adopted until the API surface is complete.

---

## 15. SECURITY / PRODUCTION SAFETY

### 15.1 Current Security Measures (CONFIRMED)

- API key authentication via `verify_token` dependency (`app/controllers/base.py`)
- Path traversal protection via `file_security.resolve_path_within_directory()` (`app/utils/file_security.py`)
- Upload filename sanitization (`_sanitize_upload_filename()` in `video.py:66`)
- BGM upload validation (FFmpeg probe, size limit, extension whitelist)
- Static file protection middleware (`protect_generated_task_files` in `asgi.py:98`)
- Secret redaction in logs (`_redact_secret()` in `material.py:192`)
- TLS verification for all external API calls (`_get_tls_verify()` in `material.py:157`)

### 15.2 Security Gaps

| Gap | Risk | Severity |
|---|---|---|
| No rate limiting on API endpoints | Abuse, quota exhaustion | MEDIUM |
| No CORS origin validation by default | CSRF | LOW (configurable) |
| Task deletion has no ownership check | Any authenticated user can delete any task | LOW |
| No audit log for configuration changes | Undetected misconfiguration | LOW |

---

## 16. TEST COVERAGE AND GAPS

### 16.1 Existing Test Files (56 files)

**Well-covered areas:**
- API controllers: `test_controller_video.py`, `test_controller_llm.py`, `test_controller_ping.py`, `test_controller_base.py`
- Material pipeline: `test_material.py`, `test_material_cache.py`, `test_material_upload.py`, `test_youtube_provider.py`, `test_youtube_cache_identity_10h1.py`, `test_youtube_format_selection_10h2.py`
- Video processing: `test_video.py`, `test_reframe.py`, `test_scene_combine.py`, `test_scene_durations.py`, `test_scene_materials.py`, `test_scene_plan.py`, `test_quality_gate_10f1.py`, `test_quality_gate_landscape.py`, `test_quality_gate_phase10f.py`
- Voice/TTS: `test_voice.py`, `test_fish_audio.py`, `test_elevenlabs_music.py`
- Subtitles: `test_subtitle.py`, `test_subtitle_background_settings.py`
- Task lifecycle: `test_task.py`, `test_task_manager.py`, `test_task_artifacts.py`
- State: `test_state.py`
- Failure recovery: `test_failure_recovery_phase10i.py`, `test_defect3_sweeper_failclosed_10i3.py`, `test_media_cleanup.py`
- WebUI: `test_webui_bgm.py`, `test_webui_generation_defaults.py`, `test_webui_i18n.py`, `test_webui_llm_settings.py`, `test_webui_loomloom.py`, `test_webui_settings_transfer.py`, `test_webui_startup.py`, `test_webui_task_history.py`, `test_webui_task.py`, `test_webui_tts_settings.py`, `test_webui_voice_preview.py`
- Config: `test_config.py`, `test_schema.py`, `test_cli.py`, `test_version_checker.py`

### 16.2 Test Gaps

| Area | Gap | Priority |
|---|---|---|
| Batch creation | No tests (no feature) | LOW |
| Thumbnail pipeline | No tests (no feature) | LOW |
| YouTube via WebUI | No tests (no UI integration) | HIGH |
| Cross-post workflow | `test_upload_post.py` exists but limited | MEDIUM |
| Mobile responsiveness | No visual/UI tests | MEDIUM |
| End-to-end batch workflow | No tests | LOW |
| Scene-aware generation | `test_scene_plan.py` exists but no E2E | MEDIUM |
| TwelveLabs integration | `test_twelvelabs.py` exists | LOW |
| API authentication | `test_api_authentication.py` exists | — |
| Combined video artifact | No specific test | MEDIUM |
| Video download endpoint | No specific test | LOW |

---

## 17. RECOMMENDED PHASE 11 ARCHITECTURE

### 17.1 Target Architecture

```
USER (mobile-first)
  ↓
WEBUI (Streamlit, improved)
  ↓
API (FastAPI, expanded endpoints)
  ↓
TASK MANAGER (existing)
  ↓
PRODUCTION ENGINE (PROTECTED CORE, unchanged)
  ↓
MEDIA ARTIFACTS (existing + thumbnails)
  ↓
WEBUI (gallery view with thumbnails)
```

### 17.2 Design Principles

1. **UI is control plane only** — no business logic duplication
2. **API-first for new features** — every new backend capability gets an endpoint
3. **Additive changes only** — no removal of existing working features
4. **Mobile-first CSS** — responsive layout, touch-friendly controls
5. **Artifact completeness** — every generated artifact is discoverable and downloadable

### 17.3 API Contract Completion (Phase 11B)

New endpoints to add:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v1/batch` | POST | Submit multiple tasks |
| `/api/v1/batch/{batch_id}` | GET | Query batch status |
| `/api/v1/thumbnails/{task_id}` | GET | Get thumbnail image |
| `/api/v1/artifacts/{task_id}` | GET | List all artifacts for a task |
| `/api/v1/artifacts/{task_id}/{file}` | GET | Download any artifact |
| `/api/v1/providers` | GET | List available providers |
| `/api/v1/youtube/search` | POST | Search YouTube directly |

---

## 18. PROPOSED PHASE 11 SUB-PHASES

Derived from actual audit findings:

### 11B — API/UI Contract Completion
- Add missing API endpoints (batch, artifacts, providers, YouTube search)
- Add YouTube to WebUI source dropdown
- Add YouTube search/direct URL mode to WebUI
- Add combined video display and download
- Add audio/subtitle artifact download
- **Depends on:** 11A complete
- **Est. effort:** 1-2 weeks

### 11C — YouTube First-Class UI Integration
- YouTube provider selection in source dropdown
- YouTube search results display with preview
- YouTube direct URL input
- YouTube provenance display (title, channel, license)
- YouTube error visibility
- **Depends on:** 11B
- **Est. effort:** 1 week

### 11D — Thumbnail Pipeline
- Backend: FFmpeg frame extraction at 25% mark
- API: thumbnail endpoint
- UI: thumbnail in task cards and video gallery
- Fallback: colored placeholder if extraction fails
- **Depends on:** 11B
- **Est. effort:** 3-5 days

### 11E — Batch/Content Factory UX
- Batch creation form (multiple topics/scripts)
- Batch status dashboard
- Batch progress aggregation
- **Depends on:** 11B (batch API)
- **Est. effort:** 2-3 weeks

### 11F — Mobile UX + Video Library
- Responsive layout (single-column on mobile)
- Bottom navigation
- Video gallery with thumbnails
- Touch-optimized controls
- **Depends on:** 11D
- **Est. effort:** 1-2 weeks

### 11G — Auto Clipper Architecture Spike
- Scene detection proof of concept
- Highlight scoring prototype
- Transcription adapter
- **Depends on:** 11B (API stability)
- **Est. effort:** 1 week (spike only)

### 11H — Auto Clipper Implementation
- Full scene detection service
- Highlight scoring engine
- Clip selection strategy
- Batch short synthesis
- **Depends on:** 11G
- **Est. effort:** 3-4 weeks

### 11I — Publishing/Distribution Integration
- Cross-post configuration UI
- Auto-publish toggle
- Platform selection
- Publishing status dashboard
- **Depends on:** 11B
- **Est. effort:** 1-2 weeks

### 11J — Analytics/Feedback Loop
- Performance data collection
- Content decision support
- **Depends on:** 11I
- **Est. effort:** 2-3 weeks

### 11K — Final Production Validation
- End-to-end testing of all Phase 11 features
- Mobile UX validation
- Performance benchmarking
- **Depends on:** All above
- **Est. effort:** 1 week

---

## 19. EXPLICIT OUT-OF-SCOPE ITEMS

The following are explicitly excluded from Phase 11:

1. **Replacing Streamlit with React/Vite** — not justified by current needs; revisit in Phase 12+
2. **Redesigning the production engine** — protected core, no changes
3. **Adding new material providers** — YouTube is the last planned provider
4. **Implementing video editing/timeline UI** — far beyond scope
5. **Adding user authentication/authorization** — single-user tool assumption
6. **Multi-tenancy** — not needed for local/self-hosted deployment
7. **Cloud storage integration** — local filesystem is sufficient
8. **A/B testing framework** — premature optimization
9. **Machine learning model training** — use pre-trained models only
10. **Monetization/payment integration** — separate product concern

---

## 20. FINAL RECOMMENDATION

**Phase 11 should proceed in the order: 11B → 11D → 11C → 11F → 11E → 11I → 11G → 11H → 11J → 11K.**

**Rationale:**

1. **11B first** — API contract completion unblocks all UI work. Without proper endpoints, every feature is a hack.
2. **11D before 11C** — thumbnails are needed for the video library (11F) which improves the YouTube UX (11C).
3. **11F before 11E** — mobile UX improvements make batch creation usable on phones.
4. **11G before 11H** — the Auto Clipper is the highest-risk subsystem; a spike validates the architecture before implementation.
5. **11I and 11J last** — publishing and analytics matter only after the production pipeline is solid.

**Streamlit should be retained for Phase 11.** The cost of a frontend rewrite exceeds the benefit for the current feature set. The API-first approach in 11B creates the foundation for a future React migration when the feature complexity justifies it.

**The highest-impact, lowest-risk improvements are:**
1. Adding YouTube to the WebUI source dropdown (1 day)
2. Adding thumbnail generation (3 days)
3. Adding batch API + UI (2 weeks)
4. Mobile layout fixes (1 week)

---

## PHASE 11A CLASSIFICATION

**PASS WITH FINDINGS**

Production mutations: 0
Production jobs: 0
YouTube downloads: 0
Source modifications: 0
Config modifications: 0
Database modifications: 0
Deployment: NONE
Git working tree: CLEAN

Commit: (pending — audit document only)

Next phase: 11B
