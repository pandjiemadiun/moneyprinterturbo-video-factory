"""
Library page — Unified Videos + Jobs view.

Shows generating, processing, complete, and failed tasks with clear status indicators.
Completed videos are visually prioritized with thumbnails, titles, status, duration, date.
Primary actions: Play, Download, Delete.
"""

import streamlit as st
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from webui.nav_shell import render_nav_shell

from webui.shared import (
    tr, collect_task_summaries, task_state_filter_key, format_task_time, format_task_subject,
    delete_task, open_task_path, open_task_video, build_video_download_name,
    count_processing_tasks, task_manager_label,
    webui_api_client, webui_batch,
    const, tm,
)


def render_library():
    """Render the Library page."""
    render_nav_shell(active="render_library")
    st.markdown(
        "<h1 style='margin-bottom: 0.25rem;'>Library</h1>"
        "<p style='color: #64748b; margin-top: 0; margin-bottom: 1.5rem;'>"
        "All your videos and generation tasks in one place.</p>",
        unsafe_allow_html=True,
    )

    tasks = collect_task_summaries()

    if not tasks:
        st.markdown(
            '<div class="empty-state">'
            '<div class="empty-state-icon">🎬</div>'
            '<h3>No videos yet</h3>'
            '</div>',
            unsafe_allow_html=True,
        )
        if st.button("Discover Ideas", key="library_empty_discover", type="primary", use_container_width=True, icon=":material/explore:"):
            from webui.nav_pages import discover_page
            st.switch_page(discover_page)
        return

    # Status statistics
    queued = sum(1 for t in tasks if t.get("state") not in [const.TASK_STATE_COMPLETE, const.TASK_STATE_FAILED, -1, 1])
    processing = sum(1 for t in tasks if t.get("state") == const.TASK_STATE_PROCESSING)
    completed = sum(1 for t in tasks if t.get("state") == const.TASK_STATE_COMPLETE)
    failed = sum(1 for t in tasks if t.get("state") == const.TASK_STATE_FAILED)
    cancelled = sum(1 for t in tasks if t.get("state") == const.TASK_STATE_CANCELLED)

    # Status summary metrics
    summary_cols = st.columns(5)
    with summary_cols[0]:
        st.metric("Queued", queued)
    with summary_cols[1]:
        st.metric("Processing", processing)
    with summary_cols[2]:
        st.metric("Completed", completed)
    with summary_cols[3]:
        st.metric("Failed", failed)
    with summary_cols[4]:
        st.metric("Cancelled", cancelled)

    st.divider()

    # Task status filter tabs
    status_tabs = [
        ("all", "All"),
        ("processing", "Processing"),
        ("complete", "Completed"),
        ("failed", "Failed"),
    ]
    tabs = st.tabs([label for _, label in status_tabs])
    for (status_key, _), tab in zip(status_tabs, tabs):
        with tab:
            filtered_tasks = [
                task for task in tasks
                if status_key == "all" or task_state_filter_key(task) == status_key
            ]
            if not filtered_tasks:
                st.info(f"No {status_key} tasks.")
                continue
            for task in filtered_tasks:
                _render_task_card(task, status_key)

    # Cleanup operations
    with st.expander("Cleanup", expanded=False):
        st.write("Remove tasks by status.")
        cleanup_cols = st.columns(5)
        with cleanup_cols[0]:
            if st.button("Clear Completed", key="btn_clear_completed", use_container_width=True):
                result = webui_api_client.api_clear_tasks("completed")
                _report_clear_result("completed", result)
                st.rerun()
        with cleanup_cols[1]:
            if st.button("Clear Failed", key="btn_clear_failed", use_container_width=True):
                result = webui_api_client.api_clear_tasks("failed")
                _report_clear_result("failed", result)
                st.rerun()
        with cleanup_cols[2]:
            if st.button("Clear Cancelled", key="btn_clear_cancelled", use_container_width=True):
                result = webui_api_client.api_clear_tasks("cancelled")
                _report_clear_result("cancelled", result)
                st.rerun()
        with cleanup_cols[3]:
            if st.button("Clear Orphan", key="btn_clear_orphan", use_container_width=True):
                result = webui_api_client.api_clear_tasks("orphan")
                _report_clear_result("orphan", result)
                st.rerun()
        with cleanup_cols[4]:
            if st.button("Clear All", key="btn_clear_all", type="primary", use_container_width=True):
                result = webui_api_client.api_clear_all_tasks()
                _report_clear_result("all", result)
                st.rerun()


