# YouTube Footage Provider — Deployment Guide

## Overview

This document describes how to deploy and configure the YouTube footage provider
in MoneyPrinterTurbo (MPT) and the Factory harness.

YouTube is added as an **additional** footage provider alongside Pexels and
Pixabay. It is **not** a replacement. See
`YOUTUBE_FOOTAGE_ARCHITECTURE.md` for the full architecture.

---

## Prerequisites

### System packages

```bash
apt-get install -y ffmpeg chromium
```

- **ffmpeg >= 7.0** — required for `scale` with
  `force_original_aspect_ratio=increase` and the `crop` filter used by the
  smart reframe pipeline.
- **chromium** — required for the browser-based PO token fallback (nodriver).
- **Deno >= 2.3** — required for the `bgutil-ytdlp-pot-provider` HTTP server.

### Python packages

In the MPT virtualenv:

```bash
pip install yt-dlp==2026.8.19 bgutil-ytdlp-pot-provider==1.3.2 yt-dlp-ejs==0.8.0 yt-dlp-getpot-wpc==1.1.2 playwright==1.62.0
```

### PO token provider

Run `bgutil-ytdlp-pot-provider` as a sidecar service or standalone process:

```bash
deno run --allow-all https://deno.land/x/bgutil_ytdlp_pot_provider/main.ts --port 4416
```

The provider exposes:
- `GET /ping` — health check
- `GET /pot` — returns a fresh PO token for the configured player client

---

## Configuration

### 1. Authentication

YouTube now supports two authentication methods. Configure at least one.

#### Option A: PO token provider (recommended)

```toml
# /opt/MoneyPrinterTurbo/config.toml

youtube_po_token_provider_url = "http://127.0.0.1:4416"
youtube_player_client = "web"
```

#### Option B: Cookies file (legacy)

```toml
youtube_cookies_file = "/opt/secrets/youtube_cookies.txt"
```

#### Option C: Browser fallback (automatic)

When `youtube_browser_fallback = true` (default), yt-dlp will attempt to
extract PO tokens from a headless Chromium session via nodriver if the HTTP
provider is unreachable.

```toml
youtube_browser_fallback = true
```

### 2. Factory configuration

In `/opt/mpt-factory/data/factory.json` or the Factory API payload:

```json
{
  "provider": "pexels",
  "provider_weights": {"pexels": 1.0, "pixabay": 0.8, "youtube": 0.5},
  "video_sources": ["pexels", "pixabay", "youtube"]
}
```

The Factory worker (`app/worker.py`) forwards `video_sources` to MPT's
`task.start()` via `mpt_client.create_video(video_sources=...)`.

---

## Enabling YouTube in production

### Default (YouTube disabled)

By default MPT uses `video_source = "pexels"` only. The YouTube provider is
available but not enabled in the default `video_sources` list.

### Enable YouTube

1. Configure `youtube_po_token_provider_url` (and optionally `youtube_cookies_file`) in `config.toml`.
2. Add `"youtube"` to the `video_sources` list in config or pass it via the
   API payload.
3. Restart the MPT service.
4. Restart the Factory worker.

### Verification

```bash
# Test the YouTube search + download path
curl -X POST http://localhost:5173/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "Misteri Gunung Salak",
    "video_sources": ["pexels", "pixabay", "youtube"],
    "n_scenes": 6
  }'
```

Monitor logs for:

```
INFO  youtube search → "mountain fog gunung salak" → N results
INFO  youtube download → asset_id=... → saved at .../materials/...
DEBUG combined video → 1080x1920 ✓
```

---

## Failure modes and recovery

YouTube downloads now use a 2-attempt recovery strategy:

1. **bgutil HTTP provider** — requests a PO token from the configured HTTP endpoint
2. **Browser fallback** — extracts a PO token from a headless Chromium session
3. **Direct** — final fallback without PO token (legacy behavior)

Failure categories are logged explicitly:
- `playability_blocked` — YouTube player-response check failed (upstream IP-level block)
- `provider_pot_failed` — HTTP provider returned a token but yt-dlp still failed
- `browser_pot_failed` — browser fallback could not extract a token
- `bot_detected` — HTTP 403 / bot detection
- `generic_download_error` — other download errors

---

## Rollback

To disable YouTube:

1. Remove `"youtube"` from `video_sources`.
2. Remove `youtube_po_token_provider_url` and `youtube_cookies_file` from config.
3. Restart services.

The existing Pexels/Pixabay pipeline is unaffected.
