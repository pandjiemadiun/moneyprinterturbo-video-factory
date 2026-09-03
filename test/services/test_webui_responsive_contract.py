"""Phase 15H structural contract guard (CI-safe, no browser).

Guards the responsive contract that the geometry test enforces at runtime.
These assertions run in any CI (AppTest-style, pure AST + text checks) and fail
fast if anyone:

  * removes the `st.container(key="llm_form_help_row")` wrapper that scopes the
    LLM form CSS, or moves `st.columns([0.9, 1.1])` out from under it;
  * deletes the scoped `@media (max-width: 639px)` override that beats the global
    `stHorizontalBlock :first-of-type` starver (specificity (0,4,2) -> needs
    (0,4,3) scoped selector + `min-width: 280px`);
  * re-introduces the broken legacy rules that the previous (rejected) fix
    shipped with: the `:last-child)::after` syntax error and the
    `:has([data-testid="stInfo"]) { flex-basis:100% }` collapse rule;
  * removes the tab fade `::-after` gradient or the global header starver rule.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SETTINGS = ROOT / "webui" / "pages" / "settings.py"
STYLES = ROOT / "webui" / "styles.css"


def _ast_call(node, attr_path):
    """Match a Call whose func is ``st.<attr_path_last>`` (e.g. st.columns)."""
    f = node.func
    parts = []
    while isinstance(f, ast.Attribute):
        parts.append(f.attr); f = f.value
    if isinstance(f, ast.Name):
        parts.append(f.id)
    parts = list(reversed(parts))
    target = attr_path.split(".")
    return parts == target


def _container_key_match(item):
    """A `with` item whose expr is st.container(key="llm_form_help_row")."""
    # item is ast.withitem; .context_expr may be a Call
    if isinstance(item.context_expr, ast.Call):
        call = item.context_expr
        if _ast_call(call, "streamlit.container") or _ast_call(call, "st.container"):
            for kw in call.keywords:
                if kw.arg == "key" and isinstance(kw.value, ast.Constant) and kw.value.value == "llm_form_help_row":
                    return True
    return False


def _columns_ratio_call(call, ratio):
    """st.columns([a, b]) matching a ratio tuple (order-insensitive)."""
    if not _ast_call(call, "streamlit.columns") and not _ast_call(call, "st.columns"):
        return False
    if not call.args:
        return False
    first = call.args[0]
    if isinstance(first, ast.List) and len(first.elts) == 2:
        vals = [e.value for e in first.elts if isinstance(e, ast.Constant) and isinstance(e.value, (int, float))]
        return sorted(vals) == sorted(ratio)
    return False


def _find_llm_columns_under_wrapper(tree):
    """Return True if a `with st.container(key='llm_form_help_row'):` body
       contains st.columns([0.9, 1.1])."""
    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            for item in node.items:
                if _container_key_match(item):
                    for body_node in ast.walk(node):
                        if isinstance(body_node, ast.Call) and _columns_ratio_call(body_node, [0.9, 1.1]):
                            return True
    return False


def test_settings_llm_form_is_wrapped_in_keyed_container():
    """The st.columns([0.9, 1.1]) LLM form must live inside the keyed wrapper
       so the scoped mobile CSS can override the global column starver."""
    tree = ast.parse(SETTINGS.read_text())
    assert _find_llm_columns_under_wrapper(tree), (
        "settings.py must wrap `st.columns([0.9, 1.1])` inside "
        "`with st.container(key='llm_form_help_row'):` -- the wrapper is the CSS "
        "scoping hook that lets the mobile @media override the global "
        "stHorizontalBlock :first-of-type starver."
    )


def _active_css(css: str) -> str:
    """Strip CSS comments so we assert against active rules, not doc comments."""
    out = []
    i = 0
    while i < len(css):
        if css[i:i+2] == "/*":
            end = css.find("*/", i+2)
            i = end + 2 if end != -1 else len(css)
        else:
            out.append(css[i]); i += 1
    return "".join(out)


def test_styles_css_mobile_llm_override_contract():
    """The mobile @media MUST carry the (0,4,3) scoped selector that beats the
       global header starver (0,4,2), otherwise the columns revert to 66/206."""
    css = _active_css(STYLES.read_text())
    # the scoped override exists
    assert "@media (max-width: 639px)" in css, "mobile LLM stack contract missing"
    assert "st-key-llm_form_help_row" in css
    # anchored to BOTH the keyed ancestor and the .stColumn class -> (0,4,3)
    assert "div[class*=\"st-key-llm_form_help_row\"] [data-testid=\"stHorizontalBlock\"] div[data-testid=\"stColumn\"].stColumn" in css, (
        "LLM override selector must include the keyed ancestor + stHorizontalBlock + "
        ".stColumn to outrank the global (0,4,2) starver."
    )
    assert "min-width: 280px" in css, "mobile LLM columns must have a 280px usability floor"
    assert "flex: 1 1 100%" in css, "mobile LLM columns must be forced to full-line"
    # the broken legacy rules must NOT be present in active CSS
    assert "lastchild)::after" not in css, "re-introduced the tab-fade syntax error (')' vs ']')"
    assert ":has(" not in css, "re-introduced a :has(...) rule (the stInfo collapse rule)"
    assert "@media (max-width: 768px)" in css
    assert "[role=\"tablist\"]::after" in css, "tab fade ::after rule missing"
    assert "linear-gradient" in css, "tab fade must be a gradient, not a flat color"
    assert "scroll-snap-type: x mandatory" in css, "tabs should snap for reachability"


def test_global_header_starver_preserved():
    """The global nav-header column rule must remain intact (header untouched by
       the LLM-scoped fix). If removed, the header hamburger collapses."""
    css = STYLES.read_text()
    assert 'div[data-testid="stHorizontalBlock"]:first-of-type div[data-testid="stColumn"]:first-child' in css
    assert 'flex: 0 0 auto !important' in css
    assert 'min-width: 56px !important' in css
