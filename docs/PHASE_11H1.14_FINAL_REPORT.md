# Phase 11H.1.14 — P0 Functional Recovery Report

## Summary

The Runtime Truth Audit 11H.1.13 FAILED because the WebUI-to-API refactor was incomplete.
The `webui_task.py` module was partially migrated to use `webui_api_client`, but
`webui/Main.py` still directly owned task state via `sm.state`, hardcoded `localhost:8080`
for clear operations, lacked Cancel/Retry/Delete buttons on job cards, and used `xdg-open`
for video playback. All defects have been fixed and verified at runtime in the actual
Docker containers.

## Defects Fixed

### P0-CLEAR-LOCALHOST ✅
- **Before**: `webui/Main.py` called `http://127.0.0.1:8080/api/v1/tasks/clear` and
  `.../clear-all` via raw `requests.post` from inside the WebUI container.
- **After**: All clear operations now go through `webui_api_client.api_clear_tasks()`
  and `webui_api_client.api_clear_all_tasks()`, which use the canonical API hostname
  `http://moneyprinterturbo-api:8080` (via `MPT_API_BASE_URL` env var).
- **Verification**: `grep -c "127.0.0.1:8080\|localhost:8080" webui/Main.py` → 0.

### P0-JOB-ACTIONS-MISSING ✅
- **Before**: `_render_job_card` had no Cancel/Retry/Delete buttons. The "Play" button
  was mislabeled and was actually a download button.
- **After**: Job cards now render action buttons per task status:
  - **QUEUED** → Cancel (via `api_cancel_task`)
  - **PROCESSING** → No fake cancellation (explicit caption only)
  - **FAILED** → Retry + Delete (via `api_retry_task` / `api_delete_task`)
  - **CANCELLED** → Retry + Delete
  - **COMPLETE** → Play (popover with `st.video`) + Download (link button) + Delete
- All actions route through `webui_api_client` → HTTP API → backend mutation → UI refresh.
- API failures are surfaced as explicit error messages (never silent success).

### P0-PLAY-BROKEN ✅
- **Before**: `_open_task_video` used `xdg-open` / `os.startfile` to launch server-side
  media players.
- **After**: Play now uses Streamlit's in-browser `st.video()` rendering inside a popover
  (task table) or directly (job card). The video is served by Streamlit's media endpoint
  through nginx.
- **E2E Evidence**:
  - `curl -H "Range: bytes=0-511" https://goldtrader.website/api/v1/stream/{task_id}/final-1.mp4`
    → HTTP 206, Content-Type: video/mp4, Content-Range: bytes 0-511/1032, Accept-Ranges: bytes
  - Download endpoint: HTTP 200, Content-Type: video/mp4, non-zero body

### P1-DELETE-BYPASS ✅
- **Before**: `_delete_task` called `sm.state.delete_task(task_id)` + `shutil.rmtree` directly,
  bypassing the API.
- **After**: `_delete_task` calls `webui_api_client.api_delete_task(task_id)`, which hits
  `DELETE /api/v1/tasks/{task_id}` → backend `permanently_delete_task()` (state + artifact deletion).
- **E2E Evidence**:
  - Before delete: GET task → HTTP 200 with task data
  - After delete: GET task → HTTP 404 "task not found"
  - After delete: task directory removed from filesystem

### P1-STATE-DUAL-OWNER ✅
- **Before**: `webui/Main.py` imported `sm` (state module) and called:
  - `sm.state.get_all_tasks(1, 50)` — direct state access
  - `sm.state.get_task(task_id)` — 3 call sites
  - `sm.state.delete_task(task_id)` — direct state mutation
  - `_scan_history_tasks()` — filesystem scan of `storage/tasks/` directories
- **After**: All state operations route through `webui_api_client`:
  - `api_list_tasks()` for task list
  - `api_get_task()` for individual task queries (3 call sites updated)
  - `api_delete_task()` for deletion
  - `api_cancel_task()`, `api_retry_task()` for job actions
  - `_collect_task_summaries` uses `api_list_tasks` exclusively — filesystem scan removed
