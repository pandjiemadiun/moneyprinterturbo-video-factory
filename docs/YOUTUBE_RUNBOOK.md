# YouTube Footage Provider — Operations Runbook

## Purpose

This runbook covers day-to-day operations for the YouTube footage provider in
MoneyPrinterTurbo and the Factory harness.

---

## Common Scenarios

### 1. YouTube search returns no results

**Symptom**: Log shows `youtube search → "query" → 0 results` for a scene.

**Checklist**:
1. Verify the visual_query is specific (not generic like "person growing").
2. Check yt-dlp version: `yt-dlp --version` (minimum 2024.07.01).
3. Verify network connectivity to `youtube.com`.
4. The pipeline will fall back to Pexels/Pixabay automatically.
5. If ALL providers return nothing, the scene fails clean (RuntimeError). Verify
   no fallback footage was substituted.

### 2. YouTube download fails (HTTP 403)

**Symptom**: Log shows `ERROR: HTTP Error 403: Forbidden`.

**Checklist**:
1. Verify `youtube_cookies_file` is set in `config.toml`.
2. Check the cookies file exists and is readable by the MPT process user.
3. Verify the cookies are fresh (YouTube cookies expire; re-export from browser).
4. Check the cookies file format: it must be in Netscape format (as exported
   by "Get cookies.txt" extension).

```bash
# Verify cookies file
head -1 /opt/secrets/youtube_cookies.txt
# Should start with: # Netscape HTTP Cookie File

# Test download manually
yt-dlp --cookies /opt/secrets/youtube_cookies.txt \
  --no-warnings --format "best[height<=720]" \
  "https://www.youtube.com/watch?v=VIDEO_ID" \
  -o /tmp/test_download.mp4
```

### 3. Output video has black bars

**Symptom**: Final video shows letterbox/pillarbox bars on sides or top/bottom.

**Checklist**:
1. Verify `combine_videos` uses `VideoAspect.portrait` for TikTok/Reels.
2. Check that clips pass the quality gate (resolution ≥ 480×480).
3. The scale-to-cover + center crop logic in `video.py` should eliminate black
   bars. If the source is squished or distorted, verify the reframe code path
   was used (not the legacy `ColorClip` + `CompositeVideoClip` pad approach).

### 4. Landscape footage appears stretched

**Symptom**: People or objects look vertically/horizontally compressed.

**Checklist**:
1. The reframe pipeline must use scale-to-cover (not scale-to-fit).
2. Verify `video.py` resize block uses:
   ```
   scale=1080:1920:force_original_aspect_ratio=increase
   crop=1080:1920 (center-aligned)
   ```
3. NOT `scale=1080:1920` (which would stretch).

### 5. Audio out of sync

**Symptom**: Narration doesn't match scene visuals timing.

**Checklist**:
1. The pipeline trims each clip to the TTS audio duration automatically.
2. If audio leads video, check `max_clip_duration` vs actual TTS duration.
3. The `_run_pipeline` function aligns combined video to audio in
   `generate_video()`.

---

## Monitoring

### Log locations

```
MPT logs:   /opt/MoneyPrinterTurbo/logs/
Factory:    /opt/mpt-factory/logs/
ffmpeg:     stdout/stderr captured in task logs
```

### Key log patterns to watch

| Pattern | Severity | Action |
|---------|----------|--------|
| `all providers exhausted` | ERROR | Manual investigation — scene failed clean |
| `HTTP Error 403` | ERROR | Refresh YouTube cookies |
| `failed to validate clip` | WARN | Clip rejected by quality gate |
| `combined video → 1080x1920 ✓` | INFO | Normal operation confirmation |

### Metrics to watch

- **YouTube search success rate**: `(searches returning ≥1 result) / total searches`
- **YouTube download success rate**: `downloads succeeding / download attempts`
- **Fallback rate**: `(scenes resolved by non-primary provider) / total scenes`
- **Quality gate rejection rate**: `clips rejected / clips downloaded`
- **Black bar detection rate**: `frames with black bars / total frames`

---

## Troubleshooting

### Pipeline: `FileNotFoundError: combined-1.mp4`

The combined video file was not created. This can happen if:

1. **All scene clips failed quality gate**: Check material download logs.
2. **`combine_videos` crashed during reframe**: Look for `cropped()` errors —
   MoviePy uses `x1`/`y1` not `x`/`y` for the `cropped()` method.
3. **Output directory doesn't exist**: Ensure `task_dir` is writable.

### Pipeline: `RuntimeError: scene N has no usable material`

The fail-clean path was triggered. Verify:

1. Search queries are scene-specific (not generic).
2. At least Pexels API key is valid.
3. YouTube cookies are configured (if YouTube is in the sources list).

### Pipeline: `yt_dlp is not installed`

```bash
pip install yt-dlp
# or
apt-get install yt-dlp
```

---

## Maintenance

### Rotating YouTube cookies

YouTube cookies typically expire within 60–90 days.

1. Re-export cookies from browser using "Get cookies.txt".
2. Replace `/opt/secrets/youtube_cookies.txt`.
3. No service restart needed — cookies are loaded per-download.

### Updating yt-dlp

```bash
pip install --upgrade yt-dlp
yt-dlp --version  # verify ≥ 2024.07.01
```

### Adding a new provider

1. Register in `_provider_and_searcher()` in `material.py`.
2. Add search function (return `List[MaterialInfo]`).
3. Add download function (save to disk, return path).
4. Add to `schema.py` `VideoParams.video_sources` default list.
5. Run quality gate tests against the new provider.
6. Update `factory/worker.py` `default_sources` if needed.

---

## Production Commands

### Full deployment checklist

```bash
# 1. Verify config
grep youtube /opt/MoneyPrinterTurbo/config.toml

# 2. Verify cookies
test -f /opt/secrets/youtube_cookies.txt && echo "cookies OK"

# 3. Run regression tests
cd /opt/MoneyPrinterTurbo && /tmp/mptpy/bin/python3 -m pytest -q test/services/test_youtube_provider.py

# 4. Run factory tests
cd /opt/mpt-factory && .venv/bin/pytest -q tests/

# 5. Test one job
python3 -c "from app.services import task; task.start('prod-test', params, stop_at='video')"

# 6. Verify output
ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 <output.mp4>
# Expected: 1080,1920
```

### Emergency disable

```bash
# Edit config to remove YouTube from sources
sed -i 's/\[\"pexels\", \"pixabay\", \"youtube\]/[\"pexels\", \"pixabay\"]/' /opt/MoneyPrinterTurbo/config.toml

# Restart MPT service
systemctl restart money-printer-turbo

# Restart Factory worker
systemctl restart factory-worker
```
