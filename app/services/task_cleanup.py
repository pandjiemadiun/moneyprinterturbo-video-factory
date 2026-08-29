"""Task cleanup and lifecycle operations for the canonical UI.

Provides backend support for:
- Delete task (state + filesystem)
- Clear completed tasks
- Clear failed tasks
- Clear orphaned tasks
- Clear all historical tasks
"""

import os
import shutil
import uuid
from loguru import logger

from app.models import const
from app.models.schema import VideoParams
from app.services import state as sm
from app.services.task import is_task_busy
from app.utils import utils


def delete_task(task_id: str) -> dict:
    """Delete a task and its associated artifacts.

    Returns:
        dict with 'success' bool and 'message' str.

    Removes:
    - Task state from the state backend
    - Task directory and all contents from filesystem
    """
    task = sm.state.get_task(task_id)
    if task is None:
        return {"success": False, "message": "task not found"}

    # Block deletion of busy tasks — pass the task dict, not the task_id string
    if is_task_busy(task):
        logger.warning(f"cannot delete busy task: {task_id}")
        return {"success": False, "message": "task is still running"}

    # Delete filesystem artifacts
    task_dir = utils.task_dir(task_id)
    if os.path.isdir(task_dir):
        try:
            shutil.rmtree(task_dir)
            logger.info(f"deleted task directory: {task_dir}")
        except Exception as exc:
            logger.warning(f"failed to delete task directory {task_dir}: {exc}")
            return {"success": False, "message": f"failed to delete files: {exc}"}

    # Delete state
    sm.state.delete_task(task_id)
    logger.info(f"deleted task: {task_id}")
    return {"success": True, "message": "deleted"}


def get_task_ids_by_status(status: str, max_tasks: int = 1000) -> list[str]:
    """Get task IDs filtered by status.

    Status values: 'completed', 'failed', 'queued', 'processing', 'cancelled'
    """
    all_tasks = []
    page = 1
    page_size = 100
    while True:
        tasks, total = sm.state.get_all_tasks(page, page_size)
        if not tasks:
            break
        all_tasks.extend(tasks)
        if len(all_tasks) >= total or len(all_tasks) >= max_tasks:
            break
        page += 1

    result = []
    for task in all_tasks:
        task_state = task.get("state")
        task_id = task.get("task_id", "")
        if not task_id:
            continue

        if status == "completed":
            if task_state == const.TASK_STATE_COMPLETE:
                result.append(task_id)
        elif status == "failed":
            if task_state == const.TASK_STATE_FAILED:
                result.append(task_id)
        elif status == "processing":
            if task_state == const.TASK_STATE_PROCESSING:
                result.append(task_id)
        elif status == "queued":
            # Exact match: only QUEUED state
            if task_state == const.TASK_STATE_QUEUED:
                result.append(task_id)
        elif status == "cancelled":
            if task_state == const.TASK_STATE_CANCELLED:
                result.append(task_id)

    return result


def clear_tasks_by_status(status: str) -> dict:
    """Clear all tasks of a given status. Returns {success, count, errors}."""
    task_ids = get_task_ids_by_status(status)
    deleted = 0
    errors = []
    for task_id in task_ids:
        result = delete_task(task_id)
        if result["success"]:
            deleted += 1
        else:
            errors.append(f"{task_id}: {result['message']}")
    logger.info(f"cleared {deleted} tasks with status={status}")
    return {"success": True, "count": deleted, "errors": errors}


def get_orphan_task_ids() -> list[str]:
    """Find tasks that exist in state but have no valid artifact."""
    orphans = []
    page = 1
    page_size = 100
    while True:
        tasks, total = sm.state.get_all_tasks(page, page_size)
        if not tasks:
            break
        for task in tasks:
            task_id = task.get("task_id", "")
            if not task_id:
                continue
            # Completed tasks without video files are orphans
            if task.get("state") == const.TASK_STATE_COMPLETE:
                videos = task.get("videos") or []
                has_valid_video = any(
                    v and os.path.isfile(v) for v in videos
                )
                if not has_valid_video:
                    orphans.append(task_id)
        if len(tasks) < page_size:
            break
        page += 1

    return orphans


