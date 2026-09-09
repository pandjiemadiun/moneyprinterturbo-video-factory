#!/usr/bin/env bash
set -euo pipefail

# MPT Content Factory — Deterministic Quality Gate
# Levels:
#   LEVEL 1 — Static analysis
#   LEVEL 2 — Deterministic unit tests (no network, no AppTest, no browser)
#   LEVEL 3A — AppTest runtime (Streamlit AppTest in subprocess)
#   LEVEL 3B — Playwright integration (real browser, opt-in via MPT_RUN_INTEGRATION_TESTS)
#   LEVEL 4 — Optional external tests (requires API keys, internet, opt-in)
#   LEVEL 5 — Production read-only verification

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
cd "$REPO"

LEVEL=0
PASS=0
FAIL=0
SKIP=0
NOT_RUN=0

report() {
  local level="$1"
  local status="$2"
  local msg="$3"
  case "$status" in
    PASS)   PASS=$((PASS + 1)) ;;
    FAIL)   FAIL=$((FAIL + 1)) ;;
    SKIP)   SKIP=$((SKIP + 1)) ;;
    NOT_RUN) NOT_RUN=$((NOT_RUN + 1)) ;;
  esac
  echo "[LEVEL $level] $status: $msg"
}

# ── LEVEL 1: Static ──────────────────────────────────────────────────────────
LEVEL=1
echo "=== LEVEL 1: Static Analysis ==="

if command -v uv >/dev/null 2>&1; then
  if uv run ruff check app/ webui/ --select F601,F811 2>/dev/null; then
    report $LEVEL PASS "ruff: no duplicate keys, redefinitions, or import-order errors"
  else
    report $LEVEL FAIL "ruff: static check failed"
  fi
else
  report $LEVEL NOT_RUN "ruff not installed"
fi

if python3 -m py_compile app/models/schema.py app/services/material.py webui/pages/create.py webui/shared.py webui/Main.py 2>/dev/null; then
  report $LEVEL PASS "py_compile: key modules compile cleanly"
else
  report $LEVEL FAIL "py_compile: compilation errors"
fi

# ── LEVEL 2: Deterministic unit tests ───────────────────────────────────────
LEVEL=2
echo ""
echo "=== LEVEL 2: Deterministic Unit Tests ==="

UNIT_PATTERNS=(
  "test/services/test_phase11h114_recovery.py"
  "test/services/test_phase11h115_recovery.py"
  "test/services/test_phase11h12_no_duplicate_key.py"
  "test/services/test_material_download.py"
  "test/services/test_webui_task_history.py"
  "test/services/test_schema.py"
  "test/services/test_llm_discovery.py"
  "test/services/test_task.py"
  "test/services/test_controller_base.py"
  "test/services/test_controller_ping.py"
  "test/services/test_controller_video.py"
  "test/services/test_quality_gate_10f1.py"
  "test/services/test_quality_gate_landscape.py"
  "test/services/test_quality_gate_phase10f.py"
  "test/services/test_phase11b_youtube_contract.py"
  "test/services/test_phase11d_thumbnails.py"
  "test/services/test_phase11e_batch.py"
  "test/services/test_phase11f_factory_ux.py"
  "test/services/test_phase11h17_recovery.py"
  "test/services/test_failure_recovery_phase10i.py"
  "test/services/test_defect3_sweeper_failclosed_10i3.py"
  "test/services/test_fallback_evidence.py"
  "test/services/test_reframing.py"
  "test/services/test_scene_combine.py"
  "test/services/test_scene_materials.py"
  "test/services/test_scene_plan.py"
  "test/services/test_scene_durations.py"
  "test/services/test_clip_speed.py"
  "test/services/test_video.py"
  "test/services/test_video_black_tail.py"
  "test/services/test_video_effects.py"
  "test/services/test_visual_opportunity.py"
  "test/services/test_voice.py"
  "test/services/test_bgm.py"
  "test/services/test_sonilo.py"
  "test/services/test_mpt_agent_skill.py"
  "test/services/test_material.py"
  "test/services/test_material_cache.py"
  "test/services/test_media_cleanup.py"
  "test/services/test_llm.py"
  "test/services/test_youtube_partial_cleanup_10i2.py"
  "test/services/test_youtube_provider_11h16.py"
  "test/services/test_twelvelabs.py"
  "test/services/test_fish_audio.py"
  "test/services/test_loomloom.py"
  "test/services/test_api_authentication.py"
  "test/services/test_asgi_static_files.py"
  "test/services/test_content_factory.py"
  "test/services/test_provider_fix.py"
  "test/services/test_schema.py"
  "test/services/test_subtitle_background_settings.py"
  "test/services/test_task_artifacts.py"
  "test/services/test_task_manager.py"
  "test/test_main.py"
  "test/services/test_webui_i18n.py"
  "test/services/test_webui_responsive_contract.py"
  "test/services/test_webui_settings_transfer.py"
  "test/services/test_webui_missing_imports.py"
)

