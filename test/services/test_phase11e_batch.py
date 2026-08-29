"""Phase 11E — Batch service tests.

TDD: These tests must FAIL before implementation.
Tests batch creation, status derivation, and failure isolation.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models import const
from app.models.schema import VideoParams, VideoAspect


class TestBatchService(unittest.TestCase):
    """Tests for the batch service layer."""

    def test_submit_batch_creates_multiple_tasks(self):
        """submit_batch should create one task per topic."""
        from app.services.webui_batch import submit_batch

        topics = [
            {"subject": "Topic A", "video_count": 1},
            {"subject": "Topic B", "video_count": 2},
            {"subject": "Topic C", "video_count": 1},
        ]
        common_params = {
            "video_source": "pexels",
            "voice_name": "female-1",
            "subtitle_enabled": True,
        }

        with patch("app.services.webui_batch.webui_task") as mock_wt:
            mock_wt.submit_generation = MagicMock()
            batch_id, task_ids = submit_batch(topics, common_params)

        self.assertIsNotNone(batch_id)
        self.assertEqual(len(task_ids), 3)
        self.assertEqual(mock_wt.submit_generation.call_count, 3)

    def test_submit_batch_returns_task_ids(self):
        """submit_batch should return the batch ID and task IDs for tracking."""
        from app.services.webui_batch import submit_batch

        topics = [{"subject": "Test", "video_count": 1}]
        common_params = {"video_source": "youtube"}

        with patch("app.services.webui_batch.webui_task") as mock_wt:
            mock_wt.submit_generation = MagicMock()
            batch_id, task_ids = submit_batch(topics, common_params)

        self.assertIsNotNone(batch_id)
        self.assertTrue(len(task_ids) > 0)
        self.assertEqual(len(task_ids), 1)

    def test_submit_batch_with_youtube_source(self):
        """Batch should support YouTube as a source."""
        from app.services.webui_batch import submit_batch

        topics = [{"subject": "Space documentary", "video_count": 2}]
        common_params = {"video_source": "youtube"}

        with patch("app.services.webui_batch.webui_task") as mock_wt:
            mock_wt.submit_generation = MagicMock()
            batch_id, task_ids = submit_batch(topics, common_params)

        self.assertIsNotNone(batch_id)
        call_args = mock_wt.submit_generation.call_args
        params = call_args[1].get("params") or call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["params"]
        self.assertEqual(params.video_source, "youtube")

    def test_get_batch_status_all_complete(self):
        """Batch status should show all tasks complete."""
        from app.services.webui_batch import get_batch_status

        task_ids = ["task-1", "task-2", "task-3"]
        tasks = {
            "task-1": {"state": const.TASK_STATE_COMPLETE, "progress": 100},
            "task-2": {"state": const.TASK_STATE_COMPLETE, "progress": 100},
            "task-3": {"state": const.TASK_STATE_COMPLETE, "progress": 100},
        }

        with patch("app.services.webui_batch.sm") as mock_sm:
            mock_sm.state.get_task.side_effect = lambda tid: tasks.get(tid)
            status = get_batch_status(task_ids)

        self.assertEqual(status["total"], 3)
        self.assertEqual(status["complete"], 3)
        self.assertEqual(status["failed"], 0)
        self.assertEqual(status["processing"], 0)
        self.assertTrue(status["is_complete"])

    def test_get_batch_status_with_failures(self):
        """Batch status should correctly count failures."""
        from app.services.webui_batch import get_batch_status

        task_ids = ["task-1", "task-2", "task-3"]
        tasks = {
            "task-1": {"state": const.TASK_STATE_COMPLETE, "progress": 100},
            "task-2": {"state": const.TASK_STATE_FAILED, "progress": 30, "error": "download failed"},
            "task-3": {"state": const.TASK_STATE_PROCESSING, "progress": 60},
        }

        with patch("app.services.webui_batch.sm") as mock_sm:
            mock_sm.state.get_task.side_effect = lambda tid: tasks.get(tid)
            status = get_batch_status(task_ids)

        self.assertEqual(status["total"], 3)
        self.assertEqual(status["complete"], 1)
        self.assertEqual(status["failed"], 1)
        self.assertEqual(status["processing"], 1)
        self.assertFalse(status["is_complete"])

    def test_get_batch_status_failure_isolation(self):
        """One failed task should not affect others in batch."""
        from app.services.webui_batch import get_batch_status

        task_ids = ["task-1", "task-2"]
        tasks = {
            "task-1": {"state": const.TASK_STATE_COMPLETE, "progress": 100},
            "task-2": {"state": const.TASK_STATE_FAILED, "progress": 20, "error": "No footage found"},
        }

        with patch("app.services.webui_batch.sm") as mock_sm:
            mock_sm.state.get_task.side_effect = lambda tid: tasks.get(tid)
            status = get_batch_status(task_ids)

        self.assertEqual(status["complete"], 1)
        self.assertEqual(status["failed"], 1)
        self.assertTrue(status["is_complete"])  # Batch is "complete" when all done (success or fail)

    def test_batch_tasks_expose_thumbnails(self):
        """Completed batch tasks should expose thumbnails."""
        from app.services.webui_batch import get_batch_tasks

        task_ids = ["task-1"]
        tasks = {
            "task-1": {
                "state": const.TASK_STATE_COMPLETE,
                "progress": 100,
                "videos": ["/tasks/task-1/final-1.mp4"],
                "thumbnails": ["/tasks/task-1/thumbnail-1.jpg"],
            },
        }

        with patch("app.services.webui_batch.sm") as mock_sm:
            mock_sm.state.get_task.side_effect = lambda tid: tasks.get(tid)
            result = get_batch_tasks(task_ids)

        self.assertEqual(len(result), 1)
        self.assertIsNotNone(result[0].get("thumbnails"))

    def test_batch_tasks_handle_missing_thumbnails(self):
        """Tasks without thumbnails should not break batch display."""
        from app.services.webui_batch import get_batch_tasks

        task_ids = ["task-1"]
        tasks = {
            "task-1": {
                "state": const.TASK_STATE_COMPLETE,
                "progress": 100,
                "videos": ["/tasks/task-1/final-1.mp4"],
                "thumbnails": None,  # Thumbnail generation failed
            },
        }

        with patch("app.services.webui_batch.sm") as mock_sm:
            mock_sm.state.get_task.side_effect = lambda tid: tasks.get(tid)
            result = get_batch_tasks(task_ids)

        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0].get("thumbnails"))

    def test_submit_batch_empty_topics_raises(self):
        """Empty topic list should raise ValueError."""
        from app.services.webui_batch import submit_batch

        with self.assertRaises(ValueError):
            submit_batch([], {"video_source": "pexels"})


if __name__ == "__main__":
    unittest.main()
