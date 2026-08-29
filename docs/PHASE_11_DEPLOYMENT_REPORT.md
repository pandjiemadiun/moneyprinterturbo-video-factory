# PHASE 11 DEPLOYMENT REPORT

**Status:** PASS
**Date:** 2026-08-29
**Deployment window:** 00:47 - 00:58 UTC

---

## 1. BASELINE

- **Git HEAD:** `6d84fbd844f145852a977c7985eb8c1691704184`
- **Phase 11 commits:** 11A (95b39b5), 11B (b3b1d3c), 11C (d3b9ab6), 11D (0d3c55c), 11E (931450f), audit (6d84fbd)
- **Previous images:** `ghcr.io/harry0703/moneyprinterturbo:latest` (WebUI), `mpt-factory-10k:latest` (API)
- **Previous image age:** 5 days (WebUI), 10 hours (API)

---

## 2. IMAGE BEFORE/AFTER

| | BEFORE | AFTER |
|---|---|---|
| **WebUI image** | `ghcr.io/harry0703/moneyprinterturbo:latest` (0e2eefc01966) | `mpt-factory-11e:latest` (0229057121d9) |
| **API image** | `mpt-factory-10k:latest` (8604104e12d5) | `mpt-factory-11e:latest` (0229057121d9) |
| **Build time** | 5 days ago / 10 hours ago | 2026-08-29 00:52 UTC |
| **Size** | 2.81GB / 3.38GB | 2.82GB (unified) |
| **Phase 11** | NO | YES |

---

## 3. CONTAINER BEFORE/AFTER

### BEFORE

| Container | Image | Ports | Binds | Restart |
|---|---|---|---|---|
| moneyprinterturbo-webui | ghcr.io/harry0703/moneyprinterturbo:latest | 127.0.0.1:8501 | config.toml, storage | always |
| moneyprinterturbo-api | mpt-factory-10k:latest | 127.0.0.1:8080 | config.toml, storage | always |

### AFTER

| Container | Image | Ports | Binds | Restart |
|---|---|---|---|---|
| moneyprinterturbo-webui | mpt-factory-11e:latest | 127.0.0.1:8501 | config.toml, storage | always |
| moneyprinterturbo-api | mpt-factory-11e:latest | 127.0.0.1:8080 | config.toml, storage | always |

**All configuration preserved.** Same ports, same bind mounts, same restart policy.

---

## 4. BUILD RESULT

```
docker build -t mpt-factory-11e:latest -f /root/moneyprinterturbo-video-factory/Dockerfile /root/moneyprinterTurbo-video-factory

Result: SUCCESS
Image: mpt-factory-11e:latest (0229057121d9)
Size: 2.82GB
Build time: ~120 seconds
```

---

## 5. DEPLOYMENT RESULT

```
docker stop moneyprinterturbo-webui moneyprinterturbo-api
docker rm moneyprinterturbo-webui moneyprinterturbo-api
docker run -d --name moneyprinterturbo-webui --restart always -p 127.0.0.1:8501:8501 -v ... mpt-factory-11e:latest streamlit run ./webui/Main.py ...
docker run -d --name moneyprinterturbo-api --restart always -p 127.0.0.1:8080:8080 -v ... mpt-factory-11e:latest python3 main.py

Result: SUCCESS
Both containers running, healthy, exit code 0
```

---

## 6. RUNTIME VERIFICATION

### Phase 10 Features (Protected Core)

| Feature | Status | Evidence |
|---|---|---|
| Phase 10F: Quality gate (_EFFECTIVE_MIN_DIMENSION) | PRESENT | 3 references in material.py |
| Phase 10H.1: Canonical YouTube identity | PRESENT | `_youtube_video_identity` function |
| Phase 10H.2: H.264/AAC format selector | PRESENT | `bestvideo[vcodec^=avc1][ext=mp4][height<=720]` |
| Phase 10I.1/10I.2/10I.3: Cleanup | PRESENT | `cleanup_orphan_cache_videos`, `run_startup_cleanup` |

### Phase 11 Features (New)

| Feature | Status | Evidence |
|---|---|---|
| Phase 11B: YouTube in WebUI dropdown | PRESENT | `(tr("YouTube"), "youtube")` in video_sources |
| Phase 11C: YouTube UX (help, labels, progress) | PRESENT | 10 i18n keys, dynamic labels |
| Phase 11D: Thumbnail pipeline | PRESENT | `generate_thumbnails`, `_extract_thumbnail_frame` |
| Phase 11E: Batch service | PRESENT | `submit_batch`, `get_batch_status` |

### Service Health

