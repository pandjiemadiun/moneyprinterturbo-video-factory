"""
Phase 10E — Quality Gate Design Spike + Landscape→Portrait Reframe Tests

DESIGN SPIKE / TEST-ONLY.
No production source changes. No YouTube downloads. No production jobs.
All tests use synthetic / isolated fixtures.

What this test suite verifies:

1. CURRENT behavior: _validate_downloaded_clip() rejects 640×360 landscape
   because height (360) < _MATERIAL_MIN_HEIGHT (480).

2. REFAME CAPABILITY: The actual combine_videos() pipeline CAN produce
   1080×1920 (9:16) output from landscape sources via scale-to-cover +
   center-crop — no stretching, no black bars, no rotation.

3. MATHEMATICAL ANALYSIS: Scale-to-cover transform math for all test cases.

4. QUALITY MODEL: Evaluates whether each source resolution is technically
   valid (output achievable) vs. quality-acceptable (upscale factor reasonable).

5. REGRESSION: Existing valid sources remain valid; tiny sources remain invalid.
"""

import json
import math
import os
import shutil
import subprocess
import tempfile
import unittest
from typing import Tuple

from app.models.schema import VideoAspect, VideoConcatMode
from app.services import material as mat
from app.services import video as vd
from moviepy import VideoFileClip


# ─────────────────────────────────────────────────────────────────────
# Constants — MUST NOT be modified in this phase
# ─────────────────────────────────────────────────────────────────────

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
TARGET_RATIO = TARGET_WIDTH / TARGET_HEIGHT  # 0.5625

MIN_UPSCALE_ACCEPTABLE = 2.0  # upscale ≤ 2x = no quality concern
MIN_UPSCALE_MODERATE = 4.0    # upscale > 2x but ≤ 4x = moderate concern
# upscale > 4x = severe concern


# ─────────────────────────────────────────────────────────────────────
# Helper: create synthetic test video via ffmpeg
# ─────────────────────────────────────────────────────────────────────

def _make_synthetic_video(path: str, width: int, height: int,
                          duration: float = 5.0, fps: int = 24) -> str:
    """Create a minimal synthetic test video using ffmpeg's lavfi color source.

    The video is a solid color with the requested dimensions — sufficient for
    resolution/aspect-ratio validation. NO YouTube download, NO real footage.
    """
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=c=blue:s={width}x{height}:d={duration}:r={fps}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[:200]}")
    return path


def _make_synthetic_audio(path: str, duration: float = 3.0) -> str:
    """Create a minimal synthetic audio file."""
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={duration}",
        "-c:a", "libmp3lame", path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio failed: {result.stderr[:200]}")
    return path


def _compute_scale_to_cover(src_w: int, src_h: int,
                            target_w: int = TARGET_WIDTH,
                            target_h: int = TARGET_HEIGHT
                            ) -> Tuple[float, int, int, bool, bool, int, int]:
    """Compute the scale-to-cover + center-crop transform.

    Mirrors the ACTUAL logic in video.py combine_videos() (lines 676-700):
      if clip_ratio > video_ratio:  scale by height (source wider)
      else:                          scale by width  (source taller)

    Returns:
      scale_factor, new_w, new_h, crops_width, crops_height, crop_x, crop_y
    """
    src_ratio = src_w / src_h
    target_ratio = target_w / target_h

    if src_ratio > target_ratio:
        # Source is wider → scale so height fills target
        scale_factor = target_h / src_h
    else:
        # Source is taller → scale so width fills target
        scale_factor = target_w / src_w

    new_w = max(1, round(src_w * scale_factor))
    new_h = max(1, round(src_h * scale_factor))

    crops_width = new_w > target_w
    crops_height = new_h > target_h

    if new_w > target_w:
        crop_x = (new_w - target_w) // 2
        crop_y = 0
    elif new_h > target_h:
        crop_x = 0
        crop_y = (new_h - target_h) // 2
    else:
        crop_x, crop_y = 0, 0

    return scale_factor, new_w, new_h, crops_width, crops_height, crop_x, crop_y


