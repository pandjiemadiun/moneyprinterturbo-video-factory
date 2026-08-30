"""Phase 11E — Batch service tests (updated for API client architecture)."""

import ast
import json
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


class TestBatchUILabels(unittest.TestCase):
    """Source-level regression tests for batch UI label correctness."""

    @staticmethod
    def _get_batch_function_source():
        main_py = Path(__file__).resolve().parents[2] / "webui" / "Main.py"
        content = main_py.read_text(encoding="utf-8")
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_render_batch_mode_toggle":
                return ast.get_source_segment(content, node)
        raise AssertionError("_render_batch_mode_toggle not found in Main.py")

    def _get_number_input_label(self, source, key):
        """Extract the first argument (label) of a number_input call with the given key."""
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr != "number_input":
                    continue
                for kw in node.keywords:
                    if kw.arg != "key":
                        continue
                    key_val = None
                    if isinstance(kw.value, ast.Constant):
                        key_val = kw.value.value
                    elif isinstance(kw.value, ast.Name):
                        key_val = kw.value.id
                    elif isinstance(kw.value, ast.JoinedStr):
                        # f-string like f"batch_topic_count_{i}"
                        for part in kw.value.values:
                            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                                key_val = part.value
                                break
                    if key_val == key:
                        if node.args and isinstance(node.args[0], ast.Constant):
                            return node.args[0].value
                        if node.args and isinstance(node.args[0], ast.Call):
                            # tr("...") call
                            call = node.args[0]
                            if (
                                isinstance(call, ast.Call)
                                and isinstance(call.func, ast.Name)
                                and call.func.id == "tr"
                                and call.args
                                and isinstance(call.args[0], ast.Constant)
                            ):
                                return call.args[0].value
        return None

    def test_batch_topic_count_uses_distinct_key_from_per_topic_video_count(self):
        """The batch-level topic count and per-topic video count must use
        different i18n keys so they show distinct labels."""
        source = self._get_batch_function_source()
        batch_topic_label = self._get_number_input_label(source, "batch_topic_count")
        per_topic_label = None
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr != "number_input":
                    continue
                for kw in node.keywords:
                    if kw.arg != "key":
                        continue
                    key_val = None
                    if isinstance(kw.value, ast.Constant):
                        key_val = kw.value.value
                    elif isinstance(kw.value, ast.JoinedStr):
                        for part in kw.value.values:
                            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                                if part.value.startswith("batch_topic_count_"):
                                    key_val = part.value
                                    break
                    if key_val and key_val.startswith("batch_topic_count_"):
                        if node.args and isinstance(node.args[0], ast.Call):
                            call = node.args[0]
                            if (
                                isinstance(call, ast.Call)
                                and isinstance(call.func, ast.Name)
                                and call.func.id == "tr"
                                and call.args
                                and isinstance(call.args[0], ast.Constant)
                            ):
                                per_topic_label = call.args[0].value
                                break

        self.assertIsNotNone(batch_topic_label, "expected batch topic count input label")
        self.assertIsNotNone(per_topic_label, "expected per-topic video count input label")
        self.assertNotEqual(batch_topic_label, per_topic_label,
                            "batch topic count and per-topic video count must use different i18n keys")
        self.assertEqual(batch_topic_label, "Batch Topic Count")
        self.assertEqual(per_topic_label, "Batch Video Count")

    def test_batch_success_message_i18n_mentions_jobs(self):
        """The batch success i18n value should guide the user to the Jobs panel."""
        i18n_path = Path(__file__).resolve().parents[2] / "webui" / "i18n" / "en.json"
        i18n = json.loads(i18n_path.read_text(encoding="utf-8"))
        msg = i18n.get("Translation", {}).get("Batch Created Success", "")
        self.assertIn("Jobs", msg)


if __name__ == "__main__":
    unittest.main()
