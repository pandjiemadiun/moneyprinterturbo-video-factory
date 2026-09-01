"""
Review page — decision screen: "Is this actually worth producing?"

Compact, scannable sections answering:
    Opportunity · Trend evidence · Visual evidence · Provider coverage ·
    Production readiness · Suggested angle · Hook · Format · Keywords

Then a clear primary action: Create Video (prefills Create).
Back → Discover. Preserves the prefill contract:
    prefill_video_subject / prefill_video_script_prompt / prefill_video_keywords
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
        if st.button(tr("Back to Discover"), key="review_back_empty", type="primary", use_container_width=True):
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
    providers = item.get("providers", [])
    feasibility = item.get("visual_feasibility", "")
    feasibility_note = item.get("feasibility_note", "")

    # Production gate: producible iff footage providers are available and the
    # feasibility check is not Low. This is the core product rule:
    # TREND -> OPPORTUNITY -> VISUAL FEASIBILITY -> PRODUCTION
    producible = bool(providers) and feasibility != "Low"

    # ── Header ───────────────────────────────────────────────────────────────
    st.markdown(
        f"<h1 style='margin-bottom: 0.25rem;'>{topic}</h1>"
        f"<p style='color: #64748b; margin-top: 0; margin-bottom: 1.5rem;'>"
        f"Decision screen: is this worth producing?</p>",
        unsafe_allow_html=True,
    )

    # ── Score summary ───────────────────────────────────────────────────────
    meta_cols = st.columns(4)
    with meta_cols[0]:
        if confidence:
            st.metric(tr("Confidence"), f"{confidence:.0%}")
        elif score:
            st.metric(tr("Score"), f"{score:.2f}")
    with meta_cols[1]:
        if freshness:
            st.metric(tr("Freshness"), f"{freshness} min" if freshness > 1 else "now")
    with meta_cols[2]:
        if format_type:
            st.metric(tr("Format"), format_type)
    with meta_cols[3]:
        st.metric(tr("Providers"), len(providers) if providers else len(sources) if sources else "-")

    st.divider()

    # ── Opportunity / Suggested angle ───────────────────────────────────────
    with st.container(border=True):
        st.subheader(tr("Opportunity"))
        if content_promise:
            st.markdown(f"**{tr('Content Promise')}:** {content_promise}")
        if hook:
            st.markdown(f"**{tr('Hook')}:** {hook}")
        elif angle:
            st.markdown(f"**{tr('Suggested Angle')}:** {angle}")
        if keywords:
            st.markdown(f"**{tr('Keywords')}:** {', '.join(keywords)}")
        if score_explanation:
            st.markdown(f"**{tr('Why It Scores')}:** {score_explanation}")

    # ── Trend evidence ───────────────────────────────────────────────────────
    if evidence:
        with st.container(border=True):
            st.subheader(tr("Trend Evidence"))
            for ev in evidence[:5]:
                if isinstance(ev, str) and ev.startswith("url="):
                    st.markdown(f"• [source]({ev[4:]})")
                elif isinstance(ev, str) and ev.startswith("source_url="):
                    st.markdown(f"• [source]({ev[10:]})")
                else:
                    st.markdown(f"• {ev}")

    # ── Visual evidence + Provider coverage + Production readiness ──────────
    with st.container(border=True):
        st.subheader(tr("Production Readiness"))
        col1, col2 = st.columns([1, 2])
        with col1:
            if feasibility:
                st.markdown(f"**{tr('Visual Feasibility')}:** {feasibility}")
            gate = "✅ Producible" if producible else "⚠️ Not producible"
            st.markdown(f"**{tr('Production Gate')}:** {gate}")
        with col2:
            if providers:
                st.markdown(f"**{tr('Provider Coverage')}:** {', '.join(providers)}")
            if feasibility_note:
                st.caption(feasibility_note)
            else:
                st.caption(tr("Provider Coverage Help") or "Footage is verified available on the listed providers.")

    if sources:
        with st.container(border=True):
            st.subheader(tr("Source / Provenance"))
            st.caption(", ".join(sources))

    # ── Primary action ───────────────────────────────────────────────────────
    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if st.button(tr("Create Video"), key="review_create", type="primary", use_container_width=True, icon=":material/movie:"):
            _navigate_to_create(item)
    with c2:
        if st.button(tr("Back to Discover"), key="review_back", use_container_width=True):
            from webui.nav_pages import discover_page
            st.switch_page(discover_page)


def _navigate_to_create(item):
    """Transfer opportunity data to Create page and navigate (prefill contract)."""
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
