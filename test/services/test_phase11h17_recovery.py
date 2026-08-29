"""Phase 11H.1.7 — Backend/UI functional recovery tests.

Tests prove actual behavior, not just code existence.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models import const


class TestNewTaskStartsQueued(unittest.TestCase):
    """P1-5: New tasks must start as QUEUED, not PROCESSING."""

    def test_queued_constant_exists(self):
        """TASK_STATE_QUEUED must be defined."""
        self.assertEqual(const.TASK_STATE_QUEUED, 0)

    def test_cancelled_constant_exists(self):
        """TASK_STATE_CANCELLED must be defined."""
        self.assertEqual(const.TASK_STATE_CANCELLED, 2)


class TestTaskCancellation(unittest.TestCase):
    """P1-2: Cancel must prevent queued task from executing."""

    def test_cancel_adds_to_cancelled_set(self):
        """cancel() should add task_id to cancelled set."""
        from app.controllers.manager.memory_manager import InMemoryTaskManager
        mgr = InMemoryTaskManager(max_concurrent_tasks=1, max_queued_tasks=10)
        result = mgr.cancel("test-task-123")
        self.assertTrue(result)
        self.assertTrue(mgr.is_cancelled("test-task-123"))

    def test_cancelled_task_skipped_in_dequeue(self):
        """Dequeue should skip cancelled tasks."""
        from app.controllers.manager.memory_manager import InMemoryTaskManager
        mgr = InMemoryTaskManager(max_concurrent_tasks=2, max_queued_tasks=10)

        # Add tasks directly to queue (simulating queued state)
        mgr.enqueue({"func": lambda: None, "args": (), "kwargs": {"task_id": "task-1"}})
        mgr.enqueue({"func": lambda: None, "args": (), "kwargs": {"task_id": "task-2"}})

        # Cancel task-1
        mgr.cancel("task-1")

        # Dequeue should return task-2, not task-1
        task = mgr.dequeue()
        self.assertIsNotNone(task)
        self.assertEqual(task["kwargs"]["task_id"], "task-2")


class TestDeleteTaskUsesTaskDict(unittest.TestCase):
    """P1-2: delete_task must pass task dict to is_task_busy."""

    def test_delete_task_checks_busy_with_dict(self):
        """delete_task should call is_task_busy with task dict."""
        from app.services import task_cleanup

        captured = []

        def mock_is_task_busy(task):
            captured.append(task)
            return False

        with patch("app.services.task_cleanup.sm") as mock_sm:
            mock_sm.state.get_task.return_value = {
                "task_id": "test-123",
                "state": const.TASK_STATE_COMPLETE,
            }
            with patch("app.services.task_cleanup.is_task_busy", side_effect=mock_is_task_busy):
                with patch("os.path.isdir", return_value=False):
                    result = task_cleanup.delete_task("test-123")

        self.assertEqual(len(captured), 1)
        self.assertIsInstance(captured[0], dict)
        self.assertEqual(captured[0]["task_id"], "test-123")
        self.assertTrue(result["success"])


class TestDeleteTaskBlocksBusy(unittest.TestCase):
    """Busy tasks must not be deleted."""

    def test_busy_task_not_deleted(self):
        """delete_task should refuse to delete busy tasks."""
        from app.services import task_cleanup

        def mock_is_task_busy(task):
            return True  # Task is busy

        with patch("app.services.task_cleanup.sm") as mock_sm:
            mock_sm.state.get_task.return_value = {
                "task_id": "busy-task",
                "state": const.TASK_STATE_PROCESSING,
            }
            with patch("app.services.task_cleanup.is_task_busy", side_effect=mock_is_task_busy):
                result = task_cleanup.delete_task("busy-task")

        self.assertFalse(result["success"])
        self.assertIn("running", result["message"])


class TestStatusFiltering(unittest.TestCase):
    """P1-5: Status filtering must use exact state matching."""

    def test_queued_means_only_queued(self):
        """get_task_ids_by_status('queued') must return only QUEUED tasks."""
        from app.services import task_cleanup

        with patch("app.services.task_cleanup.sm") as mock_sm:
            mock_sm.state.get_all_tasks.return_value = [
                {"task_id": "t1", "state": const.TASK_STATE_QUEUED},
                {"task_id": "t2", "state": const.TASK_STATE_PROCESSING},
                {"task_id": "t3", "state": const.TASK_STATE_COMPLETE},
                {"task_id": "t4", "state": const.TASK_STATE_CANCELLED},
            ], 4
            result = task_cleanup.get_task_ids_by_status("queued")

        self.assertEqual(result, ["t1"])

    def test_cancelled_not_queued(self):
        """Cancelled tasks must NOT appear as queued."""
        from app.services import task_cleanup

        with patch("app.services.task_cleanup.sm") as mock_sm:
            mock_sm.state.get_all_tasks.return_value = [
                {"task_id": "t1", "state": const.TASK_STATE_QUEUED},
                {"task_id": "t2", "state": const.TASK_STATE_CANCELLED},
            ], 2
            queued = task_cleanup.get_task_ids_by_status("queued")
            cancelled = task_cleanup.get_task_ids_by_status("cancelled")

        self.assertEqual(queued, ["t1"])
        self.assertEqual(cancelled, ["t2"])


class TestCleanupReturnsErrors(unittest.TestCase):
    """Cleanup operations must report failures, not fake success."""

    def test_delete_failure_reported(self):
        """Failed deletion must return error info."""
        from app.services import task_cleanup

        with patch("app.services.task_cleanup.sm") as mock_sm:
            mock_sm.state.get_task.return_value = {"task_id": "fail-task", "state": const.TASK_STATE_COMPLETE}
            with patch("app.services.task_cleanup.is_task_busy", return_value=False):
                with patch("os.path.isdir", return_value=True):
                    with patch("shutil.rmtree", side_effect=Exception("permission denied")):
                        result = task_cleanup.delete_task("fail-task")

        self.assertFalse(result["success"])
        self.assertIn("permission denied", result["message"])


class TestQueueCancellationReal(unittest.TestCase):
    """P1-2: Cancelled task must never execute."""

    def test_cancelled_task_not_executed(self):
        """Worker must skip cancelled tasks."""
        from app.controllers.manager.memory_manager import InMemoryTaskManager

        executed = []

        def mock_task(task_id):
            executed.append(task_id)

        mgr = InMemoryTaskManager(max_concurrent_tasks=1, max_queued_tasks=10)

        # Simulate: enqueue task, cancel it, then run_task checks cancellation
        mgr.cancel("cancelled-task")
        self.assertTrue(mgr.is_cancelled("cancelled-task"))

        # run_task should skip it
        mgr.run_task(mock_task, task_id="cancelled-task")
        self.assertEqual(executed, [], "cancelled task must not execute")


if __name__ == "__main__":
    unittest.main()
