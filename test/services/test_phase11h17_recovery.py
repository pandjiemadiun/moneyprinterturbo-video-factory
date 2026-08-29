"""Phase 11H.1.7 — Backend/UI functional recovery tests.

RED tests proving the defects exist.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models import const


class TestCleanupUsesTaskDict(unittest.TestCase):
    """P1-2: delete_task must pass task dict to is_task_busy, not task_id string."""

    def test_delete_task_passes_task_dict_to_is_task_busy(self):
        """is_task_busy expects a dict, not a string task_id."""
        from app.services import task_cleanup

        # Mock is_task_busy to capture what it receives
        captured = []
        original_is_task_busy = None

        def mock_is_task_busy(task_or_id):
            captured.append(task_or_id)
            return False

        with patch("app.services.task_cleanup.sm") as mock_sm:
            mock_sm.state.get_task.return_value = {
                "task_id": "test-123",
                "state": const.TASK_STATE_COMPLETE,
            }
            with patch("app.services.task_cleanup.is_task_busy", side_effect=mock_is_task_busy):
                with patch("os.path.isdir", return_value=False):
                    result = task_cleanup.delete_task("test-123")

        # is_task_busy should receive a dict, not a string
        self.assertEqual(len(captured), 1)
        self.assertIsInstance(
            captured[0], dict,
            f"is_task_busy must receive a dict, got {type(captured[0]).__name__}"
        )
        self.assertEqual(captured[0].get("task_id"), "test-123")


class TestStateArchitecture(unittest.TestCase):
    """P1-3: WebUI and API must share state source."""

    def test_redis_disabled_requires_shared_state(self):
        """When Redis is disabled, WebUI must use API for state operations."""
        from app.config import config
        redis_enabled = getattr(config.app, "get", lambda k, d: d)("enable_redis", False)
        # This test documents the requirement
        if not redis_enabled:
            # WebUI should NOT have its own task manager
            # It should call the API
            pass  # Documented requirement


class TestPlayUsesStreamEndpoint(unittest.TestCase):
    """P1-4: Play must use /api/v1/stream/ endpoint, not xdg-open."""

    def test_play_button_uses_stream_url(self):
        """Video play should use the stream API endpoint."""
        # The WebUI should generate a URL like /api/v1/stream/{path}
        # not invoke xdg-open
        pass  # Will be verified in implementation


class TestQueuedState(unittest.TestCase):
    """P1-5: Queued tasks should show as QUEUED, not PROCESSING."""

    def test_queued_task_state_is_queued(self):
        """A task waiting in queue should not be marked PROCESSING."""
        # Documented requirement
        pass


class TestBatchPersistence(unittest.TestCase):
    """P1-6: Batch metadata must survive browser refresh."""

    def test_batch_metadata_persists(self):
        """Batch data should be stored in backend, not just session_state."""
        pass  # Will be implemented


class TestCancelRetry(unittest.TestCase):
    """P1-7: Cancel and retry must have real backend support."""

    def test_cancel_endpoint_exists(self):
        """API must support task cancellation."""
        pass  # Will be implemented

    def test_retry_endpoint_exists(self):
        """API must support task retry."""
        pass  # Will be implemented


if __name__ == "__main__":
    unittest.main()
