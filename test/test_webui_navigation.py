"""Phase 15B — canonical navigation + product IA tests.

Proves:
  * webui/nav_pages.py is the single, side-effect-free canonical registry that
    builds exactly the six StreamlitPage objects (Overview default landing +
    Discover / Review / Create / Library / Settings) grouped into the 5 product
    domains, with the right titles/icons/default/url_path.
  * Main.py registers exactly those objects with st.navigation().
  * every st.switch_page() call passes a StreamlitPage object -- NEVER a bare
    file-path string. No invalid string targets remain anywhere in webui/.
  * Explore was retired (consolidated into Discover -- no dead route, no 2nd UI).
  * Overview is the default landing and shows ONLY real, non-faked data.
  * the prefill data contract keys are consistent across producers/consumer.
  * in the real app (AppTest on webui/Main.py) all six pages load without
    exception, the drawer opens/closes/reopens on every page, Settings is always
    reachable, and the Review -> Create prefill flow delivers topic/script-prompt/
    keywords into the Create form widgets (and consumes the prefill keys).
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

# Canonical page set after Phase 15B IA (Overview = default landing; Explore retired).
PAGE_TITLES = ["Overview", "Discover", "Review", "Create", "Library", "Settings"]
PAGE_ICONS = ["🏠", "🔍", "📋", "🎬", "📚", "⚙️"]
PAGE_UNDERLYINGS = [
    "render_overview", "render_discover", "render_review",
    "render_create", "render_library", "render_settings",
]

# Canonical product domains (webui.nav_pages.NAV_DOMAINS).
NAV_DOMAINS_EXPECTED = [
    ("OVERVIEW", ["Overview"]),
    ("DISCOVERY", ["Discover", "Review"]),
    ("PRODUCTION", ["Create"]),
    ("LIBRARY", ["Library"]),
    ("SYSTEM", ["Settings"]),
]

PAGE_MODULES = ["overview", "discover", "review", "create", "library", "settings"]


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
        r'st\.switch_page\(\s*["\'](?:review|create|discover|explore|library|settings|overview)["\']',
    ]
    offenders = []
    for p in sorted(WEBUI.rglob("*.py")):
        text = _read(p)
        for i, line in enumerate(text.splitlines(), 1):
            if "switch_page" in line and any(re.search(pat, line) for pat in bad_patterns):
                offenders.append(f"{p.relative_to(ROOT)}:{i}: {line.strip()}")
    assert not offenders, "invalid string st.switch_page targets remain:\n" + "\n".join(offenders)


def test_every_switch_page_call_passes_a_page_object():
    """Each st.switch_page() first argument must be a variable (ast.Name) --
    a StreamlitPage object, never a string literal."""
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
    # Main never defines pages itself -- registry is the single source.
    assert "st.Page(render_" not in src


def test_prefill_contract_keys_are_consistent():
    """Producers write canonical keys; create.py's consumer maps the same keys."""
    for name in ("discover", "review"):
        src = _read(WEBUI / "pages" / f"{name}.py")
        assert '"prefill_video_subject"' in src, f"{name} must set prefill_video_subject"
        assert '"prefill_video_script_prompt"' in src, f"{name} must set prefill_video_script_prompt"
        assert '"prefill_video_keywords"' in src, f"{name} must set prefill_video_keywords"
    for name in ("discover", "review", "create"):
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


def test_explore_retired_no_second_ui():
    """Explore was consolidated into Discover -- no dead route / no 2nd UI."""
    registry = _read(WEBUI / "nav_pages.py")
    assert "explore_page" not in registry, "explore_page must be retired from the registry"
    assert "render_explore" not in registry, "retired Explore must not remain in registry"
    assert not (WEBUI / "pages" / "explore.py").exists(), "retired explore.py must be removed"
    page_files = {p.name for p in sorted((WEBUI / "pages").glob("*.py"))}
    assert "explore.py" not in page_files
    # Exactly one Main.py entrypoint.
    mains = [p for p in sorted(WEBUI.rglob("Main.py"))]
    assert len(mains) == 1, f"expected exactly one WebUI entrypoint, got {mains}"


def test_no_fake_metrics_on_overview():
    """Overview must never show fabricated revenue/engagement/traffic figures."""
    src = _read(WEBUI / "pages" / "overview.py")
    # These product-metric words must not appear as displayed values.
    for banned in ("Revenue", "Engagement", "Views", "$24", "M Views", "+300%"):
        assert banned not in src, f"Overview must not fake metric: {banned!r}"


# ---------------------------------------------------------------------------
# Runtime tests (AppTest provides the Streamlit script run context)
# ---------------------------------------------------------------------------

