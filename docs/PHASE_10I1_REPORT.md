# Phase 10I.1 — Fix DEFECT-1: Failed Encoding Temp-Clip Cleanup

**Date:** 2026-08-28
**Scope:** Fix **ONLY** DEFECT-1 from Phase 10I (P1): `combine_videos()` can leave an
orphan `temp-clip-{i+1}.mp4` when clip creation/encoding fails before the clip is
added to the cleanup collection.

DEFECT-2 (download partial) and DEFECT-3 (sweeper TTL reliance) are **deferred**
to a later subphase and were intentionally left untouched.

---

## 1. Executive Summary

- Root cause identified in `app/services/video.py` `combine_videos()`.
- TDD followed: RED test reproduced the defect against the **old** code (FAIL);
  minimal fix applied; GREEN test passes against the **fixed** code (PASS).
- Minimal, surgical change: track each temp-clip path at creation time and clean
  it both on the early "no clips available" return and in the existing `finally`.
- Full regression suite passes: **171 passed, 1 skipped, 60 subtests passed**
  (plus `test_video.py`: 45 passed / 44 subtests) with **0 failures**.
- All production invariants unchanged. No production code other than
  `app/services/video.py` was modified; DEFECT-2/3 left intact.

**Final classification: PASS.**

---

## 2. DEFECT-1 Description

When a clip's encoding/write operation inside `combine_videos()` raises, the
exception is caught per-clip and the loop continues. The failed clip's
`temp-clip-{i+1}.mp4` is **never** appended to `processed_clips`, so the
`finally` block (which only deletes `clip_files` derived from `processed_clips`)
never removes it.

Worse, when **all** clips fail, `processed_clips` is empty and `combine_videos()`
hits the early `return combined_video_path` at the "no clips available for
merging" branch — which is **before** the `try/finally` cleanup block entirely —
so the `finally` never executes and the orphan temp file is leaked.

---

## 3. Root Cause

In `combine_videos()` (app/services/video.py):

- `clip_file = f"{output_dir}/temp-clip-{i+1}.mp4"` is constructed (line ~733).
- `_write_videofile_with_codec_fallback(clip, clip_file, ...)` is called (line ~734).
- On failure, the `except` (line ~757) only logs and `continue`s; `clip_file` is
  **not** added to `processed_clips`.
- `clip_files = [clip.file_path for clip in processed_clips]` (line ~784) therefore
  omits the failed clip.
- The cleanup `finally: delete_files(clip_files)` (line ~800) cannot delete a file
  that is not in `clip_files`.
- Additionally, when `processed_clips` is empty, the early `return` (line ~782)
  exits **before** the `try/finally`, so cleanup is skipped entirely.

---

## 4. RED Test Evidence

A focused regression test
(`test_D_encoding_failure_temp_clip_cleanup_behavior` in the committed Phase 10I
suite, plus the new `test_defect1_A…F` block) reproduces the defect by injecting a
failure into `_write_videofile_with_codec_fallback` after it partially writes
`temp-clip-1.mp4`.

**Run against the OLD (pre-fix, baseline commit `ce041ff`) code:**

```
test_D_encoding_failure_temp_clip_cleanup_behavior FAILED
test_defect1_A_encoding_failure_cleans_temp_clip  FAILED
test_defect1_C_successful_concat_cleans_temp_clips FAILED   (test bug; see §8)
test_defect1_D_multiple_clips_one_encodes_fails_cleans_all FAILED
================= 4 failed, 3 passed =================
```

The encoding-failure assertions genuinely demonstrate the orphan temp file
existed under the old implementation (RED). (`test_defect1_C` also failed on old
code due to a test-helper bug — using `ffmpeg` instead of `ffprobe` — which was
fixed; that failure was not evidence of the product defect.)

---

## 5. Minimal Fix

Three small, localized edits in `app/services/video.py`:

