"""
Phase 10F.1 — Upstream Quality-Filter Compatibility Audit Tests

Diagnostic tests ONLY. No network. No YouTube. No production media.

These tests verify whether rank_videos()'s pre-download 480×480 filter
blocks any candidate that the Phase 10F output-aware gate would accept.

Key question: Can a candidate with resolution UNKNOWN at search time
(e.g., YouTube via extract_flat=True) reach the post-download quality gate?
"""

import unittest
from unittest.mock import MagicMock

from app.models.schema import MaterialInfo, VideoAspect
from app.services import material as mat


def make_item(w, h, provider="youtube", duration=10, asset_id=None,
              rendition=None):
    """Create a MaterialInfo with given resolution metadata."""
    item = MaterialInfo()
    item.provider = provider
    item.duration = duration
    source_info = {
        "provider": provider,
        "asset_id": asset_id or f"{provider}-{w}x{h}",
        "rendition": rendition if rendition is not None else (
            {"width": w, "height": h, "id": "test"} if w > 0 and h > 0 else None
        ),
    }
    item.source_info = source_info
    # Set width/height on the item itself for scoring
    if w > 0 and h > 0:
        item.width = w
        item.height = h
    return item


class TestRankVideosResolutionFilter(unittest.TestCase):
    """Verify rank_videos() resolution filtering behavior.

    The pre-download filter applies ONLY when resolution is known (w > 0 and h > 0).
    When resolution is unknown (w=0, h=0), the candidate is RETAINED.
    """

    # ── Sources WITH known resolution ──

    def test_360x640_known_resolution_rejected_by_rank(self):
        """360×640 with known resolution: rank_videos rejects (w 360 < 480)."""
        item = make_item(360, 640, rendition={"width": 360, "height": 640})
        ranked = mat.rank_videos([item], "test", 3, VideoAspect.portrait)
        self.assertEqual(len(ranked), 0, "360×640 with known resolution should be filtered by rank_videos")

    def test_640x360_known_resolution_rejected_by_rank(self):
        """640×360 with known resolution: rank_videos rejects (h 360 < 480)."""
        item = make_item(640, 360, rendition={"width": 640, "height": 360})
        ranked = mat.rank_videos([item], "test", 3, VideoAspect.portrait)
        self.assertEqual(len(ranked), 0, "640×360 with known resolution should be filtered by rank_videos")

    def test_854x480_known_resolution_accepted_by_rank(self):
        """854×480 with known resolution: rank_videos accepts (both ≥ 480)."""
        item = make_item(854, 480, rendition={"width": 854, "height": 480})
        ranked = mat.rank_videos([item], "test", 3, VideoAspect.portrait)
        self.assertEqual(len(ranked), 1, "854×480 with known resolution should pass rank_videos")

    def test_1280x720_known_resolution_accepted_by_rank(self):
        """1280×720 with known resolution: rank_videos accepts."""
        item = make_item(1280, 720, rendition={"width": 1280, "height": 720})
        ranked = mat.rank_videos([item], "test", 3, VideoAspect.portrait)
        self.assertEqual(len(ranked), 1)

    def test_1920x1080_known_resolution_accepted_by_rank(self):
        """1920×1080 with known resolution: rank_videos accepts."""
        item = make_item(1920, 1080, rendition={"width": 1920, "height": 1080})
        ranked = mat.rank_videos([item], "test", 3, VideoAspect.portrait)
        self.assertEqual(len(ranked), 1)

    # ── Sources with UNKNOWN resolution (YouTube extract_flat=True scenario) ──

    def test_360x640_unknown_resolution_passes_rank(self):
        """360×640 with UNKNOWN resolution (rendition=None): rank_videos RETAINS it.

        This is the YouTube extract_flat=True scenario: yt-dlp flat search
        does not populate format metadata, so rendition is None and w/h=0.
        The 480×480 pre-download filter does NOT apply because the
        ``if w > 0 and h > 0`` guard is skipped.
        """
        item = make_item(0, 0, rendition=None)
        ranked = mat.rank_videos([item], "test", 3, VideoAspect.portrait)
        self.assertEqual(len(ranked), 1,
                         "YouTube candidate with unknown resolution must pass rank_videos")

    def test_320x180_unknown_resolution_passes_rank(self):
        """320×180 with UNKNOWN resolution: rank_videos RETAINS it."""
        item = make_item(0, 0, rendition=None)
        ranked = mat.rank_videos([item], "test", 3, VideoAspect.portrait)
        self.assertEqual(len(ranked), 1)

    def test_unknown_resolution_passes_rank_with_other_filters(self):
        """Unknown resolution candidate passes rank_videos if duration is OK."""
        item = make_item(0, 0, duration=10, rendition=None)
        ranked = mat.rank_videos([item], "test", 3, VideoAspect.portrait)
        self.assertEqual(len(ranked), 1)


