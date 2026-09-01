"""
Discover page — "What should I make?"

Opportunity-first design: real opportunity cards are the primary content.
Filters and configuration are secondary (behind a collapsible expander).
Custom-topic analysis is secondary.
Uses st.switch_page for proper multipage navigation.
"""

import streamlit as st
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from webui.shared import (
    tr, webui_api_client,
)


def render_discover():
    """Render the Discover page (primary landing — "What should I make?")."""
    st.markdown(
        "<h1 style='margin-bottom: 0.25rem;'>Discover</h1>"
        "<p style='color: #64748b; margin-top: 0; margin-bottom: 1rem;'>"
        "Find trending topics that are visually producible with your footage providers.</p>",
        unsafe_allow_html=True,
    )

    # ── Filters (secondary, collapsible) ───────────────────────────────────
    with st.expander("Filters", expanded=False):
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

    # ── Custom topic analysis (secondary, collapsible) ─────────────────────
    with st.expander("Analyze your own topic", expanded=False):
        custom_topics = st.text_area(
            "Enter topics (one per line)",
            height=80,
            key="discover_custom_topics",
            placeholder="AI in healthcare\nClimate change\nProductivity hacks",
        )
        if st.button("Analyze These Topics", key="discover_analyze_custom", type="secondary", use_container_width=True):
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
                st.rerun()

    # ── Primary content: Opportunity cards ─────────────────────────────────
    result = st.session_state.get("discover_result")

    if result is None:
        # Empty state — no data yet
        st.markdown(
            '<div class="empty-state">'
            '<div class="empty-state-icon">🔍</div>'
            '<h3>No live opportunities available right now</h3>'
            '<p>Fetch real-time trend data to discover content opportunities.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        if st.button("Fetch Live Trends", key="discover_fetch_empty", type="primary", use_container_width=True, icon=":material/refresh:"):
            _fetch_opportunities(geo, language, category)
        return

    if not result.get("success", True):
        st.error(f"Analysis failed: {result.get('message', 'Unknown error')}")
        if st.button("Retry", key="discover_retry", type="primary", use_container_width=True):
            _fetch_opportunities(geo, language, category)
        return

    # Show provider health (compact, if available)
    provider_health = result.get("provider_health", {})
    if provider_health:
        healthy = sum(1 for v in provider_health.values() if v.get("status") in ("live", "recent"))
        total = len(provider_health)
        if healthy < total:
            st.caption(f"⚠️ {healthy}/{total} data sources available")

    # Show hypotheses as opportunity cards
    hypotheses = result.get("hypotheses", [])
    opportunities = result.get("opportunities", [])

    if hypotheses:
        st.subheader(f"Content Ideas ({len(hypotheses)})")
        for i, hyp in enumerate(hypotheses[:5]):
            _render_opportunity_card(hyp, i, "hypothesis")

    if opportunities:
        st.subheader(f"Opportunities ({len(opportunities)})")
        for i, opp in enumerate(opportunities[:5]):
            _render_opportunity_card(opp, i, "opportunity")

    if not hypotheses and not opportunities:
        st.info("No results. Try adjusting the filters or fetching live data.")

    # Refresh button (secondary, at bottom)
    st.divider()
    if st.button("Refresh", key="discover_refresh", use_container_width=True, icon=":material/sync:"):
        _fetch_opportunities(geo, language, category)


def _render_opportunity_card(item, index, item_type):
    """Render a compact opportunity card with score, freshness, providers, and CTA."""
    topic = item.get("topic", "Unknown")

    # Extract metrics
    confidence = item.get("confidence", 0)
    score = item.get("score_total", 0)
    freshness = item.get("freshness", 0)
    hook = item.get("proposed_hook", "")
    angle = item.get("angle", "")
    keywords = item.get("keywords", [])
    content_promise = item.get("content_promise", "")
    format_type = item.get("format", "")

    with st.container(border=True):
        # Header row: Topic + Score
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(f"**{topic}**")
        with col2:
            if item_type == "hypothesis" and confidence:
                st.progress(confidence, text=f"{confidence:.0%}")
            elif score:
                st.caption(f"Score: {score:.2f}")

        # Reason line
        if hook:
            st.caption(f"💡 {hook}")
        elif angle:
            st.caption(f"💡 {angle}")

        # Metrics row
        meta_col1, meta_col2, meta_col3 = st.columns(3)
        with meta_col1:
            if freshness:
                st.caption(f"🕐 Fresh: {freshness:.0f} min" if freshness > 1 else "🕐 Fresh: now")
        with meta_col2:
            if keywords:
                st.caption(f"🏷️ {', '.join(keywords[:3])}")
        with meta_col3:
            if format_type:
                st.caption(f"📐 {format_type}")

        # Action buttons
        acol1, acol2 = st.columns(2)
        with acol1:
            if st.button(
                "Create Video",
                key=f"discover_create_{item_type}_{index}",
                type="primary",
                use_container_width=True,
            ):
                _navigate_to_create(item)
        with acol2:
            if st.button(
                "Review",
                key=f"discover_review_{item_type}_{index}",
                use_container_width=True,
            ):
                st.session_state["review_item"] = item
                from webui.nav_pages import review_page
                st.switch_page(review_page)


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


def _fetch_opportunities(geo, language, category):
    """Fetch live opportunities from providers."""
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