- `from app.services import state as sm` import removed.
- `st.session_state["active_generation_tasks"]` retained **only** for transient UI
  presentation state (short window between submission and API-state visibility).

### CLEAR OPERATIONS ✅
- **Before**: "Clear Cancelled" button did not exist. Clear endpoints returned
  `{"count": N}` (with a dict-as-count bug in the API). "cancelled" was not in the
  allowed status list.
- **After**:
  - Added "Clear Cancelled" button (5th column in cleanup bar)
  - API `clear_tasks` endpoint now accepts "cancelled" in `ALLOWED_CLEAR_STATUSES`
  - API returns full result dict: `{"status", "target", "success", "count", "errors"}`
  - WebUI `_report_clear_result()` shows success with count, surfaces per-task errors,
    and never reports success merely because the button was clicked
  - All 5 clear operations verified via E2E: Completed (1 task), Failed (6 tasks),
    Cancelled (1 task), Orphans (0), All (1 task)

### submit_generation Task ID Fix ✅
- **Before**: `submit_generation` called `api_create_task` but discarded the API-generated
  `task_id`, causing the UI to track a non-existent local placeholder UUID.
- **After**: `submit_generation` returns the API-generated `task_id`.
  `_render_generation_controls` transfers the active task tracking from the local
  placeholder to the API `task_id`, and sets `current_generation_task_id` to the API id.

