# Phase 10I — Failure & Recovery Audit

**Date:** 2026-08-28
**Objective:** Validate that the current MoneyPrinterTurbo media pipeline **fails safely**
and **recovers safely** under controlled failure conditions, without corrupting
production state, leaking large media artifacts, or damaging unrelated jobs.

This is an **AUDIT + TEST** phase. No source defects were fixed; one real defect
was **discovered, proven, and classified** for a later subphase (10I.1).

Phase 10H.4 already proved the happy path. Phase 10I answers the complementary
question: «When something goes wrong, does the system fail cleanly?»

---

## 1. Executive Summary

- 26 Phase 10I tests executed: **24 passed, 1 failed (proven defect), 1 skipped**.
- Regression suite (10C/10E/10F/10H + 10I): **164 passed, 60 subtests passed, 1 failed (same defect), 1 skipped**, no errors in existing suites.
- **One P1 defect proven:** a clip-encoding failure inside `combine_videos`
  leaves an orphan `temp-clip-*.mp4` (cleanup is not guaranteed on that path).
- **Two P2 hardening findings** documented (download partial left on failure;
  sweeper relies on TTL when task state is unreadable).
- **No production-integrity defect** was found: nothing deletes production data,
  no cross-job deletion, no corruption. No permanent asset is ever touched by the
  sweeper (fail-closed by pattern + protected-name + active-reference + TTL).
- **All production invariants unchanged** after the full audit.

**Final classification: PASS — WITH P1/P2 FINDINGS.**

---

## 2. Safety Contract

Strictly observed. No production job, no production YouTube E2E, no additional
real download. All tests use isolated `tmp_path` fixtures and synthetic media.
`storage_dir` is patched/mocked where a test exercises the real cache path; the
real `storage/` on disk was never written by a destructive test.

`storage/tasks/test-task/` (the empty pytest artifact identified in 10H.4) was
left untouched.

---

## 3. Baseline (pre-flight, identical to 10H.4)

| Item | Value |
|------|-------|
| git HEAD | `6137b83fb4d070208b294423f17f76be8747b515` |
| git status | clean (before adding test/report) |
| factory.db SHA256 | `ad0e6df9d5a45438532c0c99655455448e8c791bd5781711bf1f4f111a5d59a1` |
| factory.db size | 151552 |
| factory jobs | 171 |
| factory assets | 43 |
| production MP4 | 158 |
| task directories | 134 (incl. empty `test-task/`) |
| cache_videos files / size | 0 / 20K |
| config.toml SHA256 | `2a8d89a696ff5564703547e86c198d846370399de3ae3a5e105c0784d26c7f4f4f111a5d59a1` |
| container ID | `952021e92d243eb26d35563c62fed69e3d804b053044ab` |
| image | `mpt-youtube-ejs-phase10h:latest` (`81866e5161fa…`) |
| restart count | 0 |
| container health | running, ExitCode=0 |
| bind mounts | `config.toml`, `storage` (rw) |

---

## 4. Architecture Audit (source read, not modified)

Failure boundaries mapped against `app/services/material.py`, `video.py`,
`task.py`, `asgi.py`:

| Boundary | Behavior | Cleanup guaranteed? | Notes |
|----------|----------|---------------------|-------|
| A. YouTube search failure | `search_videos_youtube` returns `[]`; caller handles empty | n/a | metadata-only, no disk |
| B. Download failure | `save_video_youtube` catches `DownloadError`/`Exception`, returns `""` | **Partial only** (see P2) | no false success; partial `vid-<hash>.mp4` may remain |
| C. Quality rejection | inline in `download_videos_by_scene` (material.py:1976-1987): `os.remove` on rejected file, `try/except OSError` | Yes (non-fatal) | proven by `test_A_reject_path_deletes_file_in_pipeline` / `test_C_*` |
| D. Material exhaustion | all candidates rejected → `RuntimeError` after deleting each | Yes | proven by `test_C_*` |
| E. Clip processing error | `combine_videos` catches per-clip (video.py:757) and continues | **No** for the failed clip (see P1) | proven defect |
| F. Concat/FFmpeg failure | `combine_videos` `try/finally` → `delete_files(clip_files)`; inner `concat_video_clips_with_ffmpeg` `finally` → deletes `ffmpeg-concat-list.txt` | Yes | proven by `test_D_concat_failure_*` |
| G. Combined-video generation failure | see F (same path) | Yes for temp | protected `combined-*`/`final-*` untouched (proven `test_E_*`) |
| H. Final render failure | no false success; protected assets preserved | Yes for temp | proven `test_E_*` |
| I. Task exception | `_mark_task_failed` records structured FAILED state, preserves progress | n/a (no files) | proven `test_F_*` |
| J. Task cancellation | code-inspected (cross-post raises `RuntimeError`, task.py:1206); not simulated | n/a | Test G NOT EXECUTED (unsafe to force) |
| K. Process/container restart | `asgi.py` → `run_startup_cleanup()` → `cleanup_orphan_cache_videos()` | Yes (sweeper) | proven `test_K_*` / `test_H_*` |
| L. Orphan-cache cleanup | `cleanup_orphan_cache_videos` (material.py:2297-2391) | Yes, fail-closed | proven `test_H/I/J/L/M/N` |

