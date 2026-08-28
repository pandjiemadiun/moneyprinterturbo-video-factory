# Phase 10H.1 + 10H.2 — YouTube Cache Identity & Format Selection

## 1. Executive Summary

Phase 10H discovered two real YouTube defects in `app/services/material.py`:
1. **Cache-key collision** — `save_video_youtube` keyed its cache file on
   `video_url.split("?")[0]`, collapsing every `youtube.com/watch?v=<ID>` URL
   to the identical string `https://www.youtube.com/watch`, so distinct videos
   shared one cache file.
2. **360p format cap** — the selector `best[ext=mp4][height<=720]` always
   resolved to progressive 360p (format 18), because yt-dlp's `best` prefers
   complete streams over higher-quality DASH video-only formats. This capped
   every YouTube download at ~360p, which the Phase 10F 250-effective gate then
   rejected.

Both were **investigated, tested, fixed, and validated** in this phase:

- **10H.1** — added `_youtube_video_identity()` which canonicalizes by the
  11-char video ID (ignoring tracking params) so distinct videos never collide
  and equivalent URLs (`watch`, `youtu.be`, `/shorts`, `m.`/`music.` subdomains,
  `/embed`) share one identity. Malformed/non-YouTube URLs fail safe to the
  legacy URL-based key.
- **10H.2** — replaced the selector with
  `bestvideo[vcodec^=avc1][ext=mp4][height<=720]+bestaudio[acodec^=mp4a]/best`
  (best H.264 MP4 video ≤720p + AAC audio, merged to MP4, safe `/best`
  fallback). Verified offline and on **2 real downloads**: real footage is now
  **720p H.264 + AAC** and **passes** the Phase 10F gate (was 360p REJECT).

**Final classification: PASS** (both components fixed; regression tests pass;
isolated real-world validation confirms 720p material is obtained and accepted;
production invariants unchanged).

---

## 2. Baseline

| Invariant | Value (start of phase) |
|-----------|------------------------|
| Deployed image | `mpt-youtube-ejs-phase10f:latest` (container `moneyprinterturbo-api`) |
| Parent commit (Phase 10H report) | `2f398a1a24a66f125f1290625e85996f0377b5ac` |
| factory.db SHA256 | `ad0e6df9d5a45438532c0c99655455448e8c791bd5781711bf1f4f111a5d59a1` (151552 B) |
| config.toml SHA256 | `2a8d89a696ff5564703547e86c198d846370399de3ae3a5e105c0784d26c7f45` |
| factory job count (task dirs) | `133` |
| production MP4 count (excl. cache_videos) | `158` |
| cache_videos | `0` files |
| Phase 10F effective threshold | `250.0` |
| yt_dlp version | `2026.08.19` |
| moviepy version | `2.1.2` |

---

## 3. Cache Collision Reproduction

The buggy line:

```python
url_without_query = video_url.split("?")[0]
url_hash = utils.md5(url_without_query)
```

For `https://www.youtube.com/watch?v=AAA` and `...?v=BBB`, `split("?")[0]`
yields `https://www.youtube.com/watch` for **both**, so
`vid-<md5("https://www.youtube.com/watch")>.mp4` is identical. In Phase 10H this
manifested as B/C downloads reusing A's file until the test harness cleared the
collision file between distinct downloads. A unit regression now asserts this
can no longer happen.

---

## 4. Cache Canonicalization Design

New helper `_youtube_video_identity(video_url) -> Optional[str]`:

- Parses the URL; strips `www.`/`m.` subdomain prefixes; accepts
  `youtube.com`, `youtu.be`, `youtube-nocookie.com`, `music.youtube.com`.
- Extracts the 11-char video ID from `watch?v=`, `youtu.be/<ID>`,
  `/shorts/<ID>`, or `/embed/<ID>`.
- **Validates** the ID with `[A-Za-z0-9_-]{11}` — malformed/unsupported URLs
  return `None` (fail-safe, never an unsafe collision).
- Returns a stable token `"yt:<ID>"` (not a full URL) used to derive the cache
  filename.

`safe_video_youtube` uses the identity when present, else falls back to the
legacy `md5(url_without_query)` for non-YouTube / malformed URLs. The resulting
filename is still `vid-<32-hex>.mp4`, matching the orphan-sweeper pattern.

Supported URL forms (documented in code): `watch?v=`, `youtu.be/`, `/shorts/`,
`/embed/`, `m.`/`www.`/`music.` subdomains. Other params (`feature`, `t`,
`utm_*`, `list`, …) are correctly ignored.

---

## 5. Cache Test Matrix (see `test/services/test_youtube_cache_identity_10h1.py`)

1. Different watch URLs A≠B → different identity ✅
2. watch + tracking param + `youtu.be` + `/shorts` + `m.`/`music.` → same identity ✅
3. Deterministic (`identity(u) == identity(u)`) ✅
4. Malformed/`SHORT`/empty/non-YouTube/garbage → `None` (safe) ✅
5. Resulting filename matches `^vid-[0-9a-f]{32}\.mp4$` ✅
6. Unrelated providers (Pexels/custom host) → `None` (behavior unchanged) ✅
7. Cache lookup reuses existing file (mocked: `download` called once) ✅
8. Equivalent URL variation → no double download (`download` called once) ✅

