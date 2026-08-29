"""Task cleanup and lifecycle operations for the canonical UI.

Provides backend support for:
- Delete task (state + filesystem)
- Clear completed tasks
- Clear failed tasks
- Clear orphaned tasks (no valid artifact)
- Clear all historical tasks
"""

import os
import shutil
from loguru import logger

from app.services import state as sm
from app.utils import utils


def delete_task(task_id: str) -> bool:
    """Delete a task and its associated artifacts.

    Removes:
    - Task state from the state backend
    - Task directory and all contents from filesystem
    """
    task = sm.state.get_task(task_id)
    if task is None:
        return False

    # Block deletion of busy tasks
    from app.services.task import is_task_busy
    if is_task_busy(task_id):
        logger.warning(f"cannot delete busy task: {task_id}")
        return False

    # Delete filesystem artifacts
    task_dir = utils.task_dir(task_id)
    if os.path.isdir(task_dir):
        try:
            shutil.rmtree(task_dir)
            logger.info(f"deleted task directory: {task_dir}")
        except Exception as exc:
            logger.warning(f"failed to delete task directory {task_dir}: {exc}")

    # Delete state
    sm.state.delete_task(task_id)
    logger.info(f"deleted task: {task_id}")
    return True


def get_task_ids_by_status(status: str, max_tasks: int = 1000) -> list[str]:
    """Get task IDs filtered by status.

    Status values: 'completed', 'failed', 'queued', 'processing', 'cancelled'
    """
    from app.models import const

    status_map = {
        "completed": const.TASK_STATE_COMPLETE,
        "failed": const.TASK_STATE_FAILED,
        "queued": None,  # Special: not complete/failed/processing
        "processing": const.TASK_STATE_PROCESSING,
    }

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

    target_state = status_map.get(status)
    result = []
    for task in all_tasks:
        task_state = task.get("state")
        task_id = task.get("task_id", "")
        if not task_id:
            continue

        if status == "queued":
            # Queued = not complete/failed/processing
            if task_state not in [
                const.TASK_STATE_COMPLETE,
                const.TASK_STATE_FAILED,
                const.TASK_STATE_PROCESSING,
            ]:
                result.append(task_id)
        elif task_state == target_state:
            result.append(task_id)

    return result


def clear_tasks_by_status(status: str) -> int:
    """Clear all tasks of a given status. Returns count deleted."""
    task_ids = get_task_ids_by_status(status)
    deleted = 0
    for task_id in task_ids:
        if delete_task(task_id):
            deleted += 1
    logger.info(f"cleared {deleted} tasks with status={status}")
    return deleted


def get_orphan_task_ids() -> list[str]:
    """Find tasks that exist in state but have no valid artifact."""
    from app.models import const

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
            # Failed tasks older than threshold could be orphans
            # (keeping all failed for now for debugging)
        if len(tasks) < page_size:
            break
        page += 1

    return orphans


def clear_orphan_tasks() -> int:
    """Clear orphaned tasks (completed but no valid artifact)."""
    orphans = get_orphan_task_ids()
    deleted = 0
    for task_id in orphans:
        if delete_task(task_id):
            deleted += 1
    logger.info(f"cleared {deleted} orphan tasks")
    return deleted


def clear_all_tasks() -> int:
    """Clear ALL tasks. Destructive operation."""
    deleted = 0
    for status in ["completed", "failed", "queued", "processing"]:
        deleted += clear_tasks_by_status(status)
    return deleted
