"""
Create page — Guided video creation workflow.

Progressive disclosure: Topic → Format → Voice → Visuals → Review → Create.
Advanced technical controls under "Advanced options".
Supports prefill from Discover/Explore opportunities.
"""

import streamlit as st
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from webui.nav_shell import render_nav_shell

from webui.shared import (
    tr, get_all_fonts, get_all_songs, stable_selectbox, stable_segmented_control,
    sync_script_order_concat_mode, reset_script_system_prompt, reset_subtitle_settings,
    _set_runtime_config, _save_runtime_config, _delete_runtime_config,
    _saved_ui_choice, _saved_ui_number, _saved_ui_bool, _saved_ui_color, _saved_ui_text,
    _run_llm_read_operation, _build_uploaded_file_path, _detect_audio_mime,
    _parse_chatterbox_voices, _sync_chatterbox_config_from_session_state,
    get_material_api_keys, save_material_api_keys, support_locales,
    _effective_loomloom_api_token, _create_loomloom_script_backend, _create_loomloom_video_backend,
    _current_loomloom_video_quote_context, _loomloom_video_scene_prompts,
    _loomloom_script_signature, _loomloom_video_signature,
    _estimate_voiceover_duration_range, _get_voice_preview_sample,
    _voice_preview_fingerprint, _credential_signature, _get_voice_preview_provider_signature,
    _get_reusable_full_voice_preview,
    render_current_generation_task, prepare_generation_task,
    add_active_generation_task, remove_active_generation_task,
    webui_api_client, webui_task,
    VOICE_MODE_TTS, VOICE_MODE_UPLOAD, VOICE_MODE_NONE,
    DEFAULT_VIDEO_CODEC_OPTION, DEFAULT_SUBTITLE_SETTINGS,
    LOCAL_MATERIAL_EXTENSIONS, CUSTOM_AUDIO_EXTENSIONS,
    VideoParams, VideoAspect, VideoConcatMode, VideoTransitionMode,
    MaterialInfo,
    config, llm, loomloom, video, voice, bgm_service, sonilo_service,
    elevenlabs_music_service, cache_manager, utils,
    sonilo, elevenlabs_music,
)


