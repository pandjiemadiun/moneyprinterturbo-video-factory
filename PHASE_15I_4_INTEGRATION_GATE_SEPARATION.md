# PHASE 15I.4 — INTEGRATION GATE SEPARATION (READ-ONLY)

**Status:** SEPARATION DESIGN COMPLETE — NO SCRIPT MODIFIED

---

## EXECUTIVE SUMMARY

The current `scripts/quality_gate.sh` conflates three distinct test tiers into Level 3:
1. **AppTest runtime tests** — require Streamlit runtime, but no real browser
2. **Playwright integration tests** — require real Chromium + running WebUI server
3. **Responsive geometry tests** — require Playwright + running WebUI server

These must be separated because:
- AppTest tests can run in any environment with Streamlit installed
- Playwright tests require browser binaries, display server (or xvfb), and a running WebUI
- Playwright timeouts (20-45s per test) should not affect the deterministic quality score

---

## CURRENT STATE

### Playwright Test Files

| File | Tests | Prerequisites | Timeout |
|---|---|---|---|
| `test/services/test_webui_provider_custom.py` | 5 | Playwright + running WebUI on 8501/8502 or launchable | 20s per test |
| `test/services/test_webui_provider_custom_e2e.py` | 1+ | Playwright + running WebUI + mock OpenAI server | 20s+ per test |
| `test/services/test_webui_responsive_geometry.py` | 3 | Playwright + running WebUI on 8501/8502 | 45s per test |
| `test/services/test_youtube_provider_11h16.py` | Various | Mock-only (no Playwright) | N/A |

### Current quality_gate.sh Level 3

```bash
APPTEST_FILES=(
  "test/services/test_webui_llm_settings.py"
  "test/services/test_webui_voice_preview.py"
  "test/services/test_webui_tts_settings.py"
  "test/services/test_webui_bgm.py"
  "test/services/test_webui_loomloom.py"
  "test/services/test_webui_provider_custom.py"      # ← PLAYWRIGHT
  "test/services/test_webui_generation_defaults.py"
  "test/services/test_webui_task.py"
  "test/test_webui_navigation.py"
)
```

**Problem:** `test_webui_provider_custom.py` is Playwright, not AppTest. It requires:
1. A running WebUI server (either already running or launched by the test)
2. Playwright Chromium browser binaries
3. Network access to localhost

When no WebUI is running, these tests fail with `TimeoutError: Page.wait_for_selector: Timeout 20000ms exceeded` or skip with `"could not start local webui"`.

---

## PROPOSED SEPARATION

### LEVEL 3A — APPTEST RUNTIME (Streamlit AppTest)

**Command:**
```bash
uv run pytest -q --tb=no \
  test/test_webui_navigation.py \
  test/services/test_webui_loomloom.py \
  test/services/test_webui_responsive_contract.py \
  test/services/test_webui_voice_preview.py \
  test/services/test_webui_tts_settings.py \
  test/services/test_webui_bgm.py \
  test/services/test_webui_generation_defaults.py \
  test/services/test_webui_task.py \
  test/services/test_webui_llm_settings.py
```

**What it validates:**
- Navigation structure and page registry
- Widget rendering and labels
- Form submission and validation
- Session state management
- i18n label contracts

**Blocking:** YES (when tests are fixed to match multipage architecture)
**Current status:** 5 failures (navigation order-dependent) + ~38 failures (widget keys)

**Prerequisites:** Streamlit installed, no real browser needed

---

### LEVEL 3B — PLAYWRIGHT INTEGRATION (Real Browser)

**Command:**
```bash
MPT_RUN_INTEGRATION_TESTS=1 uv run pytest -q --tb=short \
  test/services/test_webui_provider_custom.py \
  test/services/test_webui_provider_custom_e2e.py \
  test/services/test_webui_responsive_geometry.py
```

**What it validates:**
- Real-browser layout at 320px mobile width
- Custom OpenAI provider discovery flow end-to-end
- Auth failure and 404 handling in real UI
- Stale invalidation on base URL change
- Responsive geometry (column widths, overflow, tab strip)

**Blocking:** NO (explicitly opt-in via `MPT_RUN_INTEGRATION_TESTS=1`)
**Current status:** 5 failed (timeout, no running WebUI) + 3 failed (no running WebUI)

