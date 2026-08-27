# YouTube Footage Architecture

## Status: AUDIT COMPLETE → DESIGN PHASE

---

## 1. Current Architecture

```
topic
  → topic_planner.py          (Factory: concrete topics via MPT /api/v1/scripts)
  → scene_planner.py          (Factory: NARRASI/VISUAL scenes via MPT /api/v1/scripts)
  → batch_planner.py          (Factory: one job PER (topic, provider), scenes persisted as sidecar JSON)
  → worker.py                 (Factory: create_video → poll → claim assets → validate)
  → MPT /api/v1/videos        (Factory → MPT: sends subject, script, video_scenes, video_source)
  → task.py::generate_script  (MPT: scene narrations → TTS script)
  → task.py::generate_audio   (MPT: edge_tts with WordBoundary → SubMaker)
  → task.py::generate_subtitle (MPT: SRT from SubMaker)
  → scene_durations.py        (MPT: compute_scene_durations from TTS word cues)
  → material.py::download_videos_by_scene
                             (MPT: per-scene → provider search → portrait filter → ONE clip)
  → video.py::combine_videos  (MPT: scale-to-fit + BLACK PAD → 1080×1920)
  → video.py::generate_video  (MPT: burn-in subtitles → final MP4)
  → factory asset claim       (Factory: download final MP4 via HTTP → AssetStore)
  → video_validator.py        (Factory: ffprobe → 1080×1920 h264/aac)
```

**Key architectural facts (from audit evidence):**

- **Footage resolution lives entirely in MPT** (`material.py`). The Factory only
  sends `video_scenes` (narration + visual_query per scene) and a single
  `video_source` string to MPT's `/api/v1/videos` endpoint. The Factory has no
  footage-resolution code of its own.
- **One provider per render.** `download_videos_by_scene()` takes a single
  `source` parameter (`"pexels" | "pixabay" | "coverr" | "wavespeed"`). The
  Factory creates one job per provider, but each MPT render uses exactly one.
- **Landscape footage is EXCLUDED, not reframed.** `_filter_materials_by_aspect()`
  in `material.py` (line 264) rejects any clip whose height ≤ width for portrait
  output. The combine step (`video.py` line 654-674) then pads the accepted
  portrait clips with **black bars** if their aspect ratio doesn't exactly match.
- **No ranking.** `download_videos_by_scene` picks `usable[0]` — the first
  aspect-matching clip from the search results, with no scoring by relevance,
  resolution, duration, or quality.
- **No YouTube provider.** The provider dispatch
  (`_provider_and_searcher`, line 1274) maps source names to search functions.
  YouTube is absent; the only `youtube` references in MPT are for *upload
  posting* (`upload_post.py`), not footage sourcing.

---

## 2. Provider Abstraction

**There IS an abstraction, but it is informal — not a class/interface.**

The existing pattern (MPT `material.py`):

| Component | What it does |
|---|---|
| `MaterialInfo` (schema.py:55) | Dataclass: `provider: str`, `url: str`, `duration: int`, `source_info: dict` |
| `search_videos_<name>()` | Provider-specific search fn. Signature: `(search_term, minimum_duration, video_aspect) → List[MaterialInfo]` |
| `_provider_and_searcher(source)` | Maps `"pexels"`→`search_videos_pexels`, `"pixabay"`→`search_videos_pixabay`, `"coverr"`→`search_videos_coverr`, `"wavespeed"`→`generate_videos_wavespeed` |
| `save_video(url, save_dir)` | Downloads a single clip via HTTP `requests.get` |
| `_search_videos_with_cache()` | 24h file-based JSON cache keyed by (provider, search_term, minimum_duration, video_aspect) |
| `_material_source_record()` | Whitelist-reconstructs provenance dict from `MaterialInfo` |
| `_persist_material_sources()` | Writes material_sources into the task's `script_data.json` sidecar via `task_artifacts.patch_script_data` |

**Decision:** DO NOT create a second abstraction layer. Extend the existing
function-dispatch pattern in `_provider_and_searcher` by adding a
`search_videos_youtube` function and a `"youtube"` case. The
`download_videos_by_scene` function already iterates providers generically;
it only needs to accept a fallback provider list.

**Do NOT remove or rename existing providers.** Add YouTube alongside them.