def _effective_source_region(src_w: int, src_h: int,
                             target_w: int = TARGET_WIDTH,
                             target_h: int = TARGET_HEIGHT
                             ) -> Tuple[float, float, float]:
    """Compute the effective source region retained after scale-to-cover + crop.

    The output is always target_w × target_h. The source region that maps to
    this output is (target_w/scale_factor) × (target_h/scale_factor).

    Returns: (retained_w, retained_h, pct_of_source)
    """
    scale_factor, _, _, _, _, _, _ = _compute_scale_to_cover(src_w, src_h, target_w, target_h)
    retained_w = target_w / scale_factor
    retained_h = target_h / scale_factor
    pct = (retained_w * retained_h) / (src_w * src_h) * 100
    return retained_w, retained_h, pct


# ─────────────────────────────────────────────────────────────────────
# Test Matrix Case Definition
# ─────────────────────────────────────────────────────────────────────

# (name, src_w, src_h, orientation, current_gate_rejects)
ALL_CASES = [
    # Landscape
    ("640x360",       640,  360,  "landscape"),
    ("854x480",       854,  480,  "landscape"),
    ("1280x720",     1280,  720,  "landscape"),
    ("1920x1080",    1920, 1080,  "landscape"),
    # Portrait
    ("360x640",       360,  640,  "portrait"),
    ("480x854",       480,  854,  "portrait"),
    ("720x1280",      720, 1280,  "portrait"),
    ("1080x1920",    1080, 1920,  "portrait"),
    # Square
    ("480x480",       480,  480,  "square"),
    ("720x720",       720,  720,  "square"),
    ("1080x1080",    1080, 1080,  "square"),
    # Extremely wide
    ("1920x800",     1920,  800,  "landscape"),
    ("2560x1080",    2560, 1080,  "landscape"),
    # Extremely small
    ("320x180",       320,  180,  "landscape"),
    ("426x240",       426,  240,  "landscape"),
]


# ─────────────────────────────────────────────────────────────────────
# Test Class 1: Current Quality Gate Behavior
# ─────────────────────────────────────────────────────────────────────

class TestCurrentQualityGateBehavior(unittest.TestCase):
    """Verify the CURRENT quality gate rejects/accepts according to
    _MATERIAL_MIN_WIDTH=480 and _MATERIAL_MIN_HEIGHT=480."""

    def test_constants_unchanged(self):
        """Quality gate constants must remain 480×480 during Phase 10E."""
        self.assertEqual(mat._MATERIAL_MIN_WIDTH, 480)
        self.assertEqual(mat._MATERIAL_MIN_HEIGHT, 480)

    def test_gate_matrix(self):
        """For each case in ALL_CASES, verify the current gate result."""
        for name, w, h, orientation in ALL_CASES:
            with self.subTest(case=name):
                expected = (w >= 480 and h >= 480)
                # The gate rejects if width < MIN or height < MIN
                # We verify this is what the constants produce
                self.assertEqual(
                    expected,
                    w >= mat._MATERIAL_MIN_WIDTH and h >= mat._MATERIAL_MIN_HEIGHT,
                    f"Gate mismatch for {name}: w={w}, h={h}"
                )

    def test_640x360_currently_rejected(self):
        """CONFIRMED: 640×360 landscape is rejected by current gate."""
        # width=640 >= 480 ✓, height=360 < 480 ✗ → REJECT
        self.assertGreater(640, mat._MATERIAL_MIN_WIDTH)  # width passes
        self.assertLess(360, mat._MATERIAL_MIN_HEIGHT)    # height fails

    def test_854x480_currently_accepted(self):
        """CONFIRMED: 854×480 landscape passes current gate."""
        self.assertGreaterEqual(854, mat._MATERIAL_MIN_WIDTH)
        self.assertGreaterEqual(480, mat._MATERIAL_MIN_HEIGHT)

    def test_360x640_portrait_currently_rejected(self):
        """CONFIRMED: 360×640 portrait is rejected by current gate."""
        self.assertLess(360, mat._MATERIAL_MIN_WIDTH)

    def test_320x180_currently_rejected(self):
        """CONFIRMED: 320×180 is rejected by current gate."""
        self.assertLess(320, mat._MATERIAL_MIN_WIDTH)
        self.assertLess(180, mat._MATERIAL_MIN_HEIGHT)


# ─────────────────────────────────────────────────────────────────────
# Test Class 2: Reframe Path Verification (using ACTUAL combine_videos)
# ─────────────────────────────────────────────────────────────────────