**Prerequisites:**
1. `playwright install chromium` completed
2. Running WebUI on `http://127.0.0.1:8501` or `http://127.0.0.:8502`
   - OR `MPT_WEBUI_URL` env var pointing to live WebUI
   - OR permission to launch `streamlit run webui/Main.py` on a free port
3. xvfb or headless browser support (if no display)

**Skip conditions:**
- Playwright not installed → `pytest.skip("playwright not installed")`
- No running WebUI and cannot launch → `pytest.skip("could not start local webui")`

---

### LEVEL 4 — EXTERNAL API / NETWORK

**Command:**
```bash
MPT_RUN_INTEGRATION_TESTS=1 uv run pytest -q --tb=short \
  test/services/test_youtube_provider.py \
  test/services/test_loomloom.py
```

**What it validates:**
- YouTube download with PO token recovery
- LoomLoom API integration
- External API contracts

**Blocking:** NO
**Prerequisites:** Valid API keys, network access, YouTube cookies (if needed)

---

## CANONICAL QUALITY GATE STRUCTURE (UPDATED)

| Level | Name | Command | Blocking | Prerequisites |
|---|---|---|---|---|
| 1 | Static | `ruff check` + `py_compile` | YES | None |
| 2 | Deterministic backend | `pytest test/services/ --ignore=test/services/test_webui_*.py --ignore=test/services/test_webui_i18n.py` | YES | None |
| 3A | AppTest runtime | `pytest test/test_webui_navigation.py test/services/test_webui_*.py` (excluding Playwright files) | YES | Streamlit installed |
| 3B | Playwright integration | `MPT_RUN_INTEGRATION_TESTS=1 pytest test/services/test_webui_provider_custom*.py test/services/test_webui_responsive_geometry.py` | NO | Playwright + running WebUI |
| 4 | External/Network | `MPT_RUN_INTEGRATION_TESTS=1 pytest test/services/test_youtube_*.py test/services/test_loomloom.py` | NO | API keys + network |
| 5 | Production verification | `python3 scripts/verify_production.py` | YES (deploy gate) | Production environment |

---

## FAILURE CLASSIFICATION FOR PLAYWRIGHT TESTS

| Test File | Current Failure | Category | Recommended Disposition |
|---|---|---|---|
| `test_webui_provider_custom.py` | `TimeoutError: Page.wait_for_selector: Timeout 20000ms exceeded` | CATEGORY D — Harness failure (no running WebUI) | Separate into Tier 3B with explicit prerequisite check |
| `test_webui_provider_custom_e2e.py` | Same timeout | CATEGORY D — Harness failure | Separate into Tier 3B |
| `test_webui_responsive_geometry.py` | Same timeout | CATEGORY D — Harness failure | Separate into Tier 3B |

**Key point:** These tests are NOT failing due to production regressions. They are failing because the test environment doesn't meet their prerequisites (running WebUI server). When run against a running WebUI, they verify real production contracts.

---

## APPTEST ISOLATION ISSUE

The 5 order-dependent failures in `test_webui_navigation.py` are caused by Streamlit runtime state pollution when AppTest tests run in the same process.

**Current behavior:** Tests pass in isolation but fail when run after other AppTest suites.

**Root cause:** Streamlit's global runtime (`st.runtime`) is not reset between `AppTest.from_file()` calls in the same process.

**Fix:** Either:
1. Run each AppTest file in a subprocess (already done in quality_gate.sh Level 3)
2. Add a pytest fixture that resets Streamlit runtime state
3. Use `AppTest.from_file()` with `clear_cache=True` (if supported)

---

## SUMMARY

| Tier | Test Types | Current Failures | Failure Category | Blocking |
|---|---|---|---|---|
| 3A | AppTest (Streamlit) | ~43 | CATEGORY C (obsolete test) + CATEGORY D (isolation) | YES (when fixed) |
| 3B | Playwright (real browser) | 8 | CATEGORY D (no running WebUI) | NO (opt-in) |
| 4 | External/Network | Varies | CATEGORY E (missing credentials/network) | NO (opt-in) |

**Recommendation:** Update `scripts/quality_gate.sh` to:
1. Split Level 3 into 3A (AppTest) and 3B (Playwright)
2. Add `MPT_RUN_INTEGRATION_TESTS` guard to 3B and 4
3. Add explicit prerequisite checks for Playwright tests
4. Keep 3A failures separate from 3B/4 failures in quality score

---

*Report generated: 2026-09-08*
*Phase: 15I.4 — Integration Gate Separation*
*Mode: READ-ONLY — no script modified*
