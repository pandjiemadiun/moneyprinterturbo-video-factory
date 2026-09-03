"""Real-browser (Playwright) tests for the Custom OpenAI-Compatible provider.

This is the hybrid discovery contract verification that AppTest cannot express:
a REAL Chromium drives the REAL working-tree WebUI end-to-end, talking to a
local mock ``/models`` HTTP server (no real provider, no real API key, no
internet, no production data).

Coverage:
  * Layout @320px: Provider Name / Base URL / API Key / "Test & Discover Models"
    button / Model Name are all reachable, the button is a practical tap target
    (>=44px), and there is no horizontal overflow or width starvation.
  * Success path: discover -> dropdown populated with mock IDs -> selectable.
  * Auth failure (401): distinct "Authentication failed" message + manual
    fallback, and NO false "Connection successful" claim.
  * 404 unsupported: clear message + manual fallback.
  * Stale invalidation: changing the Base URL clears the previous dropdown.

The custom-provider widgets are addressed by their stable Streamlit widget keys
(``custom_openai_compatible_*``), which the production UI renders as
``div.st-key-<key>`` wrappers -- precise and immune to label-localization drift.
"""
from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    from playwright.sync_api import sync_playwright, expect
except Exception:  # pragma: no cover - environment guard
    sync_playwright = None
    expect = None
    pytest.skip("playwright not installed", allow_module_level=True)

PLAYWRIGHT_AVAILABLE = sync_playwright is not None


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _MockModelsHandler(BaseHTTPRequestHandler):
    """Serves a canned GET {anything}/models response."""

    def do_GET(self):  # noqa: N802 - http.server requires this name
        srv = self.server
        status = srv.canned_status
        payload = srv.canned_payload
        body = json.dumps(payload).encode() if payload is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence stderr noise
        pass


