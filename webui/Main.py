"""
MoneyPrinterTurbo — canonical WebUI entry point.

Uses Streamlit's st.navigation + st.Page for clean multipage architecture.
Each page lives in webui/pages/ and imports shared utilities from webui/shared.py.
"""

import os
import sys

# Ensure project root is first in sys.path so our app package takes priority
# over any third-party packages that might shadow it.
root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if root_dir in sys.path:
    sys.path.remove(root_dir)
sys.path.insert(0, root_dir)

import streamlit as st
from pathlib import Path

from app.config import config

# ── Page config (must be first Streamlit call) ──────────────────────────────
st.set_page_config(
    page_title="MoneyPrinterTurbo",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="auto",
    menu_items={
        "Report a bug": "https://github.com/harry0703/MoneyPrinterTurbo/issues",
        "About": "# MoneyPrinterTurbo\nSimply provide a topic or keyword for a video, and it will "
        "automatically generate the video copy, video materials, video subtitles, "
        "and video background music before synthesizing a high-definition short "
        "video.\n\nhttps://github.com/harry0703/MoneyPrinterTurbo",
    },
)

# ── Global styles ───────────────────────────────────────────────────────────
style_file = Path(__file__).with_name("styles.css")
streamlit_style = f"<style>{style_file.read_text(encoding='utf-8')}</style>"
st.markdown(streamlit_style, unsafe_allow_html=True)

# ── Shared initialization (session state, locales, helpers) ────────────────
from webui.shared import initialize_session_state, tr, locales

initialize_session_state()

# ── Language selector (persisted across pages) ──────────────────────────────
language_codes = list(locales.keys())
current_language = st.session_state.get("ui_language", "")
if current_language not in language_codes:
    current_language = language_codes[0] if language_codes else "en"

selected_language = st.sidebar.selectbox(
    "Language / 语言",
    options=language_codes,
    index=language_codes.index(current_language) if current_language in language_codes else 0,
    format_func=lambda code: code.split("-")[0].upper(),
    key="global_language_selector",
)
if selected_language != st.session_state.get("ui_language", ""):
    st.session_state["ui_language"] = selected_language
    st.rerun()

# ── Navigation ──────────────────────────────────────────────────────────────
from webui.pages.discover import render_discover
from webui.pages.explore import render_explore
from webui.pages.create import render_create
from webui.pages.library import render_library
from webui.pages.settings import render_settings

pg = st.navigation(
    [
        st.Page(render_discover, title="Discover", icon="🏠", default=True),
        st.Page(render_explore, title="Explore", icon="🔎"),
        st.Page(render_create, title="Create", icon="🎬"),
        st.Page(render_library, title="Library", icon="🎞️"),
        st.Page(render_settings, title="Settings", icon="⚙️"),
    ],
    position="sidebar",
)

pg.run()
