# Phase 10E — Quality Gate Design Spike + Landscape→Portrait Validation

## STATUS: PASS ✅

This is a **design spike + test-only** phase. No production source changes were made. No YouTube downloads, no production jobs, no config changes, no Docker deployment changes. All production invariants verified unchanged.

---

## 1. Executive Summary

**Core finding**: The current quality gate (`_validate_downloaded_clip`) uses a **global minimum dimension check** (`width < 480 OR height < 480`) that rejects technically-reframeable landscape sources. The actual reframe pipeline in `combine_videos()` uses **scale-to-cover + center-crop** (not stretching, not padding), which can produce valid 1080×1920 output from any source resolution ≥ some minimum.

**Key distinction established**: "Technically valid" (output achievable without distortion/bars) ≠ "quality-acceptable" (upscale factor reasonable).

| Case | Resolution | Gate | Reframe | Upscale | Recommendation |
|---|---|---|---|---|---|
| 640×360 landscape | 640×360 | **REJECT** | ✅ YES | 5.33× (severe) | Keep rejected — quality too poor |
| 854×480 landscape | 854×480 | ACCEPT | ✅ YES | 4.00× (moderate) | Accept — at threshold boundary |
| 1280×720 landscape | 1280×720 | ACCEPT | ✅ YES | 2.67× (moderate) | Accept |
| 1920×1080 landscape | 1920×1080 | ACCEPT | ✅ YES | 1.78× (none) | Accept — best quality |

**Recommended design for Phase 10F**: Orientation-aware quality gate based on **effective output resolution after scale-to-cover**, not source resolution alone. The gate should reject sources where the effective source resolution (the crop region before upscale) falls below a minimum threshold.

---

## 2. Current Quality Gate

**Location**: `app/services/material.py`

```python
_MATERIAL_MIN_WIDTH = 480   # line 1179
_MATERIAL_MIN_HEIGHT = 480  # line 1180
```

**Gate logic** (`_validate_downloaded_clip`, line 1252):

```python
if w < _MATERIAL_MIN_WIDTH or h < _MATERIAL_MIN_HEIGHT:
    logger.warning(f"quality gate: resolution {w}x{h} below minimum ...")
    return False
```

**Where gate is invoked**: `download_videos_by_scene()` at line 1782:
```python
if not _validate_downloaded_clip(saved_video_path, min_duration=max_clip_duration):
    # Clean up rejected file
    ...
    continue  # try next ranked candidate
```

**Also in `rank_videos()`** at line 1380 (pre-download filter):
```python
if w < _MATERIAL_MIN_WIDTH or h < _MATERIAL_MIN_HEIGHT:
    continue  # skip candidate before downloading
```

**Current behavior**: The gate checks **source** width and height independently. A 640×360 landscape source has `width=640 ≥ 480` (passes) but `height=360 < 480` (fails) → **REJECTED**.

**CONFIRMED**: `_MATERIAL_MIN_WIDTH=480`, `_MATERIAL_MIN_HEIGHT=480` remain unchanged at container checksums `99aa2fd4...` (Phase 10E verified via runtime import).

---

## 3. Actual Call Graph

**CONFIRMED** call graph (verified from source, not assumed):