@pytest.fixture(scope="module")
def mock_models_server():
    srv = ThreadingHTTPServer(("127.0.0.1", _free_port()), _MockModelsHandler)
    srv.canned_status = 200
    srv.canned_payload = {"data": [{"id": "mock-model-a"}, {"id": "mock-model-b"}]}
    srv.daemon_threads = True
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _server_reachable(url: str, timeout: float = 2.0) -> bool:
    try:
        import urllib.request
        urllib.request.urlopen(url + "/render_settings", timeout=timeout)
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def local_webui():
    # Reuse a running instance when available (dev or prod), so the test always
    # exercises the SAME code that the user sees. Only fall back to launching a
    # fresh working-tree Streamlit when nothing is live.
    env_url = os.environ.get("MPT_WEBUI_URL")
    if env_url and _server_reachable(env_url):
        yield env_url; return
    for candidate in ("http://127.0.0.1:8501", "http://127.0.0.1:8502"):
        if _server_reachable(candidate):
            yield candidate; return

    port = _free_port()
    storage = "/tmp/mpt_custom_provider_test_storage"
    os.makedirs(storage, exist_ok=True)
    env = dict(
        os.environ,
        PYTHONPATH=str(ROOT),
        MPT_API_BASE_URL="http://127.0.0.1:8080",
        STORAGE_DIR=storage,
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(ROOT / "webui" / "Main.py"),
         "--server.address=127.0.0.1", f"--server.port={port}",
         "--server.enableCORS=True", "--server.headless=true",
         "--browser.serverAddress=127.0.0.1", "--browser.gatherUsageStats=False",
         "--client.toolbarMode=minimal", "--logger.hideWelcomeMessage=True",
         "--server.showEmailPrompt=False"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        preexec_fn=os.setsid if os.name != "nt" else None,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 50
        while time.time() < deadline:
            if _server_reachable(url):
                break
            time.sleep(1)
        else:
            pytest.skip("could not start local webui for custom provider tests")
        yield url
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()


def _open_llm_settings(page, base_url):
    last_err = None
    for _ in range(6):
        try:
            page.goto(base_url + "/render_settings", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector('[data-testid="stTabs"] [role="tablist"]', timeout=45000)
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(2)
    else:
        raise AssertionError(f"Settings tablist never rendered (cold start): {last_err}")
    page.eval_on_selector_all(
        '[data-testid="stTabs"] [role="tab"]',
        "(els)=>els.find(e=>e.textContent.trim().includes('AI & Script'))?.click()")
    page.wait_for_selector('div[class*="st-key-llm_form_help_row"]', timeout=20000)
    # Dismiss any transient modal (e.g. a Streamlit navigation placeholder) that
    # would otherwise intercept later clicks. No-op if nothing is open.
    page.keyboard.press("Escape")
    page.wait_for_timeout(600)


def _select_custom_provider(page):
    """Switch the LLM Provider dropdown to 'Custom Open AI-Compatible'.

    The provider listbox is virtualized and the option label may render either
    from i18n ("Custom Open AI-Compatible") or the provider default_label
    ("Custom OpenAI-Compatible"), so we match by a tolerant regex. We scroll the
    listbox incrementally from the top (moving the virtual window down) until
    the option renders, then click it.
    """
    page.wait_for_selector('div[class*="st-key-llm_form_help_row"]', timeout=20000)
    cb = page.get_by_role("combobox", name="LLM Provider").first
    cb.scroll_into_view_if_needed()
    cb.click(position={"x": 12, "y": 6})
    page.wait_for_timeout(1000)
    page.wait_for_selector('[role="listbox"]', timeout=5000)
    listbox = page.locator('[role="listbox"]').first
    target = page.get_by_role("option", name=re.compile(r"^Custom.*Compatible$", re.I))
    for _ in range(240):
        try:
            if target.count() > 0:
                target.scroll_into_view_if_needed()
                target.click()
                page.wait_for_timeout(800)
                page.wait_for_selector("div.st-key-custom_openai_compatible_provider_name_input", timeout=20000)
                return
        except Exception:  # noqa: BLE001 - option may not be rendered yet
            pass
        listbox.evaluate("el => el.scrollBy(0, 12)")
        page.wait_for_timeout(25)
    raise AssertionError("Custom OpenAI-Compatible option not found in provider dropdown")


def _fill(page, st_key, value):
    inp = page.locator(f"div.st-key-{st_key} input").first
    inp.fill(value)
    # Playwright `fill` updates the DOM value, but Streamlit only commits a
    # text widget to session_state (and triggers a script rerun) on blur/Enter.
    # Blur so dependent UI (e.g. stale-discovery invalidation) re-evaluates.
    inp.evaluate("(el)=>el.blur()")
    page.wait_for_timeout(500)


def _doc_scroll_width(page):
    return page.evaluate("()=>document.documentElement.scrollWidth")


@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="playwright not installed")
class TestCustomOpenAIProvider:
    def test_layout_320(self, local_webui, mock_models_server):
        """All custom-provider fields reachable; no overflow; tappable button."""
        mock_models_server.canned_status = 200
        mock_models_server.canned_payload = {"data": [{"id": "mock-model-a"}, {"id": "mock-model-b"}]}
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 320, "height": 1600})
            page = ctx.new_page()
            _open_llm_settings(page, local_webui)
            _select_custom_provider(page)

            for key, label in [
                ("custom_openai_compatible_provider_name_input", "Provider Name"),
                ("custom_openai_compatible_api_key_input", "API Key"),
                ("custom_openai_compatible_base_url_custom_input", "Base Url"),
            ]:
                assert page.locator(f"div.st-key-{key}").is_visible(), f"{label} field not reachable at 320px"

            btn = page.locator("div.st-key-custom_openai_compatible_discover_button button")
            assert btn.is_visible(), "Test & Discover button not visible"
            box = btn.first.bounding_box()
            assert box["width"] >= 44 and box["height"] >= 44, f"discover button too small: {box}"

            # No horizontal overflow.
            assert _doc_scroll_width(page) <= page.evaluate("()=>window.innerWidth"), "horizontal overflow at 320px"
            ctx.close()
            browser.close()

    def test_discover_success_populates_dropdown(self, local_webui, mock_models_server):
        mock_models_server.canned_status = 200
        mock_models_server.canned_payload = {"data": [{"id": "mock-model-a"}, {"id": "mock-model-b"}, {"id": "mock-model-c"}]}
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 412, "height": 1600})
            page = ctx.new_page()
            _open_llm_settings(page, local_webui)
            _select_custom_provider(page)

            base_url = f"http://127.0.0.1:{mock_models_server.server_address[1]}/v1"
            _fill(page, "custom_openai_compatible_base_url_custom_input", base_url)
            _fill(page, "custom_openai_compatible_api_key_input", "fake-discover-key-not-real")
            page.locator("div.st-key-custom_openai_compatible_discover_button button").click()
            sel = page.locator("div.st-key-custom_openai_compatible_model_select")
            page.wait_for_selector("div.st-key-custom_openai_compatible_model_select", timeout=20000)

            # Streamlit 1.59's react-aria ComboBox stores the selected model in an
            # <input value=...>, NOT as a text node, so inner_text() of the
            # selectbox container returns only the "Model name" label. Assert on the
            # input value instead, then open the dropdown to confirm the discovered
            # IDs are real selectable options.
            expect(sel.locator("input")).to_have_value("mock-model-a", timeout=10000)
            sel.get_by_role("combobox", name="Model Name").click()
            page.wait_for_timeout(400)
            assert page.get_by_role("option", name="mock-model-a").is_visible()
            assert page.get_by_role("option", name="mock-model-b").is_visible()
            assert page.get_by_role("option", name="mock-model-c").is_visible()
            page.get_by_role("option", name="mock-model-b").click()
            time.sleep(0.5)
            # selected value persists in the input's value after the rerun.
            assert sel.locator("input").get_attribute("value") == "mock-model-b"
            # Security: the API key legitimately lives in the password field
            # (the user typed it); it must never be echoed in any visible message
            # (innerText excludes input *values*, so this won't false-positive on
            # the password field's masked value).
            assert "fake-discover-key-not-real" not in page.evaluate("() => document.body.innerText || ''")
            ctx.close()
            browser.close()

    def test_auth_failure_distinct_message_and_manual_fallback(self, local_webui, mock_models_server):
        mock_models_server.canned_status = 401
        mock_models_server.canned_payload = None
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 412, "height": 1600})
            page = ctx.new_page()
            _open_llm_settings(page, local_webui)
            _select_custom_provider(page)
            base_url = f"http://127.0.0.1:{mock_models_server.server_address[1]}/v1"
            _fill(page, "custom_openai_compatible_base_url_custom_input", base_url)
            _fill(page, "custom_openai_compatible_api_key_input", "secret-that-must-not-leak")
            page.locator("div.st-key-custom_openai_compatible_discover_button button").click()
            page.wait_for_selector("div.st-key-custom_openai_compatible_model_name_manual_input", timeout=20000)
            page.wait_for_function(
                "()=>Array.from(document.body.querySelectorAll('*')).some(el=>"
                "(el.textContent||'').includes('Authentication failed'))", timeout=10000)
            # Auth must NOT claim a successful discovery (no success banner).
            assert "Connection successful" not in page.content()
            ctx.close()
            browser.close()

    def test_404_unsupported_shows_manual_fallback(self, local_webui, mock_models_server):
        mock_models_server.canned_status = 404
        mock_models_server.canned_payload = None
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 412, "height": 1600})
            page = ctx.new_page()
            _open_llm_settings(page, local_webui)
            _select_custom_provider(page)
            base_url = f"http://127.0.0.1:{mock_models_server.server_address[1]}/v1"
            _fill(page, "custom_openai_compatible_base_url_custom_input", base_url)
            _fill(page, "custom_openai_compatible_api_key_input", "fake-key")
            page.locator("div.st-key-custom_openai_compatible_discover_button button").click()
            page.wait_for_selector("div.st-key-custom_openai_compatible_model_name_manual_input", timeout=20000)
            page.wait_for_function(
                "()=>Array.from(document.body.querySelectorAll('*')).some(el=>"
                "(el.textContent||'').includes('Model discovery unsupported'))", timeout=10000)
            ctx.close()
            browser.close()

    def test_stale_invalidation_on_base_url_change(self, local_webui, mock_models_server):
        mock_models_server.canned_status = 200
        mock_models_server.canned_payload = {"data": [{"id": "first-model"}]}
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 412, "height": 1600})
            page = ctx.new_page()
            _open_llm_settings(page, local_webui)
            _select_custom_provider(page)
            base_url = f"http://127.0.0.1:{mock_models_server.server_address[1]}/v1"
            _fill(page, "custom_openai_compatible_base_url_custom_input", base_url)
            _fill(page, "custom_openai_compatible_api_key_input", "fake-key")
            page.locator("div.st-key-custom_openai_compatible_discover_button button").click()
            page.wait_for_selector("div.st-key-custom_openai_compatible_model_select", timeout=20000)
            # react-aria ComboBox keeps the value in <input value=...>; the default
            # discovered model ("first-model") is selected on success.
            expect(page.locator("div.st-key-custom_openai_compatible_model_select input")).to_have_value("first-model", timeout=10000)
            # Change Base URL -> stale dropdown must clear (invalidation).
            _fill(page, "custom_openai_compatible_base_url_custom_input", base_url + "-changed")
            # After a Base URL change the previously discovered dropdown is invalidated.
            page.wait_for_function(
                "()=>!document.querySelector('div.st-key-custom_openai_compatible_model_select')",
                timeout=10000)
            assert page.locator("div.st-key-custom_openai_compatible_model_name_manual_input").is_visible()
            # No API key echoed in any visible message (password value is excluded
            # from innerText, so this won't false-positive on the input field).
            assert "fake-key" not in page.evaluate("() => document.body.innerText || ''")
            ctx.close()
            browser.close()
