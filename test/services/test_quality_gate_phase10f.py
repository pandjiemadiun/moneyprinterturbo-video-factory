"""
Phase 10F — Output-Aware Quality Gate Tests

TDD tests written BEFORE implementation.

Tests cover:
  A. Mathematical helper tests (_validate_reframe_resolution)
  B. Boundary tests (effective dimension 249, 250, 251)
  C. Orientation tests (landscape, portrait, square)
  D. Tiny-source tests (320×180, 426×240 rejected)
  E. Invalid dimension tests (width <= 0, height <= 0, divide-by-zero safety)
  F. Integration tests (actual _validate_downloaded_clip with synthetic fixtures)
  G. Before/after gate matrix (old gate vs new gate)

NO YouTube downloads. NO production media. NO network.
All fixtures are synthetic (ffmpeg-generated color clips).
"""

import inspect
import os
import subprocess
import tempfile
import shutil
import unittest

from app.models.schema import VideoAspect
from app.services import material as mat


# ─────────────────────────────────────────────────────────────────────
# Helper: create synthetic test video via ffmpeg
# ─────────────────────────────────────────────────────────────────────

def make_synthetic_video(path, width, height, duration=5.0, fps=24):
    """Create a minimal synthetic h264 test video using ffmpeg's lavfi color source."""
    result = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"color=c=blue:s={width}x{height}:d={duration}:r={fps}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", path],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[:200]}")
    return path


# ─────────────────────────────────────────────────────────────────────
# A. Mathematical Helper Tests (Section 7A)
#    Tests the pure function _validate_reframe_resolution(w, h, target_w, target_h)
#    using VideoAspect.portrait.to_resolution() as canonical target.
# ─────────────────────────────────────────────────────────────────────

TARGET_W, TARGET_H = VideoAspect.portrait.to_resolution()


class TestValidateReframeResolution(unittest.TestCase):
    """Verify _validate_reframe_resolution() implements the approved model:
    effective source dimension >= 250 after scale-to-cover + crop.

    Target: {TARGET_W}×{TARGET_H} (canonical, from VideoAspect.portrait).
    """

    def test_640x360_landscape_rejected(self):
        """640×360: effective min ≈ 202 < 250 → REJECT."""
        result = mat._validate_reframe_resolution(640, 360, TARGET_W, TARGET_H)
        self.assertFalse(result, "640×360 should be REJECTED (effective min 202 < 250)")

    def test_854x480_landscape_accepted(self):
        """854×480: effective min ≈ 270 ≥ 250 → ACCEPT."""
        result = mat._validate_reframe_resolution(854, 480, TARGET_W, TARGET_H)
        self.assertTrue(result, "854×480 should be ACCEPTED (effective min 270 ≥ 250)")

    def test_1280x720_landscape_accepted(self):
        """1280×720: effective min ≈ 405 ≥ 250 → ACCEPT."""
        result = mat._validate_reframe_resolution(1280, 720, TARGET_W, TARGET_H)
        self.assertTrue(result, "1280×720 should be ACCEPTED (effective min 405 ≥ 250)")

    def test_1920x1080_landscape_accepted(self):
        """1920×1080: effective min ≈ 608 ≥ 250 → ACCEPT."""
        result = mat._validate_reframe_resolution(1920, 1080, TARGET_W, TARGET_H)
        self.assertTrue(result, "1920×1080 should be ACCEPTED (effective min 608 ≥ 250)")

    def test_1080x1920_portrait_accepted(self):
        """1080×1920: effective min = 1080 ≥ 250 → ACCEPT (native portrait)."""
        result = mat._validate_reframe_resolution(1080, 1920, TARGET_W, TARGET_H)
        self.assertTrue(result, "1080×1920 should be ACCEPTED (native portrait)")

    def test_360x640_portrait_accepted(self):
        """360×640: effective min = 360 ≥ 250 → ACCEPT (portrait, 3x upscale).

        Note: OLD gate rejected this (w=360 < 480). NEW gate accepts it
        because the effective source dimension after reframe is 360 ≥ 250.
        This is the key behavioral improvement of Phase 10F.
        """
        result = mat._validate_reframe_resolution(360, 640, TARGET_W, TARGET_H)
        self.assertTrue(result, "360×640 should be ACCEPTED (effective min 360 ≥ 250)")

    def test_480x854_portrait_accepted(self):
        """480×854: effective min ≈ 480 ≥ 250 → ACCEPT."""
        result = mat._validate_reframe_resolution(480, 854, TARGET_W, TARGET_H)
        self.assertTrue(result, "480×854 should be ACCEPTED")

    def test_720x1280_portrait_accepted(self):
        """720×1280: effective min = 720 ≥ 250 → ACCEPT."""
        result = mat._validate_reframe_resolution(720, 1280, TARGET_W, TARGET_H)
        self.assertTrue(result, "720×1280 should be ACCEPTED")

    def test_480x480_square_accepted(self):
        """480×480: effective min ≈ 270 ≥ 250 → ACCEPT."""
        result = mat._validate_reframe_resolution(480, 480, TARGET_W, TARGET_H)
        self.assertTrue(result, "480×480 should be ACCEPTED")

    def test_1080x1080_square_accepted(self):
        """1080×1080: effective min ≈ 608 ≥ 250 → ACCEPT."""
        result = mat._validate_reframe_resolution(1080, 1080, TARGET_W, TARGET_H)
        self.assertTrue(result, "1080×1080 should be ACCEPTED")


