# PHASE 11C — YOUTUBE FIRST-CLASS UI INTEGRATION

**Status:** PASS
**Date:** 2026-08-28
**Baseline commit:** b3b1d3c (Phase 11B)

---

## 1. OBJECTIVE

Make YouTube a first-class material source in the existing Streamlit WebUI. A normal user must be able to open the WebUI, select YouTube, enter a search, submit generation, understand what is happening, and retrieve the resulting video.

---

## 2. BASELINE

- Phase 11B commit: b3b1d3c
- Phase 11A commit: 95b39b5
- Working tree: clean
- Production invariants: factory.db, config.toml, storage/ — all unchanged

---

## 3. EXISTING UI FLOW

The WebUI renders four columns in `_render_application()`:
1. **Left panel** (`_render_script_settings`): Subject, language, script, keyword generation, keywords text area
2. **Middle panel** (`_render_video_settings`): Source selector, concat mode, transitions, aspect, clip settings, codec
3. **Audio panel** (`_render_audio_settings`): Voice mode, TTS provider, voice, BGM
4. **Right panel** (`_render_subtitle_settings`): Subtitle controls

**Generation flow:** Form → validation (`_render_generation_controls`) → `webui_task.submit_generation()` → background thread → state updates → progress polling → result display

**Key state:** `params.video_source` is set in `_render_video_settings`, `params.video_terms` is set in `_render_script_settings`. The `video_terms` field IS the YouTube search query.

---

## 4. YOUTUBE UI CHANGES

### 4.1 Source Dropdown (unchanged from 11B)
YouTube appears between Coverr and WaveSpeed in the source selector.

### 4.2 Dynamic Keywords Label
When YouTube is selected (detected from `config.app["video_source"]`), the "Video Keywords" label changes to "YouTube Search Terms" with YouTube-specific help text.

### 4.3 YouTube Help Caption
When YouTube is selected, shows: "Searches YouTube for footage. Videos are quality-checked and reframed for the selected output aspect."

### 4.4 YouTube Validation
Before task creation: if YouTube is selected and both keywords and script are empty, shows "Please enter a YouTube search term or generate keywords from the script."

### 4.5 YouTube Progress Descriptions
During generation:
- < 30% progress: "Searching YouTube for footage..."
- 30-60% progress: "Downloading YouTube footage..."
- > 60% progress: "Checking footage quality..."

### 4.6 YouTube Error Messages
Translated failure patterns:
- "No suitable YouTube footage was found..."
- "The selected YouTube footage did not meet the quality requirements."
- "YouTube footage could not be downloaded..."

### 4.7 i18n
Added 10 new keys to `en.json` and `zh.json`. Other locales fall back to English.

---

## 5. API CONTRACT USED

| Endpoint | Method | Used For |
|---|---|---|
| `/api/v1/videos` | POST | Task creation (`video_source="youtube"`) |
| `/api/v1/tasks/{task_id}` | GET | Status polling (progress + failed_stage) |
| `/api/v1/stream/{file_path}` | GET | Video preview |
| `/api/v1/download/{file_path}` | GET | Video download |

No new API endpoints. All existing contracts preserved.

---

## 6. SEARCH/DIRECT URL CAPABILITY

**YouTube Search:** SUPPORTED — The `video_terms` field maps to `search_terms` in `download_videos()`, which calls `search_videos_youtube()` using `ytsearch:` prefix.

**Direct YouTube URL:** **NOT SUPPORTED — API CONTRACT GAP**

The existing `download_videos()` function only accepts `search_terms` (list of strings), not URLs. Direct URL support would require:
1. New API parameter in `VideoParams`
2. New backend handler that resolves a URL to a search or download
3. New UI input field

**Recommendation:** Implement in Phase 11E or later when adding batch/advanced material input.

---

## 7. VALIDATION

| Validation | Message | Phase |
|---|---|---|
| Empty YouTube query + no script | "Please enter a YouTube search term or generate keywords from the script." | 11C |
| Invalid source selection | "Please select a valid video source." | Existing |
| Missing Pexels API key | "Please enter the Pexels API Key." | Existing |
| Missing local materials | "Please upload at least one local material file first." | Existing |

---

## 8. TASK LIFECYCLE UX

| State | Display | YouTube-Specific |
|---|---|---|
| QUEUED | "Generating video, please wait..." | — |
| PROCESSING (< 30%) | Progress bar + "Searching YouTube for footage..." | Yes |
| PROCESSING (30-60%) | Progress bar + "Downloading YouTube footage..." | Yes |
| PROCESSING (> 60%) | Progress bar + "Checking footage quality..." | Yes |
| COMPLETE | "Video Generation Completed" + video player + download | — |
| FAILED | Translated YouTube error message | Yes |

---

