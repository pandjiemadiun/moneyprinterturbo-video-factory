# PHASE 11H.1.1 — RUNTIME DIAGNOSTIC

**Status:** DIAGNOSIS COMPLETE
**Date:** 2026-08-29

---

## 1. CURRENT DEPLOYMENT

| Container | Image | Status | Ports |
|---|---|---|---|
| moneyprinterturbo-webui | mpt-factory-11e:latest (0229057121d9) | Up 2 hours | 127.0.0.1:8501->8501/tcp |
| moneyprinterturbo-api | mpt-factory-11e:latest (0229057121d9) | Up 2 hours | 127.0.0.1:8080->8080/tcp |
| mpt-7b-9090 | ghcr.io/harry0703/moneyprinterturbo:latest | Up 5 days | 0.0.0.0:8090->8080/tcp |

---

## 2. PORT 8501 STATUS

### Local (WORKS)

```
$ curl http://127.0.0.1:8501/
HTTP 200 Time 0.001713s
```

### External (FAILS)

```
$ curl http://95.111.192.237:8501/
HTTP 000 Time 0.000175s (CONNECTION FAILED)
```

### Binding

```
ss -tlnp | grep 8501
LISTEN 0.0.0.0:8501 127.0.0.1:8501  users:(("docker-proxy",pid=380857))
```

The docker-proxy listens on `127.0.0.1:8501` ONLY. External connections are refused.

---

## 3. IPTABLES DNAT (INEFFECTIVE)

```
DNAT tcp -- 0.0.0.0/0 127.0.0.1 tcp dpt:8501 to:172.17.0.3:8501
```

This DNAT rule attempts to forward external traffic to the container, but it doesn't work because:
- External traffic arrives on the external interface (eth0), not loopback
- The DNAT rule matches destination `127.0.0.1`, but external packets have destination `95.111.192.237`
- Even if redirected, docker-proxy only accepts connections on 127.0.0.1

---

## 4. FIREWALL

```
ufw status: inactive
```

No firewall blocking. The issue is purely the Docker port binding.

---

## 5. CONTAINER HEALTH

| Property | Value |
|---|---|
| State | running |
| ExitCode | 0 |
| RestartCount | 0 |
| Image | mpt-factory-11e:latest (0229057121d9) |
| Image built | 2026-08-29 00:52:08 UTC |

### Logs (last 30 lines)

```
2026-08-29 00:53:15.738 Uvicorn server started on 0.0.0.0:8501
2026-08-29 00:59:50.207 INFO - load config from file: /MoneyPrinterTurbo/config.toml
2026-08-29 00:59:50.208 INFO - MoneyPrinterTurbo v1.3.5
```

Streamlit started successfully. No errors. The app is running correctly internally.

---

## 6. RUNNING SOURCE VERIFICATION

### CRITICAL FINDING: STALE CONTAINER

The running container does NOT have the Phase 11H.1 changes:

```
$ docker exec moneyprinterturbo-webui grep "_render_videos_view" /MoneyPrinterTurbo/webui/Main.py
(no results)
```

| Component | Git HEAD | Container Image | Match? |
|---|---|---|---|
| webui/Main.py | 654239e (Phase 11H.1) | 0229057121d9 (pre-11H.1) | **NO** |
| Navigation | Present | **MISSING** | NO |
| Videos view | Present | **MISSING** | NO |
| Jobs view | Present | **MISSING** | NO |

The image was built at 00:52 UTC, before the Phase 11H.1 commit.

---

## 7. STREAMLIT PORT CONFIG

The container's Streamlit is configured with:
```
--server.address=0.0.0.0 --server.port=8501
```

This is correct — Streamlit listens on all interfaces INSIDE the container. The problem is the Docker port mapping OUTSIDE the container.

---

## 8. API STATUS

```
$ curl http://127.0.0.1:8080/ping
"pong"
```

API is alive and responding locally.

---

## 9. FACTORY STATUS

```
$ curl http://127.0.0.1:8000/health
{"status":"ok","service":"mpt-factory"}
```

Factory is still running at port 8000.

---

## 10. PUBLIC INTERFACE TEST

```
$ curl --max-time 10 -v http://95.111.192.237:8501/
HTTP 000 (CONNECTION FAILED)
```

Confirmed: external access fails.

---

## 11. SERVICE SEPARATION

| Service | Port | Local | External |
|---|---|---|---|
| MPT WebUI | 8501 | HTTP 200 | **CONNECTION REFUSED** |
| MPT API | 8080 | "pong" | **CONNECTION REFUSED** |
| Factory | 8080 | "ok" | Not tested |

---

## 12. ROOT CAUSE CLASSIFICATION

### PRIMARY: C — WebUI running but bound only internally

The Docker port mapping `127.0.0.1:8501->8501/tcp` exposes the port ONLY on localhost. External connections are refused by docker-proxy.

### SECONDARY: E — Stale image/deployment

The running container image (0229057121d9, built 00:52 UTC) predates the Phase 11H.1 changes (committed later). The container needs to be rebuilt and redeployed.

---

## 13. SAFE FIX RECOMMENDED

### Step 1: Rebuild image with current source

```bash
cd /root/moneyprinterturbo-video-factory
docker compose build
```

### Step 2: Recreate containers with public port binding

Change port binding from `127.0.0.1:8501:8501` to `8501:8501` (binds to 0.0.0.0 by default).

### Step 3: Remove ineffective iptables DNAT rule

```bash
iptables -t nat -D PREROUTING -d 127.0.0.1 -p tcp --dport 8501 -j DNAT --to-destination 172.17.0.3:8501
```

### Step 4: Verify external access

```bash
curl http://95.111.192.237:8501/
```

---

## 14. PRODUCTION SAFETY

- No production jobs created
- No data modified
- No containers restarted
- No source modified
- Diagnosis only

---

## PHASE 11H.1.1 CLASSIFICATION

**PASS — DIAGNOSIS COMPLETE**

---

## FINAL OUTPUT

**PRIMARY ROOT CAUSE:** C — WebUI running but bound only internally (127.0.0.1:8501)

**SECONDARY ISSUE:** E — Stale container image (predates Phase 11H.1 changes)

**SAFE FIX:**
1. `docker build -t mpt-factory-11e:latest .`
2. Recreate container with `8501:8501` (not `127.0.0.1:8501:8501`)
3. Remove iptables DNAT rule

**CANONICAL UI:** MPT WebUI : port 8501 (currently unreachable externally)

**FACTORY:** Legacy : port 8000 (still running)

**PHASE 11H.1:** BLOCKED until runtime accessibility is fixed.
