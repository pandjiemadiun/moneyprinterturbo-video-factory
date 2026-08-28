# PHASE 10F.1 — UPSTREAM QUALITY-FILTER COMPATIBILITY AUDIT

## STATUS: PASS — NO BLOCKER

---

## 1. Objective

Verify whether `rank_videos()`'s pre-download 480×480 resolution filter can prevent the
Phase 10F output-aware quality gate from ever seeing candidates that Phase 10F intentionally
accepts (e.g., 360×640 portrait with effective dimension 360 ≥ 250).

This is an **audit + test phase only**. No production source changes. No YouTube downloads.
No production E2E.

---

## 2. Baseline

- **Git HEAD:** `8223def93de6618a756f5d12d567927e8ab29aec` (Phase 10F implementation commit)
- **Working tree:** clean (only test + docs added in this phase)
- Phase 10F report and Phase 10E report confirmed present.

---

## 3. rank_videos() Implementation

**Source:** `app/services/material.py`, `rank_videos()` (line ~1449)

The pre-download resolution filter in `rank_videos()`:

```python
# Filter: known-bad resolution (skip tiny clips)
rendition = info.get("rendition") or {}
w = rendition.get("width", 0) or 0
h = rendition.get("height", 0) or 0
if w > 0 and h > 0:               # ← guard: only when resolution is KNOWN
    if w < _MATERIAL_MIN_WIDTH or h < _MATERIAL_MIN_HEIGHT:
        continue                  # ← skip candidate
```

**Key behavior:** The 480×480 filter ONLY applies when resolution is **known** (`w > 0 and h > 0`).
When resolution is unknown (`w=0, h=0`), the candidate is **retained** and passed to download
+ post-download quality gate.

The function also:
- Filters by `duration < minimum_duration` (always applies when duration known)
- Scores by relevance, duration, resolution via `_score_candidate()`
- Accepts all aspect ratios (landscape clips are reframed downstream)

**1. Fields used:** `item.source_info["rendition"]["width"]`, `["height"]`, `item.duration`, `item.source_info`

**2. Where resolution filtering occurs:** Inside the `for item in items:` loop, guarded by `if w > 0 and h > 0`.

**3. When width/height are known:** Candidates with known resolution below 480×480 are skipped.

**4. When width/height are unknown:** The guard `w > 0 and h > 0` is False → filter skipped → candidate **retained**.

**5. extract_flat=True effect:** YouTube search uses `extract_flat=True` (line 1358 in `search_videos_youtube`). With flat extraction, yt-dlp returns entries without `formats` array. The code at line ~1408 attempts `entry.get("formats")` → empty list → `rendition = None` → `w=0, h=0`. So **YouTube candidates have unknown resolution at ranking time**.

**6. Is the 480×480 filter active for YouTube search results?** NO. Because YouTube flat search produces `rendition=None` → `w=0, h=0` → the `if w > 0 and h > 0` guard is False → filter does not trigger → candidate is **retained**.

**7. Other pre-download resolution filters:** `_filter_materials_by_aspect()` filters by aspect orientation (portrait/landscape/square), not resolution. It is called in `_search_videos_with_cache()` for cache hits. No other resolution pre-download filter exists.

**8. Duration filters:** `minimum_duration` filter in `rank_videos()` always applies when duration is known. `search_videos_youtube()` also filters by `duration < minimum_duration` at search time (line ~1389). This is orthogonal to the resolution gate.

---

## 4. Resolution Metadata Availability

| Provider | Source resolution known at search? | rendition populated? | 480×480 filter applies? |
|---|---|---|---|
| **YouTube** | NO (`extract_flat=True`, formats empty) | None (w=0, h=0) | NO |
| **Pexels** | YES (API returns width/height) | Yes | YES |
| **Pixabay** | YES (API returns width/height) | Yes | YES |

**CONFIRMED:** For YouTube, resolution is unknown at ranking time. The 480×480 pre-download
filter in `rank_videos()` cannot block YouTube candidates because it only fires when
`w > 0 and h > 0`.

---

## 5. YouTube Pipeline Trace

