"""
Settings page — Advanced configuration.

Contains: TTS, provider configuration, API configuration,
default video settings, advanced generation settings.
"""

import streamlit as st
import sys
import os
import json
import webbrowser
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from webui.nav_shell import render_nav_shell

from app.models.llm_provider import get_llm_provider, LLM_PROVIDER_REGISTRY, DEFAULT_LLM_PROVIDER_ID

from webui.shared import (
    tr, get_all_fonts, get_all_songs, stable_selectbox, stable_segmented_control,
    _set_runtime_config, _save_runtime_config, _delete_runtime_config,
    _saved_ui_choice, _saved_ui_number, _saved_ui_bool, _saved_ui_color, _saved_ui_text,
    _run_llm_read_operation, _detect_audio_mime,
    _parse_chatterbox_voices, _sync_chatterbox_config_from_session_state,
    get_material_api_keys, save_material_api_keys,
    _build_key_backup_payload, _count_backup_keys, _collect_key_backup,
    _load_transfer_payload, _parse_key_backup, _build_settings_preset_payload,
    _parse_settings_preset, _apply_key_backup, _apply_restored_params,
    get_video_cache_stats, format_file_size,
    get_llm_provider_tips, get_llm_provider_label, get_tts_provider_tips,
    format_llm_connection_error, get_groq_model_ids,
    config, llm, loomloom, video, voice, bgm_service, sonilo_service,
    elevenlabs_music_service, cache_manager, utils,
    DEFAULT_VIDEO_CODEC_OPTION, DEFAULT_SUBTITLE_SETTINGS,
    LOCAL_MATERIAL_EXTENSIONS, CUSTOM_AUDIO_EXTENSIONS,
    VideoAspect, VideoConcatMode, VideoTransitionMode,
    SETTINGS_PRESET_SCHEMA, SETTINGS_PRESET_VERSION, SETTINGS_PRESET_FILE_NAME,
    KEY_BACKUP_SCHEMA, KEY_BACKUP_VERSION, KEY_BACKUP_FILE_NAME,
    PRESET_EXCLUDED_PARAM_KEYS, _RUNTIME_CONFIG_SECTIONS,
    KEY_BACKUP_EXCLUDED_SECTIONS, CREDENTIAL_KEY_SUFFIXES,
    CREDENTIAL_COMPANION_KEYS, CREDENTIAL_WIDGET_STATE_ALIASES,
    support_locales,
    locales, _get_material_api_keys, _save_material_api_keys,
)


def render_settings():
    """Render the Settings page."""
    render_nav_shell(active="render_settings")
    # Headline (### Settings) is owned by the app shell (nav_shell).
    st.markdown(
        "<p class='mpt-page-sub' style='margin-bottom:1.5rem;'>"
        "Configure providers, API keys, and default generation settings.</p>",
        unsafe_allow_html=True,
    )

    # Canonical settings categories (docs/PRODUCTION_RUNTIME_CONTRACT.md §6).
    # Each tab isolates ONE concern so the page is never a 100-field vertical
    # form. Defaults defined here flow into Create/Review as starting values.
    tabs = st.tabs([
        "🎬 Video", "🤖 AI & Script", "🎙 Voice & Audio",
        "🎞 Footage Providers", "🧠 Discovery", "🛠 System",
    ])

    with tabs[0]:
        _render_video_settings()
    with tabs[1]:
        _render_llm_settings()
        _render_script_defaults()
    with tabs[2]:
        _render_voice_audio_settings()
    with tabs[3]:
        _render_material_api_settings()
    with tabs[4]:
        _render_discovery_settings()
    with tabs[5]:
        _render_cache_settings()
        _render_key_backup_settings()
        _render_interface_settings()
        _render_diagnostics()