## 9. FAILURE UX

YouTube failures are translated from backend error patterns:

| Backend Pattern | User Message |
|---|---|
| "no results found" | "No suitable YouTube footage was found for the search terms." |
| "quality"/"resolution" | "The selected YouTube footage did not meet the quality requirements." |
| "download"/"403" | "YouTube footage could not be downloaded. The video may be unavailable." |
| Other | "Video Generation Failed" (generic, with technical details in logs) |

Technical details are preserved in the task log, not shown as primary message.

---

## 10. MOBILE BEHAVIOR

- Source selector uses the same `selectbox` as other sources — no layout change
- YouTube keywords input uses the same text area — no new controls
- Progress captions are short and don't cause overflow
- No horizontal overflow introduced
- Task status display unchanged

---

## 11. TESTS

### New Tests: `test/services/test_phase11c_youtube_ux.py` (9 tests)

| Test | Purpose | Result |
|---|---|---|
| `test_youtube_search_terms_map_to_download_videos` | Keywords map to YouTube search | PASS |
| `test_youtube_empty_search_terms_returns_empty` | Empty terms don't crash | PASS |
| `test_youtube_task_failure_has_meaningful_error` | YouTube failures are handled | PASS |
| `test_youtube_failure_includes_stage_information` | Failed stage is captured | PASS |
| `test_youtube_is_valid_source_value` | YouTube in valid sources | PASS |
| `test_youtube_maps_to_search_function` | Provider/searcher correct | PASS |
| `test_pexels_download_still_works` | Pexels unchanged | PASS |
| `test_pixabay_download_still_works` | Pixabay unchanged | PASS |
| `test_coverr_download_still_works` | Coverr unchanged | PASS |

### Regression Tests

| Test Suite | Result | Notes |
|---|---|---|
| `test_phase11b_youtube_contract.py` | 9 passed | Phase 11B tests |
| `test_webui_task.py` | All pass | WebUI generation flow |
| `test_webui_task_history.py` | All pass | Task history |
| `test_youtube_provider.py` | All pass | YouTube backend |
| `test_controller_video.py` | All pass | API contract |
| `test_task.py` | All pass | Pipeline execution |
| `test_task_artifacts.py` | All pass | Artifact persistence |

**Total: 121 passed, 0 regressions**

---

## 12. REGRESSION RESULTS

| Category | Count | Details |
|---|---|---|
| PASS | 121 | All targeted tests pass |
| CURRENT REGRESSION | 0 | No new failures introduced |
| PRE-EXISTING | 22 | `test_webui_bgm.py` and `test_webui_generation_defaults.py` — fail on baseline |
| SKIPPED | 3 | Platform-specific tests |

The 22 pre-existing failures are in BGM settings and generation defaults tests. They fail on the baseline commit (b3b1d3c) and are unrelated to YouTube integration.

---

## 13. PRODUCTION SAFETY

- factory.db: unchanged
- config.toml: unchanged
- production task count: unchanged
- production MP4 count: unchanged
- cache_videos: unchanged
- production jobs: 0
- production YouTube downloads: 0
- production E2E: 0
- Docker production deployment: NONE

---

## 14. REMAINING LIMITATIONS

| Limitation | Reason | Target Phase |
|---|---|---|
| Direct YouTube URL input | API contract gap | 11E or later |
| YouTube search results preview | Requires search-only API endpoint | 11E |
| YouTube cookies file configuration | Not exposed in settings UI | 11F |
| Multi-provider fallback | UI only allows single source | 11C (documented) |
| Thumbnail generation | No backend support | 11D |
| Batch task creation | No backend support | 11E |

---

## 15. GIT COMMIT

```
feat(ui): make youtube a first-class material source

- Dynamic "YouTube Search Terms" label when YouTube selected
- YouTube help caption and search hints
- Empty query validation for YouTube
- YouTube progress descriptions (search/download/quality)
- YouTube-specific error message translation
- i18n: 10 new keys in en.json + zh.json

Phase 11C: YouTube first-class UI integration
```

Working tree: clean

---

## 16. RECOMMENDATION FOR PHASE 11D

Proceed with **Phase 11D — Thumbnail Pipeline**:

1. Backend: FFmpeg frame extraction at 25% mark from final video
2. API: thumbnail endpoint
3. UI: thumbnail in task cards and video gallery
4. Fallback: colored placeholder if extraction fails

Phase 11D depends on: 11C complete ✓

---

## PHASE 11C CLASSIFICATION

**PASS**

Production mutations: 0
Production jobs: 0
YouTube downloads: 0
Source modifications: 3 files (Main.py, en.json, zh.json)
Config modifications: 0
Database modifications: 0
Deployment: NONE
Git working tree: CLEAN

Commit: (see git log)

Next phase: 11D