def clear_orphan_tasks() -> dict:
    """Clear orphaned tasks (completed but no valid artifact)."""
    orphans = get_orphan_task_ids()
    deleted = 0
    errors = []
    for task_id in orphans:
        result = delete_task(task_id)
        if result["success"]:
            deleted += 1
        else:
            errors.append(f"{task_id}: {result['message']}")
    logger.info(f"cleared {deleted} orphan tasks")
    return {"success": True, "count": deleted, "errors": errors}


def clear_all_tasks() -> dict:
    """Clear ALL tasks except busy ones. Destructive operation."""
    deleted = 0
    errors = []
    for status in ["completed", "failed", "queued", "processing", "cancelled"]:
        result = clear_tasks_by_status(status)
        deleted += result["count"]
        errors.extend(result["errors"])
    return {"success": True, "count": deleted, "errors": errors}


def retry_task(task_id: str) -> dict:
    """Retry a failed task. Creates a new task with the same parameters."""
    from app.services.task import start as tm_start
    from app.controllers.v1.video import task_manager as api_task_manager

    task = sm.state.get_task(task_id)
    if task is None:
        return {"success": False, "message": "task not found"}

    # Only retry failed or cancelled tasks
    if task.get("state") not in [const.TASK_STATE_FAILED, const.TASK_STATE_CANCELLED]:
        return {"success": False, "message": "only failed or cancelled tasks can be retried"}

    # Get original parameters
    params_dict = task.get("params", {})
    if not params_dict:
        return {"success": False, "message": "original parameters not available"}

    # Create new task
    new_task_id = str(uuid.uuid4())
    try:
        params = VideoParams(**params_dict)
    except Exception as exc:
        return {"success": False, "message": f"invalid parameters: {exc}"}

    # Submit to API task manager
    api_task_manager.add_task(
        tm_start,
        task_id=new_task_id,
        params=params,
    )

    logger.info(f"retried task {task_id} as {new_task_id}")
    return {"success": True, "new_task_id": new_task_id}


def cancel_task(task_id: str) -> dict:
    """Cancel a queued task.

    Only QUEUED tasks are cancellable. PROCESSING tasks have no real worker
    interruption, so we never present a fake cancellation for them. The task
    manager's cancellation set is updated so the worker skips the task before
    execution, and the state is marked CANCELLED for the UI.
    """
    task = sm.state.get_task(task_id)
    if task is None:
        return {"success": False, "message": "task not found"}

    state = task.get("state")
    if state == const.TASK_STATE_PROCESSING:
        return {"success": False, "message": "cannot cancel running task"}
    if state == const.TASK_STATE_COMPLETE:
        return {"success": False, "message": "task already completed"}
    if state == const.TASK_STATE_FAILED:
        return {"success": False, "message": "task already failed"}
    if state == const.TASK_STATE_CANCELLED:
        return {"success": False, "message": "task already cancelled"}

    # Real worker interruption: tell the task manager to skip this task if it
    # is still enqueued (not yet executing). The worker checks _cancelled_ids
    # in run_task / dequeue and will not execute a cancelled task.
    try:
        from app.controllers.v1.video import task_manager as api_task_manager

        if api_task_manager is not None:
            api_task_manager.cancel(task_id)
    except Exception as exc:
        logger.warning(f"task_manager.cancel failed for {task_id}: {exc}")

    # Persist the CANCELLED terminal state so the UI and API agree.
    sm.state.update_task(task_id, state=const.TASK_STATE_CANCELLED)
    logger.info(f"cancelled task: {task_id}")
    return {"success": True, "message": "cancelled"}