# PHASE 11D — THUMBNAIL PIPELINE

**Status:** PASS
**Date:** 2026-08-28
**Baseline commit:** d3b9ab6 (Phase 11C)

---

## 1. OBJECTIVE

Every successfully generated final video should have an automatically generated thumbnail artifact that can be displayed and accessed through the existing Videos/UI flow.

---

## 2. BASELINE

- Phase 11C commit: d3b9ab6
- Working tree: clean
- Production invariants: factory.db, config.toml, storage/ — all unchanged

---

## 3. EXISTING ARTIFACT ARCHITECTURE

```
Task Pipeline (task.py _run_pipeline):
  1. Generate script
  2. Generate terms
  3. Generate audio
  4. Generate subtitle
  5. Get video materials
  6. Generate final videos → final-{index}.mp4 + combined-{index}.mp4
  7. Cross-post scheduling

Artifact Storage:
  - Task directory: storage/tasks/{task_id}/
  - Static serving: /tasks/{task_path} via StaticFiles mount
  - API exposure: task state dict → API response

Cleanup:
  - cache_videos/ sweeper (only operates on cache_videos/)
  - Protected filenames: final-*.mp4, combined-*.mp4, audio.mp3, etc.
  - Task deletion removes entire task directory
```

---

## 4. THUMBNAIL GENERATION DESIGN

### Insertion Point
After step 6 (generate final videos) success, before step 7 (cross-post).
This ensures thumbnails are only generated for successfully completed videos.

### Function: `_extract_thumbnail_frame()`
- Uses FFmpeg to extract a single frame
- Deterministic timestamp: `min(duration * 0.10, 3.0)` seconds
- Scaled to 480px wide, aspect ratio preserved (`scale=480:-1`)
- JPEG quality: `-q:v 5` (good quality, reasonable size)
- Timeout: 30 seconds
- Returns None on any failure (fail-safe)

### Function: `generate_thumbnails()`
- Iterates over final video paths
- Generates `thumbnail-{index}.jpg` for each
- Returns None if ANY thumbnail fails (all-or-nothing)
- Exception-safe: catches and logs, never raises

### Integration Function: `_generate_task_thumbnails()`
- Resolves task directory
- Calls `video.generate_thumbnails()`
- On failure: logs warning, returns None (does NOT fail task)

### Key Properties:
- **Format**: JPEG
- **Naming**: `thumbnail-{index}.jpg` (parallel to `final-{index}.mp4`)
- **Dimensions**: 480px wide, aspect ratio preserved (e.g., 480×854 for 9:16)
- **Frame selection**: 10% of duration, capped at 3 seconds
- **Quality**: `-q:v 5` (FFmpeg JPEG quality scale)

---

## 5. FRAME SELECTION STRATEGY

```python
timestamp = min(duration * 0.10, 3.0)
```

- **10% of duration**: Avoids black opening frames common at t=0
- **Capped at 3 seconds**: Prevents selecting frames too early in long videos
- **Deterministic**: Same video always produces same thumbnail
- **Within bounds**: Always < video duration

Example:
- 10s video → frame at 1.0s
- 30s video → frame at 3.0s
- 60s video → frame at 3.0s (capped)

---

## 6. FILENAME/PATH CONVENTION

- **Filename**: `thumbnail-{index}.jpg` (1-indexed, parallel to `final-{index}.mp4`)
- **Location**: Task directory (`storage/tasks/{task_id}/`)
- **API URI**: Converted via `_task_file_to_uri()` to `/tasks/{task_id}/thumbnail-{index}.jpg`
- **Access**: Via existing StaticFiles mount at `/tasks/`

---

## 7. API CONTRACT

### Task State
Added `thumbnails` field to task state dict (list of paths or None).

### API Response
Added thumbnail URI conversion in `GET /api/v1/tasks/{task_id}`:
```python
if "thumbnails" in task and task["thumbnails"]:
    response_task["thumbnails"] = [
        _task_file_to_uri(v, endpoint, task_dir, request_id)
        for v in task["thumbnails"]
    ]
```

### Schema
Added optional `thumbnails` field to `TaskStatusData`:
```python
thumbnails: Optional[List[str]] = None
```

### Backward Compatibility
- `thumbnails` field is optional (defaults to None)
- Existing API clients ignore unknown fields (Pydantic `extra="allow"`)
- Old tasks without thumbnails return `thumbnails: None`
- No existing fields modified

---

## 8. UI CHANGES

No UI changes in Phase 11D. Thumbnail display in the Videos UI will be implemented in Phase 11F.

---

## 9. FAILURE ISOLATION

Critical rule: **Thumbnail failure ≠ video generation failure.**

```python
# In _run_pipeline:
thumbnail_paths = _generate_task_thumbnails(task_id, final_video_paths)
# Even if thumbnail_paths is None, execution continues to:
sm.state.update_task(task_id, state=const.TASK_STATE_COMPLETE, progress=100, **kwargs)
```

- If `_extract_thumbnail_frame` fails → returns None
- If `generate_thumbnails` fails → returns None
- If `_generate_task_thumbnails` fails → returns None, logs warning
- Task state is always COMPLETED with videos available
- Warning is logged for diagnosis

