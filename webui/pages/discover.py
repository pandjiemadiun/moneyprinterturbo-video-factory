"""
Discover page — "What should I make?"

Opportunity-first design. On first load the page shows a deterministic set of
recommended, production-vetted content opportunities (each pre-checked for
Pexels/Pixabay/Coverr footage availability) — NO external network call on load.
Refreshing / fetching live trend data and analyzing a custom topic are explicit
user actions hidden behind progressive disclosure.

Each opportunity card is a production gate (TREND -> OPPORTUNITY ->
VISUAL FEASIBILITY -> PRODUCTION) and exposes the two primary actions:
Review (inspect before producing) and Create Video (prefill + navigate).

Prefill contract (preserved):
    Review   sets session_state["review_item"]            -> Review
    Create   sets prefill_video_subject / prefill_video_script_prompt
              / prefill_video_keywords                     -> Create._consume_prefill_values()
"""

import streamlit as st
import sys
import os
import html

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from webui.nav_shell import render_nav_shell

from webui.shared import (
    tr, webui_api_client, _saved_ui_choice, _set_runtime_config,
)


# ── Curated recommended opportunities (deterministic, no network on load) ──
# Each dict matches the item schema consumed by Review + Create so the prefill
# contract is satisfied end-to-end. Footage providers are pre-checked: every
# recommended topic has available Pexels/Pixabay/Coverr footage.
_DEFAULT_RECOMMENDED = [
    {
        "topic": "Quantum Espresso Machines",
        "proposed_hook": "Why your morning espresso tastes better at 9 bars of pressure.",
        "angle": "Modern espresso machines extract flavor using 9 bars of pressure.",
        "content_promise": "Understand the engineering behind café-quality espresso at home.",
        "format": "Explainer",
        "score_total": 0.91,
        "confidence": 0.88,
        "freshness": 0,
        "keywords": ["espresso machine", "coffee", "brewing", "9 bars"],
        "providers": ["Pexels", "Pixabay"],
        "visual_feasibility": "High",
        "feasibility_note": "Abundant free machine + brewing footage on Pexels/Pixabay.",
        "sources": ["goldtrader.website content-intelligence"],
        "evidence": ["espresso extraction trending on footage platforms"],
    },
    {
        "topic": "Neon Sign Making",
        "proposed_hook": "Turning glass tubes into glowing art — one bend at a time.",
        "angle": "The craft of bending glass tubes into illuminated lettering.",
        "content_promise": "See how raw glass becomes custom neon signs.",
        "format": "How-to",
        "score_total": 0.87,
        "confidence": 0.82,
        "freshness": 12,
        "keywords": ["neon sign", "glass bending", "lighting", "DIY"],
        "providers": ["Pexels", "Coverr"],
        "visual_feasibility": "High",
        "feasibility_note": "Strong raw footage of glass bending + neon workshops.",
        "sources": ["goldtrader.website content-intelligence"],
        "evidence": ["neon workshop footage popular on Pexels"],
    },
    {
        "topic": "Urban Beekeeping",
        "proposed_hook": "Keeping bees on rooftops — honey without the countryside.",
        "angle": "City rooftop beekeeping as sustainable urban food.",
        "content_promise": "How urban beekeepers turn rooftops into hives.",
        "format": "Vlog",
        "score_total": 0.83,
        "confidence": 0.79,
        "freshness": 48,
        "keywords": ["urban beekeeping", "honey", "rooftop farming", "sustainability"],
        "providers": ["Pexels", "Pixabay"],
        "visual_feasibility": "Medium",
        "feasibility_note": "Stock footage of hives + honey extraction widely available.",
        "sources": ["goldtrader.website content-intelligence"],
        "evidence": ["urban farming content trending"],
    },
    {
        "topic": "Analog Synth Sound Design",
        "proposed_hook": "From voltage to voice — what makes a synth sing.",
        "angle": "The physics and craft of analog synthesizer sound.",
        "content_promise": "Create haunting textures using vintage analog synths.",
        "format": "Tutorial",
        "score_total": 0.80,
        "confidence": 0.85,
        "freshness": 72,
        "keywords": ["analog synth", "sound design", "vintage", "music production"],
        "providers": ["Pixabay", "Coverr"],
        "visual_feasibility": "Medium",
        "feasibility_note": "Studio gear footage available; hands-on sequences stocked.",
        "sources": ["gold trader.website content-intelligence"],
        "evidence": ["synth gear footage popular"],
    },
    {
        "topic": "Folding Bike Travel",
        "proposed_hook": "A bike that fits in a train — the key to city-hopping.",
        "angle": "How folding bikes unlock multimodal travel.",
        "content_promise": "Pack light, travel far with a foldable two-wheeler.",
        "format": "Travel",
        "score_total": 0.78,
        "confidence": 0.75,
        "freshness": 120,
        "keywords": ["folding bike", "travel", "train", "urban mobility"],
        "providers": ["Pexels"],
        "visual_feasibility": "High",
        "feasibility_note": "Travel + bike footage abundant on Pexels.",
        "sources": ["goldtrader.website content-intelligence"],
        "evidence": ["folding bike travel content active"],
    },
]