---

## 3. Recommended YouTube Integration Point

### Where it goes

**`MPT` `app/services/material.py`** — specifically:

1. **New function:** `search_videos_youtube(search_term, minimum_duration, video_aspect) -> List[MaterialInfo]`
   - Uses `yt_dlp` Python API with `extract_flat=True` for search (works without auth)
   - Populates `MaterialInfo` with YouTube-specific `source_info` (video_id, channel, view_count, etc.)
   - Respects `video_aspect` filtering (accepts landscape for reframing, see §4)

2. **Extend `_provider_and_searcher`:** add `"youtube"` → `search_videos_youtube`

3. **Extend `download_videos_by_scene`:** accept `sources: list[str]` (ordered fallback)
   instead of a single `source: str`. For each scene, try providers in order
   until one returns usable material. If ALL fail for a scene → fail-clean.

4. **New function:** `save_video_youtube(video_url, save_dir, ydl_opts) -> str`
   - Uses `yt_dlp.YoutubeDL` to download the video
   - Supports cookie-based auth via configurable cookie file path
   - Returns the local file path on success, `""` on failure

### Config additions (MPT config.toml / config.example.toml)

```toml
# YouTube provider (additional provider, never replaces Pexels/Pixabay/Coverr)
youtube_cookies_file = ""      # Path to yt-dlp cookies.txt (optional; enables download)
youtube_enabled = false        # Gate: only attempt YouTube when true
youtube_max_height = 720       # Max resolution to request (bandwidth/latency)
```

### STOP CONDITION — YouTube Download Credentials

**Audit evidence (tested 2026-08-27):**

| Capability | yt-dlp result |
|---|---|
| YouTube search (ytsearch) | ✅ Works |
| Metadata extraction (flat playlist) | ✅ Works (id, title, duration, channel, view_count) |
| License/CC detection | ❌ Not available in flat mode; requires YouTube Data API v3 |
| Full metadata (resolution, aspect ratio) | ❌ Requires full extraction (blocked by bot detection) |
| Video download | ❌ **403 Forbidden** — "Sign in to confirm you're not a bot" |
| Cookie-based download | ✅ Should work (cookies from a logged-in browser session) |
| YouTube Data API v3 key | ❌ Not configured (no API key in config.toml) |

**No secrets are available** (`list_secrets` returned "No secrets available").
No browser cookies found. No YouTube API key in config.

**Recommendation:** Proceed with building the YouTube provider with cookie
support. The provider searches and extracts metadata without auth (works now),
and downloads with cookie-based auth (fail-clean without cookies). This does
NOT block the Pexels/Pixabay/Coverr pipeline — YouTube is an optional
additional provider that fails-clean when credentials are unavailable.

---

## 4. MPT Current Resize Behavior

### What MPT does today (`video.py` combine_videos, lines 654-674)

```python
clip_ratio = clip.w / clip.h          # source aspect (W/H)
video_ratio = video_width / video_height  # target aspect (1080/1920 = 0.5625)

if clip_ratio == video_ratio:
    clip = clip.resized(new_size=(video_width, video_height))   # exact match
else:
    # SCALE TO FIT + BLACK PAD (letterbox/pillarbox)
    if clip_ratio > video_ratio:
        scale_factor = video_width / clip_w   # scale to fit width
    else:
        scale_factor = video_height / clip_h   # scale to fit height

    new_width = int(clip_w * scale_factor)
    new_height = int(clip_h * scale_factor)

    background = ColorClip(size=(video_width, video_height), color=(0,0,0)).with_duration(clip_duration)
    clip_resized = clip.resized(new_size=(new_width, new_height)).with_position("center")
    clip = CompositeVideoClip([background, clip_resized])
```

### What this means for landscape → portrait