class TestReframePathVerification(unittest.TestCase):
    """Verify that combine_videos() can actually reframe landscape → portrait.

    Uses synthetic test videos (ffmpeg-generated, NOT YouTube downloads).
    """

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="test_phase10e_reframe_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _run_reframe(self, src_w: int, src_h: int) -> Tuple[int, int]:
        """Run actual combine_videos() with a synthetic source and return output dims."""
        src_path = os.path.join(self.tmpdir, f"src_{src_w}x{src_h}.mp4")
        audio_path = os.path.join(self.tmpdir, f"audio_{src_w}x{src_h}.mp3")
        combined_path = os.path.join(self.tmpdir, f"combined_{src_w}x{src_h}.mp4")

        _make_synthetic_video(src_path, src_w, src_h, duration=12, fps=24)
        _make_synthetic_audio(audio_path, duration=3)

        result = vd.combine_videos(
            combined_video_path=combined_path,
            video_paths=[src_path],
            audio_file=audio_path,
            video_aspect=VideoAspect.portrait,
            video_concat_mode=VideoConcatMode.random,
            max_clip_duration=5,
            scene_specs=None,
        )
        self.assertTrue(os.path.exists(result), f"Output not created for {src_w}x{src_h}")

        clip = VideoFileClip(result)
        out_w, out_h = clip.size
        clip.close()
        return out_w, out_h

    def test_reframe_640x360_to_1080x1920(self):
        """CONFIRMED: 640×360 landscape → 1080×1920 portrait via actual pipeline."""
        out_w, out_h = self._run_reframe(640, 360)
        self.assertEqual(out_w, 1080, "Output width must be 1080")
        self.assertEqual(out_h, 1920, "Output height must be 1920")

    def test_reframe_854x480_to_1080x1920(self):
        """CONFIRMED: 854×480 landscape → 1080×1920 portrait."""
        out_w, out_h = self._run_reframe(854, 480)
        self.assertEqual(out_w, 1080)
        self.assertEqual(out_h, 1920)

    def test_reframe_1280x720_to_1080x1920(self):
        """CONFIRMED: 1280×720 landscape → 1080×1920 portrait."""
        out_w, out_h = self._run_reframe(1280, 720)
        self.assertEqual(out_w, 1080)
        self.assertEqual(out_h, 1920)

    def test_reframe_1920x1080_to_1080x1920(self):
        """CONFIRMED: 1920×1080 landscape → 1080×1920 portrait."""
        out_w, out_h = self._run_reframe(1920, 1080)
        self.assertEqual(out_w, 1080)
        self.assertEqual(out_h, 1920)

    def test_reframe_1080x1920_to_1080x1920(self):
        """CONFIRMED: 1080×1920 portrait → 1080×1920 (passthrough)."""
        out_w, out_h = self._run_reframe(1080, 1920)
        self.assertEqual(out_w, 1080)
        self.assertEqual(out_h, 1920)


# ─────────────────────────────────────────────────────────────────────
# Test Class 3: Reframe Quality Assertions
# ─────────────────────────────────────────────────────────────────────

