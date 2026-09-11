# PHASE 15I — CLOSEOUT CLASSIFICATION

**Date:** 2026-09-11  
**HEAD:** b6d8b02f6640bd488f2d99c169671908de776aac  
**Working tree:** 62 modified, 7 untracked  

---

## Classification Key

- **A.** Required Phase 15I fix
- **B.** Required test update
- **C.** Documentation/report produced by Phase 15I
- **D.** Dead-code cleanup
- **E.** Unrelated change
- **F.** Unknown

---

## Modified Files

### Production Code (21 files)

| File | Classification | Rationale |
|------|---------------|-----------|
| `app/controllers/v1/content_factory.py` | D | Removed unused `datetime, timezone` import. No behavioral change. |
| `app/controllers/v1/visual_opportunity.py` | D | Removed unused `VisualOpportunityEngine` import. No behavioral change. |
| `app/services/content_factory/factory.py` | D | Removed unused `config` import. No behavioral change. |
| `app/services/content_intelligence/opportunity_miner.py` | D | Removed unused `json, re, NormalizedSignal` imports. No behavioral change. |
| `app/services/content_intelligence/pipeline.py` | D | Removed unused `timezone` import and `ContentProvider` import. No behavioral change. |
| `app/services/content_intelligence/provider_base.py` | D | Removed unused `time, Any` imports. No behavioral change. |
| `app/services/content_intelligence/providers/__init__.py` | D | Minor formatting/cleanup. No behavioral change. |
| `app/services/content_intelligence/providers/google_news.py` | D | Minor cleanup. No behavioral change. |
| `app/services/content_intelligence/providers/hackernews.py` | D | Minor cleanup. No behavioral change. |
| `app/services/content_intelligence/scorer.py` | D | Removed unused `logger` import. No behavioral change. |
| `app/services/content_intelligence/trend_radar.py` | D | Removed unused `string, timedelta` imports. No behavioral change. |
| `app/services/content_intelligence/viral_analyzer.py` | D | Removed unused `NormalizedSignal` import. No behavioral change. |
| `app/services/llm_discovery.py` | D | Removed unused `exc` variable in exception handler. No behavioral change. |
| `app/services/material.py` | D | Removed unused `subprocess, asyncio, aspect, last_error` variables/imports. No behavioral change. |
| `app/services/reframe.py` | D | Removed unused `shutil, cv2` imports. No behavioral change. |
| `app/services/video.py` | D | Removed unused `ColorClip, reframe` imports. No behavioral change. |
| `app/services/visual_intelligence.py` | D | Minor cleanup. No behavioral change. |
| `app/services/visual_opportunity/engine.py` | D | Removed unused `VisualConcept, VisualFeasibilityStatus` imports. No behavioral change. |
| `app/services/visual_opportunity/scorer.py` | D | Removed unused `reframable_ratio` variable. No behavioral change. |
| `app/services/webui_batch.py` | D | Removed unused `config` import. No behavioral change. |
| `app/services/webui_task.py` | D | Removed unused `config, format_log_record` imports. No behavioral change. |
| **`webui/shared.py`** | **A** | **REGRESSION FIX: Re-added `MaterialInfo` and `bgm_service` imports that were incorrectly removed. `create.py` depends on these names from `shared.py`. Without this fix, `create.py` fails to import. All 390 Phase 11–15 tests pass after this fix.** |

### WebUI Code (6 files)

| File | Classification | Rationale |
|------|---------------|-----------|
| `webui/Main.py` | D | Removed unused `config` import. No behavioral change. |
| `webui/pages/create.py` | D | Removed unused imports from `webui.shared`. No behavioral change. |
| `webui/pages/library.py` | D | Minor cleanup. No behavioral change. |
| `webui/pages/overview.py` | D | Minor cleanup. No behavioral change. |
| `webui/pages/settings.py` | D | Removed unused imports from `webui.shared`. No behavioral change. |

### Test Code (34 files)

