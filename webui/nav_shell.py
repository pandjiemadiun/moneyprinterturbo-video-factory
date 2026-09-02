"""
Canonical application navigation shell.

Provides an EXPLICIT, visible hamburger navigation drawer that works on mobile
WITHOUT relying on Streamlit's hidden sidebar / left-edge-swipe gestures.

Design decision (Phase 14.8 de-risking):
  * ``st.popover`` gives a floating overlay with native click-outside dismiss,
    BUT it has **no programmatic close() in this Streamlit build** (``.close``
    / ``.show`` are phantom ``__getattr__`` stubs that raise
    ``StreamlitAPIException: 'close()' is not a valid Streamlit command``) and
    ``at.popover`` does not exist in AppTest. That fails requirement #6 (explicit
    close) and makes open/close/reopen untestable in AppTest.
  * ``st.modal`` is not available in this build (Phase 14.7 proven).
  * Therefore the drawer is a ``st.button`` hamburger that toggles a
    ``st.container`` panel bound to ``session_state["mpt_nav_drawer_open"]``.
    Every control (hamburger, nav items, ✕ Close, Settings) is an
    ``at.button`` -- so open / navigate / close / reopen is fully AppTest-
    verifiable, and real-browser behaviour is verified with Playwright.

Single source of truth for navigation items, labels, icons, targets and the
active page: ``webui.nav_pages.NAV_PAGES`` (the six registered StreamlitPage
objects).

Navigation rule (Phase 14.6 proven): ``st.switch_page(<Page object>)`` -- never a
bare string. A bare string is resolved by Streamlit as a file path and raises
``StreamlitAPIException`` for callable-registered pages.

Usage -- call once as the FIRST statement of each ``render_*()`` page function::

    from webui.nav_shell import render_nav_shell
    def render_settings():
        render_nav_shell(active="render_settings")   # first statement
        ...page content...

``active`` is the page's ``url_path`` slug (``""`` for the default Discover page
served at ``/``); it highlights the active item and disables re-navigation to
the current page.
"""

import streamlit as st

from webui.shared import locales  # safe: shared.py does not import nav_pages/pages

# Toggle key held in st.session_state. The drawer opens when True and renders a
# st.container; closed = the container is not rendered at all (no empty shell).
_SESSION_NAV = "mpt_nav_drawer_open"


def _slug(page):
    """Canonical slug for a registered page: its ``url_path`` ("" for Discover)."""
    return page.url_path or ""


def _render_language():
    """Language selector (persisted in session_state["ui_language"]).

    Moved out of the Streamlit sidebar into this shell so that the only
    hamburger on mobile is the application shell's own. Uses an ``on_change``
    callback instead of a manual ``st.rerun()`` so that merely *rendering* the
    drawer never triggers a restart (which would interfere with open/close).
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

    The hamburger (``st.button("☰")``) is always visible at the top of the page
    -- no swipe from the edge is required. Toggling it opens/closes an inline
    navigation drawer listing all canonical pages (Settings always present) and
    navigating via ``st.switch_page(<StreamlitPage object>)``.
    """
    # LAZY import: webui.nav_pages imports every page module at top level, and
    # every page module imports THIS module at top level -- a top-level import
    # of nav_pages here would create a cycle (page -> nav_shell -> nav_pages ->
    # page). Importing inside the function runs after page import is complete.
    from webui.nav_pages import NAV_PAGES

    st.session_state.setdefault(_SESSION_NAV, False)

    # ── Header: hamburger + current-page title ───────────────────────────────
    btn_col, title_col = st.columns([1, 14], vertical_alignment="center")
    with btn_col:
        if st.button(
            "☰",
            key="nav_hamburger",
            help="Open navigation",
            use_container_width=True,
        ):
            # Toggle open / closed (explicit close via the hamburger too).
            st.session_state[_SESSION_NAV] = not st.session_state.get(_SESSION_NAV, False)
    with title_col:
        active_page = next((p for p in NAV_PAGES if _slug(p) == active), None)
        st.markdown(f"### {active_page.title if active_page else 'VIDEO FACTORY'}")
    st.divider()

    # ── Drawer: inline panel, rendered only while open ───────────────────────
    if st.session_state.get(_SESSION_NAV):
        with st.container(border=True, key="nav_drawer_panel"):
            st.markdown("### VIDEO FACTORY")
            st.caption("Application navigation")
            st.divider()

            # Single source of truth: NAV_PAGES (webui/nav_pages.py)
            for page in NAV_PAGES:
                slug = _slug(page)
                icon = page.icon or "•"
                label = f"{icon} {page.title}"
                is_active = slug == active
                if st.button(
                    label,
                    key=f"nav_item_{slug or 'discover'}",
                    type="primary" if is_active else "secondary",
                    use_container_width=True,
                    disabled=is_active,  # cannot navigate to the current page
                ):
                    st.session_state[_SESSION_NAV] = False
                    st.switch_page(page)  # OBJECT -- registered StreamlitPage

            st.divider()

            # Settings is a first-class, always-visible menu item. It also
            # appears in the NAV_PAGES loop above; this emphasised button is a
            # redundant guarantee that Settings can NEVER be hidden.
            settings_page = next(
                (p for p in NAV_PAGES if _slug(p) == "render_settings"), None
            )
            if settings_page:
                if st.button(
                    f"{settings_page.icon or '⚙️'} Settings",
                    key="nav_settings_explicit",
                    use_container_width=True,
                    type="primary" if active == "render_settings" else "secondary",
                    disabled=active == "render_settings",
                ):
                    st.session_state[_SESSION_NAV] = False
                    st.switch_page(settings_page)

            # Explicit close affordance (the hamburger toggle also closes).
            if st.button("✕ Close", key="nav_close", use_container_width=True):
                st.session_state[_SESSION_NAV] = False

            st.divider()
            _render_language()
