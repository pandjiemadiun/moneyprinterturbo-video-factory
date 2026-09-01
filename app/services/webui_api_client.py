"""API client for WebUI → API communication.

All task operations go through the API. WebUI never owns task state.
"""

import os
import uuid
from typing import Any

import httpx
from loguru import logger


def _get_api_base_url() -> str:
    """Get the API base URL.

    When running in Docker, the API is reachable via the container name on the mpt-network.
    """
    return os.getenv("MPT_API_BASE_URL", "http://moneyprinterturbo-api:8080")


def _get_request_id() -> str:
    return str(uuid.uuid4())


def api_create_task(params: dict) -> dict:
    """Create a task via API. Returns {task_id, ...}."""
    base_url = _get_api_base_url()
    try:
        resp = httpx.post(
            f"{base_url}/api/v1/videos",
            json=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {})
    except Exception as exc:
        logger.error(f"api_create_task failed: {exc}")
        raise


def api_get_task(task_id: str) -> dict | None:
    """Get task status via API."""
    base_url = _get_api_base_url()
    try:
        resp = httpx.get(
            f"{base_url}/api/v1/tasks/{task_id}",
            timeout=10,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        return data.get("data")
    except Exception as exc:
        logger.warning(f"api_get_task failed: {exc}")
        return None


def api_list_tasks(page: int = 1, page_size: int = 50) -> tuple[list[dict], int]:
    """List tasks via API. Returns (tasks, total)."""
    base_url = _get_api_base_url()
    try:
        resp = httpx.get(
            f"{base_url}/api/v1/tasks",
            params={"page": page, "page_size": page_size},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        return data.get("tasks", []), data.get("total", 0)
    except Exception as exc:
        logger.warning(f"api_list_tasks failed: {exc}")
        return [], 0


def api_delete_task(task_id: str) -> dict:
    """Delete a task via API."""
    base_url = _get_api_base_url()
    try:
        resp = httpx.delete(
            f"{base_url}/api/v1/tasks/{task_id}",
            timeout=30,
        )
        if resp.status_code == 404:
            return {"success": False, "message": "task not found"}
        resp.raise_for_status()
        data = resp.json().get("data", {})
        # API returns empty data {} on success; normalize to explicit success
        if "success" not in data:
            data["success"] = True
        return data
    except Exception as exc:
        logger.error(f"api_delete_task failed: {exc}")
        return {"success": False, "message": str(exc)}


def api_clear_tasks(status: str) -> dict:
    """Clear tasks by status via API."""
    base_url = _get_api_base_url()
    try:
        resp = httpx.post(
            f"{base_url}/api/v1/tasks/clear",
            params={"status": status},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("data", {"count": 0})
    except Exception as exc:
        logger.error(f"api_clear_tasks failed: {exc}")
        return {"success": False, "count": 0, "message": str(exc)}


def api_clear_all_tasks() -> dict:
    """Clear all tasks via API."""
    base_url = _get_api_base_url()
    try:
        resp = httpx.post(
            f"{base_url}/api/v1/tasks/clear-all",
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json().get("data", {"count": 0})
    except Exception as exc:
        logger.error(f"api_clear_all_tasks failed: {exc}")
        return {"success": False, "count": 0, "message": str(exc)}


def api_cancel_task(task_id: str) -> dict:
    """Cancel a task via API."""
    base_url = _get_api_base_url()
    try:
        resp = httpx.post(
            f"{base_url}/api/v1/tasks/{task_id}/cancel",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        # API returns empty data {} on success; normalize to explicit success
        if "success" not in data:
            data["success"] = True
        return data
    except Exception as exc:
        logger.error(f"api_cancel_task failed: {exc}")
        return {"success": False, "message": str(exc)}


def api_retry_task(task_id: str) -> dict:
    """Retry a task via API."""
    base_url = _get_api_base_url()
    try:
        resp = httpx.post(
            f"{base_url}/api/v1/tasks/{task_id}/retry",
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        # API returns empty data {} on success; normalize to explicit success
        if "success" not in data:
            data["success"] = True
        return data
    except Exception as exc:
        logger.error(f"api_retry_task failed: {exc}")
        return {"success": False, "message": str(exc)}


def api_save_batch(batch_id: str, data: dict) -> dict:
    """Save batch metadata via API."""
    base_url = _get_api_base_url()
    try:
        resp = httpx.post(
            f"{base_url}/api/v1/batches",
            json=data,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("data", {"success": True})
    except Exception as exc:
        logger.error(f"api_save_batch failed: {exc}")
        return {"success": False, "message": str(exc)}


def api_get_batch(batch_id: str) -> dict | None:
    """Get batch metadata via API."""
    base_url = _get_api_base_url()
    try:
        resp = httpx.get(
            f"{base_url}/api/v1/batches/{batch_id}",
            timeout=10,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get("data")
    except Exception as exc:
        logger.warning(f"api_get_batch failed: {exc}")
        return None


def api_content_intelligence_analyze(
    topics: list[str] | None = None,
    use_providers: bool = False,
    geo: str = "ID",
    language: str = "id",
    category: str = "general",
    min_score: float = 0.0,
    max_signals_per_provider: int = 20,
) -> dict:
    """Run Content Intelligence analysis via API."""
    base_url = _get_api_base_url()
    try:
        resp = httpx.post(
            f"{base_url}/api/v1/content-intelligence/analyze",
            json={
                "topics": topics or [],
                "use_providers": use_providers,
                "geo": geo,
                "language": language,
                "category": category,
                "min_score": min_score,
                "max_signals_per_provider": max_signals_per_provider,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("data", {})
    except Exception as exc:
        logger.error(f"api_content_intelligence_analyze failed: {exc}")
        return {"success": False, "message": str(exc)}


def api_content_intelligence_hypotheses(
    topics: list[str] | None = None,
    use_providers: bool = False,
    geo: str = "ID",
    language: str = "id",
    category: str = "general",
) -> dict:
    """Generate content hypotheses via API."""
    base_url = _get_api_base_url()
    try:
        resp = httpx.post(
            f"{base_url}/api/v1/content-intelligence/hypotheses",
            json={
                "topics": topics or [],
                "use_providers": use_providers,
                "geo": geo,
                "language": language,
                "category": category,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("data", {})
    except Exception as exc:
        logger.error(f"api_content_intelligence_hypotheses failed: {exc}")
        return {"success": False, "message": str(exc)}


def api_visual_opportunity_analyze(
    topics: list[str] | None = None,
    category: str = "general",
    providers: list[str] | None = None,
    max_queries_per_topic: int = 6,
    force_refresh: bool = False,
) -> dict:
    """Assess visual feasibility for topics via API."""
    base_url = _get_api_base_url()
    try:
        resp = httpx.post(
            f"{base_url}/api/v1/visual-opportunity/analyze",
            json={
                "topics": topics or [],
                "category": category,
                "providers": providers or ["pexels", "pixabay", "coverr"],
                "max_queries_per_topic": max_queries_per_topic,
                "force_refresh": force_refresh,
            },
            timeout=180,
        )
        resp.raise_for_status()
        return resp.json().get("data", {})
    except Exception as exc:
        logger.error(f"api_visual_opportunity_analyze failed: {exc}")
        return {"success": False, "message": str(exc)}


def api_content_factory_produce(
    topic: str,
    visual_concepts: list[dict[str, Any]] | None = None,
    visual_feasibility_score: float = 0.0,
    relevance_confidence: float = 0.0,
    language: str = "id",
    video_aspect: str = "portrait",
    preferred_providers: list[str] | None = None,
) -> dict:
    """Produce a video from a validated visual opportunity via Content Factory."""
    base_url = _get_api_base_url()
    try:
        resp = httpx.post(
            f"{base_url}/api/v1/content-factory/produce",
            json={
                "topic": topic,
                "visual_concepts": visual_concepts or [],
                "visual_feasibility_score": visual_feasibility_score,
                "relevance_confidence": relevance_confidence,
                "language": language,
                "video_aspect": video_aspect,
                "preferred_providers": preferred_providers or ["pexels", "pixabay", "coverr"],
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("data", {})
    except Exception as exc:
        logger.error(f"api_content_factory_produce failed: {exc}")
        return {"success": False, "message": str(exc)}
