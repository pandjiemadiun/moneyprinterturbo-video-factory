import ast
import os
import re
import time
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from loguru import logger

from app.models import const
from app.models.schema import VideoParams
from app.services import webui_api_client, webui_task
from app.utils import logging_utils


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


def _attribute_name(node):
    """把 ``module.function`` 形式的 AST 调用还原为稳定字符串。"""
    names = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        names.append(node.id)
    return ".".join(reversed(names))


def test_generation_controls_submit_background_task_instead_of_blocking_page():
    """WebUI 生成按钮不能重新直接调用同步流水线。

    这是 Issue #1120 白屏的核心回归保护：只要完整页面脚本再次阻塞在
    ``tm.start``，用户在生成期间刷新时仍可能收到指向旧渲染树的 delta。
    """
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_render_generation_controls"
    )
    calls = {
        _attribute_name(node.func)
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    }

    assert "webui_task.submit_generation" in calls
    assert "tm.start" not in calls


def test_webui_runtime_config_updates_do_not_use_blocking_writes():
    """生成期间的普通控件 rerun 不能重新等待长任务持有的配置锁。"""
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    calls = {
        _attribute_name(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "config.runtime_config_lock" not in calls
    assert "config.save_config" not in calls
    assert not calls.intersection(
        {
            "config.app.clear",
            "config.app.pop",
            "config.app.setdefault",
            "config.app.update",
            "config.azure.clear",
            "config.azure.pop",
            "config.azure.setdefault",
            "config.azure.update",
            "config.chatterbox.clear",
            "config.chatterbox.pop",
            "config.chatterbox.setdefault",
            "config.chatterbox.update",
            "config.elevenlabs.clear",
            "config.elevenlabs.pop",
            "config.elevenlabs.setdefault",
            "config.elevenlabs.update",
            "config.siliconflow.clear",
            "config.siliconflow.pop",
            "config.siliconflow.setdefault",
            "config.siliconflow.update",
            "config.ui.clear",
            "config.ui.pop",
            "config.ui.setdefault",
            "config.ui.update",
        }
    )

    synchronized_sections = {
        "app",
        "azure",
        "chatterbox",
        "elevenlabs",
        "siliconflow",
        "ui",
    }
    direct_writes = []
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]

        for target in targets:
            if not isinstance(target, ast.Subscript):
                continue
            section = target.value
            if (
                isinstance(section, ast.Attribute)
                and isinstance(section.value, ast.Name)
                and section.value.id == "config"
                and section.attr in synchronized_sections
            ):
                direct_writes.append(node.lineno)

    assert direct_writes == []


@pytest.mark.parametrize(
    ("ui_config", "expected_open_count"),
    [
        ({}, 1),
        ({"open_task_folder_on_completion": True}, 1),
        ({"open_task_folder_on_completion": False}, 0),
    ],
)
def test_completed_task_renders_subject_named_video_download(
    tmp_path, ui_config, expected_open_count
):
    """完成任务应提供成片下载，并按 WebUI 配置决定是否自动打开目录。"""
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    selected_nodes = []
    target_names = {
        "_DOWNLOAD_FILENAME_INVALID_PATTERN",
        "_build_video_download_name",
        "_normalize_task_state",
        "_render_generation_task_snapshot",
    }
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in target_names
            for target in node.targets
        ):
            selected_nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in target_names:
            selected_nodes.append(node)

    class FakeColumn:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeStreamlit:
        def __init__(self):
            self.session_state = {}
            self.downloads = []
            self.videos = []
            self.link_buttons = []
            self.successes = []
            self.warnings = []
            self.errors = []

        def columns(self, count):
            return [FakeColumn() for _ in range(count)]

        def video(self, video_path):
            self.videos.append(video_path)

        def link_button(self, label, url, **kwargs):
            self.link_buttons.append((label, url, kwargs))

        def success(self, message):
            self.successes.append(message)

        def warning(self, message):
            self.warnings.append(message)

        def error(self, message):
            self.errors.append(message)

    video_path = tmp_path / "final-1.mp4"
    video_path.write_bytes(b"video-content")
    fake_st = FakeStreamlit()
    open_task_folder = MagicMock()
    namespace = {
        "Mapping": Mapping,
        "config": SimpleNamespace(ui=ui_config),
        "const": const,
        "logger": MagicMock(),
        "mimetypes": __import__("mimetypes"),
        "open_task_folder": open_task_folder,
        "os": os,
        "re": re,
        "st": fake_st,
        "tr": lambda key: key,
        "_render_generation_logs": lambda _task_id: None,
    }
    module = ast.fix_missing_locations(ast.Module(body=selected_nodes, type_ignores=[]))
    exec(compile(module, str(WEBUI_MAIN), "exec"), namespace)

    namespace["_render_generation_task_snapshot"](
        "download-test",
        {
            "state": const.TASK_STATE_COMPLETE,
            "progress": 100,
            "videos": [str(video_path)],
            "warnings": [],
            "video_subject": "A day: in / Shanghai?",
        },
    )

    assert fake_st.videos == [str(video_path)]
    assert len(fake_st.link_buttons) == 1
    label, url, kwargs = fake_st.link_buttons[0]
    assert label == "Download Video"
    assert url == "/api/v1/download/download-test/final-1.mp4"
    assert kwargs["key"] == "download_generated_video_download-test_0"
    assert open_task_folder.call_count == expected_open_count
    if expected_open_count:
        open_task_folder.assert_called_once_with("download-test")


