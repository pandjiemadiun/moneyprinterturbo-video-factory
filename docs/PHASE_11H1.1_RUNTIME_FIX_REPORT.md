# PHASE 11H.1.1 — RUNTIME FIX REPORT

**Status:** PASS
**Date:** 2026-08-29

---

## 1. PRE-DEPLOYMENT INVARIANTS

| Invariant | Value |
|---|---|
| Git HEAD | 3c1a1b5c6a74cbe892eb62d475f3cddb2a10154e |
| Factory DB SHA256 | 397baba627d4223b29851b34d28dc59a92e363cd50b010db915e7f86aa09e7b9 |
| Factory DB size | 155648 |
| MPT DB SHA256 | ad0e6df9d5a45438532c0c99655455448e8c791bd5781711bf1f4f111a5d59a1 |
| MPT DB size | 151552 |
| Config SHA256 | e8634227e57f0b362c9792f785685e5f4e399e73a5ea328a8ef422e025f8591f |
| MP4 count | 158 |
| Task directories | 136 |
| Cache files | 0 |
| Old container ID | 3e92e1e74fe6 |

---

## 2. IMAGE BUILD

```
docker build -t mpt-factory-11h1:latest /root/mpt-factoryturbo-video-factory

Result: SUCCESS
Image: mpt-factory-11h1:latest (f33213d38b6)
Build time: ~30 seconds
```

### Source Verification (inside image)

| Check | Result |
|---|---|
| `_render_videos_view` present | YES (2 references) |
| `_render_jobs_view` present | YES |
| `_render_create_view` present | YES |
| `Nav Create` i18n key | YES |
| YouTube provider | YES |

---

## 3. DEPLOYMENT

### Old Container

```
docker stop moneyprinterturbo-webui && docker rm moneyprinterturbo-webui
Result: REMOVED
```

### New Container

```
docker run -d \
  --name moneyprinterturbo-webui \
  --restart always \
  -p 8501:8501 \
  -v /opt/MoneyPrinterTurbo/config.toml:/MoneyPrinterTurbo/config.toml \
  -v /opt/MoneyPrinterTurbo/storage:/MoneyPrinterTurbo/storage \
  mpt-factory-11h1:latest \
  streamlit run ./webui/Main.py \
  --server.address=0.0.0.0 \
  --server.port=8501 \
  --browser.serverAddress=https://goldtrader.website \
  --server.enableCORS=True \
  --browser.gatherUsageStats=False \
  --client.toolbarMode=minimal \
  --logger.hideWelcomeMessage=True \
  --server.showEmailPrompt=False

Result: SUCCESS
Container ID: c8b8c23f00a4
Image: mpt-factory-11h1:latest
Port: 0.0.0.0:8501->8501/tcp
```

---

## 4. RUNTIME VERIFICATION

### Container Health

| Property | Value |
|---|---|
| State | running |
| ExitCode | 0 |
| RestartCount | 0 |
| Uptime | 18 seconds → stable |

### Local Access

```
curl http://127.0.0.1:8501/
HTTP 200 Time 0.005790s
```

### External Access

```
curl http://95.111.192.237:8501/
HTTP 200 Time 0.001981s
```

**FIXED:** External access now returns HTTP 200.

### Services Status

| Service | Endpoint | Status |
|---|---|---|
| MPT WebUI | 127.0.0.1:8501 | HTTP 200 |
| MPT WebUI | 95.111.192.237:8501 | HTTP 200 |
| MPT API | 127.0.0.1:8080/ping | "pong" |
| Factory | 127.0.0.1:8000/health | "ok" |

---

## 5. SOURCE VERIFICATION (RUNNING CONTAINER)

| Check | Command | Result |
|---|---|---|
| Has _render_videos_view | `docker exec moneyprinterturbo-webui grep -c "_render_videos_view" /MoneyPrinterTurbo/webui/Main.py` | 2 |
| Has Nav Create | `docker exec moneyprinterturbo-webui grep "Nav Create" /MoneyPrinterTurbo/webui/i18n/en.json` | YES |

**VERIFIED:** Running container has Phase 11H.1 changes.

---

## 6. PRODUCTION INVARIANTS (AFTER)

| Invariant | BEFORE | AFTER | Status |
|---|---|---|---|
| Factory DB SHA256 | 397baba6... | 397baba6... | IDENTICAL |
| Factory DB size | 155648 | 155648 | IDENTICAL |
| MPT DB SHA256 | ad0e6df9... | ad0e6df9... | IDENTICAL |
| MPT DB size | 151552 | 151552 | IDENTICAL |
| Config SHA256 | e863422... | e863422... | IDENTICAL |
| MP4 count | 158 | 158 | IDENTICAL |
| Task directories | 136 | 136 | IDENTICAL |
| Cache files | 0 | 0 | IDENTICAL |
| API health | pong | pong | OK |
| Factory health | ok | ok | OK |

---

## 7. IPTABLES DNAT RULE

The existing DNAT rule was NOT removed:

```
DNAT tcp -- 0.0.0.0/0 127.0.0.1 tcp dpt:8501 to:172.17.0.3:8501
```

**Reason:** The corrected Docker port binding (`0.0.0.0:8501->8501`) handles external traffic directly. The DNAT rule is now obsolete but harmless. Per instructions, firewall rules were left untouched since the fix works without modification.

---

## 8. CLASSIFICATION

| Level | Status |
|---|---|
| SOURCE VERIFIED | YES — Phase 11H.1 code in running container |
| RUNTIME VERIFIED | YES — Container running, ExitCode=0, RestartCount=0 |
| EXTERNAL ACCESS VERIFIED | YES — HTTP 200 from 95.111.192.237:8501 |

---

## 9. FINAL ARCHITECTURE

```
USER
  ↓
http://95.111.192.237:8501 (MPT Content Factory UI)
  ↓
MPT WebUI container (mpt-factory-11h1:latest, port 0.0.0.0:8501)
  ↓
MPT API container (port 127.0.0.1:8080, internal)
  ↓
ARTIFACTS (storage/tasks/, cache_videos/)
```

---

## PHASE 11H.1.1 CLASSIFICATION

**PASS**

---

## FINAL STATUS

| Component | Status |
|---|---|
| PRIMARY ROOT CAUSE | FIXED — Port binding changed to 0.0.0.0 |
| SECONDARY ISSUE | FIXED — New image with Phase 11H.1 code |
| LOCAL ACCESS | HTTP 200 |
| EXTERNAL ACCESS | HTTP 200 |
| CONTAINER HEALTH | running, ExitCode=0, RestartCount=0 |
| API | healthy |
| FACTORY | healthy |
| PRODUCTION DATA | unchanged |

**PHASE 11H.1 IS NOW UNBLOCKED.**

NEXT: Human UI verification → Factory decommission → Phase 11H.2