```
download_videos_by_scene(task_id, video_scenes, sources, video_aspect)
    │
    ├── for each scene:
    │   ├── _search_videos_with_cache(provider, search_term, min_duration, video_aspect)
    │   │   └── provider.search_videos(search_term, min_duration, video_aspect)
    │   │       ├── Pexels API → search → download URL → save_video()
    │   │       ├── Pixabay API → search → download URL → save_video()
    │   │       └── YouTube URL → save_video_youtube()
    │   │           └── yt-dlp download (format: best[ext=mp4][height<=720])
    │   │
    │   ├── rank_videos(items, search_term, min_duration, video_aspect)
    │   │   └── filters: duration < min → skip
    │   │       filters: w < 480 or h < 480 → skip (PRE-DOWNLOAD filter)
    │   │       scores: duration (0.3) + relevance (0.4) + resolution (0.3)
    │   │
    │   ├── for each ranked candidate:
    │   │   ├── _download_material_item(item, provider, material_directory)
    │   │   │   └── save_video() or save_video_youtube()
    │   │   │       └── yt_dlp.YoutubeDL.download() → cache_videos/vid-HASH.mp4
    │   │   │
    │   │   ├── _validate_downloaded_clip(saved_video_path, min_duration)
    │   │   │   ├── ffprobe: file exists, size > 0
    │   │   │   ├── VideoFileClip: codec, duration, fps, size
    │   │   │   ├── duration > 0, fps > 0
    │   │   │   └── w < 480 OR h < 480 → REJECT → delete file → try next
    │   │   │
    │   │   └── if accepted: _material_source_record() → add to video_paths[]
    │   │
    │   └── if no candidate passed: FAIL-CLEAN scene
    │
    └── video_paths[] → combine_videos(combined_video_path, video_paths, ...)
        │
        ├── VideoAspect(portrait) → to_resolution() → (1080, 1920)
        │
        ├── for each source clip:
        │   ├── _open_video_clip_quietly(path).subclipped(start, end)
        │   │
        │   ├── clip_w, clip_h = clip.size
        │   │
        │   ├── if clip_w != 1080 or clip_h != 1920:
        │   │   ├── clip_ratio = clip.w / clip.h
        │   │   ├── video_ratio = 1080/1920 = 0.5625
        │   │   │
        │   │   ├── if clip_ratio == video_ratio:
        │   │   │   └── uniform scale to (1080, 1920)
        │   │   │
        │   │   └── else:  ← SCALE-TO-COVER + CROP (the actual reframe path)
        │   │       ├── if clip_ratio > video_ratio:  # source wider
        │   │       │   scale_factor = 1920 / clip_h   # scale by height
        │   │       │ else:
        │   │       │   scale_factor = 1080 / clip_w   # scale by width
        │   │       ├── new_w = round(clip_w * scale_factor)
        │   │       ├── new_h = round(clip_h * scale_factor)
        │   │       ├── clip_resized = clip.resized(new_size=(new_w, new_h))
        │   │       ├── center crop offsets computed
        │   │       └── clip = clip_resized.cropped(x1=x, y1=y,
        │   │           width=1080, height=1920)
        │   │
        │   └── _write_videofile_with_codec_fallback(clip, temp-clip-N.mp4)
        │
        ├── processed_clips → temp-clip-N.mp4 files
        │
        ├── try:
        │     concat_video_clips_with_ffmpeg(clip_files, output_file, ...)
        │   finally:
        │     delete_files(clip_files)  ← P1: temp cleanup
        │
        └── return combined_video_path (final MP4)
```

### Key observations:

1. **`reframe.py` is NOT in the runtime call graph.** It is defined (`reframe_to_portrait()`) and imported (`from app.services import reframe` at video.py:38), but it is **only referenced in a comment** (video.py:674). The actual reframe is done **inline** in `combine_videos()` at video.py:666-700 using MoviePy's `resized()` + `cropped()`.

2. **Quality gate runs BEFORE reframe.** `_validate_downloaded_clip()` is called in `download_videos_by_scene()` (line 1782), which happens before `combine_videos()`. A 640×360 source is rejected at the gate and never reaches the reframe pipeline.

3. **Aspect ratio is known at gate time.** `VideoAspect(portrait)` → `to_resolution()` returns `(1080, 1920)`. The gate has access to the target aspect ratio if it chooses to use it.

4. **Source dimensions are available** via `VideoFileClip(video_path).size` in `_validate_downloaded_clip()` (line 1273).

---

## 4. Actual Reframe/Resize Path

**CONFIRMED**: The reframe path is in `video.py:655-700` inside `combine_videos()`.

```python
# Line 581-582: target resolution
aspect = VideoAspect(video_aspect)
video_width, video_height = aspect.to_resolution()  # (1080, 1920) for portrait

# Line 657-660: check if source needs reframing
if clip_w != video_width or clip_h != video_height:
    clip_ratio = clip.w / clip.h
    video_ratio = video_width / video_height  # 0.5625

# Line 676-681: scale-to-cover (NOT stretch)
if clip_ratio > video_ratio:
    # Source is wider than target → scale by height
    scale_factor = video_height / clip_h
else:
    # Source is taller than target → scale by width
    scale_factor = video_width / clip_w

# Line 683-700: resize + center crop
new_width = max(1, round(clip_w * scale_factor))
new_height = max(1, round(clip_h * scale_factor))
clip_resized = clip.resized(new_size=(new_width, new_height))

if new_width > video_width:
    x = (new_width - video_width) // 2
    y = 0
elif new_height > video_height:
    x = 0
    y = (new_height - video_height) // 2
else:
    x, y = 0, 0

clip = clip_resized.cropped(x1=x, y1=y, width=video_width, height=video_height)
```

### Properties of this transform:

| Property | How it's ensured |
|---|---|
| No stretching | `resized()` uses proportional scale_factor |
| No black bars | scale-to-cover always fills target (one dimension ≥ target, other ≥ target) |
| No rotation | No `.rotate()` or `.vflip()` calls |
| Output = 1080×1920 | Final `.cropped()` enforces exact dimensions |
| Deterministic | Center-crop offsets computed deterministically |