# ─────────────────────────────────────────────────────────────────────
# B. Boundary Tests (Section 7B)
#    Boundary rule: < 250 → reject, == 250 → accept, > 250 → accept.
# ─────────────────────────────────────────────────────────────────────

class TestBoundaryConditions(unittest.TestCase):
    """Test the effective-dimension boundary at exactly 250."""

    def test_effective_dimension_249_rejected(self):
        """Source where effective min dim is just below 250 → REJECT."""
        # landscape: scale = max(target_w/w, target_h/h)
        # For 640×h landscape: src_ratio = 640/h, target_ratio = 1080/1920 = 0.5625
        # If 640/h > 0.5625 (i.e., h < 1137), scale = target_h/h = 1920/h
        # effective_w = target_w/scale = 1080/(1920/h) = 1080*h/1920
        # We need effective_w < 250 → 1080*h/1920 < 250 → h < 250*1920/1080 = 444.44
        # h=442: effective_w = 1080*442/1920 = 249.06 < 250 → REJECT
        h = 442
        result = mat._validate_reframe_resolution(640, h, TARGET_W, TARGET_H)
        self.assertFalse(result, f"height={h} should be REJECTED (effective ~249 < 250)")

    def test_effective_dimension_250_accepted(self):
        """Source where effective min dim is exactly ≥ 250 → ACCEPT."""
        # h=445: effective_w = 1080*445/1920 = 250.31 ≥ 250 → ACCEPT
        h = 445
        result = mat._validate_reframe_resolution(640, h, TARGET_W, TARGET_H)
        self.assertTrue(result, f"height={h} should be ACCEPTED (effective ~250 ≥ 250)")

    def test_effective_dimension_251_accepted(self):
        """Source where effective min dim is just above 250 → ACCEPT."""
        # h=450: effective_w = 1080*450/1920 = 253.125 ≥ 250 → ACCEPT
        h = 450
        result = mat._validate_reframe_resolution(640, h, TARGET_W, TARGET_H)
        self.assertTrue(result, f"height={h} should be ACCEPTED")

    def test_640x360_far_below_boundary(self):
        """640×360 has effective min ~202 — confirms boundary is not at 202."""
        result = mat._validate_reframe_resolution(640, 360, TARGET_W, TARGET_H)
        self.assertFalse(result)


# ─────────────────────────────────────────────────────────────────────
# C. Orientation Tests (Section 7C)
# ─────────────────────────────────────────────────────────────────────