def render_create():
    """Render the Create page."""
    render_nav_shell(active="render_create")
    # Headline (### Create) is owned by the app shell (nav_shell).
    st.markdown(
        "<p class='mpt-page-sub' style='margin-bottom:1.5rem;'>"
        "Generate a video from your topic. Guided workflow with progressive disclosure.</p>",
        unsafe_allow_html=True,
    )

    # Consume prefill values from Discover/Explore
    _consume_prefill_values()

    params = VideoParams(video_subject="")
    params.match_materials_to_script = bool(st.session_state.get("match_materials_to_script", False))

    # ── Selected opportunity context (from Discover / Review) ──────────────
    _render_selected_opportunity_banner()

    # ── Step 1: IDEA ───────────────────────────────────────────────────────
    with st.container(border=True):
        st.subheader("① IDEA")
        params.video_subject = st.text_area(
            tr("Video Subject"),
            placeholder=tr("Video Subject Placeholder"),
            height=96,
            key="video_subject",
        ).strip()

        video_languages = [(tr("Auto Detect"), "")]
        for code in support_locales:
            video_languages.append((code, code))
        selected_language_code = stable_selectbox(
            tr("Script Language"),
            options=[value for _, value in video_languages],
            default_value=_saved_ui_choice("video_language", [value for _, value in video_languages], ""),
            key="script_language_select",
            format_func=lambda value: dict((v, label) for label, v in video_languages)[value],
        )
        params.video_language = selected_language_code
        _set_runtime_config("ui", "video_language", params.video_language)

    # ── Step 2: CREATIVE BRIEF ─────────────────────────────────────────────
    with st.container(border=True):
        st.subheader("② Creative Brief")

        # Script generation backend
        script_backend_options = ["local", "loomloom"]
        script_backend_labels = {
            "local": tr("Local LLM Script Generation"),
            "loomloom": tr("Shengsuan Cloud Batch Script Generation"),
        }
        script_generation_backend = stable_selectbox(
            tr("Script Generation Method"),
            options=script_backend_options,
            default_value=_effective_script_generation_backend(),
            key="script_generation_backend_select",
            format_func=lambda value: script_backend_labels[value],
        )
        _set_runtime_config("app", "script_generation_backend", script_generation_backend)

        if script_generation_backend == "loomloom":
            _render_loomloom_script_generation(params)
        else:
            _render_local_script_generation(params)

        params.video_script = st.text_area(
            tr("Video Script"),
            help=tr("Video Script Help"),
            height=180,
            key="video_script",
        )

        # Keywords
        _video_source_for_keywords = config.app.get("video_source", "pexels")
        if _video_source_for_keywords == "youtube":
            keywords_label = tr("YouTube Keywords Label")
            keywords_help = tr("YouTube Keywords Help")
        else:
            keywords_label = tr("Video Keywords")
            keywords_help = tr("Video Keywords Help")

        params.video_terms = st.text_area(keywords_label, help=keywords_help, key="video_terms")

    # ── Step 3: PRODUCTION SETTINGS — VISUALS ──────────────────────────────
    with st.container(border=True):
        st.subheader("③ Production Settings — Visuals")

        video_sources = [
            (tr("Pexels"), "pexels"), (tr("Pixabay"), "pixabay"), (tr("Coverr"), "coverr"),
            (tr("YouTube"), "youtube"), (tr("WaveSpeed AI Video"), "wavespeed"),
            (tr("Shengsuan Cloud AI Video"), "loomloom"), (tr("Local file"), "local"),
        ]
        saved_video_source_name = config.app.get("video_source", "pexels")
        params.video_source = stable_selectbox(
            tr("Video Source"),
            options=[value for _, value in video_sources],
            default_value=saved_video_source_name,
            key="video_source_select",
            format_func=lambda value: dict((v, label) for label, v in video_sources)[value],
        )
        _set_runtime_config("app", "video_source", params.video_source)

        uploaded_files = []
        if params.video_source == "local":
            local_file_types = sorted(extension.removeprefix(".") for extension in LOCAL_MATERIAL_EXTENSIONS)
            uploaded_files = st.file_uploader(
                tr("Upload Local Files"),
                type=local_file_types + [ft.upper() for ft in local_file_types],
                accept_multiple_files=True,
                key="local_video_materials_uploader",
            )

        # Aspect ratio
        video_aspect_ratios = [(tr("Portrait"), VideoAspect.portrait.value), (tr("Landscape"), VideoAspect.landscape.value)]
        default_aspect_index = 1 if params.video_source == "coverr" else 0
        video_aspect_values = [value for _, value in video_aspect_ratios]
        video_aspect_config_key = f"video_aspect_{params.video_source}"
        selected_aspect_ratio = stable_selectbox(
            tr("Video Ratio"),
            options=video_aspect_values,
            default_value=_saved_ui_choice(video_aspect_config_key, video_aspect_values, video_aspect_ratios[default_aspect_index][1]),
            key=f"video_aspect_for_{params.video_source}",
            format_func=lambda value: dict((v, label) for label, v in video_aspect_ratios)[value],
        )
        params.video_aspect = VideoAspect(selected_aspect_ratio)
        _set_runtime_config("ui", video_aspect_config_key, params.video_aspect.value)

        # Clip duration and count
        video_clip_durations = [2, 3, 4, 5, 6, 7, 8, 9, 10]
        params.video_clip_duration = stable_selectbox(
            tr("Clip Duration"), options=video_clip_durations,
            default_value=_saved_ui_choice("video_clip_duration", video_clip_durations, 3),
            key="video_clip_duration_select", help=tr("Clip Duration Help"),
        )
        _set_runtime_config("ui", "video_clip_duration", params.video_clip_duration)

        video_count_options = [1, 2, 3, 4, 5]
        params.video_count = stable_selectbox(
            tr("Number of Videos Generated Simultaneously"), options=video_count_options,
            default_value=_saved_ui_choice("video_count", video_count_options, 1),
            key="video_count_select",
        )
        _set_runtime_config("ui", "video_count", params.video_count)

    # ── Step 4: PRODUCTION SETTINGS — VOICE ────────────────────────────────
    with st.container(border=True):
        st.subheader("④ Production Settings — Voice")

        voice_mode_options = [VOICE_MODE_TTS, VOICE_MODE_UPLOAD, VOICE_MODE_NONE]
        voice_mode_labels = {
            VOICE_MODE_TTS: tr("Automatic Voiceover"),
            VOICE_MODE_UPLOAD: tr("Upload Voiceover"),
            VOICE_MODE_NONE: tr("No Voiceover"),
        }
        saved_tts_server = config.ui.get("tts_server", "azure-tts-v1")
        saved_voice_mode = config.ui.get("voice_mode")
        if saved_voice_mode not in {VOICE_MODE_TTS, VOICE_MODE_UPLOAD, VOICE_MODE_NONE}:
            saved_voice_mode = VOICE_MODE_NONE if saved_tts_server == voice.NO_VOICE_NAME else VOICE_MODE_TTS
        voice_mode = stable_segmented_control(
            tr("Voiceover Mode"), options=voice_mode_options,
            default_value=saved_voice_mode, key="voice_mode_control",
            format_func=lambda value: voice_mode_labels[value], width="stretch",
        )
        _set_runtime_config("ui", "voice_mode", voice_mode)
        tts_mode_enabled = voice_mode == VOICE_MODE_TTS

        tts_servers = [
            ("azure-tts-v1", "Azure TTS V1"), ("azure-tts-v2", "Azure TTS V2"),
            ("siliconflow", "SiliconFlow TTS"), ("gemini-tts", "Google Gemini TTS"),
            ("mimo-tts", "Xiaomi MiMo TTS"), ("minimax-tts", "MiniMax TTS"),
            ("elevenlabs", "ElevenLabs TTS"), ("chatterbox", "Chatterbox TTS"),
            ("fish_audio", "Fish Audio TTS"),
        ]
        tts_server_values = [sv for sv, _ in tts_servers]
        if saved_tts_server not in tts_server_values:
            saved_tts_server = "azure-tts-v1"

        if tts_mode_enabled:
            selected_tts_server = stable_selectbox(
                tr("Voiceover Service"), options=tts_server_values,
                default_value=saved_tts_server, key="tts_server_select",
                format_func=lambda value: dict((v, label) for v, label in tts_servers)[value],
            )
        else:
            selected_tts_server = saved_tts_server
        _set_runtime_config("ui", "tts_server", selected_tts_server)

        # Voice selection
        filtered_voices = []
        if tts_mode_enabled:
            if selected_tts_server == "siliconflow":
                filtered_voices = voice.get_siliconflow_voices()
            elif selected_tts_server == "gemini-tts":
                filtered_voices = voice.get_gemini_voices()
            elif selected_tts_server == "mimo-tts":
                filtered_voices = voice.get_mimo_voices()
            elif selected_tts_server == "minimax-tts":
                minimax_voices, minimax_voice_labels = _render_minimax_tts_settings()
                filtered_voices = minimax_voices
            elif selected_tts_server == "elevenlabs":
                saved_elevenlabs_api_key = _sync_elevenlabs_api_key_input()
                cache_key = f"elevenlabs_voices_{saved_elevenlabs_api_key}"
                if cache_key not in st.session_state:
                    st.session_state[cache_key] = voice.get_elevenlabs_voices(saved_elevenlabs_api_key)
                filtered_voices = st.session_state[cache_key]
            elif selected_tts_server == "chatterbox":
                _sync_chatterbox_config_from_session_state()
                filtered_voices = voice.get_chatterbox_voices()
            elif selected_tts_server == "fish_audio":
                filtered_voices = voice.get_fish_audio_voices()
            else:
                all_voices = voice.get_all_azure_voices(filter_locals=None)
                for v in all_voices:
                    if selected_tts_server == "azure-tts-v2":
                        if "V2" in v:
                            filtered_voices.append(v)
                    else:
                        if "V2" not in v:
                            filtered_voices.append(v)

        friendly_names = {v: _friendly(v) for v in filtered_voices}
        saved_voice_name = config.ui.get("voice_name", "")
        if saved_voice_name in friendly_names:
            saved_voice_name_index = list(friendly_names.keys()).index(saved_voice_name)
        else:
            saved_voice_name_index = 0
            for i, v in enumerate(filtered_voices):
                if v.lower().startswith(st.session_state.get("ui_language", "en").lower()):
                    saved_voice_name_index = i
                    break

        if tts_mode_enabled and friendly_names:
            voice_name = stable_selectbox(
                tr("Voiceover Voice"),
                options=list(friendly_names.keys()),
                default_value=list(friendly_names.keys())[saved_voice_name_index],
                key=f"speech_synthesis_select_{selected_tts_server}",
                format_func=lambda value: friendly_names.get(value, str(value).removeprefix("minimax:")),
            )
            params.voice_name = voice_name
            if not voice.is_no_voice(voice_name):
                _set_runtime_config("ui", "voice_name", voice_name)
        else:
            voice_name = saved_voice_name or voice.NO_VOICE_NAME
            params.voice_name = voice_name

        # Voice volume and rate
        params.voice_volume = 1.0
        params.voice_rate = 1.0
        uploaded_audio_file = None

        if tts_mode_enabled:
            voice_control_cols = st.columns(2)
            with voice_control_cols[0]:
                voice_volume_options = [0.6, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0, 4.0, 5.0]
                params.voice_volume = stable_selectbox(
                    tr("Voiceover Volume"), options=voice_volume_options,
                    default_value=_saved_ui_choice("voice_volume", voice_volume_options, 1.0),
                    key="voice_volume_select", format_func=lambda value: f"{int(value * 100)}%",
                    help=tr("Voiceover Volume Help"),
                )
            with voice_control_cols[1]:
                voice_rate_options = [0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 1.8, 2.0]
                params.voice_rate = stable_selectbox(
                    tr("Voiceover Speed"), options=voice_rate_options,
                    default_value=_saved_ui_choice("voice_rate", voice_rate_options, 1.0),
                    key="voice_rate_select", format_func=lambda value: f"{value:.1f}×",
                    help=tr("Voiceover Speed Help"),
                )
            _set_runtime_config("ui", "voice_volume", params.voice_volume)
            _set_runtime_config("ui", "voice_rate", params.voice_rate)

            _render_voice_preview(params, friendly_names, selected_tts_server, voice_name)
        elif voice_mode == VOICE_MODE_UPLOAD:
            custom_audio_file_types = sorted(extension.removeprefix(".") for extension in CUSTOM_AUDIO_EXTENSIONS)
            uploaded_audio_file = st.file_uploader(
                tr("Upload Voiceover File"),
                type=custom_audio_file_types + [ft.upper() for ft in custom_audio_file_types],
                accept_multiple_files=False, key="custom_audio_file_uploader",
                help=tr("Upload Voiceover File Help"),
            )
            voice_volume_options = [0.6, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0, 4.0, 5.0]
            params.voice_volume = stable_selectbox(
                tr("Voiceover Volume"), options=voice_volume_options,
                default_value=_saved_ui_choice("voice_volume", voice_volume_options, 1.0),
                key="voice_volume_select", format_func=lambda value: f"{int(value * 100)}%",
                help=tr("Voiceover Volume Help"),
            )
            _set_runtime_config("ui", "voice_volume", params.voice_volume)
            if uploaded_audio_file:
                st.audio(uploaded_audio_file, format="audio/mp3")

    # ── Step 5: STYLE ──────────────────────────────────────────────────────
    with st.container(border=True):
        st.subheader("⑤ Style")
        st.session_state.setdefault("subtitle_enabled_checkbox", _saved_ui_bool("subtitle_enabled", DEFAULT_SUBTITLE_SETTINGS["subtitle_enabled"]))
        params.subtitle_enabled = st.checkbox(tr("Enable Subtitles"), key="subtitle_enabled_checkbox")
        _set_runtime_config("ui", "subtitle_enabled", params.subtitle_enabled)
        subtitle_settings_disabled = not params.subtitle_enabled

        font_names = get_all_fonts()
        saved_font_name = config.ui.get("font_name", DEFAULT_SUBTITLE_SETTINGS["font_name"])
        saved_font_name_index = 0
        if saved_font_name in font_names:
            saved_font_name_index = font_names.index(saved_font_name)
        params.font_name = stable_selectbox(
            tr("Font"), options=font_names,
            default_value=font_names[saved_font_name_index] if font_names else "",
            key="font_name_select_step5", disabled=subtitle_settings_disabled,
        )
        _set_runtime_config("ui", "font_name", params.font_name)

        subtitle_positions = [(tr("Top"), "top"), (tr("Center"), "center"), (tr("Bottom"), "bottom"), (tr("Custom"), "custom")]
        saved_subtitle_position = config.ui.get("subtitle_position", DEFAULT_SUBTITLE_SETTINGS["subtitle_position"])
        saved_position_index = 2
        for i, (_, pos_value) in enumerate(subtitle_positions):
            if pos_value == saved_subtitle_position:
                saved_position_index = i
                break
        selected_subtitle_position = stable_selectbox(
            tr("Position"), options=[value for _, value in subtitle_positions],
            default_value=subtitle_positions[saved_position_index][1],
            key="subtitle_position_select_step5",
            format_func=lambda value: dict((v, label) for label, v in subtitle_positions)[value],
            disabled=subtitle_settings_disabled,
        )
        params.subtitle_position = selected_subtitle_position
        _set_runtime_config("ui", "subtitle_position", params.subtitle_position)

    # ── Advanced options ────────────────────────────────────────────────────
    with st.expander("Advanced Options", expanded=False):
        _render_advanced_options(params)

    # ── Launch (primary action) ────────────────────────────────────────────
    # The production workspace ends at a single, unambiguous call to produce.
    # prepare_generation_task() is the on_click contract: it seeds an in-session
    # active task; _handle_generation_submit() then POSTs to /api/v1/videos.
    # The pipeline trigger is UNCHANGED -- only the product framing and label.
    st.divider()

    has_input = bool(params.video_subject) or bool(st.session_state.get("video_script"))
    if has_input:
        st.caption(
            "✅ Ready to produce · Estimated pipeline: "
            "Script → Materials → Audio → Composition"
        )
    else:
        st.caption("⚠️ Enter a video subject to produce.")

    start_button = st.button(
        tr("Launch Production"), use_container_width=True, type="primary",
        key="generate_video_button", on_click=prepare_generation_task,
    )

    if start_button:
        _handle_generation_submit(params, uploaded_files, uploaded_audio_file, voice_mode)

    render_current_generation_task()

    if not start_button:
        _save_runtime_config()