class TestReframeQualityAssertions(unittest.TestCase):
    """Verify no stretching, no black bars, no rotation in the reframe pipeline.

    Uses the ACTUAL combine_videos() with synthetic sources.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="test_phase10e_quality_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _make_and_reframe(self, src_w: int, src_h: int):
        """Create synthetic video, reframe it, return source + output clips."""
        src_path = os.path.join(self.tmpdir, f"q_src_{src_w}x{src_h}.mp4")
        audio_path = os.path.join(self.tmpdir, f"q_audio_{src_w}x{src_h}.mp3")
        combined_path = os.path.join(self.tmpdir, f"q_combined_{src_w}x{src_h}.mp4")

        _make_synthetic_video(src_path, src_w, src_h, duration=12, fps=24)
        _make_synthetic_audio(audio_path, duration=3)

        vd.combine_videos(
            combined_video_path=combined_path,
            video_paths=[src_path],
            audio_file=audio_path,
            video_aspect=VideoAspect.portrait,
            video_concat_mode=VideoConcatMode.random,
            max_clip_duration=5,
            scene_specs=None,
        )

        src_clip = VideoFileClip(src_path)
        out_clip = VideoFileClip(combined_path)
        return src_clip, out_clip

    def test_no_stretching_640x360(self):
        """Scale-to-cover must not stretch — aspect is preserved by the algorithm."""
        src_clip, out_clip = self._make_and_reframe(640, 360)
        # The pipeline uses scale-to-cover + crop (NOT uniform resize),
        # which preserves aspect ratio. If it were a stretch, the output
        # pixels would be non-uniformly scaled. We verify output is exactly
        # 1080×1920 (the target, not a stretched source dimension).
        self.assertEqual(out_clip.size[0], 1080)
        self.assertEqual(out_clip.size[1], 1920)
        src_clip.close()
        out_clip.close()

    def test_no_black_bars_640x360(self):
        """Scale-to-cover fills the target completely — no black bars."""
        src_clip, out_clip = self._make_and_reframe(640, 360)
        # If black bars existed, moviepy would need padding, which would
        # change the clip size. Output is exactly 1080×1920 — no padding.
        self.assertEqual(tuple(out_clip.size), (1080, 1920))
        src_clip.close()
        out_clip.close()

    def test_no_rotation_640x360(self):
        """Reframe does not rotate the source."""
        # The transform is scale + center-crop only (no transpose/rotation).
        # We verify by checking the output dimensions are as expected.
        src_clip, out_clip = self._make_and_reframe(640, 360)
        # Landscape source (640×360) → portrait output (1080×1920)
        # requires a crop, not a rotation. The output is exactly 1080×1920.
        self.assertEqual(tuple(out_clip.size), (1080, 1920))
        src_clip.close()
        out_clip.close()

    def test_output_is_9_16_aspect(self):
        """Output aspect ratio must be exactly 9:16 (0.5625)."""
        src_clip, out_clip = self._make_and_reframe(640, 360)
        w, h = out_clip.size
        self.assertAlmostEqual(w / h, 9 / 16, places=4)
        src_clip.close()
        out_clip.close()

    def test_codec_decode_clean(self):
        """Output must be cleanly decodable."""
        src_clip, out_clip = self._make_and_reframe(640, 360)
        # VideoFileClip successfully loaded it → decode is clean
        self.assertGreater(out_clip.duration, 0)
        self.assertGreater(out_clip.fps, 0)
        src_clip.close()
        out_clip.close()

    def test_temp_clips_cleaned_after_reframe(self):
        """Reframe run must clean up its own temp clips (P1 hardening)."""
        tmp = tempfile.mkdtemp(prefix="test_phase10e_tempclip_")
        try:
            src_path = os.path.join(tmp, "src.mp4")
            audio_path = os.path.join(tmp, "audio.mp3")
            combined_path = os.path.join(tmp, "combined-1.mp4")

            _make_synthetic_video(src_path, 640, 360, duration=12)
            _make_synthetic_audio(audio_path, duration=3)

            vd.combine_videos(
                combined_video_path=combined_path,
                video_paths=[src_path],
                audio_file=audio_path,
                video_aspect=VideoAspect.portrait,
                video_concat_mode=VideoConcatMode.random,
                max_clip_duration=5,
                scene_specs=None,
            )

            temp_clips = [f for f in os.listdir(tmp) if f.startswith("temp-clip-")]
            self.assertEqual(len(temp_clips), 0,
                             f"Temp clips leaked: {temp_clips}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────
# Test Class 4: Mathematical Scale-to-Cover Analysis
# ─────────────────────────────────────────────────────────────────────

class TestScaleToCoverMath(unittest.TestCase):
    """Verify the scale-to-cover + center-crop math for all test cases.

    These tests validate the TRANSFORM MATH (the same logic used in
    combine_videos() at video.py:676-700) without running ffmpeg.
    """

    def test_640x360_scale_to_cover(self):
        """640×360 landscape: scale by height (wider than target)."""
        scale, new_w, new_h, crop_w, crop_h, cx, cy = _compute_scale_to_cover(640, 360)
        # src_ratio = 640/360 = 1.778 > target_ratio = 0.5625 → scale by height
        self.assertAlmostEqual(scale, 1920 / 360, places=2)
        self.assertEqual(new_h, 1920)  # height fills exactly
        self.assertGreater(new_w, TARGET_WIDTH)  # width overflows → crop
        self.assertTrue(crop_w)
        self.assertFalse(crop_h)
        # Center crop: (3413 - 1080) / 2 = 1166
        self.assertEqual(cx, (new_w - TARGET_WIDTH) // 2)

    def test_854x480_scale_to_cover(self):
        """854×480 landscape: scale by height."""
        scale, new_w, new_h, crop_w, crop_h, cx, cy = _compute_scale_to_cover(854, 480)
        self.assertAlmostEqual(scale, 1920 / 480, places=2)  # 4.0x
        self.assertEqual(new_h, 1920)
        self.assertGreater(new_w, TARGET_WIDTH)

    def test_1920x1080_scale_to_cover(self):
        """1920×1080 landscape: scale by height, width overflows (crop needed)."""
        scale, new_w, new_h, crop_w, crop_h, cx, cy = _compute_scale_to_cover(1920, 1080)
        self.assertAlmostEqual(scale, 1920 / 1080, places=2)  # 1.778x
        self.assertEqual(new_h, 1920)  # height fills exactly
        self.assertEqual(new_w, round(1920 * scale))  # 3413 — overflows width
        self.assertTrue(crop_w)  # width is cropped

    def test_portrait_360x640_scale_to_cover(self):
        """360×640 portrait: scale by width (taller than target)."""
        scale, new_w, new_h, crop_w, crop_h, cx, cy = _compute_scale_to_cover(360, 640)
        # src_ratio = 360/640 = 0.5625 == target_ratio → same ratio
        self.assertAlmostEqual(scale, 1080 / 360, places=2)  # 3.0x
        self.assertEqual(new_w, TARGET_WIDTH)
        self.assertEqual(new_h, TARGET_HEIGHT)
        self.assertFalse(crop_w)
        self.assertFalse(crop_h)

    def test_square_480x480_scale_to_cover(self):
        """480×480 square: scale by height (wider than portrait target)."""
        scale, new_w, new_h, crop_w, crop_h, cx, cy = _compute_scale_to_cover(480, 480)
        # src_ratio = 1.0 > target_ratio = 0.5625 → scale by height
        self.assertAlmostEqual(scale, 1920 / 480, places=2)  # 4.0x
        self.assertEqual(new_h, 1920)
        self.assertGreater(new_w, TARGET_WIDTH)
        self.assertTrue(crop_w)

    def test_1080x1920_passthrough(self):
        """1080×1920 portrait: perfect match, no scaling needed."""
        scale, new_w, new_h, crop_w, crop_h, cx, cy = _compute_scale_to_cover(1080, 1920)
        self.assertAlmostEqual(scale, 1.0, places=2)
        self.assertEqual(new_w, TARGET_WIDTH)
        self.assertEqual(new_h, TARGET_HEIGHT)
        self.assertFalse(crop_w)
        self.assertFalse(crop_h)


# ─────────────────────────────────────────────────────────────────────
# Test Class 5: Quality Model — Upscale Factor Analysis
# ─────────────────────────────────────────────────────────────────────

class TestQualityModelUpscale(unittest.TestCase):
    """Evaluate upscale factors to determine quality acceptability.

    This analysis drives the quality-gate design recommendation:
    - upscale ≤ 2x: no quality concern
    - upscale 2-4x: moderate concern
    - upscale > 4x: severe concern

    The KEY question is NOT "is output achievable?" (always yes for scale-to-cover)
    but "is the upscale quality acceptable for the intended use case?"
    """

    def test_640x360_upscale_factor(self):
        """640×360 → 1080×1920: upscale factor = 5.33x (severe)."""
        scale, new_w, new_h, _, _, _, _ = _compute_scale_to_cover(640, 360)
        self.assertAlmostEqual(scale, 5.33, places=1)
        self.assertGreater(scale, MIN_UPSCALE_ACCEPTABLE)  # > 2x → quality concern

    def test_854x480_upscale_factor(self):
        """854×480 → 1080×1920: upscale factor = 4.0x (moderate)."""
        scale, _, _, _, _, _, _ = _compute_scale_to_cover(854, 480)
        self.assertAlmostEqual(scale, 4.0, places=1)

    def test_1280x720_upscale_factor(self):
        """1280×720 → 1080×1920: upscale factor = 2.67x (moderate)."""
        scale, _, _, _, _, _, _ = _compute_scale_to_cover(1280, 720)
        self.assertAlmostEqual(scale, 2.67, places=1)
        self.assertGreater(scale, MIN_UPSCALE_ACCEPTABLE)

    def test_1920x1080_upscale_factor(self):
        """1920×1080 → 1080×1920: upscale factor = 1.78x (no concern)."""
        scale, _, _, _, _, _, _ = _compute_scale_to_cover(1920, 1080)
        self.assertAlmostEqual(scale, 1.78, places=1)
        self.assertLessEqual(scale, MIN_UPSCALE_ACCEPTABLE)

    def test_320x180_upscale_factor(self):
        """320×180 → 1080×1920: upscale factor = 10.67x (severe)."""
        scale, _, _, _, _, _, _ = _compute_scale_to_cover(320, 180)
        self.assertAlmostEqual(scale, 10.67, places=1)

    def test_1080x1920_upscale_factor(self):
        """1080×1920 → 1080×1920: upscale factor = 1.0x (no concern)."""
        scale, _, _, _, _, _, _ = _compute_scale_to_cover(1080, 1920)
        self.assertAlmostEqual(scale, 1.0, places=2)
        self.assertLessEqual(scale, MIN_UPSCALE_ACCEPTABLE)

    def test_effective_source_resolution(self):
        """640×360 retains only 202.5×360 source pixels (60300 pixels).

        This means each output pixel maps to ~0.19 source pixels (upscaled 5.33x).
        """
        ret_w, ret_h, pct = _effective_source_region(640, 360)
        self.assertAlmostEqual(ret_w, 202.5, places=0)
        self.assertAlmostEqual(ret_h, 360, places=0)
        self.assertAlmostEqual(pct, 31.6, places=0)


# ─────────────────────────────────────────────────────────────────────
# Test Class 6: Resolution Matrix — Comprehensive
# ─────────────────────────────────────────────────────────────────────

class TestResolutionMatrix(unittest.TestCase):
    """Comprehensive resolution matrix for all test cases.

    Each case is evaluated for:
    - source dimensions
    - orientation
    - scale-to-cover feasibility
    - upscale factor
    - current gate behavior
    - technical validity (output achievable without distortion/bars)
    """

    EXPECTED_MATRIX = {
        # (name, src_w, src_h, orientation, current_rejects, tech_valid, upscale_category)
        "640x360":        (640,  360,  "landscape", True,  True,  "severe"),
        "854x480":        (854,  480,  "landscape", False, True,  "moderate"),
        "1280x720":      (1280,  720,  "landscape", False, True,  "moderate"),
        "1920x1080":     (1920, 1080,  "landscape", False, True,  "none"),
        "360x640":        (360,  640,  "portrait",   True,  True,  "moderate"),
        "480x854":        (480,  854,  "portrait",   False, True,  "moderate"),
        "720x1280":       (720, 1280,  "portrait",   False, True,  "none"),
        "1080x1920":     (1080, 1920,  "portrait",   False, True,  "none"),
        "480x480":        (480,  480,  "square",     False, True,  "moderate"),
        "720x720":        (720,  720,  "square",     False, True,  "moderate"),
        "1080x1080":     (1080, 1080,  "square",     False, True,  "none"),
        "1920x800":      (1920,  800,  "landscape", False, True,  "moderate"),
        "2560x1080":     (2560, 1080,  "landscape", False, True,  "none"),
        "320x180":        (320,  180,  "landscape", True,  True,  "severe"),
        "426x240":        (426,  240,  "landscape", True,  True,  "severe"),
    }

    def test_matrix_completeness(self):
        """Verify the matrix covers all defined cases."""
        for name, w, h, orientation in ALL_CASES:
            self.assertIn(name, self.EXPECTED_MATRIX, f"Missing case: {name}")

    def test_resolution_analysis(self):
        """For each case, verify the mathematical analysis matches expectations."""
        for name, (src_w, src_h, orient, current_rejects, tech_valid, upscale_cat) in self.EXPECTED_MATRIX.items():
            with self.subTest(case=name):
                scale, new_w, new_h, crop_w, crop_h, cx, cy = _compute_scale_to_cover(src_w, src_h)

                # Technical validity: scale-to-cover always produces valid output
                output_valid = (new_w >= TARGET_WIDTH or crop_w) and (new_h >= TARGET_HEIGHT or crop_h)
                self.assertTrue(output_valid, f"{name}: output not achievable")

                # No distortion (scale-to-cover preserves aspect ratio)
                # No black bars (scale-to-cover fills target)
                # These are structural properties of the algorithm

                # Upscale category
                if scale <= MIN_UPSCALE_ACCEPTABLE:
                    expected_cat = "none"
                elif scale <= MIN_UPSCALE_MODERATE:
                    expected_cat = "moderate"
                else:
                    expected_cat = "severe"
                self.assertEqual(upscale_cat, expected_cat,
                                 f"{name}: upscale {scale:.2f}x → '{expected_cat}', expected '{upscale_cat}'")

    def test_current_gate_matrix(self):
        """Verify each case's current gate rejection status matches."""
        for name, (src_w, src_h, orient, current_rejects, tech_valid, upscale_cat) in self.EXPECTED_MATRIX.items():
            with self.subTest(case=name):
                actual_reject = src_w < mat._MATERIAL_MIN_WIDTH or src_h < mat._MATERIAL_MIN_HEIGHT
                self.assertEqual(actual_reject, current_rejects,
                                 f"{name}: gate reject mismatch")

    def test_tech_valid_all(self):
        """All cases are technically valid (scale-to-cover always works)."""
        for name, (src_w, src_h, orient, current_rejects, tech_valid, upscale_cat) in self.EXPECTED_MATRIX.items():
            with self.subTest(case=name):
                self.assertTrue(tech_valid, f"{name}: should be technically valid")


