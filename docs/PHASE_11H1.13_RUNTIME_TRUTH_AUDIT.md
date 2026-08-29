# PHASE 11H.1.13 — RUNTIME TRUTH AUDIT

**Status:** AUDIT ONLY. No source modified. No production data mutated (one disposable
probe row was inserted into and then deleted from the DB to prove the backend; it is gone).
**Date:** 2026-08-29
**Auditor:** runtime-truth pass (independent re-verification of prior "PASS" claims)

---

## 0. HEAD / REMOTE / RUNTIME IDENTITY (exact)

| Item | Value |
|---|---|
| Local `HEAD` | `d8231f2c3b0227acf012f4d8c58d474792926156` |
| `origin/main` | `d8231f2c3b0227acf012f4d8c58d474792926156` (matches `git ls-remote`) |
| Last reported "final" SHA in handoff | `d8231f2` / `cadec6e` — reconciled; both are ancestors, HEAD=origin |
| Canonical domain | `https://goldtrader.website` → nginx → `127.0.0.1:8501` |
| Canonical repo | `/root/moneyprinterturbo-video-factory` |
| Runtime storage (bind mount) | `/opt/MoneyPrinterTurbo/storage` (host) ↔ `/MoneyPrinterTurbo/storage` (container) |
| Runtime config (bind mount) | `/opt/MoneyPrinterTurbo/config.toml` |
| `config.toml` SHA256 | `60a8fed3…ff4cbda` |
| `tasks.db` SHA256 | `b142217e…35f673` |

### Running containers

| Container | Image | Ports | Role | Verdict |
|---|---|---|---|---|
| `moneyprinterturbo-webui` | `mpt-factory-11h1af:latest` | `0.0.0.0:8501→8501` | Canonical Streamlit UI | CANONICAL |
| `moneyprinterturbo-api` | `mpt-factory-11h1af:latest` | `127.0.0.1:8080→8080` | Canonical FastAPI engine | CANONICAL |
| `mpt-7b-9090` | `ghcr.io/harry0703/moneyprinterturbo:latest` | `0.0.0.1:8090→8080` | **Stale upstream GHCR image** | ORPHAN / NOT routed by nginx |

- nginx `goldtrader.website` → `proxy_pass http://127.0.0.1:8501` (the canonical WebUI). ✓ correct.
- nginx `factory.goldtrader.website` → `127.0.0.1:8000` (the legacy `/opt/mpt-factory`, a separate app — not in scope).
- `mpt-7b-9090` is **not** referenced by any nginx vhost; it is dead weight running a 5-day-old
  upstream image. Flagged INFO/P2 (handoff rule: do not run stale images).

---

## 1. ARCHITECTURE AS OBSERVED (not as documented)

```
Browser
  │  https://goldtrader.website
  ▼
nginx  (proxy_pass 127.0.0.1:8501)
  ▼
moneyprinterturbo-webui  (Streamlit :8501)         [container A]
  ├─ create task   ──HTTP──▶ moneyprinterturbo-api  (FastAPI :8080, docker DNS)   ✓ correct
  ├─ clear tasks    ──HTTP──▶ http://127.0.0.1:8080  ✗ BROKEN (localhost inside container)
  ├─ status polling ──DIRECT in-process SQLiteState (sm.state) + filesystem scan  ✗ bypasses API
  ├─ delete task    ──DIRECT in-process sm.state.delete_task + shutil.rmtree      ✗ bypasses API
  └─ play/download  ──Streamlit st.video / st.download_button reading shared bind mount
  ▼
moneyprinterturbo-api  (FastAPI :8080)              [container B]
  ├─ SQLiteState (tasks.db)  — SAME file opened by BOTH containers (dual owner)
  ├─ task_manager (worker)   — executes tasks
  └─ StaticFiles /tasks, /stream, /download  — NOT reachable from browser (8080 not exposed)
```

**Key truth:** The canonical UI and API are correctly wired for *create* (docker DNS), but the
UI maintains its **own** in-process state handle and a **filesystem scan** for completeness, while
the API also owns the same SQLite file. This is dual state ownership, in violation of the
"ONE canonical state source, WebUI goes through API" contract (see P1-STATE).

---

## 2. EVIDENCE — STATE vs FILESYSTEM DIVERGENCE (measured)

| Metric | Value | Source |
|---|---|---|
| Task rows in `tasks.db` | **5** (all `state=-1` FAILED) | `sqlite3 tasks.db` |
| Batch rows in `tasks.db` | **1** (`batch-test-001`, status `running`, references a failed task) | `sqlite3 tasks.db` |
| `storage/tasks/` directories | **151** | `ls /opt/MoneyPrinterTurbo/storage/tasks` |
| Directories containing `final-*.mp4` (completed videos) | **77** | scan |
| Thumbnail files (`thumbnail-*.jpg`) | **0** | `find` |
| MP4 files total (incl. intermediate `combined-`, temp clips) | 156+ | `find` |

