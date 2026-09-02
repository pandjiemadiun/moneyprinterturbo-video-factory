"""
Canonical multipage registry for the MoneyPrinterTurbo WebUI.

This module is the SINGLE source of truth for the StreamlitPage objects used by
the app AND for the canonical product information architecture:

  * ``webui/Main.py`` registers them with ``st.navigation()``.
  * every page module reuses the SAME objects when calling ``st.switch_page()``.
  * ``webui/nav_shell.py`` groups them into the 5 canonical product domains.

Canonical Product IA (Phase 15B)::

    OVERVIEW        -> goldtrader.website           (/  — default landing)
    DISCOVERY       -> Discover | Review
    PRODUCTION      -> Create
    LIBRARY         -> Library
    SYSTEM          -> Settings

Why Page objects, not strings
-----------------------------
Pages are registered from callables (``render_*``), so a *bare string* passed to
``st.switch_page()`` is resolved as a FILE PATH relative to the main script
directory and matched against each page's ``script_path``. Callable-registered
pages have an empty ``script_path``, so a string like ``"review"`` is interpreted
as the file path ``.../review`` (which does not exist) and raises
``StreamlitAPIException: Could not find page``.

Only a ``StreamlitPage`` object matches a callable-registered page. Pass the
objects defined here.  -> STAYS THE SAME as 14.6 (the proven contract).

Side effects
------------
Importing this module has no Streamlit side effects: it only imports the render
callables and builds the page objects + domain map. Page *registration* happens
in Main.py via ``st.navigation()``.  Page modules import the objects LAZILY
(inside the functions that navigate) to avoid a circular import (this module
imports the page modules, so they cannot import this module at top level).

Canonical public URLs:
    /                -> Overview        (default=True page, served at root)
    /render_discover
    /render_review
    /render_create
    /render_library
    /render_settings

(Explore was retired in Phase 15B: its live-analysis results are consolidated
into a single Discover workspace. Its unique Trends/Patterns views are preserved
as a progressive-disclosure "Raw Intelligence" section inside Discover.)
"""

import os
import sys

# Ensure the project root is importable regardless of the caller's CWD (tests, etc.)
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

import streamlit as st

from webui.pages.overview import render_overview
from webui.pages.discover import render_discover
from webui.pages.review import render_review
from webui.pages.create import render_create
from webui.pages.library import render_library
from webui.pages.settings import render_settings

# ── The six canonical logical pages ─────────────────────────────────────────
# Navigation is by st.Page OBJECTS only (never bare strings) -- see above.
# Overview is the default landing page (default=True). Streamlit serves the
# default page at the root "/" and ignores its url_path for routing; the active
# slug for the shell is "" (see nav_shell._slug). url_path is set explicitly on
# the five non-default pages so the registry is self-documenting and public URLs
# are provable.
overview_page = st.Page(render_overview, title="Overview", icon="🏠", default=True)
discover_page = st.Page(render_discover, title="Discover", icon="🔍", url_path="render_discover")
review_page = st.Page(render_review, title="Review", icon="📋", url_path="render_review")
create_page = st.Page(render_create, title="Create", icon="🎬", url_path="render_create")
library_page = st.Page(render_library, title="Library", icon="📚", url_path="render_library")
settings_page = st.Page(render_settings, title="Settings", icon="⚙️", url_path="render_settings")

# Canonical ordered list consumed by st.navigation().
NAV_PAGES = [
    overview_page,
    discover_page,
    review_page,
    create_page,
    library_page,
    settings_page,
]

# ── Canonical product domains (single source for the nav shell) ─────────────
# Each entry is (domain_label, [page objects]). The nav shell renders a domain
# header followed by the pages in that domain. Settings is always present (never
# hidden behind a gesture) because it lives in the SYSTEM domain list.
NAV_DOMAINS = [
    ("OVERVIEW", [overview_page]),
    ("DISCOVERY", [discover_page, review_page]),
    ("PRODUCTION", [create_page]),
    ("LIBRARY", [library_page]),
    ("SYSTEM", [settings_page]),
]