def test_canonical_registry_builds_six_pages_and_five_domains():
    """nav_pages.py builds 6 StreamlitPage objects + 5 domains with exact IA."""
    script = (
        "import sys, json\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from webui.nav_pages import NAV_PAGES, NAV_DOMAINS\n"
        "import streamlit as st\n"
        "info = [dict(title=p.title, icon=p.icon, default=p._default,\n"
        "               url_path=p.url_path, underlying=p._url_path) for p in NAV_PAGES]\n"
        "domains = [(label, [p.title for p in pages]) for label, pages in NAV_DOMAINS]\n"
        "st.markdown('NAVINFO_START' + json.dumps(info, ensure_ascii=False) + 'NAVINFO_END')\n"
        "st.markdown('DOMINFO_START' + json.dumps(domains, ensure_ascii=False) + 'DOMINFO_END')\n"
    )
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        script_file = Path(tmp) / "nav_check.py"
        script_file.write_text(script, encoding="utf-8")
        at = AppTest.from_file(str(script_file), default_timeout=120)
        at.run()
    assert not at.exception, at.exception
    md = "".join(m.value for m in at.markdown)
    mi = re.search(r"NAVINFO_START(.*?)NAVINFO_END", md, re.S)
    di = re.search(r"DOMINFO_START(.*?)DOMINFO_END", md, re.S)
    assert mi and di, "registry did not emit page/domain info"
    info = json.loads(mi.group(1))
    domains = json.loads(di.group(1))
    assert len(info) == 6
    assert [d["title"] for d in info] == PAGE_TITLES
    assert [d["icon"] for d in info] == PAGE_ICONS
    assert [d["default"] for d in info] == [True, False, False, False, False, False]
    assert [d["underlying"] for d in info] == PAGE_UNDERLYINGS
    assert domains == [[l, ps] for l, ps in NAV_DOMAINS_EXPECTED], domains


PAGE_HASHES = [
    ("Overview", None, "Create Video"),
    ("Discover", "render_discover", "Fetch Live Trends"),
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
        assert any(expect_button in lbl for lbl in labels), f"{label} expected button {expect_button!r}, got {labels}"


def test_overview_is_default_landing():
    """goldtrader.website (/) must land on Overview, not Discover."""
    at = _load_main()
    at.run()  # no page_hash -> default page
    assert not at.exception, at.exception
    md = [m.value for m in at.markdown if m.value]
    assert any("### Overview" in v for v in md), "root '/' did not land on Overview"
    # Real-data dashboard sections (never fake).
    assert any("Production pipeline" in v for v in md)
    assert any("Recent activity" in v for v in md)
    assert any("Quick actions" in v for v in md)
    # Real st.metric labels (Active / Completed / Attention / Storage).
    metric_labels = [getattr(m, "label", "") for m in at.metric]
    assert "Active" in metric_labels and "Completed" in metric_labels, metric_labels
    assert "Storage" in metric_labels, metric_labels


def test_overview_pipeline_is_responsive_no_compressed_columns():
    """Phase 15F: the production-pipeline stage labels must NEVER fragment on
    narrow screens. The old 6-column `st.columns()` row squeezed each stage label
    into a ~30-50px column on 320px and shattered words ("COMPOSI/TION",
    "CO/MP/LE/TE"). It is replaced by a scrollable stepper (.mpt-pipeline) with
    white-space:nowrap per step so the row scrolls instead of the words breaking."""
    src = _read(WEBUI / "pages" / "overview.py")
    css = _read(WEBUI / "styles.css")
    # (1) the broken compressed layout is gone.
    assert "st.columns(len(_PIPELINE_STAGES))" not in src, \
        "Overview still renders the pipeline as 6 squeezed columns"
    # (2) the deliberate responsive stepper is in place.
    assert "mpt-pipeline" in src, "Overview pipeline step missing (.mpt-pipeline)"
    assert ".mpt-pipeline-step" in css, ".mpt-pipeline-step CSS rule missing"
    assert "white-space: nowrap" in css, "pipeline steps must use white-space:nowrap"
    # (3) at runtime the real step labels are still rendered (no data loss).
    at = _load_main()
    at.run()
    assert not at.exception, at.exception
    md = "".join(m.value for m in at.markdown if m.value)
    for stage in ("IDEA", "SCRIPT", "MATERIALS", "AUDIO", "COMPOSITION", "COMPLETE"):
        assert stage in md, f"pipeline stage {stage!r} missing from rendered Overview"


def test_overview_quick_actions_responsive_no_compressed_columns():
    """Phase 15G Class R1: Overview Quick Actions must never compress button
    labels on mobile. The old `st.columns(3)` starved each button to ~90px and
    shattered 'Open Library' -> 'Open/Librar/y'. Replaced by a .mpt-action-row
    flex-wrap row (min 160px per button) so the row wraps instead of words
    breaking. This guardrail forbids the dangerous pattern from returning."""
    src = _read(WEBUI / "pages" / "overview.py")
    css = _read(WEBUI / "styles.css")
    # (1) no st.columns() call remains in Overview (AST check -- ignores comments)
    cols_calls = [n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "columns"
                  and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                  and n.func.value.id == "st"]
    assert not cols_calls, f"Overview must not call st.columns (width-starvation risk): {len(cols_calls)}"
    # (2) the deliberate responsive contract is present
    assert "quick_actions_row" in src, ".mpt-action-row container missing in Overview"
    assert "st-key-quick_actions_row" in css, ".mpt-action-row CSS rule missing"
    assert "flex-wrap: wrap" in css, "action-row must flex-wrap (no squeezing)"
    # runtime: the three labelled actions still render (no data loss / dead buttons)
    at = _load_main()
    at.run()
    assert not at.exception, at.exception
    labels = [b.label for b in at.button]
    for action in ("🔍 Discover Ideas", "🎬 Create Video", "📚 Open Library"):
        assert any(action in lbl for lbl in labels), f"quick action {action!r} missing: {labels}"


def test_library_card_actions_not_width_starved(monkeypatch):
    """Phase 15G Class R2/R3: Library card action buttons must not be squeezed
    into a 2/6 column (~47px at 320px) -- that clipped 'Open folder' ->
    'Downloa/d'. Actions now live in a dedicated .mpt-card-actions full-width
    row below the metadata (PO-accepted mobile contract)."""
    from webui.pages import library as library_mod
    import app.models.const as const
    src = _read(WEBUI / "pages" / "library.py")
    css = _read(WEBUI / "styles.css")
    # (1) the width-starving [3,1,2] action-column layout is gone (AST check --
    # ignores comments; st.columns(3) for the cache *metrics* is allowed).
    bad_card_cols = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "columns" \
           and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) \
           and n.func.value.id == "st" and n.args:
            arg = n.args[0]
            if isinstance(arg, ast.List) and [e.value for e in arg.elts] == [3, 1, 2]:
                bad_card_cols.append("st.columns([3,1,2])")
    assert not bad_card_cols, "Library card still uses width-starving st.columns([3,1,2])"
    # (2) the dedicated card-actions contract is present
    assert "card_actions_" in src, "dedicated card_actions container missing in Library"
    assert "st-key-card_actions" in css, ".mpt-card-actions CSS rule missing"
    # runtime: a Complete task renders full, untruncated action labels
    monkeypatch.setattr(library_mod, "collect_task_summaries", lambda limit=20: [{
        "task_id": "t-9", "subject": "Demo", "state": const.TASK_STATE_COMPLETE,
        "progress": 100, "video_file": "/no/such/v-9.mp4", "mtime": 1700000000.0,
    }])
    at = _load_main()
    at._page_hash = calc_hash("render_library")
    at.run()
    assert not at.exception, at.exception
    labels = [b.label for b in at.button]
    assert any("Open folder" in lbl for lbl in labels), f"'Open folder' label missing/truncated: {labels}"
    assert any("Delete" in lbl for lbl in labels), f"'Delete' label missing: {labels}"