def _consume_prefill_values():
    """Transfer prefill values from Discover/Review into widget state keys."""
    prefill_map = {
        "prefill_video_subject": "video_subject",
        "prefill_video_script_prompt": "video_script_prompt",
        "prefill_video_keywords": "video_terms",
    }
    for prefill_key, widget_key in prefill_map.items():
        if prefill_key in st.session_state and st.session_state[prefill_key]:
            st.session_state[widget_key] = st.session_state[prefill_key]
            st.session_state[prefill_key] = ""


def _render_selected_opportunity_banner():
    """Contextual header showing the opportunity driving this production.

    When a user arrives from Discover/Review (via the prefill contract), surface
    the selected topic so the production workspace always answers
    'WHAT AM I MAKING?'. Offers a one-click 'Change' back to Discover. Real data
    only -- reads session state that the prefill contract populates.
    """
    review_item = st.session_state.get("review_item")
    subject = (st.session_state.get("video_subject") or "").strip()
    topic = (review_item or {}).get("topic") or subject
    if not topic:
        return
    providers = (review_item or {}).get("providers", [])
    feasibility = (review_item or {}).get("visual_feasibility", "")
    score = (review_item or {}).get("score_total") or (review_item or {}).get("confidence")
    badge = "✅ PRODUCIBLE" if (providers and feasibility != "Low") else "⚠️ Review before producing"
    score_span = f"<span style='color:#64748b'>score {score:.0%}</span>" if score else ""
    st.markdown(
        f"<div class='selected-opportunity-banner'>"
        f"<div style='display:flex;align-items:center;gap:0.6rem;flex-wrap:wrap'>"
        f"<b style='color:#0f172a'>{topic}</b>"
        f"<span style='color:#16a34a'>{badge}</span>"
        f"{score_span}"
        f"</div></div>",
        unsafe_allow_html=True,
    )
    if st.button("Change topic →", key="create_change_topic", type="secondary", use_container_width=False):
        from webui.nav_pages import discover_page
        st.switch_page(discover_page)
    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)


def _effective_script_generation_backend():
    app_config_snapshot = config.snapshot_config_with_pending(config.app)
    backend = str(app_config_snapshot.get("script_generation_backend", "local") or "local").strip()
    return backend if backend in {"local", "loomloom"} else "local"


def _effective_loomloom_api_token():
    app_config_snapshot = config.snapshot_config_with_pending(config.app)
    return loomloom.resolve_api_token(app_config_snapshot)


def _create_loomloom_script_backend():
    app_config_snapshot = config.snapshot_config_with_pending(config.app)
    settings = loomloom.LoomLoomSettings.from_mapping(app_config_snapshot)
    return loomloom.LoomLoomScriptBackend(settings)


def _create_loomloom_video_backend():
    app_config_snapshot = config.snapshot_config_with_pending(config.app)
    settings = loomloom.video_settings_from_mapping(app_config_snapshot)
    return loomloom.LoomLoomVideoBackend(settings)