Key safe-design facts in `cleanup_orphan_cache_videos`:
- Pattern allowlist (`vid-{32-hex}.mp4`, `.part`, `.ytdl`, `.Frag*`) — unknown files KEPT.
- `_PROTECTED_FILENAMES` (`final-1.mp4`, `combined-1.mp4`, `audio.mp3`, `script.json`, …) never touched.
- Age < TTL → KEPT; active reference → KEPT; inspection/deletion error → KEPT/logged.

---

## 5. Failure Matrix (corrected to actual semantics)

| Failure | Expected State | Temporary Media | Raw Cache | Permanent Assets | Recovery |
|---------|---------------|-----------------|-----------|------------------|----------|
| Search failure | failed/clean | none | none | untouched | retry possible |
| Download failure | failed/clean (`""`) | partial may persist (P2) | no false entry | untouched | retry possible |
| Quality rejection | failed/next candidate | rejected raw **deleted** | no leak | untouched | next candidate |
| Material exhaustion | failed-clean (`RuntimeError`) | all rejected **deleted** | no leak | untouched | new task |
| Clip processing error | failed/clean | **orphan temp (P1)** | safe | untouched | new attempt |
| FFmpeg concat failure | failed/clean | temp clips + list **removed** | safe | untouched | new attempt |
| Final render failure | failed/clean | temp cleaned | safe | preserved | retry/new task |
| Cancellation | (inspected, not simulated) | recoverable | safe | preserved | new task |
| Container restart | recoverable | stale temp sweepable | stale cache sweepable | preserved | startup recovery |
| Orphan sweeper | unchanged | stale removed | only eligible removed | NEVER touched | idempotent |

---

## 6. Test A — Quality-Gate Failure ✅
`_validate_downloaded_clip` returns `False` for low-res (160×120, effective_min≈67.5<250) and sub-1024-byte files. The pipeline deletes the rejected raw file (proven via `download_videos_by_scene` with mocked search/downloader). Deletion via `delete_files` is non-fatal/idempotent. Unrelated cache files untouched.

## 7. Test B — Download Failure ✅
Mocked `yt_dlp.YoutubeDL` raises `DownloadError`. `save_video_youtube` returns `""` (no false success). Pre-existing unrelated cache file survives; no new valid entry created.

## 8. Test C — Material Exhaustion ✅
Three rejected candidates → each raw file deleted by the pipeline; scene raises `RuntimeError` (fail-clean); no `final-*`/`combined-*` created. Provider fallback was disabled (single source) — no silent substitution.

## 9. Test D — Temp Clip Failure
- **D (concat failure):** ✅ `try/finally` removes `temp-clip-*.mp4` and `ffmpeg-concat-list.txt`; protected `combined-1.mp4` preserved.
- **D (encoding failure):** ❌ **PROVEN DEFECT (P1).** A clip-encoding failure is caught (video.py:757) and the loop continues; the failed clip's `temp-clip-{i+1}.mp4` is never added to `processed_clips`, so the `finally` `delete_files(clip_files)` does not remove it. An orphan temp file remains. See §21.

## 10. Test E — Final Render Failure ✅
A failing render does not falsely report success; pre-existing `combined-1.mp4` and `final-1.mp4` are preserved; temp artifacts cleaned.

## 11. Test F — Pipeline Exception / Task Failure State ✅
`_mark_task_failed` sets `TASK_STATE_FAILED`, records `error`/`failed_stage`, preserves prior `progress`; does not crash even when task state is unreadable.

