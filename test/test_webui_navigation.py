"""Phase 14.6 — deterministic navigation-contract tests.

These tests prove:
  * webui/nav_pages.py is the single, side-effect-free canonical registry that
    builds exactly the six StreamlitPage objects with the right titles/icons/
    default/url_path.
  * Main.py registers exactly those objects with st.navigation().
  * every st.switch_page() call passes a StreamlitPage object (an ast.Name bound
    to a nav_pages object) -- NEVER a bare file-path string. No invalid string
    targets remain anywhere in the canonical webui.
  * the prefill data contract keys are consistent across producers and consumer.
  * in the real app (AppTest on webui/Main.py) all six pages load without
    exception, Review -> "Back to Discover" navigates (no exception), and the
    Review -> Create prefill flow delivers topic/script-prompt/keywords into the
    Create form widgets (and consumes the prefill keys).
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WEBUI = ROOT / "webui"
MAIN = WEBUI / "Main.py"


def _load_main(default_timeout: float = 120) -> AppTest:
    return AppTest.from_file(str(MAIN), default_timeout=default_timeout)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Static / structural tests (no Streamlit runtime needed)
# ---------------------------------------------------------------------------

def test_nav_pages_registry_module_exists():
    assert (WEBUI / "nav_pages.py").is_file(), "canonical registry webui/nav_pages.py missing"


def test_no_invalid_string_switch_page_targets_remain():
    """No st.switch_page() may pass a bare page-name string (file-path form)."""
    bad_patterns = [
        r'st\.switch_page\(\s*["\'](?:render_[a-z]+)["\']',
        r'st\.switch_page\(\s*["\'](?:review|create|discover|explore|library|settings)["\']',
    ]
    offenders = []
    for p in sorted(WEBUI.rglob("*.py")):
        text = _read(p)
        for i, line in enumerate(text.splitlines(), 1):
            if "switch_page" in line and any(re.search(pat, line) for pat in bad_patterns):
                offenders.append(f"{p.relative_to(ROOT)}:{i}: {line.strip()}")
    assert not offenders, "invalid string st.switch_page targets remain:\n" + "\n".join(offenders)


def test_every_switch_page_call_passes_a_page_object():
    """Each st.switch_page() call's first argument must be a variable (ast.Name),
    i.e. a StreamlitPage object -- never a string literal."""
    for p in sorted(WEBUI.rglob("*.py")):
        if p.name == "nav_pages.py":
            continue
        tree = ast.parse(_read(p))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "switch_page":
                assert node.args, f"{p.relative_to(ROOT)}:{node.lineno}: switch_page() called with no arguments"
                arg0 = node.args[0]
                assert isinstance(arg0, ast.Name), (
                    f"{p.relative_to(ROOT)}:{node.lineno}: switch_page must receive a "
                    f"StreamlitPage variable, got {type(arg0).__name__}"
                )


def test_main_uses_canonical_registry():
    src = _read(MAIN)
    assert "from webui.nav_pages import NAV_PAGES" in src
    assert "st.navigation(" in src and "NAV_PAGES" in src
    assert "st.Page(render_discover" not in src
    assert "st.Page(render_review" not in src


def test_prefill_contract_keys_are_consistent():
    """Producers write canonical keys; create.py's consumer maps the same keys."""
    for name in ("discover", "explore", "review"):
        src = _read(WEBUI / "pages" / f"{name}.py")
        assert '"prefill_video_subject"' in src, f"{name} must set prefill_video_subject"
        assert '"prefill_video_script_prompt"' in src, f"{name} must set prefill_video_script_prompt"
        assert '"prefill_video_keywords"' in src, f"{name} must set prefill_video_keywords"
    for name in ("discover", "explore", "review", "create"):
        assert "prefill_script_prompt" not in _read(WEBUI / "pages" / f"{name}.py"), name
    create_src = _read(WEBUI / "pages" / "create.py")
    assert '"prefill_video_subject": "video_subject"' in create_src
    assert '"prefill_video_script_prompt": "video_script_prompt"' in create_src
    assert '"prefill_video_keywords": "video_terms"' in create_src


def test_no_duplicate_credential_signature_in_shared():
    assert _read(WEBUI / "shared.py").count("def _credential_signature") == 1