def test_review_back_to_discover_navigates_cleanly():
    """Reproduces the previously-broken flow with the Page-object contract."""
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
    """Data contract: Review -> Create carries topic / script prompt / keywords."""
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
    """Negative repro: a bare-string target raises StreamlitAPIException
    ('Could not find page'). Proves the object-based contract is necessary."""
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
    """Regression guard: settings.py uses datetime (cache stats)."""
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
# Phase 14.7/14.8 + 15B -- Explicit mobile navigation shell (hamburger drawer)
# ---------------------------------------------------------------------------

SHELL_PAGES = [
    ("Overview", "", "Overview"),
    ("Discover", "render_discover", "Discover"),
    ("Review", "render_review", "Review"),
    ("Create", "render_create", "Create"),
    ("Library", "render_library", "Library"),
    ("Settings", "render_settings", "Settings"),
]

# Title-derived nav item keys (nav_shell._page_id).
SHELL_NAV_KEYS = {
    "Overview": "nav_item_overview",
    "Discover": "nav_item_discover",
    "Review": "nav_item_review",
    "Create": "nav_item_create",
    "Library": "nav_item_library",
    "Settings": "nav_item_settings",
}


def _nav_open(at: AppTest) -> bool:
    """Reliable open/closed indicator for the drawer (session_state toggle)."""
    try:
        return bool(at.session_state["mpt_nav_drawer_open"])
    except Exception:
        return False


def _nav_item_keys(at: AppTest) -> list:
    return [b.key for b in at.button if b.key and b.key.startswith("nav_item_")]


