# Phase 10H.3 — Permanent Docker Deployment + Runtime Verification

**Date:** 2026-08-28
**Objective:** Permanently bake the validated Phase 10H.1 and 10H.2 fixes into the
MoneyPrinterTurbo Docker image and verify the new container carries the fixes
**without** relying on `docker cp`. This phase is deployment + verification only.
Phase 10I is intentionally **not** started.

---

## 1. Objective

Deploy Phase 10H.1 (YouTube cache identity canonicalization) and Phase 10H.2
(YouTube format selection) as a permanent, image-baked change, replacing the
prior temporary `docker cp` deployment, and verify the running container derives
the fixes from the image — not from a host-to-container file copy.

---

## 2. Baseline (captured before deployment)

| Item | Value |
|------|-------|
| git HEAD | `ad2aa620c10cd1fdea0f4b7ccb2456f95f1548e2` (`ad2aa62`) |
| git status | clean (nothing to commit) |
| factory.db SHA256 | `ad0e6df9d5a45438532c0c99655455448e8c791bd5781711bf1f4f111a5d59a1` |
| factory.db size | 151552 bytes |
| factory job count (`jobs` table) | 171 |
| factory assets count | 43 |
| production MP4 count | 158 |
| task directory count | 134 |
| cache_videos count / size | 0 files / 20K (empty dir) |
| config.toml SHA256 | `2a8d89a696ff5564703547e86c198d846370399de3ae3a5e105c0784d26c7f45` |
| current container ID | `5b7acab82caf42d93425f67ec57bd1e77fdca3cc0e34776d672f2bf07b147775` |
| current container image | `mpt-youtube-ejs-phase10f:latest` (`d800b37eadcd…`) |
| restart count (old) | 0 |
| bind mounts | `/opt/MoneyPrinterTurbo/config.toml:/MoneyPrinterTurbo/config.toml:rw`, `/opt/MoneyPrinterTurbo/storage:/MoneyPrinterTurbo/storage:rw` |
| exposed ports | `127.0.0.1:8080->8080/tcp`, `8501/tcp` (exposed, unpublished) |
| restart policy | `always` |
| network mode | `bridge` |
| command | `python3 main.py` |

---

## 3. Source Commit Verification

### Ancestry (all are ancestors of HEAD `ad2aa62`)
- `6199d56` — fix: canonicalize YouTube cache identity → **IS ancestor**
- `a3bad2a` — fix: improve YouTube format selection → **IS ancestor**
- `ad2aa62` — docs: Phase 10H.1 + 10H.2 report → **IS ancestor**
- working tree: **clean**

### Files touched by the three commits (no unrelated changes)
- `6199d56`: `app/services/material.py`, `test/services/test_youtube_cache_identity_10h1.py`, `test/services/test_youtube_provider.py`
- `a3bad2a`: `app/services/material.py`, `test/services/test_youtube_format_selection_10h2.py`
- `ad2aa62`: `docs/PHASE_10H1_H2_REPORT.md`

No modification to `factory.db`, `config.toml`, nginx, provider fallback order,
quality-gate threshold, cleanup behavior, or any unrelated source.

### Intended change verification (in committed source)
- **Cache identity:** `save_video_youtube()` no longer uses `url.split("?")[0]`
  for the YouTube path. It derives the cache key from `_youtube_video_identity()`
  → `yt:<11-char-video-ID>`. The `url.split("?")[0]` fallback at
  `material.py:1361` is only the safe non-YouTube branch (`identity is None`).
  Confirmed the other `url.split("?")[0]` at `material.py:1121` belongs to
  `save_video()` (general non-YouTube path), not the YouTube cache identity.
- **Format selector (10H.2):** present at `material.py:1376`:
  `bestvideo[vcodec^=avc1][ext=mp4][height<=720]+bestaudio[acodec^=mp4a]/best`

---

## 4. New Image ID / Tag

- **Build method:** `docker build -f /tmp/Dockerfile.phase10h3 -t mpt-youtube-ejs-phase10h:latest /opt/MoneyPrinterTurbo`
- **Base image:** `mpt-youtube-ejs:latest` (`afd296c29a70…`) — already contains
  Deno 2.4.0, yt-dlp + yt-dlp-ejs, ffmpeg, MoviePy, the YouTube provider
  scaffolding, and the storage/cookies layout.
- **New image tag:** `mpt-youtube-ejs-phase10h:latest`
- **New image ID:** `sha256:81866e5161fa2dcb742dcad6f43497eb78d23801f40449e44af28cd09404bcb8` (`81866e5161fa`)
- **Old image tag (preserved, NOT overwritten):** `mpt-youtube-ejs-phase10f:latest` (`d800b37eadcd…`)
- The build `COPY . .` bakes the committed source into the image. `.dockerignore`
  excludes `storage/` and `config.toml`, so the runtime bind mounts remain the
  source of truth. **No `docker cp` was used to bake the source.**

---