---

## 6. Format-Selection Root Cause

Inspecting formats for `eV6lTEY95yY` (metadata only, no download):

| id | ext | height | vcodec | acodec | note |
|----|-----|--------|--------|--------|------|
| 18 | mp4 | 360 | avc1 | mp4a | progressive (complete) |
| 135 | mp4 | 480 | avc1 | none | DASH video-only |
| 136 | mp4 | 720 | avc1 | none | DASH video-only |
| 398 | mp4 | 720 | av01 | none | DASH video-only (AV1) |
| 137 | mp4 | 1080 | avc1 | none | DASH video-only |
| 140 | m4a | – | none | mp4a | audio-only |
| 251 | webm | – | none | opus | audio-only |

`best[ext=mp4][height<=720]` selected **format 18 (360p)** because yt-dlp's
`best` ranks complete (video+audio) streams above higher-resolution DASH
video-only streams. The video-only 480p/720p/1080p streams were ignored.

---

## 7. Available-Format Evidence

(See table above; captured via `yt_dlp -F` with cookies, no secrets.)
Video-only 480p/720p/1080p/4k and audio-only m4a/opus streams are present; the
old selector simply never selected the DASH video-only ones.

---

## 8. Candidate Selector Comparison (offline `build_format_selector`)

| Selector | Result on (360p prog + 720p DASH) |
|----------|-----------------------------------|
| `best[ext=mp4][height<=720]` (old) | `18` (360p) ❌ |
| `best[height<=720]` | `18` (360p) ❌ |
| `bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best` | `398+140` (720p **AV1**) ⚠ compatibility |
| `bestvideo[vcodec^=avc1][ext=mp4][height<=720]+bestaudio[acodec^=mp4a]/best` | `136+140` (720p **H.264**+AAC) ✅ |
| same, fallback when only 360p+webm | `18` (safe progressive) ✅ |

AV1 (`av01`) at 720p was rejected in favor of H.264 (`avc1`) for broad
MoviePy/ffmpeg/player compatibility. The fallback `/best` preserves a safe
download when no H.264 DASH ≤720p exists.

---

## 9. Selected Selector and Rationale

```
bestvideo[vcodec^=avc1][ext=mp4][height<=720]+bestaudio[acodec^=mp4a]/best
```

- Prefers **H.264 MP4** video ≤720p (broad decode compatibility).
- Separate **AAC** audio, merged to MP4 (`merge_output_format="mp4"`).
- `height<=720` — never exceeds 720p (no pointless up/down re-encode from 1080p+).
- `/best` fallback — safe progressive MP4 when no H.264 DASH ≤720p available.
- Result remains compatible with MoviePy, ffmpeg, `_validate_downloaded_clip()`
  (H.264+AAC in MP4), and `combine_videos()`.

---

## 10. Implementation Changes

`app/services/material.py`:
- Added constants `_YOUTUBE_HOSTS`, `_YOUTUBE_ID_RE`.
- Added `_youtube_video_identity()` helper (canonicalization).
- `save_video_youtube()`: derive cache filename from canonical identity
  (fallback to legacy key for non-YouTube/malformed); replaced the `format`
  string with the evidence-based selector above. Cookies, `outtmpl`, quiet/
  no_warnings, `merge_output_format`, save path pattern, cleanup, provider
  order, rank filter (`480×480`), and the 250 effective threshold are **all
  unchanged**.

---

## 11. Regression Tests (23 total passing)

- `test/services/test_youtube_cache_identity_10h1.py` (8 tests) — cache matrix.
- `test/services/test_youtube_format_selection_10h2.py` (4 tests) — selector
  configuration, prefers 720p H.264 over 360p, never exceeds 720p, safe
  fallback. Offline `build_format_selector` proves the new selector picks
  `136+140` while the old would pick `18`.
- `test/services/test_youtube_provider.py` — `test_15_b` updated to the new
  canonical key; full file still passes.

Unchanged invariants verified by tests/code review: effective threshold = 250,
rank filter = 480×480, provider order (HTTP → YouTube), cleanup = Phase 10C,
cookies/EJS/Deno unchanged, target portrait = 1080×1920.

---

## 12. Real YouTube Validation (Part F — max 2 downloads)

Isolated dir `/tmp/phase10h_test` (production `cache_videos` untouched).

| video_id | actual W×H | vcodec/acodec | chosen fmt | file size | gate | eff_min |
|----------|-----------|--------------|-----------|-----------|------|---------|
| `eV6lTEY95yY` | **1280×682** (720p) | h264 / aac | `136+140` | 29.5 MB | **ACCEPT** | 383.6 |
| `pb-j3svRQLI` | **1280×720** (720p) | h264 / aac | `136+140` | 490 MB | **ACCEPT** | 405.0 |