def _render_loomloom_script_generation(params):
    st.caption(tr("LoomLoom Batch Script Generation Help"))
    effective_token = _render_loomloom_api_token_input()
    if not effective_token:
        st.warning(tr("Shengsuan Cloud API Key Required"))
    candidate_col, duration_col = st.columns(2)
    candidate_count = candidate_col.number_input(
        tr("Script Candidate Count"), min_value=1, max_value=loomloom.MAX_SCRIPT_CANDIDATES,
        step=1, key="loomloom_candidate_count",
    )
    duration_seconds = duration_col.number_input(
        tr("Target Script Duration Seconds"), min_value=10, max_value=600,
        step=10, key="loomloom_script_duration_seconds",
    )
    _set_runtime_config("ui", "loomloom_candidate_count", int(candidate_count))
    _set_runtime_config("ui", "loomloom_script_duration_seconds", int(duration_seconds))


def _render_local_script_generation(params):
    if not st.button(
        tr("Generate Video Script and Keywords"), key="auto_generate_script",
        use_container_width=True, type="secondary", icon=":material/auto_awesome:",
    ):
        return
    if not params.video_subject:
        st.toast(tr("Please Enter the Video Subject First"))
        st.warning(tr("Please Enter the Video Subject First"))
        return
    with st.spinner(tr("Generating Video Script and Keywords")):
        def generate_script_and_terms(app_config_snapshot):
            script = llm.generate_script(
                video_subject=params.video_subject, language=params.video_language,
                paragraph_number=params.paragraph_number, video_script_prompt=params.video_script_prompt,
                custom_system_prompt=params.custom_system_prompt, app_config=app_config_snapshot,
            )
            terms = llm.generate_terms(
                params.video_subject, script,
                amount=8 if params.match_materials_to_script else 5,
                match_script_order=params.match_materials_to_script, app_config=app_config_snapshot,
            )
            return script, terms
        script, terms = _run_llm_read_operation("generate_script_and_terms", generate_script_and_terms)
        if "Error: " in script:
            st.error(tr(script))
        elif "Error: " in terms:
            st.error(tr(terms))
        else:
            st.session_state["video_script"] = script
            st.session_state["video_terms"] = ", ".join(terms)


def _render_loomloom_api_token_input():
    app_config_snapshot = config.snapshot_config_with_pending(config.app)
    if str(app_config_snapshot.get("llm_provider", "") or "").lower() == "shengsuanyun":
        st.caption(tr("Shengsuan Cloud API Key Reused"))
        return loomloom.resolve_api_token(app_config_snapshot)
    configured_token = loomloom.resolve_api_token(app_config_snapshot)
    st.session_state.setdefault("loomloom_user_api_token", configured_token)
    api_token = st.text_input(
        tr("Shengsuan Cloud API Key"), type="password",
        key="loomloom_user_api_token", help=tr("Shengsuan Cloud API Key Help"),
        placeholder=tr("Shengsuan Cloud API Key Placeholder"),
    ).strip()
    _set_runtime_config("app", "loomloom_api_token", api_token)
    return _effective_loomloom_api_token()


def _render_minimax_tts_settings():
    effective_api_key = _sync_minimax_tts_api_key_input()
    effective_api_key = st.text_input(
        tr("MiniMax TTS API Key"), type="password",
        key="minimax_tts_api_key_input",
    ).strip()
    dedicated_key = str(config.minimax_tts.get("api_key", "") or "").strip()
    minimax_tts_endpoints = [voice.MINIMAX_TTS_GLOBAL_URL, voice.MINIMAX_TTS_CN_URL]
    effective_endpoint = voice.get_minimax_tts_endpoint()
    if effective_endpoint not in minimax_tts_endpoints:
        effective_endpoint = voice.MINIMAX_TTS_GLOBAL_URL
    minimax_tts_base_url = stable_selectbox(
        tr("MiniMax TTS Endpoint"), options=minimax_tts_endpoints,
        default_value=effective_endpoint, key="minimax_tts_endpoint_select",
        disabled=not dedicated_key,
    )
    if dedicated_key:
        _set_runtime_config("minimax_tts", "base_url", minimax_tts_base_url)
    configured_model = config.minimax_tts.get("model_id", voice.MINIMAX_TTS_DEFAULT_MODEL)
    if configured_model not in voice.MINIMAX_TTS_MODELS:
        configured_model = voice.MINIMAX_TTS_DEFAULT_MODEL
    minimax_tts_model = stable_selectbox(
        tr("MiniMax TTS Model"), options=list(voice.MINIMAX_TTS_MODELS),
        default_value=configured_model, key="minimax_tts_model_select",
    )
    _set_runtime_config("minimax_tts", "model_id", minimax_tts_model)
    available_voices = _get_cached_minimax_voices(effective_api_key, minimax_tts_base_url)
    voice_labels = {
        f"minimax:{item['voice_id']}": (
            f"{item['voice_name']} ({item['voice_id']})"
            if item["voice_name"] != item["voice_id"]
            else item["voice_id"]
        )
        for item in available_voices
    }
    configured_voice_id = str(
        config.minimax_tts.get("voice_id", voice.MINIMAX_TTS_DEFAULT_VOICE) or voice.MINIMAX_TTS_DEFAULT_VOICE
    ).strip()
    configured_voice = f"minimax:{configured_voice_id}"
    voice_labels.setdefault(configured_voice, configured_voice_id)
    return list(voice_labels), voice_labels


def _sync_minimax_tts_api_key_input():
    widget_key = "minimax_tts_api_key_input"
    configured_key = str(config.minimax_tts.get("api_key", "") or "").strip()
    shared_key = str(config.app.get("minimax_api_key", "") or os.getenv("MINIMAX_API_KEY", "") or "").strip()
    effective_key = configured_key or shared_key
    had_widget_state = widget_key in st.session_state
    entered_key = str(st.session_state.get(widget_key, "") or "").strip()
    if not entered_key and effective_key:
        st.session_state[widget_key] = effective_key
        entered_key = effective_key
        if had_widget_state:
            logger.debug("restored MiniMax TTS API key after empty session replay")
    elif not had_widget_state:
        st.session_state[widget_key] = effective_key
        entered_key = effective_key
    if entered_key and entered_key != effective_key:
        _set_runtime_config("minimax_tts", "api_key", entered_key)
    return entered_key


def _get_cached_minimax_voices(api_key, endpoint):
    cache = st.session_state.get("minimax_tts_voice_catalog_cache", {})
    cache_key = f"{endpoint}|{_credential_signature(api_key)}"
    cached_voices = cache.get(cache_key, [])
    return cached_voices if isinstance(cached_voices, list) else []


def _cache_minimax_voices(api_key, endpoint, voices):
    cache = st.session_state.setdefault("minimax_tts_voice_catalog_cache", {})
    cache_key = f"{endpoint}|{_credential_signature(api_key)}"
    cache[cache_key] = voices


def _sync_elevenlabs_api_key_input():
    widget_key = "elevenlabs_api_key_input"
    configured_key = str(config.elevenlabs.get("api_key", "") or "").strip()
    env_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    effective_key = configured_key or env_key
    had_widget_state = widget_key in st.session_state
    entered_key = str(st.session_state.get(widget_key, "") or "").strip()
    if not entered_key and effective_key:
        st.session_state[widget_key] = effective_key
        entered_key = effective_key
        if had_widget_state:
            logger.debug("restored ElevenLabs API key after empty session replay")
    elif not had_widget_state:
        st.session_state[widget_key] = entered_key
    if entered_key and entered_key != effective_key:
        for cache_key in list(st.session_state.keys()):
            if str(cache_key).startswith("elevenlabs_voices_"):
                del st.session_state[cache_key]
        _set_runtime_config("elevenlabs", "api_key", entered_key)
    return entered_key