```
search_videos_youtube()            extract_flat=True, no formats → rendition=None
        ↓
_search_videos_with_cache()        passes items through (caching wrapper)
        ↓
rank_videos()                      w=0, h=0 → 480×480 filter SKIPPED → candidate RETAINED
        ↓
_download_material_item()          yt_dlp downloads the video (best[ext=mp4][height<=720])
        ↓
save_video_youtube()               returns local file path
        ↓
_validate_downloaded_clip()        VideoFileClip reads actual resolution → NEW gate applies
        ↓
combine_videos()                   scale-to-cover + crop → 1080×1920
```

**CONFIRMED:** Resolution is unknown at search/ranking time for YouTube, and known only after
download via `_validate_downloaded_clip()`. This is the intended design — YouTube's flat
search cannot provide per-format resolution without a full extraction (which requires
download/simulate).

**Answer to core questions:**
- Can a known 360×640 YouTube candidate reach `_validate_downloaded_clip()`? **YES** — because
  at search time, resolution is unknown (rendition=None), so `rank_videos()` does not filter it.
  After download, `_validate_downloaded_clip()` reads the actual resolution (360×640) and the
  new gate accepts it (effective 360 ≥ 250).
- Can a known 854×480 candidate reach it? **YES** — same reasoning. After download, the gate
  accepts it (effective 270 ≥ 250).

**Important note for Pexels/Pixabay:** These providers return known resolution at search time.
However, Pexels already filters to exact target aspect at search time (matching `video_width`
and `video_height`), and Pixabay requires `w >= video_width`. So Pexels/Pixabay candidates
that pass their search-time filters are already at or above target resolution — they would
pass both the 480×480 pre-download filter and the 250 effective gate. No conflict.

**INFERRED:** The 360×640 portrait case that Phase 10F intends to accept is reachable in
production via the YouTube provider, which is the source of landscape-portrait candidates
that pass Phase 10F's broader acceptance.

---

## 6. Synthetic Ranking Results

**TESTED** via `test/services/test_quality_gate_10f1.py` (17 tests, all passing):

### rank_videos() with KNOWN resolution

| Source | rank_videos() |
|---|---|
| 360×640 | REJECTS (w 360 < 480) |
| 640×360 | REJECTS (h 360 < 480) |
| 854×480 | KEEPS (both ≥ 480) |
| 1280×720 | KEEPS |
| 1920×1080 | KEEPS |
| 480×854 | KEEPS |
| 1080×1920 | KEEPS |

### rank_videos() with UNKNOWN resolution (YouTube extract_flat scenario)

| Source | rank_videos() |
|---|---|
| Any (w=0, h=0) | KEEPS (guard `w > 0 and h > 0` is False) |

### Output-aware gate (_validate_downloaded_clip after download)

| Source | Effective min | Gate result |
|---|---|---|
| 640×360 | 202.5 | REJECT |
| 854×480 | 270.0 | ACCEPT |
| 1280×720 | 405.0 | ACCEPT |
| 1920×1080 | 607.5 | ACCEPT |
| 360×640 | 360.0 | ACCEPT |
| 480×854 | 480.0 | ACCEPT |
| 320×180 | 101.2 | REJECT |
| 426×240 | 135.0 | REJECT |

---

## 7. Combined Decision Matrix

```
SOURCE
    ↓
RANK_VIDEOS (pre-download)
    ↓
DOWNLOAD (yt_dlp / HTTP)
    ↓
VALIDATE DOWNLOADED CLIP (post-download, output-aware gate)
```

| Source | Rank (known res) | Rank (YouTube) | Reaches gate? | Output gate | Final |
|---|---|---|---|---|---|
| 360×640 | REJECTS | KEEPS | YES (YT) | ACCEPT (360≥250) | **ACCEPT** |
| 640×360 | REJECTS | KEEPS | YES (YT) | REJECT (202<250) | REJECT |
| 854×480 | KEEPS | KEEPS | YES | ACCEPT (270≥250) | ACCEPT |
| 1280×720 | KEEPS | KEEPS | YES | ACCEPT (405≥250) | ACCEPT |
| 1920×1080 | KEEPS | KEEPS | YES | ACCEPT (608≥250) | ACCEPT |
| 320×180 | REJECTS (known) | KEEPS (YT) | YES (YT) | REJECT (101<250) | REJECT |
| 426×240 | REJECTS (known) | KEEPS (YT) | YES (YT) | REJECT (135<250) | REJECT |