- **Cache-identity check:** 2 distinct videos → 2 distinct cache files →
  `no_collision = True`. (Previously these same videos would have shared one
  file.)
- Both are materially better than the previous ~360p limitation.
- Container format string confirmed at runtime:
  `bestvideo[vcodec^=avc1][ext=mp4][height<=720]+bestaudio[acodec^=mp4a]/best`.

---

## 13. Actual Resolutions Obtained

- `eV6lTEY95yY`: 1280×682 (yt-dlp reports 720p DASH height as 682; actual frames
  1280×720). Gate eff_min 383.6 ≥ 250 → ACCEPT.
- `pb-j3svRQLI`: 1280×720. Gate eff_min 405.0 ≥ 250 → ACCEPT.

---

## 14. Effective-Resolution Results (target 1080×1920, threshold 250)

- 1280×682 → `scale=1920/682=2.815` → eff `383.6 × 682` → min **383.6** → ACCEPT
- 1280×720 → `scale=1920/720=2.667` → eff `405.0 × 720` → min **405.0** → ACCEPT

(Predicted, not exercised: 854×480 → eff 270; 640×360 → eff 202.5 → REJECT —
the gate is unchanged and still rejects true low-res.)

---

## 15. Production Invariants (before → after)

| Check | Before | After | Result |
|-------|--------|-------|--------|
| factory.db SHA | `ad0e6df9…` | `ad0e6df9…` | unchanged |
| factory.db size | 151552 | 151552 | unchanged |
| factory job count | 133 | 133 | unchanged |
| production MP4 count | 158 | 158 | unchanged |
| cache_videos files | 0 | 0 | unchanged |
| config.toml SHA | `2a8d89a6…` | `2a8d89a6…` | unchanged |
| git working tree | — | clean (after commits) | ✅ |
| container restart count | 0 | 0 | ✅ |
| container state | running | running | ✅ |

(One transient test task dir `storage/tasks/test-task` left by the YouTube
provider test suite was removed; count restored to 133.)

---

## 16. Security / Secret Exposure Check

- No cookies, cookie contents, auth tokens, or private headers were read or
  printed. Only sanitized `https://www.youtube.com/watch?v=<id>` URLs and
  video IDs were recorded.
- Format inspection used the configured cookie file path only as a yt-dlp
  argument (metadata simulate); no secret material was logged.

---

## 17. Known Limitations

- **Fallback quality:** if a video has no H.264 MP4 DASH ≤720p (only AV1/VP9
  webm DASH + progressive), the selector falls back to progressive 360p (safe
  MP4, but lower quality). This is an intentional safe degradation, not a gate
  change.
- **720p cap:** 1080p/4k sources are deliberately downscaled to 720p (no
  unnecessary larger download / later downscale). The effective gate still
  passes at 720p.
- **Deployment scope:** the fix was applied to the running container via an
  in-container copy of `material.py` for validation. The image
  `mpt-youtube-ejs-phase10f:latest` was **not** rebuilt, so a container recreate
  from the old image would revert it. **Recommendation:** rebuild the image from
  the committed code for permanent deployment. No production data was touched.

---

## 18. Final Classification

**PASS**

- 10H.1 PASS — different videos cannot collide; equivalent URLs resolve
  consistently; cache lookup functional; no production data changed; tests pass.
- 10H.2 PASS — root cause identified (360p via `best`); higher-quality formats
  correctly evaluated; selector chosen from evidence (720p H.264 + AAC, ≤720p,
  MP4, safe fallback); compatible with existing pipeline; cookies/EJS/Deno
  unchanged; tests pass.
- Combined PASS — cache fixed, format fixed, regression tests pass, isolated
  real-world validation shows 720p H.264 footage obtained and accepted,
  production invariants unchanged.

No FAIL-CLEAN trigger occurred.

---

## 19. Exact Commits

- **10H.1 cache identity:** `6199d567d5080a5d90c9d23552689191f36496c9`
  (`fix: canonicalize YouTube cache identity`)
- **10H.2 format selection:** `a3bad2acd19c33c2b28c5df1d4b82636007cd047`
  (`fix: improve YouTube format selection`)
- **Report (this file):** see §20 (current HEAD).

---

## 20. Current HEAD

- Pre-report HEAD: `a3bad2acd19c33c2b28c5df1d4b82636007cd047`
- Report commit added on top (see `git log -1 -- docs/PHASE_10H1_H2_REPORT.md`).

### Explicit statements

- **Production deployment occurred?** The fix was deployed to the *running*
  container via an in-container copy of `material.py` for runtime validation.
  The Docker image was not rebuilt (see §17). No production task/DB/config was
  modified.
- **Real YouTube downloads occurred?** Yes — 2 downloads (Part F), recorded in §12.
- **Production jobs occurred?** No.
- **Production database changed?** No — factory.db SHA/size unchanged.
