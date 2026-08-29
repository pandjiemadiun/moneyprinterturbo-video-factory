# YOUTUBE MISSING IN RUNNING WEBUI — ROOT CAUSE AUDIT

**Date:** 2026-08-29
**Finding:** DEPLOYMENT/VERSION MISMATCH (confirmed)
**Source modifications during this audit:** 0

---

## 1. EXECUTIVE SUMMARY

YouTube is missing from the running WebUI because **the deployed containers are running images built BEFORE the Phase 11B/11C/11D/11E changes were committed**. The source code changes exist only in the local git repository — they have NOT been built into a Docker image and deployed.

**Root cause:** The running containers use `docker-compose.release.yml` which pulls pre-built images from GHCR and does NOT mount the local source code. The local `docker-compose.yml` (which builds from `./` and mounts source) is NOT what's running.

---

## 2. EVIDENCE

### 2.1 Running Containers

| Container | Image | Created | Has Phase 11? |
|---|---|---|---|
| `moneyprinterturbo-webui` | `ghcr.io/harry0703/moneyprinterturbo:latest` | 5 days ago | **NO** |
| `moneyprinterturbo-api` | `mpt-factory-10k:latest` | 10 hours ago (14:56 UTC) | **NO** |
| `mpt-7b-9090` | `ghcr.io/harry0703/moneyprinterturbo:latest` | 5 days ago | **NO** |

### 2.2 Source Code vs Deployed Images

| Component | Local Source (git HEAD) | API Container (mpt-factory-10k) | WebUI Container (ghcr) |
|---|---|---|---|
| YouTube in WebUI dropdown | YES (Phase 11B) | NO | NO |
| YouTube help text | YES (Phase 11C) | NO | NO |
| Thumbnail pipeline | YES (Phase 11D) | NO | NO |
| Batch service | YES (Phase 11E) | NO | NO |
| Phase 11 docs | YES (6 commits) | NO | NO |

### 2.3 Timeline Proof

```
2026-08-28 14:56 UTC → mpt-factory-10k:latest image built (Phase 10K only)
2026-08-28 16:07 UTC → Phase 11A commit (95b39b5)
2026-08-28 16:35 UTC → Phase 11B commit (b3b1d3c) ← YouTube added
2026-08-28 16:52 UTC → Phase 11C commit (d3b9ab6) ← YouTube UX
2026-08-28 17:14 UTC → Phase 11D commit (0d3c55c) ← Thumbnails
2026-08-28 17:31 UTC → Phase 11E commit (931450f) ← Batch service
```

The image was built at 14:56 UTC — **all Phase 11 commits came AFTER** (16:07-17:31 UTC).

### 2.4 Deployment Configuration

**Active configuration** (`docker-compose.release.yml`):
```yaml
services:
  webui:
    image: ghcr.io/harry0703/moneyprinterturbo:latest  # ← Pre-built image
    volumes:
      - ./config.toml:/MoneyPrinterTurbo/config.toml   # ← Only config
      - ./storage:/MoneyPrinterTurbo/storage           # ← Only storage
      # ← NO source code mount!
```

**Inactive configuration** (`docker-compose.yml`):
```yaml
services:
  webui:
    build:
      context: .                   # ← Would build from local source
      dockerfile: Dockerfile
    volumes:
      - ./:/MoneyPrinterTurbo      # ← Would mount local source
```

---

## 3. ROOT CAUSE CHAIN

```
Phase 11 changes committed to git (16:07-17:31 UTC)
    ↓
NOT built into new Docker image
    ↓
NOT deployed to running containers
    ↓
Running containers still use old images (14:56 UTC or 5 days ago)
    ↓
YouTube/thumbnails/batch NOT visible in WebUI
```

---

## 4. VERIFICATION COMMANDS

```bash
# Verify local source has YouTube
grep "YouTube" /root/moneyprinterturbo-video-factory/webui/Main.py
# → Found: (tr("YouTube"), "youtube")

# Verify deployed WebUI does NOT have YouTube
docker exec moneyprinterturbo-webui grep "YouTube" /MoneyPrinterTurbo/webui/Main.py
# → NOT FOUND

# Verify deployed API does NOT have YouTube in WebUI
docker exec moneyprinterturbo-api grep "YouTube" /MoneyPrinterTurbo/webui/Main.py
# → NOT FOUND

# Verify image build time vs commit times
docker inspect mpt-factory-10k:latest | grep Created
# → 2026-08-28T14:56:50 UTC (BEFORE Phase 11 commits)
```

---

## 5. FIX REQUIRED

To make YouTube (and thumbnails, batch service) visible in the running WebUI:

```bash
cd /root/moneyprinterturbo-video-factory

# Rebuild images from current source
docker compose build

# Restart containers with new images
docker compose up -d
```

This will:
1. Build new images from the current local source (with Phase 11B-11E changes)
2. Restart containers with the new images
3. YouTube will appear in the source dropdown
4. Thumbnail generation will work
5. Batch service will be available

---

## 6. ADDITIONAL FINDINGS

### 6.1 API Container Also Missing Changes
The API container (`mpt-factory-10k:latest`) was built 10 hours ago but still BEFORE Phase 11 commits. It also needs rebuild.

### 6.2 No Source Volume Mount
The `docker-compose.release.yml` only mounts `config.toml` and `storage`. It does NOT mount `./:/MoneyPrinterTurbo`. This means even if local source changes, running containers won't pick them up without rebuild.

### 6.3 Third Container
There's a third container `mpt-7b-9090` (port 8090) also using the old GHCR image — likely another instance.

---

## 7. SAFETY NOTES

- This audit did NOT modify any source code
- This audit did NOT modify any Docker configuration
- This audit did NOT restart any containers
- This audit did NOT mutate any production data
- The fix requires explicit user approval before execution

---

## 8. CLASSIFICATION

**ROOT CAUSE:** Deployment/version mismatch — running containers use images built before Phase 11 commits.

**NOT a code bug.** The source code is correct and complete. The deployment is stale.

**ACTION REQUIRED:** Rebuild and redeploy containers to pick up Phase 11 changes.
