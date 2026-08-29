"""Batch service for WebUI content-factory workflow.

Enables creating multiple video generation tasks as a grouped batch.
Batch metadata is stored in Streamlit session state (per-session persistence).
Task states are read from the existing state backend.
"""

import uuid
from datetime import datetime

from loguru import logger

from app.config import config
from app.models.schema import VideoParams
from app.services import state as sm
from app.services import webui_task


def submit_batch(
    topics: list[dict],
    common_params: dict,
) -> str:
    """Submit multiple video generation tasks as a batch.

    Args:
        topics: List of topic configs, each containing:
            - subject (str): Video subject/topic
            - video_count (int): Number of videos for this topic
            - video_terms (str, optional): Search terms/keywords
            - video_source (str, optional): Override source for this topic
        common_params: Shared parameters for all topics:
            - video_source (str): Default material source
            - voice_name (str): TTS voice name
            - subtitle_enabled (bool): Whether to generate subtitles
            - video_aspect (str): Video aspect ratio
            - And other VideoParams fields

    Returns:
        Tuple of (batch_id, task_ids) where batch_id is the UUID string
        identifying this batch and task_ids is the list of task UUIDs created.

    Raises:
        ValueError: If topics list is empty.
    """
    if not topics:
        raise ValueError("Batch must contain at least one topic")

    batch_id = str(uuid.uuid4())
    task_ids = []

    for index, topic in enumerate(topics, start=1):
        task_id = str(uuid.uuid4())
        task_params = _build_task_params(topic, common_params, index)

        try:
            webui_task.submit_generation(
                task_id=task_id,
                params=task_params,
            )
            task_ids.append(task_id)
            logger.info(
                f"batch {batch_id}: submitted task {index}/{len(topics)} "
                f"(task_id={task_id}, subject={topic.get('subject', 'N/A')!r})"
            )
        except Exception as exc:
            logger.error(
                f"batch {batch_id}: failed to submit task {index}/{len(topics)} "
                f"(subject={topic.get('subject', 'N/A')!r}): {exc}"
            )
            task_ids.append(task_id)

    logger.success(
        f"batch {batch_id}: submitted {len(task_ids)} tasks"
    )
    return batch_id, task_ids


def get_batch_status(task_ids: list[str]) -> dict:
    """Derive batch status from individual task states.

    Args:
        task_ids: List of task IDs in the batch.

    Returns:
        Dict with batch status:
            - total (int): Total number of tasks
            - complete (int): Number of completed tasks
            - failed (int): Number of failed tasks
            - processing (int): Number of processing tasks
            - queued (int): Number of queued tasks
            - progress (float): Average progress across all tasks (0-100)
            - is_complete (bool): Whether all tasks are done
    """
    total = len(task_ids)
    complete = 0
    failed = 0
    processing = 0
    queued = 0
    total_progress = 0.0

    for task_id in task_ids:
        task = sm.state.get_task(task_id)
        if task is None:
            failed += 1
            continue

        state = task.get("state")
        progress = task.get("progress", 0)
        total_progress += progress

        if state == 1:  # TASK_STATE_COMPLETE
            complete += 1
        elif state == -1:  # TASK_STATE_FAILED
            failed += 1
        elif state == 4:  # TASK_STATE_PROCESSING
            processing += 1
        else:
            queued += 1

    avg_progress = total_progress / total if total > 0 else 0.0
    is_complete = (complete + failed) == total

    return {
        "total": total,
        "complete": complete,
        "failed": failed,
        "processing": processing,
        "queued": queued,
        "progress": round(avg_progress, 1),
        "is_complete": is_complete,
    }


def get_batch_tasks(task_ids: list[str]) -> list[dict]:
    """Retrieve task states for a batch.

    Args:
        task_ids: List of task IDs.

    Returns:
        List of task state dicts with batch-specific metadata added.
    """
    tasks = []
    for task_id in task_ids:
        task = sm.state.get_task(task_id)
        if task is not None:
            task["task_id"] = task_id
            tasks.append(task)
    return tasks


def _build_task_params(
    topic: dict,
    common_params: dict,
    index: int,
) -> VideoParams:
    """Build VideoParams for a single topic within a batch.

    Args:
        topic: Topic-specific config.
        common_params: Shared batch parameters.
        index: Topic index (1-based).

    Returns:
        VideoParams instance for this topic.
    """
    params = dict(common_params)

    params["video_subject"] = topic.get("subject", f"Batch Video {index}")
    params["video_count"] = topic.get("video_count", 1)

    if "video_terms" in topic:
        params["video_terms"] = topic["video_terms"]
    if "video_source" in topic:
        params["video_source"] = topic["video_source"]

    if "video_aspect" not in params:
        params["video_aspect"] = "9:16"
    if "video_source" not in params:
        params["video_source"] = "pexels"

    return VideoParams(**params)
