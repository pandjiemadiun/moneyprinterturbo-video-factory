"""Phase 15H regression protection -- REAL-browser geometry assertions.

The PO defect (Settings -> AI & Script, narrow mobile) was a GEOMETRY bug, not a
logic bug. AppTest only proves the widget tree renders; it cannot prove the
columns stop starving each other. This test asserts the REAL rendered contract
in Chromium, the same way the defect was diagnosed:

  * MOBILE (320/360/390/412): the LLM form column and the help column each get
    the full practical width (stacked, same left edge, help below form), the
    "Kimi API Platform" selectbox label renders on a SINGLE line (height < 32px,
    not fragmented to 5+ lines), and there is NO horizontal page overflow.
  * DESKTOP (>=768): the two columns stay side-by-side (help column starts to the
    right of the form column) -- the desktop contract is preserved.
  * TAB STRIP: on narrow viewports the tab bar overflows and renders a right-edge
    fade (::after gradient) so clipped tabs are discoverable, and every tab --
    including "System" at the far right -- is reachable by scrolling.

Server handling:
  * MPT_WEBUI_URL env var -> use that server directly.
  * else if http://127.0.0.1:8502 is live -> use it.
  * else launch a throwaway `streamlit run webui/Main.py` on a free port and tear
    it down afterwards. The render routes are read-only GETs (no jobs created).
"""
from __future__ import annotations

import os, sys, time, socket, subprocess, signal

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

PLAYWRIGHT_AVAILABLE = True
try:
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover
    PLAYWRIGHT_AVAILABLE = False

MOBILE_VIEWPORTS = [320, 360, 390, 412]
DESKTOP_VIEWPORTS = [768, 1024, 1365]
PRACTICAL_MIN_WIDTH = 250  # px: wide enough for a tappable selectbox / input


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close(); return port


def _server_reachable(url: str, timeout: float = 1.5) -> bool:
    from urllib.request import urlopen
    try:
        urlopen(url + "/render_settings", timeout=timeout); return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def webui_server():
    env_url = os.environ.get("MPT_WEBUI_URL")
    if env_url and _server_reachable(env_url):
        yield env_url; return
    if _server_reachable("http://127.0.0.1:8502"):
        yield "http://127.0.0.1:8502"; return

    if not PLAYWRIGHT_AVAILABLE:
        pytest.skip("playwright not installed and no webui server reachable")

    port = _free_port()
    env = dict(os.environ,
               MPT_API_BASE_URL="http://127.0.0.1:8080",
               PYTHONPATH=str(ROOT),
               STORAGE_DIR=os.environ.get("STORAGE_DIR", "/tmp/mpt_test_storage"))
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(ROOT / "webui" / "Main.py"),
         "--server.address=127.0.0.1", f"--server.port={port}",
         "--server.enableCORS=False", "--server.headless=true",
         "--browser.serverAddress=127.0.0.1",
         "--browser.gatherUsageStats=False", "--client.toolbarMode=minimal",
         "--logger.hideWelcomeMessage=True", "--server.showEmailPrompt=False"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        preexec_fn=os.setsid if os.name != "nt" else None)
    try:
        url = f"http://127.0.0.1:{port}"
        deadline = time.time() + 35
        while time.time() < deadline:
            if _server_reachable(url): break
            time.sleep(1)
        else:
            pytest.skip("could not start webui server")
        yield url
    finally:
        try:
            if os.name != "nt": os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            else: proc.terminate()
        except Exception:
            pass
        try: proc.wait(timeout=8)
        except Exception:
            try: proc.kill()
            except Exception: pass