**Interpretation:** 77 completed videos exist on disk but are **not** represented in the canonical
SQLite state (which holds only 5 failed test tasks). The WebUI renders them via a filesystem scan
(`_scan_history_tasks`, completeness = presence of `final-*.mp4`), so they *appear* in the library,
but the canonical state backend does not know about them. Any operation that keys off the DB
(e.g. Clear Completed, Clear Orphan) therefore cannot touch them.

The 5 DB tasks are previous-agent test artifacts: `subject="Test"`, `voice_name=""`,
`failed_stage="audio"` → `azure_tts_v1 failed, error: Invalid voice ''`. The engine runs; it fails
only because TTS voice config is empty. (INFO, not a code defect.)

---

## 3. PER-ACTION CHAIN MAP (UI element → handler → HTTP → endpoint → backend → state → fs → UI refresh)

### CREATE (Quick Create, single video)
- UI: `webui/Main.py` generation button → `_render_generation_controls`
- Handler: `webui_api_client.api_create_task` → `POST {MPT_API_BASE_URL}/api/v1/videos`
- Endpoint: `app/controllers/v1/video.py:create_task` → `sm.state.update_task(QUEUED)` + `task_manager.add_task`
- Verified: docker-DNS path returns 200 (connectivity test). The 5 failed tasks prove the
  submission→execution pipeline runs. **Works** (subject to TTS config).

### BATCH CREATE
- UI: batch form `video_source` selectbox (includes `youtube`), topics list → `api_create_task` per topic
- `MPT_API_BASE_URL` used. **Works** (same path as CREATE).

### BATCH VIEW / PERSISTENCE
- `save_batch` → `POST /api/v1/batches` → `sm.state.save_batch` (SQLite `batches` table).
- Verified: `batch-test-001` persists in DB across restarts (SQLite file on shared storage).
- Gap: the UI only re-displays the *current* batch from `st.session_state["current_batch_id"]`
  (+ `batch_topics`); there is **no browseable historical-batch list** in the UI even though
  `GET /api/v1/batches` exists. Batch survives refresh *only while the Streamlit session lives*.
  (P2 — partial contract compliance; batch metadata persists in backend, but UI retrieval is session-scoped.)

### PLAY (video library / jobs)
- **Video Library** (`_render_videos_view` → `_render_video_card`): **NO Play button at all** — only a
  `st.download_button`. (P1)
- **Jobs view** (`_render_job_card`, COMPLETE): a `st.download_button` labelled `"▶"` (a play glyph)
  that is actually a **download**, not a streamed Play. (P1 — mislabeled, no streaming)
- **Generation-result snapshot** (`_render_generation_task_snapshot`): `st.video(local_path)` — this
  works (Streamlit streams the file from the shared bind mount to the browser). (works, but only for
  the most-recently-generated video)
- **Top-bar Task Manager table** Play button → `_open_task_video` → **`xdg-open` / `webbrowser.open` on
  the SERVER** (lines 871, 893). This opens a file on the VPS desktop, not the user's browser.
  **BROKEN for remote users.** (P0)
- **Conclusion:** there is no reliable in-browser streaming Play for completed videos in the library or
  jobs views. Download (file bytes) is the only thing that reaches the user.

### DOWNLOAD
- Video Library: `st.download_button(data=open(video_file,'rb'))` reading the shared bind mount.
  **Works** (file bytes served by Streamlit). (verified by code path; file exists on disk)
- Jobs view: same mechanism, mislabeled as `▶`. **Works as download.**

### DELETE (single task)
- **Jobs nav view** (`_render_job_card`): **NO Delete button.** (P0 — required action absent)
- **Top-bar Task Manager table** (`_render_task_table` → `_delete_task`): calls `sm.state.delete_task`
  (in-process) + `shutil.rmtree(task_path)`. **Works at filesystem + DB level** (verified by code;
  the WebUI process has direct DB access). But it bypasses the API.
- **API endpoint** `DELETE /api/v1/tasks/{id}`: verified functional in controlled test (→404 after).
- Gap: Delete is not uniformly present, and the WebUI path bypasses the canonical API. (P1)

### CANCEL (QUEUED)
- **UI: NO Cancel button exists anywhere** in the Jobs/Library views. (P0 — required action absent)
- API `POST /api/v1/tasks/{id}/cancel` → `task_cleanup.cancel_task`: sets `state=CANCELLED` (state 2).
  Verified in controlled test: QUEUED→CANCELLED succeeded. Backend works.