def _render_voice_preview(params, friendly_names, selected_tts_server, voice_name):
    if not friendly_names:
        return
    script_content = str(params.video_script or "").strip()
    estimated_range = _estimate_voiceover_duration_range(script_content, params.voice_rate)
    if estimated_range:
        st.caption(tr("Estimated Voiceover Duration").format(min=estimated_range[0], max=estimated_range[1]))
    else:
        st.caption(tr("Voiceover Script Required"))
    sample_content = _get_voice_preview_sample(voice_name)
    provider_signature = _get_voice_preview_provider_signature(selected_tts_server)
    preview_columns = st.columns(2)
    short_preview_requested = preview_columns[0].button(
        tr("Play Voice"), key="play_voice_button", icon=":material/graphic_eq:", use_container_width=True,
    )
    full_preview_requested = preview_columns[1].button(
        tr("Generate Full Voiceover Preview"), key="generate_full_voiceover_preview_button",
        icon=":material/article:", help=tr("Full Voiceover Preview Cost Hint"),
        use_container_width=True, disabled=not bool(script_content),
    )
    preview_type = ""
    preview_content = ""
    if short_preview_requested:
        preview_type = "sample"
        preview_content = sample_content
    elif full_preview_requested:
        preview_type = "full"
        preview_content = script_content
    sample_fingerprint = _voice_preview_fingerprint(
        preview_type="sample", content=sample_content, tts_server=selected_tts_server,
        voice_name=voice_name, voice_rate=params.voice_rate, voice_volume=params.voice_volume,
        provider_signature=provider_signature,
    )
    full_fingerprint = (
        _voice_preview_fingerprint(
            preview_type="full", content=script_content, tts_server=selected_tts_server,
            voice_name=voice_name, voice_rate=params.voice_rate, voice_volume=params.voice_volume,
            provider_signature=provider_signature,
        )
        if script_content
        else ""
    )
    if preview_type:
        requested_fingerprint = sample_fingerprint if preview_type == "sample" else full_fingerprint
        cached_preview = st.session_state.get("voice_preview_audio")
        if not cached_preview or cached_preview.get("fingerprint") != requested_fingerprint:
            try:
                with st.spinner(tr("Synthesizing Voice")):
                    preview_result = _synthesize_voice_preview(
                        content=preview_content, preview_type=preview_type,
                        selected_tts_server=selected_tts_server, voice_name=voice_name,
                        voice_rate=params.voice_rate, voice_volume=params.voice_volume,
                    )
            except Exception as exc:
                logger.exception(f"failed to generate {preview_type} voice preview")
                st.error(tr("Voice Preview Failed").format(error=str(exc)))
            else:
                if preview_result and preview_result.get("busy"):
                    st.warning(tr("Voice Preview Busy"))
                elif preview_result:
                    preview_result["fingerprint"] = requested_fingerprint
                    st.session_state["voice_preview_audio"] = preview_result
                else:
                    st.error(tr("Voice Preview No Audio"))
    cached_preview = st.session_state.get("voice_preview_audio")
    valid_fingerprints = {sample_fingerprint, full_fingerprint}
    if cached_preview and cached_preview.get("fingerprint") in valid_fingerprints and cached_preview.get("audio_bytes"):
        should_autoplay = bool(
            short_preview_requested
            and cached_preview.get("preview_type") == "sample"
            and cached_preview.get("fingerprint") == sample_fingerprint
        )
        st.audio(cached_preview["audio_bytes"], format=cached_preview.get("mime_type", "audio/mp3"), autoplay=should_autoplay)
        if cached_preview.get("preview_type") == "full":
            duration = cached_preview.get("duration")
            if isinstance(duration, (int, float)) and duration > 0:
                st.caption(tr("Actual Voiceover Duration").format(duration=f"{duration:.1f}"))
            else:
                st.warning(tr("Voice Preview Duration Unavailable"))


def _synthesize_voice_preview(*, content, preview_type, selected_tts_server, voice_name, voice_rate, voice_volume):
    if preview_type == "sample":
        text = content
    else:
        text = content
    if selected_tts_server == "azure-tts-v1":
        audio_bytes = voice.azure_tts_v1(text=text, voice_name=voice_name, rate=voice_rate, volume=voice_volume)
    elif selected_tts_server == "azure-tts-v2":
        audio_bytes = voice.azure_tts_v2(text=text, voice_name=voice_name, rate=voice_rate, volume=voice_volume)
    elif selected_tts_server == "siliconflow":
        audio_bytes = voice.siliconflow_tts(text=text, voice_name=voice_name, rate=voice_rate, volume=voice_volume)
    elif selected_tts_server == "gemini-tts":
        audio_bytes = voice.gemini_tts(text=text, voice_name=voice_name, rate=voice_rate, volume=voice_volume)
    elif selected_tts_server == "mimo-tts":
        audio_bytes = voice.mimo_tts(text=text, voice_name=voice_name, rate=voice_rate, volume=voice_volume)
    elif selected_tts_server == "minimax-tts":
        audio_bytes = voice.minimax_tts(text=text, voice_name=voice_name, rate=voice_rate, volume=voice_volume)
    elif selected_tts_server == "elevenlabs":
        audio_bytes = voice.elevenlabs_tts(text=text, voice_name=voice_name, rate=voice_rate, volume=voice_volume)
    elif selected_tts_server == "chatterbox":
        audio_bytes = voice.chatterbox_tts(text=text, voice_name=voice_name, rate=voice_rate, volume=voice_volume)
    elif selected_tts_server == "fish_audio":
        audio_bytes = voice.fish_audio_tts(text=text, voice_name=voice_name, rate=voice_rate, volume=voice_volume)
    else:
        audio_bytes = voice.azure_tts_v1(text=text, voice_name=voice_name, rate=voice_rate, volume=voice_volume)
    if not audio_bytes:
        return None
    mime_type = _detect_audio_mime("preview.mp3", audio_bytes)
    return {"audio_bytes": audio_bytes, "mime_type": mime_type, "preview_type": preview_type, "duration": len(audio_bytes) / 16000}


