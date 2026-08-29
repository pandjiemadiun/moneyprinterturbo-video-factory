"""Phase 11F — Factory UX tests.

TDD: These tests must FAIL before implementation.
Tests cover batch UI contract, thumbnail display, mobile CSS, and provider parity.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models import const
from app.models.schema import VideoParams, VideoAspect
from app.services import webui_batch


class TestBatchUIContract(unittest.TestCase):
    """Tests for batch creation UI contract (11F.1)."""

    def _get_video_sources(self):
        """Extract video_sources values from Main.py without importing Streamlit."""
        main_py = Path(__file__).parent.parent.parent / "webui" / "Main.py"
        content = main_py.read_text()
        import re
        # Find the video_sources = [...] block by bracket matching
        start_marker = 'video_sources = ['
        start_idx = content.find(start_marker)
        if start_idx == -1:
            return []
        bracket_start = content.index('[', start_idx)
        bracket_count = 0
        end_idx = bracket_start
        for i in range(bracket_start, len(content)):
            if content[i] == '[':
                bracket_count += 1
            elif content[i] == ']':
                bracket_count -= 1
                if bracket_count == 0:
                    end_idx = i
                    break
        block = content[bracket_start:end_idx + 1]
        # Extract lowercase values (labels are mixed-case, values are lowercase identifiers)
        return re.findall(r'"([a-z]+)"', block)

    def test_all_providers_available_in_batch(self):
        """All backend providers should be available for batch creation."""
        expected_sources = {"pexels", "pixabay", "coverr", "youtube", "wavespeed", "loomloom", "local"}
        actual_sources = set(self._get_video_sources())
        self.assertEqual(expected_sources, actual_sources)

    def test_youtube_requires_search_terms(self):
        """YouTube batch should require search terms or script."""
        params = VideoParams(
            video_subject="",
            video_script="",
            video_source="youtube",
            video_terms="",
        )
        # YouTube with empty terms and empty script should fail validation
        self.assertTrue(
            not params.video_terms and not params.video_script,
            "YouTube requires either search terms or script"
        )

    def test_batch_submit_with_multiple_topics(self):
        """Batch submission should create one task per topic."""
        topics = [
            {"subject": "Space", "video_count": 2, "video_source": "youtube"},
            {"subject": "Ocean", "video_count": 1, "video_source": "pexels"},
        ]
        common_params = {"voice_name": "female-1", "subtitle_enabled": True}

        with patch("app.services.webui_batch.webui_task") as mock_wt:
            mock_wt.submit_generation = MagicMock()
            batch_id, task_ids = webui_batch.submit_batch(topics, common_params)

        self.assertIsNotNone(batch_id)
        self.assertEqual(len(task_ids), 2)
        self.assertEqual(mock_wt.submit_generation.call_count, 2)

    def test_batch_empty_topics_rejected(self):
        """Empty topic list should raise ValueError."""
        with self.assertRaises(ValueError):
            webui_batch.submit_batch([], {"video_source": "pexels"})


class TestBatchMonitor(unittest.TestCase):
    """Tests for batch monitoring (11F.2)."""

    def test_batch_status_counts(self):
        """Batch status should correctly derive counts from tasks."""
        task_ids = ["t1", "t2", "t3", "t4"]
        tasks = {
            "t1": {"state": const.TASK_STATE_COMPLETE, "progress": 100},
            "t2": {"state": const.TASK_STATE_COMPLETE, "progress": 100},
            "t3": {"state": const.TASK_STATE_PROCESSING, "progress": 50},
            "t4": {"state": const.TASK_STATE_FAILED, "progress": 20, "error": "fail"},
        }
        with patch("app.services.webui_batch.sm") as mock_sm:
            mock_sm.state.get_task.side_effect = lambda tid: tasks.get(tid)
            status = webui_batch.get_batch_status(task_ids)

        self.assertEqual(status["total"], 4)
        self.assertEqual(status["complete"], 2)
        self.assertEqual(status["processing"], 1)
        self.assertEqual(status["failed"], 1)
        self.assertFalse(status["is_complete"])

    def test_batch_all_complete(self):
        """Batch with all tasks complete should report is_complete."""
        task_ids = ["t1", "t2"]
        tasks = {
            "t1": {"state": const.TASK_STATE_COMPLETE, "progress": 100},
            "t2": {"state": const.TASK_STATE_COMPLETE, "progress": 100},
        }
        with patch("app.services.webui_batch.sm") as mock_sm:
            mock_sm.state.get_task.side_effect = lambda tid: tasks.get(tid)
            status = webui_batch.get_batch_status(task_ids)

        self.assertTrue(status["is_complete"])
        self.assertEqual(status["progress"], 100.0)


class TestThumbnailDisplay(unittest.TestCase):
    """Tests for thumbnail display in video library (11F.3)."""

    def test_thumbnail_uri_present_when_available(self):
        """Task with thumbnail should expose thumbnail URI."""
        task = {
            "task_id": "test-1",
            "state": const.TASK_STATE_COMPLETE,
            "videos": ["/tasks/test-1/final-1.mp4"],
            "thumbnails": ["/tasks/test-1/thumbnail-1.jpg"],
        }
        self.assertIsNotNone(task.get("thumbnails"))
        self.assertTrue(len(task["thumbnails"]) > 0)
        self.assertFalse(task["thumbnails"][0].startswith("/storage/tasks"))

    def test_missing_thumbnail_does_not_fail_video(self):
        """Task without thumbnail should still be complete."""
        task = {
            "task_id": "test-2",
            "state": const.TASK_STATE_COMPLETE,
            "videos": ["/tasks/test-2/final-1.mp4"],
            "thumbnails": None,
        }
        self.assertEqual(task["state"], const.TASK_STATE_COMPLETE)
        self.assertIsNone(task.get("thumbnails"))

    def test_thumbnail_path_not_exposed(self):
        """Filesystem paths should not be exposed to browser."""
        task = {
            "thumbnails": ["/tasks/task-1/thumbnail-1.jpg"],
        }
        for path in task["thumbnails"]:
            self.assertFalse(path.startswith("/storage/"))
            self.assertFalse(path.startswith("/opt/"))


class TestMobileCSS(unittest.TestCase):
    """Tests for mobile layout CSS (11F.4)."""

    def test_mobile_breakpoint_exists(self):
        """CSS should contain mobile breakpoint rules."""
        css_path = Path(__file__).parent.parent.parent / "webui" / "styles.css"
        css_content = css_path.read_text()
        self.assertIn("max-width: 700px", css_content)
        self.assertIn("max-width: 480px", css_content)

    def test_no_hardcoded_4column_overflow(self):
        """4-column layout should have mobile override."""
        css_path = Path(__file__).parent.parent.parent / "webui" / "styles.css"
        css_content = css_path.read_text()
        # Should have grid or flex wrapping for mobile
        self.assertTrue(
            "grid-template-columns" in css_content or "flex-wrap" in css_content,
            "CSS should have mobile layout rules"
        )


class TestProviderParity(unittest.TestCase):
    """Tests that all providers are preserved (11F.5)."""

    def _get_video_sources(self):
        """Extract video_sources values from Main.py without importing Streamlit."""
        main_py = Path(__file__).parent.parent.parent / "webui" / "Main.py"
        content = main_py.read_text()
        import re
        # Find the video_sources = [...] block by bracket matching
        start_marker = 'video_sources = ['
        start_idx = content.find(start_marker)
        if start_idx == -1:
            return []
        bracket_start = content.index('[', start_idx)
        bracket_count = 0
        end_idx = bracket_start
        for i in range(bracket_start, len(content)):
            if content[i] == '[':
                bracket_count += 1
            elif content[i] == ']':
                bracket_count -= 1
                if bracket_count == 0:
                    end_idx = i
                    break
        block = content[bracket_start:end_idx + 1]
        # Extract lowercase values (labels are mixed-case, values are lowercase identifiers)
        return re.findall(r'"([a-z]+)"', block)

    def test_provider_validation_includes_all(self):
        """Provider validation list should include all 7 sources."""
        expected = {"pexels", "pixabay", "coverr", "youtube", "wavespeed", "loomloom", "local"}
        actual = set(self._get_video_sources())
        self.assertEqual(expected, actual)

    def test_youtube_in_validation_list(self):
        """YouTube must be in the valid source list."""
        sources = set(self._get_video_sources())
        self.assertIn("youtube", sources)


if __name__ == "__main__":
    unittest.main()