- Caveat: `cancel_task` only flips DB state; it does **not** dequeue an in-flight worker job. True
  worker cancellation is unverified (no `is_task_busy` check removes from the in-memory queue). (P2)

### RETRY (FAILED / CANCELLED)
- **UI: NO Retry button exists anywhere** in the Jobs/Library views. (P0 — required action absent)
- API `POST /api/v1/tasks/{id}/retry` → `task_cleanup.retry_task`: creates a NEW task_id, reuses
  `api_task_manager.add_task` (canonical path), state→QUEUED. Verified: backend reachable; with real
  `params` it returns the new task id (probe lacked params → 409 "original parameters not available",
  which is correct guard behavior). Backend works; UI does not expose it.

### CLEAR COMPLETED / FAILED / ORPHAN / ALL
- UI: `_render_jobs_view` cleanup buttons → `_api_clear_tasks` / `_api_clear_all_tasks`
  (`webui/Main.py:6211-6238`) → **hardcoded `requests.post("http://127.0.0.1:8080/api/v1/tasks/clear")`**
- **BUG (P0, RUNTIME-PROVEN):** inside the WebUI container, `127.0.0.1:8080` is the WebUI itself
  (Streamlit), NOT the API. Connection refused.
- Log evidence (container `moneyprinterturbo-webui`, verbatim):
  ```
  2026-08-29 10:17:34 WARNING ./webui/Main.py:6237 _api_clear_all_tasks
    clear all tasks failed: HTTPConnectionPool(host='127.0.0.1', port=8080):
    Max retries exceeded ... [Errno 111] Connection refused
  2026-08-29 10:17:39 WARNING ./webui/Main.py:6222 _api_clear_tasks
    clear tasks failed: HTTPConnectionPool(host='127.0.0.1', port=8080): ... Connection refused
  ```
- Connectivity proof (from inside the WebUI container):
  - `http://moneyprinterturbo-api:8080/api/v1/tasks` → **200** (docker DNS correct)
  - `http://127.0.0.1:8080/api/v1/tasks` → **Errno 111 Connection refused** (what the code uses)
- Secondary effect: even if the URL were fixed, `clear_*` only operates on DB tasks (5 failed), so the
  77 on-disk completed videos and 151 dirs would still not be cleared. Double failure.
- **User-visible result:** clicking Clear shows "Cleared 0" and **does nothing** — exactly the reported symptom.

### YOUTUBE (footage source)
- **Present in UI:** create-form `video_sources` includes `("YouTube","youtube")` (`webui/Main.py:3790-3816`);
  batch form includes `"youtube"` (`webui/Main.py:3730`). Selectable.
- **Present in engine:** `app/services/material.py` implements YouTube download via `yt_dlp`
  (`save_video_youtube`, `_youtube_video_identity` validating 11-char video IDs). This is **direct-URL**
  support, not search. Pexels/Pixabay/Coverr are the *search* sources.
- **Verdict:** YouTube source is implemented and surfaced. "YouTube missing" from the complaint likely
  referred to it being unverified/broken at runtime (needs cookies/`youtube_cookies_file`, network).
  Not a missing-code defect. (INFO — runtime behavior of actual download not exercised in this audit to
  avoid network/cookie use; do not claim verified until a real download succeeds.)

---

## 4. FINDINGS (classified)

### P0 — blocks the stated user contract; runtime-proven broken
- **P0-CLEAR-LOCALHOST**: All "Clear Completed / Failed / Orphan / All" buttons fail at runtime because
  `webui/Main.py:_api_clear_tasks`/`_api_clear_all_tasks` call `http://127.0.0.1:8080` (WebUI's own
  loopback) instead of `MPT_API_BASE_URL` (`moneyprinterturbo-api:8080`). Evidence: container logs
  (Errno 111) + in-container connectivity test. **Fix:** route these through `webui_api_client`
  (`api_clear_tasks`/`api_clear_all_tasks`), which already uses the correct DNS name.
- **P0-PLAY-BROKEN**: No in-browser streaming Play for completed videos in Library/Jobs. Library has
  none; Jobs mislabels a download as `▶`; Task-Manager Play calls server-side `xdg-open` (opens file on
  server, useless to remote user). Evidence: `_render_video_card` (download only), `_render_job_card`
  (`▶`=download), `_open_task_video` (`xdg-open`). **Fix:** add `st.video(local_path)` to video/job cards.
- **P0-JOB-ACTIONS-MISSING**: Jobs view (`_render_job_card`) has **no Cancel, Retry, or Delete** buttons.
  The contract requires QUEUED→Cancel, FAILED/CANCELLED→Retry, and Delete. Evidence: `_render_job_card`
  body (only subject/status/progress + optional download/error). **Fix:** add per-task Cancel/Retry/Delete
  wired to `webui_api_client` (API), gated by state.

