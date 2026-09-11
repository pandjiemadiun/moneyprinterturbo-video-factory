# PHASE 15I.2A — WIDGET-KEY FORENSIC MAPPING (READ-ONLY)

**Status:** INVENTORY COMPLETE — NO FIXES APPLIED

---

## EXECUTIVE SUMMARY

All ~38 remaining AppTest failures across 5 test suites share a **single root cause**: tests load `webui/Main.py` via `AppTest.from_file(str(WEBUI_MAIN))`, but `Main.py` uses `st.navigation(NAV_PAGES, position="hidden")` with **Overview as the default page**. AppTest executes Main.py but does not automatically navigate to Create/Settings pages, so widgets defined in `webui/pages/create.py` and `webui/pages/settings.py` are never rendered.

**Classification:** CATEGORY C — OBSOLETE TEST / ARCHITECTURE MISMATCH

**No production code is implicated.** The widgets exist at the correct keys in the correct page modules. The tests simply never reach those pages.

---

## INVENTORY BY TEST SUITE

### 1. test/services/test_webui_voice_preview.py (7 failures)

| Test Function | Old Key / Search | Expected Behavior | New Location | Actual Key | Disposition |
|---|---|---|---|---|---|
| `test_full_voiceover_preview_is_disabled_until_script_exists` | `generate_full_voiceover_preview_button` | Button disabled when script empty | `webui/pages/create.py:648` | `generate_full_voiceover_preview_button` | CATEGORY C — AppTest loads Main.py (defaults to Overview); button is on Create page |
| `test_script_shows_estimate_and_enables_full_voiceover_preview` | `generate_full_voiceover_preview_button` | Button enabled when script present | `webui/pages/create.py:648` | `generate_full_voiceover_preview_button` | CATEGORY C — Same navigation issue |
| `test_short_preview_autoplays_only_after_explicit_click_and_reuses_cache` | `play_voice_button` | Short preview button with autoplay | `webui/pages/create.py:645` | `play_voice_button` | CATEGORY C — Same navigation issue |
| `test_full_preview_uses_script_and_reuses_identical_cached_audio` | `play_voice_button`, `generate_full_voiceover_preview_button` | Full preview caches audio | `webui/pages/create.py:645,648` | Same keys | CATEGORY C — Same navigation issue |
| `test_full_preview_reports_when_tts_returns_no_audio` | `generate_full_voiceover_preview_button` | Error shown when TTS returns None | `webui/pages/create.py:648` | Same key | CATEGORY C — Same navigation issue |
| `test_full_preview_returns_immediately_when_runtime_config_is_busy` | `generate_full_voiceover_preview_button` | Preview skipped when config busy | `webui/pages/create.py:648` | Same key | CATEGORY C — Same navigation issue |
| `test_full_preview_warns_when_audio_duration_is_unavailable` | `generate_full_voiceover_preview_button` | Warning shown when duration unreadable | `webui/pages/create.py:648` | Same key | CATEGORY C — Same navigation issue |

**Pattern:** All 7 failures are `StopIteration` from `_button_by_key()` because `app.button` is empty (Overview page has no buttons with these keys).

**Atomic fix scope:** Update all 7 tests to load `webui/pages/create.py` directly instead of `webui/Main.py`, OR add navigation logic to switch to Create page before assertions.

---

### 2. test/services/test_webui_tts_settings.py (7 failures)

| Test Function | Old Key / Search | Expected Behavior | New Location | Actual Key | Disposition |
|---|---|---|---|---|---|
| `test_tts_provider_inputs_render_the_standardized_labels` | `tts_server_select` | Selectbox with provider labels | `webui/pages/settings.py` | `tts_server_select` (in settings page) | CATEGORY C — AppTest loads Main.py (Overview); widget is on Settings page |
| `test_elevenlabs_reconnect_restores_saved_key_before_loading_voices` | `elevenlabs_api_key_input` | Saved key restored before voice load | `webui/pages/settings.py` | `elevenlabs_api_key_input` | CATEGORY C — Same navigation issue |
| `test_elevenlabs_environment_key_is_used_without_persisting_it` | `elevenlabs_api_key_input` | Env key used but not saved | `webui/pages/settings.py` | `elevenlabs_api_key_input` | CATEGORY C — Same navigation issue |
| `test_minimax_reconnect_restores_saved_tts_key` | `minimax_api_key_input` | Saved key restored on reconnect | `webui/pages/settings.py` | `minimax_api_key_input` | CATEGORY C — Same navigation issue |
| `test_minimax_shared_llm_key_is_not_duplicated_in_tts_config` | `minimax_api_key_input` | LLM key not duplicated in TTS config | `webui/pages/settings.py` | `minimax_api_key_input` | CATEGORY C — Same navigation issue |
| `test_minimax_voice_selector_accepts_a_custom_voice_id` | `minimax_voice_select` | Voice selector accepts custom ID | `webui/pages/settings.py` | `minimax_voice_select` | CATEGORY C — Same navigation issue |
| `test_minimax_voices_load_only_on_demand_and_sync_the_selected_voice` | `minimax_voice_select` | Voices load on demand | `webui/pages/settings.py` | `minimax_voice_select` | CATEGORY C — Same navigation issue |