def test_no_dead_review_dialog_state_keys():
    for name in ("discover", "review"):
        src = _read(WEBUI / "pages" / f"{name}.py")
        assert "discover_show_review" not in src
        assert "discover_review_item" not in src


# ---------------------------------------------------------------------------
# Runtime tests (AppTest provides the Streamlit script run context)
# ---------------------------------------------------------------------------

def test_canonical_registry_builds_six_page_objects(tmp_path):
    """nav_pages.py builds exactly six StreamlitPage objects with the right
    titles/icons/default/url_path when imported inside a Streamlit context."""
    script = (
        "import sys, json\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from webui.nav_pages import NAV_PAGES\n"
        "import streamlit as st\n"
        "info = [dict(title=p.title, icon=p.icon, default=p._default,\n"
        "               url_path=p.url_path, underlying=p._url_path) for p in NAV_PAGES]\n"
        "st.markdown('NAVINFO_START' + json.dumps(info, ensure_ascii=False) + 'NAVINFO_END')\n"
    )
    script_file = tmp_path / "nav_check.py"
    script_file.write_text(script, encoding="utf-8")
    at = AppTest.from_file(str(script_file), default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    md = "".join(m.value for m in at.markdown)
    m = re.search(r"NAVINFO_START(.*?)NAVINFO_END", md, re.S)
    assert m, "registry did not emit page info"
    info = json.loads(m.group(1))
    assert len(info) == 6
    assert [d["title"] for d in info] == ["Discover", "Explore", "Review", "Create", "Library", "Settings"]
    assert [d["icon"] for d in info] == ["🏠", "🔎", "🔍", "🎬", "🎞️", "⚙️"]
    assert [d["default"] for d in info] == [True, False, False, False, False, False]
    assert [d["underlying"] for d in info] == [
        "render_discover", "render_explore", "render_review",
        "render_create", "render_library", "render_settings",
    ]


PAGE_HASHES = [
    ("Discover", None, "Fetch Live Trends"),
    ("Explore", "render_explore", None),
    ("Review", "render_review", "Back to Discover"),
    ("Create", "render_create", None),
    ("Library", "render_library", "Discover Ideas"),
    ("Settings", "render_settings", None),
]


@pytest.mark.parametrize("label,page_hash,expect_button", PAGE_HASHES)
def test_all_six_pages_load_without_exception(label, page_hash, expect_button):
    at = _load_main()
    if page_hash:
        at._page_hash = calc_hash(page_hash)
    at.run()
    assert not at.exception, f"{label} raised: {at.exception}"
    if expect_button:
        labels = [getattr(b, "label", "") for b in at.button]
        assert expect_button in labels, f"{label} expected button {expect_button!r}, got {labels}"


def test_review_back_to_discover_navigates_cleanly():
    """Reproduces the exact previously-broken flow: Review 'Back to Discover'
    used st.switch_page('render_discover') -> StreamlitAPIException. With the
    Page-object contract it must navigate without exception."""
    at = _load_main()
    at._page_hash = calc_hash("render_review")
    at.run()
    assert not at.exception, at.exception
    back = [b for b in at.button if getattr(b, "label", "") == "Back to Discover"]
    assert len(back) == 1, "Review empty-state 'Back to Discover' button missing"
    back[0].click()
    at.run()
    assert not at.exception, f"Review->Discover raised: {at.exception}"
    labels = [getattr(b, "label", "") for b in at.button]
    assert "Fetch Live Trends" in labels, f"did not land on Discover: {labels}"


def test_prefill_flows_from_review_to_create():
    """Data contract: Review -> Create carries topic / script prompt / keywords
    into the Create form widgets and consumes the prefill keys."""
    item = {
        "topic": "Quantum Espresso",
        "proposed_hook": "Hook here",
        "angle": "Angle here",
        "content_promise": "Promise here",
        "format": "Short",
        "keywords": ["quantum", "espresso", "physics"],
    }
    at = _load_main()
    at.session_state["review_item"] = item
    at._page_hash = calc_hash("render_review")
    at.run()
    assert not at.exception, at.exception
    create_btns = [b for b in at.button if getattr(b, "label", "") == "Create Video"]
    assert len(create_btns) == 1, "Review 'Create Video' button missing"
    create_btns[0].click()
    at.run()
    assert not at.exception, f"Review->Create raised: {at.exception}"
    assert at.text_area(key="video_subject").value == "Quantum Espresso"
    assert "quantum" in (at.text_area(key="video_terms").value or "")
    assert at.text_area(key="video_script_prompt").value.startswith("Topic: Quantum Espresso")
    ps = dict(at.session_state.filtered_state) if hasattr(at.session_state, "filtered_state") else {}
    assert ps.get("prefill_video_subject", "") == "" or "prefill_video_subject" not in ps
    assert ps.get("prefill_video_script_prompt", "") == "" or "prefill_video_script_prompt" not in ps


def test_string_switch_page_target_raises(tmp_path):
    """Negative repro of the root cause: a bare string target raises
    StreamlitAPIException ('Could not find page') because Streamlit resolves a
    string as a file path -- it cannot match a callable-registered page.
    (The positive object-based proof is test_review_back_to_discover_navigates_cleanly.)"""
    script = (
        "import streamlit as st\n"
        "st.set_page_config(page_title='neg')\n"
        "if st.button('go', key='go'):\n"
        "    st.switch_page('render_discover')\n"
    )
    f = tmp_path / "neg_app.py"
    f.write_text(script, encoding="utf-8")
    at = AppTest.from_file(str(f), default_timeout=60)
    at.run()
    go = [b for b in at.button if getattr(b, "label", "") == "go"]
    assert go, "neg_app 'go' button missing"
    go[0].click()
    at.run()
    assert at.exception, "expected StreamlitAPIException for string switch_page target"
    assert "Could not find page" in str(at.exception[0])


def test_settings_imports_datetime():
    """Regression guard: settings.py used ``datetime`` in
    _render_cache_settings without importing it, producing
    ``NameError: name 'datetime' is not defined`` at runtime whenever the video
    cache holds data (production). Static guard (the dynamic counterpart is the
    production Playwright check that GET /render_settings renders cleanly)."""
    tree = ast.parse(_read(WEBUI / "pages" / "settings.py"))
    has_import = False
    for node in tree.body:
        if isinstance(node, ast.Import) and any(a.name == "datetime" for a in node.names):
            has_import = True
        if isinstance(node, ast.ImportFrom) and node.module == "datetime" and any(
            a.name == "datetime" for a in node.names
        ):
            has_import = True
    assert has_import, "settings.py must import datetime (used by _render_cache_settings)"


# ---------------------------------------------------------------------------
# Phase 14.7 — Product Shell deterministic tests
# ---------------------------------------------------------------------------

def test_settings_has_six_category_tabs():
    """Settings page exposes the 6 canonical category tabs (no 100-field form)."""
    at = _load_main()
    at._page_hash = calc_hash("render_settings")
    at.run()
    assert not at.exception, at.exception
    assert len(at.tabs) == 6, f"expected 6 Settings tabs, got {len(at.tabs)}"
    labels = [t.label for t in at.tabs]
    assert labels == [
        "🎬 Video", "🤖 AI & Script", "🎙 Voice & Audio",
        "🎞 Footage Providers", "🧠 Discovery", "🛠 System",
    ], labels


def test_settings_has_diagnostics_subsection():
    """🛠 System includes a Diagnostics subsection (Application version shown)."""
    at = _load_main()
    at._page_hash = calc_hash("render_settings")
    at.run()
    assert not at.exception, at.exception
    captions = [c.value for c in at.caption if getattr(c, "value", None)]
    assert any("Application version" in v for v in captions), \
        "Settings System tab has no Diagnostics subsection (Application version)"


def test_discover_shows_recommended_opportunities_without_network():
    """First-load Discover shows curated recommended opportunities (no external API)."""
    at = _load_main()
    at._page_hash = calc_hash("render_discover")
    at.run()
    assert not at.exception, at.exception
    md = [m.value for m in at.markdown if m.value]
    assert any("Quantum Espresso Machines" in v for v in md), "Discover did not render a recommended opportunity"
    labels = [getattr(b, "label", "") for b in at.button]
    assert "Fetch Live Trends" in labels, "Discover must keep Fetch Live Trends as an explicit action"


# ---------------------------------------------------------------------------
# Phase 14.8 — Explicit mobile navigation shell (hamburger drawer)
# ---------------------------------------------------------------------------

# Canonical page ordering + slugs from webui/nav_pages.py (single source).
SHELL_PAGES = [
    ("Discover", ""),
    ("Explore", "render_explore"),
    ("Review", "render_review"),
    ("Create", "render_create"),
    ("Library", "render_library"),
    ("Settings", "render_settings"),
]


def _nav_open(at: AppTest) -> bool:
    """Reliable open/closed indicator for the drawer (session_state toggle).

    NOTE: we cannot use presence of ``nav_item_*`` buttons to detect closed
    state in AppTest because a button that flips the flag mid-run is still
    emitted by that same run -- so we read the toggle flag directly."""
    try:
        return bool(at.session_state["mpt_nav_drawer_open"])
    except Exception:
        return False


def _nav_item_keys(at: AppTest) -> list:
    return [b.key for b in at.button if b.key and b.key.startswith("nav_item_")]


def test_nav_shell_renders_hamburger_on_all_six_pages():
    """Requirement: a visible hamburger control exists on every primary page."""
    for label, slug in SHELL_PAGES:
        at = _load_main()
        if slug:
            at._page_hash = calc_hash(slug)
        at.run()
        assert not at.exception, f"{label} shell raised: {at.exception}"
        keys = [b.key for b in at.button if b.key]
        assert "nav_hamburger" in keys, f"{label}: hamburger (nav_hamburger) missing"


def test_hamburger_opens_drawer_with_all_six_items_and_settings():
    """Requirement: hamburger opens the navigation drawer; all 6 pages + a
    redundant explicit Settings item are present (Settings never hidden)."""
    at = _load_main()
    at._page_hash = calc_hash("render_discover")
    at.run()
    assert not _nav_open(at)  # closed by default
    at.button(key="nav_hamburger").click().run()  # open
    assert _nav_open(at) is True
    items = _nav_item_keys(at)
    assert items == [
        "nav_item_discover",
        "nav_item_render_explore",
        "nav_item_render_review",
        "nav_item_render_create",
        "nav_item_render_library",
        "nav_item_render_settings",
    ], items
    assert "nav_item_render_settings" in items, "Settings missing from explicit nav"
    # Settings is explicitly visible as a menu item (the ⚙️ Settings entry in the
    # NAV_PAGES loop) -- it can never be hidden.


@pytest.mark.parametrize("close_via", ["nav_close", "nav_hamburger"])
def test_open_close_reopen_drawer(close_via):
    """Requirement: open -> close -> reopen works (explicit close + toggle)."""
    at = _load_main()
    at._page_hash = calc_hash("render_discover")
    at.run()
    # open
    at.button(key="nav_hamburger").click().run()
    assert _nav_open(at) is True
    assert len(_nav_item_keys(at)) == 6
    # close (explicit ✕ or hamburger toggle)
    at.button(key=close_via).click().run()
    assert _nav_open(at) is False
    # reopen
    at.button(key="nav_hamburger").click().run()
    assert _nav_open(at) is True
    assert len(_nav_item_keys(at)) == 6


# (target_title, nav_item_key, start_slug) -- open drawer on start_slug, then
# click the nav item to reach target_title. Each case is a SINGLE nav step
# (AppTest re-runs the destination page after a button-click switch_page).
SHELL_NAV_CASES = [
    ("Explore", "nav_item_render_explore", "render_discover"),
    ("Review", "nav_item_render_review", "render_discover"),
    ("Create", "nav_item_render_create", "render_discover"),
    ("Library", "nav_item_render_library", "render_discover"),
    ("Settings", "nav_item_render_settings", "render_discover"),
    ("Discover", "nav_item_discover", "render_settings"),
]


@pytest.mark.parametrize("target,nav_key,start_slug", SHELL_NAV_CASES)
def test_drawer_navigates_to_each_target(target, nav_key, start_slug):
    """Requirement: each menu item navigates to the registered StreamlitPage."""
    at = _load_main()
    if start_slug != "render_discover":
        at._page_hash = calc_hash(start_slug)
    at.run()
    assert not at.exception, at.exception
    # open the drawer, confirm it rendered the items (incl. Settings)
    at.button(key="nav_hamburger").click().run()
    assert "nav_item_render_settings" in _nav_item_keys(at)
    # navigate
    at.button(key=nav_key).click().run()
    assert not at.exception, f"nav to {target} raised: {at.exception}"
    # The shell header renders the active page title -> proves we landed there.
    md = [m.value for m in at.markdown if m.value]
    assert any(f"### {target}" in v for v in md), f"did not land on {target}"
    # navigation closes the drawer on the destination page
    assert _nav_open(at) is False


def test_settings_reachable_via_drawer():
    """Requirement: Settings MUST be explicitly visible & reachable from the
    drawer (the ⚙️ Settings menu item in the NAV_PAGES loop)."""
    at = _load_main()
    at._page_hash = calc_hash("render_discover")
    at.run()
    at.button(key="nav_hamburger").click().run()
    at.button(key="nav_item_render_settings").click().run()
    assert not at.exception, at.exception
    md = [m.value for m in at.markdown if m.value]
    assert any("### Settings" in v for v in md), "Settings menu item did not navigate"


def test_nav_shell_is_single_source_of_truth():
    """Requirement: NAV_PAGES is the one source for labels/icons/targets/active."""
    shell = _read(WEBUI / "nav_shell.py")
    # pulls items exclusively from the canonical registry
    assert "from webui.nav_pages import NAV_PAGES" in shell
    assert "for page in NAV_PAGES:" in shell
    # Settings is a loop item (always visible) -- not a redundant duplicate
    assert "nav_settings_explicit" not in shell
    # every page module wires in the shell
    for name in ("discover", "explore", "review", "create", "library", "settings"):
        src = _read(WEBUI / "pages" / f"{name}.py")
        assert "from webui.nav_shell import render_nav_shell" in src, f"{name} does not import the shell"
        assert "render_nav_shell(" in src, f"{name} does not call the shell"


def test_no_invalid_string_switch_page_targets_in_nav_shell():
    """Requirement: no string-based st.switch_page() calls (incl. nav_shell)."""
    bad = re.search(r'st\.switch_page\(\s*["\']', _read(WEBUI / "nav_shell.py"))
    assert not bad, "nav_shell.py must not call st.switch_page with a string"



def test_review_renders_production_gate_and_create():
    """Review decision screen shows the production gate + Create Video primary action."""
    item = {
        "topic": "Quantum Espresso",
        "proposed_hook": "Hook here",
        "content_promise": "Promise here",
        "format": "Explainer",
        "keywords": ["quantum", "espresso"],
        "providers": ["Pexels"],
        "visual_feasibility": "High",
    }
    at = _load_main()
    at.session_state["review_item"] = item
    at._page_hash = calc_hash("render_review")
    at.run()
    assert not at.exception, at.exception
    md = [m.value for m in at.markdown if m.value]
    assert any("Production Gate" in v for v in md), "Review missing Production Readiness gate"
    assert any("Producible" in v for v in md), "Review missing producibility verdict"
    labels = [getattr(b, "label", "") for b in at.button]
    assert "Create Video" in labels and "Back to Discover" in labels


def test_library_tab_completed_label(monkeypatch):
    """Library status tab 'Completed' (not 'Complete'); rendering a task that
    appears in BOTH the 'All' tab and its status tab must NOT raise
    StreamlitDuplicateElementKey (regression guard for status-scoped keys)."""
    from webui.pages import library as library_mod
    import app.models.const as const
    monkeypatch.setattr(library_mod, "collect_task_summaries", lambda limit=20: [{
        "task_id": "t-1", "subject": "Demo Video", "state": const.TASK_STATE_COMPLETE,
        "progress": 100, "video_file": "/no/such/final-1.mp4", "video_source": "pexels",
        "mtime": 1700000000.0, "failed_stage": None,
    }])
    at = _load_main()
    at._page_hash = calc_hash("render_library")
    at.run()
    assert not at.exception, at.exception  # duplicate-key crash would surface here
    labels = [t.label for t in at.tabs]
    assert "Completed" in labels, labels
    assert "Complete" not in labels, f"'Complete' label still present: {labels}"


def test_create_step_labels_are_content_visuals_voice_style():
    """Create guided flow uses the spec step labels: Content/Visuals/Voice/Style."""
    src = _read(MAIN.parent / "pages" / "create.py")
    assert "1. Content" in src
    assert "3. Visuals" in src
    assert "4. Voice" in src
    assert "5. Style" in src
    assert "Generate Video" in src  # Produce primary action preserved