| Service | Endpoint | Status |
|---|---|---|
| WebUI | http://127.0.0.1:8501 | HTTP 200 |
| API ping | http://127.0.0.1:8080/ping | "pong" |
| API tasks | http://127.0.0.1:8080/api/v1/tasks | HTTP 200 |

---

## 7. UI VERIFICATION

### YouTube Provider in Running WebUI

```python
# Source inside running container (/MoneyPrinterTurbo/webui/Main.py):
video_sources = [
    (tr("Pexels"), "pexels"),
    (tr("Pixabay"), "pixabay"),
    (tr("Coverr"), "coverr"),
    (tr("YouTube"), "youtube"),    # ← PRESENT
    (tr("WaveSpeed AI Video"), "wavespeed"),
    (tr("Shengsuan Cloud AI Video"), "loomloom"),
    (tr("Local file"), "local"),
]
```

### YouTube i18n Keys in Running WebUI

```
YouTube Help
YouTube Keywords Label
YouTube Keywords Help
YouTube Progress Search
YouTube Progress Download
YouTube Progress Quality
YouTube Error No Results
YouTube Error Quality
YouTube Error Download
YouTube Empty Query
```

---

## 8. TESTS

### Phase 11 Tests

| Test Suite | Result |
|---|---|
| test_phase11b_youtube_contract.py | 9 passed |
| test_phase11c_youtube_ux.py | 9 passed |
| test_phase11d_thumbnails.py | 10 passed |
| test_phase11e_batch.py | 9 passed |

### Regression Tests

| Test Suite | Result |
|---|---|
| test_webui_task.py | 17 passed |
| test_task.py | 55 passed, 3 skipped |
| test_controller_video.py | 26 passed |
| test_schema.py | 4 passed |

**Total: 132 passed, 3 skipped, 0 failures**

---

## 9. PRODUCTION INVARIANTS BEFORE/AFTER

| Invariant | BEFORE | AFTER | Status |
|---|---|---|---|
| factory.db SHA256 | ad0e6df9d5a45438532c0c99655455448e8c791bd5781711bf1f4f111a5d59a1 | ad0e6df9d5a45438532c0c99655455448e8c791bd5781711bf1f4f111a5d59a1 | IDENTICAL |
| factory.db size | 151552 | 151552 | IDENTICAL |
| Task directories | 136 | 136 | IDENTICAL |
| MP4 count | 158 | 158 | IDENTICAL |
| cache_videos files | 0 | 0 | IDENTICAL |
| cache_videos size | 20K | 20K | IDENTICAL |
| Container status | running | running | OK |
| Exit codes | 0 | 0 | OK |
| Bind mounts | config.toml, storage | config.toml, storage | IDENTICAL |
| Ports | 8501, 8080 | 8501, 8080 | IDENTICAL |
| Restart policy | always | always | IDENTICAL |

---

## 10. ROLLBACK PROCEDURE

If rollback is needed:

```bash
# Stop new containers
docker stop moneyprinterturbo-webui moneyprinterturbo-api
docker rm moneyprinterturbo-webui moneyprinterturbo-api

# Recreate with old images
docker run -d --name moneyprinterturbo-webui --restart always -p 127.0.0.1:8501:8501 \
  -v /opt/MoneyPrinterTurbo/config.toml:/MoneyPrinterTurbo/config.toml \
  -v /opt/MoneyPrinterTurbo/storage:/MoneyPrinterTurbo/storage \
  ghcr.io/harry0703/moneyprinterturbo:latest \
  streamlit run ./webui/Main.py --server.address=0.0.0.0 --server.port=8501 \
  --browser.serverAddress=https://goldtrader.website --server.enableCORS=True \
  --browser.gatherUsageStats=False --client.toolbarMode=minimal \
  --logger.hideWelcomeMessage=True --server.showEmailPrompt=False

docker run -d --name moneyprinterturbo-api --restart always -p 127.0.0.1:8080:8080 \
  -v /opt/MoneyPrinterTurbo/config.toml:/MoneyPrinterTurbo/config.toml \
  -v /opt/MoneyPrinterTurbo/storage:/MoneyPrinterTurbo/storage \
  mpt-factory-10k:latest python3 main.py
```

---

## 11. KNOWN ISSUES

| Issue | Severity | Notes |
|---|---|---|
| mpt-7b-9090 still on old image | LOW | Third container not in scope of this deployment |
| Batch UI not yet built | LOW | Service layer ready (11E), UI planned for 11F |

---

## 12. PHASE 11 DEPLOYMENT CLASSIFICATION

**PASS**

Production mutations: 0
Production jobs: 0
YouTube downloads: 0
Source modifications: 0 (deployment only)
Config modifications: 0
Database modifications: 0
Deployment: COMPLETE

Git working tree: CLEAN

Next phase: 11F (not started)
