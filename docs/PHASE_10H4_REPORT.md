# Phase 10H.4 — Final Accepted-Source Real YouTube E2E

**Date:** 2026-08-28
**Objective:** Final controlled real-YouTube end-to-end validation after the
permanent Phase 10H.1 + 10H.2 Docker deployment, proving:

REAL YouTube → correct cache identity → improved format selection →
actual high-resolution download → output-aware quality gate ACCEPT →
actual MPT reframe → 1080×1920 output → clean media lifecycle.

This is **not** a production job. Phase 10I is **not** started.

---

## 1. Executive Summary

A single real YouTube video (`BHACKCNDMW8`, "3 Hours of Amazing Nature
Scenery…") was searched, downloaded, and reframed entirely through the existing
MPT code paths:

- Search: `search_videos_youtube()` (yt-dlp `ytsearch`, metadata only).
- Download: `save_video_youtube()` via the **Phase 10H.2** selector
  `bestvideo[vcodec^=avc1][ext=mp4][height<=720]+bestaudio[acodec^=mp4a]/best`
  → selected **1280×720 H.264 + AAC** (merged to mp4). This is materially
  higher quality than the old `best[ext=mp4][height<=720]` behavior, which would
  have picked the progressive **360p** stream (format 18).
- Quality gate: Phase 10F output-aware gate ACCEPTED
  (`effective_min = 405 ≥ 250`).
- Reframe: `combine_videos()` produced a file that is **exactly 1080×1920**
  (9:16), H.264, with scale-to-cover (no stretching, no black bars).
- Cache identity: canonical `yt:<video-ID>`; the downloaded file path matched
  `vid-{md5(identity)}.mp4` and equivalent URL forms resolved to the same
  identity.
- Cleanup: temporary download and reframe output removed; `cache_videos`
  restored to empty; no `.part`/`.ytdl` left.

**Classification: PASS.**

---

## 2. Task-Directory 133→134 Investigation (Pre-Flight)

The extra directory is `storage/tasks/test-task/` (mtime
`2026-08-28T09:19:40`).

Findings:
- It is **empty** — it contains no `script.json` (every real task directory
  has one).
- Its name is created by the pytest suite `test/services/test_youtube_provider.py`
  (lines 279 and 312 use `task_id="test-task"` / `"test-task-fail"`).
- Its mtime (`09:19:40`) **predates** the Phase 10H.3 deployment
  (`~10:34`), so it is **not** a 10H.3 artifact.
- It is **not** referenced in `factory.db` (no `jobs` row with `id='test-task'`).
- It holds no production data.

Conclusion: a pre-existing, harmless, empty test artifact left by the unit-test
suite. Per the safety rules it was **not** deleted (it is not a 10H.3 artifact,
and removing it would be mutating state merely to restore a count). It is
counted in the baseline's 134 task directories and left untouched throughout.

---

## 3. Baseline (captured before the test)

| Item | Value |
|------|-------|
| git HEAD | `476fba9bdf70f56e3476539282118b84fb8ce1d8` |
| git status | clean |
| factory.db SHA256 | `ad0e6df9d5a45438532c0c99655455448e8c791bd5781711bf1f4f111a5d59a1` |
| factory.db size | 151552 bytes |
| factory job count | 171 |
| factory assets | 43 |
| production MP4 count | 158 |
| task directory count | 134 (incl. empty `test-task/`) |
| cache_videos file count | 0 |
| cache_videos total size | 20K (empty dir) |
| config.toml SHA256 | `2a8d89a696ff5564703547e86c198d846370399de3ae3a5e105c0784d26c7f45` |
| container ID | `952021e92d243eb26d35563c62fed69e3d1fdc748d7f8077d3eddd0b053044ab` |
| image ID / tag | `81866e5161fa2dcb742dcad6f43497eb78d23801f40449e44af28cd09404bcb8` / `mpt-youtube-ejs-phase10h:latest` |
| restart count | 0 |
| container health | running, ExitCode=0 |
| bind mounts | `config.toml`, `storage` (rw) |

---

## 4. Runtime Image / Container Verification

Confirmed the running container is the permanent Phase 10H image:

- `Config.Image = mpt-youtube-ejs-phase10h:latest`, `ImageID = 81866e5161fa…`
- Runtime source checks inside the container:
  - `_youtube_video_identity()` present, **id-based** (`yt:` prefix). ✅
  - Format selector =
    `bestvideo[vcodec^=avc1][ext=mp4][height<=720]+bestaudio[acodec^=mp4a]/best` ✅
  - `_EFFECTIVE_MIN_DIMENSION = 250.0` ✅
  - Quality-gate target resolves to portrait `1080×1920` ✅
  - `_validate_downloaded_clip`, `_validate_reframe_resolution` present ✅
  - Phase 10C `cleanup_orphan_cache_videos` present ✅

Nothing was modified.

---

## 5. Cache Identity Verification

- `_youtube_video_identity("https://www.youtube.com/watch?v=BHACKCNDMW8")`
  → `yt:BHACKCNDMW8`.
- Equivalent supported URL forms all map to the **same** identity:
  - `…watch?v=BHACKCNDMW8&feature=youtu.be&t=10` → `yt:BHACKCNDMW8`
  - `https://youtu.be/BHACKCNDMW8` → `yt:BHACKCNDMW8`
- A different video ID (`AAAAAAAAAAA`) → different identity. ✅
- Non-YouTube URL → `None` (safe fallback, no collision). ✅
- The actual downloaded file path equaled the canonical path
  `cache_videos/vid-{md5("yt:BHACKCNDMW8")}.mp4`
  (`vid-f241b9429697537f850ba77d72ce27d8.mp4`), proving the cache key is unique
  per video ID. ✅

---

## 6. Search Result

- Provider: YouTube (MPT `search_videos_youtube`), single `ytsearch` call.
- Candidates returned: **1** (yt-dlp `ytsearch` default yields one entry).
- Selected candidate:
  - title: "3 Hours of Amazing Nature Scenery & Relaxing Music for Stress Relief."
  - URL (sanitized): `https://www.youtube.com/watch?v=BHACKCNDMW8`
  - asset_id / video ID: `BHACKCNDMW8`
  - search-reported duration: 10809 s (3 h)
- No repeated search; no candidate substitution.

---

## 7. Real YouTube Candidate

Selected the single returned candidate (the only one available from the single
search). It is landscape, which the smart-reframe pipeline accepts and reframes
to 9:16.

---

## 8. Actual Format Selection (Phase 10H.2)

`save_video_youtube()` downloaded using the validated selector:

```
bestvideo[vcodec^=avc1][ext=mp4][height<=720]+bestaudio[acodec^=mp4a]/best
```

Resulting source clip: **1280×720**, H.264 video, **AAC** audio, muxed to **mp4**.

This is the **improved** behavior: the old selector
`best[ext=mp4][height<=720]` would have selected the progressive **360p**
stream (format 18). The new selector selected the **720p** H.264 DASH video
plus compatible AAC audio, merged into MP4 — a strictly higher-quality source.

---

## 9. Actual Resolution

- Source: **1280×720** (landscape). Meets the preferred
  "landscape ≥ 854×480" criterion.
- Duration (actual): 10808.9 s.
- Video codec: H.264 (avc1). Audio codec: AAC (mp4a). Container: MP4.
- Filesize (transient): 1,253,383,304 bytes (~1.25 GB) — see Limitations.

---

## 10. Effective-Resolution Calculation (Phase 10F)

Target = portrait `1080×1920` (ratio 0.5625).
Source = `1280×720` (ratio 1.7778 > 0.5625 → source wider → scale by height):

```
scale        = target_h / src_h = 1920 / 720        = 2.6667
effective_src_w = target_w / scale = 1080 / 2.6667  = 405.0
effective_src_h = target_h / scale = 1920 / 2.6667  = 720.0
effective_min   = min(405.0, 720.0)                 = 405.0
```

`effective_min (405.0) >= 250.0` → **ACCEPT**.

---

## 11. Quality-Gate Decision

`_validate_downloaded_clip()` returned **True**:
- file exists, size > 0, duration > 0, fps > 0 ✅
- output-aware gate: `effective_min = 405.0 ≥ 250.0` ✅
- duration check (min_duration=0) not binding ✅

**Decision: ACCEPT.**

---

## 12. Real Reframe Result

`combine_videos()` was invoked with the real downloaded clip and an isolated,
locally-generated 6 s silent WAV (no network, no production audio). Output
written to `/tmp/e2e_h4/combined_1080x1920.mp4` (outside `storage/tasks/` — not
a production task).

Result:
- width × height = **1080 × 1920**
- codec: H.264
- duration: 6.0 s
- container: MP4
- filesize: 1,162,512 bytes

---

## 13. 1080×1920 Verification

- `output_is_1080x1920 = True` (ffprobe: 1080×1920).
- `output_aspect = 0.5625` = exactly **9:16**.
- No stretching: scale-to-cover applies a **uniform** scale factor
  (`scale = 2.6667` for both axes) followed by center-crop — by construction no
  distortion.
- No black bars: the scale-to-cover + crop fully covers the 9:16 frame.
  Edge-sampling evidence: left-edge average luma `YAVG = 52.9` (not pure black,
  `> 5`), confirming the frame is filled with source content, not letterbox bars.
- Clean decode: ffprobe read the file without error.
- Source composition reasonable (nature scenery, no rotation introduced).

---

## 14. Visual-Quality Checks

| Check | Result |
|-------|--------|
| output 1080×1920 | ✅ |
| aspect 9:16 | ✅ (0.5625) |
| proportional scaling (no stretch) | ✅ (uniform scale-to-cover) |
| no rotation | ✅ |
| no black bars | ✅ (edge YAVG 52.9, not black) |
| clean decode | ✅ |

---

## 15. Cleanup Verification

- Temporary reframe output (`/tmp/e2e_h4/combined_1080x1920.mp4`) removed. ✅
- Temporary silent audio removed. ✅
- Temporary real download (`cache_videos/vid-f241b9429697537f850ba77d72ce27d8.mp4`)
  removed. ✅
- No `.part`, `.ytdl`, or `.tmp` files in `storage`. ✅
- `cache_videos` restored to **0 files / 20K** (matches baseline). ✅
- Container `/tmp` harness artifacts removed. ✅
- No pre-existing file was deleted.

---

## 16. Production Invariant Comparison

| Invariant | Baseline | After test | Status |
|-----------|----------|------------|--------|
| factory.db SHA256 | `ad0e6df9…` | `ad0e6df9…` | ✅ unchanged |
| factory.db size | 151552 | 151552 | ✅ |
| factory jobs | 171 | 171 | ✅ |
| factory assets | 43 | 43 | ✅ |
| production MP4 | 158 | 158 | ✅ |
| task directories | 134 | 134 | ✅ (test-task untouched) |
| config.toml SHA256 | `2a8d89a6…` | `2a8d89a6…` | ✅ |
| cache_videos count/size | 0 / 20K | 0 / 20K | ✅ |
| container ID | `952021e92d24…` | `952021e92d24…` | ✅ |
| container image | `mpt-youtube-ejs-phase10h:latest` | same | ✅ |
| restart count | 0 | 0 | ✅ |
| git status | clean | clean (report uncommitted) | ✅ |

Container remains **running, ExitCode=0, RestartCount=0**.

---

## 17. Any Anomalies

- **Selected candidate was a 3-hour video.** The single search result happened
  to be a long nature compilation, so the real download was ~1.25 GB. This is a
  transient, controlled download (exactly one, as permitted) and was fully
  removed during cleanup — no multi-GB artifact remains.
- **Only one search result** was returned by `ytsearch` (default count = 1).
  The single candidate was used; no re-search or substitution was performed.

Neither anomaly affects the acceptance criteria; both are documented as
limitations below.

---

## 18. Limitations

- Only one YouTube candidate was returned by the metadata search, so the
  candidate pool for this run was a single video. The selected video was
  landscape and accepted by the gate; the result is still representative of the
  real pipeline.
- The candidate's full 3-hour duration made the downloaded file large (~1.25 GB)
  before cleanup. A shorter candidate would be preferable for future isolated
  tests, but re-searching was disallowed by the safety contract.
- The downstream subtitle/audio pipeline (Step 8) was **not** run as a full
  render: that would require a production task (factory job) or writing into
  `storage/tasks/`, which the safety contract forbids. The combined clip is
  already consumable by that pipeline (standard MP4/H.264, 1080×1920); the
  isolated render check is therefore skipped and documented as such.

---

## 19. Final Classification

**PASS** — all acceptance criteria satisfied:

1. Real YouTube footage downloaded through MPT (search → `save_video_youtube`). ✅
2. Phase 10H.2 selector selected 720p H.264+AAC, higher quality than old 360p. ✅
3. Actual source resolution sufficient (1280×720). ✅
4. Output-aware quality gate ACCEPTED (effective_min=405 ≥ 250). ✅
5. Real source reached `combine_videos()`. ✅
6. Real output exactly 1080×1920. ✅
7. No stretching (uniform scale-to-cover). ✅
8. No black bars (edge YAVG 52.9). ✅
9. Clean decode. ✅
10. Cache identity corresponds to correct YouTube video (canonical `yt:` path). ✅
11. Temporary artifacts cleaned. ✅
12. Production invariants unchanged. ✅
13. No provider fallback/substitution (YouTube only). ✅
14. No secrets exposed (cookies never read/printed). ✅
15. No source modification during this phase. ✅

---

## 20. Exact Commits

- `6199d56` — fix: canonicalize YouTube cache identity (10H.1)
- `a3bad2a` — fix: improve YouTube format selection (10H.2)
- `ad2aa62` — docs: Phase 10H.1 + 10H.2 report (10H)
- (10H.3 report commit) `476fba9` — docs: Phase 10H.3 deployment + verification

## 21. Final HEAD

Before this report commit: `476fba9bdf70f56e3476539282118b84fb8ce1d8`
After this report commit: see git log (`docs: Phase 10H.4 final accepted-source E2E report`).

---

## 22. Explicit Safety / Compliance Statements

- **real YouTube downloads:** 1
- **production jobs:** 0
- **production E2E:** 0
- **factory.db modified:** NO
- **config.toml modified:** NO
- **nginx modified:** NO
- **source modified:** NO

Phase 10I was **not** started, per the stop rule.