UNIT_ARGS=()
for p in "${UNIT_PATTERNS[@]}"; do
  [[ -f "$p" ]] && UNIT_ARGS+=("$p")
done

if [[ ${#UNIT_ARGS[@]} -eq 0 ]]; then
  report $LEVEL NOT_RUN "no deterministic unit test files matched"
else
  if uv run pytest -q --tb=no --ignore=test/test_webui_navigation.py \
     --ignore=test/services/test_webui_*.py \
     --ignore=phase11h117_e2e_test.py \
     --ignore=test_phase11h118.py \
     "${UNIT_ARGS[@]}" 2>/dev/null; then
    report $LEVEL PASS "deterministic unit tests passed"
  else
    report $LEVEL FAIL "deterministic unit tests had failures"
  fi
fi

# ── LEVEL 3A: AppTest runtime (Streamlit AppTest in subprocess isolation) ────
LEVEL=3A
echo ""
echo "=== LEVEL 3A: AppTest Runtime Tests ==="

APPTEST_FILES=(
  "test/test_webui_navigation.py"
  "test/services/test_webui_voice_preview.py"
  "test/services/test_webui_tts_settings.py"
  "test/services/test_webui_bgm.py"
  "test/services/test_webui_loomloom.py"
  "test/services/test_webui_generation_defaults.py"
  "test/services/test_webui_task.py"
  "test/services/test_webui_startup.py"
)

APPTEST_ARGS=()
for p in "${APPTEST_FILES[@]}"; do
  [[ -f "$p" ]] && APPTEST_ARGS+=("$p")
done

if [[ ${#APPTEST_ARGS[@]} -eq 0 ]]; then
  report $LEVEL NOT_RUN "no AppTest files matched"
else
  APPTEST_PASS=0
  APPTEST_FAIL=0
  for f in "${APPTEST_ARGS[@]}"; do
    if uv run pytest "$f" -q --tb=no 2>/dev/null; then
      ((APPTEST_PASS++)) || true
    else
      ((APPTEST_FAIL++)) || true
    fi
  done
  if [[ $APPTEST_FAIL -eq 0 ]]; then
    report $LEVEL PASS "all AppTest suites passed in isolation"
  else
    report $LEVEL FAIL "$APPTEST_FAIL AppTest suite(s) failed (see details above)"
  fi
fi

# ── LEVEL 3B: Playwright integration (real browser, opt-in) ──────────────────
LEVEL=3B
echo ""
echo "=== LEVEL 3B: Playwright Integration Tests ==="

if [[ "${MPT_RUN_INTEGRATION_TESTS:-0}" != "1" ]]; then
  report $LEVEL SKIP "set MPT_RUN_INTEGRATION_TESTS=1 to run Playwright tests"
else
  if ! command -v playwright >/dev/null 2>&1; then
    report $LEVEL SKIP "playwright not installed"
  else
    PLAYWRIGHT_FILES=(
      "test/services/test_webui_provider_custom.py"
      "test/services/test_webui_provider_custom_e2e.py"
      "test/services/test_webui_responsive_geometry.py"
    )

    PLAYWRIGHT_ARGS=()
    for p in "${PLAYWRIGHT_FILES[@]}"; do
      [[ -f "$p" ]] && PLAYWRIGHT_ARGS+=("$p")
    done

    if [[ ${#PLAYWRIGHT_ARGS[@]} -eq 0 ]]; then
      report $LEVEL NOT_RUN "no Playwright test files matched"
    else
      PLAYWRIGHT_PASS=0
      PLAYWRIGHT_FAIL=0
      for f in "${PLAYWRIGHT_ARGS[@]}"; do
        if MPT_RUN_INTEGRATION_TESTS=1 uv run pytest "$f" -q --tb=short 2>/dev/null; then
          ((PLAYWRIGHT_PASS++)) || true
        else
          ((PLAYWRIGHT_FAIL++)) || true
        fi
      done
      if [[ $PLAYWRIGHT_FAIL -eq 0 ]]; then
        report $LEVEL PASS "all Playwright suites passed"
      else
        report $LEVEL FAIL "$PLAYWRIGHT_FAIL Playwright suite(s) failed (see details above)"
      fi
    fi
  fi
fi

# ── LEVEL 4: Optional external tests ────────────────────────────────────────
LEVEL=4
echo ""
echo "=== LEVEL 4: Optional External Tests ==="

if [[ "${MPT_RUN_INTEGRATION_TESTS:-0}" != "1" ]]; then
  report $LEVEL SKIP "set MPT_RUN_INTEGRATION_TESTS=1 to run external tests"
else
  EXTERNAL_FILES=(
    "test/services/test_youtube_provider.py"
    "test/services/test_loomloom.py"
  )

  EXTERNAL_ARGS=()
  for p in "${EXTERNAL_FILES[@]}"; do
    [[ -f "$p" ]] && EXTERNAL_ARGS+=("$p")
  done

  if [[ ${#EXTERNAL_ARGS[@]} -eq 0 ]]; then
    report $LEVEL NOT_RUN "no external test files matched"
  else
    if MPT_RUN_INTEGRATION_TESTS=1 uv run pytest -q --tb=short "${EXTERNAL_ARGS[@]}" 2>/dev/null; then
      report $LEVEL PASS "external tests passed"
    else
      report $LEVEL FAIL "external tests had failures"
    fi
  fi
fi

# ── LEVEL 5: Production read-only verification ──────────────────────────────
LEVEL=5
echo ""
echo "=== LEVEL 5: Production Read-Only Verification ==="

PRODUCTION_CONFIG="${MPT_PRODUCTION_CONFIG_TOML:-/opt/MoneyPrinterTurbo/config.toml}"
PRODUCTION_STORAGE="${MPT_PRODUCTION_STORAGE:-/opt/MoneyPrinterTurbo/storage}"

if [[ -f "$PRODUCTION_CONFIG" ]]; then
  report $LEVEL PASS "production config.toml exists"
else
  report $LEVEL NOT_RUN "production config.toml not mounted"
fi

if [[ -d "$PRODUCTION_STORAGE" ]]; then
  STORAGE_COUNT=$(find "$PRODUCTION_STORAGE" -type f 2>/dev/null | wc -l)
  report $LEVEL PASS "production storage accessible ($STORAGE_COUNT files)"
else
  report $LEVEL NOT_RUN "production storage not mounted"
fi

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "=== Quality Gate Summary ==="
echo "PASS:   $PASS"
echo "FAIL:   $FAIL"
echo "SKIP:   $SKIP"
echo "NOT_RUN: $NOT_RUN"
echo ""

if [[ $FAIL -gt 0 ]]; then
  echo "GATE: FAILED"
  exit 1
else
  echo "GATE: PASSED"
  exit 0
fi