def _render_llm_settings():
    """Render LLM provider configuration."""
    llm_provider_ids = [provider.provider_id for provider in LLM_PROVIDER_REGISTRY]
    llm_provider_labels = {provider.provider_id: get_llm_provider_label(provider) for provider in LLM_PROVIDER_REGISTRY}
    saved_llm_provider = config.app.get("llm_provider", DEFAULT_LLM_PROVIDER_ID).lower()
    if saved_llm_provider not in llm_provider_ids:
        saved_llm_provider = DEFAULT_LLM_PROVIDER_ID

    llm_provider = stable_selectbox(
        tr("LLM Provider"), options=llm_provider_ids,
        default_value=saved_llm_provider, key="llm_provider_select",
        format_func=lambda provider_id: llm_provider_labels[provider_id],
    )
    _set_runtime_config("app", "llm_provider", llm_provider)
    llm_provider_spec = get_llm_provider(llm_provider)
    if llm_provider_spec is None:
        raise RuntimeError(f"unsupported llm provider: {llm_provider}")

    llm_form_panel, llm_help_panel = st.columns([0.9, 1.1], gap="large", vertical_alignment="top")
    llm_helper = llm_help_panel.container()

    with llm_form_panel:
        llm_api_key = config.app.get(llm_provider_spec.config_key("api_key"), "")
        configured_llm_base_url = config.app.get(llm_provider_spec.config_key("base_url"), "")
        llm_default_base_url = llm_provider_spec.effective_default_base_url
        llm_base_url = configured_llm_base_url or llm_default_base_url
        llm_model_name = llm_provider_spec.resolve_model_name(config.app.get(llm_provider_spec.config_key("model_name"), ""))

        provider_tip_context = {}
        selected_service_endpoint = None
        if llm_provider_spec.service_endpoints:
            selected_service_endpoint = llm_provider_spec.select_service_endpoint(
                configured_llm_base_url,
                has_api_key=bool(str(llm_api_key).strip()),
                prefer_international=(st.session_state.get("ui_language", "en") != "zh"),
            )
            endpoint_options = [endpoint.endpoint_id for endpoint in llm_provider_spec.service_endpoints] + ["custom"]
            default_endpoint_id = selected_service_endpoint.endpoint_id if selected_service_endpoint else "custom"
            endpoint_labels = {
                endpoint.endpoint_id: tr_optional(llm_provider_spec.endpoint_label_key(endpoint.endpoint_id), fallback_language="en") or endpoint.default_label
                for endpoint in llm_provider_spec.service_endpoints
            }
            endpoint_labels["custom"] = tr_optional("Custom API Endpoint", fallback_language="en") or "Custom API Endpoint"
            selected_endpoint_id = stable_selectbox(
                tr_optional(llm_provider_spec.endpoint_selector_label_key, fallback_language="en") or tr("API Platform"),
                options=endpoint_options, default_value=default_endpoint_id,
                key=f"{llm_provider}_service_endpoint_select",
                format_func=lambda endpoint_id: endpoint_labels[endpoint_id],
                help=tr_optional(llm_provider_spec.endpoint_selector_help_key, fallback_language="en") or None,
            )
            selected_service_endpoint = next(
                (endpoint for endpoint in llm_provider_spec.service_endpoints if endpoint.endpoint_id == selected_endpoint_id),
                None,
            )
            if selected_service_endpoint:
                llm_base_url = selected_service_endpoint.base_url
                provider_tip_context.update({
                    "api_key_url": selected_service_endpoint.api_key_url,
                    "default_base_url": selected_service_endpoint.base_url,
                    "model_docs_url": selected_service_endpoint.model_docs_url,
                })
            else:
                llm_base_url = str(configured_llm_base_url or "").strip()

        if llm_provider == "ollama":
            llm_default_base_url = config.get_default_ollama_base_url()
            if not llm_base_url:
                llm_base_url = llm_default_base_url
            docker_hint = ""
            if config.is_running_in_container():
                docker_hint = tr_optional("llm_provider_tips.ollama.docker_hint", fallback_language="en")
            provider_tip_context["docker_hint"] = docker_hint

        tips = get_llm_provider_tips(llm_provider, **provider_tip_context)
        if tips:
            with llm_helper:
                st.info(tips)

        st_llm_api_key = llm_api_key
        if llm_provider_spec.show_api_key:
            st_llm_api_key = st.text_input(tr("API Key"), value=llm_api_key, type="password", key=f"{llm_provider}_api_key_input")

        st_llm_base_url = llm_base_url
        if llm_provider_spec.show_base_url:
            st_llm_base_url = st.text_input(
                tr("Base Url"), value=llm_base_url,
                key=f"{llm_provider}_base_url_{selected_service_endpoint.endpoint_id}_input" if selected_service_endpoint else f"{llm_provider}_base_url_custom_input",
            )

        st_llm_model_name = ""
        if llm_provider == "groq":
            effective_api_key = st_llm_api_key or llm_api_key
            effective_base_url = st_llm_base_url or llm_base_url
            groq_models = get_groq_model_ids(api_key=effective_api_key, base_url=effective_base_url)
            if groq_models:
                selected_index = 0
                if llm_model_name in groq_models:
                    selected_index = groq_models.index(llm_model_name)
                st_llm_model_name = st.selectbox(tr("Model Name"), options=groq_models, index=selected_index, key="groq_model_name_select")
            else:
                st_llm_model_name = st.text_input(tr("Model Name"), value=llm_model_name, key="groq_model_name_input")
                if effective_api_key:
                    st.caption(tr("Groq Model List Load Failed"))
                else:
                    st.caption(tr("Groq API Key Required for Model List"))
        else:
            st_llm_model_name = st.text_input(tr("Model Name"), value=llm_model_name, key=f"{llm_provider}_model_name_input")

        _set_runtime_config("app", llm_provider_spec.config_key("api_key"), st_llm_api_key)
        _set_runtime_config("app", llm_provider_spec.config_key("base_url"), _normalize_provider_override(st_llm_base_url, llm_default_base_url))
        _set_runtime_config("app", llm_provider_spec.config_key("model_name"), _normalize_provider_override(st_llm_model_name, llm_provider_spec.default_model))

        for field in llm_provider_spec.extra_fields:
            field_config_key = llm_provider_spec.config_key(field.config_suffix)
            field_value = st.text_input(
                tr(field.label_key),
                value=(config.app.get(field_config_key, "") or field.default_value),
                type="password" if field.secret else "default",
                key=f"{llm_provider}_{field.config_suffix}_input",
            )
            _set_runtime_config("app", field_config_key, _normalize_provider_override(field_value, field.default_value))

        if st.button(tr("Test LLM Connection"), key="test_llm_connection_button", use_container_width=True, type="secondary", icon=":material/network_check:"):
            with config.try_runtime_config_lock() as lock_acquired:
                if not lock_acquired:
                    st.warning(tr("Runtime Configuration Busy"))
                else:
                    with st.spinner(tr("Testing LLM Connection")):
                        connection_ok, connection_error, connection_elapsed = llm.test_connection()
                    if not lock_acquired:
                        connection_ok = None
                    elif connection_ok:
                        st.success(tr("LLM Connection Test Succeeded").format(
                            provider=llm_provider_labels[llm_provider], model=st_llm_model_name or "-", elapsed=f"{connection_elapsed:.2f}",
                        ))
                    else:
                        connection_error = format_llm_connection_error(llm_provider, st_llm_base_url, connection_error)
                        st.error(tr("LLM Connection Test Failed").format(error=connection_error))