### Runtime verification (actual `combine_videos()` with synthetic 640×360):

```
Input:  640×360 landscape, 12s, 24fps
Output: 1080×1920 portrait, 3.0s, 30fps
Scale factor: 5.33x (height-based)
Scaled before crop: 3413×1920
Crop: x=1166, y=0 (center width crop)
Effective source region: 202.5×360
Result: ✅ 1080×1920, no distortion, no black bars, no rotation
```

---

## 5. Mathematical Analysis

### Scale-to-cover transform formula

For source (W, H) → target (1080, 1920):

```
src_ratio = W / H
target_ratio = 1080 / 1920 = 0.5625

if src_ratio > target_ratio:  # source wider than target
    scale_factor = 1920 / H   # scale by height
else:                          # source taller (or same ratio)
    scale_factor = 1080 / W   # scale by width

scaled_w = round(W * scale_factor)
scaled_h = round(H * scale_factor)

# Center crop to 1080×1920
if scaled_w > 1080:
    crop_x = (scaled_w - 1080) / 2
    crop_y = 0
elif scaled_h > 1920:
    crop_x = 0
    crop_y = (scaled_h - 1920) / 2
else:
    crop_x = crop_y = 0

# Effective source region retained (maps to output)
retained_w = 1080 / scale_factor
retained_h = 1920 / scale_factor
pct_retained = (retained_w * retained_h) / (W * H) * 100
```

### Complete resolution matrix

| Case | Source | Orientation | Scale | Retained Src | Retained % | Current Gate | Upscale | Reframe Valid |
|---|---|---|---|---|---|---|---|---|
| 640×360 | 640×360 | landscape | 5.33× | 202×360 | 31.6% | **REJECT** | severe | ✅ |
| 854×480 | 854×480 | landscape | 4.00× | 270×480 | 31.6% | ACCEPT | moderate | ✅ |
| 1280×720 | 1280×720 | landscape | 2.67× | 405×720 | 31.6% | ACCEPT | moderate | ✅ |
| 1920×1080 | 1920×1080 | landscape | 1.78× | 608×1080 | 31.6% | ACCEPT | none | ✅ |
| 360×640 | 360×640 | portrait | 3.00× | 360×640 | 100.0% | **REJECT** | moderate | ✅ |
| 480×854 | 480×854 | portrait | 2.25× | 480×853 | 99.9% | ACCEPT | moderate | ✅ |
| 720×1280 | 720×1280 | portrait | 1.50× | 720×1280 | 100.0% | ACCEPT | none | ✅ |
| 1080×1920 | 1080×1920 | portrait | 1.00× | 1080×1920 | 100.0% | ACCEPT | none | ✅ |
| 480×480 | 480×480 | square | 4.00× | 270×480 | 56.2% | ACCEPT | moderate | ✅ |
| 720×720 | 720×720 | square | 2.67× | 405×720 | 56.2% | ACCEPT | moderate | ✅ |
| 1080×1080 | 1080×1080 | square | 1.78× | 608×1080 | 56.2% | ACCEPT | none | ✅ |
| 1920×800 | 1920×800 | landscape | 2.40× | 450×800 | 23.4% | ACCEPT | moderate | ✅ |
| 2560×1080 | 2560×1080 | landscape | 1.78× | 608×1080 | 23.7% | ACCEPT | none | ✅ |
| 320×180 | 320×180 | landscape | 10.67× | 101×180 | 31.6% | **REJECT** | severe | ✅ |
| 426×240 | 426×240 | landscape | 8.00× | 135×240 | 31.7% | **REJECT** | severe | ✅ |

### Cases currently REJECTED but technically reframeable:

| Case | Resolution | Upscale | Why rejected | Reframe possible? |
|---|---|---|---|---|
| 640×360 | 640×360 | 5.33× (severe) | height 360 < 480 | ✅ Yes, but quality poor |
| 360×640 | 360×640 | 3.00× (moderate) | width 360 < 480 | ✅ Yes, but moderate quality loss |
| 320×180 | 320×180 | 10.67× (severe) | both < 480 | ✅ Yes, but severe quality loss |
| 426×240 | 426×240 | 8.00× (severe) | both < 480 | ✅ Yes, but severe quality loss |

### Key mathematical insights:

1. **All landscape sources have ~31.6% pixel retention** after scale-to-cover crop to 9:16. This is inherent to the aspect ratio mismatch (16:9 → 9:16). A 16:9 source loses 2/3 of its width when cropped to portrait.

2. **Portrait sources have ~100% retention** (or ~99.9% due to rounding). This means portrait sources are the "native" format — no pixel waste.

3. **Square sources have ~56.2% retention**. They lose more than landscape because the crop is more aggressive.