**Key distinction:** "can reach post-download gate" (rank_videos decision) is NOT the same as
"post-download gate would accept" (output-aware gate decision). For YouTube candidates with
unknown resolution, `rank_videos()` always KEEPS them, so the output-aware gate is always
reachable. The gate then makes the final accept/reject decision.

---

## 8. Interaction with Phase 10F

**CONFIRMED:** Phase 10F's intended behavioral improvement (360×640 portrait: REJECT→ACCEPT)
is reachable in production via the YouTube provider, because:
1. YouTube search uses `extract_flat=True` → resolution unknown at ranking time
2. `rank_videos()` skips the 480×480 filter when resolution is unknown (`w=0, h=0`)
3. The candidate reaches `_download_material_item()` → downloaded via yt_dlp
4. `_validate_downloaded_clip()` reads the actual resolution and applies the output-aware
   250 threshold → 360 ≥ 250 → ACCEPT

**No contradiction found.** The pre-download 480×480 filter in `rank_videos()` does not
block YouTube candidates because resolution metadata is unavailable at search time for
that provider.

---

## 9. Test Results

| Suite | Result |
|---|---|
| Phase 10F.1 new tests | **17 passed** |
| Phase 10F tests | 45 passed |
| Phase 10E tests | 37 passed, 60 subtests |
| Media cleanup tests | (included in full regression) |
| Material tests | (included in full regression) |
| Video tests | (included in full regression) |
| **Full regression** | **840 passed, 11 skipped, 5497 subtests** |

Zero unexpected regressions. Test count increased from 823 (Phase 10F) to 840 (Phase 10F +
17 Phase 10F.1 tests).

---

## 10. Production Safety

**CONFIRMED** — all production invariants match baseline:

| Invariant | Value |
|---|---|
| Production MP4 count | 158 (unchanged) |
| Task-directory count | 133 (unchanged) |
| cache_videos file count | 0 (unchanged) |
| cache_videos total size | 20,480 bytes (unchanged) |
| config.toml SHA256 | `2a8d89a6...` (unchanged) |
| factory.db SHA256 | `ad0e6df9...` (unchanged) |
| factory.db size | 151,552 bytes (unchanged) |
| `_MATERIAL_MIN_WIDTH` | 480 (preserved) |
| `_MATERIAL_MIN_HEIGHT` | 480 (preserved) |
| `_EFFECTIVE_MIN_DIMENSION` | 250.0 (preserved) |
| yt-dlp format | `best[ext=mp4][height<=720]` (unchanged) |
| Container | running, 0 restarts |

YouTube downloads: **0**
Production jobs: **0**
Production E2E: **0**
Docker deployment: **NONE** (no docker commands executed)

---

## 11. Conclusion

**NO BLOCKER.** The pre-download 480×480 resolution filter in `rank_videos()` does NOT
prevent YouTube candidates from reaching the Phase 10F output-aware quality gate. This is
because YouTube search uses `extract_flat=True`, which means format-level resolution metadata
(rendition width/height) is not available at search time. The `if w > 0 and h > 0` guard
in `rank_videos()` skips the 480×480 filter when resolution is unknown, so YouTube candidates
are always retained through ranking and reach the post-download gate.

The intended Phase 10F behavioral improvement (360×640 portrait REJECT→ACCEPT) is fully
reachable via the YouTube provider in the actual pipeline.

**No changes to `rank_videos()` or any production source code were made in this audit phase.**
The Phase 10F implementation is frozen and unchanged.

---

## 12. Recommendation for 10G

No upstream blocker requires fixing. Phase 10G can proceed with deployment/runtime
verification:

1. Deploy the Phase 10F code change (container rebuild + recreate, NOT `docker restart`).
2. Run a targeted YouTube E2E test with a scene whose visual query produces a 360×640
   portrait candidate, to confirm the new gate accepts it and the reframe produces valid
   1080×1920 output.
3. Monitor production logs for any unexpected accepts of low-quality footage.

If, in a future phase, it becomes desirable to also apply the output-aware model as a
**pre-download** filter for Pexels/Pixabay candidates (which DO have known resolution at
search time), that can be done by calling `_validate_reframe_resolution()` in `rank_videos()`
instead of the raw 480×480 check. This is out of scope for 10F/10F.1.