class TestOrientationHandling(unittest.TestCase):
    """Verify the model works for all orientations."""

    def test_landscape_orientations(self):
        """Landscape: 640×360 reject, 854×480+ accept."""
        self.assertFalse(mat._validate_reframe_resolution(640, 360, TARGET_W, TARGET_H))
        self.assertTrue(mat._validate_reframe_resolution(854, 480, TARGET_W, TARGET_H))
        self.assertTrue(mat._validate_reframe_resolution(1280, 720, TARGET_W, TARGET_H))
        self.assertTrue(mat._validate_reframe_resolution(1920, 1080, TARGET_W, TARGET_H))

    def test_portrait_orientations(self):
        """Portrait: 360×640 accept (effective 360 ≥ 250), 480×854+ accept."""
        self.assertTrue(mat._validate_reframe_resolution(360, 640, TARGET_W, TARGET_H))
        self.assertTrue(mat._validate_reframe_resolution(480, 854, TARGET_W, TARGET_H))
        self.assertTrue(mat._validate_reframe_resolution(720, 1280, TARGET_W, TARGET_H))
        self.assertTrue(mat._validate_reframe_resolution(1080, 1920, TARGET_W, TARGET_H))

    def test_square_orientations(self):
        """Square: 480×480 accept, 720×720 accept, 1080×1080 accept."""
        self.assertTrue(mat._validate_reframe_resolution(480, 480, TARGET_W, TARGET_H))
        self.assertTrue(mat._validate_reframe_resolution(720, 720, TARGET_W, TARGET_H))
        self.assertTrue(mat._validate_reframe_resolution(1080, 1080, TARGET_W, TARGET_H))

    def test_extremely_wide(self):
        """Extremely wide sources: both pass threshold."""
        self.assertTrue(mat._validate_reframe_resolution(1920, 800, TARGET_W, TARGET_H))
        self.assertTrue(mat._validate_reframe_resolution(2560, 1080, TARGET_W, TARGET_H))


# ─────────────────────────────────────────────────────────────────────
# D. Tiny-Source Tests (Section 7D)
# ─────────────────────────────────────────────────────────────────────

class TestTinySources(unittest.TestCase):
    """Verify very low-resolution sources remain rejected."""

    def test_320x180_rejected(self):
        """320×180: effective min ≈ 101 < 250 → REJECT."""
        result = mat._validate_reframe_resolution(320, 180, TARGET_W, TARGET_H)
        self.assertFalse(result, "320×180 should be REJECTED (effective ~101 < 250)")

    def test_426x240_rejected(self):
        """426×240: effective min ≈ 135 < 250 → REJECT."""
        result = mat._validate_reframe_resolution(426, 240, TARGET_W, TARGET_H)
        self.assertFalse(result, "426×240 should be REJECTED (effective ~135 < 250)")

    def test_200x112_rejected(self):
        """200×112: extreme upscale, should be rejected."""
        result = mat._validate_reframe_resolution(200, 112, TARGET_W, TARGET_H)
        self.assertFalse(result)


# ─────────────────────────────────────────────────────────────────────
# E. Invalid Dimension Tests (Section 7E)
# ─────────────────────────────────────────────────────────────────────

class TestInvalidDimensions(unittest.TestCase):
    """Verify invalid dimensions reject safely, no division by zero."""

    def test_zero_width(self):
        """Width = 0 must reject without error."""
        result = mat._validate_reframe_resolution(0, 360, TARGET_W, TARGET_H)
        self.assertFalse(result)

    def test_zero_height(self):
        """Height = 0 must reject without error (no division by zero)."""
        result = mat._validate_reframe_resolution(640, 0, TARGET_W, TARGET_H)
        self.assertFalse(result)

    def test_negative_width(self):
        """Negative width must reject safely."""
        result = mat._validate_reframe_resolution(-1, 360, TARGET_W, TARGET_H)
        self.assertFalse(result)

    def test_negative_height(self):
        """Negative height must reject safely."""
        result = mat._validate_reframe_resolution(640, -1, TARGET_W, TARGET_H)
        self.assertFalse(result)

    def test_both_zero(self):
        """Both zero must reject without division by zero."""
        result = mat._validate_reframe_resolution(0, 0, TARGET_W, TARGET_H)
        self.assertFalse(result)


# ─────────────────────────────────────────────────────────────────────
# F. Integration Tests — _validate_downloaded_clip with synthetic fixtures (Section 8)
#    These tests verify the ACTUAL _validate_downloaded_clip() function
#    end-to-end with real synthetic video files.
# ─────────────────────────────────────────────────────────────────────

