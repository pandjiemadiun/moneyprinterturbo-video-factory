"""
Overview page — the canonical landing page and situational-awareness dashboard.

Reachable at ``goldtrader.website`` (the default route). Answers, within a few
seconds:
    * Status now  -> Active productions (processing/queued)
    * Done        -> Completed videos
    * Attention   -> Failed jobs (with stage + link to Library)
    * Storage     -> real storage footprint

REAL DATA ONLY. No fake revenue / engagement / growth metrics. Every number is
derived from the task API (state) and a read-only filesystem walk of the storage
volume. If the API is unreachable or there is no data, the page shows an honest
empty / disconnected state -- never fabricated figures.
"""

import streamlit as st
import sys
import os
import html

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from webui.nav_shell import render_nav_shell

from webui.shared import (
    tr, const,
    format_file_size, format_task_time, format_task_subject,
    normalize_task_state, task_state_label,
    get_dashboard_state, get_storage_usage, collect_task_summaries,
    render_metrics_grid,
)


# Canonical production pipeline stages (informational; the dashboard annotates
# them with REAL tallies, never fabricated per-stage progress).
_PIPELINE_STAGES = [
    ("IDEA", "💡"),
    ("SCRIPT", "📝"),
    ("MATERIALS", "📡"),
    ("AUDIO", "🎙"),
    ("COMPOSITION", "🎞️"),
    ("COMPLETE", "✅"),
]


