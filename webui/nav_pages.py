"""
Canonical multipage registry for the MoneyPrinterTurbo WebUI.

This module is the SINGLE source of truth for the StreamlitPage objects used by
the app:

  * ``webui/Main.py`` registers them with ``st.navigation()``.
  * every page module reuses the SAME objects when calling ``st.switch_page()``.

Why Page objects, not strings
-----------------------------
Pages are registered from callables (``render_*``), so their ``url_path`` is the
callable name ("render_discover", "render_review", ...). In Streamlit 1.59.1 a
*bare string* passed to ``st.switch_page()`` is resolved as a FILE PATH relative
to the main script directory and is matched against each page's ``script_path``.
Callable-registered pages have an empty ``script_path``, so a string like
``"render_review"`` is interpreted as the file path ``.../render_review`` (which
does not exist) and raises ``StreamlitAPIException: Could not find page``.

Only a ``StreamlitPage`` object matches a callable-registered page. Pass the
objects defined here.

Side effects
------------
Importing this module has no Streamlit side effects: it only imports the render
callables and builds the page objects. Page *registration* happens in Main.py via
``st.navigation()``. Page modules import the objects LAZILY (inside the
functions that navigate) to avoid a circular import (this module imports the
page modules, so they cannot import this module at top level).

Note: building the ``st.Page`` objects requires an active Streamlit script run
context (provided at app runtime and inside AppTest sessions).
"""

import os
import sys

# Ensure the project root is importable regardless of the caller's CWD (tests, etc.)
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

import streamlit as st

from webui.pages.discover import render_discover
from webui.pages.explore import render_explore
from webui.pages.review import render_review
from webui.pages.create import render_create
from webui.pages.library import render_library
from webui.pages.settings import render_settings

# The six canonical logical pages. Each is explicitly assigned the url_path
# "render_<callable-name>" so the canonical /render_* public URLs are stable and
# provable (see docs/PRODUCTION_RUNTIME_CONTRACT.md). In Streamlit 1.59.1 the
# `url_path` of a callable-registered Page defaults to the callable name, EXCEPT
# for the `default=True` page (Discover) whose url_path would otherwise collapse
# to "/" and make /render_discover fall back to "Page not found". Setting it
# explicitly on every page keeps the registry self-documenting and fixes that.
discover_page = st.Page(render_discover, title="Discover", icon="🏠",
                        default=True, url_path="render_discover")
explore_page = st.Page(render_explore, title="Explore", icon="🔎",
                       url_path="render_explore")
review_page = st.Page(render_review, title="Review", icon="🔍",
                      url_path="render_review")
create_page = st.Page(render_create, title="Create", icon="🎬",
                      url_path="render_create")
library_page = st.Page(render_library, title="Library", icon="🎞️",
                       url_path="render_library")
settings_page = st.Page(render_settings, title="Settings", icon="⚙️",
                        url_path="render_settings")

# Canonical ordered list consumed by st.navigation().
NAV_PAGES = [
    discover_page,
    explore_page,
    review_page,
    create_page,
    library_page,
    settings_page,
]
