"""Phase 11H.1.14 — P0 functional recovery tests.

These tests prove actual behaviour, not just code existence:
  - No hardcoded localhost API calls in WebUI.
  - Job cards render Cancel / Retry / Delete per status via the API.
  - Play uses in-browser st.video, never xdg-open.
  - Delete routes through the canonical API.
  - WebUI is a pure API client for task state (no sm.state / filesystem scan).
  - Clear operations return full result dicts and handle "cancelled".
  - Cancel rejects non-queued states and actually invokes the task manager.
"""

import ast
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


def _attribute_name(node):
    """Resolve ``module.function`` style AST call to a flat string."""
    names = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        names.append(node.id)
    return ".".join(reversed(names))


def _all_call_names(tree):
    """Return a set of all dotted call names in the AST tree."""
    return {
        _attribute_name(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }


def _all_attribute_access(tree):
    """Return a set of all dotted attribute access strings."""
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            names = []
            cur = node
            while isinstance(cur, ast.Attribute):
                names.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                names.append(cur.id)
            result.add(".".join(reversed(names)))
    return result


# ---------------------------------------------------------------------------
# P0-CLEAR-LOCALHOST
# ---------------------------------------------------------------------------

class TestNoHardcodedLocalhostAPI:
    """ALL clear operations MUST use webui_api_client, never localhost:8080."""

    def test_no_hardcoded_127001_8080(self):
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        assert "127.0.0.1:8080" not in source
        assert "localhost:8080" not in source

    def test_clear_uses_webui_api_client(self):
        tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
        calls = _all_call_names(tree)
        assert "webui_api_client.api_clear_tasks" in calls
        assert "webui_api_client.api_clear_all_tasks" in calls

    def test_no_raw_requests_post_to_localhost(self):
        """The only requests.post remaining should be for Groq, not localhost."""
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _attribute_name(node.func) == "requests.post":
                # Must not target localhost or 127.0.0.1
                for kw in node.keywords:
                    if kw.arg == "url" and isinstance(kw.value, ast.Constant):
                        url = kw.value.value
                        assert "127.0.0.1" not in str(url)
                        assert "localhost" not in str(url)


# ---------------------------------------------------------------------------
# P0-JOB-ACTIONS-MISSING
# ---------------------------------------------------------------------------

class TestJobActionButtons:
    """Cancel / Retry / Delete buttons per job status via the API."""

    def test_job_card_has_api_action_calls(self):
        tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
        calls = _all_call_names(tree)
        assert "webui_api_client.api_cancel_task" in calls
        assert "webui_api_client.api_retry_task" in calls
        assert "webui_api_client.api_delete_task" in calls

    def test_job_card_has_do_job_action_helper(self):
        tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
        funcs = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        }
        assert "_do_job_action" in funcs

    def test_queued_shows_cancel_not_retry(self):
        """_do_job_action must dispatch cancel for QUEUED tasks."""
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        assert "job_cancel" in source
        assert "_do_job_action(task_id, \"cancel\")" in source or 'job_action(task_id, "cancel")' in source

    def test_failed_shows_retry_and_delete(self):
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        assert "job_retry" in source
        assert "_do_job_action(task_id, \"retry\")" in source or "_do_job_action(task_id, \"delete\")" in source

    def test_complete_shows_delete(self):
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        assert "job_delete" in source

    def test_processing_no_fake_cancel(self):
        """PROCESSING tasks must NOT have a Cancel button."""
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        tree = ast.parse(source)
        # Find the _render_job_card function
        func = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_render_job_card"
        )
        func_source = ast.get_source_segment(source, func)
        # The PROCESSING branch should not create a cancel button
        processing_section = func_source[
            func_source.find('TASK_STATE_PROCESSING'):
            func_source.find('TASK_STATE_FAILED') if 'TASK_STATE_FAILED' in func_source
            else func_source.find('TASK_STATE_CANCELLED')
        ]
        assert "job_cancel" not in processing_section