4. **Extremely wide sources (1920×800, 2560×1080) have ~23% retention** — even more pixel waste. The scale factor is 1.78-2.40×, but only 1/4 of the source width ends up in the output.

5. **The effective source resolution** (the crop region before upscale) is the critical quality metric:
   - 640×360 → effective: 202×360 (72,900 pixels) → 5.33× upscale → severe
   - 1920×1080 → effective: 608×1080 (656,100 pixels) → 1.78× upscale → acceptable
   - 320×180 → effective: 101×180 (18,180 pixels) → 10.67× upscale → severe

---

## 6. Resolution/Orientation Test Matrix

Full matrix verified by `TestResolutionMatrix` (37 tests, 60 subtests):

### Landscape (target ratio 0.5625, scale by height)
| Source | Scale | Scaled (pre-crop) | Crop | Retained Src | Upscale | Gate | Valid |
|---|---|---|---|---|---|---|---|
| 640×360 | 5.33× | 3413×1920 | x=1166, crop W | 202×360 | severe | REJECT | ✅ |
| 854×480 | 4.00× | 3416×1920 | x=1168, crop W | 270×480 | moderate | ACCEPT | ✅ |
| 1280×720 | 2.67× | 3413×1920 | x=1166, crop W | 405×720 | moderate | ACCEPT | ✅ |
| 1920×1080 | 1.78× | 3413×1920 | x=1166, crop W | 608×1080 | none | ACCEPT | ✅ |
| 1920×800 | 2.40× | 4608×1920 | x=1764, crop W | 450×800 | moderate | ACCEPT | ✅ |
| 2560×1080 | 1.78× | 4551×1920 | x=1735, crop W | 608×1080 | none | ACCEPT | ✅ |
| 320×180 | 10.67× | 3413×1920 | x=1166, crop W | 101×180 | severe | REJECT | ✅ |
| 426×240 | 8.00× | 3408×1920 | x=1164, crop W | 135×240 | severe | REJECT | ✅ |

### Portrait (target ratio 0.5625, scale by width or height)
| Source | Scale | Scaled (pre-crop) | Crop | Retained Src | Upscale | Gate | Valid |
|---|---|---|---|---|---|---|---|
| 360×640 | 3.00× | 1080×1920 | none | 360×640 | moderate | REJECT | ✅ |
| 480×854 | 2.25× | 1080×1922 | y=1, crop H | 480×853 | moderate | ACCEPT | ✅ |
| 720×1280 | 1.50× | 1080×1920 | none | 720×1280 | none | ACCEPT | ✅ |
| 1080×1920 | 1.00× | 1080×1920 | none | 1080×1920 | none | ACCEPT | ✅ |

### Square (scale by height)
| Source | Scale | Scaled (pre-crop) | Crop | Retained Src | Upscale | Gate | Valid |
|---|---|---|---|---|---|---|---|
| 480×480 | 4.00× | 1920×1920 | x=420, crop W | 270×480 | moderate | ACCEPT | ✅ |
| 720×720 | 2.67× | 1920×1920 | x=420, crop W | 405×720 | moderate | ACCEPT | ✅ |
| 1080×1080 | 1.78× | 1920×1920 | x=420, crop W | 608×1080 | none | ACCEPT | ✅ |

---

## 7. Option A Analysis — Preserve Global 480×480

### Description
Keep `_MATERIAL_MIN_WIDTH=480` and `_MATERIAL_MIN_HEIGHT=480` unchanged. No quality gate change.

### Pros
- ✅ Zero behavior change — safest option
- ✅ Zero risk of regression
- ✅ All Phase 10C/10D tests remain valid
- ✅ Production safety maximized

### Cons
- ❌ Valid landscape 640×360 is still rejected (height 360 < 480)
- ❌ Doesn't address the YouTube provider use case
- ❌ The gate conflates "resolution" with "quality"

### Evaluation
**REJECTED as preferred direction** — does not address the core problem. However, it is the **fallback** if Phase 10F determines no change should be made.

---

## 8. Option B Analysis — Orientation-Aware Threshold

### Description
Replace the single global minimum with orientation-dependent thresholds:

```python
# CONCEPT (not implemented — Phase 10E is design-only)
if source_is_landscape:
    min_source_width = 640   # enough for acceptable crop
    min_source_height = 360  # landscape source, height is the smaller dimension
elif source_is_portrait:
    min_source_width = 480   # portrait native, keep existing
    min_source_height = 854  # portrait native
else:  # square
    min_source_width = 480
    min_source_height = 480
```

### Analysis of the 640×360 case under Option B

