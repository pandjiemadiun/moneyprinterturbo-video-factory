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
# Page objects are defined exactly once in the canonical registry
# (webui/nav_pages.py) and reused both here and inside each page module for
# programmatic navigation via st.switch_page(<StreamlitPage object>).
# DO NOT pass bare strings to st.switch_page() for callable-registered pages:
# Streamlit resolves a string as a file path and raises StreamlitAPIException.
from webui.nav_pages import NAV_PAGES

pg = st.navigation(
    NAV_PAGES,
    position="sidebar",
)

pg.run()