def _render_advanced_options(params):
    """Render advanced technical controls."""
    # Script settings
    with st.expander("Script Settings", expanded=False):
        params.paragraph_number = st.slider(
            tr("Script Paragraph Number"),
            min_value=llm.MIN_SCRIPT_PARAGRAPH_NUMBER, max_value=llm.MAX_SCRIPT_PARAGRAPH_NUMBER,
            key="paragraph_number_input",
        )
        _set_runtime_config("ui", "paragraph_number", params.paragraph_number)
        params.video_script_prompt = st.text_area(
            tr("Custom Script Requirements"), height=100,
            max_chars=llm.MAX_SCRIPT_PROMPT_LENGTH,
            placeholder=tr("Custom Script Requirements Placeholder"),
            key="video_script_prompt",
        ).strip()
        _set_runtime_config("ui", "video_script_prompt", params.video_script_prompt)
        system_prompt = st.text_area(
            tr("Custom System Prompt"), height=240,
            max_chars=llm.MAX_SCRIPT_SYSTEM_PROMPT_LENGTH,
            key="custom_system_prompt",
        ).strip()
        params.custom_system_prompt = "" if system_prompt == llm.DEFAULT_SCRIPT_SYSTEM_PROMPT.strip() else system_prompt
        _set_runtime_config("ui", "custom_system_prompt", params.custom_system_prompt)

    # Video settings
    with st.expander("Video Settings", expanded=False):
        video_concat_modes = [(tr("Sequential"), "sequential"), (tr("Random"), "random")]
        sync_script_order_concat_mode()
        selected_concat_mode = stable_selectbox(
            tr("Video Concat Mode"),
            options=[value for _, value in video_concat_modes],
            default_value=_saved_ui_choice("video_concat_mode", [value for _, value in video_concat_modes], VideoConcatMode.random.value),
            key="video_concat_mode_select",
            format_func=lambda value: dict((v, label) for label, v in video_concat_modes)[value],
            disabled=bool(st.session_state.get("match_materials_to_script", False)),
        )
        params.video_concat_mode = VideoConcatMode(selected_concat_mode)
        if not params.match_materials_to_script:
            _set_runtime_config("ui", "video_concat_mode", params.video_concat_mode.value)

        params.match_materials_to_script = st.checkbox(
            tr("Match Materials to Script Order"),
            help=tr("Match Materials to Script Order Help"),
            key="match_materials_to_script",
            on_change=sync_script_order_concat_mode,
        )
        _set_runtime_config("app", "match_materials_to_script", params.match_materials_to_script)

        video_transition_modes = [
            (tr("None"), VideoTransitionMode.none.value), (tr("Shuffle"), VideoTransitionMode.shuffle.value),
            (tr("FadeIn"), VideoTransitionMode.fade_in.value), (tr("FadeOut"), VideoTransitionMode.fade_out.value),
            (tr("SlideIn"), VideoTransitionMode.slide_in.value), (tr("SlideOut"), VideoTransitionMode.slide_out.value),
            (tr("ZoomIn"), VideoTransitionMode.zoom_in.value), (tr("ZoomOut"), VideoTransitionMode.zoom_out.value),
        ]
        selected_transition_mode = stable_selectbox(
            tr("Video Transition Mode"),
            options=[value for _, value in video_transition_modes],
            default_value=_saved_ui_choice("video_transition_mode", [value for _, value in video_transition_modes], VideoTransitionMode.none.value),
            key="video_transition_mode_select",
            format_func=lambda value: dict((v, label) for label, v in video_transition_modes)[value],
        )
        params.video_transition_mode = VideoTransitionMode(selected_transition_mode)
        _set_runtime_config("ui", "video_transition_mode", params.video_transition_mode.value)

        clip_speed_key = "video_clip_speed_slider"
        st.session_state[clip_speed_key] = utils.normalize_clip_speed(
            st.session_state.get(clip_speed_key, _saved_ui_number("video_clip_speed", 1.0, 0.5, 2.0)),
        )
        params.video_clip_speed = st.slider(
            tr("Clip Speed"), min_value=0.5, max_value=2.0, step=0.05, format="%.2fx",
            key=clip_speed_key, help=tr("Clip Speed Help"),
        )
        _set_runtime_config("ui", "video_clip_speed", params.video_clip_speed)

    # Subtitle settings
    with st.expander("Subtitle Settings", expanded=False):
        _render_subtitle_settings(params)

    # Background music
    with st.expander("Background Music", expanded=False):
        _render_background_music_settings(params)


def _render_subtitle_settings(params):
    font_names = get_all_fonts()
    saved_font_name = config.ui.get("font_name", DEFAULT_SUBTITLE_SETTINGS["font_name"])
    saved_font_name_index = 0
    if saved_font_name in font_names:
        saved_font_name_index = font_names.index(saved_font_name)
    params.font_name = stable_selectbox(
        tr("Font"), options=font_names,
        default_value=font_names[saved_font_name_index] if font_names else "",
        key="font_name_select",
    )
    _set_runtime_config("ui", "font_name", params.font_name)

    subtitle_positions = [(tr("Top"), "top"), (tr("Center"), "center"), (tr("Bottom"), "bottom"), (tr("Custom"), "custom")]
    saved_subtitle_position = config.ui.get("subtitle_position", DEFAULT_SUBTITLE_SETTINGS["subtitle_position"])
    saved_position_index = 2
    for i, (_, pos_value) in enumerate(subtitle_positions):
        if pos_value == saved_subtitle_position:
            saved_position_index = i
            break
    selected_subtitle_position = stable_selectbox(
        tr("Position"), options=[value for _, value in subtitle_positions],
        default_value=subtitle_positions[saved_position_index][1],
        key="subtitle_position_select",
        format_func=lambda value: dict((v, label) for label, v in subtitle_positions)[value],
    )
    params.subtitle_position = selected_subtitle_position
    _set_runtime_config("ui", "subtitle_position", params.subtitle_position)

    if params.subtitle_position == "custom":
        saved_custom_position = config.ui.get("custom_position", DEFAULT_SUBTITLE_SETTINGS["custom_position"])
        st.session_state.setdefault("custom_position_input", str(saved_custom_position))
        custom_position = st.text_input(tr("Custom Position (% from top)"), key="custom_position_input")
        try:
            params.custom_position = float(custom_position)
            if params.custom_position < 0 or params.custom_position > 100:
                st.error(tr("Please enter a value between 0 and 100"))
            else:
                _set_runtime_config("ui", "custom_position", params.custom_position)
        except ValueError:
            st.error(tr("Please enter a valid number"))

    font_cols = st.columns([0.42, 0.58])
    with font_cols[0]:
        saved_text_fore_color = config.ui.get("text_fore_color", DEFAULT_SUBTITLE_SETTINGS["text_fore_color"])
        st.session_state.setdefault("font_color_picker", saved_text_fore_color)
        params.text_fore_color = st.color_picker(tr("Font Color"), key="font_color_picker")
        _set_runtime_config("ui", "text_fore_color", params.text_fore_color)
    with font_cols[1]:
        saved_font_size = config.ui.get("font_size", DEFAULT_SUBTITLE_SETTINGS["font_size"])
        st.session_state.setdefault("font_size_slider", saved_font_size)
        params.font_size = st.slider(tr("Font Size"), 30, 100, key="font_size_slider")
        _set_runtime_config("ui", "font_size", params.font_size)

    stroke_cols = st.columns([0.42, 0.58])
    with stroke_cols[0]:
        st.session_state.setdefault("stroke_color_picker", _saved_ui_color("stroke_color", DEFAULT_SUBTITLE_SETTINGS["stroke_color"]))
        params.stroke_color = st.color_picker(tr("Stroke Color"), key="stroke_color_picker")
        _set_runtime_config("ui", "stroke_color", params.stroke_color)
    with stroke_cols[1]:
        st.session_state.setdefault("stroke_width_slider", _saved_ui_number("stroke_width", DEFAULT_SUBTITLE_SETTINGS["stroke_width"], 0.0, 10.0))
        params.stroke_width = st.slider(tr("Stroke Width"), 0.0, 10.0, key="stroke_width_slider")
        _set_runtime_config("ui", "stroke_width", params.stroke_width)

    if st.button(tr("Restore Default Subtitle Settings"), key="restore_default_subtitle_settings", icon=":material/restart_alt:", on_click=reset_subtitle_settings, use_container_width=True):
        st.toast(tr("Default Subtitle Settings Restored"))