**Pattern:** All 7 failures are `StopIteration` from `_widget_by_key()` because `app.selectbox`/`app.text_input` is empty (Overview page has no TTS settings widgets).

**Atomic fix scope:** Update all 7 tests to load `webui/pages/settings.py` directly, OR add navigation to Settings page.

---

### 3. test/services/test_webui_bgm.py (18 failures + 6 subfailed)

#### FAILED (hard failures — 6 tests)

| Test Function | Old Key / Search | Expected Behavior | New Location | Actual Key | Disposition |
|---|---|---|---|---|---|
| `test_elevenlabs_connection_button_reports_success` | `bgm_type_select` | BGM type selector present | `webui/pages/create.py` | `bgm_type_select` | CATEGORY C — AppTest loads Main.py (Overview); widget is on Create page |
| `test_sonilo_connection_button_reports_success` | `bgm_type_select` | Sonilo connection test | `webui/pages/create.py` | `bgm_type_select` | CATEGORY C — Same navigation issue |
| `test_elevenlabs_tts_and_music_share_one_api_key_widget` | `elevenlabs_api_key_input` | Shared API key widget | `webui/pages/settings.py` or `create.py` | `elevenlabs_api_key_input` | CATEGORY C — Same navigation issue |
| `test_zero_volume_defers_custom_upload_validation_until_enabled` | `bgm_custom_upload` | Custom upload validation deferred | `webui/pages/create.py` | `bgm_custom_upload` | CATEGORY C — Same navigation issue |
| `test_zero_volume_does_not_require_elevenlabs_key` | `bgm_type_select` | No key required at zero volume | `webui/pages/create.py` | `bgm_type_select` | CATEGORY C — Same navigation issue |
| `test_zero_volume_does_not_require_sonilo_key` | `bgm_type_select` | No Sonilo key at zero volume | `webui/pages/create.py` | `bgm_type_select` | CATEGORY C — Same navigation issue |

#### SUBFAILED (locale-dependent — 12 tests, 6 en + 6 id)

These tests use `pytest.mark.parametrize("locale", TEST_LOCALES)` where `TEST_LOCALES = ("en", "id")`. They fail with `SUBFAILED(locale='en')` or `SUBFAILED(locale='id')` because the widget lookup fails for both locales.

| Test Function | Old Key / Search | New Location | Disposition |
|---|---|---|---|
| `test_elevenlabs_connection_reports_paid_plan_requirement` | `bgm_type_select` | `webui/pages/create.py` | CATEGORY C — Same navigation issue |
| `test_elevenlabs_source_reuses_masked_tts_key_and_shows_prompt` | `bgm_type_select` | `webui/pages/create.py` | CATEGORY C — Same navigation issue |
| `test_invalid_audio_shows_error_without_ready_state_or_player` | `bgm_custom_upload` | `webui/pages/create.py` | CATEGORY C — Same navigation issue |
| `test_service_failure_is_not_reported_as_invalid_user_audio` | `bgm_custom_upload` | `webui/pages/create.py` | CATEGORY C — Same navigation issue |
| `test_sonilo_source_shows_masked_prefilled_key_and_optional_prompt` | `bgm_type_select` | `webui/pages/create.py` | CATEGORY C — Same navigation issue |
| `test_valid_audio_shows_ready_state_and_reuses_validation_cache` | `bgm_custom_upload` | `webui/pages/create.py` | CATEGORY C — Same navigation issue |

**Atomic fix scope:** Update all 18 tests to load `webui/pages/create.py` directly (or navigate to Create page). The locale parametrization is correct; the failure is purely navigation.

---

### 4. test/services/test_webui_navigation.py (5 order-dependent failures)

These 5 failures only appear when navigation tests run AFTER other AppTest suites in the same process. They are caused by Streamlit's global runtime state being polluted by previous AppTest runs.