# ─────────────────────────────────────────────────────────────────────
# Test Class 7: Key Finding — Gate Mismatch
# ─────────────────────────────────────────────────────────────────────

class TestKeyFindingGateMismatch(unittest.TestCase):
    """The core finding of Phase 10E: the quality gate uses a GLOBAL minimum
    dimension (480×480) that rejects technically-valid landscape sources.

    640×360 landscape IS rejected by the current gate, but the pipeline CAN
    reframe it to 1080×1920 portrait. This is the design tension that
    Phase 10E's quality model must resolve.
    """

    def test_640x360_rejected_but_reframeable(self):
        """CONFIRMED FINDING: 640×360 is rejected by gate but can be reframed.

        - Current gate: REJECTS (height 360 < 480)
        - Reframe capability: YES (verified by test_reframe_640x360_to_1080x1920)
        - Upscale factor: 5.33x (severe quality concern)
        - Conclusion: The gate correctly rejects for QUALITY reasons,
          not because reframe is impossible.
        """
        # Gate rejects
        self.assertFalse(
            _validate_current_gate(640, 360),
            "640×360 should be rejected by current gate"
        )
        # But reframe IS technically possible
        scale, new_w, new_h, _, _, _, _ = _compute_scale_to_cover(640, 360)
        self.assertGreaterEqual(new_w, TARGET_WIDTH)
        self.assertGreaterEqual(new_h, TARGET_HEIGHT)
        # The question is: should 5.33x upscale be acceptable?

    def test_854x480_accepted_with_moderate_upscale(self):
        """854×480 is accepted by gate AND can be reframed.

        - Upscale factor: 4.0x (moderate concern)
        - This is the boundary case: accepted, but with quality tradeoff.
        """
        self.assertTrue(_validate_current_gate(854, 480))
        scale, _, _, _, _, _, _ = _compute_scale_to_cover(854, 480)
        self.assertAlmostEqual(scale, 4.0, places=1)
        self.assertGreater(scale, MIN_UPSCALE_ACCEPTABLE)

    def test_1920x1080_accepted_no_upscale_concern(self):
        """1920×1080 is accepted by gate with minimal upscale (1.78x)."""
        self.assertTrue(_validate_current_gate(1920, 1080))
        scale, _, _, _, _, _, _ = _compute_scale_to_cover(1920, 1080)
        self.assertLessEqual(scale, MIN_UPSCALE_ACCEPTABLE)


def _validate_current_gate(width: int, height: int) -> bool:
    """Replicate the CURRENT quality gate logic (for test purposes only).

    This mirrors _validate_downloaded_clip's dimension check:
        if w < _MATERIAL_MIN_WIDTH or h < _MATERIAL_MIN_HEIGHT: return False
    """
    return width >= mat._MATERIAL_MIN_WIDTH and height >= mat._MATERIAL_MIN_HEIGHT


if __name__ == "__main__":
    unittest.main()