| Metric | Value | Acceptable? |
|---|---|---|
| Source | 640×360 landscape | — |
| Upscale factor | 5.33× | ❌ Severe (far above 2× threshold) |
| Effective source region | 202×360 (72,900 pixels) | ❌ Below 720p equivalent |
| Pixel retention | 31.6% | Standard for 16:9→9:16 crop |
| Current gate rejection | height 360 < 480 | ❌ Rejected |
| Option B acceptance | width 640 ≥ 640, height 360 ≥ 360 | ✅ Accepted |

### Pros
- ✅ Simple to implement
- ✅ Addresses the 640×360 rejection
- ✅ Orientation-aware logic is intuitive

### Cons
- ❌ Accepts 640×360 which has 5.33× upscale — quality is poor
- ❌ Doesn't directly measure output quality — uses proxy thresholds
- ❌ Hard to determine the "right" threshold without data
- ❌ Would also accept 320×180 (if threshold were 320), 426×240, etc.

### Evaluation
**REJECTED as preferred direction** — uses arbitrary source-dimension thresholds that don't directly measure output quality. Accepting 640×360 with 5.33× upscale is questionable quality for a video generation pipeline.

---

## 9. Option C Analysis — Output-Aware Validation

### Description
Simulate the actual scale-to-cover + crop transform and validate the **effective output quality**:

```python
# CONCEPT (not implemented — Phase 10E is design-only)
def _validate_for_reframe(w, h, target_w=1080, target_h=1920):
    src_ratio = w / h
    target_ratio = target_w / target_h
    
    if src_ratio > target_ratio:
        scale = target_h / h
    else:
        scale = target_w / w
    
    # Effective source resolution that maps to each output pixel
    effective_src_w = target_w / scale
    effective_src_h = target_h / scale
    
    # Minimum quality: effective source should have enough pixels
    # e.g., at least 480 effective pixels in the shorter dimension
    effective_min = min(effective_src_w, effective_src_h)
    
    return effective_min >= 360  # or some threshold
```

### Analysis of the 640×360 case under Option C

| Metric | Value |
|---|---|
| Source | 640×360 landscape |
| Scale factor | 5.33× |
| Effective source region | 202×360 |
| Effective min dimension | 202 (width) |
| With threshold 360: | 202 < 360 → **REJECT** |
| With threshold 200: | 202 < 200 → **REJECT** (barely) |
| With threshold 200 (width is 202): | 202 ≥ 200 → **ACCEPT** (barely) |

For comparison, 854×480:
- Scale: 4.00×
- Effective source: 270×480
- Effective min: 270

1920×1080:
- Scale: 1.78×
- Effective source: 608×1080
- Effective min: 608

### Pros
- ✅ Directly measures output quality, not source proxy
- ✅ Orientation-agnostic: works for all source aspect ratios
- ✅ Threshold is meaningful: "the crop region must have at least N pixels in its shortest dimension"
- ✅ Naturally handles landscape, portrait, square, wide, and tiny sources
- ✅ No stretching of the quality concept

### Cons
- ❌ More complex to implement
- ❌ Need to determine the right effective-minimum threshold
- ❌ Slightly more CPU per validation (compute scale factor)

### Threshold analysis for Option C

| Threshold | 640×360 accepted? | 854×480 accepted? | 1280×720 accepted? | 320×180 accepted? |
|---|---|---|---|---|
| 200 | ✅ Yes (202) | ✅ Yes (270) | ✅ Yes (405) | ❌ No (101) |
| 250 | ❌ No (202) | ✅ Yes (270) | ✅ Yes (405) | ❌ No (101) |
| 270 | ❌ No (202) | ✅ Yes (270) | ✅ Yes (405) | ❌ No (101) |
| 300 | ❌ No (202) | ❌ No (270) | ✅ Yes (405) | ❌ No (101) |

A threshold of **200** would accept 640×360 (202 effective). This is borderline — 5.33× upscale of a 640×360 source.

A threshold of **250** would reject 640×360 (202 < 250) but accept 854×480 (270 ≥ 250) and 1280×720 (405 ≥ 250). This seems like the safer choice.

### Evaluation
**RECOMMENDED as preferred direction** for Phase 10F. It directly answers "can this source produce a quality output?" rather than "is this source resolution high enough?" The effective-source-resolution metric is the actual quality determinant after scale-to-cover + crop.

**Caveat**: A threshold of 200 would accept 640×360, which has 5.33× upscale. Recommendation for Phase 10F: set effective-min threshold at **250** or higher to reject 640×360 while accepting 854×480 and above. This is a data-driven choice: the 640×360 source's effective resolution (202) is below the 250 threshold, so it remains rejected.

---

## 10. Recommended Design

### Recommended approach: Option C (Output-Aware Validation)