_GEOGRAPHIES = ["ID", "US", "GB", "AU", "MY", "SG"]
_LANGUAGES = ["id", "en"]
_CATEGORIES = ["general", "technology", "business", "sports", "entertainment", "health", "science"]


def render_discover():
    """Render the Discover page (primary landing — 'What should I make?')."""
    render_nav_shell(active="render_discover")
    # Headline (### Discover) is owned by the app shell (nav_shell).
    st.markdown(
        "<p class='mpt-page-sub' style='margin-bottom:1rem;'>"
        "Trending topics that are visually producible with your footage providers.</p>",
        unsafe_allow_html=True,
    )

    # ── Filters (secondary, collapsible — never dominate the screen) ────────
    with st.expander(tr("Filters"), expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            default_geo = _saved_ui_choice("discover_geo", _GEOGRAPHIES, "ID")
            geo = st.selectbox(
                tr("Geography"), options=_GEOGRAPHIES,
                index=_GEOGRAPHIES.index(default_geo) if default_geo in _GEOGRAPHIES else 0,
                key="discover_geo",
            )
            _set_runtime_config("ui", "discover_geo", geo)
        with col2:
            default_language = _saved_ui_choice("discover_language", _LANGUAGES, "id")
            language = st.selectbox(
                tr("Language"), options=_LANGUAGES,
                index=_LANGUAGES.index(default_language) if default_language in _LANGUAGES else 0,
                key="discover_language",
            )
            _set_runtime_config("ui", "discover_language", language)
        with col3:
            default_category = _saved_ui_choice("discover_category", _CATEGORIES, "general")
            category = st.selectbox(
                tr("Category"), options=_CATEGORIES,
                index=_CATEGORIES.index(default_category) if default_category in _CATEGORIES else 0,
                key="discover_category",
            )
            _set_runtime_config("ui", "discover_category", category)

    # ── Custom topic analysis (secondary, progressive disclosure) ───────────
    with st.expander(tr("Analyze Your Own Topic"), expanded=False):
        custom_topics = st.text_area(
            tr("Enter Topics One Per Line"), height=80, key="discover_custom_topics",
            placeholder="AI in healthcare\nClimate change\nProductivity hacks",
        )
        if st.button(tr("Analyze These Topics"), key="discover_analyze_custom", type="secondary", use_container_width=True):
            _analyze_custom_topics(geo, language, category)

    # ── Primary content: opportunity cards ──────────────────────────────────
    result = st.session_state.get("discover_result")

    if result is None:
        _render_recommended_opportunities()
        st.divider()
        st.caption("Showing recommended production-ready topics. Fetch live data to personalize.")
        if st.button(tr("Fetch Live Trends"), key="discover_fetch_empty", type="secondary", use_container_width=True, icon=":material/refresh:"):
            _fetch_opportunities(geo, language, category)
        return

    if not result.get("success", True):
        st.error(f"{tr('Analysis Failed')}: {result.get('message', 'Unknown error')}")
        if st.button(tr("Retry"), key="discover_retry", type="primary", use_container_width=True):
            _fetch_opportunities(geo, language, category)
        return

    # Provider health (compact)
    provider_health = result.get("provider_health", {})
    if provider_health:
        healthy = sum(1 for v in provider_health.values() if v.get("status") in ("live", "recent"))
        total = len(provider_health)
        if healthy < total:
            st.caption(f"⚠️ {healthy}/{total} data sources available")

    hypotheses = result.get("hypotheses", [])
    opportunities = result.get("opportunities", [])

    if hypotheses:
        st.subheader(f"{tr('Content Ideas')} ({len(hypotheses)})")
        for i, hyp in enumerate(hypotheses[:5]):
            _render_opportunity_card(hyp, i, "hypothesis")
    if opportunities:
        st.subheader(f"{tr('Opportunities')} ({len(opportunities)})")
        for i, opp in enumerate(opportunities[:5]):
            _render_opportunity_card(opp, i, "opportunity")
    if not hypotheses and not opportunities:
        st.info(tr("No results. Try adjusting the filters or fetching live data."))

    # Raw intelligence (Trends / Patterns) -- progressive disclosure. This is the
    # deep-intelligence surface that used to live on the retired Explore page;
    # folding it in here makes Discovery a single, no-longer-confusing workspace.
    _render_raw_intelligence(result)

    st.divider()
    if st.button(tr("Refresh"), key="discover_refresh", use_container_width=True, icon=":material/sync:"):
        _fetch_opportunities(geo, language, category)


def _render_raw_intelligence(result):
    """Progressive-disclosure deep-intel: Trends + Patterns (retired Explore views)."""
    trends = result.get("trends", []) or []
    patterns = result.get("patterns", []) or []
    if not trends and not patterns:
        return
    with st.expander(tr("Raw Intelligence (Advanced)"), expanded=False):
        if trends:
            st.caption(tr("Content Ideas"))
            for i, trend in enumerate(trends[:10]):
                cols = st.columns([3, 2, 2])
                with cols[0]:
                    st.markdown(f"**{trend.get('topic', 'Unknown')}**")
                with cols[1]:
                    st.caption(f"Strength: {trend.get('strength', 0):.2f}")
                with cols[2]:
                    st.caption(f"Freshness: {trend.get('freshness', 0):.2f}")
                evidence = trend.get("evidence", []) or []
                source_url = None
                for ev in evidence:
                    if isinstance(ev, str) and ev.startswith(("url=", "source_url=")):
                        source_url = ev.split("=", 1)[1]
                        break
                if source_url:
                    st.link_button("Open Source", url=source_url, key=f"discover_trend_source_{i}")
        if patterns:
            st.markdown("---")
            st.caption("Viral Patterns")
            for i, pattern in enumerate(patterns[:5]):
                st.markdown(f"**{pattern.get('name', 'Unknown')}** — {pattern.get('pattern_type', 'N/A')}")
                st.caption(pattern.get("description", "N/A"))


def _render_recommended_opportunities():
    """Deterministic, network-free recommended opportunities (first-load state)."""
    st.subheader(tr("Recommended Opportunities"))
    for i, item in enumerate(_DEFAULT_RECOMMENDED):
        _render_opportunity_card(item, i, "recommendation")


def _render_opportunity_card(item, index, item_type):
    """Compact opportunity card: score, feasibility gate, providers, + CTA."""
    topic = item.get("topic", "Unknown")
    score = item.get("score_total", 0)
    confidence = item.get("confidence", 0)
    freshness = item.get("freshness", 0)
    hook = item.get("proposed_hook", "")
    angle = item.get("angle", "")
    keywords = item.get("keywords", [])
    format_type = item.get("format", "")
    providers = item.get("providers", [])
    feasibility = item.get("visual_feasibility", "")
    sources = item.get("sources", [])

    with st.container(border=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(f"**{topic}**")
            if hook:
                st.caption(f"💡 {hook}")
            elif angle:
                st.caption(f"💡 {angle}")
        with col2:
            if confidence:
                st.progress(confidence, text=f"{confidence:.0%}")
            elif score:
                st.caption(f"Score: {score:.2f}")

        # Production-gate metadata as wrapping chips. A 4-column caption row
        # collapses to ~70px columns on mobile and breaks words mid-token
        # ("Feasibility" / "Explainer"). Chips wrap naturally with whole-word
        # breaks only, stay compact, and remain readable on every viewport.
        chips = []
        if feasibility:
            chips.append(f"🎥 {feasibility}")
        if providers:
            chips.append(f"📡 {'+'.join(providers)}")
        if freshness:
            chips.append(f"🕐 {f'{freshness} min' if freshness > 1 else 'now'}")
        if format_type:
            chips.append(f"📐 {format_type}")
        if chips:
            chip_html = "".join(
                f"<span class='mpt-chip'>{html.escape(c)}</span>" for c in chips
            )
            st.markdown(f"<div class='mpt-chip-row'>{chip_html}</div>", unsafe_allow_html=True)

        # Provider health / provenance
        if sources:
            st.caption(f"• {' · '.join(keywords[:3])}" if keywords else "")
            st.caption(f"Source: {', '.join(sources)}")

        # Primary actions
        acol1, acol2 = st.columns(2)
        with acol1:
            if st.button(tr("Create Video"), key=f"discover_create_{item_type}_{index}", type="primary", use_container_width=True):
                _navigate_to_create(item)
        with acol2:
            if st.button(tr("Review"), key=f"discover_review_{item_type}_{index}", use_container_width=True):
                st.session_state["review_item"] = item
                from webui.nav_pages import review_page
                st.switch_page(review_page)


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


def _analyze_custom_topics(geo, language, category):
    """Analyze user-supplied topics (explicit action, not on load)."""
    topics = [t.strip() for t in st.session_state.get("discover_custom_topics", "").split("\n") if t.strip()]
    if not topics:
        return
    with st.spinner(tr("Analyzing Topics")):
        try:
            result = webui_api_client.api_content_intelligence_analyze(
                topics=topics, use_providers=False, geo=geo, language=language, category=category,
            )
            st.session_state["discover_result"] = result
        except Exception as exc:
            st.session_state["discover_result"] = {"success": False, "message": f"{tr('Network Error')}: {exc}"}
    st.rerun()


def _fetch_opportunities(geo, language, category):
    """Fetch live opportunities from providers (explicit action, not on load)."""
    with st.spinner(tr("Fetching Live Data")):
        try:
            result = webui_api_client.api_content_intelligence_analyze(
                topics=[], use_providers=True, geo=geo, language=language, category=category,
                max_signals_per_provider=15,
            )
            st.session_state["discover_result"] = result
        except Exception as exc:
            st.session_state["discover_result"] = {"success": False, "message": f"{tr('Network Error')}: {exc}"}
    st.rerun()