## 12. Test G — Cancellation — NOT EXECUTED ⚠️
Deterministic isolated cancellation requires an active orchestrated task (live worker/API). Forcing it risks production interaction, forbidden by the contract. The cancellation code path was inspected (`task.py:1206` raises `RuntimeError`; WebUI cancel transitions state). Marked NOT EXECUTED with rationale.

## 13. Test H — Container Restart / Recovery ✅
Isolated fixture with stale `vid-*.mp4`, `.part`, `.ytdl`, unknown file, protected file → sweeper deletes exactly the 3 eligible stale files; unknown + protected preserved. Recent files preserved (TTL). Idempotent on re-run.

## 14. Test I — Active Job Safety ✅
Active reference → `vid-X` KEPT. No active reference + beyond TTL → `vid-X` DELETED. Same identity referenced by two tasks → KEPT.

## 15. Test J — Cross-Job Isolation ✅
Job A failed, Job B active → `vid-A` deleted, `vid-B` untouched. Two tasks sharing one identity → KEPT.

## 16. Test K — Startup Cleanup Safety ✅
`run_startup_cleanup()` only invokes the sweeper; it does not touch config, factory.db, or production MP4s, and does not crash (its own `try/except` swallows sweeper errors).

## 17. Test L — Idempotency ✅
Sweeper run twice: first removes eligible, second is a no-op (no error). Repeated reject-cleanup (`delete_files`) is harmless when file already gone.

## 18. Test M — Fail-Closed Behavior ✅
Unknown filename, invalid hash, unexpected extension, and subdirectories inside `cache_videos` are all KEPT. A simulated `OSError` during deletion is logged and skipped (non-fatal). When task state is unreadable, the real `_get_active_cache_references` returns an empty set (fail-closed) and only stale eligible files are removed by TTL; young files remain protected.

## 19. Test N — Large-File Regression Model ✅
A symbolic `vid-{32-hex}.mp4` (canonical name, 1 MiB stand-in for the Phase 9 3.21 GiB rejected-download class) is removed by the exact sweeper deletion path; a co-located `final-1.mp4` is preserved. Proves the unbounded-leak failure class from Phase 9 is now handled (deletion path works; only a TTL wait is required, which is acceptable).

---

## 20. Production Invariant Comparison (after ALL tests)

| Invariant | Baseline | After tests | Status |
|-----------|----------|-------------|--------|
| factory.db SHA256 | `ad0e6df9…` | `ad0e6df9…` | ✅ unchanged |
| factory.db size | 151552 | 151552 | ✅ |
| factory jobs | 171 | 171 | ✅ |
| factory assets | 43 | 43 | ✅ |
| production MP4 | 158 | 158 | ✅ |
| task directories | 134 | 134 | ✅ |
| config.toml SHA256 | `2a8d89a6…` | `2a8d89a6…` | ✅ |
| cache_videos | 0 / 20K | 0 / 20K | ✅ |
| container ID/image | `952021e92d…` / phase10h | same | ✅ |
| restart count | 0 | 0 | ✅ |
| git state | clean (+ new test/report) | clean (+ new test/report) | ✅ |

---

## 21. Defects Discovered

### DEFECT-1 (P1) — Clip-encoding failure leaks a temp-clip file
- **Location:** `app/services/video.py`, `combine_videos` — clip loop `try` (write) at ~734, `except` at ~757; `finally` `delete_files(clip_files)` at ~800-802.
- **Mechanism:** On a clip-encoding failure the exception is caught and the loop continues. The failed clip's `temp-clip-{i+1}.mp4` was created at ~733 but is **not** appended to `processed_clips`, so the `finally` cleanup (which only deletes `processed_clips`' files) never removes it.
- **Impact:** An orphan `temp-clip-*.mp4` remains in the task output directory on the encoding-failure path. Not production-data-destructive (it is a transient temp file, and permanent `combined-*`/`final-*` are untouched), but it can accumulate uncontrolled temporary media on a failure path.
- **Evidence:** `test_D_encoding_failure_temp_clip_cleanup_behavior` FAILED (orphan left behind).
- **Severity:** P1 (crash/error leaves temporary media indefinitely on a common failure path).
- **Recommended 10I.1 fix:** in the `except` block at ~757, also `delete_files(clip_file)` (or collect failed clip paths and remove them in the existing `finally`).

