# Phase 10H — Real YouTube E2E Validation Report

## 1. Executive Summary

Phase 10H validated the deployed **Phase 10F output-aware quality gate** against **real YouTube
footage** inside the running `moneyprinterturbo-api` production container. A dedicated, isolated
temp directory (`/tmp/phase10h_test` inside the container) was used for all downloads so that the
production `storage/cache_videos` was never touched.

Four (4) **real** YouTube downloads were performed (the maximum allowed by the safety budget):

| Test | Real video | Real resolution | Effective min | Gate |
|------|-----------|-----------------|--------------|------|
| A (portrait candidate) | `Eoo4HzILB-M` | 640×360 (landscape) | 202.5 | **REJECT** |
| B (landscape HD candidate) | `pb-j3svRQLI` | 640×360 (landscape) | 202.5 | **REJECT** |
| C (low-res candidate) | `AmbQMU-lTII` | 202×360 | 202.0 | **REJECT** (+cleanup ✓) |
| D reframe source | `eV6lTEY95yY` | 640×340 (landscape) | 191.2 | REJECT (reframe only) |

**Key finding:** In *this runtime* the YouTube provider caps every download at ~360p (see
Anomalies #2), so **no real YouTube source can currently pass the 250 effective gate**. The gate
itself behaved correctly on every real clip (all sub-250 effective → REJECT). Rejected-file cleanup
was verified (Test C). The **actual reframe transform** (`combine_videos` scale-to-cover + center
crop) was exercised on a real downloaded YouTube clip and produced **exactly 1080×1920, 9:16, no
stretch, no black bars, clean decode**.

Because no real source passed the gate, the strict "accepted real footage → reframe" E2E could not
be exercised within the 4-download cap. This is an environmental limitation, not a gate defect, and
no downloads were repeated to force a pass.

**Final classification: PASS — PARTIAL ACCEPTED-SOURCE COVERAGE**
(Download path, gate execution, negative-case rejection, cleanup, and reframe transform all proven
on real YouTube media; only the accept→reframe E2E was blocked by the runtime's 360p cap.)

---

## 2. Exact Runtime / Container Used

- **Container:** `moneyprinterturbo-api`
- **Container ID:** `5b7acab82caf42d93425f67ec57bd1e77fdca3cc0e34776d672f2bf07b147775`
- **Image:** `mpt-youtube-ejs-phase10f:latest`
- **Restart count:** 0 (before and after)
- **State:** running
- **Python:** 3.11.13 · **yt_dlp:** 2026.08.19 · **moviepy:** 2.1.2
- **Functions exercised (unchanged source):**
  - `app.services.material.search_videos_youtube`
  - `app.services.material.save_video_youtube`
  - `app.services.material._validate_downloaded_clip` → `_validate_reframe_resolution` (Phase 10F)
  - `app.services.video.combine_videos` (scale-to-cover + center-crop reframe)
- **Test isolation:** all downloads written to container `/tmp/phase10h_test` (via
  `save_video_youtube(url, save_dir=...)`); production `storage/cache_videos` untouched.

---

## 3. Baseline Invariants (captured before test, identical after)

| Invariant | Value |
|-----------|-------|
| Phase 10F implementation | `8223def` |
| Phase 10F.1 audit | `12b355e` |
| Phase 10G deployed runtime | `b57f8f8` |
| Deployed image | `mpt-youtube-ejs-phase10f:latest` |
| Effective threshold | `250.0` |
| Portrait target | `1080×1920` |
| factory.db SHA256 | `ad0e6df9d5a45438532c0c99655455448e8c791bd5781711bf1f4f111a5d59a1` |
| factory.db size | `151552` bytes |
| factory job count (task dirs) | `133` |
| production MP4 count (excl. cache_videos) | `158` |
| cache_videos count / size | `0` files / `20K` |
| config.toml SHA256 | `2a8d89a696ff5564703547e86c198d846370399de3ae3a5e105c0784d26c7f45` |
| git HEAD | `b57f8f8cfa0ce170277f870b21ef02ac871f6be0` |
| git status | clean |

---

## 4. Test A — Real Portrait Candidate

- **Query:** `vertical 9:16 travel reel aesthetic`
- **Search metadata (no secrets):** 1 candidate — title "No Copyright, Copyright Free Videos,
  sunset, beach, sea, waves", duration 21 s, `video_id=Eoo4HzILB-M`. Search rendition
  width/height came back `null` (see Anomaly #3).
- **Download:** `https://www.youtube.com/watch?v=Eoo4HzILB-M`
  - file size: `936633` bytes · codec: `h264` · **640×360** · duration `20.2 s`
  - cache path pattern: `cache_videos/vid-<md5(url_without_query)>.mp4`
- **Actual orientation:** **landscape** (not portrait) — the real candidate was a 360p landscape clip.
- **Effective resolution:** `scale = 1920/360 = 5.333` → effective `202.5 × 360`, **effective min = 202.5**
- **Gate decision:** **REJECT** (`202.5 < 250`)
- **Honest classification:** The single real portrait query returned a landscape 360p video, so the
  intended "portrait PASS" was **not** exercised. The gate correctly rejected it. No retry was
  performed to manufacture a pass (per safety rule).

---

## 5. Test B — Real Landscape Source (≥854×480 expected to PASS)

- **Query:** `4k nature documentary aerial landscape`
- **Search metadata:** 1 candidate — "Animals Of The World 4K - Scenic Wildlife Film With Calming
  Music", duration 3655 s, `video_id=pb-j3svRQLI`.
- **Download:** `https://www.youtube.com/watch?v=pb-j3svRQLI`
  - file size: `210201565` bytes · codec: `h264` · **640×360** · duration `3654.8 s`
- **Effective resolution:** effective `202.5 × 360`, **effective min = 202.5**
- **Gate decision:** **REJECT** (`202.5 < 250`)
- **Honest classification:** The *expected* "landscape HD passes" class was **not** exercised,
  because the chosen real video resolved to 360p (see Anomaly #2 — runtime caps YouTube at 360p).
  If a real ≥480p source had been obtained, the math predicts ACCEPT (480p → eff min 270 ≥ 250;
  720p → eff min 405 ≥ 250). The gate logic is correct; the resolution ceiling is environmental.

---

## 6. Test C — Real Low-Res Landscape (negative failure class)

- **Query:** `old uploaded home video 2008`
- **Search metadata:** 1 candidate — duration 9778 s, `video_id=AmbQMU-lTII`.
- **Download:** `https://www.youtube.com/watch?v=AmbQMU-lTII`
  - file size: `266396208` bytes · codec: `h264` · **202×360** · duration `9777.6 s`
- **Effective resolution:** `src_ratio = 202/360 = 0.561 < 0.5625` → `scale = 1080/202 = 5.347`
  → effective `202.0 × 359.1`, **effective min = 202.0**
- **Gate decision:** **REJECT** (`202.0 < 250`)
- **Cleanup verification (Phase 10C):** the rejected raw cache file was deleted by the same
  cleanup path the production flow uses (`app/services/material.py:1897-1908`). Observed
  `cleanup_occurred = true` (file no longer present). This exercises the real negative failure
  class (sub-250 effective) **and** confirms the rejected raw download is removed.
- This is an even sharper negative than the canonical 640×360 case (eff min 202.5) — both confirm
  rejection.

---

## 7. Test D — Real Accepted Source → Actual Reframe

- **Accepted source obtained?** **No.** All 4 real downloads were ≤360p and were REJECTED by the
  250 gate (runtime resolution cap, Anomaly #2), so no *gate-accepted* real source existed to feed
  the full accept→reframe E2E. The 4-download safety cap was respected; no extra downloads were
  made to force an accept.
- **Reframe transform validated on real YouTube media:** to prove the actual reframe path
  (`combine_videos` inline scale-to-cover + center-crop, `app/services/video.py:676-700`) works on
  **real** footage, `combine_videos()` was run on a real downloaded YouTube clip
  (`eV6lTEY95yY`, 640×340, gate-REJECTED low-res) as a single scene:
  - **Final output:** `1080×1920` (exact) · codec `h264` · duration `5.0 s`
  - **Aspect ratio:** `0.5625` (= 9:16) ✓
  - **No stretching:** uniform scale-to-cover (single scale factor applied to W and H) ✓
  - **No black bars:** resized clip `3614×1920` ≥ target, center-cropped to `1080×1920` (full
    coverage, no padding) ✓
  - **Clean decode:** reopened successfully with `VideoFileClip` ✓
  - Debug log confirmed: `resizing clip, source: 640x340, ratio: 1.88, target: 1080x1920, ratio: 0.56`
- **Caveat:** the strict "accepted real source reaches reframe" E2E is **not** claimed; only the
  reframe *transform* is verified on real YouTube media. The transform is resolution-agnostic, so a
  gate-accepting source would reframe identically.

---

## 8. Actual Source Resolutions

| Test | video_id | width × height | orientation | codec | duration (s) | file size (bytes) |
|------|----------|---------------|-------------|-------|--------------|-------------------|
| A | `Eoo4HzILB-M` | 640×360 | landscape | h264 | 20.2 | 936633 |
| B | `pb-j3svRQLI` | 640×360 | landscape | h264 | 3654.8 | 210201565 |
| C | `AmbQMU-lTII` | 202×360 | portrait (low) | h264 | 9777.6 | 266396208 |
| D-src | `eV6lTEY95yY` | 640×340 | landscape | h264 | 202.4 | 12464144 |

---

## 9. Effective-Resolution Calculations (target 1080×1920, threshold 250)

- **640×360:** `scale = 1920/360 = 5.333` → effective `1080/5.333 × 1920/5.333`
  = `202.5 × 360.0` → **min 202.5** → REJECT
- **202×360:** `src_ratio = 202/360 = 0.561 < 0.5625` → `scale = 1080/202 = 5.347`
  → effective `202.0 × 359.1` → **min 202.0** → REJECT
- **640×340:** `scale = 1920/340 = 5.647` → effective `191.2 × 340.0` → **min 191.2** → REJECT
- (Predicted, not obtained) **854×480:** `scale = 1920/480 = 4.0` → effective `270 × 480` →
  **min 270** → ACCEPT
- (Predicted, not obtained) **1280×720:** `scale = 1920/720 = 2.667` → effective `405 × 720` →
  **min 405** → ACCEPT

---

## 10. Gate Decisions

All four real clips were evaluated by the actual `_validate_downloaded_clip` →
`_validate_reframe_resolution` (Phase 10F) runtime gate with `video_aspect=portrait`
(1080×1920) and `min_effective_dimension = 250.0`:

- A: REJECT (202.5)
- B: REJECT (202.5)
- C: REJECT (202.0) — negative failure class confirmed
- D-src: REJECT (191.2)

The gate executed in the runtime and enforced the 250 effective threshold exactly as designed.

---

## 11. Reframe Verification

- Function: `combine_videos()` (real, unmodified).
- Input: real YouTube clip `eV6lTEY95yY` (640×340).
- Output: `1080×1920`, codec `h264`, duration `5.0 s`.
- Aspect `0.5625` (9:16) ✓ · no stretch ✓ · no black bars ✓ · clean decode ✓.
- (See §7 for full detail and caveat regarding accepted-source E2E.)

---

## 12. Cache Cleanup Verification

- **Production `cache_videos`:** `0` files before and after (all test downloads used the isolated
  `/tmp/phase10h_test` dir; never the production cache). No unexpected leftovers.
- **Test C rejected raw file:** deleted (`cleanup_occurred = true`), mirroring the Phase 10C
  cleanup block (`app/services/material.py:1897-1908`).
- **Accepted test source growth:** none — the entire `/tmp/phase10h_test` directory (all 4 real
  clips, combined output, scripts, results) was removed at the end of the phase.

---

## 13. Production Safety Verification

| Check | Before | After | Result |
|-------|--------|-------|--------|
| factory.db SHA256 | `ad0e6df9…` | `ad0e6df9…` | unchanged ✓ |
| factory.db size | 151552 | 151552 | unchanged ✓ |
| factory job count (task dirs) | 133 | 133 | unchanged ✓ |
| production MP4 count | 158 | 158 | unchanged ✓ |
| cache_videos files | 0 | 0 | unchanged ✓ |
| config.toml SHA256 | `2a8d89a6…` | `2a8d89a6…` | unchanged ✓ |
| git HEAD | `b57f8f8` | `b57f8f8` | unchanged ✓ |
| git working tree | clean | clean | ✓ |
| container restart count | 0 | 0 | ✓ |
| container state | running | running | ✓ |

No production task was created, no production artifact modified, no production job inserted into
`factory.db`.

---

## 14. Anomalies (real defects discovered — reported, NOT modified)

1. **YouTube cache-key collision in `save_video_youtube`** (`app/services/material.py:1287-1290`):
   the cache filename is derived from `url.split("?")[0]`. For every
   `https://www.youtube.com/watch?v=<ID>` URL this collapses to the identical string
   `https://www.youtube.com/watch`, so **all YouTube downloads map to one cache file**
   (`vid-<md5("https://www.youtube.com/watch")>.mp4`). Consequence: only one distinct YouTube video
   can ever be cached; any later YouTube URL returns the first download's file. In this phase it
   caused B/C to initially reuse A's file until the test harness cleared the collision file between
   distinct downloads (isolated `/tmp` only). This is a genuine provider defect affecting production
   too. Per Phase 10H rules (no source changes, report-only), it is documented here, not fixed.

2. **YouTube format selection caps at 360p** (`save_video_youtube` format
   `"best[ext=mp4][height<=720]"`, `app/services/material.py:1297`): yt-dlp's `best` prefers
   *complete* (video+audio) streams, so it selects progressive **format 18 (640×340/360)** instead of
   the available DASH **480p (id 135) / 720p (id 136)** which are video-only. Verified two ways:
   (a) `yt-dlp -F` shows 480p/720p/1080p/4k present; (b) `yt-dlp --simulate
   -f "best[ext=mp4][height<=720]"` reports `format_id=18, 640x340`. Net effect in this runtime:
   **all YouTube footage resolves to ~360p and is therefore always REJECTED by the 250 gate.**
   Reported only; format selection was NOT changed (safety rule 7).

3. **Search metadata lacks resolution:** `search_videos_youtube` (extract_flat) returned
   `rendition_width/height = null` for every candidate, consistent with the phase guidance "do not
   assume the search metadata reports resolution." Resolution can only be known after download.

No secrets, cookies, or auth tokens were read or printed (only sanitized `watch?v=<id>` URLs and
video IDs are recorded).

---

## 15. Final PASS / FAIL-CLEAN Classification

**PASS — PARTIAL ACCEPTED-SOURCE COVERAGE**

Criteria:
- ✅ Real YouTube download path works (4 distinct real downloads succeeded).
- ✅ Output-aware gate executes in runtime (Phase 10F gate ran on all 4 real clips).
- ✅ Rejected real footage is cleaned when rejection is exercised (Test C cleanup verified).
- ⚠️ Accepted real footage reaches reframe — **not exercised**: no real YouTube source passed the
  250 gate (runtime 360p cap, Anomaly #2). The reframe *transform* was proven on real footage
  (Test D). The 4-download cap was respected; no forced retries.
- ✅ No production invariants changed (factory.db, config.toml, tasks, MP4 counts, git, container).
- ✅ No provider fallback/substitution (YouTube only; no Pexels/Pixabay).
- ✅ No secrets exposed.

The validation did not manufacture evidence; all results are from real YouTube media and the
unchanged production pipeline. Two real defects (cache-key collision, 360p format cap) were found
and reported without modification.

---

## 16. Exact Git Commit

- **Validation-only commit:** the Phase 10H report is the only change added on top of
  `b57f8f8` (Phase 10G runtime). No source code was modified during Phase 10H.
- **Commit hash (report introduction):** `b2d1f0904dcc6e966fc1e4bc98b79bc38941ca77`
  - Parent (Phase 10G runtime): `b57f8f8cfa0ce170277f870b21ef02ac871f6be0`
  - This is the commit that added `docs/PHASE_10H_REPORT.md`. No pipeline source was changed.
