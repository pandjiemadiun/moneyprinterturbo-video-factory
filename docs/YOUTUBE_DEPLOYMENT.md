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
apt-get install -y ffmpeg yt-dlp
```

- **ffmpeg >= 7.0** — required for `scale` with
  `force_original_aspect_ratio=increase` and the `crop` filter used by the
  smart reframe pipeline.
- **yt-dlp** — required for `ytsearch` flat playlist extraction and cookie-
  authenticated downloads.

### Python packages

In the MPT virtualenv (`/tmp/mptpy`):

```bash
pip install "yt-dlp>=2024.7.1"
```

---

## Configuration

### 1. YouTube cookies file

YouTube blocks unauthenticated downloads with HTTP 403 ("Sign in to confirm
you're not a bot"). To download YouTube videos, you must supply a cookies
file.

#### Obtaining cookies

1. Install the "Get cookies.txt" browser extension (Chrome/Firefox).
2. Navigate to https://www.youtube.com
3. Click the extension icon → **Export cookies** → save as
   `youtube_cookies.txt`.
4. Upload the file to a secure, non-public location on the server:

```
/opt/secrets/youtube_cookies.txt
```

#### Registering the cookies path in MPT config

```toml
# /opt/MoneyPrinterTurbo/config.toml

youtube_cookies_file = "/opt/secrets/youtube_cookies.txt"

# Optional: explicitly configure which providers are searched for each scene.
# When omitted, [pexels, pixabay, youtube] are tried in order.
# video_source = "pexels"          # primary fallback (backward compat)
# video_sources = ["pexels", "pixabay", "youtube"]
```

> **Security**: The cookies file must NOT be in source control, must NOT be
> passed via command-line arguments, and must NOT appear in logs. See
> `YOUTUBE_FOOTAGE_ARCHITECTURE.md` §Security for details.

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

1. Set `youtube_cookies_file` in `config.toml`.
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

## Rollback

To disable YouTube:

1. Remove `"youtube"` from `video_sources`.
2. Remove `youtube_cookies_file` from config.
3. Restart services.

The existing Pexels/Pixabay pipeline is unaffected.