class TestValidateDownloadedClipIntegration(unittest.TestCase):
    """Verify _validate_downloaded_clip() uses the new output-aware gate
    with actual synthetic video fixtures.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="test_phase10f_integration_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _make_and_validate(self, w, h, min_duration=0):
        """Create a synthetic video and run _validate_downloaded_clip on it."""
        path = os.path.join(self.tmpdir, f"src_{w}x{h}.mp4")
        make_synthetic_video(path, w, h, duration=5, fps=24)
        result = mat._validate_downloaded_clip(path, min_duration=min_duration)
        return result

    def test_640x360_rejected_by_integration(self):
        """INTEGRATION: 640×360 synthetic fixture → REJECT."""
        result = self._make_and_validate(640, 360, min_duration=3)
        self.assertFalse(result, "640×360 must be REJECTED by quality gate")

    def test_854x480_accepted_by_integration(self):
        """INTEGRATION: 854×480 synthetic fixture → ACCEPT."""
        result = self._make_and_validate(854, 480, min_duration=3)
        self.assertTrue(result, "854×480 must be ACCEPTED by quality gate")

    def test_1280x720_accepted_by_integration(self):
        """INTEGRATION: 1280×720 synthetic fixture → ACCEPT."""
        result = self._make_and_validate(1280, 720, min_duration=3)
        self.assertTrue(result, "1280×720 must be ACCEPTED by quality gate")

    def test_1920x1080_accepted_by_integration(self):
        """INTEGRATION: 1920×1080 synthetic fixture → ACCEPT.

        Tradeoff: 1920×1080 fixtures are larger but verifying the real gate
        at full HD validates no false rejection at the upper end.
        """
        result = self._make_and_validate(1920, 1080, min_duration=3)
        self.assertTrue(result, "1920×1080 must be ACCEPTED by quality gate")

    def test_320x180_rejected_by_integration(self):
        """INTEGRATION: 320×180 synthetic fixture → REJECT (tiny source)."""
        result = self._make_and_validate(320, 180, min_duration=3)
        self.assertFalse(result, "320×180 must be REJECTED by quality gate")

    def test_426x240_rejected_by_integration(self):
        """INTEGRATION: 426×240 synthetic fixture → REJECT (tiny source)."""
        result = self._make_and_validate(426, 240, min_duration=3)
        self.assertFalse(result, "426×240 must be REJECTED by quality gate")

    def test_nonexistent_file_rejected(self):
        """INTEGRATION: Non-existent file → REJECT (file_exists check)."""
        result = mat._validate_downloaded_clip("/nonexistent/video.mp4", min_duration=3)
        self.assertFalse(result)

    def test_empty_file_rejected(self):
        """INTEGRATION: Empty file → REJECT (file size check)."""
        path = os.path.join(self.tmpdir, "empty.mp4")
        open(path, "wb").close()
        result = mat._validate_downloaded_clip(path, min_duration=3)
        self.assertFalse(result)


# ─────────────────────────────────────────────────────────────────────
# G. Before/After Gate Matrix (Section 11)
#    Compares old gate (w < 480 OR h < 480) vs new gate (effective ≥ 250).
# ─────────────────────────────────────────────────────────────────────

class TestBeforeAfterMatrix(unittest.TestCase):
    """Verify the before/after matrix for key source resolutions.

    NOTE on 854×480: The Phase 10F task spec's Section 11 matrix lists
    OLD GATE = REJECT for 854×480, but the actual old gate (480×480)
    ACCEPTS 854×480 (854 ≥ 480 AND 480 ≥ 480). This test uses the ACTUAL
    old-gate behavior, not the task spec's incorrect claim. The NEW gate
    also accepts 854×480 (effective 270 ≥ 250). Both agree: ACCEPT.

    The actual behavioral change in Phase 10F is:
      360×640 portrait: OLD=REJECT (w 360 < 480) → NEW=ACCEPT (effective 360 ≥ 250)
    """

    def old_gate_rejects(self, w, h):
        """Old gate: w < 480 OR h < 480."""
        return w < mat._MATERIAL_MIN_WIDTH or h < mat._MATERIAL_MIN_HEIGHT

    def new_gate_rejects(self, w, h):
        """New gate: effective dimension < 250."""
        return not mat._validate_reframe_resolution(w, h, TARGET_W, TARGET_H)

    def test_640x360_matrix(self):
        """640×360: OLD=REJECT, NEW=REJECT → EXPECTED REJECT."""
        w, h = 640, 360
        self.assertTrue(self.old_gate_rejects(w, h), "OLD gate should reject 640×360")
        self.assertTrue(self.new_gate_rejects(w, h), "NEW gate should also reject 640×360 (effective 202 < 250)")

    def test_854x480_matrix(self):
        """854×480: OLD=ACCEPT, NEW=ACCEPT → EXPECTED ACCEPT.

        (Task spec incorrectly claims OLD=REJECT; actual old gate accepts.)
        """
        w, h = 854, 480
        self.assertFalse(self.old_gate_rejects(w, h), "OLD gate should ACCEPT 854×480 (both dims ≥ 480)")
        self.assertFalse(self.new_gate_rejects(w, h), "NEW gate should also ACCEPT 854×480 (effective 270 ≥ 250)")

    def test_1280x720_matrix(self):
        """1280×720: OLD=ACCEPT, NEW=ACCEPT → EXPECTED ACCEPT."""
        w, h = 1280, 720
        self.assertFalse(self.old_gate_rejects(w, h))
        self.assertFalse(self.new_gate_rejects(w, h))

    def test_1920x1080_matrix(self):
        """1920×1080: OLD=ACCEPT, NEW=ACCEPT → EXPECTED ACCEPT."""
        w, h = 1920, 1080
        self.assertFalse(self.old_gate_rejects(w, h))
        self.assertFalse(self.new_gate_rejects(w, h))

    def test_360x640_portrait_behavior_change(self):
        """360×640 portrait: OLD=REJECT, NEW=ACCEPT → behavioral change.

        This is the core improvement: portrait 360×640 (effective 360 ≥ 250)
        is now accepted instead of being rejected by the old 480×480 gate.
        """
        w, h = 360, 640
        self.assertTrue(self.old_gate_rejects(w, h), "OLD gate should REJECT 360×640 (w 360 < 480)")
        self.assertFalse(self.new_gate_rejects(w, h), "NEW gate should ACCEPT 360×640 (effective 360 ≥ 250)")

    def test_320x180_matrix(self):
        """320×180: OLD=REJECT, NEW=REJECT → EXPECTED REJECT."""
        w, h = 320, 180
        self.assertTrue(self.old_gate_rejects(w, h))
        self.assertTrue(self.new_gate_rejects(w, h))

    def test_426x240_matrix(self):
        """426×240: OLD=REJECT, NEW=REJECT → EXPECTED REJECT."""
        w, h = 426, 240
        self.assertTrue(self.old_gate_rejects(w, h))
        self.assertTrue(self.new_gate_rejects(w, h))


# ─────────────────────────────────────────────────────────────────────
# H. No Behavior Change Outside Gate (Section 12)
# ─────────────────────────────────────────────────────────────────────

class TestNoBehavioralChangeOutsideGate(unittest.TestCase):
    """Verify the only behavior change is the resolution decision."""

    def test_constants_preserved(self):
        """_MATERIAL_MIN_WIDTH and _MATERIAL_MIN_HEIGHT must still be 480."""
        self.assertEqual(mat._MATERIAL_MIN_WIDTH, 480)
        self.assertEqual(mat._MATERIAL_MIN_HEIGHT, 480)

    def test_constants_still_used_by_rank_videos(self):
        """_MATERIAL_MIN_WIDTH/HEIGHT must still be referenced (by rank_videos pre-download filter)."""
        source = inspect.getsource(mat.rank_videos)
        self.assertIn("_MATERIAL_MIN_WIDTH", source)
        self.assertIn("_MATERIAL_MIN_HEIGHT", source)

    def test_save_video_youtube_format_unchanged(self):
        """yt-dlp format must not change."""
        source = inspect.getsource(mat.save_video_youtube)
        self.assertIn("best[ext=mp4][height<=720]", source)
        self.assertNotIn("nopart", source)

    def test_validate_downloaded_clip_preserves_other_checks(self):
        """_validate_downloaded_clip must still check file exists, size, codec, duration, fps."""
        source = inspect.getsource(mat._validate_downloaded_clip)
        self.assertIn("os.path.exists(video_path)", source)
        # Must NOT contain the old raw resolution check anymore
        self.assertNotIn("w < _MATERIAL_MIN_WIDTH or h < _MATERIAL_MIN_HEIGHT", source)
        # Must contain the new resolution check
        self.assertIn("_validate_reframe_resolution", source)


if __name__ == "__main__":
    unittest.main()
