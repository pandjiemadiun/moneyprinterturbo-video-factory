# DEFECT REPORT — Discover Trend Analysis Runtime Failure
**Defect ID:** PHASE15H-DF-001
**Severity:** HIGH — Production functional failure
**Status:** FIXED AND VERIFIED
**Date:** 2026-09-03

---

## 1. USER-VISIBLE SYMPTOM

On the Discover page, clicking "Fetch Live Trends" or "Analyze Your Own Topic" displays:

```
Analysis Failed: [Errno -2] Name or service not known
```

This prevents all trend-analysis functionality in the Discover page.

---

## 2. EXACT FAILING HOSTNAME

`moneyprinterturbo-api:8080`

The WebUI container attempts to resolve the Docker container name `moneyprinterturbo-api` via Docker DNS, but resolution fails with `[Errno -2] Name or service not known`.

---

## 3. FULL EXECUTION PATH

```
User clicks "Fetch Live Trends" on Discover page
  → webui/pages/discover.py (handler)
    → webui_api_client.api_content_intelligence_analyze()
      → _get_api_base_url() returns "http://moneyprinterturbo-api:8080"
        → httpx.post("http://moneyprinterturbo-api:8080/api/v1/content-intelligence/analyze")
          → socket.getaddrinfo("moneyprinterturbo-api", 8080)
            → [Errno -2] Name or service not known
```

Also affects:
- `api_list_tasks()` — called on every page render to load task list
- `api_content_intelligence_analyze()` — called for trend analysis

---

## 4. ROOT CAUSE

**Category: Docker service hostname unavailable (C)**

The WebUI container (`moneyprinterturbo-webui`) was deployed on the `bridge` network, while the API container (`moneyprinterturbo-api`) was deployed on the `mpt-network`. Docker DNS only resolves container names within the same network. Since the WebUI container was not connected to `mpt-network`, it could not resolve `moneyprinterturbo-api`.

**Evidence:**
- `docker inspect moneyprinterturbo-webui` — NetworkMode: `bridge`
- `docker inspect moneyprinterturbo-api` — NetworkMode: `mpt-network`
- `docker exec moneyprinterturbo-webui python3 -c "import socket; socket.getaddrinfo('moneyprinterturbo-api', 8080)"` — `socket.gaierror: [Errno -2] Name or service not known`
- `docker network connect mpt-network moneyprinterturbo-webui` — DNS resolution succeeds immediately
- `docker exec moneyprinterturbo-webui curl http://moneyprinterturbo-api:8080/api/v1/tasks` — returns 200

**Source of misconfiguration:**
`docker-compose.release.yml` — the `webui` service was missing the `networks: - mpt-network` declaration, while the `api` service had it.

---

## 5. WHY PREVIOUS TESTS DID NOT CATCH THIS

1. **Unit tests mock the API client** — `test_webui_navigation.py` uses `webui_api_client` but does not test actual network connectivity.
2. **Local development uses `docker-compose.yml`** — in the default compose file, both services share the default `bridge` network, so container name resolution works.
3. **Production deployment uses `docker-compose.release.yml`** — this file has the network misconfiguration that only manifests in production.
4. **No integration test for container-to-container DNS** — the test suite does not verify that the WebUI can resolve the API container hostname.

---

## 6. SIBLING SEARCH RESULTS

Searched the entire canonical codebase for similar Docker service hostname/endpoint patterns:

| Pattern | Location | Classification |
|---|---|---|
| `moneyprinterturbo-api:8080` (default `MPT_API_BASE_URL`) | `app/services/webui_api_client.py:19` | **SAME DEFECT** — fixed by network config |
| `http://127.0.0.1:4123/v1` (Chatterbox) | `webui/shared.py:76` | NOT APPLICABLE — local service, configurable |
| `https://api.wavespeed.ai/api/v3` | `app/services/material.py:1077` | NOT APPLICABLE — external API |
| `https://api.upload-post.com` | `app/services/upload_post.py:15` | NOT APPLICABLE — external API |
| `localhost` (Redis) | `app/services/state.py:114` | NOT APPLICABLE — API-internal, not WebUI |
| `host.docker.internal` | `app/config/config.py:18` | NOT APPLICABLE — host gateway, intentional |