def _render_material_api_settings():
    """Render material API key configuration."""
    pexels_api_key = _get_material_api_keys("pexels_api_keys")
    pexels_api_key = st.text_input(tr("Pexels API Key"), value=pexels_api_key, type="password", key="pexels_api_keys_input")
    _save_material_api_keys("pexels_api_keys", pexels_api_key)

    pixabay_api_key = _get_material_api_keys("pixabay_api_keys")
    pixabay_api_key = st.text_input(tr("Pixabay API Key"), value=pixabay_api_key, type="password", key="pixabay_api_keys_input")
    _save_material_api_keys("pixabay_api_keys", pixabay_api_key)

    coverr_api_key = _get_material_api_keys("coverr_api_keys")
    coverr_api_key = st.text_input(tr("Coverr API Key"), value=coverr_api_key, type="password", key="coverr_api_keys_input")
    _save_material_api_keys("coverr_api_keys", coverr_api_key)

    wavespeed_api_key = _get_material_api_keys("wavespeed_api_keys")
    wavespeed_api_key = st.text_input(tr("WaveSpeed API Key"), value=wavespeed_api_key, type="password", key="wavespeed_api_keys_input")
    _save_material_api_keys("wavespeed_api_keys", wavespeed_api_key)


def _render_key_backup_settings():
    """Render key backup export/import."""
    backup_message = st.session_state.pop("key_backup_message", None)
    if backup_message:
        message_type, message = backup_message
        if message_type == "success":
            st.success(message)
        else:
            st.error(message)

    st.caption(tr("Key Backup Help"))
    st.warning(tr("Key Backup Warning"))

    backup_payload = _build_key_backup_payload(_RUNTIME_CONFIG_SECTIONS, config.project_version)
    backup_key_count = _count_backup_keys(backup_payload["keys"])
    st.caption(tr("Key Backup Summary").format(count=backup_key_count))
    st.download_button(
        tr("Export Keys"),
        data=json.dumps(backup_payload, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name=KEY_BACKUP_FILE_NAME, mime="application/json",
        disabled=backup_key_count == 0, use_container_width=True,
        key="export_key_backup_button", icon=":material/download:",
    )

    uploaded_backup = st.file_uploader(tr("Import Keys"), type=["json"], key="key_backup_uploader")
    if uploaded_backup is None:
        return
    if st.session_state.get("key_backup_file_id") == uploaded_backup.file_id:
        return
    st.session_state["key_backup_file_id"] = uploaded_backup.file_id
    try:
        restored_keys = _parse_key_backup(uploaded_backup.getvalue(), _RUNTIME_CONFIG_SECTIONS)
    except Exception as e:
        logger.warning(f"failed to import key backup: {e}")
        st.session_state["key_backup_message"] = ("error", tr("Key Restore Failed"))
    else:
        restored_count = _apply_key_backup(restored_keys)
        _save_runtime_config()
        logger.info(f"restored keys from backup file: count={restored_count}")
        st.session_state["key_backup_message"] = ("success", tr("Keys Restored").format(count=restored_count))
    st.rerun(scope="app")


def _render_cache_settings():
    """Render cache management settings."""
    cleanup_message = st.session_state.pop("video_cache_cleanup_message", None)
    if cleanup_message:
        message_type, message = cleanup_message
        if message_type == "success":
            st.success(message)
        else:
            st.warning(message)

    st.caption(tr("Video Cache Directory"))
    st.code(cache_manager.video_cache_dir(), language="text")

    total_stats = get_video_cache_stats()
    metric_count, metric_size, metric_oldest = st.columns(3)
    metric_count.metric(tr("Cache File Count"), total_stats.file_count)
    metric_size.metric(tr("Cache Total Size"), format_file_size(total_stats.total_size))
    oldest_text = datetime.fromtimestamp(total_stats.oldest_mtime).strftime("%Y-%m-%d") if total_stats.oldest_mtime is not None else "-"
    metric_oldest.metric(tr("Oldest Cache Date"), oldest_text)

    st.caption(tr("Video Cache Management Help"))
    cleanup_options = (30, 7, 90, None)
    cleanup_labels = {30: tr("Cache Older Than 30 Days"), 7: tr("Cache Older Than 7 Days"), 90: tr("Cache Older Than 90 Days"), None: tr("All Video Cache")}
    max_age_days = st.selectbox(tr("Cache Cleanup Range"), options=cleanup_options, format_func=lambda value: cleanup_labels[value], key="video_cache_cleanup_range")
    cleanup_preview = get_video_cache_stats(max_age_days=max_age_days)
    st.info(tr("Cache Cleanup Preview").format(count=cleanup_preview.file_count, size=format_file_size(cleanup_preview.total_size)))

    confirm_nonce = st.session_state.get("video_cache_cleanup_confirm_nonce", 0)
    confirmed = st.checkbox(tr("Confirm Cache Cleanup"), key=f"video_cache_cleanup_confirm_{confirm_nonce}")
    # Class R1 fix: st.columns(3) starved each button to ~50px and wrapped
    # "Clean Cache Now" to 5 lines on 320px. Same .mpt-action-row contract:
    # min 160px, wrap to fewer columns on narrow screens.
    with st.container(key="cache_actions"):
        if st.button(tr("Refresh Cache Stats"), key="refresh_video_cache_stats", use_container_width=True, icon=":material/refresh:"):
            get_video_cache_stats.clear()
            st.rerun(scope="fragment")
        if st.button(tr("Open Cache Directory"), key="open_video_cache_directory", use_container_width=True, icon=":material/folder_open:"):
            webbrowser.open(Path(cache_manager.video_cache_dir()).as_uri())
        cleanup_disabled = not confirmed or cleanup_preview.file_count == 0
        if st.button(tr("Clean Cache Now"), key="clean_video_cache_now", type="primary", disabled=cleanup_disabled, use_container_width=True, icon=":material/delete_sweep:"):
            result = cache_manager.clean_video_cache(max_age_days=max_age_days)
            message_key = "Cache Cleanup Completed With Failures" if result.failed_count else "Cache Cleanup Completed"
            st.session_state["video_cache_cleanup_message"] = (
                "warning" if result.failed_count else "success",
                tr(message_key).format(count=result.deleted_count, size=format_file_size(result.deleted_size), failed=result.failed_count),
            )
            st.session_state["video_cache_cleanup_confirm_nonce"] = confirm_nonce + 1
            get_video_cache_stats.clear()
            st.rerun(scope="fragment")


def _render_interface_settings():
    """Render interface settings."""
    hide_log = st.checkbox(tr("Hide Log"), value=config.ui.get("hide_log", False), key="hide_log_checkbox")
    _set_runtime_config("ui", "hide_log", hide_log)


def _normalize_provider_override(value, default_value):
    """Normalize provider override values."""
    if value == default_value or value == str(default_value):
        return ""
    return value


def tr_optional(key, fallback_language=""):
    loc = locales.get(st.session_state.get("ui_language", "en"), {})
    value = loc.get("Translation", {}).get(key, "")
    if not value and fallback_language:
        fallback_loc = locales.get(fallback_language, {})
        value = fallback_loc.get("Translation", {}).get(key, "")
    return value if value else ""


# ── Product-shell category renderers ────────────────────────────────────────
# These surface defaults into Settings. Create/Review consume the same config
# keys, so "defaults come from Settings" without rewriting the engine.

def _render_video_settings():
    """🎬 Video — visual-production defaults surfaced into Settings."""
    st.subheader(tr("Video Defaults"))
    video_sources = [
        (tr("Pexels"), "pexels"), (tr("Pixabay"), "pixabay"), (tr("Coverr"), "coverr"),
        (tr("YouTube"), "youtube"), (tr("WaveSpeed AI Video"), "wavespeed"),
        (tr("Shengsuan Cloud AI Video"), "loomloom"), (tr("Local file"), "local"),
    ]
    saved_video_source = config.app.get("video_source", "pexels")
    video_source = stable_selectbox(
        tr("Default Video Source"), options=[v for _, v in video_sources],
        default_value=saved_video_source, key="mpts_video_source_select",
        format_func=lambda value: dict((v, label) for label, v in video_sources)[value],
    )
    _set_runtime_config("app", "video_source", video_source)

    video_aspect_ratios = [(tr("Portrait"), VideoAspect.portrait.value), (tr("Landscape"), VideoAspect.landscape.value)]
    aspect_values = [v for _, v in video_aspect_ratios]
    saved_aspect = _saved_ui_choice(f"video_aspect_{video_source}", aspect_values, video_aspect_ratios[0][1])
    selected_aspect = stable_selectbox(
        tr("Default Video Ratio"), options=aspect_values, default_value=saved_aspect,
        key="mpts_video_aspect_select",
        format_func=lambda value: dict((v, label) for label, v in video_aspect_ratios)[value],
    )
    _set_runtime_config("ui", f"video_aspect_{video_source}", selected_aspect)

    durations = [2, 3, 4, 5, 6, 7, 8, 9, 10]
    clip_duration = stable_selectbox(
        tr("Default Clip Duration (sec)"), options=durations,
        default_value=_saved_ui_choice("video_clip_duration", durations, 3), key="mpts_clip_duration",
    )
    _set_runtime_config("ui", "video_clip_duration", clip_duration)

    counts = [1, 2, 3, 4, 5]
    video_count = stable_selectbox(
        tr("Default Videos Per Batch"), options=counts,
        default_value=_saved_ui_choice("video_count", counts, 1), key="mpts_video_count",
    )
    _set_runtime_config("ui", "video_count", video_count)

    st.subheader(tr("Subtitle Defaults"))
    subtitle_enabled = st.checkbox(
        tr("Enable Subtitles"),
        value=_saved_ui_bool("subtitle_enabled", DEFAULT_SUBTITLE_SETTINGS["subtitle_enabled"]),
        key="mpts_subtitle_enabled",
    )
    _set_runtime_config("ui", "subtitle_enabled", subtitle_enabled)
    font_names = get_all_fonts()
    saved_font = config.ui.get("font_name", DEFAULT_SUBTITLE_SETTINGS["font_name"])
    font_idx = font_names.index(saved_font) if saved_font in font_names else 0
    font_name = stable_selectbox(
        tr("Default Font"), options=font_names or [""],
        default_value=(font_names[font_idx] if font_names else ""),
        key="mpts_font_name", disabled=not subtitle_enabled,
    )
    _set_runtime_config("ui", "font_name", font_name)

    subtitle_positions = [(tr("Top"), "top"), (tr("Center"), "center"), (tr("Bottom"), "bottom"), (tr("Custom"), "custom")]
    pos_values = [v for _, v in subtitle_positions]
    saved_pos = _saved_ui_choice("subtitle_position", pos_values, DEFAULT_SUBTITLE_SETTINGS["subtitle_position"])
    position = stable_selectbox(
        tr("Default Subtitle Position"), options=pos_values, default_value=saved_pos,
        key="mpts_subtitle_position",
        format_func=lambda value: dict((v, label) for label, v in subtitle_positions)[value],
        disabled=not subtitle_enabled,
    )
    _set_runtime_config("ui", "subtitle_position", position)


def _render_script_defaults():
    """🤖 AI & Script — script-generation defaults surfaced into Settings."""
    st.subheader(tr("Script Defaults"))
    video_languages = [(tr("Auto Detect"), "")] + [(code, code) for code in support_locales]
    language_values = [v for _, v in video_languages]
    saved_language = _saved_ui_choice("video_language", language_values, "")
    language = stable_selectbox(
        tr("Default Script Language"), options=language_values, default_value=saved_language,
        key="mpts_script_language",
        format_func=lambda value: dict((v, label) for label, v in video_languages)[value],
    )
    _set_runtime_config("ui", "video_language", language)

    script_prompt = st.text_area(
        tr("Video Script Prompt"), value=_saved_ui_text("video_script_prompt", max_length=None),
        height=120, key="mpts_script_prompt_input",
    )
    _set_runtime_config("ui", "video_script_prompt", script_prompt)

    paragraph_number = st.number_input(
        tr("Default Paragraph Number"), min_value=1, max_value=8,
        value=int(_saved_ui_number("paragraph_number", 1, 1, 8, int)), key="mpts_paragraph_number",
    )
    _set_runtime_config("ui", "paragraph_number", int(paragraph_number))


def _render_voice_audio_settings():
    """🎙 Voice & Audio — voice defaults surfaced into Settings (full preview on Create)."""
    st.subheader(tr("Voice Defaults Applied On Create"))
    tts_server_options = ["azure-tts-v1", "azure-tts-v2", "siliconflow", "gemini-tts",
                          "mimo-tts", "minimax-tts", "elevenlabs", "chatterbox", "fish_audio"]
    tts_server_labels = {
        "azure-tts-v1": "Azure TTS V1", "azure-tts-v2": "Azure TTS V2",
        "siliconflow": "SiliconFlow TTS", "gemini-tts": "Google Gemini TTS",
        "mimo-tts": "Xiaomi MiMo TTS", "minimax-tts": "MiniMax TTS",
        "elevenlabs": "ElevenLabs TTS", "chatterbox": "Chatterbox TTS",
        "fish_audio": "Fish Audio TTS",
    }
    saved_tts = config.ui.get("tts_server", "azure-tts-v1")
    tts_server = stable_selectbox(
        tr("Default Voiceover Service"), options=tts_server_options,
        default_value=(saved_tts if saved_tts in tts_server_options else "azure-tts-v1"),
        key="mpts_tts_server",
        format_func=lambda value: tts_server_labels[value],
    )
    _set_runtime_config("ui", "tts_server", tts_server)

    voice_name = st.text_input(tr("Default Voice Name (optional)"), value=config.ui.get("voice_name", ""), key="mpts_voice_name")
    if voice_name:
        _set_runtime_config("ui", "voice_name", voice_name)
    st.caption("Select a voice and use the voice preview on the Create page to test it.")

    voice_mode_labels = {"tts": tr("Automatic Voiceover"), "upload": tr("Upload Voiceover"), "none": tr("No Voiceover")}
    saved_voice_mode = config.ui.get("voice_mode", "tts") if config.ui.get("voice_mode") in {"tts", "upload", "none"} else "tts"
    voice_mode = stable_segmented_control(
        tr("Default Voiceover Mode"), options=["tts", "upload", "none"],
        default_value=saved_voice_mode, key="mpts_voice_mode",
        format_func=lambda value: voice_mode_labels[value], width="stretch",
    )
    _set_runtime_config("ui", "voice_mode", voice_mode)

    if voice_mode == "tts":
        volumes = [0.6, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0, 4.0, 5.0]
        voice_volume = stable_selectbox(tr("Default Voice Volume"), options=volumes,
            default_value=_saved_ui_choice("voice_volume", volumes, 1.0), key="mpts_voice_volume",
            format_func=lambda value: f"{int(value * 100)}%")
        _set_runtime_config("ui", "voice_volume", voice_volume)
        rates = [0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 1.8, 2.0]
        voice_rate = stable_selectbox(tr("Default Voice Speed"), options=rates,
            default_value=_saved_ui_choice("voice_rate", rates, 1.0), key="mpts_voice_rate",
            format_func=lambda value: f"{value:.1f}x")
        _set_runtime_config("ui", "voice_rate", voice_rate)

    st.subheader(tr("Background Music"))
    custom_bgm = st.text_input(tr("Custom BGM File Path"), value=_saved_ui_text("custom_bgm_file"), key="mpts_custom_bgm")
    if custom_bgm:
        _set_runtime_config("ui", "custom_bgm_file", custom_bgm)


def _render_discovery_settings():
    """🧠 Discovery — geography/language/category defaults + visual-producibility gate."""
    st.subheader(tr("Discovery Defaults"))
    geos = ["ID", "US", "GB", "AU", "MY", "SG"]
    geo = stable_selectbox(tr("Geography"), options=geos,
        default_value=_saved_ui_choice("discover_geo", geos, "ID"), key="mpts_discover_geo")
    _set_runtime_config("ui", "discover_geo", geo)

    langs = ["id", "en"]
    language = stable_selectbox(tr("Language"), options=langs,
        default_value=_saved_ui_choice("discover_language", langs, "id"), key="mpts_discover_language")
    _set_runtime_config("ui", "discover_language", language)

    categories = ["general", "technology", "business", "sports", "entertainment", "health", "science"]
    category = stable_selectbox(tr("Category"), options=categories,
        default_value=_saved_ui_choice("discover_category", categories, "general"), key="mpts_discover_category")
    _set_runtime_config("ui", "discover_category", category)

    strict = st.checkbox(tr("Strict Visual Feasibility"),
        value=_saved_ui_bool("visual_producibility_strict", False), key="mpts_visual_strict")
    _set_runtime_config("ui", "visual_producibility_strict", strict)
    st.caption("When on, only topics with available Pexels/Pixabay/Coverr footage are recommended.")


def _render_diagnostics():
    """🛠 System — read-only runtime diagnostics."""
    st.subheader(tr("Diagnostics"))
    version = getattr(config, "project_version", None) or "unknown"
    st.caption(f"Application version: {version}")
    config_path = getattr(config, "config_file", None) or ""
    if config_path:
        st.caption(f"Config file: {config_path}")
    try:
        total = get_video_cache_stats()
        st.caption(f"Cache: {total.file_count} files, {format_file_size(total.total_size)}")
    except Exception as exc:
        st.caption(f"Cache stats unavailable: {exc}")