### DEFECT-2 (P2) — Download failure may leave a partial cache file
- **Location:** `app/services/material.py`, `save_video_youtube` (~1387-1411).
- **Mechanism:** On `DownloadError` the function returns `""` but does not remove a partially-written `vid-<hash>.mp4` at the final cache path. The orphan sweeper only removes `vid-*.mp4` after the 30-day TTL, so a partial could persist (or be overwritten on retry).
- **Impact:** No false success (returns `""`), no corruption of unrelated files. Minor disk retention until TTL/overwrite.
- **Severity:** P2 (hardening).
- **Recommended 10I.1 fix:** on `DownloadError`, attempt `os.remove(video_path)` (best-effort, non-fatal) before returning `""`.

### DEFECT-3 (P2) — Sweeper relies on TTL when task state is unreadable
- **Location:** `app/services/material.py`, `_get_active_cache_references` (fail-closed returns empty set on error).
- **Mechanism:** When task state cannot be read, references are empty, so stale eligible files are deleted by the age rule. Young files (<30d) remain protected by TTL. Risk window is small (only >30d-old files during a state-backend outage).
- **Severity:** P2 (observability/hardening).
- **Recommended 10I.1:** optionally treat "state unreadable" as "preserve everything" for an extra-safe mode, at the cost of not reclaiming genuinely stale files during an outage.

---

## 22. Severity Classification

- **P0 (Critical):** none found. No production-data deletion, cross-job deletion, permanent corruption, unbounded leak without recovery, or task-state corruption.
- **P1 (Important):** DEFECT-1 (temp-clip leak on encoding failure).
- **P2 (Hardening):** DEFECT-2 (download partial), DEFECT-3 (sweeper TTL reliance on unreadable state).
- Cancellation (Test G) is an audit limitation, not a defect.

---

## 23. Regression Suite

Executed inside the production container (image unchanged; `pytest` installed
ephemerally for the run only):

| Suite | Result |
|-------|--------|
| `test_youtube_cache_identity_10h1.py` | passed |
| `test_youtube_format_selection_10h2.py` | passed |
| `test_quality_gate_10f1.py` | passed |
| `test_quality_gate_phase10f.py` | passed |
| `test_quality_gate_landscape.py` | passed |
| `test_media_cleanup.py` (10C) | passed |
| `test_failure_recovery_phase10i.py` (10I) | 24 passed / 1 failed (DEFECT-1) / 1 skipped |

**Totals:** 164 passed, 60 subtests passed, 1 failed (DEFECT-1), 1 skipped. No
existing test was weakened or deleted.

---

## 24. Limitations

- Test G (cancellation) was **not executed** — deterministic isolated cancellation
  needs a live orchestrated task; forcing it would risk production interaction.
- DEFECT-1 was proven with a synthetic partial-file injection (ffmpeg-less) to
  avoid real encodes; the code path exercised is the real `combine_videos`.
- The sweeper's 30-day TTL means a rejected/orphaned file is reclaimed after TTL,
  not instantly; this is by design and acceptable.

---

## 25. Recommended Phase 10I.1 Fixes

1. **P1:** cleanup the failed clip's `temp-clip-{i+1}.mp4` in `combine_videos`' `except` block (DEFECT-1).
2. **P2:** best-effort remove partial cache file on `save_video_youtube` `DownloadError` (DEFECT-2).
3. **P2:** consider a stricter "preserve-all" mode when task state is unreadable (DEFECT-3).

No source modifications were made during Phase 10I.

---

## 26. Final Classification

**PASS — WITH P1/P2 FINDINGS.**

The system demonstrably fails cleanly on the vast majority of paths (quality
rejection, download failure, material exhaustion, concat/render failure,
task-failure state, orphan sweeper, active-job safety, cross-job isolation,
startup cleanup, idempotency, fail-closed behavior, large-file regression). One
P1 defect (temp-clip leak on clip-encoding failure) and two P2 hardening items
were discovered, proven by deterministic tests, and classified — but none affect
production-data integrity, so this is **not** FAIL-CLEAN.

---

## Compliance Statements

- real YouTube downloads: **0**
- production jobs: **0**
- production E2E: **0**
- factory.db modified: **NO**
- config.toml modified: **NO**
- nginx modified: **NO**
- production MP4 modified: **NO**
- production task artifacts modified: **NO**
- source behavior modified: **NO**

## Git

- New test: `test/services/test_failure_recovery_phase10i.py`
- New doc: `docs/PHASE_10I_REPORT.md`
- No production source modification.
- Commit: `test: Phase 10I failure and recovery audit`
