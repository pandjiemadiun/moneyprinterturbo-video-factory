# PHASE 11H.1.2 — CANONICAL UI IDENTITY & DOMAIN ROUTING AUDIT

**Status:** PASS
**Date:** 2026-08-29

---

## 1. DOMAIN

| Property | Value |
|---|---|
| Canonical domain | `goldtrader.website` |
| DNS A record | `95.111.192.237` |
| SSL | Let's Encrypt (Certbot) |
| Reverse proxy | nginx/1.28.3 |

---

## 2. DNS

```
dig +short goldtrader.website
→ 95.111.192.237
```

DNS correctly points to this server.

---

## 3. REVERSE PROXY

### goldtrader.website (CANONICAL)

File: `/etc/nginx/sites-available/moneyprinterturbo`

```nginx
server {
    server_name goldtrader.website www.goldtrader.website;
    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }
    listen 443 ssl;
    ssl_certificate /etc/letsencrypt/live/goldtrader.website/fullchain.pem;
}
```

### factory.goldtrader.website (LEGACY)

File: `/etc/nginx/sites-available/factory.goldtrader.website`

```nginx
server {
    server_name factory.goldtrader.website;
    location / {
        proxy_pass http://127.0.0.1:8000;
    }
    listen 443 ssl;
}
```

---

## 4. PORT MAP

| Port | Process | Bind Address | Purpose | Public |
|---|---|---|---|---|
| 80 | nginx | 0.0.0.0 | HTTP → HTTPS redirect | YES |
| 443 | nginx | 0.0.0.0 | HTTPS (Let's Encrypt) | YES |
| 8501 | docker-proxy (MPT WebUI) | 0.0.0.0 | **Canonical user UI** | YES |
| 8000 | uvicorn (Factory) | 127.0.0.1 | Legacy Factory | NO |
| 8080 | docker-proxy (MPT API) | 127.0.0.1 | Internal video engine | NO |
| 8090 | docker-proxy (Legacy MPT) | 0.0.0.0 | Legacy upstream image | YES |

---

## 5. MPT WEBUI IDENTITY

| Property | Value |
|---|---|
| Container name | moneyprinterturbo-webui |
| Container ID | c8b8c23f00a4 |
| Image | mpt-factory-11h1:latest |
| Image ID | f33213d38b6 |
| Port | 0.0.0.0:8501 |
| Command | `streamlit run ./webui/Main.py --server.address=0.0.0.0 --server.port=8501` |
| Browser serverAddress | https://goldtrader.website |
| Volumes | config.toml, storage |

### Phase 11H.1 Code in Running Container

| Check | Result |
|---|---|
| `_render_videos_view` | YES (2 references) |
| `_render_jobs_view` | YES |
| `_render_create_view` | YES |
| `Nav Create` i18n | YES |
| YouTube provider | YES |

---

## 6. MPT API IDENTITY

| Property | Value |
|---|---|
| Container name | moneyprinterturbo-api |
| Container ID | 93ca87fdd975 |
| Image | mpt-factory-11e:latest |
| Port | 127.0.0.1:8080 |
| Command | `python3 main.py` |

---

## 7. FACTORY IDENTITY

| Property | Value |
|---|---|
| Source path | `/opt/mpt-factory/` |
| Process | uvicorn pid 180209 |
| Port | 127.0.0.1:8000 |
| Domain | `https://factory.goldtrader.website` |
| Frontend | `/opt/mpt-factory/static_dashboard/` |
| Database | `/opt/mpt-factory/data/factory.db` |
| Status | LEGACY |

---

## 8. DOMAIN ROUTING

### goldtrader.website → MPT WebUI (VERIFIED)

```
User → https://goldtrader.website
  → nginx (443, Let's Encrypt)
  → proxy_pass http://127.0.0.1:8501
  → docker-proxy (0.0.0.0:8501)
  → moneyprinterturbo-webui container
  → Streamlit webui/Main.py
```

### factory.goldtrader.website → Factory (VERIFIED)

```
User → https://factory.goldtrader.website
  → nginx (443, Let's Encrypt)
  → proxy_pass http://127.0.0.1:8000
  → uvicorn pid 180209
  → FastAPI app/main.py
```

---

## 9. DIRECT :8501 BEHAVIOR

### Local (WORKS)

```
curl http://127.0.0.1:8501/
HTTP 200
```

### Public IP (WORKS after fix)

```
curl http://95.111.192.237:8501/
HTTP 200
```

**Previous issue (CONNECTION_TIMEOUT) was caused by Docker binding `127.0.0.1:8501` only. Fixed by recreating container with `0.0.0.0:8501`.**

---

## 10. WHY DOMAIN WORKS

`goldtrader.website` works because:

1. DNS resolves to this server (`95.111.192.237`)
2. nginx listens on port 443 with valid SSL
3. nginx proxies to `127.0.0.1:8501`
4. MPT WebUI container listens on `0.0.0.0:8501`
5. Streamlit responds with HTTP 200

---

## 11. WHY DIRECT IP:8501 NOW WORKS

After the Phase 11H.1.1 fix:

1. Docker container recreated with `0.0.0.0:8501` binding
2. docker-proxy listens on all interfaces
3. External connections reach the container
4. Streamlit responds with HTTP 200

---

## 12. CANONICAL ARCHITECTURE

```
USER
  ↓
https://goldtrader.website
  ↓
nginx (443)
  ↓
proxy_pass http://127.0.0.1:8501
  ↓
MPT WebUI (Streamlit)
  ├── Create view
  ├── Videos view
  └── Jobs view
```

---

## 13. AGENT SAFETY RULES

All agents working on this project MUST:

1. Implement user-facing features ONLY in `/root/moneyprinterturbo-video-factory/webui/`
2. NOT implement user-facing features in `/opt/mpt-factory/static_dashboard/`
3. NOT create a second UI
4. Treat port 8000 Factory as legacy
5. Verify changes in the running container, not just source
6. Before modifying UI, verify the target is the canonical path

---

## 14. PRODUCTION SAFETY

| Action | Status |
|---|---|
| Source modification | NO |
| Docker restart | NO |
| Docker rebuild | NO (done in 11H.1.1) |
| Container recreation | NO (done in 11H.1.1) |
| Database mutation | NO |
| Config mutation | NO |
| nginx mutation | NO |
| Firewall mutation | NO |
| Factory deletion | NO |

---

## PHASE 11H.1.2 CLASSIFICATION

**PASS**

---

## FINAL OUTPUT

| Item | Value |
|---|---|
| **CANONICAL USER UI** | MoneyPrinterTurbo WebUI (Streamlit) |
| **CANONICAL DOMAIN** | `https://goldtrader.website` |
| **DOMAIN ROUTES TO** | MPT WebUI via nginx → 127.0.0.1:8501 |
| **MPT WEBUI** | `moneyprinterturbo-webui` container, `mpt-factory-11h1:latest`, port 8501 |
| **MPT API** | `moneyprinterturbo-api` container, `mpt-factory-11e:latest`, port 8080 |
| **LEGACY FACTORY** | `/opt/mpt-factory/`, port 8000, pid 180209 |
| **DIRECT :8501** | HTTP 200 (fixed from CONNECTION_TIMEOUT) |
| **ROOT CAUSE** | Docker binding was `127.0.0.1:8501` (localhost only); fixed to `0.0.0.0:8501` |
| **NO RUNTIME MODIFICATION** | YES (this was audit only) |