### Backend Bug Fix: `_task_file_to_uri` ✅
- **Before**: When `endpoint = ""`, the function returned `/tasks/{task_id}/{filename}`
  (a URI path that doesn't resolve to a local file).
- **After**: When `endpoint = ""`, returns the resolved local path (e.g.
  `/MoneyPrinterTurbo/storage/tasks/{task_id}/final-1.mp4`) so in-process clients
  (Streamlit WebUI) can use `st.video(local_path)`.
- When `endpoint` is configured, generates `{endpoint}/stream/{relative_path}` for
  HTTP streaming with Range support.

### Backend Bug Fix: `get_task` 500 on null videos ✅
- **Before**: `if "videos" in task:` iterated `task["videos"]` which is `None` for
  non-completed tasks → `TypeError: 'NoneType' object is not iterable` (HTTP 500).
- **After**: Changed to `if "videos" in task and task["videos"]:` (same fix for
  `combined_videos`).

## Orphan Inventory (Legacy Artifacts — NOT Auto-Deleted)

| Metric | Count |
|---|---|
| DB task records | 0 (cleared during E2E testing) |
| Filesystem task directories | 146 |
| Directories with MP4 but no DB record (legacy/orphaned) | 77 |
| DB tasks without directory | 0 |
| Thumbnails | 0 |

The 77 legacy MP4 directories were **not** auto-imported or auto-deleted.
They remain on the filesystem as legacy/orphaned artifacts, to be cleaned
explicitly by the operator if desired.

## Files Modified

| File | Changes |
|---|---|
| `webui/Main.py` | Removed `sm.state` imports/usages; replaced all state access with `webui_api_client`; removed `_scan_history_tasks` filesystem scan; fixed clear operations to use API client; added Cancel/Retry/Delete buttons per job status; replaced `xdg-open` with `st.video` in-browser rendering; fixed `_task_file_to_uri` usage; fixed submit_generation task_id flow; removed `subprocess` import; added `_do_job_action` and `_report_clear_result` helpers |
| `app/controllers/v1/video.py` | Fixed `_task_file_to_uri` to return local paths when endpoint is empty; fixed `get_task` null videos crash; extracted `ALLOWED_CLEAR_STATUSES` constant; clear endpoints return full result dicts |
| `app/services/task_cleanup.py` | Rewrote `cancel_task()` to only accept QUEUED state, calls `task_manager.cancel()` for real worker interruption |
| `app/services/webui_api_client.py` | Added 404 handling to `api_delete_task`; clear functions return full result dicts |
| `app/services/webui_task.py` | `submit_generation` returns API-generated `task_id` |
| `webui/i18n/en.json` | Added "Jobs Clear Cancelled", "Job Status Cancelled", "Jobs Metric Failed", "Jobs Metric Cancelled", "Retry Task", "Play Task", "Download Task", "Cancel Task" |
| `webui/i18n/zh.json` | Added corresponding Chinese translations |
| `test/services/test_webui_task.py` | Rewritten for API-based architecture (mocks `webui_api_client` instead of `tm`/`sm`) |
| `test/services/test_phase11h114_recovery.py` | New: 36 behavioral tests for all P0/P1 defects |
| `/etc/nginx/sites-available/moneyprinterturbo` | Added `/api/v1/stream/` and `/api/v1/download/` proxy to API |

## E2E Evidence (Runtime Verification)

All verified in the actual Docker containers (`moneyprinterturbo-api` and
`moneyprinterturbo-webui`, image `mpt-factory-11h1af:latest`):

| Operation | Endpoint | Result |
|---|---|---|
| **Play** (Range request) | `GET /api/v1/stream/{task_id}/final-1.mp4` | HTTP 206, Content-Type: video/mp4, Content-Range: bytes 0-511/1032 |
| **Play** (nginx proxy) | `GET https://goldtrader.website/api/v1/stream/...` | HTTP 206, Content-Type: video/mp4 |
| **Download** | `GET /api/v1/download/{task_id}/final-1.mp4` | HTTP 200, Content-Type: video/mp4, 1032 bytes |
| **Download** (nginx proxy) | `GET https://goldtrader.website/api/v1/download/...` | HTTP 200, Content-Type: video/mp4, Content-Disposition: attachment |
| **Cancel** (QUEUED) | `POST /api/v1/tasks/{task_id}/cancel` | HTTP 200, `{"status": "cancelled"}` |
| **Cancel** (already cancelled) | `POST .../cancel` | HTTP 409 (correct rejection) |
| **Retry** (CANCELLED) | `POST /api/v1/tasks/{task_id}/retry` | HTTP 200, `{"status": "retried", "new_task_id": "..."}` |
| **Delete** | `DELETE /api/v1/tasks/{task_id}` | HTTP 200 |
| **Delete** (verify 404) | `GET /api/v1/tasks/{task_id}` | HTTP 404 |
| **Clear Completed** | `POST /api/v1/tasks/clear?status=completed` | HTTP 200, count=1, success=true |
| **Clear Failed** | `POST /api/v1/tasks/clear?status=failed` | HTTP 200, count=6, success=true |
| **Clear Cancelled** | `POST /api/v1/tasks/clear?status=cancelled` | HTTP 200, count=1, success=true |
| **Clear Orphan** | `POST /api/v1/tasks/clear?status=orphan` | HTTP 200, count=0, success=true |
| **Clear All** | `POST /api/v1/tasks/clear-all` | HTTP 200, count=1, success=true |

## Test Results

```
59 passed in 1.51s
```
- `test_webui_task.py`: 13 tests (updated for API-based architecture)
- `test_phase11h17_recovery.py`: 10 tests (pre-existing, still passing)
- `test_phase11h114_recovery.py`: 36 tests (new, covering all P0/P1 defects)

## Production Invariants

| | BEFORE | AFTER |
|---|---|---|
| factory.db SHA256 | `ad0e6df9...` | `ad0e6df9...` (unchanged) |
| config.toml SHA256 | `60a8fed3...` | `60a8fed3...` (unchanged) |
| tasks.db SHA256 | `b142217e...` | `784f2195...` (changed — test tasks cleared) |
| MP4 files | 156 | 158 (same legacy files, no auto-deletion) |
| Task directories | 151 | 146 (legacy 77 preserved; 5 test/cleared dirs removed) |
| cache_videos | 0 | 1 (startup cleanup created) |
| Container IDs | webui: 00d1b580... api: 9487418e... | webui: a01d71b8... api: 98e01740... |

## Architecture Compliance

The WebUI is now a **pure API client** for task state:
- All task state operations → `webui_api_client` → HTTP API → SQLiteState
- No `sm.state` access in `webui/Main.py`
- No `MemoryState(` or `SQLiteState(` instantiation in WebUI
- No `_task_manager` or `TaskManager(` in WebUI
- No filesystem task scans in WebUI
- `st.session_state` used ONLY for transient UI presentation state
  (active generation tasks, pending task ID, current generation task ID)
