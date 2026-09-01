"""
Discover page — "What should I make?"

Primary landing experience showing ranked content opportunities
generated from real trend data → Content Intelligence → Visual Opportunity Engine.
"""

import streamlit as st
import sys
import os

# Ensure shared module is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from webui.shared import (
    tr, collect_task_summaries, task_state_filter_key,
    webui_api_client, st as st_mod,
)


def render_discover():
    """Render the Discover page (primary landing — "What should I make?")."""
    st.markdown(
        "<h1 style='margin-bottom: 0.25rem;'>Discover</h1>"
        "<p style='color: #64748b; margin-top: 0; margin-bottom: 1.5rem;'>"
        "Find trending topics that are visually producible with your footage providers.</p>",
        unsafe_allow_html=True,
    )

    # Fetch controls
    col1, col2, col3 = st.columns(3)
    with col1:
        geo = st.selectbox(
            "Geography",
            options=["ID", "US", "GB", "AU", "MY", "SG"],
            index=0,
            key="discover_geo",
        )
    with col2:
        language = st.selectbox(
            "Language",
            options=["id", "en"],
            index=0,
            key="discover_language",
        )
    with col3:
        category = st.selectbox(
            "Category",
            options=["general", "technology", "business", "sports", "entertainment", "health", "science"],
            index=0,
            key="discover_category",
        )

    # Action buttons
    bcol1, bcol2 = st.columns(2)
    with bcol1:
        fetch_clicked = st.button(
            "Fetch Live Trends",
            key="discover_fetch_btn",
            type="primary",
            use_container_width=True,
            icon=":material/refresh:",
        )
    with bcol2:
        custom_clicked = st.button(
            "Analyze Custom Topics",
            key="discover_custom_btn",
            use_container_width=True,
            icon=":material/edit:",
        )

    # Custom topics input
    if st.session_state.get("discover_show_text_input"):
        custom_topics = st.text_area(
            "Enter topics (one per line)",
            height=100,
            key="discover_custom_topics",
            placeholder="AI in healthcare\nClimate change\nProductivity hacks",
        )
        if st.button("Analyze These Topics", key="discover_analyze_custom", type="primary"):
            topics = [t.strip() for t in custom_topics.split("\n") if t.strip()]
            if topics:
                with st.spinner("Analyzing topics..."):
                    result = webui_api_client.api_content_intelligence_analyze(
                        topics=topics,
                        use_providers=False,
                        geo=geo,
                        language=language,
                        category=category,
                    )
                st.session_state["discover_result"] = result
                st.session_state["discover_show_text_input"] = False
                st.rerun()

    if custom_clicked:
        st.session_state["discover_show_text_input"] = True
        st.rerun()

    if fetch_clicked:
        st.session_state["discover_show_text_input"] = False
        with st.spinner("Fetching live data from providers..."):
            try:
                result = webui_api_client.api_content_intelligence_analyze(
                    topics=[],
                    use_providers=True,
                    geo=geo,
                    language=language,
                    category=category,
                    max_signals_per_provider=15,
                )
                st.session_state["discover_result"] = result
            except Exception as e:
                st.session_state["discover_result"] = {
                    "success": False,
                    "message": f"Network error: {str(e)}",
                }
        st.rerun()

    # Display results
    result = st.session_state.get("discover_result")
    if result is None:
        st.info("Click 'Fetch Live Trends' to discover content opportunities from real-time data sources.")
        return

    if not result.get("success", True):
        st.error(f"Analysis failed: {result.get('message', 'Unknown error')}")
        return

    # Show hypotheses as opportunity cards
    hypotheses = result.get("hypotheses", [])
    opportunities = result.get("opportunities", [])

    if hypotheses:
        st.subheader(f"Content Ideas ({len(hypotheses)})")
        for i, hyp in enumerate(hypotheses[:5]):
            with st.container(border=True):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**{hyp.get('topic', 'Unknown')}**")
                    hook = hyp.get("proposed_hook", "")
                    if hook:
                        st.caption(f"Hook: {hook}")
                    keywords = hyp.get("keywords", [])
                    if keywords:
                        st.caption(f"Keywords: {', '.join(keywords[:5])}")
                with col2:
                    confidence = hyp.get("confidence", 0)
                    st.progress(confidence, text=f"Confidence: {confidence:.0%}")
                    if st.button(
                        "Create Video",
                        key=f"discover_create_{i}",
                        type="primary",
                        use_container_width=True,
                    ):
                        st.session_state["prefill_video_subject"] = hyp.get("topic", "")
                        st.session_state["prefill_script_prompt"] = (
                            f"Topic: {hyp.get('topic', '')}. Hook: {hyp.get('proposed_hook', '')}. "
                            f"Promise: {hyp.get('content_promise', '')}. Format: {hyp.get('format', '')}."
                        )
                        st.session_state["prefill_video_keywords"] = ", ".join(hyp.get("keywords", []))
                        st.session_state["nav_view"] = "create"
                        st.rerun()

    if opportunities:
        st.subheader(f"Opportunities ({len(opportunities)})")
        for i, opp in enumerate(opportunities[:5]):
            with st.container(border=True):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**{opp.get('topic', 'Unknown')}**")
                    angle = opp.get("angle", "")
                    if angle:
                        st.caption(f"Angle: {angle}")
                with col2:
                    score = opp.get("score_total", 0)
                    st.caption(f"Score: {score:.2f}" if score else "Score: N/A")

    if not hypotheses and not opportunities:
        st.info("No results. Try adjusting the controls or fetching live data.")
