"""Phase 11E — Batch service tests (updated for API client architecture)."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.services import webui_batch


class TestBatchService(unittest.TestCase):
    """Tests for the batch service layer."""

    def setUp(self):
        self.original_app_config = dict(config.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def test_submit_batch_creates_multiple_tasks(self):
        """submit_batch should create one task per topic."""
        topics = [
            {"subject": "Topic A", "video_count": 1},
            {"subject": "Topic B", "video_count": 2},
        ]
        common_params = {"video_source": "pexels"}

        with patch("app.services.webui_batch.webui_api_client") as mock_client:
            mock_client.api_create_task.return_value = {"task_id": "mock-id"}
            batch_id, task_ids = webui_batch.submit_batch(topics, common_params)

        self.assertIsNotNone(batch_id)
        self.assertEqual(len(task_ids), 2)

    def test_submit_batch_empty_topics_raises(self):
        """Empty topic list should raise ValueError."""
        with self.assertRaises(ValueError):
            webui_batch.submit_batch([], {"video_source": "pexels"})

    def test_get_batch_status_counts(self):
        """Batch status should correctly derive counts from tasks."""
        task_ids = ["t1", "t2", "t3"]
        tasks = {
            "t1": {"state": 1, "progress": 100},
            "t2": {"state": -1, "progress": 30},
            "t3": {"state": 4, "progress": 60},
        }

        with patch("app.services.webui_batch.webui_api_client") as mock_client:
            mock_client.api_get_task.side_effect = lambda tid: tasks.get(tid)
            status = webui_batch.get_batch_status(task_ids)

        self.assertEqual(status["total"], 3)
        self.assertEqual(status["complete"], 1)
        self.assertEqual(status["failed"], 1)
        self.assertEqual(status["processing"], 1)

    def test_existing_providers_unchanged(self):
        """Regression: existing providers must work after changes."""
        result = webui_batch._build_task_params(
            {"subject": "Test", "video_count": 1},
            {"video_source": "pexels"},
            1,
        )
        self.assertEqual(result.video_source, "pexels")


if __name__ == "__main__":
    unittest.main()
