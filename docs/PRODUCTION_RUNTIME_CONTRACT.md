# Production Runtime Contract (Phase 14.7)

> **Authoritative single source of truth for what is production, what is
> canonical, and how to prove it.** This file supersedes every prior
> conflicting statement in the repository (including `docs/FINAL_REPORT.md`,
> which previously declared `/opt/MoneyPrinterTurbo` as "the repository").

## 1. Canonical identity

| Field | Value |
|---|---|
| CANONICAL_REPOSITORY | `/root/moneyprinterturbo-video-factory` |
| CANONICAL_BRANCH | `main` |
| CANONICAL_WEBUI | `/root/moneyprinterturbo-video-factory/webui/Main.py` |
| CANONICAL_WEBUI_PACKAGE | `/root/moneyprinterturbo-video-factory/webui/` |
| CANONICAL_API_PACKAGE | `/root/moneyprinterturbo-video-factory/app/` |
| CANONICAL_DOMAIN | `https://goldtrader.website` |
| CANONICAL_WEBUI_PORT | `8501` (Streamlit, MPT WebUI) |
| CANONICAL_API_PORT | `8080` (FastAPI, MPT API engine) |
| CANONICAL_DNS_A | `95.111.192.237` |
| CANONICAL_DEPLOYMENT_METHOD | `docker run` of a SHA-tagged image `mpt-webui:<git-sha>`, built from the canonical repository ONLY, with data bind-mounted from `/opt/MoneyPrinterTurbo/{config.toml,storage}` |

Production chain (every arrow is mechanically verifiable):

```
Browser  https://goldtrader.website:443
  ↓  (TLS: Let's Encrypt via nginx)
nginx   server_name goldtrader.website www.goldtrader.website
        location /api/v1/ → 127.0.0.1:8080
        location /        → 127.0.0.1:8501
  ↓
container  moneyprinterturbo-webui
  ↓  (image label git-sha == canonical repo HEAD)
image  mpt-webui:<git-sha>  (Dockerfile bakes webui/Main.py from THIS repo)
  ↓
source  /root/moneyprinterturbo-video-factory/webui/Main.py  (git HEAD)
  ↓
engine  /root/moneyprinterturbo-video-factory/app/  → 127.0.0.1:8080 (API container)
```

## 2. What is NOT canonical (and why confusion happened)

### 2a. `/opt/MoneyPrinterTurbo`

- **Role:** PRODUCTION DATA VOLUME ONLY.
  - Bind-mounted into the containers as the config + storage:
    - `-v /opt/MoneyPrinterTurbo/config.toml:/MoneyPrinterTurbo/config.toml`
    - `-v /opt/MoneyPrinterTurbo/storage:/MoneyPrinterTurbo/storage`
  - This is where `tasks.db`, production MP4s, and `config.toml` live.
  **DO NOT DELETE.**
- **NOT canonical source.** It also happens to contain a stale *git checkout*
  at `bdbcdb5` (dirty: `M app/services/material.py`), but that checkout is
  **not** what the running image is built from and must never be edited as
  "the source." Editing it has zero production effect and only widens the
  source/data conflation that caused the original "wrong address" bug.
- The canonical AGENTS.md previously omitted `/opt/MoneyPrinterTurbo`
  entirely, so editors could not tell source from data. This contract makes
  it explicit.

### 2b. `/opt/mpt-factory`

- **Role:** Legacy Factory UI/API/DB (port `8000` localhost). NON-canonical.
- Must NOT serve any user traffic (see §5 Factory decommission).

### 2c. `/opt/MoneyPrinterTurbo` vs `/root/.../video-factory` (the root cause)

There are **two** git checkouts that look almost identical:

| Path | HEAD | Purpose | Canonical? |
|---|---|---|---|
| `/root/moneyprinterturbo-video-factory` | canonical HEAD | canonical source/build context | **YES** |
| `/opt/MoneyPrinterTurbo` | `bdbcdb5` | production data volume (+ stale source copy) | NO (data only) |

A coding agent can reasonably edit `/opt/MoneyPrinterTurbo/webui/Main.py`
thinking it is "the production WebUI" (because prior reports and the
bind-mount naming use that path), while production actually runs an image
**baked from `/root/.../video-factory`**. The edit is invisible live, so the
agent concludes "the website didn't change / wrong repo." The durable fix is
§3–§5 below: one canonical contract + a fail-closed verifier + immutable
SHA-tagged images so the identity chain can always be proven.

## 3. Single deployment contract (permanent prevention)

- There is exactly **one** build context: the canonical repository.
  `docker build … /root/moneyprinterturbo-video-factory`.
- There is exactly **one** image naming scheme: `mpt-webui:<git-sha>`
  (immutable). `:current` may exist only as a rollback alias and is **never**
  the source of truth — `verify_production.py` rejects it.
- There is exactly **one** data volume: `/opt/MoneyPrinterTurbo/{config.toml,storage}`.
  Source is **never** bind-mounted into the production container (the image is
  baked); only config + storage are mounted.
- There is one production WebUI: `goldtrader.website` → nginx → `:8501`.

## 4. Immutable image provenance

Every production image is built with:

```bash
GIT_SHA="$(git -C /root/moneyprinterturbo-video-factory rev-parse HEAD)" \
GIT_COMMIT="$GIT_SHA" \
BUILD_PHASE="14.7" \
docker build \
  --build-arg GIT_SHA="$GIT_SHA" \
  --build-arg GIT_COMMIT="$GIT_SHA" \
  --build-arg BUILD_PHASE="14.7" \
  -t mpt-webui:"$GIT_SHA" \
  -t mpt-webui:14.7 \
  -f Dockerfile /root/moneyprinterturbo-video-factory
```

The `Dockerfile` stamps `LABEL git-sha`, `git-commit`, `phase`, and `repo`
onto every image. `scripts/verify_production.py` asserts the running webui
container's `git-sha` label equals `git rev-parse HEAD` of the canonical
repository. A mismatch → **FAIL CLOSED**.

## 5. Factory decommission

- Port `8000` MUST NOT be listening (legacy Factory UI). 
- The `factory.goldtrader.website` nginx vhost MUST NOT be enabled (no
  symlink in `sites-enabled`). It is removed/kept-disabled.
- No container whose job is the Factory UI must run. (The `moneyprinterturbo-api`
  container serves the MPT API on `:8080` — that is the canonical engine, not
  the Factory.)

## 6. How to prove it (machine checkable)

```bash
python3 scripts/verify_production.py          # exit 0 = PASS, exit 1 = FAIL
```

The verifier is **fail-closed**: if it cannot prove every arrow in §1, it
exits non-zero with evidence. Run it before every deploy and after every
deploy.

## 7. Edit authorization rule for future agents

> Before editing any WebUI/API file, confirm:
> 1. `git -C <file> rev-parse --show-toplevel` == canonical repository path.
> 2. `git rev-parse HEAD` == image label `git-sha` on the running webui
>    container (`verify_production.py` prints both).
> 3. The file lives under `/root/moneyprinterturbo-video-factory/webui/` (or
>    `/app/`), NOT under `/opt/`.
> If those do not all match, STOP and re-read this contract.