| Question | Answer (with evidence) |
|---|---|
| 1. Can MPT convert landscape → 9:16? | **Yes**, but with black bars |
| 2. Stretch or crop/pad? | **Pad** (black bars via `ColorClip` background) |
| 3. Is landscape video stretched? | **No** — aspect ratio is preserved. But the visible content area is small. |
| 4. Can subject be cut off? | **No** — padding adds black space, never crops. |
| 5. Portrait source correct? | **Yes** — if exact 9:16, direct resize; else padded. |
| 6. Square source correct? | **Yes** — but padded (not cropped). |
| 7. Mixed aspect ratio safe? | **Yes** — each clip is padded independently, then concatenated. |
| 8. Output is 1080×1920? | **Yes** — `video_width, video_height = aspect.to_resolution()` = (1080, 1920). |
| 9. Audio sync? | **Yes** — audio is a separate file, combined in `generate_video()` (line 1218+). |
| 10. Crop before or after trim? | **N/A** — no crop occurs; clip is trimmed via `subclipped()` in `combine_videos`. |
| 11. Black bar risk? | **HIGH** — landscape 1920×1080 → 1080×607 → ~32% visible, ~68% black bars. |
| 12. Black tail risk? | **FIXED** — `generate_video()` line 1255: `video_clip = video_clip.with_duration(source_video_clip.duration)` anchors composite to real video length. |

### What MPT does NOT do

- **No scale-to-cover.** MPT scales to *fit* the target (smaller dimension), then
  pads the remaining space with black. This means ~68% of a landscape clip
  becomes black bars in portrait output.
- **No crop.** No content is ever removed; black bars are always added.
- **No aspect filtering in the combine step.** The combine step accepts any
  aspect ratio and pads as needed. The *search* step filters for portrait-only
  material, which means landscape footage is never even considered.

### Test gap

The existing tests (`test_scene_combine.py`) mock `_FakeVideoClip` with
`size = (1080, 1920)` — i.e., all test clips are already the target dimension.
The resize/crop logic for mismatched-aspect clips is **never exercised with
real video**. `test_video_black_tail.py` does use real ffmpeg-generated video,
but only for the black-tail regression, not for aspect reframing.

---

## 5. Gap Analysis

| Gap | Current State | Required | Severity |
|---|---|---|---|
| **YouTube provider** | Not present | yt-dlp search + download + metadata | MEDIUM |
| **Scale-to-cover reframing** | Scale-to-fit + black pad | Scale-to-cover + crop | HIGH |
| **Subject-safe crop** | No crop at all | Face/person/subject-aware crop | MEDIUM |
| **Multi-provider fallback per scene** | Single provider per render | Try Pexels → Pixabay → Coverr → YouTube per scene | HIGH |
| **Footage ranking** | Picks `usable[0]` (first result) | Score by relevance, duration, resolution, crop-safety | MEDIUM |
| **Landscape footage acceptance** | Filtered out by `_filter_materials_by_aspect` | Accept landscape + reframe intelligently | HIGH |
| **Quality gate on footage** | Only final MP4 validated (factory) | Validate each clip: readable, duration, resolution, codec | MEDIUM |
| **Provenance for YouTube** | No field for license/origin | Store provider, video_id, source_url, title, channel, query, timestamp, license | LOW |
| **Fail-clean per scene** | Raises RuntimeError (scene-aware) | Must try all allowed providers before failing | HIGH |
| **No cross-scene substitution** | Enforced in `download_videos_by_scene` | Must preserve | CRITICAL (already works) |

---

## 6. Proposed Changes

### Phase 1: Smart 9:16 Reframing (MPT `video.py`)

**Change `combine_videos()` resize logic** (line 654-674):

Replace "scale to fit + black pad" with "scale to cover + subject-safe crop":

```
scale-to-cover:  scale=1080:1920:force_original_aspect_ratio=increase
subject-safe crop:  crop=1080:1920:x_offset:y_offset
```

- Compute crop offset using `cropdetect` (FFmpeg) to find content bounds
- If face detection available (optional, with OpenCV model): offset toward faces
- Fallback: center crop (`(sw-ow)/2, (sh-oh)/2`)
- **Preserve existing behavior for exact aspect matches** (no change to portrait/1:1 clips)
- **Preserve black-tail fix** (line 1255 already anchors composite duration)

**New isolated module:** `app/services/reframe.py`
- `compute_crop_offset(video_path, target_w, target_h) -> (x, y)`
- Uses FFmpeg `cropdetect` on a sample of frames (lightweight, no ML dependency)
- Optional face detection via OpenCV `FaceDetectorYN` if model file is configured
- Center crop fallback always available