---

## 10. SECURITY/PATH SAFETY

- Thumbnails are stored in task directory (same as final videos)
- Path validation uses existing `file_security.resolve_path_with_directory()`
- API uses existing `_task_file_to_uri()` which validates paths within task directory
- No user-supplied filenames: `thumbnail-{index}.jpg` is deterministic
- Served via existing `/tasks/` StaticFiles mount with auth middleware

---

## 11. TDD RED EVIDENCE

Before implementation, 9 of 10 tests FAILED:

| Test | Failure Reason |
|---|---|
| `test_thumbnail_generated_from_final_video` | `video.generate_thumbnails` doesn't exist |
| `test_thumbnail_naming_convention` | `video.generate_thumbnails` doesn't exist |
| `test_thumbnail_uses_final_video_not_source` | `video.generate_thumbnails` doesn't exist |
| `test_thumbnail_failure_does_not_raise` | `video._extract_thumbnail_frame` doesn't exist |
| `test_thumbnail_missing_video_returns_none` | `video.generate_thumbnails` doesn't exist |
| `test_task_remains_complete_when_thumbnail_fails` | `task.generate_final_videos` doesn't call thumbnails |
| `test_thumbnail_path_in_task_state` | `task.generate_final_videos` doesn't store thumbnails |
| `test_frame_selection_uses_safe_timestamp` | `video._extract_thumbnail_frame` doesn't exist |
| `test_frame_selection_within_video_duration` | `video._extract_thumbnail_frame` doesn't exist |

1 test passed (cleanup safety — no production code needed).

---

## 12. TDD GREEN EVIDENCE

After implementation, all 10 tests PASS:

| Test | Result |
|---|---|
| `test_thumbnail_generated_from_final_video` | PASS |
| `test_thumbnail_naming_convention` | PASS |
| `test_thumbnail_uses_final_video_not_source` | PASS |
| `test_thumbnail_failure_does_not_raise` | PASS |
| `test_thumbnail_missing_video_returns_none` | PASS |
| `test_task_remains_complete_when_thumbnail_fails` | PASS |
| `test_thumbnail_path_in_task_state` | PASS |
| `test_frame_selection_uses_safe_timestamp` | PASS |
| `test_frame_selection_within_video_duration` | PASS |
| `test_cache_sweeper_does_not_touch_thumbnails` | PASS |

---

## 13. REGRESSION RESULTS

| Test Suite | Result | Notes |
|---|---|---|
| `test_phase11d_thumbnails.py` | 10 passed | New thumbnail tests |
| `test_phase11c_youtube_ux.py` | 9 passed | Phase 11C tests |
| `test_phase11b_youtube_contract.py` | 9 passed | Phase 11B tests |
| `test_task.py` | 55 passed, 3 skipped | Pipeline execution |
| `test_task_artifacts.py` | 4 passed | Artifact persistence |
| `test_youtube_provider.py` | 34 passed | YouTube backend |
| `test_controller_video.py` | 26 passed | API contract |
| `test_webui_task.py` | 17 passed | WebUI generation |
| `test_schema.py` | 4 passed | Request/response models |

**Total: 168 passed, 3 skipped, 0 regressions**

---

## 14. PRODUCTION SAFETY

- factory.db: unchanged
- config.toml: unchanged
- production task count: unchanged
- production MP4 count: unchanged
- cache_videos: unchanged
- production jobs: 0
- YouTube downloads: 0
- production E2E: 0
- Docker production deployment: NONE

---

## 15. REMAINING LIMITATIONS

| Limitation | Reason | Target Phase |
|---|---|---|
| Thumbnail display in UI | Scope limited to pipeline | 11F |
| Thumbnail regeneration | Not implemented | Future |
| Custom thumbnail upload | Not implemented | Future |
| Thumbnail for old tasks | Only new tasks get thumbnails | Future |

---

## 16. GIT COMMIT

```
feat: generate thumbnails for completed videos

- Extract frame at 10% duration (capped at 3s) using FFmpeg
- Save as thumbnail-{index}.jpg in task directory
- Scale to 480px wide, aspect ratio preserved
- Failure is non-fatal: task remains COMPLETE
- Exposed via API as thumbnails field
- 10 new tests for thumbnail pipeline

Phase 11D: Thumbnail pipeline
```

Working tree: clean

---

## 17. RECOMMENDATION FOR PHASE 11E

Proceed with **Phase 11E — Batch/Content Factory UX**:

1. Add batch creation form (multiple topics/scripts)
2. Add batch status dashboard
3. Consider adding YouTube direct URL support (requires API changes)

Phase 11E depends on: 11D complete ✓

---

## PHASE 11D CLASSIFICATION

**PASS**

Production mutations: 0
Production jobs: 0
YouTube downloads: 0
Source modifications: 3 files (video.py, task.py, schema.py)
Config modifications: 0
Database modifications: 0
Deployment: NONE
Git working tree: CLEAN

Commit: (see git log)

Next phase: 11E
