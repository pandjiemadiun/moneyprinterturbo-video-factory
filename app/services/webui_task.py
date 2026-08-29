import threading
from collections import deque

from loguru import logger

from app.config import config
from app.models.schema import VideoParams
from app.services.loomloom import LoomLoomConfirmedVideoRequest
from app.services import webui_api_client
from app.utils.logging_utils import format_log_record


# WebUI no longer owns task state or a TaskManager.
# All task operations go through the API via webui_api_client.
_task_logs: dict[str, deque[str]] = {}
_task_logs_lock = threading.RLock()
_MAX_LOG_TASKS = 20
_MAX_LOG_RECORDS_PER_TASK = 1000
TASK_LOG_REFRESH_INTERVAL_SECONDS = 0.5


def _append_task_log(task_id: str, message: str) -> None:
    """按任务保存有限数量的日志，供 Streamlit Fragment 安全轮询。"""
    with _task_logs_lock:
        records = _task_logs.get(task_id)
        if records is None:
            # 只保留最近任务的日志，避免 WebUI 服务长时间运行后持续占用内存。
            # dict 保持插入顺序；任务日志仅用于界面诊断，淘汰最早记录不影响任务。
            if len(_task_logs) >= _MAX_LOG_TASKS:
                oldest_task_id = next(iter(_task_logs))
                _task_logs.pop(oldest_task_id, None)
            records = deque(maxlen=_MAX_LOG_RECORDS_PER_TASK)
            _task_logs[task_id] = records
        records.append(message.rstrip())


def get_task_logs(task_id: str) -> list[str]:
    """返回日志快照，避免页面渲染期间持有后台线程使用的锁。"""
    with _task_logs_lock:
        return list(_task_logs.get(task_id, ()))


def _run_generation(
    task_id: str,
    params: VideoParams,
    capture_logs: bool,
    voice_preview: dict | None = None,
    loomloom_video_request: LoomLoomConfirmedVideoRequest | None = None,
) -> dict:
    """Placeholder — API now handles task execution."""
    pass


def submit_generation(
    task_id: str,
    params: VideoParams,
    capture_logs: bool = True,
    voice_preview: dict | None = None,
    loomloom_video_request: LoomLoomConfirmedVideoRequest | None = None,
) -> str:
    """Submit a video generation task via API.

    WebUI no longer owns task state. All operations go through the API.
    Returns the API-generated task_id (which replaces the local placeholder
    so subsequent UI polling queries the correct task).
    """
    task_params = params.model_copy(deep=True)
    try:
        result = webui_api_client.api_create_task(task_params.model_dump())
        api_task_id = result.get("task_id", task_id)
        logger.info(f"task submitted via API: task_id={api_task_id}")
        return api_task_id
    except Exception as exc:
        logger.error(f"submit_generation failed: {exc}")
        raise