### P1 — contract violations / material gaps
- **P1-STATE-DUAL-OWNER**: WebUI imports `app.services.state as sm` and `app.services.task as tm`
  directly and opens the **same** `tasks.db` in-process; it also scans the filesystem for completeness.
  The contract mandates WebUI→API→SQLite as the single path. Evidence: `webui/Main.py:56-57,798,903,
  1807` + `state.py` SQLiteState on shared file. Two processes owning one file + a disk-scan truth
  source = the 151-vs-5 divergence. **Fix:** WebUI must read/write task state exclusively via the API
  (`webui_api_client`); completeness must come from canonical state, not disk globbing.
- **P1-DELETE-BYPASS**: WebUI Delete (`_delete_task`) and status polling bypass the API. Same root cause
  as P1-STATE. **Fix:** unify on API endpoints.
- **P1-ORPHAN-MANAGEMENT**: 77 completed videos / 151 dirs are invisible to the canonical state backend;
  Clear/Orphan cannot reclaim them. **Fix:** reconcile state↔filesystem (backfill DB from disk, or make
  cleanup scan disk). Align with P1-STATE.

### P2 — quality / hardening
- **P2-THUMBNAILS**: 0 `thumbnail-*.jpg` across all tasks. `_find_task_thumbnail` falls back to a
  placeholder for every card. Contract wants auto-generated thumbnails. **Fix:** generate
  `thumbnail-1.jpg` at completion (do not block completion on thumbnail failure).
- **P2-CANCEL-REAL**: `cancel_task` flips DB state but does not dequeue an in-memory worker job; a
  QUEUED task already pulled by the worker could still run. Verify true worker cancellation before
  claiming Cancel is real (contract §16).
- **P2-BATCH-UI**: Batch persists in backend but UI only shows the current session's batch; no historical
  batch browser. Add a batches list view backed by `GET /api/v1/batches`.
- **P2-STALE-CONTAINER**: `mpt-7b-9090` (GHCR upstream image) is running, unrouted, 5 days old. Retire
  after canonical MPT is proven (roadmap 11H.5). Not user-facing.
- **P2-UVICORN-HEADER**: `127.0.0.1:8501` returns `server: uvicorn` and the WebUI log shows
  "Uvicorn server started on 0.0.0.0:8501", yet PID 1 cmdline is `streamlit run ./webui/Main.py`. The
  UI is interactive Streamlit (user-observed), so functionally fine, but the header/launcher mismatch
  should be confirmed (possible misbuilt image). INFO unless it affects behavior.
- **INFO-TTS-CONFIG**: 5 failed DB tasks failed at `audio` because `voice_name=""`. Engine works; TTS
  voice/config needs valid value. Not a code defect.

---

## 5. PRIORITY-ORDERED RECOMMENDED FIXES (for Phase 11H.2, not applied here)

1. **P0-CLEAR-LOCALHOST** — repoint `_api_clear_tasks`/`_api_clear_all_tasks` to `webui_api_client`
   (DNS). One-line-per-call change; immediately restores Clear. (Highest leverage, proven root cause.)
2. **P0-JOB-ACTIONS-MISSING** + **P0-PLAY-BROKEN** — add `st.video` Play and per-task
   Cancel/Retry/Delete buttons to `_render_video_card` and `_render_job_card`, all calling
   `webui_api_client` (API). Delete must `rmtree` + API delete; Cancel/Retry gated by state.
3. **P1-STATE-DUAL-OWNER** — make WebUI a pure API client for task state; remove in-process
   `sm.state`/`tm` usage and filesystem-scan-as-truth. This also fixes P1-DELETE-BYPASS and
   P1-ORPHAN-MANAGEMENT (reconcile disk→DB).
4. **P2-THUMBNAILS** — generate `thumbnail-1.jpg` at completion.
5. **P2-BATCH-UI / P2-CANCEL-REAL / P2-STALE-CONTAINER / P2-UVICORN-HEADER** — follow-ups.

---

## 6. WHAT WAS NOT DONE
- No source files modified.
- No production tasks/videos deleted.
- One disposable probe task (`audit-probe-*`) was inserted and then deleted from `tasks.db` to prove
  the API cancel/delete backend; confirmed gone (GET → 404, row absent).
- No containers restarted; no images rebuilt.

## 7. VERDICT
Prior "PASS" claims for job lifecycle, cleanup, play, and state are **NOT VERIFIED** by runtime
behavior. Concrete, reproduced failures exist for: Clear (connection refused, runtime log), Play
(server-side open / missing), and missing Cancel/Retry/Delete in the Jobs UI. The API backend itself
is functional (proven via controlled mutation test), so the defects are concentrated in the WebUI's
wiring and the dual-ownership state model. Audit gate **11H.1.13 = FAIL** until P0 items are resolved.