def render_overview():
    """Render the Overview dashboard (default landing)."""
    render_nav_shell(active="")

    # Headline (### Overview) is owned by the app shell (nav_shell) so the
    # page never repeats the title -- this is a muted subtitle only.
    st.markdown(
        "<p class='mpt-page-sub' style='margin-bottom:1.5rem;'>"
        "Video Factory status at a glance. Real data only.</p>",
        unsafe_allow_html=True,
    )

    counts, _active_session, total = get_dashboard_state()
    active = counts["processing"] + counts["queued"]
    completed = counts["complete"]
    failed = counts["failed"]
    total_bytes, file_count = get_storage_usage()

    # ── Pipeline snapshot (4 real metrics) ────────────────────────────────
    # Visual: responsive 2-per-row-on-mobile SaaS metric grid (render_metrics_grid).
    # The real st.metric calls live inside a hidden keyed contract container so
    # the AppTest data contract (Active/Completed/Storage labels) still holds.
    render_metrics_grid(
        [
            {
                "label": "Active",
                "value": f"{active} running",
                "delta": f"{counts['queued']} queued" if counts["queued"] else None,
                "delta_color": "off",
            },
            {
                "label": "Completed",
                "value": completed,
                "delta": f"{completed} total videos" if completed else None,
                "delta_color": "off",
            },
            {
                "label": "Attention",
                "value": failed,
                "delta": f"{failed} failed" if failed else "all clear",
                "delta_color": "inverse" if failed else "off",
            },
            {
                "label": "Storage",
                "value": format_file_size(total_bytes),
                "delta": f"{file_count} files" if file_count else None,
                "delta_color": "off",
            },
        ],
        contract_key="mpt-overview-metrics",
        columns=4,
    )

    # ── Production pipeline (informational, responsive) ────────────────────
    # Real mobile-first layout: a horizontally-scrollable stepper so every stage
    # label stays on one line. The old `st.columns(6)` compressed the stages to
    # ~30-50px on narrow screens and shattered labels ("COMPOSI/TION",
    # "CO/MP/LE/TE"). Each step here has a min-width + white-space:nowrap, and the
    # track scrolls horizontally when 6 steps exceed the viewport (a genuine
    # horizontal sequence -> allowed per Phase 15F). Streamlit 1.59 ignores @media
    # in injected <style>, so this is a single non-media flex rule that works at
    # every width from 320px up to desktop.
    st.markdown("<div style='margin-top:1rem;'><b>Production pipeline</b></div>", unsafe_allow_html=True)
    track_html = ""
    for stage, icon in _PIPELINE_STAGES:
        track_html += (
            f'<div class="mpt-pipeline-step">'
            f'<span class="mpt-pipeline-icon" aria-hidden="true">{html.escape(icon)}</span>'
            f'<span class="mpt-pipeline-label">{html.escape(stage)}</span>'
            f'</div>'
        )
    st.markdown(
        f'<div class="mpt-pipeline"><div class="mpt-pipeline-track">{track_html}</div></div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Active: {active}  ·  Completed: {completed}  ·  Failed: {failed}  ·  "
        f"Total tasks: {total} ·  Storage: {format_file_size(total_bytes)}"
    )
    st.divider()

    # ── Attention center ───────────────────────────────────────────────────
    if failed > 0:
        st.markdown(
            "<h3 style='margin-bottom:0.5rem;'>⚠️ Needs Attention</h3>",
            unsafe_allow_html=True,
        )
        st.warning(f"{failed} production{'s' if failed != 1 else ''} failed and need review.")
        if st.button("Review issues →", key="overview_attention_failed", type="primary", use_container_width=True):
            from webui.nav_pages import library_page
            st.session_state["overview_filter_failed"] = True
            st.switch_page(library_page)
        st.divider()

    # ── Quick actions ──────────────────────────────────────────────────────
    # Class R1 fix (Phase 15G): `st.columns(3)` squeezed three labelled buttons
    # into ~90px columns on 320px and shattered "Open Library" -> "Open/Librar/y".
    # The buttons now live in a single `.mpt-action-row` flex-wrap container:
    # each button has a 160px minimum so on narrow screens the row wraps to
    # fewer (or 1) column instead of squeezing words; on desktop it stays
    # multi-column (flex-grow distributes the extra space). Streamlit 1.59
    # ignores @media in injected <style>, so this is one non-media rule -- no
    # st.columns, no width starvation, explicit mobile contract.
    st.markdown("<b>Quick actions</b>", unsafe_allow_html=True)
    with st.container(key="quick_actions_row"):
        if st.button("🔍 Discover Ideas", key="overview_discover", type="primary", use_container_width=True):
            from webui.nav_pages import discover_page
            st.switch_page(discover_page)
        if st.button("🎬 Create Video", key="overview_create", type="primary", use_container_width=True):
            from webui.nav_pages import create_page
            st.switch_page(create_page)
        if st.button("📚 Open Library", key="overview_library", type="primary", use_container_width=True):
            from webui.nav_pages import library_page
            st.switch_page(library_page)
    st.divider()

    # ── Recent activity (real tasks, newest first) ─────────────────────────
    st.markdown("<b>Recent activity</b>", unsafe_allow_html=True)
    tasks = collect_task_summaries(limit=8)
    if not tasks:
        st.info("No recent production activity yet.")
        if st.button("Discover Ideas", key="overview_recent_discover", type="primary", use_container_width=True):
            from webui.nav_pages import discover_page
            st.switch_page(discover_page)
        return

    for task in tasks:
        _render_activity_row(task)


def _render_activity_row(task):
    """Render one real task as a compact activity row (status + time + subject)."""
    task_id = task.get("task_id", "")
    subject = format_task_subject(task.get("subject") or task_id, max_length=40)
    state = normalize_task_state(task.get("state"))
    has_video = bool(task.get("video_file"))
    status_label = task_state_label(state, has_video=has_video)
    when = format_task_time(task.get("mtime") or 0)

    if state == const.TASK_STATE_COMPLETE:
        icon = "✅"
    elif state == const.TASK_STATE_PROCESSING:
        icon = "🟢"
    elif state == const.TASK_STATE_FAILED:
        icon = "⚠️"
    elif state == const.TASK_STATE_CANCELLED:
        icon = "⏸️"
    else:
        icon = "🟡"

    line = f"{icon} **{subject}** — {status_label} · {when}"
    st.markdown(line)
    if state == const.TASK_STATE_FAILED and task.get("failed_stage"):
        st.caption(f"Failed at: {task['failed_stage']}")
    if has_video:
        st.caption("🎞️ video ready")
