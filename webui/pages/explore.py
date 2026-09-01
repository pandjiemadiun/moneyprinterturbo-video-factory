"""
Explore page — Deep intelligence workspace.

Advanced users can inspect trends, opportunities, viral patterns,
scores, evidence, providers, freshness, and source links.
Uses progressive disclosure (tabs, expanders, cards).
"""

import streamlit as st
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from webui.shared import (
    tr, webui_api_client, st as st_mod,
)


def render_explore():
    """Render the Explore page."""
    st.markdown(
        "<h1 style='margin-bottom: 0.25rem;'>Explore</h1>"
        "<p style='color: #64748b; margin-top: 0; margin-bottom: 1.5rem;'>"
        "Deep intelligence workspace — inspect trends, opportunities, and viral patterns.</p>",
        unsafe_allow_html=True,
    )

    # Controls in expander for progressive disclosure
    with st.expander("Analysis Controls", expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            geo = st.selectbox("Geography", options=["ID", "US", "GB", "AU", "MY", "SG"], index=0, key="explore_geo")
        with col2:
            language = st.selectbox("Language", options=["id", "en"], index=0, key="explore_language")
        with col3:
            category = st.selectbox(
                "Category",
                options=["general", "technology", "business", "sports", "entertainment", "health", "science"],
                index=0, key="explore_category",
            )
        max_signals = st.slider("Max signals per provider", min_value=5, max_value=50, value=15, key="explore_max_signals")

    # Action buttons
    bcol1, bcol2, bcol3 = st.columns(3)
    with bcol1:
        fetch_clicked = st.button("Fetch Live Trends", key="explore_fetch_btn", type="primary", use_container_width=True, icon=":material/refresh:")
    with bcol2:
        text_clicked = st.button("Analyze Custom Topics", key="explore_text_btn", use_container_width=True, icon=":material/edit:")
    with bcol3:
        refresh_clicked = st.button("Refresh", key="explore_refresh_btn", use_container_width=True, icon=":material/sync:")

    # Custom topics input
    if st.session_state.get("explore_show_text_input"):
        custom_topics = st.text_area("Enter topics (one per line)", height=100, key="explore_custom_topics")
        if st.button("Analyze Topics", key="explore_analyze_topics", type="primary"):
            topics = [t.strip() for t in custom_topics.split("\n") if t.strip()]
            if topics:
                with st.spinner("Analyzing topics..."):
                    result = webui_api_client.api_content_intelligence_analyze(
                        topics=topics, use_providers=False, geo=geo, language=language, category=category,
                    )
                st.session_state["explore_result"] = result
                st.session_state["explore_show_text_input"] = False
                st.rerun()

    if text_clicked:
        st.session_state["explore_show_text_input"] = True
        st.rerun()

    if fetch_clicked:
        st.session_state["explore_show_text_input"] = False
        with st.spinner("Fetching live data..."):
            try:
                result = webui_api_client.api_content_intelligence_analyze(
                    topics=[], use_providers=True, geo=geo, language=language, category=category,
                    max_signals_per_provider=max_signals,
                )
                st.session_state["explore_result"] = result
            except Exception as e:
                st.session_state["explore_result"] = {"success": False, "message": f"Network error: {str(e)}"}
        st.rerun()

    if refresh_clicked:
        st.session_state["explore_show_text_input"] = False
        with st.spinner("Refreshing..."):
            try:
                result = webui_api_client.api_content_intelligence_analyze(
                    topics=[], use_providers=True, geo=geo, language=language, category=category,
                    max_signals_per_provider=max_signals,
                )
                st.session_state["explore_result"] = result
            except Exception as e:
                st.session_state["explore_result"] = {"success": False, "message": f"Network error: {str(e)}"}
        st.rerun()

    # Display results with progressive disclosure via tabs
    result = st.session_state.get("explore_result")
    if result is None:
        st.info("Click 'Fetch Live Trends' to explore real-time data from external providers.")
        return

    if not result.get("success", True):
        st.error(f"Analysis failed: {result.get('message', 'Unknown error')}")
        return

    # Provider health
    provider_health = result.get("provider_health", {})
    if provider_health:
        with st.expander("Provider Status", expanded=False):
            cols = st.columns(len(provider_health))
            for i, (pid, health) in enumerate(provider_health.items()):
                with cols[i]:
                    status = health.get("status", "unknown")
                    status_icon = {"live": "🟢", "recent": "🟡", "stale": "🟠", "offline": "🔴", "disabled": "⚫", "unknown": "⚪"}.get(status, "⚪")
                    st.metric(label=f"{status_icon} {pid}", value=status.upper(), delta=f"Signals: {health.get('total_signals', 0)}")

    # Tabs for different intelligence views
    tabs = st.tabs(["Trends", "Opportunities", "Patterns", "Hypotheses"])

    with tabs[0]:
        trends = result.get("trends", [])
        if trends:
            for i, trend in enumerate(trends[:10]):
                with st.container(border=True):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.markdown(f"**{trend.get('topic', 'Unknown')}**")
                    with col2:
                        st.caption(f"Source: {trend.get('data_source_classification', 'UNKNOWN')}")
                    meta_col1, meta_col2, meta_col3 = st.columns(3)
                    with meta_col1:
                        st.caption(f"Strength: {trend.get('strength', 0):.2f}")
                    with meta_col2:
                        st.caption(f"Freshness: {trend.get('freshness', 0):.2f}")
                    with meta_col3:
                        sources = trend.get("sources", [])
                        st.caption(f"Sources: {', '.join(sources) if sources else 'N/A'}")
                    evidence = trend.get("evidence", [])
                    source_url = None
                    for ev in evidence:
                        if ev.startswith("url="):
                            source_url = ev[4:]
                            break
                        elif ev.startswith("source_url="):
                            source_url = ev[10:]
                            break
                    if source_url:
                        st.link_button("Open Source", url=source_url, help="Open original source")
        else:
            st.info("No trends found.")

    with tabs[1]:
        opportunities = result.get("opportunities", [])
        if opportunities:
            for i, opp in enumerate(opportunities[:5]):
                with st.container(border=True):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.markdown(f"**{opp.get('topic', 'Unknown')}**")
                    with col2:
                        score = opp.get("score_total", 0)
                        st.caption(f"Score: {score:.2f}" if score else "Score: N/A")
                    st.caption(f"Angle: {opp.get('angle', 'N/A')}")
                    st.caption(f"Audience: {opp.get('audience', 'N/A')}")
                    if opp.get("score_explanation"):
                        with st.expander("Score Explanation", expanded=False):
                            st.caption(opp["score_explanation"])
        else:
            st.info("No opportunities found.")

    with tabs[2]:
        patterns = result.get("patterns", [])
        if patterns:
            for i, pattern in enumerate(patterns[:5]):
                with st.container(border=True):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.markdown(f"**{pattern.get('name', 'Unknown')}**")
                    with col2:
                        st.caption(f"Type: {pattern.get('pattern_type', 'N/A')}")
                    st.caption(f"Description: {pattern.get('description', 'N/A')}")
        else:
            st.info("No patterns found.")

    with tabs[3]:
        hypotheses = result.get("hypotheses", [])
        if hypotheses:
            for i, hyp in enumerate(hypotheses[:5]):
                with st.container(border=True):
                    st.markdown(f"**{hyp.get('topic', 'Unknown')}**")
                    col1, col2 = st.columns(2)
                    with col1:
                        st.caption(f"Hook: {hyp.get('proposed_hook', 'N/A')}")
                    with col2:
                        st.caption(f"Promise: {hyp.get('content_promise', 'N/A')}")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.caption(f"Format: {hyp.get('format', 'N/A')}")
                    with col2:
                        st.caption(f"Confidence: {hyp.get('confidence', 0):.2f}")
                    with col3:
                        keywords = hyp.get("keywords", [])
                        st.caption(f"Keywords: {', '.join(keywords[:3])}")
                    if st.button("Create Video", key=f"explore_create_{i}", type="primary"):
                        st.session_state["prefill_video_subject"] = hyp.get("topic", "")
                        st.session_state["prefill_script_prompt"] = (
                            f"Topic: {hyp.get('topic', '')}. Hook: {hyp.get('proposed_hook', '')}. "
                            f"Promise: {hyp.get('content_promise', '')}. Format: {hyp.get('format', '')}."
                        )
                        st.session_state["prefill_video_keywords"] = ", ".join(hyp.get("keywords", []))
                        st.session_state["nav_view"] = "create"
                        st.rerun()
        else:
            st.info("No hypotheses found.")
