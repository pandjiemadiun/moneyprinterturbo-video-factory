# AGENTS.md — MPT Content Factory

## IMPORTANT

This repository is the canonical product.

**User-facing UI = MPT WebUI** (`webui/Main.py`)

**Do NOT implement user-facing features in `/opt/mpt-factory`.**

**Do NOT treat port 8000 Factory UI as canonical.**

**Do NOT create a second UI.**

Before modifying UI, verify the target is:

`/root/moneyprinterturbo-video-factory/webui/`

## Canonical Architecture

| Component | Application | Port | Access |
|---|---|---|---|
| **Canonical User UI** | MPT WebUI (Streamlit) | 8501 | Public |
| **Video Engine** | MPT API (FastAPI) | 8080 | Internal |
| **Admin/Debug UI** | MPT WebUI (Streamlit) | 8501 | Public |

## Production User Domain

`https://goldtrader.website`

- Routes to: `http://127.0.0.1:8501` (MPT WebUI)
- SSL: Let's Encrypt via nginx
- DNS: `95.111.192.237`

## Legacy (Do Not Extend)

| Component | Location | Port |
|---|---|---|
| Factory UI | `/opt/mpt-factory/static_dashboard/` | 8000 (localhost) |
| Factory API | `/opt/mpt-factory/app/main.py` | 8000 (localhost) |
| Factory DB | `/opt/mpt-factory/data/factory.db` | N/A |

### `/opt/MoneyPrinterTurbo` is NOT canonical source

`/opt/MoneyPrinterTurbo` is the **production data volume only**:
`config.toml` and `storage/` (tasks.db, production MP4s) are bind-mounted from
here into the canonical containers. It also happens to contain a *stale git
checkout* (`bdbcdb5`) that is **not** what production is built from.

**Do NOT edit `/opt/MoneyPrinterTurbo/webui/...` or `/opt/MoneyPrinterTurbo/app/...`
as "the source."** Those edits are invisible to production (the running image is
baked from `/root/moneyprinterturbo-video-factory`) and only re-create the
source/data conflation that caused the "wrong address" bug.

- Canonical source repository: `/root/moneyprinterturbo-video-factory`
- Canonical build context: `/root/moneyprinterturbo-video-factory` ONLY.
- Data volume (do not delete, do not treat as source): `/opt/MoneyPrinterTurbo`

See `docs/PRODUCTION_RUNTIME_CONTRACT.md` and verify with
`python3 scripts/verify_production.py` before every deploy.

## Permanent Deployment Contract

## Source Code of Truth

| Concern | Canonical Location |
|---|---|
| User interface | `/root/moneyprinterturbo-video-factory/webui/` |
| Video engine | `/root/moneyprinterturbo-video-factory/app/` |
| API endpoints | `/root/moneyprinterturbo-video-factory/app/router.py` |
| Configuration | `/root/moneyprinterturbo-video-factory/config.example.toml` |

## Before Making Changes

1. Verify the target is in `/root/moneyprinterturbo-video-factory/`
2. Do NOT modify `/opt/mpt-factory/` for user-facing features
3. Do NOT create a second UI
4. If a task refers to "Factory UI", interpret it as the canonical MPT WebUI unless explicitly stated otherwise
5. Run tests after changes: `python -m pytest test/services/`
6. Do NOT create production jobs during testing
7. Do NOT download YouTube footage during testing

## Testing

- Use isolated fixtures/mocks
- No production network calls
- No production jobs
- No YouTube downloads