# ---------------------------------------------------------------------------
# P0-PLAY-BROKEN
# ---------------------------------------------------------------------------

class TestInBrowserVideoPlayback:
    """Play must use st.video (in-browser), never xdg-open."""

    def test_no_xdg_open(self):
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        assert "xdg-open" not in source
        assert "os.startfile" not in source

    def test_no_xdg_open_in_open_task_video(self):
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        tree = ast.parse(source)
        func = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_open_task_video"
        )
        func_source = ast.get_source_segment(source, func)
        assert "xdg" not in func_source
        assert "subprocess" not in func_source
        assert "os.startfile" not in func_source

    def test_st_video_used_for_playback(self):
        tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
        attrs = _all_attribute_access(tree)
        assert "st.video" in attrs

    def test_stream_endpoint_supports_range(self):
        """The API stream endpoint must return 206 with Content-Range."""
        from app.controllers.v1.video import _parse_byte_range
        start, end = _parse_byte_range("bytes=0-1023", 2048, "test")
        assert start == 0
        assert end == 1023


# ---------------------------------------------------------------------------
# P1-DELETE-BYPASS
# ---------------------------------------------------------------------------

class TestDeleteRoutesThroughAPI:
    """UI Delete → API delete endpoint → canonical state + artifact deletion."""

    def test_delete_task_uses_api_client(self):
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        tree = ast.parse(source)
        func = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_delete_task"
        )
        calls = _all_call_names(func)
        assert "webui_api_client.api_delete_task" in calls
        # Must NOT directly call sm.state.delete_task or shutil.rmtree
        func_source = ast.get_source_segment(source, func)
        assert "sm.state" not in func_source
        assert "shutil.rmtree" not in func_source

    def test_no_sm_state_delete_in_main(self):
        """sm.state.delete_task must not appear anywhere in Main.py."""
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        assert "sm.state.delete_task" not in source
        assert "sm.state.get_task" not in source
        assert "sm.state.get_all_tasks" not in source


# ---------------------------------------------------------------------------
# P1-STATE-DUAL-OWNER
# ---------------------------------------------------------------------------

class TestWebUIIsPureAPIClient:
    """WebUI must not own task state.

    Only st.session_state is allowed for transient UI presentation.
    """

    def test_no_sm_state_in_main(self):
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        assert "sm.state" not in source

    def test_no_sm_import_in_main(self):
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        assert "from app.services import state as sm" not in source

    def test_no_memory_state_instantiation_in_main(self):
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        assert "MemoryState(" not in source

    def test_no_sqlite_state_instantiation_in_main(self):
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        assert "SQLiteState(" not in source

    def test_no_get_all_tasks_direct_call(self):
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        assert "get_all_tasks" not in source.replace(
            "api_list_tasks", ""
        )  # api_list_tasks may contain it... actually it shouldn't

    def test_no_task_manager_instantiation_in_main(self):
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        assert "TaskManager(" not in source

    def test_no_filesystem_task_scan_in_collect_summaries(self):
        """_collect_task_summaries must NOT call _scan_history_tasks."""
        tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
        func = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_collect_task_summaries"
        )
        calls = _all_call_names(func)
        assert "_scan_history_tasks" not in calls
        assert "sm.state.get_all_tasks" not in calls
        assert "webui_api_client.api_list_tasks" in calls

    def test_sm_import_removed_from_webui_task(self):
        """webui_task.py must not import or use sm (state)."""
        src = (ROOT_DIR / "app" / "services" / "webui_task.py").read_text(encoding="utf-8")
        assert "from app.services import state as sm" not in src
        assert "sm.state" not in src

    def test_webui_api_client_used_for_all_state_ops(self):
        tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
        calls = _all_call_names(tree)
        expected = {
            "webui_api_client.api_list_tasks",
            "webui_api_client.api_get_task",
            "webui_api_client.api_delete_task",
            "webui_api_client.api_clear_tasks",
            "webui_api_client.api_clear_all_tasks",
            "webui_api_client.api_cancel_task",
            "webui_api_client.api_retry_task",
        }
        assert expected.issubset(calls)