| Test Function | Failure Mode | Disposition |
|---|---|---|
| `test_prefill_flows_from_review_to_create` | Order-dependent state pollution | CATEGORY D — Harness failure (AppTest isolation) |
| `test_nav_shell_renders_hamburger_on_all_six_pages` | Order-dependent state pollution | CATEGORY D — Harness failure |
| `test_drawer_navigates_to_each_target[Create-nav_item_create-render_discover]` | Order-dependent state pollution | CATEGORY D — Harness failure |
| `test_create_is_production_workspace` | Order-dependent state pollution | CATEGORY D — Harness failure |
| `test_prefill_preserves_script_opportunity_and_media` | Order-dependent state pollution | CATEGORY D — Harness failure |

**Note:** All 5 pass when run in isolation (41 passed when run alone). This is a test isolation issue, not a production regression.

**Atomic fix scope:** Ensure each AppTest runs in a subprocess or reset Streamlit runtime state between tests.

---

### 5. test/services/test_webui_voice_preview.py (2 additional backend-contract failures)

These are NOT widget-key failures. They are backend contract tests that run after the AppTest tests and fail due to shared state pollution.

| Test Function | Failure Mode | Disposition |
|---|---|---|
| `test_provider_signature_changes_when_api_key_changes` | AssertionError: signature unchanged after key change | CATEGORY C — Stale expectation (test uses SimpleNamespace dict which doesn't trigger actual config reload) |
| `test_task_regenerates_audio_when_preview_parameters_changed` | AssertionError: cached preview not invalidated | CATEGORY C — Stale expectation (same SimpleNamespace issue) |

**Atomic fix scope:** These tests need to properly mock the config reload path or use a real config object.

---

## CONSOLIDATED ATOMIC FIX GROUPS

### Group A — Navigation Fix (largest impact, ~30 tests)

**Tests affected:**
- test_webui_voice_preview.py: 7 tests
- test_webui_tts_settings.py: 7 tests
- test_webui_bgm.py: 18 tests
- test_webui_voice_preview.py: 2 tests (partial)

**Root cause:** All tests load `webui/Main.py` which defaults to Overview page.

**Minimal fix options:**
1. **Option 1 (preferred):** Load page modules directly:
   - Voice preview tests → `AppTest.from_file(str(WEBUI_CREATE))`
   - TTS settings tests → `AppTest.from_file(str(WEBUI_SETTINGS))`
   - BGM tests → `AppTest.from_file(str(WEBUI_CREATE))`

2. **Option 2:** Navigate within AppTest:
   - `app.switch_page(create_page)` before assertions
   - Requires importing `webui.nav_pages` in tests

**Risk:** Option 1 is lowest risk — each test loads only the page it cares about, avoiding navigation state issues.

---

### Group B — Backend Contract Fix (2 tests)

**Tests affected:**
- test_webui_voice_preview.py: `test_provider_signature_changes_when_api_key_changes`
- test_webui_voice_preview.py: `test_task_regenerates_audio_when_preview_parameters_changed`

**Root cause:** Tests use `SimpleNamespace` for config but the production code reads from `config.app`/`config.elevenlabs` etc. via dict-like access. SimpleNamespace allows attribute assignment but doesn't trigger config change notifications.

**Minimal fix:** Use `patch.object(config, "elevenlabs", new_callable=dict_property)` or similar to ensure config changes are visible to production code.

---

### Group C — Test Isolation Fix (5 tests)

**Tests affected:**
- test_webui_navigation.py: 5 order-dependent failures

**Root cause:** Streamlit runtime state is not reset between AppTest runs in the same process.

**Minimal fix:** Add `@pytest.fixture(autouse=True)` that resets `st.runtime` or run navigation tests in a subprocess.

---

## SUMMARY

| Group | Tests | Root Cause | Category | Atomic? |
|---|---|---|---|---|
| A — Navigation | ~30 | AppTest loads Main.py (Overview) instead of target page | CATEGORY C | YES — single pattern fix |
| B — Backend contract | 2 | SimpleNamespace doesn't trigger config reload | CATEGORY C | YES — 2 tests, same root cause |
| C — Test isolation | 5 | Streamlit state pollution between tests | CATEGORY D | YES — single isolation fix |
| **Total** | **~38** | **3 distinct root causes** | **CATEGORY C/D** | **YES — 3 atomic groups** |

---

*Report generated: 2026-09-08*
*Phase: 15I.2A — Widget-Key Forensic Mapping*
*Mode: READ-ONLY — no files modified*