def _open_llm_settings(page, base_url):
    # Cold-start tolerant: a freshly (re)started Streamlit may need several
    # seconds to first-render Settings. Retry the navigation (domcontentloaded
    # is more reliable than networkidle on Streamlit's long-poll) and wait
    # generously for the tab bar -- the real readiness signal.
    last_err = None
    for _ in range(6):
        try:
            page.goto(base_url + "/render_settings", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector('[data-testid="stTabs"] [role="tablist"]', timeout=45000)
            break
        except Exception as e:  # noqa: BLE001 - retry until Settings is ready
            last_err = e
            time.sleep(2)
    else:
        raise AssertionError(f"Settings tablist never rendered (cold start): {last_err}")
    page.eval_on_selector_all('[data-testid="stTabs"] [role="tab"]',
        "(els)=>els.find(e=>e.textContent.trim().includes('AI & Script'))?.click()")
    page.wait_for_selector('div[class*="st-key-llm_form_help_row"]', timeout=20000)
    # Cold-start race: the form/help row may exist while the LLM provider
    # selectbox label ('Kimi API Platform') is still being painted. Wait for
    # the actual label text to be present so the geometry measurement is valid.
    page.wait_for_function(
        "()=>Array.from(document.querySelectorAll('[data-testid=\"stWidgetLabel\"]'))"
        ".some(l=>(l.textContent||'').trim()==='Kimi API Platform')",
        timeout=25000)


def _llm_form_geometry(page):
    return page.evaluate("""() => {
  const root = document.querySelector('div[class*="st-key-llm_form_help_row"]');
  const form = root.querySelector('[data-testid="stColumn"]:first-child');
  const help = root.querySelector('[data-testid="stColumn"]:last-child');
  let label = null;
  const labels = Array.from(document.querySelectorAll('[data-testid="stWidgetLabel"]'));
  const lblEl = labels.find(l => (l.textContent||"").trim() === "Kimi API Platform");
  if (lblEl) {
    const r = lblEl.getBoundingClientRect();
    label = {w: Math.round(r.width), h: Math.round(r.height)};
  }
  const fr = root.getBoundingClientRect();
  const f = form.getBoundingClientRect(); const h = help.getBoundingClientRect();
  return {
    parentW: Math.round(fr.width),
    formCol: {x: Math.round(f.x), y: Math.round(f.y), w: Math.round(f.width), bottom: Math.round(f.bottom)},
    helpCol: {x: Math.round(h.x), y: Math.round(h.y), w: Math.round(h.width), top: Math.round(h.top)},
    label,
    docScrollW: document.documentElement.scrollWidth,
    winW: window.innerWidth,
  };
    }""")


@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="playwright not installed")
class TestResponsiveGeometry:
    def test_llm_form_stacks_full_width_on_mobile(self, webui_server):
        """Phase 15H PO defect: form+help must STACK full-width (no starvation) on mobile."""
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            for vw in MOBILE_VIEWPORTS:
                ctx = b.new_context(viewport={"width": vw, "height": 1400})
                page = ctx.new_page()
                _open_llm_settings(page, webui_server)
                g = _llm_form_geometry(page)
                f, h = g["formCol"], g["helpCol"]
                assert f["w"] >= PRACTICAL_MIN_WIDTH, f"form col starved at {vw}px: {f['w']}px"
                assert h["w"] >= PRACTICAL_MIN_WIDTH, f"help col starved at {vw}px: {h['w']}px"
                assert f["x"] == h["x"], f"not stacked at {vw}px: form x={f['x']} help x={h['x']}"
                assert h["top"] > f["bottom"], f"help not below form at {vw}px"
                assert g["label"]["h"] < 32, f"'Kimi API Platform' fragmented at {vw}px: h={g['label']['h']}"
                assert g["docScrollW"] <= g["winW"], f"horizontal overflow at {vw}px"
                ctx.close()
            b.close()

    def test_llm_form_stays_side_by_side_on_desktop(self, webui_server):
        """Desktop contract preserved: columns remain side-by-side."""
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            for vw in DESKTOP_VIEWPORTS:
                ctx = b.new_context(viewport={"width": vw, "height": 1400})
                page = ctx.new_page()
                _open_llm_settings(page, webui_server)
                g = _llm_form_geometry(page)
                f, h = g["formCol"], g["helpCol"]
                assert h["x"] >= f["x"] + f["w"] - 20, f"not side-by-side at {vw}px: {f} {h}"
                assert g["docScrollW"] <= g["winW"], f"horizontal overflow at {vw}px"
                ctx.close()
            b.close()

    def test_tab_strip_fade_and_all_tabs_reachable(self, webui_server):
        """Phase C: mobile tab bar overflows with a visible fade; every tab reachable."""
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            ctx = b.new_context(viewport={"width": 320, "height": 1400})
            page = ctx.new_page()
            page.goto(webui_server + "/render_settings", wait_until="networkidle")
            page.wait_for_selector('[data-testid="stTabs"] [role="tablist"]', timeout=20000)
            page.eval_on_selector_all('[data-testid="stTabs"] [role="tab"]',
                "(els)=>els.find(e=>e.textContent.trim().includes('AI & Script'))?.click()")
            time.sleep(0.4)
            info = page.evaluate("""() => {
  const tl = document.querySelector('[data-testid="stTabs"] [role="tablist"]');
              const after = getComputedStyle(tl, '::after');
              const tr = tl.getBoundingClientRect();
              const hasFade = /linear-gradient/.test(after.background) &&
                0 < parseFloat(after.width) && parseFloat(after.width) < tr.width;
              const tabs = Array.from(document.querySelectorAll('[data-testid="stTabs"] [role="tab"]'));
              tl.scrollTo({left: tl.scrollWidth, behavior: 'auto'});
              const sys = tabs.find(t => t.textContent.includes('System'));
              const sysR = sys ? sys.getBoundingClientRect() : null;
              return {nTabs: tabs.length, overflow: tl.scrollWidth > tl.clientWidth,
                hasFade, systemRight: sysR ? Math.round(sysR.right) : null,
                winW: window.innerWidth,
                systemFullyVisible: sysR ? sysR.right <= window.innerWidth + 4 : false};
            }""")
            assert info["nTabs"] == 6, f"expected 6 tabs, got {info['nTabs']}"
            assert info["overflow"], "tab strip should overflow on mobile"
            assert info["hasFade"], "tab strip must render a right-edge fade affordance"
            assert info["systemFullyVisible"], f"System tab unreachable when scrolled: right={info['systemRight']} win={info['winW']}"
            ctx.close(); b.close()