**Core principle**: Validate the **effective source resolution** (the crop region after scale-to-cover) rather than the raw source dimensions.

#### Proposed quality gate logic for Phase 10F:

```python
# Phase 10F PROPOSAL (NOT IMPLEMENTED in Phase 10E)

def _validate_for_portrait_reframe(w: int, h: int,
                                   target_w: int = 1080,
                                   target_h: int = 1920,
                                   min_effective_dim: int = 250) -> bool:
    """Check if source can produce quality portrait output via scale-to-cover + crop.

    Returns True if the effective source resolution (crop region before upscale)
    has at least min_effective_dim pixels in its shortest dimension.
    """
    src_ratio = w / h
    target_ratio = target_w / target_h

    if src_ratio > target_ratio:
        scale_factor = target_h / h  # scale by height
    else:
        scale_factor = target_w / w  # scale by width

    # Effective source region that maps to output
    effective_w = target_w / scale_factor
    effective_h = target_h / scale_factor

    # Minimum of the two dimensions determines quality
    effective_min = min(effective_w, effective_h)

    return effective_min >= min_effective_dim
```

#### Integration with existing gate:

The current `_validate_downloaded_clip()` would be **extended** (not replaced) to add an orientation-aware check:

```python
# In _validate_downloaded_clip(), AFTER existing checks:

# Orientation-aware reframe quality check
# (only for clips that pass the minimum decode checks)
if video_aspect == VideoAspect.portrait:
    if not _validate_for_portrait_reframe(w, h, min_effective_dim=250):
        logger.warning(
            f"quality gate: effective source resolution "
            f"{target_w/scale:.0f}x{target_h/scale:.0f} below minimum "
            f"for portrait reframing, src={w}x{h}"
        )
        return False
```

#### Why threshold = 250?

| Source | Effective min dim | Accepted (≥250)? |
|---|---|---|
| 640×360 | 202 | ❌ No (correctly rejected — 5.33× upscale is too much) |
| 854×480 | 270 | ✅ Yes (4.00× upscale — acceptable for web video) |
| 1280×720 | 405 | ✅ Yes (2.67× upscale — good) |
| 1920×1080 | 608 | ✅ Yes (1.78× upscale — excellent) |
| 360×640 | 360 | ✅ Yes (3.00× upscale — portrait native, acceptable) |
| 320×180 | 101 | ❌ No (correctly rejected) |

This threshold **keeps 640×360 rejected** (quality too poor) while **accepting 854×480 and above** (acceptable quality). The key insight: 640×360 landscape → portrait requires 5.33× upscale, which produces visibly degraded output. 854×480 → portrait requires 4.0× upscale, which is acceptable for web/social video.

#### Alternative: dual-threshold approach

If the team prefers a simpler gate, a dual-threshold could work:

```python
# For landscape sources: minimum width 640, minimum height 360
# (640×360 is the YouTube 360p standard — widely available)
# PLUS the existing 480×480 check as a fallback
```

But this still doesn't capture the quality dimension. The effective-resolution approach is superior.

### Why NOT just lower the threshold to 360?

| Issue | Detail |
|---|---|
| `w < 480 or h < 480` | 360×640 portrait also rejected (width 360 < 480) |
| `w < 360 or h < 360` | 320×180 also passes (height 180 < 360 → rejected) |
| But: 640×360 at height=360 | Would be accepted, but 5.33× upscale is poor quality |
| And: 360×640 portrait | Would be accepted, 3.0× upscale — acceptable for portrait native |

A simple height threshold doesn't distinguish between "640×360 landscape needs 5.33× upscale" and "360×640 portrait needs 3.0× upscale but is already in the right aspect ratio". The effective-resolution model does.

---

## 11. Rejected Designs + Reasons

### Rejected: Simple threshold lowering (height 480 → 360)

**Reason**: Does not distinguish landscape (5.33× upscale) from portrait (3.0× but native aspect). A global minimum can't be orientation-aware. Also, accepting 640×360 with 5.33× upscale produces visibly degraded output — the quality gate should protect quality, not just enable completion.

### Rejected: Option A (keep 480×480 global)

**Reason**: Does not address the core problem. The quality gate would continue rejecting technically-reframeable YouTube landscape sources. Acceptable only as a fallback.

### Rejected: Option B (orientation-aware source thresholds)

**Reason**: Uses proxy thresholds (source dimensions) rather than measuring actual output quality. The "right" threshold values are arbitrary without data. Would accept 640×360 with 5.33× upscale, which is questionable quality.

### Accepted direction: Option C (output-aware effective resolution)

**Reason**: Directly measures the quality determinant — the effective source resolution that maps to each output pixel. Threshold is meaningful and orientation-agnostic. Recommended for Phase 10F.