def _render_background_music_settings(params):
    uploaded_bgm_file = None
    previous_bgm_type = st.session_state.get("last_rendered_bgm_type")
    bgm_options = [
        (tr("No Background Music"), ""), (tr("Random Background Music"), "random"),
        (tr("Custom Background Music"), "custom"), (tr("Sonilo Background Music"), "sonilo"),
        (tr("ElevenLabs Background Music"), "elevenlabs"),
    ]
    selected_bgm_type = stable_selectbox(
        tr("Background Music Source"),
        options=[value for _, value in bgm_options],
        default_value=_saved_ui_choice("bgm_type", [value for _, value in bgm_options], "random"),
        key="bgm_type_select",
        format_func=lambda value: dict((v, label) for label, v in bgm_options)[value],
    )
    params.bgm_type = selected_bgm_type
    _set_runtime_config("ui", "bgm_type", params.bgm_type)

    if params.bgm_type == "sonilo":
        configured_key = str(config.app.get("sonilo_api_key", "") or "").strip()
        effective_key = configured_key or os.getenv("SONILO_API_KEY", "").strip()
        entered_key = st.text_input(tr("Sonilo API Key"), value=effective_key, type="password", key="sonilo_api_key_input").strip()
        if configured_key or entered_key != effective_key:
            _set_runtime_config("app", "sonilo_api_key", entered_key)
    elif params.bgm_type == "elevenlabs":
        _render_elevenlabs_api_key_input("ElevenLabs Music API Key")

    bgm_volume_options = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    params.bgm_volume = stable_selectbox(
        tr("Background Music Volume"), options=bgm_volume_options,
        default_value=_saved_ui_choice("bgm_volume", bgm_volume_options, 0.2),
        key="bgm_volume_select", format_func=lambda value: f"{int(value * 100)}%",
        disabled=not params.bgm_type,
    )
    _set_runtime_config("ui", "bgm_volume", params.bgm_volume)
    bgm_enabled = bgm_service.should_use_bgm(params.bgm_type, params.bgm_volume)

    if params.bgm_type == "custom":
        uploaded_bgm_file = st.file_uploader(
            tr("Upload Background Music"),
            type=[extension.removeprefix(".") for extension in bgm_service.SUPPORTED_BGM_EXTENSIONS],
            accept_multiple_files=False, key="custom_bgm_uploader",
            help=tr("Upload Background Music Help"),
            max_upload_size=bgm_service.MAX_BGM_UPLOAD_BYTES // (1024 * 1024),
        )
        if uploaded_bgm_file is not None and bgm_enabled:
            try:
                safe_name = bgm_service.sanitize_upload_filename(uploaded_bgm_file.name)
                validation_key = (safe_name, uploaded_bgm_file.size, hashlib.sha256(uploaded_bgm_file.getbuffer()).hexdigest())
                cached_validation = st.session_state.get("custom_bgm_validation")
                if not cached_validation or cached_validation.get("key") != validation_key:
                    try:
                        bgm_service.validate_bgm_upload(uploaded_bgm_file.name, uploaded_bgm_file)
                    except bgm_service.BgmUploadError as exc:
                        cached_validation = {"key": validation_key, "error": str(exc), "error_type": "upload"}
                        logger.warning(f"WebUI background music validation rejected: name={safe_name}, error={str(exc)}")
                    except bgm_service.BgmServiceError as exc:
                        cached_validation = {"key": validation_key, "error": str(exc), "error_type": "service"}
                        logger.error(f"WebUI background music validation failed: name={safe_name}, error={str(exc)}")
                    else:
                        cached_validation = {"key": validation_key, "error": "", "error_type": ""}
                    st.session_state["custom_bgm_validation"] = cached_validation
                if cached_validation.get("error"):
                    if cached_validation.get("error_type") == "service":
                        raise bgm_service.BgmServiceError(cached_validation["error"])
                    raise bgm_service.BgmUploadError(cached_validation["error"])
            except bgm_service.BgmUploadError:
                params.bgm_file = ""
                st.error(tr("Invalid Background Music"))
            except bgm_service.BgmServiceError:
                params.bgm_file = ""
                st.error(tr("Background Music Validation Failed"))
            else:
                uploaded_mime_type = str(getattr(uploaded_bgm_file, "type", "") or "")
                preview_mime_type = uploaded_mime_type if uploaded_mime_type.startswith("audio/") else mimetypes.guess_type(safe_name)[0] or "audio/mpeg"
                st.audio(uploaded_bgm_file, format=preview_mime_type)
                st.info(f"{tr('Background Music Ready')}: {safe_name}")
                params.bgm_file = safe_name
        elif uploaded_bgm_file:
            params.bgm_file = ""

        if previous_bgm_type != "custom":
            st.session_state["custom_bgm_file_input"] = _saved_ui_text("custom_bgm_file")
        custom_bgm_file = st.text_input(tr("Custom Background Music File"), key="custom_bgm_file_input", disabled=uploaded_bgm_file is not None)
        _set_runtime_config("ui", "custom_bgm_file", custom_bgm_file.strip())
        if uploaded_bgm_file is None and custom_bgm_file and bgm_enabled:
            params.bgm_file = custom_bgm_file.strip()
        elif not bgm_enabled:
            params.bgm_file = ""

    if params.bgm_type == "sonilo":
        if previous_bgm_type != "sonilo":
            st.session_state["sonilo_bgm_prompt_input"] = _saved_ui_text("sonilo_bgm_prompt", max_length=sonilo_service.MAX_PROMPT_LENGTH)
        params.video_music_prompt = st.text_input(
            tr("Sonilo Music Prompt"), key="sonilo_bgm_prompt_input",
            max_chars=sonilo_service.MAX_PROMPT_LENGTH, help=tr("Sonilo Music Prompt Help"),
        ).strip()
        _set_runtime_config("ui", "sonilo_bgm_prompt", params.video_music_prompt)
        if params.video_count > 1:
            st.warning(tr("Sonilo Multiple Videos Warning"))
    elif params.bgm_type == "elevenlabs":
        if previous_bgm_type != "elevenlabs":
            st.session_state["elevenlabs_music_prompt_input"] = _saved_ui_text("elevenlabs_music_prompt", max_length=elevenlabs_music_service.MAX_PROMPT_LENGTH)
        params.video_music_prompt = st.text_input(
            tr("ElevenLabs Music Prompt"), key="elevenlabs_music_prompt_input",
            max_chars=elevenlabs_music_service.MAX_PROMPT_LENGTH, help=tr("ElevenLabs Music Prompt Help"),
        ).strip()
        _set_runtime_config("ui", "elevenlabs_music_prompt", params.video_music_prompt)
        if params.video_count > 1:
            st.warning(tr("ElevenLabs Multiple Videos Warning"))

    st.session_state["last_rendered_bgm_type"] = params.bgm_type
    return uploaded_bgm_file


def _render_elevenlabs_api_key_input(label_key):
    _sync_elevenlabs_api_key_input()
    return st.text_input(tr(label_key), type="password", key="elevenlabs_api_key_input").strip()


