# CANONICAL ARCHITECTURE

**Last Updated:** 2026-08-29
**Status:** LOCKED

---

## CANONICAL USER UI

**MoneyPrinterTurbo WebUI**

- Source: `/root/moneyprinterturbo-video-factory/webui/`
- Entry point: `webui/Main.py` (Streamlit)
- Container: `moneyprinterturbo-webui`
- Port: 8501

## CANONICAL SOURCE

`/root/moneyprinterturbo-video-factory/`

## CANONICAL USER DOMAIN

`https://goldtrader.website`

- DNS: `goldtrader.website` → `95.111.192.237`
- SSL: Let's Encrypt (Certbot)
- Reverse proxy: nginx
- Routes to: `http://127.0.0.1:8501` (MPT WebUI)

## VIDEO ENGINE

MoneyPrinterTurbo API / backend

- Source: `/root/moneyprinterturbo-video-factory/`
- API entry: `app/main.py` (FastAPI)
- Container: `moneyprinterturbo-api`
- Port: 8080 (localhost only, internal)

## MPT WEBUI

- Container: `moneyprinterturbo-webui`
- Image: `mpt-factory-11h1:latest`
- Port: `0.0.0.0:8501` (public)
- Command: `streamlit run ./webui/Main.py --server.address=0.0.0.0 --server.port=8501`
- Volumes: config.toml, storage
- Restart: always

## MPT API

- Container: `moneyprinterturbo-api`
- Image: `mpt-factory-11e:latest`
- Port: `127.0.0.1:8080` (internal only)
- Command: `python3 main.py`
- Volumes: config.toml, storage
- Restart: always

## LEGACY FACTORY

`/opt/mpt-factory/`

- Process: uvicorn (pid 180209)
- Port: `127.0.0.1:8000` (localhost only)
- Domain: `https://factory.goldtrader.website`
- Frontend: `/opt/mpt-factory/static_dashboard/`
- Database: `/opt/mpt-factory/data/factory.db`
- Status: LEGACY — do not extend

## LEGACY FACTORY PORT

8000

---

## RULE

**NO NEW USER-FACING FEATURES MAY BE IMPLEMENTED IN:**
`/opt/mpt-factory/static_dashboard/`

All user-facing feature development goes into the canonical MPT WebUI:
`/root/moneyprinterturbo-video-factory/webui/`

---

## PORT MAP

| Port | Process | Bind | Purpose | Public |
|---|---|---|---|---|
| 80 | nginx | 0.0.0.0 | HTTP → HTTPS redirect | YES |
| 443 | nginx | 0.0.0.0 | HTTPS (Let's Encrypt) | YES |
| 8501 | docker-proxy (MPT WebUI) | 0.0.0.0 | Canonical user UI | YES |
| 8000 | uvicorn (Factory) | 127.0.0.1 | Legacy Factory | NO |
| 8080 | docker-proxy (MPT API) | 127.0.0.1 | Internal video engine | NO |
| 8090 | docker-proxy (Legacy MPT) | 0.0.0.0 | Legacy upstream image | YES |

## DOMAIN ROUTING

| Domain | nginx → | Application | Status |
|---|---|---|---|
| goldtrader.website | 127.0.0.1:8501 | MPT WebUI (Streamlit) | **CANONICAL** |
| factory.goldtrader.website | 127.0.0.1:8000 | Factory (FastAPI) | LEGACY |

## DOMAIN CONTENT FINGERPRINTS

| Domain | <title> | Application |
|---|---|---|
| goldtrader.website | Streamlit | MPT WebUI (canonical) |
| factory.goldtrader.website | Factory Dashboard | Factory (legacy) |

## DEPLOYMENT DIAGRAM

```
USER
  ↓
https://goldtrader.website
  ↓
nginx (443, Let's Encrypt)
  ↓
proxy_pass http://127.0.0.1:8501
  ↓
docker-proxy (0.0.0.0:8501)
  ↓
moneyprinterturbo-webui container
  ↓
Streamlit webui/Main.py (Phase 11H.1)
  ├── Create view (4-column form)
  ├── Videos view (library + thumbnails)
  └── Jobs view (task monitoring)
```

## MPT ENGINE (INTERNAL)

```
Factory (legacy) ──→ MPT API (127.0.0.1:8080) ──→ Video pipeline
                                                  ──→ Material download
                                                  ──→ Quality gate
                                                  ──→ Reframe
                                                  ──→ Thumbnail
                                                  ──→ Artifacts
```