def _render_task_card(task, status_key):
    """Render a single task card with status, progress, and actions.

    ``status_key`` scopes widget keys so the same task (rendered in the "All"
    tab and its status tab) never collides on its Streamlit element keys.
    """
    task_id = task.get("task_id", "")
    state = task.get("state")
    progress = task.get("progress", 0)

    # Status styling
    if state == const.TASK_STATE_COMPLETE:
        status_class = "status-complete"
        status_label = "Completed"
    elif state == const.TASK_STATE_PROCESSING:
        status_class = "status-processing"
        status_label = "Processing"
    elif state == const.TASK_STATE_CANCELLED:
        status_class = "status-cancelled"
        status_label = "Cancelled"
    elif state == const.TASK_STATE_FAILED:
        status_class = "status-failed"
        status_label = "Failed"
    else:
        status_class = "status-queued"
        status_label = "Queued"

    with st.container(key=f"task_card_{status_key}_{task_id}", border=True):
        col1, col2, col3 = st.columns([3, 1, 1.5])
        with col1:
            # Thumbnail (real if the task summary exposes one, else a status tinted placeholder)
            thumbnail = task.get("thumbnail") or ""
            if thumbnail and os.path.isfile(thumbnail):
                st.image(thumbnail, width=60)
            else:
                st.markdown(
                    f"<div class='thumb-{status_class}' style='width:60px;height:36px;display:flex;"
                    f"align-items:center;justify-content:center;font-size:1.4rem;border-radius:6px;'>🎬</div>",
                    unsafe_allow_html=True,
                )
            st.write(f"**{task.get('subject', task_id)}**")
            if task.get("video_source"):
                st.caption(f"Source: {task['video_source']}")
            elif task.get("source"):
                st.caption(f"Source: {task['source']}")
            st.caption(format_task_time(task.get("mtime")))
        with col2:
            st.markdown(f'<span class="{status_class}">{status_label}</span>', unsafe_allow_html=True)
            if state == const.TASK_STATE_PROCESSING:
                st.progress(progress / 100.0, text=f"{progress}%")
            elif state == const.TASK_STATE_COMPLETE:
                st.progress(1.0, text="100%")
            else:
                st.caption(f"{progress}%")
        with col3:
            video_file = task.get("video_file", "")
            has_video = bool(video_file) and os.path.isfile(video_file)
            is_processing = task_state_filter_key(task) == "processing"
            is_busy = is_processing or tm.is_task_busy(task)

            if state == const.TASK_STATE_QUEUED:
                if st.button("✕", key=f"task_cancel_{status_key}_{task_id}", help="Cancel", type="primary"):
                    _do_job_action(task_id, "cancel")
                    st.rerun()
            elif state == const.TASK_STATE_PROCESSING:
                st.caption("Processing...")
            elif state == const.TASK_STATE_FAILED:
                if st.button("↻", key=f"task_retry_{status_key}_{task_id}", help="Retry"):
                    _do_job_action(task_id, "retry")
                    st.rerun()
                if st.button("✕", key=f"task_delete_{status_key}_{task_id}", help="Delete", type="primary"):
                    _do_job_action(task_id, "delete")
                    st.rerun()
            elif state == const.TASK_STATE_CANCELLED:
                if st.button("↻", key=f"task_retry_{status_key}_{task_id}", help="Retry"):
                    _do_job_action(task_id, "retry")
                    st.rerun()
                if st.button("✕", key=f"task_delete_{status_key}_{task_id}", help="Delete", type="primary"):
                    _do_job_action(task_id, "delete")
                    st.rerun()
            elif state == const.TASK_STATE_COMPLETE:
                acols = st.columns(4)
                with acols[0]:
                    if has_video:
                        with st.popover("▶", key=f"task_play_{status_key}_{task_id}", help="Play"):
                            st.video(video_file)
                    else:
                        st.empty()
                with acols[1]:
                    if st.button("📂", key=f"task_open_{status_key}_{task_id}", help="Open folder"):
                        open_task_path(task_id)
                with acols[2]:
                    if has_video:
                        filename = os.path.basename(video_file)
                        st.link_button("↓", url=f"/api/v1/download/{task_id}/{filename}", key=f"task_download_{status_key}_{task_id}", help="Download")
                    else:
                        st.empty()
                with acols[3]:
                    if st.button("✕", key=f"task_delete_{status_key}_{task_id}", help="Delete", type="primary"):
                        _do_job_action(task_id, "delete")
                        st.rerun()

        if task.get("failed_stage"):
            st.caption(f"Failed at: {task['failed_stage']}")


def _do_job_action(task_id, action):
    """Execute a job-level action (cancel/retry/delete)."""
    if action == "cancel":
        result = webui_api_client.api_cancel_task(task_id)
        success = result.get("success", False)
        label = "Cancelled"
    elif action == "retry":
        result = webui_api_client.api_retry_task(task_id)
        success = result.get("success", False)
        label = "Retried"
    elif action == "delete":
        result = webui_api_client.api_delete_task(task_id)
        success = result.get("success", False)
        label = "Deleted"
    else:
        return
    if success:
        st.success(f"{label} task: {task_id}")
    else:
        msg = result.get("message", str(result))
        st.error(f"{label} failed: {msg}")


def _report_clear_result(target, result):
    """Display the outcome of a clear operation."""
    success = result.get("success", False)
    count = result.get("count", 0)
    errors = result.get("errors", [])
    message = result.get("message", "")
    if success:
        st.success(f"Cleared {target}: {count} task(s) removed.")
    else:
        st.error(f"Clear {target} failed: {message or 'unknown error'}")
    if errors:
        for err in errors:
            st.warning(str(err))