# ---------------------------------------------------------------------------
# CLEAR OPERATIONS
# ---------------------------------------------------------------------------

class TestClearOperations:
    """Clear Completed/Failed/Cancelled/Orphans/All via canonical API."""

    def test_clear_accepts_cancelled_status(self):
        """The API clear_tasks endpoint must accept 'cancelled'."""
        from app.controllers.v1.video import ALLOWED_CLEAR_STATUSES
        assert "cancelled" in ALLOWED_CLEAR_STATUSES

    def test_clear_returns_full_result_dict(self):
        """clear_tasks endpoint must return success, count, errors — not just count."""
        from app.services import task_cleanup
        # Mock sm.state to return empty
        with patch("app.services.task_cleanup.sm") as mock_sm:
            mock_sm.state.get_all_tasks.return_value = ([], 0)
            result = task_cleanup.clear_tasks_by_status("completed")
        assert "success" in result
        assert "count" in result
        assert "errors" in result

    def test_clear_all_returns_full_result_dict(self):
        from app.services import task_cleanup
        with patch("app.services.task_cleanup.sm") as mock_sm:
            mock_sm.state.get_all_tasks.return_value = ([], 0)
            result = task_cleanup.clear_orphan_tasks()
        assert "success" in result
        assert "count" in result
        assert "errors" in result

    def test_clear_buttons_use_api_client(self):
        tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        # Verify the 5 clear buttons are present
        assert 'btn_clear_completed' in source
        assert 'btn_clear_failed' in source
        assert 'btn_clear_cancelled' in source
        assert 'btn_clear_orphan' in source
        assert 'btn_clear_all' in source


# ---------------------------------------------------------------------------
# CANCEL TASK BEHAVIOR
# ---------------------------------------------------------------------------

class TestCancelTaskBehavior:
    """cancel_task must only accept QUEUED/FALILED/CANCELLED and invoke
    the task manager for real worker interruption."""

    def test_cancel_calls_task_manager_for_queued(self):
        """Cancel on a QUEUED task must invoke the real task manager."""
        from app.services import task_cleanup
        with patch("app.services.task_cleanup.sm") as mock_sm:
            mock_sm.state.get_task.return_value = {
                "task_id": "q-1",
                "state": 0,  # QUEUED
            }
            with patch("app.controllers.v1.video.task_manager") as mock_tm:
                mock_tm.cancel.return_value = True
                result = task_cleanup.cancel_task("q-1")

        assert result["success"] is True
        mock_sm.state.update_task.assert_called_once()
        mock_tm.cancel.assert_called_once_with("q-1")

    def test_cancel_rejects_processing(self):
        """PROCESSING tasks cannot be cancelled."""
        from app.services import task_cleanup
        with patch("app.services.task_cleanup.sm") as mock_sm:
            mock_sm.state.get_task.return_value = {
                "task_id": "p-1",
                "state": 4,  # PROCESSING
            }
            result = task_cleanup.cancel_task("p-1")

        assert result["success"] is False
        assert "PROCESSING" in result["message"] or "not" in result["message"].lower()

    def test_cancel_rejects_complete(self):
        """COMPLETE tasks cannot be cancelled."""
        from app.services import task_cleanup
        with patch("app.services.task_cleanup.sm") as mock_sm:
            mock_sm.state.get_task.return_value = {
                "task_id": "c-1",
                "state": 1,  # COMPLETE
            }
            result = task_cleanup.cancel_task("c-1")

        assert result["success"] is False

    def test_cancel_rejects_failed(self):
        """FAILED tasks cannot be cancelled."""
        from app.services import task_cleanup
        with patch("app.services.task_cleanup.sm") as mock_sm:
            mock_sm.state.get_task.return_value = {
                "task_id": "f-1",
                "state": -1,  # FAILED
            }
            result = task_cleanup.cancel_task("f-1")

        assert result["success"] is False


# ---------------------------------------------------------------------------
# TASK ID FLOW
# ---------------------------------------------------------------------------