**Only one sibling with the same defect class: the `webui_api_client.py` default URL, which is now resolved by the network fix.**

---

## 7. EXACT FIX

**File:** `docker-compose.release.yml`

**Change:** Added `networks: - mpt-network` to the `webui` service definition.

**Before:**
```yaml
services:
  webui:
    image: ghcr.io/harry0703/moneyprinterturbo:latest
    container_name: "moneyprinterturbo-webui"
    ports:
      - "127.0.0.1:8501:8501"
    command: [ "streamlit", "run", ... ]
    volumes: *common-volumes
    restart: always
    # MISSING: networks: - mpt-network
```

**After:**
```yaml
services:
  webui:
    image: ghcr.io/harry0703/moneyprinterturbo:latest
    container_name: "moneyprinterturbo-webui"
    ports:
      - "127.0.0.1:8501:8501"
    command: [ "streamlit", "run", ... ]
    volumes: *common-volumes
    restart: always
    networks:
      - mpt-network
```

**Runtime fix applied:** Connected the running WebUI container to `mpt-network`:
```bash
docker network connect mpt-network moneyprinterturbo-webui
```

---

## 8. TESTS ADDED/UPDATED

No new tests added. Existing test suite (`test/test_webui_navigation.py`) passes (41/41).

**Recommended regression guardrail (not yet implemented):**
- Add an integration test that verifies the WebUI container can resolve `moneyprinterturbo-api` via Docker DNS when deployed with `docker-compose.release.yml`.

---

## 9. REAL PRODUCTION BROWSER VERIFICATION

After fixing the network configuration:

1. Opened `https://goldtrader.website/render_discover`
2. Clicked "Fetch Live Trends"
3. **Result:** Analysis completed successfully, trends displayed
4. **No `[Errno -2]` error**

Container logs confirm:
- `api_content_intelligence_analyze` no longer logs errors
- `api_list_tasks` no longer logs errors
- Content Intelligence API returns 200 with trend data

---

## 10. PRODUCTION IDENTITY VERIFICATION

| Check | Result |
|---|---|
| Canonical repo | `/root/moneyprinterturbo-video-factory` |
| HEAD | `b0de54c4dae16eecc6fd867c6cbd219a54694fd1` |
| Deployed image | `mpt-webui:15H-b0de54c` |
| Container git-sha | `b0de54c` == HEAD |
| Production domain | `goldtrader.website` → `127.0.0.1:8501` |
| Runtime Main.py sha256 | Matches committed blob |

---

## 11. DATA INVARIANTS VERIFICATION

- Production storage: 473 mp4 / 7.3G in `/opt/MoneyPrinterTurbo/storage/`
- Config unchanged: `config.toml` sha256 matches
- No production data modified
- No database schema changes
- No engine behavior modifications

---

## 12. DISTINCTION FROM PHASE 15H RESPONSIVE AUDIT

This defect is a **separate functional failure** discovered after the Phase 15H responsive/layout verification was complete.

- **Phase 15H scope:** Responsive layout, interaction usability, viewport matrix, button geometry, navigation flows
- **This defect scope:** Docker network configuration causing DNS resolution failure between WebUI and API containers

The Phase 15H responsive verification remains valid. This is a new infrastructure/configuration defect that was not visible during UI-only testing.

---

## 13. HONEST LIMITATIONS

- The integration test for container-to-container DNS resolution was not in the existing test suite and was not added during this fix cycle.
- The fix was applied at the infrastructure level (Docker network) rather than at the application level. A more resilient application could try multiple hostnames or fallback addresses.
- The `docker-compose.release.yml` fix will only take effect on next deployment. The running container was fixed via `docker network connect`.

---

*Defect report generated per PO mandate. Defect is fixed and verified in production.*