class TestCombinedDecisionMatrix(unittest.TestCase):
    """Combined matrix: rank_videos decision × output-aware gate decision.

    The key distinction:
    - 'can reach post-download gate' = rank_videos keeps the candidate
    - 'post-download gate would accept' = _validate_reframe_resolution returns True

    These are NOT the same thing when resolution is unknown at ranking time.
    """

    def _rank_result(self, item):
        """Return 'KEEPS' or 'REJECTS' based on rank_videos."""
        ranked = mat.rank_videos([item], "test", 3, VideoAspect.portrait)
        return "KEEPS" if len(ranked) == 1 else "REJECTS"

    def _gate_result(self, w, h):
        """Return 'ACCEPT' or 'REJECT' based on output-aware gate."""
        tw, th = VideoAspect.portrait.to_resolution()
        return "ACCEPT" if mat._validate_reframe_resolution(w, h, tw, th) else "REJECT"

    def test_matrix_360x640_portrait(self):
        """360×640: rank=UNKNOWN (passes), gate=ACCEPT."""
        # With known resolution: rank REJECTS (w 360 < 480)
        item_known = make_item(360, 640, rendition={"width": 360, "height": 640})
        self.assertEqual(self._rank_result(item_known), "REJECTS")
        # With unknown resolution (YouTube scenario): rank KEEPS
        item_unknown = make_item(0, 0, rendition=None)
        self.assertEqual(self._rank_result(item_unknown), "KEEPS")
        # Gate: ACCEPT (effective 360 ≥ 250)
        self.assertEqual(self._gate_result(360, 640), "ACCEPT")

    def test_matrix_640x360_landscape(self):
        """640×360: rank depends on known/unknown, gate=REJECT."""
        # With known resolution: rank REJECTS (h 360 < 480)
        item_known = make_item(640, 360, rendition={"width": 640, "height": 360})
        self.assertEqual(self._rank_result(item_known), "REJECTS")
        # With unknown resolution: rank KEEPS (reaches gate)
        item_unknown = make_item(0, 0, rendition=None)
        self.assertEqual(self._rank_result(item_unknown), "KEEPS")
        # Gate: REJECT (effective 202 < 250)
        self.assertEqual(self._gate_result(640, 360), "REJECT")

    def test_matrix_854x480_landscape(self):
        """854×480: rank=ACCEPTES (known), gate=ACCEPT."""
        item = make_item(854, 480, rendition={"width": 854, "height": 480})
        self.assertEqual(self._rank_result(item), "KEEPS")
        self.assertEqual(self._gate_result(854, 480), "ACCEPT")

    def test_matrix_1280x720_landscape(self):
        """1280×720: rank=ACCEPTES (known), gate=ACCEPT."""
        item = make_item(1280, 720, rendition={"width": 1280, "height": 720})
        self.assertEqual(self._rank_result(item), "KEEPS")
        self.assertEqual(self._gate_result(1280, 720), "ACCEPT")

    def test_matrix_1920x1080_landscape(self):
        """1920×1080: rank=ACCEPTES (known), gate=ACCEPT."""
        item = make_item(1920, 1080, rendition={"width": 1920, "height": 1080})
        self.assertEqual(self._rank_result(item), "KEEPS")
        self.assertEqual(self._gate_result(1920, 1080), "ACCEPT")

    def test_matrix_480x854_portrait(self):
        """480×854: rank=ACCEPTES (known), gate=ACCEPT."""
        item = make_item(480, 854, rendition={"width": 480, "height": 854})
        self.assertEqual(self._rank_result(item), "KEEPS")
        self.assertEqual(self._gate_result(480, 854), "ACCEPT")

    def test_matrix_1080x1920_portrait(self):
        """1080×1920: rank=ACCEPTES (known), gate=ACCEPT."""
        item = make_item(1080, 1920, rendition={"width": 1080, "height": 1920})
        self.assertEqual(self._rank_result(item), "KEEPS")
        self.assertEqual(self._gate_result(1080, 1920), "ACCEPT")

    def test_matrix_320x180_tiny(self):
        """320×180: rank=UNKNOWN (passes), gate=REJECT."""
        item_unknown = make_item(0, 0, rendition=None)
        self.assertEqual(self._rank_result(item_unknown), "KEEPS")
        self.assertEqual(self._gate_result(320, 180), "REJECT")


class TestExtractFlatMetadataScenario(unittest.TestCase):
    """Simulate the exact YouTube extract_flat=True metadata scenario.

    When extract_flat=True, yt-dlp returns entries without 'formats'.
    search_videos_youtube() sets rendition=None in this case.
    """

    def test_youtube_flat_search_entry_has_no_rendition(self):
        """Simulate a yt-dlp flat entry — no formats, rendition=None."""
        # Simulate what search_videos_youtube does with extract_flat=True
        entry = {
            "id": "dQw4w9WgXcQ",
            "title": "test video",
            "duration": 15,
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            # NO 'formats' key — extract_flat=True
        }
        # This mirrors the code path in search_videos_youtube
        formats = entry.get("formats") or []
        rendition = None
        if formats:
            best = max(formats, key=lambda f: f.get("height", 0) or 0)
            rendition = {
                "id": best.get("format_id"),
                "width": best.get("width"),
                "height": best.get("height"),
            }
        self.assertIsNone(rendition, "YouTube flat search should produce rendition=None")

        # Now create a MaterialInfo like search_videos_youtube would
        item = MaterialInfo()
        item.provider = "youtube"
        item.url = entry["url"]
        item.duration = entry["duration"]
        item.source_info = {
            "provider": "youtube",
            "rendition": rendition,  # None
        }

        # rank_videos should NOT filter this out
        info = item.source_info or {}
        rendition_check = info.get("rendition") or {}
        w = rendition_check.get("width", 0) or 0
        h = rendition_check.get("height", 0) or 0
        self.assertEqual(w, 0, "Width should be 0 when rendition is None")
        self.assertEqual(h, 0, "Height should be 0 when rendition is None")
        # The w > 0 and h > 0 guard in rank_videos will be False → not filtered
        self.assertFalse(w > 0 and h > 0, "Should NOT trigger 480×480 filter")

        # rank_videos should retain this item
        ranked = mat.rank_videos([item], "test", 3, VideoAspect.portrait)
        self.assertEqual(len(ranked), 1, "YouTube flat-search candidate must be retained by rank_videos")


if __name__ == "__main__":
    unittest.main()