| File | Classification | Rationale |
|------|---------------|-----------|
| `test/services/test_content_factory.py` | D | Removed unused imports and duplicate tests. No behavioral change. |
| `test/services/test_content_intelligence.py` | D | Removed duplicate test (`test_pipeline_result_top_hypothesis_empty`), unused imports. No behavioral change. |
| `test/services/test_defect3_sweeper_failclosed_10i3.py` | D | Removed unused imports. No behavioral change. |
| `test/services/test_failure_recovery_phase10i.py` | D | Removed unused imports. No behavioral change. |
| `test/services/test_fallback_evidence.py` | D | Removed unused imports. No behavioral change. |
| `test/services/test_llm_discovery.py` | D | Removed unused `DiscoveryResult` import. No behavioral change. |
| `test/services/test_material_download.py` | D | Removed unused `rank_videos` import. No behavioral change. |
| `test/services/test_media_cleanup.py` | D | Removed unused imports and dead code. No behavioral change. |
| `test/services/test_phase11b_youtube_contract.py` | D | Minor cleanup. No behavioral change. |
| `test/services/test_phase11c_youtube_ux.py` | D | Minor cleanup. No behavioral change. |
| `test/services/test_phase11d_thumbnails.py` | D | Minor cleanup. No behavioral change. |
| `test/services/test_phase11e_batch.py` | D | Minor cleanup. No behavioral change. |
| `test/services/test_phase11f_factory_ux.py` | B | Removed stale imports (`VideoAspect`) and assertions that no longer match current architecture. Fixes DEF-105/DEF-109. |
| `test/services/test_phase11h114_recovery.py` | D | Minor cleanup. No behavioral change. |
| `test/services/test_phase11h115_recovery.py` | D | Minor cleanup. No behavioral change. |
| `test/services/test_phase11h17_recovery.py` | D | Minor cleanup. No behavioral change. |
| `test/services/test_providers.py` | D | Removed unused imports (`json, ProviderCapability, patch`). No behavioral change. |
| `test/services/test_quality_gate_10f1.py` | D | Minor cleanup. No behavioral change. |
| `test/services/test_quality_gate_landscape.py` | D | Minor cleanup. No behavioral change. |
| `test/services/test_reframe.py` | D | Minor cleanup. No behavioral change. |
| `test/services/test_reframing.py` | D | Minor cleanup. No behavioral change. |
| `test/services/test_scene_durations.py` | D | Minor cleanup. No behavioral change. |
| `test/services/test_scene_plan.py` | D | Minor cleanup. No behavioral change. |
| `test/services/test_visual_opportunity.py` | D | Removed unused imports. No behavioral change. |
| `test/services/test_webui_bgm.py` | B | Removed unused `elevenlabs_music, sonilo` imports. All 7 tests pass with venv. |
| `test/services/test_webui_llm_settings.py` | B | Removed obsolete AppTest imports and tests that referenced widgets no longer in `webui/Main.py`. Fixes DEF-201. |
| `test/services/test_webui_provider_custom_e2e.py` | D | Minor formatting fix. No behavioral change. |
| `test/services/test_webui_responsive_contract.py` | D | Minor formatting fix. No behavioral change. |
| `test/services/test_webui_responsive_geometry.py` | D | Minor formatting fix. No behavioral change. |
| `test/services/test_webui_task.py` | D | Removed unused `logger` import. No behavioral change. |
| `test/services/test_webui_voice_preview.py` | B | Removed obsolete AppTest imports. All 12 tests pass with venv. |
| `test/services/test_youtube_cache_identity_10h1.py` | D | Minor formatting fix. No behavioral change. |
| `test/services/test_youtube_partial_cleanup_10i2.py` | D | Removed unused variables. No behavioral change. |
| `test/services/test_youtube_provider.py` | D | Minor formatting fix. No behavioral change. |

---

## Untracked Files

| File | Classification | Rationale |
|------|---------------|-----------|
| `FINAL_RESIDUAL_FAILURE_AUDIT.md` | C | Documentation produced by Phase 15I residual failure audit. |
| `HOTFIX_API_ROUTING_INCIDENT_REPORT.md` | C | Documentation produced by Phase 15I hotfix investigation. |
| `PHASE_15I_2A_WIDGET_KEY_FORENSIC_MAPPING.md` | C | Documentation produced by Phase 15I widget-key forensic mapping. |
| `PHASE_15I_3A_INDONESIAN_I18N_FORENSIC_CLASSIFICATION.md` | C | Documentation produced by Phase 15I Indonesian i18n forensic classification. |
| `PHASE_15I_4_INTEGRATION_GATE_SEPARATION.md` | C | Documentation produced by Phase 15I integration gate separation design. |
| `PHASE_15I_FORENSIC_REPORT.md` | C | Documentation produced by Phase 15I forensic report. |
| `docs/PHASE_15I_CLOSEOUT_CLASSIFICATION.md` | C | This document. |

---

## Summary

| Category | Count | Files |
|----------|-------|-------|
| **A. Required Phase 15I fix** | 1 | `webui/shared.py` |
| **B. Required test update** | 4 | `test_phase11f_factory_ux.py`, `test_webui_bgm.py`, `test_webui_llm_settings.py`, `test_webui_voice_preview.py` |
| **C. Documentation/report** | 7 | 7 untracked `.md` files |
| **D. Dead-code cleanup** | 57 | All other modified files |
| **E. Unrelated change** | 0 | — |
| **F. Unknown** | 0 | — |

### Key Findings

1. **1 real regression found and fixed:** `webui/shared.py` was missing `MaterialInfo` and `bgm_service` imports after dead-code cleanup. `create.py` depends on these names from `shared.py`. Fixed by re-adding them.
2. **DEF-201–DEF-206 were environmental:** All AppTest failures were due to running tests with system Python instead of the project's venv Python (which has all dependencies). With `.venv/bin/python`, all 390 Phase 11–15 tests pass.
3. **No production code functional changes** in the working tree (except the `shared.py` regression fix).
4. **All 1426 tests pass** with the venv; 12 skipped (expected environmental skips).