## 5. Image Filesystem Verification

Verified inside the new image (`docker run --rm … mpt-youtube-ejs-phase10h:latest`):

| Check | Result |
|-------|--------|
| `_youtube_video_identity()` exists | ✅ (`def _youtube_video_identity` at `material.py:1282`) |
| YouTube cache identity no longer uses collision-prone logic | ✅ YouTube path uses `yt:<ID>`; `split("?")[0]` only in non-YouTube fallback |
| New format selector present | ✅ `bestvideo[vcodec^=avc1][ext=mp4][height<=720]+bestaudio[acodec^=mp4a]/best` |
| `_EFFECTIVE_MIN_DIMENSION = 250.0` | ✅ (`material.py:1197`) |
| Output-aware quality gate present | ✅ (`material.py:1461`, `# Phase 10F: output-aware effective-resolution gate`) |
| Phase 10C cleanup function present | ✅ `cleanup_orphan_cache_videos` (`material.py:2297`), `cleanup_expired_material_search_cache` (`material_cache.py:383`) |
| Startup cleanup hook present | ✅ `app/asgi.py:51` calls `material_service.run_startup_cleanup()` |

Toolchain inside the new image:
- yt-dlp `2026.8.19`
- yt-dlp-ejs `0.8.0`
- Deno `2.4.0 (stable, release, x86_64-unknown-linux-gnu)`
- ffmpeg `4.3.9-0+deb11u2`
- MoviePy present (base image dependency set)

No cookie contents were read or exposed during verification.

---

## 6. Container Recreation Details

The old temporary container was **stopped and removed**, then a new container was
created **from the new image** with identical configuration:

| Field | Value (identical to old) |
|-------|--------------------------|
| name | `moneyprinterturbo-api` |
| image | `mpt-youtube-ejs-phase10h:latest` (was `…phase10f:latest`) |
| command | `python3 main.py` |
| restart policy | `always` |
| network | `bridge` |
| ports | `127.0.0.1:8080->8080/tcp`, `8501/tcp` exposed |
| bind mounts | `/opt/MoneyPrinterTurbo/config.toml:/MoneyPrinterTurbo/config.toml:rw`, `/opt/MoneyPrinterTurbo/storage:/MoneyPrinterTurbo/storage:rw` |
| working dir | `/MoneyPrinterTurbo` |

Host storage directory was **not** deleted or recreated. `config.toml` was **not**
altered. Cookies are served from `/MoneyPrinterTurbo/storage/youtube_cookies.txt`
(bind-mounted storage), unchanged.

**New container ID:** `952021e92d243eb26d35563c62fed69e3d1fdc748d7f8077d3eddd0b053044ab` (`952021e92d24`)

---

## 7. Runtime Source Verification (inside the running new container)

Run via an in-container Python script (`/tmp/rt_verify.py`, later removed). No
network downloads were performed.

**Cache identity (10H.1):**
```
id1 (watch?v=dQw4w9WgXcQ)        : yt:dQw4w9WgXcQ
id2 (watch?v=AAAAAAAAAAA)        : yt:AAAAAAAAAAA
id3 (youtu.be/dQw4w9WgXcQ?t=30)  : yt:dQw4w9WgXcQ
id4 (watch?v=…&feature=…&t=10)   : yt:dQw4w9WgXcQ
distinct IDs        -> True
equivalent URLs -> same identity -> True
non-YouTube -> None -> True
```

**Format selector (10H.2):**
```
runtime selector: bestvideo[vcodec^=avc1][ext=mp4][height<=720]+bestaudio[acodec^=mp4a]/best
matches expected -> True
```

**Quality gate (10F):** `_EFFECTIVE_MIN_DIMENSION = 250.0`; gate references the
portrait `1080×1920` target (`material.py:1437`).

**Cleanup (10C):** `cleanup_orphan_cache_videos` ✅,
`cleanup_expired_material_search_cache` ✅, `run_startup_cleanup` ✅.

Container logs show the startup event fired (`app/asgi.py:23`) and **no errors /
tracebacks** — i.e. the startup cleanup hook executed cleanly.

---

## 8. Cache Identity Verification
Two distinct YouTube IDs produce distinct identities (`yt:dQw4w9WgXcQ` ≠
`yt:AAAAAAAAAAA`). Equivalent supported URL forms for the same video
(`watch?v=…`, `youtu.be/…`, `watch?v=…&feature=…&t=…`) resolve to the same
identity `yt:dQw4w9WgXcQ`. Non-YouTube/malformed input returns `None` (safe
fallback, no collision). No network downloads were required.

## 9. Format Selector Verification
`save_video_youtube()` in the live container contains exactly:
`bestvideo[vcodec^=avc1][ext=mp4][height<=720]+bestaudio[acodec^=mp4a]/best`
— the validated Phase 10H.2 selector.