---

## 12. Regression Test Results

### Phase 10E test suite (`test_quality_gate_landscape.py`)
```
37 passed, 60 subtests passed in 124.41s
```

Test breakdown:
- `TestCurrentQualityGateBehavior`: 6 tests — verifies current 480×480 gate behavior ✅
- `TestReframePathVerification`: 5 tests — actual `combine_videos()` reframe for 640×360, 854×480, 1280×720, 1920×1080, 1080×1920 ✅
- `TestReframeQualityAssertions`: 6 tests — no stretching, no black bars, no rotation, 9:16 aspect, clean decode, temp clip cleanup ✅
- `TestScaleToCoverMath`: 6 tests — mathematical transform verification ✅
- `TestQualityModelUpscale`: 7 tests — upscale factor analysis for all key cases ✅
- `TestResolutionMatrix`: 4 tests (15 cases × subtests) — comprehensive matrix ✅
- `TestKeyFindingGateMismatch`: 3 tests — core finding verification ✅

### Existing Phase 10C test suite (`test_media_cleanup.py`)
```
29 passed in 0.79s
```

### Existing material tests (`test_material.py`)
```
42 passed, 5 subtests passed in 0.48s
```

### Existing video tests (`test_video.py`)
```
45 passed, 44 subtests passed in 3.78s
```

### Full service test suite (regression)
```
778 passed, 11 skipped, 5497 subtests passed in 195.65s
```

**All tests pass. No regressions detected.** ✅

---

## 13. Production Safety Verification

| Check | Status | Evidence |
|---|---|---|
| Production MP4 count | ✅ 158 (unchanged) | `find storage/tasks -name '*.mp4' | wc -l` |
| Production task dirs | ✅ 133 (unchanged) | `find storage/tasks -maxdepth 1 -type d` |
| cache_videos file count | ✅ 0 (unchanged) | `find storage/cache_videos -type f` |
| cache_videos total size | ✅ 20KB (unchanged) | `du -sb storage/cache_videos` |
| config.toml SHA256 | ✅ `2a8d89a6...` (unchanged) | `sha256sum config.toml` |
| `_MATERIAL_MIN_WIDTH` | ✅ 480 (unchanged) | Runtime import verified |
| `_MATERIAL_MIN_HEIGHT` | ✅ 480 (unchanged) | Runtime import verified |
| yt-dlp format | ✅ `best[ext=mp4][height<=720]` (unchanged) | `inspect.getsource` verified |
| yt-dlp `nopart` | ✅ absent (unchanged) | `inspect.getsource` verified |
| YouTube downloads | ✅ 0 | No YouTube operations performed |
| Production jobs | ✅ 0 created | All tests use isolated temp dirs |
| Production E2E | ✅ 0 | No combine_videos runs on production data |
| Docker deployment | ✅ unchanged | No Docker operations |
| nginx | ✅ unchanged | Not touched |
| Secrets exposed | ✅ none | No API keys in tests or commands |
| Startup cleanup hook | ✅ intact | Phase 10C startup hook still running |
| Temp clip cleanup | ✅ intact | Phase 10C try/finally still in place |
| Cleanup Phase 10C | ✅ intact | Phase 10C/10D changes not modified |
| Combined video lifecycle | ✅ intact | No combined-*.mp4 deleted |
| Final video lifecycle | ✅ intact | No final-*.mp4 deleted |
| Scene-aware path | ✅ intact | No changes to scene path |

---

## 14. Files Changed

### Created (Phase 10E only):
| File | Action |
|---|---|
| `test/services/test_quality_gate_landscape.py` | **Created** — 37 tests, 60 subtests for quality gate + reframe analysis |
| `docs/PHASE_10E_REPORT.md` | **Created** — this report |

### Modified:
None.

**NO production source files were modified in Phase 10E.** Only test files and documentation were added.

---

## 15. Files NOT Changed (Production Preserved)

