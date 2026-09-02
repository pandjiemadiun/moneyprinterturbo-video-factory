"""
Canonical application navigation shell (Phase 15B).

Provides an EXPLICIT, visible hamburger navigation drawer that works on mobile
WITHOUT relying on Streamlit's hidden sidebar / left-edge-swipe gestures.

Product IA (single source: webui/nav_pages.NAV_DOMAINS, built from NAV_PAGES)::

    OVERVIEW        -> goldtrader.website (landing)
    DISCOVERY       -> Discover | Review
    PRODUCTION      -> Create
    LIBRARY         -> Library
    SYSTEM          -> Settings

Design decision (Phase 14.8 de-risking, unchanged contract):
  * ``st.popover`` has NO programmatic close() in this Streamlit build and
    ``at.popover`` does not exist in AppTest -> untestable open/close.
  * ``st.modal`` is not available (Phase 14.7 proven).
  * The drawer is therefore a ``st.button`` hamburger toggling a ``st.container``
    bound to ``session_state["mpt_nav_drawer_open"]``. Every control is an
    ``at.button`` -> open/close/reopen fully AppTest-verifiable, and verified in
    the real browser with Playwright.

Navigation rule (Phase 14.6 proven): ``st.switch_page(<Page object>)`` -- never a
bare string. A bare string is resolved by Streamlit as a file path and raises
``StreamlitAPIException`` for callable-registered pages. Static guard lives in
``test/test_webui_navigation.py``.

Usage -- FIRST statement of every ``render_*()`` page function::

    from webui.nav_shell import render_nav_shell
    def render_settings():
        render_nav_shell(active="render_settings")   # first statement
        ...page content...

``active`` is the page slug (``page.url_path``; "" for the default Overview page
served at ``/``). It highlights the active item and disables re-navigation.
"""

import streamlit as st

from webui.shared import locales  # safe: shared.py does not import nav_pages/pages

# Toggle key held in st.session_state. True == drawer rendered; False == not
# rendered at all (no empty shell).
_SESSION_NAV = "mpt_nav_drawer_open"


def _slug(page):
    """Canonical slug for a registered page: its ``url_path`` ("" for Overview)."""
    return page.url_path or ""


def _page_id(page):
    """Stable, collision-free element id for a page, derived from its title."""
    return (page.title or "").lower().replace(" ", "_")


def _render_language():
    """Language selector (persisted in session_state["ui_language"]).

    Moved out of the Streamlit sidebar into this shell so the only hamburger on
    mobile is the application shell's own. Uses ``on_change`` so rendering the
    drawer never triggers a restart.
    """
    def _language_changed():
        st.session_state["ui_language"] = st.session_state.get(
            "global_language_selector", ""
        )

    language_codes = list(locales.keys())
    current_language = st.session_state.get("ui_language", "")
    if current_language not in language_codes:
        current_language = language_codes[0] if language_codes else "en"
    st.selectbox(
        "Language / 语言",
        options=language_codes,
        index=(
            language_codes.index(current_language)
            if current_language in language_codes
            else 0
        ),
        format_func=lambda code: code.split("-")[0].upper(),
        key="global_language_selector",
        on_change=_language_changed,
    )


def render_nav_shell(active=""):
    """Render the hamburger header + navigation drawer.

    The hamburger (``st.button("☰")``) is always visible at the top of every
    page -- no swipe from the edge is required. Toggling it opens/closes an
    inline drawer listing the canonical pages grouped into the 5 product domains
    (Settings always present) and navigating via ``st.switch_page(<Page>)``.
    """
    # LAZY import: webui.nav_pages imports every page module at top level, and
    # every page module imports THIS module at top level -- a top-level import
    # of nav_pages here would create a cycle (page -> nav_shell -> nav_pages ->
    # page). Importing inside the function runs after page import is complete.
    from webui.nav_pages import NAV_PAGES, NAV_DOMAINS

    st.session_state.setdefault(_SESSION_NAV, False)

    # ── Header: compact top nav bar ─────────────────────────────────────────
    # Single-line SaaS chrome: compact hamburger + the page headline.
    # The headline (### {title}) is the *only* headline on the page -- each
    # page body renders a muted subtitle, never a competing H1 -- so the shell
    # and page no longer duplicate each other (Phase 15D defect B).
    # The hamburger is a compact icon button (use_container_width=False so it
    # never stretches into a giant white rectangle -- Phase 15D defect C);
    # compact dark styling is applied via data-testid in styles.css.
    btn_col, title_col = st.columns([1, 14], vertical_alignment="center")
    with btn_col:
        if st.button(
            "☰",
            key="nav_hamburger",
            help="Open navigation",
            use_container_width=False,   # compact icon, not a stretched block
            type="secondary",
        ):
            st.session_state[_SESSION_NAV] = not st.session_state.get(_SESSION_NAV, False)
    with title_col:
        active_page = next((p for p in NAV_PAGES if _slug(p) == active), None)
        st.markdown(f"### {active_page.title if active_page else 'VIDEO FACTORY'}")
    st.divider()

    # ── Drawer: inline panel, rendered only while open ───────────────────────
    if st.session_state.get(_SESSION_NAV):
        with st.container(border=True, key="nav_drawer_panel"):
            st.markdown("### VIDEO FACTORY")
            st.caption("Navigate by product domain")
            st.divider()

            # Single source of truth: NAV_DOMAINS (built from NAV_PAGES).
            for domain_label, pages in NAV_DOMAINS:
                st.markdown(f"<small style='color:#94a3b8'>{domain_label}</small>", unsafe_allow_html=True)
                for page in pages:
                    slug = _slug(page)
                    icon = page.icon or "•"
                    label = f"{icon} {page.title}"
                    is_active = slug == active
                    if st.button(
                        label,
                        key=f"nav_item_{_page_id(page)}",
                        type="primary" if is_active else "secondary",
                        use_container_width=True,
                        disabled=is_active,  # cannot navigate to the current page
                    ):
                        st.session_state[_SESSION_NAV] = False
                        st.switch_page(page)  # OBJECT -- registered StreamlitPage

                st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

            st.divider()

            # Explicit close (the hamburger toggle also closes).
            # NOTE: st.button callbacks do NOT auto-rerun, and this button lives
            # inside the drawer -- so without st.rerun() the drawer is rendered
            # once more before the flag clears. st.rerun() forces a clean
            # re-render with the flag cleared.
            if st.button("✕ Close", key="nav_close", use_container_width=True):
                st.session_state[_SESSION_NAV] = False
                st.rerun()

            _render_language()
