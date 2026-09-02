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
    initial_sidebar_state="expanded",
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
from webui.shared import initialize_session_state

initialize_session_state()

# ── Navigation ──────────────────────────────────────────────────────────────
# Page objects are defined exactly once in the canonical registry
# (webui/nav_pages.py) and reused both here and inside each page module for
# programmatic navigation via st.switch_page(<StreamlitPage object>).
# DO NOT pass bare strings to st.switch_page() for callable-registered pages:
# Streamlit resolves a string as a file path and raises StreamlitAPIException.
#
# position="hidden" removes Streamlit's own sidebar page-nav (which hid Settings
# behind a swipe gesture on mobile). The EXPLICIT application navigation shell
# (hamburger drawer) now lives in webui/nav_shell.py, which reuses NAV_PAGES.
# The Language selector also moved there, so the only hamburger is the shell's.
from webui.nav_pages import NAV_PAGES

pg = st.navigation(
    NAV_PAGES,
    position="hidden",
)

pg.run()