| File | Status |
|---|---|
| `app/services/material.py` | ✅ Unchanged (Phase 10C code intact) |
| `app/services/video.py` | ✅ Unchanged (Phase 10C try/finally intact) |
| `app/asgi.py` | ✅ Unchanged (startup cleanup hook intact) |
| `app/services/reframe.py` | ✅ Unchanged (NOT used in runtime pipeline) |
| `app/models/schema.py` | ✅ Unchanged |
| `app/models/const.py` | ✅ Unchanged |
| `app/models/config.py` | ✅ Unchanged |
| `app/services/state.py` | ✅ Unchanged |
| `app/services/task.py` | ✅ Unchanged |
| `config.toml` | ✅ Unchanged (SHA256 `2a8d89a6...`) |
| `storage/` | ✅ Unchanged (133 tasks, 158 MP4s) |
| `storage/cache_videos/` | ✅ Unchanged (0 files, 20KB) |
| Docker image | ✅ Unchanged (`afd296c29a70`) |
| Container deployment | ✅ Unchanged |
| nginx | ✅ Not applicable / unchanged |
| `_MATERIAL_MIN_WIDTH` | ✅ 480 (unchanged) |
| `_MATERIAL_MIN_HEIGHT` | ✅ 480 (unchanged) |
| yt-dlp format | ✅ `best[ext=mp4][height<=720]` (unchanged) |
| Quality gate logic | ✅ Not modified |
| Provider order | ✅ Pexels → Pixabay → YouTube (unchanged) |
| Cleanup behavior | ✅ Phase 10C/10D cleanup behavior (unchanged) |
| `reframe.py` | ✅ Not modified and NOT used in pipeline (only defined, not called) |

---

## 16. Decision / Next Phase Recommendation

### Decision: Option C (Output-Aware Validation) — PROPOSED for Phase 10F

**Rationale**: The current global 480×480 gate serves its original purpose (filtering tiny/unusable clips) but is too blunt for landscape→portrait reframe. The scale-to-cover + crop pipeline can produce valid 1080×1920 output from any source ≥ ~200 effective pixels, but quality degrades significantly with high upscale factors.

**Recommended Phase 10F implementation**:

1. **Extend** `_validate_downloaded_clip()` with an orientation-aware effective-resolution check
2. **Keep** the existing 480×480 check as a baseline (it catches genuinely tiny files)
3. **Add** `_validate_for_portrait_reframe(w, h, target_w=1080, target_h=1920, min_effective_dim=250)`
4. **Decision matrix**:
   - 640×360 → effective 202×360 → 202 < 250 → **REJECT** (5.33× upscale too poor)
   - 854×480 → effective 270×480 → 270 ≥ 250 → **ACCEPT** (4.0× upscale acceptable)
   - 1280×720 → effective 405×720 → 405 ≥ 250 → **ACCEPT**
   - 1920×1080 → effective 608×1080 → 608 ≥ 250 → **ACCEPT** (excellent quality)
5. **Keep** `rank_videos()` filter unchanged (pre-download filter stays at 480×480 as a safety net)
6. **Add** the effective-resolution check as a POST-download refinement in `_validate_downloaded_clip()`

**Why this is safe**:
- The effective-resolution check is **more restrictive** for 640×360 (still rejected) and **less restrictive** for 854×480+ (already accepted by current gate)
- No currently-accepted source would be newly rejected (854×480: effective 270 ≥ 250; 1280×720: effective 405 ≥ 250; etc.)
- The only behavioral change is: 640×360 remains rejected (same as before), and sources between 400-480 in the short dimension would be re-evaluated based on effective resolution rather than raw dimension

**Files that WOULD need modification in Phase 10F**:
- `app/services/material.py` — extend `_validate_downloaded_clip()`, add `_validate_for_portrait_reframe()`
- `app/models/schema.py` — may need VideoAspect import in material.py (already imported via `from app.models.schema import VideoAspect, VideoConcatMode, ...`)

---

## 17. Explicit Statement

> **NO PRODUCTION QUALITY-GATE CHANGE WAS IMPLEMENTED IN PHASE 10E.**

Phase 10E is a design spike + test-only phase. The quality gate (`_MATERIAL_MIN_WIDTH=480`, `_MATERIAL_MIN_HEIGHT=480`, `_validate_downloaded_clip()`) remains unchanged. The recommended design (Option C, effective-resolution threshold of 250) is **PROPOSED** for Phase 10F implementation, pending explicit approval.

All tests use isolated temporary directories and synthetic fixtures (ffmpeg-generated color clips). No YouTube footage was downloaded. No production jobs were created. No production E2E was run.

---

## Summary

| Area | Status |
|---|---|
| Quality gate (current) | ✅ PASS — 480×480 confirmed unchanged |
| Reframe path verification | ✅ PASS — 640×360 → 1080×1920 confirmed via actual `combine_videos()` |
| Mathematical analysis | ✅ PASS — 15 cases analyzed, scale-to-cover math verified |
| Quality model (upscale thresholds) | ✅ PASS — 3 tiers: none (≤2×), moderate (2-4×), severe (>4×) |
| Design options (A, B, C) | ✅ PASS — Option C recommended, Option A fallback, Option B rejected |
| Regression tests | ✅ PASS — 37 new + 778 existing tests pass |
| Production safety | ✅ PASS — all invariants unchanged |
| Runtime deployment | ✅ PASS — container healthy, no source changes deployed |
| No production changes | ✅ PASS — only test + docs files added |