## 10. Quality Gate Verification
`_EFFECTIVE_MIN_DIMENSION = 250.0` confirmed at runtime. The gate targets the
portrait `1080×1920` output resolution (canonical portrait). Phase 10F logic
intact.

## 11. Cleanup Verification
Phase 10C cleanup functions are present and the startup hook
(`run_startup_cleanup`, invoked from `app/asgi.py` at app startup) executed
without error on container start.

---

## 12. Production Invariant Comparison (baseline → post-deploy)

| Invariant | Baseline | Post-deploy | Status |
|-----------|----------|-------------|--------|
| factory.db SHA256 | `ad0e6df9…` | `ad0e6df9…` | ✅ unchanged |
| factory.db size | 151552 | 151552 | ✅ unchanged |
| factory jobs | 171 | 171 | ✅ unchanged |
| factory assets | 43 | 43 | ✅ unchanged |
| production MP4 | 158 | 158 | ✅ unchanged |
| task directories | 134 | 134 | ✅ unchanged |
| cache_videos files/size | 0 / 20K | 0 / 20K | ✅ unchanged |
| config.toml SHA256 | `2a8d89a6…` | `2a8d89a6…` | ✅ unchanged |
| container health | (old running) | running | ✅ |
| ExitCode | 0 | 0 | ✅ |
| RestartCount | 0 | 0 | ✅ |

---

## 13. Container Health
- Status: **running**
- ExitCode: **0**
- RestartCount: **0**
- No errors/tracebacks in logs; startup event and startup cleanup hook executed.

---

## 14. Rollback Procedure

To roll back to the previous known-good image:

1. Stop and remove the current container (do **not** touch host storage):
   ```
   docker stop moneyprinterturbo-api
   docker rm moneyprinterturbo-api
   ```
2. Recreate from the previous image with identical configuration:
   ```
   docker run -d \
     --name moneyprinterturbo-api \
     --restart always \
     -p 127.0.0.1:8080:8080 \
     -v /opt/MoneyPrinterTurbo/config.toml:/MoneyPrinterTurbo/config.toml:rw \
     -v /opt/MoneyPrinterTurbo/storage:/MoneyPrinterTurbo/storage:rw \
     -w /MoneyPrinterTurbo \
     mpt-youtube-ejs-phase10f:latest \
     python3 main.py
   ```

**Record:**
| | Old (pre-deploy) | New (deployed) |
|---|---|---|
| image ID | `d800b37eadcd0f1fd8b6e05fe403683cab0b14df29f6e5fa7fafc926116cf67b` | `81866e5161fa2dcb742dcad6f43497eb78d23801f40449e44af28cd09404bcb8` |
| image tag | `mpt-youtube-ejs-phase10f:latest` | `mpt-youtube-ejs-phase10h:latest` |
| container ID | `5b7acab82caf42d93425f67ec57bd1e77fdca3cc0e34776d672f2bf07b147775` (removed) | `952021e92d243eb26d35563c62fed69e3d1fdc748d7f8077d3eddd0b053044ab` |
| binds | config.toml + storage | config.toml + storage (same) |
| ports | 127.0.0.1:8080 + 8501 | 127.0.0.1:8080 + 8501 (same) |
| network | bridge | bridge (same) |
| restart policy | always | always (same) |

Host storage directory is **never** deleted during rollback.

---

## 15. Any Anomalies
- None. The old image `mpt-youtube-ejs-phase10f:latest` was previously fed the
  10H.1/10H.2 source via `docker cp` (temporary). The new image now carries that
  source natively; the `docker cp` mechanism is no longer part of the deployment.
- `cache_videos` is empty (0 files); no runtime download or smoke test was
  required, so no `/tmp` artifacts were created or needed deletion.

---

## 16. Final Classification
**PASS** — all acceptance criteria satisfied:
- new Docker image contains both 10H.1 and 10H.2 fixes ✅
- new container recreated from that image (not a restart) ✅
- runtime source inspection confirms both fixes ✅
- Phase 10F quality gate remains intact ✅
- Phase 10C cleanup remains intact ✅
- production invariants unchanged ✅
- container healthy (running, ExitCode=0, RestartCount=0) ✅
- working tree clean ✅
- rollback documented ✅

---

## 17. Exact Commits
- `6199d56` — fix: canonicalize YouTube cache identity (10H.1)
- `a3bad2a` — fix: improve YouTube format selection (10H.2)
- `ad2aa62` — docs: Phase 10H.1 + 10H.2 YouTube cache identity & format selection report (10H)

## 18. Final HEAD
`ad2aa620c10cd1fdea0f4b7ccb2456f95f1548e2` (`ad2aa62`)

---

## Explicit Safety / Compliance Statements

- **docker cp dependency:** NONE (source baked into image via `COPY` in build)
- **production jobs created:** 0
- **production YouTube downloads:** 0
- **production E2E runs:** 0
- **factory.db modified:** NO
- **config.toml modified:** NO
- **nginx modified:** NO

Phase 10I was **not** started, per the stop rule.
