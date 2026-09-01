"""
Review page — Inspect an opportunity before creating.

Shows why a topic is worth making, the evidence, visual feasibility,
provider availability, and proposed format. Then provides a clear
primary action: Create Video.
"""

import streamlit as st
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from webui.shared import tr


def render_review():
    """Render the Review page."""
    item = st.session_state.get("review_item")

    if item is None:
        st.markdown(
            "<h1 style='margin-bottom: 0.25rem;'>Review</h1>"
            "<p style='color: #64748b; margin-top: 0; margin-bottom: 1.5rem;'>"
            "No opportunity selected.</p>",
            unsafe_allow_html=True,
        )
        if st.button("Back to Discover", key="review_back_empty", type="primary", use_container_width=True):
            from webui.nav_pages import discover_page
            st.switch_page(discover_page)
        return

    topic = item.get("topic", "Unknown")
    confidence = item.get("confidence", 0)
    score = item.get("score_total", 0)
    freshness = item.get("freshness", 0)
    hook = item.get("proposed_hook", "")
    angle = item.get("angle", "")
    keywords = item.get("keywords", [])
    content_promise = item.get("content_promise", "")
    format_type = item.get("format", "")
    score_explanation = item.get("score_explanation", "")
    sources = item.get("sources", [])
    evidence = item.get("evidence", [])

    # Header
    st.markdown(
        f"<h1 style='margin-bottom: 0.25rem;'>{topic}</h1>"
        f"<p style='color: #64748b; margin-top: 0; margin-bottom: 1.5rem;'>"
        f"Why this topic is worth making.</p>",
        unsafe_allow_html=True,
    )

    # Score summary
    col1, col2, col3 = st.columns(3)
    with col1:
        if confidence:
            st.metric("Confidence", f"{confidence:.0%}")
        elif score:
            st.metric("Score", f"{score:.2f}")
    with col2:
        if freshness:
            st.metric("Freshness", f"{freshness:.0f} min" if freshness > 1 else "now")
    with col3:
        if format_type:
            st.metric("Format", format_type)

    st.divider()

    # Why this topic
    with st.container(border=True):
        st.subheader("Why This Topic?")
        if hook:
            st.markdown(f"**Hook:** {hook}")
        elif angle:
            st.markdown(f"**Angle:** {angle}")
        if content_promise:
            st.markdown(f"**Promise:** {content_promise}")
        if keywords:
            st.markdown(f"**Keywords:** {', '.join(keywords)}")

    # Evidence
    if evidence or sources:
        with st.container(border=True):
            st.subheader("Evidence")
            if sources:
                st.markdown(f"**Sources:** {', '.join(sources)}")
            if evidence:
                st.markdown("**Trend Evidence:**")
                for ev in evidence[:5]:
                    st.caption(f"• {ev}")

    # Score explanation
    if score_explanation:
        with st.container(border=True):
            st.subheader("Score Explanation")
            st.caption(score_explanation)

    st.divider()

    # Primary action
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Create Video", key="review_create", type="primary", use_container_width=True, icon=":material/movie:"):
            _navigate_to_create(item)
    with col2:
        if st.button("Back to Discover", key="review_back", use_container_width=True):
            from webui.nav_pages import discover_page
            st.switch_page(discover_page)


def _navigate_to_create(item):
    """Transfer opportunity data to Create page and navigate."""
    from webui.nav_pages import create_page

    topic = item.get("topic", "")
    hook = item.get("proposed_hook", "")
    angle = item.get("angle", "")
    keywords = item.get("keywords", [])
    content_promise = item.get("content_promise", "")
    format_type = item.get("format", "")

    st.session_state["prefill_video_subject"] = topic
    st.session_state["prefill_video_script_prompt"] = (
        f"Topic: {topic}. Hook: {hook or angle}. "
        f"Promise: {content_promise}. Format: {format_type}."
    )
    st.session_state["prefill_video_keywords"] = ", ".join(keywords)
    st.switch_page(create_page)