**Why this is safe to change:**
- The existing black-pad behavior produces poor visual quality (~68% black bars)
- Scale-to-cover + crop is strictly better for landscape footage
- Exact-match clips (portrait 9:16, square 1:1) keep the same `resized()` path
- Tests use mock clips with exact (1080,1920) size — no regression risk

### Phase 2: YouTube Provider (MPT `material.py`)

**New function:** `search_videos_youtube()` — uses `yt_dlp` Python API
- `ytsearch:` query with `extract_flat=True` for search + metadata
- Returns `List[MaterialInfo]` with YouTube-specific `source_info`
- Accepts landscape videos (they'll be reframed in Phase 1)
- Does NOT filter by aspect — lets the combine step handle all aspect ratios

**Extend `_provider_and_searcher`:** add `"youtube"` → `search_videos_youtube`

**New function:** `save_video_youtube(video_url, save_dir) -> str`
- Uses `yt_dlp.YoutubeDL` to download the video
- Config-driven cookie file path (`youtube_cookies_file`)
- Falls back to `save_video()` (HTTP GET) if yt-dlp download fails
- Returns local path or `""` on failure

### Phase 3: Multi-Provider Fallback + Ranking (MPT `material.py`)

**Extend `download_videos_by_scene`:**
- Accept `sources: list[str]` (ordered fallback) instead of `source: str`
- For each scene, try each provider in order until one returns usable material
- **Ranking** within each provider's results: score by:
  - Semantic relevance (query match — basic text overlap)
  - Duration (≥ minimum, ≤ reasonable max)
  - Resolution (prefer highest)
  - Portrait/landscape suitability for reframing
  - Duplicate risk (exclude already-claimed asset_ids)
- **Fail-clean:** if ALL providers fail for a scene → raise RuntimeError (existing behavior)

### Phase 4: Quality Gate (MPT `material.py`)

**Extend `download_videos_by_scene` validation:**
- After download, validate each clip with `ffprobe`:
  - File exists and size > 0
  - Video stream exists, codec is h264 or h265
  - Duration ≥ max_clip_duration (or scene duration for scene-aware)
  - Resolution ≥ minimum (480×480, matching `is_material_resolution_acceptable`)
- Reject clip if validation fails, try next candidate from the same provider
- If no valid candidate from any provider → fail-clean for the scene

### Phase 5: Provenance (MPT `material.py`)

**Extend `_material_source_record`:**
- Add YouTube-specific fields: `video_id`, `source_url`, `license_status`
- Add `download_timestamp` (ISO 8601 UTC)
- Add `license_status`: `"downloadable" | "reusable" | "license_unknown"` for YouTube,
  `"stock_license"` for Pexels/Pixabay/Coverr
- These are stored in the existing `script_data.json` sidecar (no DB schema change)

### Factory-Side Changes

**Minimal factory-side changes:**
- `mpt_client.py`: Accept `video_sources: list[str]` instead of single `source: str` in the payload
- `worker.py`: Forward the provider list to MPT
- `batch_planner.py`: When `sources=["pexels","pixabay","youtube"]`, create jobs that carry
  the full fallback list (not one job per provider)
- `pipeline.py`: Wire the provider list into the production pipeline
- `video_validator.py`: Already validates final MP4; no change needed
- `assets.py`: Already tracks provenance; no change needed

---

## 7. Files Affected

### MPT changes (new + modified):

| File | Change | Risk |
|---|---|---|
| `app/services/material.py` | Add `search_videos_youtube()`, extend `_provider_and_searcher`, extend `download_videos_by_scene` for multi-provider + ranking + quality gate | MEDIUM — new code, existing paths unchanged |
| `app/services/reframe.py` | **NEW** — isolated scale-to-cover + subject-safe crop module | LOW — new file |
| `app/services/video.py` | Modify `combine_videos()` resize block to use scale-to-cover + crop | MEDIUM — core render path |
| `app/services/video.py` | Import `reframe` module | LOW |
| `app/models/schema.py` | Add `video_sources: Optional[List[str]]` to `VideoParams` (backward-compatible: `video_source` still works) | LOW |
| `app/services/task.py` | Forward `video_sources` list to `download_videos_by_scene` in scene-aware path | LOW |
| `config.example.toml` | Document `youtube_cookies_file`, `youtube_enabled` | LOW |
| `pyproject.toml` | Add `yt-dlp` as dependency | LOW |
| `requirements.txt` | Add `yt-dlp` (if used) | LOW |

### Factory changes (new + modified):

| File | Change | Risk |
|---|---|---|
| `app/mpt_client.py` | Accept `video_sources` list in payload | LOW |
| `app/worker.py` | Forward `video_sources` to MPT | LOW |
| `app/batch_planner.py` | Pass provider fallback list to jobs | LOW |
| `app/pipeline.py` | Wire provider fallback list | LOW |

### New test files:

| File | Purpose |
|---|---|
| `app/test/services/test_youtube_provider.py` (MPT) | Unit tests for YouTube search/metadata/ranking |
| `app/test/services/test_reframe.py` (MPT) | Unit tests for scale-to-cover + crop (18 cases) |
| `tests/test_universal_footage_resolver.py` (factory) | Integration test for multi-provider fallback |
| `tests/test_smart_reframing.py` (factory) | Integration test for reframing validation |

---

## 8. Files Explicitly NOT Affected

| File | Reason |
|---|---|
| `factory.db` | NO database schema changes. Provenance stored in MPT's existing `script_data.json` sidecar. |
| `app/jobs.py` (factory) | No schema change needed; scenes sidecar already exists. |
| `app/assets.py` (factory) | Asset tracking already works; no provenance schema change. |
| `app/video_validator.py` (factory) | Already validates final MP4; no change needed. |
| `app/content.py` (factory) | Visual queries already generated; no change needed. |
| `app/scene_planner.py` (factory) | Scene planning already works; no change needed. |
| `app/topic_planner.py` (factory) | Topic generation already works; no change needed. |
| `app/services/material_cache.py` | Cache logic unchanged; YouTube adds a new provider key. |
| `app/services/llm.py` | Script system prompt unchanged; no new prompts. |
| `app/services/voice.py` | TTS/WordBoundary unchanged. |
| `app/services/subtitle.py` | Subtitle generation unchanged. |
| `app/services/sonilo.py` | BGM unchanged. |
| `app/services/loomloom.py` | LoomLoom provider unchanged. |

---

## 9. Test Strategy

### TDD approach (RED first, then GREEN)

**New reframing tests (MPT `test/services/test_reframe.py`):**

| # | Test | Type |
|---|---|---|
| 1 | landscape 16:9 → 1080×1920, no stretching | Real ffmpeg |
| 2 | portrait 9:16 → 1080×1920 | Real ffmpeg |
| 3 | square 1:1 → 1080×1920 | Real ffmpeg |
| 4 | No stretching (pixel aspect ratio preserved) | Real ffmpeg |
| 5 | Correct output dimensions (1080×1920) | Real ffmpeg |
| 6 | Subject-safe crop (center, no face cut) | Real ffmpeg |
| 7 | Person on left — crop keeps them visible | Synthetic video |
| 8 | Person on right — crop keeps them visible | Synthetic video |
| 9 | Subject in center — crop centered | Synthetic video |
| 10 | No-face fallback (center crop) | Synthetic video |
| 11 | Mixed aspect ratio in one render | Real ffmpeg |
| 12 | Invalid video → handled gracefully | Error case |
| 13 | Too-short video → handled | Error case |

**YouTube provider tests (MPT `test/services/test_youtube_provider.py`):**

| # | Test | Type |
|---|---|---|
| 14 | YouTube search returns candidates (mocked yt-dlp) | Mock |
| 15 | YouTube download failure → fail-clean | Mock |
| 16 | YouTube unavailable → provider fallback | Mock |
| 17 | Candidate ranking by relevance/duration/resolution | Mock |
| 18 | Provenance stored (provider, video_id, title, channel, url, license) | Mock |

**Factory-level tests:**

| # | Test | Type |
|---|---|---|
| 19 | Provider fallback (Pexels → YouTube) | Mock |
| 20 | Fail-clean (all providers fail → RuntimeError) | Mock |
| 21 | No cross-scene substitution | Mock |

**Regression suite:**
- MPT existing tests (scene_materials, scene_combine, scene_durations, scene_plan, video, video_black_tail): must remain green
- Factory existing tests (202 passed, 2 skipped): must remain green

**Baseline confirmed:**
- Factory: `202 passed, 2 skipped` (verified 2026-08-27)
- MPT: `127 passed, 55 subtests passed` (relevant tests: scene_materials, scene_combine, scene_durations, scene_plan, video, video_black_tail, material, schema)

---

## 10. E2E Strategy

### Isolated E2E (production-like, NOT touching production)

1. **Isolated DB:** `data/e2e_test.db` (factory.db untouched)
2. **Isolated video dir:** `data/videos_e2e_test/`
3. **Isolated task dir:** MPT task with unique ID
4. **No watchdog:** ProductionRunner not started

### Pipeline:

```
niche="misteri"
  → topic_planner (MPT /api/v1/scripts)
  → 6 scenes (UniversalScenePlanner, MPT /api/v1/scripts)
  → batch_planner.create_batch(niche="misteri", count=1, providers=["pexels","pixabay","youtube"])
  → worker.run_job (MPT create_video with video_scenes + video_sources)
  → MPT task.py: TTS → scene_durations → download_videos_by_scene(multi-provider)
  → MPT combine_videos with smart reframing
  → MPT generate_video (burned-in subtitles #FFFF00)
  → factory claim → VideoValidator.validate
  → ffprobe verification
```

### Acceptance checks (26 criteria from §11):
- Use `ffprobe` for codec/duration/resolution
- Use `ffmpeg -vf blackdetect` for black bars/tail
- Use frame sampling for pixel analysis (subtitle color, stretching)
- Use SRT diff for subtitle narration match
- Compare factory.db hash before/after

---

## 11. Rollback Strategy

### If YouTube provider causes issues:

1. **Disable YouTube** via `config.toml`: `youtube_enabled = false`
2. **Revert `_provider_and_searcher`**: remove `"youtube"` case (2 lines)
3. **Revert `download_videos_by_scene`**: restore single `source` parameter
4. No factory.db or production data affected (provider is a runtime config)
5. No MPT source changes outside `material.py`, `material.py imports`, `video.py` reframing

### If smart reframing causes issues:

1. **Feature flag in `video.py`**: `use_smart_reframe = config.app.get("use_smart_reframe", True)`
2. When `False`, existing scale-to-fit + black-pad behavior is restored
3. Reframing module (`reframe.py`) is isolated — easy to disable

### Backup steps (before production rollout):

1. `cp data/factory.db data/factory.db.bak`
2. `git tag -a pre-youtube-integration -m "before youtube integration"`
3. Verify service state: `curl /health`
4. Verify DB state: `sqlite3 data/factory.db ".tables"`
5. Verify MPT state: `MPT_BASE_URL=http://127.0.0.1:8080 curl /health`
6. Verify provider credentials: `grep video_source config.toml`, `grep youtube config.toml`
7. Verify disk space: `df -h /opt`

---

## 12. STOP Conditions Documented

| Condition | Status | Evidence |
|---|---|---|
| Provider abstraction existing tidak cocok | ✅ N/A — abstraction IS suitable | `_provider_and_searcher` dispatch pattern can extend to YouTube |
| MPT harus dimodifikasi secara besar | ⚠️ Minor changes needed | `material.py` + `video.py` reframing + `schema.py` backward-compatible field |
| DB schema perlu diubah | ✅ No | Provenance via existing sidecar JSON, no DB change |
| YouTube membutuhkan credential yang tidak tersedia | ⚠️ Download requires cookies | yt-dlp search works, download blocked by bot detection; no cookies available |
| yt-dlp tidak dapat digunakan secara reliable | ✅ Search reliable, download needs cookies | yt-dlp 2026.08.19; search returns metadata, download returns 403 without auth |
| FFmpeg tidak mampu melakukan reframing | ✅ FFmpeg CAN reframe | `scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920` verified (1080×1920 output) |
| Subject-aware crop membutuhkan dependency berat | ⚠️ Face detection needs model | OpenCV `FaceDetectorYN` model not downloadable; fallback to FFmpeg `cropdetect` + center crop |
| Production service harus direstart | ✅ No restart needed | YouTube is runtime-configurable |
| Acceptance criterion bertentangan dengan architecture | ✅ No conflict | Multi-provider per scene aligns with existing `_provider_and_searcher` pattern |
