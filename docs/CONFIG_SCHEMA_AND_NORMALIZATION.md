# Canonical Configuration Schema & Normalization

This document is the permanent reference for the canonical `config.toml` schema used by
the **MPT WebUI** (`webui/`) and the **MPT API** (`app/`). It explains why the file may
change shape on a render (the *config normalization* behavior) and why **no production
credentials are ever lost** by that normalization.

Source of truth for the schema: `config.example.toml` in the repository root.
Config engine: `app/config/config.py` (shared by the WebUI and the API).

---

## 1. Canonical sections

`config.toml` is a TOML file whose canonical top-level sections are exactly:

| Section | Managed by | Purpose |
|---|---|---|
| `log_level`, `listen_host`, `listen_port` | `app` base config | server/observability |
| `app` | `app` | global runtime flags: `endpoint`, `video_source`, `pexels_api_keys`, `pixabay_api_keys`, `script_generation_backend`, `llm_provider`, etc. |
| `whisper` | `app` | Whisper transcription (model_size/device/compute_type) |
| `proxy` | `app` | optional proxy |
| `azure` | `app` | Azure Speech TTS (speech_key/speech_region) |
| `siliconflow` | `app` | SiliconFlow API key |
| `minimax_tts` | `app` | MiniMax TTS (api_key/base_url/model_id/voice_id/…) |
| `elevenlabs` | `app` | ElevenLabs TTS (api_key/model_id/…) |
| `chatterbox` | `app` | Chatterbox TTS (base_url/api_key/model_id/voices) |
| `fish_audio` | `app` | Fish Audio TTS (api_key/model/voices) |
| `ui` | WebUI | UI preferences: discover_geo/language/category, video_source, clip duration, voice_mode, subtitle settings, font, etc. |

**The credentials that the canonical engine actually consumes live here — do not place
them under legacy provider sections (see §3).**

---

## 2. How config is loaded and saved

`app/config/config.py`:

- `config_file = f"{root_dir}/config.toml"` — the single, bind-mounted runtime config.
- At **module import** (once per process): `_cfg = load_config()` parses `config.toml`
  (falling back to `config.example.toml` if the file is missing). The module-level
  section objects (`app`, `azure`, `siliconflow`, `minimax_tts`, `elevenlabs`,
  `chatterbox`, `fish_audio`, `ui`, plus `whisper`/`proxy` read from `_cfg`) are
  populated **from the file**.
- `_SynchronizedConfig` (a `dict` subclass) makes in-process writes lock-serialized.
- `save_config()` writes the file with a fixed, explicit set of sections:

  ```python
  config_to_save = dict(_cfg)                 # base: log_level/listen_*/whisper/proxy (+ example defaults)
  config_to_save["app"]    = dict(app)
  config_to_save["azure"]   = dict(azure)
  config_to_save["siliconflow"] = dict(siliconflow)
  config_to_save["minimax_tts"] = dict(minimax_tts)
  config_to_save["elevenlabs"] = dict(elevenlabs)
  config_to_save["chatterbox"] = dict(chatterbox)
  config_to_save["fish_audio"] = dict(fish_audio)
  config_to_save["ui"] = dict(ui)
  toml.dumps(config_to_save)
  ```

- The WebUI triggers a non-blocking save via `try_save_config()` (called from
  `webui/shared.py::_save_runtime_config` on explicit settings changes, and on page
  reruns that touch runtime config). The save is serialized and atomic.

> **Consequence:** `save_config()` writes **only** the canonical section list above.
> Any extra/unknown sections present in the file are **not** written back and are
> therefore dropped on the next save.

---

## 3. Why legacy provider sections may disappear (and why it is safe)

Older MoneyPrinterTurbo configs stored footage-provider credentials under dedicated
sections (`[pexels]`, `[pixabay]`, `[coverr]`, `[wavespeed]`, `[gemini]`, `[groq]`).
The **canonical** engine does **not** consume those sections:

- Footage keys are read from **`[app]`** — e.g. `get_api_key("pexels_api_keys")`
  in `app/services/material.py` resolves the Pexels key from `config["app"]["pexels_api_keys"]`,
  not from a `[pexels]` section.
- The legacy `[pexels]`/`[pixabay]`/… sections are therefore **redundant duplicates**
  of keys that already live in `[app]`.

When a canonical page (notably **Settings / System** and **Production / Create**) renders
and triggers `save_config()`, the file is re-serialized with **only** the canonical
sections. The redundant legacy sections (`[pexels]`, `[pixabay]`, `[coverr]`,
`[wavespeed]`, `[gemini]`, `[groq]`) are **dropped**, while `[app]` (which holds the
real `pexels_api_keys`/`pixabay_api_keys`) is **preserved**.

**No credentials are lost:** the operational keys (`app.pexels_api_keys`,
`app.pixabay_api_keys`, `video_source`, `endpoint`, TTS/voice defaults in `[ui]`/`[app]`)
are all in sections that `save_config()` writes, so they survive normalization.

---

## 4. Fixed-point (idempotent) behavior

A freshly normalized file may be missing a few canonical default keys that the current
pages read (e.g. `ui.discover_geo`, `ui.discover_language`, `ui.discover_category`,
`app.video_sources`, `app.enable_sqlite_state`, `app.youtube_cookies_file`,
`app.video_aspect_youtube`, `ui.visual_producibility_strict`). On the next render that
calls `save_config()`, these defaults are added. After all canonical keys are present,
the file reaches its **fixed point**: re-rendering any page produces a byte-identical
`config.toml` (save is a no-op when the serialized content equals the on-disk file —
see the `f.read() == serialized_config` short-circuit in `save_config()`).

**Operational guidance**

- Treat `config.example.toml` as the schema source of truth.
- Keep credentials in the canonical sections (`[app]` for footage API keys; `[azure]`,
  `[minimax_tts]`, `[elevenlabs]`, `[chatterbox]`, `[fish_audio]`, `[siliconflow]`
  for provider/TTS keys).
- `config.toml` sha may differ from an historical snapshot after a normalization pass;
  what matters is that the **canonical sections, credentials, `endpoint`, and
  `video_source` are intact and the file is at a stable fixed point** (idempotent).
- Do **not** hand-author legacy `[pexels]`/`[pixabay]`/… sections as the source of
  truth — they are not read by the canonical engine and will be normalized away.

---

## 5. Production state (as of this writing)

- `config.toml` is at its canonical fixed point (idempotent across 28+ live renders).
- `[app].pexels_api_keys` and `[app].pixabay_api_keys` populated; `video_source=pexels`;
  `endpoint=https://goldtrader.website`.
- `tasks.db`, MP4 artifacts, and storage are unchanged by UI verification (no production
  jobs were created, retried, or deleted).