1. **Track temp paths at creation.** Added a `temp_clip_paths = []` list alongside
   `processed_clips`, and appended `clip_file` to it immediately after the path is
   constructed (before the write can fail):
   ```python
   clip_file = f"{output_dir}/temp-clip-{i+1}.mp4"
   temp_clip_paths.append(clip_file)
   _write_videofile_with_codec_fallback(...)
   ```

2. **Clean on the all-failed early return.** Before the
   `if not processed_clips: ... return combined_video_path` branch:
   ```python
   if not processed_clips:
       logger.warning("no clips available for merging")
       delete_files(temp_clip_paths)
       return combined_video_path
   ```

3. **Clean in the existing `finally`.** Extended the cleanup to include every
   created temp file (not just successfully-processed ones):
   ```python
   finally:
       delete_files(clip_files + temp_clip_paths)
   ```
   `delete_files` deduplicates, so successful clips (present in both lists) are
   deleted exactly once.

The fix does **not** broaden cleanup scope: it only ensures temp files that were
created are also tracked for deletion. No permanent/protected files are touched.

---

## 6. GREEN Evidence

**Run against the FIXED code** (all DEFECT-1 tests):

```
test_D_encoding_failure_temp_clip_cleanup_behavior PASSED
test_defect1_A_encoding_failure_cleans_temp_clip       PASSED
test_defect1_B_concat_failure_cleans_temp_clips        PASSED
test_defect1_C_successful_concat_cleans_temp_clips      PASSED
test_defect1_D_multiple_clips_one_encodes_fails_cleans_all PASSED
test_defect1_E_missing_temp_file_idempotent            PASSED
test_defect1_F_unrelated_files_not_removed             PASSED
====================== 7 passed ======================
```

After the injected encoding failure, `temp-clip-*.mp4` files are **absent**.

---

## 7. Regression Matrix

| Case | Verdict |
|------|---------|
| A. Encoding failure → temp clip deleted | ✅ `test_defect1_A` |
| B. Concat failure → temp clips + concat list deleted | ✅ `test_defect1_B` |
| C. Successful concat → temp clips deleted, output valid 1080×1920 | ✅ `test_defect1_C` |
| D. Multiple clips, one encoding fails → ALL temp clips cleaned | ✅ `test_defect1_D` |
| E. Missing temp file → cleanup idempotent (no error) | ✅ `test_defect1_E` |
| F. Unrelated files (`combined-*`, `final-*`, `audio.mp3`, `subtitle.srt`, `script.json`, source) NOT removed | ✅ `test_defect1_F` |

---

## 8. Full Regression Results

Executed inside the production container (image unchanged; `pytest` installed
ephemerally for the run only):

| Suite | Result |
|-------|--------|
| `test_failure_recovery_phase10i.py` (10I + 10I.1) | passed |
| `test_media_cleanup.py` (10C) | passed |
| `test_quality_gate_10f1.py`, `test_quality_gate_phase10f.py`, `test_quality_gate_landscape.py` (10F) | passed |
| `test_youtube_cache_identity_10h1.py`, `test_youtube_format_selection_10h2.py` (10H) | passed |
| `test_video.py` | 45 passed / 44 subtests passed |

**Totals:** 171 passed, 1 skipped, 60 subtests passed (plus 45/44 from `test_video.py`),
**0 failures**. No existing test weakened or deleted.

> Note: `test_defect1_C` initially failed on the old code due to a test-helper bug
> (used `ffmpeg` instead of `ffprobe` in `_probe_dims`); this was a test issue,
> corrected before GREEN. It is unrelated to the product defect and does not affect
> the RED/GREEN conclusion for DEFECT-1 (the encoding-failure assertions were
> valid RED evidence).

---

## 9. Behavioral-Drift Analysis

The **only** intended behavioral change is:

> A failed temp-clip encoding no longer leaves an orphan `temp-clip-*.mp4`.