def test_nav_shell_renders_hamburger_on_all_six_pages():
    """Requirement: a visible hamburger control exists on every primary page."""
    for label, slug, _ in SHELL_PAGES:
        at = _load_main()
        if slug:
            at._page_hash = calc_hash(slug)
        at.run()
        assert not at.exception, f"{label} shell raised: {at.exception}"
        keys = [b.key for b in at.button if b.key]
        assert "nav_hamburger" in keys, f"{label}: hamburger (nav_hamburger) missing"


def test_hamburger_opens_drawer_with_all_pages_and_settings():
    """Requirement: hamburger opens the drawer; all 6 pages + Settings present."""
    at = _load_main()  # Overview (default)
    at.run()
    assert not _nav_open(at)  # closed by default
    at.button(key="nav_hamburger").click().run()  # open
    assert _nav_open(at) is True
    items = _nav_item_keys(at)
    assert items == [
        SHELL_NAV_KEYS["Overview"],
        SHELL_NAV_KEYS["Discover"],
        SHELL_NAV_KEYS["Review"],
        SHELL_NAV_KEYS["Create"],
        SHELL_NAV_KEYS["Library"],
        SHELL_NAV_KEYS["Settings"],
    ], items
    assert SHELL_NAV_KEYS["Settings"] in items, "Settings missing from explicit nav"


@pytest.mark.parametrize("close_via", ["nav_close", "nav_hamburger"])
def test_open_close_reopen_drawer(close_via):
    """Requirement: open -> close -> reopen works (explicit close + toggle)."""
    at = _load_main()
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


# (target_title, nav_key, start_slug) -- open drawer on start_slug, click item
# to reach target, then assert we landed (header renders ### {title}).
SHELL_NAV_CASES = [
    ("Discover", SHELL_NAV_KEYS["Discover"], ""),            # start Overview -> Discover
    ("Review", SHELL_NAV_KEYS["Review"], "render_discover"),
    ("Create", SHELL_NAV_KEYS["Create"], "render_discover"),
    ("Library", SHELL_NAV_KEYS["Library"], "render_discover"),
    ("Settings", SHELL_NAV_KEYS["Settings"], "render_discover"),
    ("Overview", SHELL_NAV_KEYS["Overview"], "render_settings"),
]


@pytest.mark.parametrize("target,nav_key,start_slug", SHELL_NAV_CASES)
def test_drawer_navigates_to_each_target(target, nav_key, start_slug):
    """Requirement: each menu item navigates to the registered StreamlitPage."""
    at = _load_main()
    if start_slug:
        at._page_hash = calc_hash(start_slug)
    at.run()
    assert not at.exception, at.exception
    # open the drawer, confirm Settings is present
    at.button(key="nav_hamburger").click().run()
    assert SHELL_NAV_KEYS["Settings"] in _nav_item_keys(at)
    # navigate
    at.button(key=nav_key).click().run()
    assert not at.exception, f"nav to {target} raised: {at.exception}"
    # The shell header renders the active page title -> proves we landed there.
    md = [m.value for m in at.markdown if m.value]
    assert any(f"### {target}" in v for v in md), f"did not land on {target}"
    # navigation closes the drawer on the destination page
    assert _nav_open(at) is False


def test_settings_reachable_via_drawer():
    """Requirement: Settings MUST be explicitly visible & reachable from drawer."""
    at = _load_main()
    at._page_hash = calc_hash("render_discover")
    at.run()
    at.button(key="nav_hamburger").click().run()
    at.button(key=SHELL_NAV_KEYS["Settings"]).click().run()
    assert not at.exception, at.exception
    md = [m.value for m in at.markdown if m.value]
    assert any("### Settings" in v for v in md), "Settings menu item did not navigate"


def test_nav_shell_is_single_source_of_truth():
    """Requirement: NAV_DOMAINS/NAV_PAGES is the one source for items/targets/active."""
    shell = _read(WEBUI / "nav_shell.py")
    assert "from webui.nav_pages import NAV_PAGES" in shell
    assert "NAV_DOMAINS" in shell
    # settings is a loop item (always visible) -- not a redundant duplicate
    assert "nav_settings_explicit" not in shell
    # every page module wires in the shell
    for name in PAGE_MODULES:
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
    """Library status tab 'Completed' (not 'Complete'); duplicate-key safe."""
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


def test_create_is_production_workspace():
    """Create is framed as a Production workspace (progressive disclosure + launch)."""
    at = _load_main()
    at._page_hash = calc_hash("render_create")
    at.run()
    assert not at.exception, at.exception
    src = _read(MAIN.parent / "pages" / "create.py")
    assert "① IDEA" in src and "② Creative Brief" in src
    assert "Production Settings" in src
    # The Launch action is the unambiguous primary call to produce.
    assert "Launch Production" in src
    # Preselected-opportunity context helper exists.
    assert "_render_selected_opportunity_banner" in src
    labels = [getattr(b, "label", "") for b in at.button]
    assert any("Launch Production" in lbl for lbl in labels), f"Launch button missing: {labels}"
