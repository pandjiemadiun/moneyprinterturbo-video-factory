"""End-to-end regression for the COMPLETE Custom OpenAI-Compatible provider flow.

The existing ``test_webui_provider_custom.py`` proves model *discovery*, but
not the full contract: discover -> select model -> "Test LLM Connection" ->
actual ``POST /chat/completions`` carrying the selected model + Bearer auth.

This module closes that gap with a real Chromium driving a real (isolated,
working-tree) WebUI talking to a local mock OpenAI-compatible server.

The mock never logs or echoes the API key: it only records a boolean
``auth_valid`` flag (does the ``Authorization`` header equal
``Bearer <expected_key>``) and the model string the runtime sent. No secret
value appears in test output, screenshots, or committed assertions.

Contract proven:
  1. GET {base_url}/models is received by the mock.
  2. Discovered IDs populate the model dropdown.
  3. A specific discovered model is selected.
  4. The selected model reaches the runtime (POST /chat/completions model ==
     selected) -- this is also the "persisted into config" proof, because
     ``llm.test_connection()`` reads ``config.app`` which the UI writes from the
     selected widget value.
  5. "Test LLM Connection" triggers an ACTUAL generation request.
  6. The POST hits the configured Base URL path (/v1/chat/completions).
  7. The POST uses Bearer auth and EXACTLY the selected model.
  8. The mock response reaches the application.
  9. The UI reports a successful connection.
 10. API keys never appear in visible UI / assertions / screenshots.

A negative test proves the assertions are meaningful (wrong model or broken
auth would fail the same assertions).
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
    pytest.skip("playwright not installed", allow_module_level=True)

PLAYWRIGHT_AVAILABLE = True

# Test-only secret. NEVER printed, NEVER asserted on by value, NEVER written
# into any visible UI. The mock only exposes a boolean auth-validity flag.
TEST_SECRET = "test-only-mpt-secret-9f3c2a81"

DISCOVERED_MODELS = ["model-alpha", "model-bravo"]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _server_reachable(url: str, timeout: float = 2.0) -> bool:
    try:
        import urllib.request

        urllib.request.urlopen(url + "/render_settings", timeout=timeout)
        return True
    except Exception:
        return False


class _MockOpenAIHandler(BaseHTTPRequestHandler):
    """Isolated mock OpenAI-compatible server.

    GET  .../v1/models           -> model list (always 200; discovery is not
                                     auth-gated in this mock so the auth path
                                     can be isolated to the generation POST).
    POST .../v1/chat/completions -> captures model + auth status; returns a
                                     minimal "OK" completion when the Bearer
                                     token matches ``expected_api_key``, else
                                     401. The API key is NEVER stored.
    """

    def _read_body(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def do_GET(self):  # noqa: N802 - http.server requires this name
        srv = self.server
        auth = self.headers.get("Authorization", "")
        srv.received_gets.append(
            {
                "path": self.path,
                "auth_present": bool(auth),
                "auth_valid": auth == f"Bearer {srv.expected_api_key}",
            }
        )
        if "/models" in self.path:
            body = json.dumps(
                {
                    "object": "list",
                    "data": [{"id": m, "object": "model"} for m in srv.canned_models],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def do_POST(self):  # noqa: N802
        srv = self.server
        raw = self._read_body()
        try:
            payload = json.loads(raw.decode()) if raw else {}
        except Exception:
            payload = {}
        auth = self.headers.get("Authorization", "")
        srv.received_posts.append(
            {
                "path": self.path,
                "model": payload.get("model"),
                "auth_present": bool(auth),
                "auth_valid": auth == f"Bearer {srv.expected_api_key}",
            }
        )
        if "/chat/completions" in self.path and auth == f"Bearer {srv.expected_api_key}":
            body = json.dumps(
                {
                    "id": "e2e-chatcm",
                    "object": "chat.completion",
                    "created": 1700000000,
                    "model": payload.get("model", ""),
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "OK"},
                            "finish_reason": "stop",
                        }
                    ],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = json.dumps({"error": {"message": "Unauthorized"}}).encode()
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, *args):  # silence stderr noise
        pass


def _make_mock_server():
    port = _free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), _MockOpenAIHandler)
    srv.expected_api_key = TEST_SECRET
    srv.canned_models = list(DISCOVERED_MODELS)
    srv.received_gets = []
    srv.received_posts = []
    srv.daemon_threads = True
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv


@pytest.fixture(scope="module")
def mock_openai_server():
    srv = _make_mock_server()
    yield srv
    srv.shutdown()
    srv.server_close()


def _reset_mock(srv):
    srv.received_gets.clear()
    srv.received_posts.clear()
    srv.expected_api_key = TEST_SECRET
    srv.canned_models = list(DISCOVERED_MODELS)


@pytest.fixture(scope="module")
def isolated_webui():
    """ALWAYS launch a host-local throwaway WebUI (never reuse prod 8501):

    the mock server is bound to 127.0.0.1 on the host, and a bridged container
    (prod 8501) cannot reach the host's loopback. An isolated throwaway
    (working-tree code == deployed 9a065a9) guarantees the mock is reachable.
    """
    port = _free_port()
    storage = f"/tmp/mpt_custom_e2e_storage_{port}"
    os.makedirs(storage, exist_ok=True)
    env = dict(
        os.environ,
        PYTHONPATH=str(ROOT),
        MPT_API_BASE_URL="http://127.0.0.1:8080",
        STORAGE_DIR=storage,
    )
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", str(ROOT / "webui" / "Main.py"),
            "--server.address=127.0.0.1", f"--server.port={port}",
            "--server.headless=true", "--browser.serverAddress=127.0.0.1",
            "--browser.gatherUsageStats=False", "--client.toolbarMode=minimal",
            "--logger.hideWelcomeMessage=True", "--server.showEmailPrompt=False",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid if os.name != "nt" else None,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            if _server_reachable(url):
                break
            time.sleep(1)
        else:
            pytest.skip("could not start isolated webui for E2E test")
        yield url, port
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()


# --- navigation helpers (copied verbatim from the proven custom-provider tests) ---

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
    page.keyboard.press("Escape")  # dismiss transient modals
    page.wait_for_timeout(600)


def _select_custom_provider(page):
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
                page.wait_for_selector(
                    "div.st-key-custom_openai_compatible_provider_name_input", timeout=20000
                )
                return
        except Exception:  # noqa: BLE001
            pass
        listbox.evaluate("el => el.scrollBy(0, 12)")
        page.wait_for_timeout(25)
    raise AssertionError("Custom OpenAI-Compatible option not found in provider dropdown")


def _fill(page, st_key, value):
    inp = page.locator(f"div.st-key-{st_key} input").first
    inp.fill(value)
    # Streamlit 1.59 only commits a text widget on blur; blur so the rerun
    # actually propagates dependent state (stale-discovery invalidation).
    inp.evaluate("(el)=>el.blur()")
    page.wait_for_timeout(500)


def _doc_scroll_width(page):
    return page.evaluate("()=>document.documentElement.scrollWidth")


def _configure_custom_provider(page, mock_port, api_key, provider_name="Groq"):
    """Select Custom provider, fill the three fields, run discovery.

    Returns the discovered-model selectbox locator (dropdown populated).
    """
    _select_custom_provider(page)
    _fill(page, "custom_openai_compatible_provider_name_input", provider_name)
    base_url = f"http://127.0.0.1:{mock_port}/v1"
    _fill(page, "custom_openai_compatible_base_url_custom_input", base_url)
    _fill(page, "custom_openai_compatible_api_key_input", api_key)
    page.locator("div.st-key-custom_openai_compatible_discover_button button").click()
    page.wait_for_selector("div.st-key-custom_openai_compatible_model_select", timeout=30000)
    return base_url


def _select_discovered_model(page, model_id):
    sel = page.locator("div.st-key-custom_openai_compatible_model_select")
    sel.get_by_role("combobox", name="Model Name").click()
    page.wait_for_timeout(400)
    page.get_by_role("option", name=model_id).click()
    page.wait_for_timeout(600)
    expect(sel.locator("input")).to_have_value(model_id, timeout=10000)
    return sel


def _test_llm_connection(page):
    page.locator("div.st-key-test_llm_connection_button button").click()


def _wait_for_success(page, timeout=25000):
    page.wait_for_function(
        "()=>document.body.innerText.includes('Connection successful:')",
        timeout=timeout,
    )


def _wait_for_failure(page, timeout=25000):
    page.wait_for_function(
        "()=>document.body.innerText.includes('Connection failed:')",
        timeout=timeout,
    )


@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="playwright not installed")
class TestCustomProviderE2E:
    """Full discover -> select -> Test LLM Connection -> POST contract."""

    def test_e2e_discover_select_and_test_connection(
        self, isolated_webui, mock_openai_server
    ):
        _reset_mock(mock_openai_server)
        webui_url, _port = isolated_webui
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 412, "height": 1600})
            page = ctx.new_page()
            _open_llm_settings(page, webui_url)

            # (steps 4-6) Select Custom, fill Name/Base URL/API Key, discover.
            base_url = _configure_custom_provider(
                page, mock_openai_server.server_address[1], TEST_SECRET
            )

            # (step 7) GET /v1/models was received by the mock.
            gets = [g for g in mock_openai_server.received_gets if "/models" in g["path"]]
            assert gets, "GET /models was never received by the mock server"
            assert any(g["path"].endswith("/v1/models") for g in gets), (
                f"unexpected discovery path: {[g['path'] for g in gets]}"
            )

            # (step 8) Dropdown is populated with the discovered IDs.
            sel = page.locator("div.st-key-custom_openai_compatible_model_select")
            expect(sel.locator("input")).to_have_value("model-alpha", timeout=10000)
            sel.get_by_role("combobox", name="Model Name").click()
            page.wait_for_timeout(400)
            assert page.get_by_role("option", name="model-alpha").is_visible()
            assert page.get_by_role("option", name="model-bravo").is_visible()

            # (step 9-10) Select model-bravo (committed to <input value> by 1.59).
            _select_discovered_model(page, "model-bravo")
            expect(sel.locator("input")).to_have_value("model-bravo", timeout=10000)

            # (step 11) Click "Test LLM Connection".
            _test_llm_connection(page)

            # (step 16) UI reports connection success (mock response reached app).
            # Waiting for the success banner also proves the generation POST has
            # completed end-to-end, so the mock captures below are settled.
            _wait_for_success(page, timeout=30000)

            # (step 12) POST /v1/chat/completions was received.
            posts = list(mock_openai_server.received_posts)
            assert posts, "POST /chat/completions was NEVER received (no generation request)"
            post = posts[-1]

            # (step 13) selected model == POST model.
            assert post["model"] == "model-bravo", (
                f"request model mismatch: got {post['model']!r}, expected 'model-bravo'"
            )
            # (step 14) Base URL path == /v1/chat/completions.
            assert post["path"] == "/v1/chat/completions", (
                f"unexpected POST path: {post['path']!r}"
            )
            # (step 7/15) Bearer auth validated WITHOUT exposing the secret.
            assert post["auth_present"] is True, "Authorization header missing on POST"
            assert post["auth_valid"] is True, (
                "Bearer auth mismatch: the configured API key did not authenticate"
            )

            visible = page.evaluate("() => document.body.innerText || ''")
            assert "model-bravo" in visible, "UI did not echo the selected model on success"
            # (step 10 of safety) API key must NEVER appear in visible UI.
            assert TEST_SECRET not in visible, "API key leaked into visible UI text"

            ctx.close()
            browser.close()

    def test_e2e_wrong_model_would_fail_assertion(
        self, isolated_webui, mock_openai_server
    ):
        """NEGATIVE / regression proof: selecting model-alpha must send
        model-alpha. If the runtime ignored the selection (hardcoded / stale
        value), ``post['model']`` would be 'model-bravo' and this assertion
        would FAIL -- proving the model-binding contract is actually enforced."""
        _reset_mock(mock_openai_server)
        webui_url, _port = isolated_webui
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 412, "height": 1600})
            page = ctx.new_page()
            _open_llm_settings(page, webui_url)
            _configure_custom_provider(
                page, mock_openai_server.server_address[1], TEST_SECRET
            )
            # NOTE: deliberately select model-ALPHA here.
            _select_discovered_model(page, "model-alpha")
            _test_llm_connection(page)
            _wait_for_success(page, timeout=30000)
            posts = list(mock_openai_server.received_posts)
            assert posts
            post = posts[-1]
            assert post["model"] == "model-alpha", (
                f"model binding broken: expected 'model-alpha', got {post['model']!r}"
            )
            visible = page.evaluate("() => document.body.innerText || ''")
            assert "model-alpha" in visible
            assert TEST_SECRET not in visible
            ctx.close()
            browser.close()

    def test_e2e_auth_mismatch_blocks_success(
        self, isolated_webui, mock_openai_server
    ):
        """NEGATIVE / regression proof: a wrong API key must still trigger a
        POST /chat/completions (proving the generation path fires) but the
        request must be auth-rejected (auth_valid=False) and the UI must NOT
        report success. This catches an auth-bypass regression."""
        _reset_mock(mock_openai_server)
        # Simulate a user who configured a DIFFERENT/incorrect key than the mock
        # expects. The mock compares against TEST_SECRET and will reject it.
        mock_openai_server.expected_api_key = TEST_SECRET
        webui_url, _port = isolated_webui
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 412, "height": 1600})
            page = ctx.new_page()
            _open_llm_settings(page, webui_url)
            # Wrong API key on the UI side; mock expects TEST_SECRET -> mismatch.
            _configure_custom_provider(
                page, mock_openai_server.server_address[1], "invalid-key-not-the-expected-secret"
            )
            _select_discovered_model(page, "model-bravo")
            _test_llm_connection(page)
            # Wait for the FAILURE banner (the mock rejects the wrong key). This
            # also guarantees the generation POST has been received + rejected
            # before we inspect the captures -- i.e. the request really fired.
            _wait_for_failure(page, timeout=30000)
            # The POST is still issued (proving the generation path fires)...
            posts = list(mock_openai_server.received_posts)
            assert posts, "Test LLM Connection did not issue a POST request"
            post = posts[-1]
            assert post["auth_present"] is True
            assert post["auth_valid"] is False, (
                "auth_valid should be False for a mismatched API key"
            )
            # ...but the mock rejected it -> UI shows failure, not success.
            visible = page.evaluate("() => document.body.innerText || ''")
            assert "Connection failed" in visible
            assert TEST_SECRET not in visible
            # No false Test-LLM success banner. (The discovery success banner
            # "✓ Connection successful" has no colon and is allowed; only the
            # generation success "Connection successful:" must be absent.)
            assert "Connection successful:" not in visible, (
                "UI falsely claimed Test LLM Connection success despite auth failure"
            )
            # No false success banner from the *generation* attempt (the
            # discovery success banner is allowed, but not a Test LLM success).
            assert "Connection successful:" not in visible, (
                "UI falsely claimed Test LLM Connection success despite auth failure"
            )
            ctx.close()
            browser.close()