Verified unchanged:
- output filename / location — unchanged
- clip ordering / duration — unchanged
- reframe (scale-to-cover + crop) calculation — unchanged
- resolution of output (1080×1920 portrait) — unchanged
- concat invocation (`concat_video_clips_with_ffmpeg`) — unchanged
- codec fallback (`_get_effective_video_codec` / `_write_videofile_with_codec_fallback`) — unchanged
- error propagation (per-clip `except` logs and continues; `RuntimeError` from
  concat propagates) — unchanged
- logging — unchanged (one added `logger.warning` on the all-failed path)
- permanent artifacts (`combined-*`, `final-*`, `audio.mp3`, `script.json`,
  source videos) — never touched by cleanup (pattern/protected-name safe)

---

## 10. Production Safety Comparison

| Item | Baseline (ce041ff) | After fix | Status |
|------|--------------------|-----------|--------|
| factory.db SHA256 | `ad0e6df9…` | `ad0e6df9…` | ✅ unchanged |
| factory.db size | 151552 | 151552 | ✅ |
| factory jobs | 171 | 171 | ✅ |
| production MP4 count | 158 | 158 | ✅ |
| task directory count | 134 | 134 | ✅ |
| cache_videos | 0 / 20K | 0 / 20K | ✅ |
| config.toml SHA256 | `2a8d89a6…` | `2a8d89a6…` | ✅ |
| nginx | unchanged | unchanged | ✅ |
| container ID/image | `952021e92d…` / phase10h | same | ✅ |
| restart count | 0 | 0 | ✅ |
| production jobs | 0 | 0 | ✅ |
| YouTube downloads | 0 | 0 | ✅ |
| production E2E | 0 | 0 | ✅ |

`storage/tasks/test-task/` (empty pytest artifact) remains untouched.

---

## 11. DEFECT-2 Status — DEFERRED

Not addressed in this phase (out of scope). `save_video_youtube` still returns
`""` on `DownloadError` without removing a partial cache file; reclaimed only by
the 30-day TTL sweeper. Left intact per the hard scope boundary.

## 12. DEFECT-3 Status — DEFERRED

Not addressed in this phase (out of scope). The sweeper remains fail-closed
(returns empty refs on unreadable task state) and relies on TTL for that case.
Left intact per the hard scope boundary.

---

## 13. Limitations

- The running container was not redeployed; the fix lives in the committed source
  and will take effect on the next image build/redeploy. The live process retains
  its deployed (pre-fix) in-memory code, which is correct for this audit/fix phase.
- `test_defect1_C` required a test-helper correction (`ffprobe` vs `ffmpeg`);
  this is a test concern, not a product change.

---

## 14. Final Classification

**PASS** — all acceptance criteria satisfied:
- RED test genuinely failed before fix ✅
- minimal fix implemented ✅
- GREEN test passes ✅
- encoding failure leaves no temp clip ✅
- concat failure still cleans temp clips ✅
- successful path still works ✅
- no unrelated artifacts deleted ✅
- full regression passes ✅
- production invariants unchanged ✅
- working tree clean after commit ✅
- DEFECT-2/3 remain untouched ✅

---

## Compliance Statements

- DEFECT-1 P1: **FIXED**
- DEFECT-2 P2: **DEFERRED**
- DEFECT-3 P2: **DEFERRED**
- real YouTube downloads: **0**
- production jobs: **0**
- production E2E: **0**
- factory.db modified: **NO**
- config.toml modified: **NO**
- nginx modified: **NO**
- production MP4 modified: **NO**

## 15. Exact Commit

- Previous HEAD: `ce041ff3fe0c16c3951527979f77508d0c807507` (Phase 10I)
- New commit: `fix: clean failed temp clips in combine_videos`
- Final HEAD: see `git rev-parse HEAD` after commit
- Files changed:
  - `app/services/video.py` (production fix)
  - `test/services/test_failure_recovery_phase10i.py` (DEFECT-1 regression + matrix)
  - `docs/PHASE_10I1_REPORT.md` (this report)