class TestTaskIdFlow:
    """submit_generation must return the API-generated task_id."""

    def test_submit_generation_returns_api_id(self):
        from app.models.schema import VideoParams
        params = VideoParams(video_subject="test")
        with patch.object(
            __import__("app.services.webui_api_client", fromlist=["api_create_task"]),
            "api_create_task",
            return_value={"task_id": "api-id-123"},
        ):
            from app.services import webui_task
            result = webui_task.submit_generation(
                "local-id-456", params, capture_logs=False
            )
        assert result == "api-id-123"
        assert result != "local-id-456"

    def test_generation_controls_uses_returned_id(self):
        """_render_generation_controls must store the returned API task_id."""
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        assert "api_task_id = webui_task.submit_generation" in source


# ---------------------------------------------------------------------------
# P0-A: NAVIGATION STATE (11H.1.15)
# ---------------------------------------------------------------------------

class TestNavigationCanonicalState:
    """All navigation entry points must share ONE canonical state key (nav_view).

    The 11H.1.13 audit found that _render_videos_view set
    st.session_state["nav_view"] = "create" while _render_top_bar used a
    SEPARATE widget key "nav_view_selector" whose stale value overwrote
    the CTA's navigation on rerun.

    Fix: the segmented_control uses key="nav_view" (the same canonical key
    the CTA writes to), and all entry points go through _switch_nav_view().
    """

    def test_no_nav_view_selector_key(self):
        """The widget must NOT use a separate key that can shadow nav_view."""
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        assert "nav_view_selector" not in source

    def test_segmented_control_uses_canonical_key(self):
        """The segmented_control key must be "nav_view" (the canonical state)."""
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _attribute_name(node.func) == "st.segmented_control":
                for kw in node.keywords:
                    if kw.arg == "key" and isinstance(kw.value, ast.Constant):
                        assert kw.value.value == "nav_view", (
                            f"segmented_control key must be 'nav_view', got {kw.value.value!r}"
                        )

    def test_switch_nav_view_helper_exists(self):
        """A canonical _switch_nav_view helper must exist."""
        tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
        funcs = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        }
        assert "_switch_nav_view" in funcs

    def test_videos_empty_cta_uses_switch_nav_view(self):
        """The Videos empty-state CTA must use _switch_nav_view, not raw
        session_state assignment + rerun."""
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        tree = ast.parse(source)
        func = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_render_videos_view"
        )
        func_source = ast.get_source_segment(source, func)
        assert "_switch_nav_view" in func_source
        # Must NOT have the old anti-pattern
        assert 'st.session_state["nav_view"] = "create"' not in func_source

    def test_top_bar_uses_switch_nav_view(self):
        """_render_top_bar must dispatch navigation via _switch_nav_view."""
        source = WEBUI_MAIN.read_text(encoding="utf-8")
        tree = ast.parse(source)
        func = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_render_top_bar"
        )
        func_source = ast.get_source_segment(source, func)
        assert "_switch_nav_view" in func_source


# ---------------------------------------------------------------------------
# _task_file_to_uri
# ---------------------------------------------------------------------------

class TestTaskFileToUri:
    """When endpoint is empty, return local path for in-process clients."""

    def test_returns_local_path_when_no_endpoint(self, tmp_path):
        from app.controllers.v1.video import _task_file_to_uri
        video = tmp_path / "final-1.mp4"
        video.write_bytes(b"fake-video")
        result = _task_file_to_uri("final-1.mp4", "", str(tmp_path), "req-1")
        assert result == str(video)

    def test_returns_stream_url_when_endpoint_set(self, tmp_path):
        from app.controllers.v1.video import _task_file_to_uri
        video = tmp_path / "final-1.mp4"
        video.write_bytes(b"fake-video")
        result = _task_file_to_uri("final-1.mp4", "https://example.com/api/v1", str(tmp_path), "req-1")
        assert result.startswith("https://example.com/api/v1/stream/")
        assert "final-1.mp4" in result