def _friendly(v):
    if voice.is_no_voice(v):
        return tr("No Voice Selected")
    if voice.is_elevenlabs_voice(v):
        parts = v.split(":", 2)
        return parts[2] if len(parts) >= 3 else v
    if voice.is_chatterbox_voice(v):
        name = v.split(":", 1)[1] if ":" in v else v
        return name.replace("-Female", "").replace("-Male", "")
    if voice.is_minimax_voice(v):
        return v.split(":", 1)[1]
    if voice.is_fish_audio_voice(v):
        parts = v.split(":", 2)
        display_name = parts[2] if len(parts) >= 3 else v
        return display_name.replace("Female", tr("Female")).replace("Male", tr("Male"))
    return v.replace("Female", tr("Female")).replace("Male", tr("Male")).replace("Neural", "")


def _handle_generation_submit(params, uploaded_files, uploaded_audio_file, voice_mode):
    """Handle the generation task submission."""
    _save_runtime_config()
    task_id = st.session_state.get("pending_generation_task_id") or str(uuid4())
    add_active_generation_task(task_id, subject=params.video_subject or params.video_script or task_id)
    if not params.video_subject and not params.video_script:
        remove_active_generation_task(task_id)
        st.error(tr("Video Script and Subject Cannot Both Be Empty"))
        st.stop()
    if params.video_source not in ["pexels", "pixabay", "coverr", "youtube", "wavespeed", "loomloom", "local"]:
        remove_active_generation_task(task_id)
        st.error(tr("Please Select a Valid Video Source"))
        st.stop()
    if params.video_source == "pexels" and not config.app.get("pexels_api_keys", ""):
        remove_active_generation_task(task_id)
        st.error(tr("Please Enter the Pexels API Key"))
        st.stop()
    if params.video_source == "pixabay" and not config.app.get("pixabay_api_keys", ""):
        remove_active_generation_task(task_id)
        st.error(tr("Please Enter the Pixabay API Key"))
        st.stop()
    if params.video_source == "coverr" and not config.app.get("coverr_api_keys", ""):
        remove_active_generation_task(task_id)
        st.error(tr("Please Enter the Coverr API Key"))
        st.stop()
    if params.video_source == "wavespeed" and not config.app.get("wavespeed_api_keys", ""):
        remove_active_generation_task(task_id)
        st.error(tr("Please Enter the WaveSpeed API Key"))
        st.stop()
    if params.video_source == "wavespeed" and not st.session_state.get("wavespeed_confirm_charge", False):
        remove_active_generation_task(task_id)
        st.error(tr("Confirm WaveSpeed Charge Required"))
        st.stop()
    if params.video_source == "local" and not (uploaded_files or st.session_state.get("local_video_materials", [])):
        remove_active_generation_task(task_id)
        st.error(tr("Please Upload Local Materials First"))
        st.stop()
    if voice_mode == VOICE_MODE_UPLOAD and not uploaded_audio_file:
        remove_active_generation_task(task_id)
        st.error(tr("Please Upload Voiceover File First"))
        st.stop()

    if uploaded_audio_file:
        task_dir = utils.task_dir(task_id)
        try:
            custom_audio_path = _build_uploaded_file_path(uploaded_audio_file, task_dir, CUSTOM_AUDIO_EXTENSIONS, "custom-audio")
        except ValueError:
            remove_active_generation_task(task_id)
            st.error(tr("Unsupported Upload File Type"))
            st.stop()
        with open(custom_audio_path, "wb") as f:
            f.write(uploaded_audio_file.getbuffer())
        params.custom_audio_file = custom_audio_path

    if uploaded_files:
        local_videos_dir = utils.storage_dir("local_videos", create=True)
        params.video_materials = []
        persisted_local_materials = []
        for file in uploaded_files:
            try:
                file_path = _build_uploaded_file_path(file, local_videos_dir, LOCAL_MATERIAL_EXTENSIONS, "material")
            except ValueError:
                remove_active_generation_task(task_id)
                st.error(tr("Unsupported Upload File Type"))
                st.stop()
            with open(file_path, "wb") as f:
                f.write(file.getbuffer())
                m = MaterialInfo()
                m.provider = "local"
                m.url = file_path
                params.video_materials.append(m)
                persisted_local_materials.append({"provider": m.provider, "url": m.url, "duration": m.duration})
        st.session_state["local_video_materials"] = persisted_local_materials
    elif params.video_source == "local" and st.session_state.get("local_video_materials", []):
        params.video_materials = []
        for material in st.session_state["local_video_materials"]:
            m = MaterialInfo()
            m.provider = material.get("provider", "local")
            m.url = material.get("url", "")
            m.duration = material.get("duration", 0)
            if m.url:
                params.video_materials.append(m)

    reusable_voice_preview = _get_reusable_full_voice_preview(params, voice_mode)
    if reusable_voice_preview:
        preview_audio_file = os.path.join(utils.task_dir(task_id), "audio.mp3")
        with open(preview_audio_file, "wb") as file:
            file.write(reusable_voice_preview.pop("audio_bytes"))
        reusable_voice_preview["audio_file"] = preview_audio_file
        logger.info(f"reuse full voice preview for task: task_id={task_id}, duration={reusable_voice_preview['duration']:.2f}s")

    try:
        st.toast(tr("Generating Video"))
        logger.info(tr("Start Generating Video"))
        logger.info(utils.to_json(params))
        api_task_id = webui_task.submit_generation(
            task_id=task_id, params=params,
            capture_logs=not config.ui.get("hide_log", False),
            voice_preview=reusable_voice_preview,
            loomloom_video_request=None,
        )
    except Exception:
        remove_active_generation_task(task_id)
        st.error(tr("Video Generation Failed"))
        st.stop()

    if api_task_id and api_task_id != task_id:
        active = st.session_state.get("active_generation_tasks", {})
        prev = active.pop(str(task_id), {})
        active[str(api_task_id)] = prev
    del st.session_state["pending_generation_task_id"]
    st.session_state["current_generation_task_id"] = api_task_id
    logger.info(f"WebUI generation task submitted: task_id={api_task_id}")


def _get_reusable_full_voice_preview(params, voice_mode):
    if voice_mode != VOICE_MODE_TTS:
        return None
    script_content = str(params.video_script or "").strip()
    selected_tts_server = config.ui.get("tts_server", "azure-tts-v1")
    if not script_content or not params.voice_name or not math.isclose(float(params.voice_volume), 1.0):
        return None
    expected_fingerprint = _voice_preview_fingerprint(
        preview_type="full", content=script_content, tts_server=selected_tts_server,
        voice_name=params.voice_name, voice_rate=params.voice_rate, voice_volume=params.voice_volume,
        provider_signature=_get_voice_preview_provider_signature(selected_tts_server),
    )
    cached_preview = st.session_state.get("voice_preview_audio")
    if (
        not cached_preview
        or cached_preview.get("fingerprint") != expected_fingerprint
        or cached_preview.get("preview_type") != "full"
        or not cached_preview.get("audio_bytes")
        or cached_preview.get("sub_maker") is None
    ):
        return None
    duration = cached_preview.get("duration")
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        return None
    return {
        "audio_bytes": bytes(cached_preview["audio_bytes"]),
        "duration": float(duration),
        "sub_maker": cached_preview["sub_maker"],
        "script": script_content,
        "voice_name": params.voice_name,
        "voice_rate": float(params.voice_rate),
        "voice_volume": float(params.voice_volume),
    }