def test_submit_generation_returns_api_task_id_without_blocking():
    """Submit must return the API task_id quickly without blocking on the
    server-side pipeline. The API handles execution asynchronously."""
    task_id = "background-submit-test"
    api_task_id = "api-generated-uuid-12345"

    params = VideoParams(video_subject="异步生成测试")
    with patch.object(
        webui_api_client, "api_create_task", return_value={"task_id": api_task_id}
    ) as mock_create:
        started_at = time.monotonic()
        returned_id = webui_task.submit_generation(
            task_id, params, capture_logs=False
        )
        elapsed = time.monotonic() - started_at

    assert mock_create.called
    assert returned_id == api_task_id
    assert elapsed < 1.0


def test_submit_generation_propagates_api_errors():
    """API failures during submission must raise so the UI can surface them."""
    task_id = "error-propagation-test"
    params = VideoParams(video_subject="错误传播测试")
    with patch.object(
        webui_api_client,
        "api_create_task",
        side_effect=ConnectionError("API unreachable"),
    ):
        with pytest.raises(ConnectionError, match="API unreachable"):
            webui_task.submit_generation(task_id, params, capture_logs=False)


def test_submit_generation_does_not_use_legacy_tm_or_state():
    """webui_task must not reference tm.start, _task_manager, or sm.state."""
    src = (ROOT_DIR / "app" / "services" / "webui_task.py").read_text(encoding="utf-8")
    assert "tm.start" not in src
    assert "_task_manager" not in src
    assert "sm.state" not in src


def test_worker_logs_are_available_without_streamlit_session_state():
    """后台日志写入线程安全缓存，页面只需轮询快照即可恢复实时日志。"""
    task_id = "captured-log-test"
    with webui_task._task_logs_lock:
        webui_task._task_logs.pop(task_id, None)

    webui_task._append_task_log(task_id, "unique background task log")

    records = webui_task.get_task_logs(task_id)
    assert len(records) == 1
    assert records[0].endswith("unique background task log")

    with webui_task._task_logs_lock:
        webui_task._task_logs.pop(task_id, None)


def test_generation_log_fragment_refreshes_within_half_a_second():
    """日志轮询间隔不能退回到明显落后于终端输出的秒级刷新。"""
    assert webui_task.TASK_LOG_REFRESH_INTERVAL_SECONDS <= 0.5

    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_render_running_generation_task"
    )
    decorator = function.decorator_list[0]
    assert isinstance(decorator, ast.Call)
    assert _attribute_name(decorator.func) == "st.fragment"
    run_every = next(
        keyword.value for keyword in decorator.keywords if keyword.arg == "run_every"
    )
    assert ast.unparse(run_every) == ("webui_task.TASK_LOG_REFRESH_INTERVAL_SECONDS")


def test_generation_submit_skips_duplicate_config_save():
    """提交任务后不能在页面末尾再次等待配置锁。"""
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    controls = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_render_generation_controls"
    )

    assert isinstance(controls.body[-1], ast.Return)
    assert ast.unparse(controls.body[-1].value) == "start_button"

    create_view = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_render_create_view"
    )

    submitted_assignment = next(
        node
        for node in create_view.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "generation_submitted"
            for target in node.targets
        )
    )
    assert isinstance(submitted_assignment.value, ast.Call)
    assert _attribute_name(submitted_assignment.value.func) == (
        "_render_generation_controls"
    )

    guarded_save = next(
        node
        for node in create_view.body
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "not generation_submitted"
    )
    guarded_calls = {
        _attribute_name(node.func)
        for node in ast.walk(guarded_save)
        if isinstance(node, ast.Call)
    }
    assert guarded_calls == {"_save_runtime_config"}


def test_terminal_logger_reload_preserves_task_log_handler():
    """热重载只能替换终端 handler，不能清空后台任务的日志 sink。"""
    previous_handler_id = logging_utils._terminal_handler_id
    try:
        with (
            patch.object(logging_utils.logger, "remove") as remove,
            patch.object(logging_utils.logger, "add", return_value=456) as add,
        ):
            logging_utils._terminal_handler_id = 123
            handler_id = logging_utils.configure_terminal_logger(
                sink=object(),
                level="DEBUG",
                colorize=True,
            )

        assert handler_id == 456
        remove.assert_called_once_with(123)
        add.assert_called_once()
        assert logging_utils._terminal_handler_id == 456
    finally:
        logging_utils._terminal_handler_id = previous_handler_id


def test_submit_generation_returns_api_id_not_local_placeholder():
    """submit_generation must return the API-generated task_id, not the
    local placeholder uuid, so the UI polls the correct task."""
    local_id = "local-placeholder-uuid"
    api_id = "api-generated-uuid-abcdef"

    params = VideoParams(video_subject="task_id flow test")
    with patch.object(
        webui_api_client, "api_create_task", return_value={"task_id": api_id}
    ):
        returned = webui_task.submit_generation(
            task_id=local_id, params=params, capture_logs=False
        )

    assert returned == api_id
    assert returned != local_id
