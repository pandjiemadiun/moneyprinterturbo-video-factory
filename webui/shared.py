"""
Shared utilities, constants, session-state initialization, and helpers
for the MoneyPrinterTurbo WebUI multipage application.

All page modules import from here to avoid duplication.
"""

import hashlib
import html
import json
import math
import mimetypes
import os
import re
import sys
import time
import webbrowser
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

import requests
import streamlit as st
from loguru import logger

# ── Path setup ──────────────────────────────────────────────────────────────
root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if root_dir in sys.path:
    sys.path.remove(root_dir)
sys.path.insert(0, root_dir)

# ── App imports ─────────────────────────────────────────────────────────────
from app.config import config
from app.models import const
from app.models.llm_provider import (
    DEFAULT_LLM_PROVIDER_ID,
    LLM_PROVIDER_REGISTRY,
    get_llm_provider,
    normalize_provider_override,
)
from app.models.schema import (
    MaterialInfo,
    VideoAspect,
    VideoConcatMode,
    VideoParams,
    VideoTransitionMode,
)
from app.services import bgm as bgm_service
from app.services import (
    cache_manager,
    llm,
    loomloom,
    video,
    voice,
    webui_api_client,
    webui_task,
)
from app.services import elevenlabs_music as elevenlabs_music_service
from app.services import sonilo as sonilo_service
from app.services import task as tm
from app.services import version_checker
from app.services import webui_batch
from app.services import elevenlabs_music
from app.services import sonilo
from app.utils.logging_utils import configure_terminal_logger
from app.utils import utils

# ── Constants ───────────────────────────────────────────────────────────────
font_dir = os.path.join(root_dir, "resource", "fonts")
song_dir = os.path.join(root_dir, "resource", "songs")
i18n_dir = os.path.join(root_dir, "webui", "i18n")

locales = utils.load_locales(i18n_dir)

DEFAULT_CHATTERBOX_BASE_URL = "http://127.0.0.1:4123/v1"
DEFAULT_CHATTERBOX_MODEL = "chatterbox"
DEFAULT_CHATTERBOX_VOICES = ["default-Female"]
ONBOARDING_TOUR_KEY = "mpt-onboarding-v1"
CUSTOM_LLM_ENDPOINT_ID = "custom"
VOICE_MODE_TTS = "tts"
VOICE_MODE_UPLOAD = "upload"
VOICE_MODE_NONE = "none"
LOOMLOOM_MAX_POLL_FAILURES = 5
DEFAULT_VIDEO_CODEC_OPTION = "__default__"

DEFAULT_SUBTITLE_SETTINGS = {
    "subtitle_enabled": True,
    "font_name": "MicrosoftYaHeiBold.ttc",
    "subtitle_position": "bottom",
    "custom_position": 70.0,
    "text_fore_color": "#FFFFFF",
    "font_size": 60,
    "stroke_color": "#000000",
    "stroke_width": 1.5,
    "subtitle_background_enabled": False,
    "subtitle_background_color": "#000000",
    "rounded_subtitle_background": False,
}

LOCAL_MATERIAL_EXTENSIONS = {".mp4", ".mov", ".avi", ".flv", ".mkv", ".jpg", ".jpeg", ".png"}
CUSTOM_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}

_FINAL_VIDEO_PATTERN = re.compile(
    r"^final-(?P<index>\d+)\.(?P<extension>mp4|mov|mkv|webm)$",
    re.IGNORECASE,
)
_DOWNLOAD_FILENAME_INVALID_PATTERN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

_RUNTIME_CONFIG_SECTIONS = {
    "app": config.app,
    "azure": config.azure,
    "chatterbox": config.chatterbox,
    "elevenlabs": config.elevenlabs,
    "minimax_tts": config.minimax_tts,
    "siliconflow": config.siliconflow,
    "fish_audio": config.fish_audio,
    "ui": config.ui,
}

SETTINGS_PRESET_SCHEMA = "moneyprinterturbo.settings-preset"
SETTINGS_PRESET_VERSION = 1
SETTINGS_PRESET_FILE_NAME = "moneyprinterturbo-settings.json"
KEY_BACKUP_SCHEMA = "moneyprinterturbo.key-backup"
KEY_BACKUP_VERSION = 1
KEY_BACKUP_FILE_NAME = "moneyprinterturbo-keys.json"

PRESET_EXCLUDED_PARAM_KEYS = frozenset({"video_materials", "custom_audio_file", "bgm_file"})

CREDENTIAL_KEY_SUFFIXES = ("api_key", "api_keys", "api_token", "access_key", "secret_key", "speech_key")

CREDENTIAL_COMPANION_KEYS = {
    "azure": ("speech_region",),
    "app": tuple(
        provider.config_key(field.config_suffix)
        for provider in LLM_PROVIDER_REGISTRY
        for field in provider.extra_fields
    ),
}

CREDENTIAL_WIDGET_STATE_ALIASES = {
    ("app", "gemini_api_key"): ("gemini_tts_api_key_input",),
    ("app", "mimo_api_key"): ("mimo_tts_api_key_input",),
    ("app", "loomloom_api_token"): ("loomloom_user_api_token",),
}

KEY_BACKUP_EXCLUDED_SECTIONS = frozenset({"ui"})

support_locales = [
    "zh-CN", "zh-HK", "zh-TW", "de-DE", "en-US", "es-ES",
    "fr-FR", "it-IT", "ru-RU", "vi-VN", "th-TH", "tr-TR",
]


# ── Config helpers ──────────────────────────────────────────────────────────

def _set_runtime_config(section_name, key, value):
    config_section = _RUNTIME_CONFIG_SECTIONS[section_name]
    updated = config.update_config_nonblocking(config_section, key, value)
    if not updated:
        logger.debug(f"deferred WebUI config update: section={section_name}, key={key}")
    return updated


def _delete_runtime_config(section_name, key):
    config_section = _RUNTIME_CONFIG_SECTIONS[section_name]
    deleted = config.delete_config_nonblocking(config_section, key)
    if not deleted:
        logger.debug(f"deferred WebUI config delete: section={section_name}, key={key}")
    return deleted


def _save_runtime_config():
    saved = config.try_save_config()
    if not saved:
        logger.debug("deferred WebUI config save until active task completes")
    save_error = config.get_last_save_error()
    if save_error and not st.session_state.get("_config_persistence_warning_shown"):
        st.warning(save_error)
        st.session_state["_config_persistence_warning_shown"] = True
        config.clear_last_save_error()
    return saved


def _saved_ui_choice(key, options, default):
    options = list(options)
    saved = config.ui.get(key, default)
    numeric_default = isinstance(default, (int, float)) and not isinstance(default, bool)
    if numeric_default and isinstance(saved, bool):
        return default
    for option in options:
        if saved == option:
            return option
    if numeric_default and isinstance(saved, str):
        try:
            converted = type(default)(saved)
        except (TypeError, ValueError):
            converted = None
        for option in options:
            if converted == option:
                return option
    return default


def _saved_ui_number(key, default, minimum, maximum, number_type=float):
    try:
        saved = config.ui.get(key, default)
        if isinstance(saved, bool):
            raise ValueError("boolean is not a numeric setting")
        value = number_type(saved)
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("non-finite value")
    except (TypeError, ValueError, OverflowError):
        value = default
    return min(maximum, max(minimum, value))


def _saved_ui_bool(key, default):
    value = config.ui.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _saved_ui_color(key, default):
    value = str(config.ui.get(key, default) or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return value
    return default


def _saved_ui_text(key, default="", max_length=None):
    value = str(config.ui.get(key, default) or default)
    if max_length is not None:
        value = value[:max_length]
    return value


# ── LLM helpers ─────────────────────────────────────────────────────────────

def _run_llm_read_operation(operation_name, operation):
    with config.try_runtime_config_lock() as lock_acquired:
        app_config_snapshot = config.snapshot_config_with_pending(config.app)
        if lock_acquired:
            return operation(app_config_snapshot)
    logger.info(f"run read-only LLM operation with active task configuration: operation={operation_name}")
    return operation(app_config_snapshot)


# ── Audio helpers ───────────────────────────────────────────────────────────

def _parse_chatterbox_voices(voices):
    if isinstance(voices, str):
        return [v.strip() for v in voices.split(",") if v.strip()]
    return [str(v).strip() for v in voices or [] if str(v).strip()]


def _sync_chatterbox_config_from_session_state():
    _set_runtime_config(
        "chatterbox", "base_url",
        (st.session_state.get("chatterbox_base_url_input", config.chatterbox.get("base_url") or DEFAULT_CHATTERBOX_BASE_URL) or "").strip(),
    )
    _set_runtime_config(
        "chatterbox", "api_key",
        st.session_state.get("chatterbox_api_key_input", config.chatterbox.get("api_key", "")),
    )
    _set_runtime_config(
        "chatterbox", "model_id",
        (st.session_state.get("chatterbox_model_input", config.chatterbox.get("model_id") or DEFAULT_CHATTERBOX_MODEL) or DEFAULT_CHATTERBOX_MODEL).strip(),
    )
    _set_runtime_config(
        "chatterbox", "voices",
        _parse_chatterbox_voices(st.session_state.get("chatterbox_voices_input", config.chatterbox.get("voices") or DEFAULT_CHATTERBOX_VOICES)),
    )


def _detect_audio_mime(audio_file: str, audio_bytes: bytes) -> str:
    header = audio_bytes[:12]
    if header.startswith(b"RIFF") and header[8:12] == b"WAVE":
        return "audio/wav"
    if header.startswith(b"ID3") or header[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mp3"
    if header.startswith(b"OggS"):
        return "audio/ogg"
    ext = os.path.splitext(audio_file)[1].lower()
    return {".wav": "audio/wav", ".m4a": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg", ".flac": "audio/flac"}.get(ext, "audio/mp3")


# ── File upload helpers ─────────────────────────────────────────────────────

def _build_uploaded_file_path(uploaded_file, target_dir, allowed_extensions, prefix):
    original_name = os.path.basename(str(uploaded_file.name or ""))
    extension = os.path.splitext(original_name)[1].lower()
    if extension not in allowed_extensions:
        logger.warning(f"reject unsupported uploaded file extension: {original_name or '<empty>'}")
        raise ValueError("unsupported uploaded file type")
    normalized_target_dir = os.path.realpath(target_dir)
    os.makedirs(normalized_target_dir, exist_ok=True)
    file_path = os.path.realpath(os.path.join(normalized_target_dir, f"{prefix}-{uuid4().hex}{extension}"))
    if os.path.commonpath([normalized_target_dir, file_path]) != normalized_target_dir:
        logger.warning(f"invalid uploaded file path: {file_path}")
        raise ValueError("invalid uploaded file path")
    return file_path


# ── Session state initialization ────────────────────────────────────────────

def initialize_session_state():
    """Initialize cross-run session state. Safe to call multiple times."""
    if not st.session_state.get("cross_post_recovery_checked"):
        recovered = tm.recover_interrupted_cross_posts()
        if recovered is not None:
            st.session_state["cross_post_recovery_checked"] = True

    saved_ui_language = config.ui.get("language", "")
    browser_locale = st.context.locale
    initial_ui_language = utils.resolve_ui_language(
        saved_language=saved_ui_language,
        browser_locale=browser_locale,
        supported_languages=locales.keys(),
    )

    defaults = {
        "video_subject": "",
        "video_script": "",
        "video_terms": "",
        "paragraph_number_input": _saved_ui_number("paragraph_number", 1, llm.MIN_SCRIPT_PARAGRAPH_NUMBER, llm.MAX_SCRIPT_PARAGRAPH_NUMBER, int),
        "video_script_prompt": _saved_ui_text("video_script_prompt", max_length=llm.MAX_SCRIPT_PROMPT_LENGTH),
        "custom_system_prompt": _saved_ui_text("custom_system_prompt", llm.DEFAULT_SCRIPT_SYSTEM_PROMPT, llm.MAX_SCRIPT_SYSTEM_PROMPT_LENGTH),
        "match_materials_to_script": bool(config.app.get("match_materials_to_script", False)),
        "custom_bgm_file_input": _saved_ui_text("custom_bgm_file"),
        "sonilo_bgm_prompt_input": _saved_ui_text("sonilo_bgm_prompt", max_length=sonilo_service.MAX_PROMPT_LENGTH),
        "elevenlabs_music_prompt_input": _saved_ui_text("elevenlabs_music_prompt", max_length=elevenlabs_music_service.MAX_PROMPT_LENGTH),
        "subtitle_enabled_checkbox": _saved_ui_bool("subtitle_enabled", True),
        "stroke_color_picker": _saved_ui_color("stroke_color", "#000000"),
        "stroke_width_slider": _saved_ui_number("stroke_width", 1.5, 0.0, 10.0),
        "loomloom_candidate_count": _saved_ui_number("loomloom_candidate_count", 3, 1, loomloom.MAX_SCRIPT_CANDIDATES, int),
        "loomloom_script_duration_seconds": _saved_ui_number("loomloom_script_duration_seconds", 60, 10, 600, int),
        "ui_language": initial_ui_language,
        "local_video_materials": [],
        "active_generation_tasks": {},
        "current_generation_task_id": "",
        "loomloom_script_batch": None,
        "loomloom_script_quote": None,
        "loomloom_script_input_signature": "",
        "loomloom_client_request_id": "",
        "loomloom_run_id": "",
        "loomloom_run_status": "",
        "loomloom_run_error": "",
        "loomloom_poll_failure_count": 0,
        "loomloom_poll_retry_after": 0.0,
        "loomloom_poll_paused": False,
        "loomloom_script_candidates": (),
        "loomloom_candidate_errors": (),
        "loomloom_selected_candidate": 0,
        "loomloom_video_batch": None,
        "loomloom_video_quote": None,
        "loomloom_video_input_signature": "",
        "loomloom_video_client_request_id": "",
        "loomloom_video_confirm_charge": False,
        "wavespeed_confirm_charge": False,
        "vo_result": None,
        "vo_show_text_input": False,
        "loomloom_video_scene_count": _saved_ui_number("loomloom_video_scene_count", 1, 1, loomloom.MAX_VIDEO_SCENES, int),
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


# ── Translation ─────────────────────────────────────────────────────────────

def tr(key):
    loc = locales.get(st.session_state.get("ui_language", "en"), {})
    value = loc.get("Translation", {}).get(key)
    if value is not None:
        return value
    return locales.get("en", {}).get("Translation", {}).get(key, key)


# ── Task management helpers ─────────────────────────────────────────────────

def format_task_time(timestamp):
    if not timestamp:
        return "-"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def format_task_subject(subject, max_length=30):
    subject = str(subject or "").replace("\n", " ").strip()
    if len(subject) <= max_length:
        return subject or "-"
    return f"{subject[:max_length]}..."


def safe_load_task_script(task_path):
    script_file = os.path.join(task_path, "script.json")
    if not os.path.isfile(script_file):
        return {}
    try:
        with open(script_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"failed to read task script data: {script_file}, {e}")
        return {}


def find_final_task_video(task_path: str) -> str:
    try:
        files = os.listdir(task_path)
    except OSError:
        return ""
    candidates = []
    for file_name in files:
        match = _FINAL_VIDEO_PATTERN.fullmatch(file_name)
        if match:
            candidates.append((int(match.group("index")), file_name))
    if not candidates:
        return ""
    _, file_name = min(candidates, key=lambda item: item[0])
    return os.path.join(task_path, file_name)


def build_restore_upload_requirements(params: Mapping) -> dict:
    return {
        "local_materials": params.get("video_source") == "local",
        "custom_audio": bool(params.get("custom_audio_file")),
        "original_voice_name": params.get("voice_name") or "",
    }


def get_unmet_restore_upload_requirements(requirements, *, video_source, voice_name, has_local_materials, has_custom_audio, voice_mode=None):
    requirements = requirements or {}
    unmet = set()
    if requirements.get("local_materials") and video_source == "local" and not has_local_materials:
        unmet.add("local_materials")
    if requirements.get("custom_audio") and not has_custom_audio:
        if voice_mode is not None:
            if voice_mode == VOICE_MODE_UPLOAD:
                unmet.add("custom_audio")
        elif voice_name == requirements.get("original_voice_name", ""):
            unmet.add("custom_audio")
    return unmet


def queue_task_restore(task_id):
    st.session_state["task_restore_candidate_id"] = task_id
    st.session_state["task_manager_popover_nonce"] = st.session_state.get("task_manager_popover_nonce", 0) + 1
    st.rerun(scope="app")


def normalize_task_state(state):
    if state in (const.TASK_STATE_COMPLETE, const.TASK_STATE_FAILED, const.TASK_STATE_PROCESSING):
        return state
    try:
        return int(state)
    except (TypeError, ValueError):
        return state


def active_generation_tasks():
    tasks = st.session_state.setdefault("active_generation_tasks", {})
    if not isinstance(tasks, dict):
        tasks = {}
        st.session_state["active_generation_tasks"] = tasks
    return tasks


def add_active_generation_task(task_id, subject=None):
    tasks = active_generation_tasks()
    task = tasks.setdefault(task_id, {})
    task["subject"] = subject or task.get("subject") or task_id
    task["mtime"] = task.get("mtime") or datetime.now().timestamp()


def remove_active_generation_task(task_id):
    tasks = active_generation_tasks()
    if task_id in tasks:
        del tasks[task_id]
    if st.session_state.get("pending_generation_task_id") == task_id:
        del st.session_state["pending_generation_task_id"]


def prepare_generation_task():
    task_id = str(uuid4())
    st.session_state["pending_generation_task_id"] = task_id
    subject = st.session_state.get("video_subject") or st.session_state.get("video_script")
    add_active_generation_task(task_id, subject=subject)


def task_state_label(state, has_video):
    normalized_state = normalize_task_state(state)
    if normalized_state == const.TASK_STATE_COMPLETE:
        return tr("Task Status Complete")
    if normalized_state == const.TASK_STATE_FAILED:
        return tr("Task Status Failed")
    if normalized_state == const.TASK_STATE_PROCESSING:
        return tr("Task Status Processing")
    if has_video:
        return tr("Task Status Complete")
    return tr("Task Status History")


def task_state_filter_key(task):
    normalized_state = normalize_task_state(task.get("state"))
    if normalized_state == const.TASK_STATE_PROCESSING:
        return "processing"
    if normalized_state == const.TASK_STATE_FAILED:
        return "failed"
    if normalized_state == const.TASK_STATE_COMPLETE or task.get("video_file"):
        return "complete"
    return "history"


def scan_history_tasks(limit=30):
    return []


def collect_task_summaries(limit=20):
    task_summaries: dict[str, dict] = {}
    try:
        runtime_tasks, _ = webui_api_client.api_list_tasks(1, 50)
    except Exception as e:
        logger.warning(f"failed to load runtime tasks: {e}")
        runtime_tasks = []

    for task in runtime_tasks:
        task_id = task.get("task_id", "")
        if not task_id:
            continue
        task_path = os.path.join(utils.task_dir(), task_id)
        video_files = task.get("videos") or []
        video_file = video_files[0] if video_files else ""
        params = task.get("params") or {}
        subject = (
            task.get("video_subject")
            or params.get("video_subject")
            or (task.get("script", "")[:40] if task.get("script") else "")
            or task_id
        )
        mtime = 0
        if os.path.isdir(task_path):
            try:
                mtime = os.path.getmtime(task_path)
            except OSError:
                pass
        task_summaries[task_id] = {
            "task_id": task_id,
            "subject": subject,
            "state": task.get("state"),
            "cross_post_state": task.get("cross_post_state"),
            "progress": int(task.get("progress", 0) or 0),
            "mtime": mtime,
            "task_path": task_path,
            "video_file": video_file,
            "source": "api",
        }

    for task_id, active_task in active_generation_tasks().items():
        existing = task_summaries.get(task_id, {})
        if existing and task_state_filter_key(existing) in {"complete", "failed"}:
            continue
        task_path = os.path.join(utils.task_dir(), task_id)
        mtime = 0
        if os.path.isdir(task_path):
            try:
                mtime = os.path.getmtime(task_path)
            except OSError:
                pass
        task_summaries[task_id] = {
            "task_id": task_id,
            "subject": active_task.get("subject") or existing.get("subject", task_id),
            "state": const.TASK_STATE_PROCESSING,
            "cross_post_state": existing.get("cross_post_state"),
            "progress": existing.get("progress", 0),
            "mtime": active_task.get("mtime") or existing.get("mtime", datetime.now().timestamp()),
            "task_path": task_path,
            "video_file": existing.get("video_file", ""),
            "source": "active",
        }

    tasks = list(task_summaries.values())
    return sorted(tasks, key=lambda item: item["mtime"], reverse=True)[:limit]


def open_task_path(task_path):
    tasks_root = os.path.abspath(utils.task_dir())
    normalized_path = os.path.abspath(task_path)
    if not normalized_path.startswith(tasks_root + os.sep):
        logger.warning(f"invalid task folder path: {normalized_path}")
        return
    if os.path.isdir(normalized_path):
        webbrowser.open(f"file://{normalized_path}")


def open_task_video(video_file):
    if not video_file:
        return None
    tasks_root = os.path.abspath(utils.task_dir())
    normalized_file = os.path.abspath(video_file)
    if not normalized_file.startswith(tasks_root + os.sep):
        logger.warning(f"invalid task video path: {normalized_file}")
        return None
    if not os.path.isfile(normalized_file):
        logger.warning(f"task video does not exist: {normalized_file}")
        return None
    return normalized_file


def delete_task(task_id, task_path, task_state=None):
    tasks_root = os.path.abspath(utils.task_dir())
    normalized_path = os.path.abspath(task_path)
    if not normalized_path.startswith(tasks_root + os.sep):
        logger.warning(f"invalid task folder path for deletion: {normalized_path}")
        return False
    try:
        result = webui_api_client.api_delete_task(task_id)
    except Exception as e:
        logger.exception(f"failed to call API delete for task: {task_id}, {e}")
        return False
    if not result.get("success", False):
        logger.warning(f"API delete failed for task {task_id}: {result}")
        return False
    logger.info(f"deleted task via API: {task_id}")
    return True


def count_processing_tasks(tasks):
    processing_task_ids = {task["task_id"] for task in tasks if task_state_filter_key(task) == "processing"}
    return len(processing_task_ids)


def task_manager_label(processing_count):
    label = tr("Task Manager")
    if processing_count <= 0:
        return label
    return f"{label} · {processing_count}"


def build_video_download_name(subject, index, total):
    safe_subject = _DOWNLOAD_FILENAME_INVALID_PATTERN.sub(" ", str(subject or ""))
    safe_subject = re.sub(r"\s+", " ", safe_subject).strip(" .")[:80].rstrip(" .")
    if not safe_subject:
        safe_subject = "video"
    suffix = f"-{index}" if total > 1 else ""
    return f"{safe_subject}{suffix}.mp4"


# ── Task restore helpers ────────────────────────────────────────────────────

def load_task_restore_payload(task_id):
    tasks_root = os.path.realpath(utils.task_dir())
    task_path = os.path.realpath(os.path.join(tasks_root, str(task_id)))
    try:
        if os.path.commonpath([tasks_root, task_path]) != tasks_root:
            raise ValueError("task path is outside the task directory")
    except ValueError as e:
        logger.warning(f"invalid task restore path: {task_id}, {e}")
        return None
    script_data = safe_load_task_script(task_path)
    raw_params = script_data.get("params")
    if not isinstance(raw_params, dict):
        logger.warning(f"task has no restorable parameters: {task_id}")
        return None
    params_input = dict(raw_params)
    if script_data.get("script"):
        params_input["video_script"] = script_data["script"]
    if script_data.get("search_terms"):
        params_input["video_terms"] = script_data["search_terms"]
    try:
        params = VideoParams.model_validate(params_input).model_dump(mode="json")
    except Exception as e:
        logger.warning(f"failed to validate task restore parameters: {task_id}, {e}")
        return None
    return {
        "task_id": str(task_id),
        "subject": params.get("video_subject") or script_data.get("script") or task_id,
        "params": params,
    }


def infer_tts_server_from_voice(voice_name):
    if voice.is_no_voice(voice_name):
        return voice.NO_VOICE_NAME
    if voice.is_siliconflow_voice(voice_name):
        return "siliconflow"
    if voice.is_gemini_voice(voice_name):
        return "gemini-tts"
    if voice.is_mimo_voice(voice_name):
        return "mimo-tts"
    if voice.is_minimax_voice(voice_name):
        return "minimax-tts"
    if voice.is_elevenlabs_voice(voice_name):
        return "elevenlabs"
    if voice.is_chatterbox_voice(voice_name):
        return "chatterbox"
    if voice.is_fish_audio_voice(voice_name):
        return "fish_audio"
    if voice.is_azure_v2_voice(voice_name):
        return "azure-tts-v2"
    return "azure-tts-v1"


def set_stable_widget_value(key, value):
    if value is not None:
        st.session_state[localized_widget_key(key)] = value


def apply_pending_task_restore():
    payload = st.session_state.pop("task_restore_payload", None)
    if not payload:
        return False
    apply_restored_params(payload["params"])
    st.session_state["task_restore_succeeded"] = True
    logger.info(f"restored task configuration: {payload['task_id']}")
    return True


def apply_restored_params(params):
    video_terms = params.get("video_terms") or ""
    if isinstance(video_terms, list):
        video_terms = ", ".join(str(term) for term in video_terms)
    st.session_state["video_subject"] = params.get("video_subject") or ""
    st.session_state["video_script"] = params.get("video_script") or ""
    st.session_state["video_terms"] = str(video_terms)
    set_stable_widget_value("script_language_select", params.get("video_language") or "")
    st.session_state["paragraph_number_input"] = params.get("paragraph_number", 1)
    st.session_state["video_script_prompt"] = params.get("video_script_prompt") or ""
    st.session_state["custom_system_prompt"] = params.get("custom_system_prompt") or llm.DEFAULT_SCRIPT_SYSTEM_PROMPT
    video_source = params.get("video_source") or "pexels"
    set_stable_widget_value("video_source_select", video_source)
    set_stable_widget_value("video_concat_mode_select", params.get("video_concat_mode") or "random")
    set_stable_widget_value("video_transition_mode_select", params.get("video_transition_mode") or VideoTransitionMode.none.value)
    set_stable_widget_value(f"video_aspect_for_{video_source}", params.get("video_aspect") or VideoAspect.portrait.value)
    set_stable_widget_value("video_clip_duration_select", params.get("video_clip_duration", 3))
    set_stable_widget_value("video_clip_speed_slider", utils.normalize_clip_speed(params.get("video_clip_speed", 1.0)))
    set_stable_widget_value("video_count_select", params.get("video_count", 1))
    st.session_state["match_materials_to_script"] = bool(params.get("match_materials_to_script", False))
    voice_name = params.get("voice_name") or voice.NO_VOICE_NAME
    tts_server = infer_tts_server_from_voice(voice_name)
    if params.get("custom_audio_file"):
        voice_mode = VOICE_MODE_UPLOAD
    elif voice.is_no_voice(voice_name):
        voice_mode = VOICE_MODE_NONE
    else:
        voice_mode = VOICE_MODE_TTS
    set_stable_widget_value("voice_mode_control", voice_mode)
    if tts_server != voice.NO_VOICE_NAME:
        set_stable_widget_value("tts_server_select", tts_server)
        set_stable_widget_value(f"speech_synthesis_select_{tts_server}", voice_name)
    set_stable_widget_value("voice_volume_select", params.get("voice_volume", 1.0))
    set_stable_widget_value("voice_rate_select", params.get("voice_rate", 1.0))
    bgm_type = params.get("bgm_type") or ""
    set_stable_widget_value("bgm_type_select", bgm_type)
    set_stable_widget_value("bgm_volume_select", params.get("bgm_volume", 0.2))
    st.session_state["custom_bgm_file_input"] = params.get("bgm_file") or ""
    st.session_state["sonilo_bgm_prompt_input"] = params.get("video_music_prompt") or params.get("sonilo_bgm_prompt") or ""
    st.session_state["elevenlabs_music_prompt_input"] = params.get("video_music_prompt") or ""
    st.session_state["subtitle_enabled_checkbox"] = bool(params.get("subtitle_enabled", True))
    set_stable_widget_value("font_name_select", params.get("font_name") or "")
    set_stable_widget_value("subtitle_position_select", params.get("subtitle_position") or "bottom")
    custom_position = min(100.0, max(0.0, float(params.get("custom_position", 70.0))))
    st.session_state["custom_position_input"] = str(custom_position)
    st.session_state["font_color_picker"] = params.get("text_fore_color") or "#FFFFFF"
    st.session_state["font_size_slider"] = min(100, max(30, int(params.get("font_size", 60))))
    st.session_state["stroke_color_picker"] = params.get("stroke_color") or "#000000"
    st.session_state["stroke_width_slider"] = min(10.0, max(0.0, float(params.get("stroke_width", 1.5))))
    background_color = params.get("text_background_color")
    background_enabled = bool(background_color)
    st.session_state["subtitle_background_enabled_checkbox"] = background_enabled
    if isinstance(background_color, str):
        st.session_state["subtitle_background_color_picker"] = background_color
    st.session_state["rounded_subtitle_background_checkbox"] = bool(params.get("rounded_subtitle_background", False) and background_enabled)
    st.session_state.pop("local_video_materials_uploader", None)
    st.session_state["local_video_materials"] = []
    st.session_state.pop("custom_audio_file_uploader", None)
    st.session_state.pop("custom_bgm_uploader", None)
    st.session_state.pop("custom_bgm_validation", None)
    st.session_state["task_restore_upload_requirements"] = build_restore_upload_requirements(params)
    return True


# ── UI helpers ──────────────────────────────────────────────────────────────

def localized_widget_key(name, *parts):
    language = st.session_state.get("ui_language", config.ui.get("language", ""))
    suffix_parts = [name, language, *[str(part) for part in parts if part]]
    return "_".join(suffix_parts)


def stable_selectbox(label, options, default_value, key, format_func=None, **kwargs):
    options = list(options)
    if not options:
        raise ValueError(f"selectbox options cannot be empty: {key}")
    if default_value not in options:
        default_value = options[0]
    widget_key = localized_widget_key(key)
    selected_value = st.session_state.get(widget_key)
    accepts_custom_value = bool(kwargs.get("accept_new_options"))
    has_valid_custom_value = (
        accepts_custom_value
        and isinstance(selected_value, str)
        and bool(selected_value.strip())
    )
    if selected_value not in options and not has_valid_custom_value:
        st.session_state[widget_key] = default_value
    if format_func is None:
        format_func = str
    return st.selectbox(label, options=options, format_func=format_func, key=widget_key, **kwargs)


def stable_segmented_control(label, options, default_value, key, format_func=None, **kwargs):
    options = list(options)
    if not options:
        raise ValueError(f"segmented control options cannot be empty: {key}")
    if default_value not in options:
        default_value = options[0]
    widget_key = localized_widget_key(key)
    if st.session_state.get(widget_key) not in options:
        st.session_state[widget_key] = default_value
    return st.segmented_control(
        label, options=options, selection_mode="single", required=True,
        format_func=format_func or str, key=widget_key, **kwargs,
    )


def sync_script_order_concat_mode():
    widget_key = localized_widget_key("video_concat_mode_select")
    previous_key = "video_concat_mode_before_script_order_match"
    match_script_order = bool(st.session_state.get("match_materials_to_script", False))
    if match_script_order:
        current_mode = st.session_state.get(widget_key, VideoConcatMode.random.value)
        if current_mode != VideoConcatMode.sequential.value:
            st.session_state[previous_key] = current_mode
        st.session_state[widget_key] = VideoConcatMode.sequential.value
        return
    previous_mode = st.session_state.pop(previous_key, None)
    if previous_mode in {VideoConcatMode.sequential.value, VideoConcatMode.random.value}:
        st.session_state[widget_key] = previous_mode


def reset_script_system_prompt():
    st.session_state["custom_system_prompt"] = llm.DEFAULT_SCRIPT_SYSTEM_PROMPT


def reset_subtitle_settings():
    defaults = DEFAULT_SUBTITLE_SETTINGS
    st.session_state["subtitle_enabled_checkbox"] = defaults["subtitle_enabled"]
    set_stable_widget_value("font_name_select", defaults["font_name"])
    set_stable_widget_value("subtitle_position_select", defaults["subtitle_position"])
    st.session_state["custom_position_input"] = str(defaults["custom_position"])
    st.session_state["font_color_picker"] = defaults["text_fore_color"]
    st.session_state["font_size_slider"] = defaults["font_size"]
    st.session_state["stroke_color_picker"] = defaults["stroke_color"]
    st.session_state["stroke_width_slider"] = defaults["stroke_width"]
    st.session_state["subtitle_background_enabled_checkbox"] = defaults["subtitle_background_enabled"]
    st.session_state["subtitle_background_color_picker"] = defaults["subtitle_background_color"]
    st.session_state["rounded_subtitle_background_checkbox"] = defaults["rounded_subtitle_background"]
    for key in (
        "subtitle_enabled", "font_name", "subtitle_position", "custom_position",
        "text_fore_color", "font_size", "stroke_color", "stroke_width",
        "subtitle_background_enabled", "subtitle_background_color", "rounded_subtitle_background",
    ):
        _set_runtime_config("ui", key, defaults[key])


# ── LLM provider helpers ────────────────────────────────────────────────────

def get_llm_provider_tips(provider_id, **kwargs):
    provider = get_llm_provider(provider_id)
    if provider is None:
        return ""
    ui_language = st.session_state.get("ui_language", "en")
    tips_language = ui_language if ui_language in {"zh", "en"} else "en"
    tips = locales.get(tips_language, {}).get("Translation", {}).get(provider.tips_key, "")
    if not tips:
        return tips
    service_endpoint = provider.preferred_service_endpoint(prefer_international=tips_language == "en")
    api_key_url = service_endpoint.api_key_url if service_endpoint else provider.effective_api_key_url()
    format_context = {
        "api_key_url": api_key_url,
        "default_model": provider.default_model,
        "default_base_url": service_endpoint.base_url if service_endpoint else provider.effective_default_base_url,
        "model_docs_url": service_endpoint.model_docs_url if service_endpoint else "",
        **{f"default_{field.config_suffix}": field.default_value for field in provider.extra_fields},
        **kwargs,
    }
    try:
        return tips.format(**format_context)
    except Exception as e:
        logger.warning(f"format llm provider tips failed: {provider_id}, {e}")
        return tips


def format_llm_connection_error(provider_id, base_url, error):
    error_text = str(error or "").strip()
    normalized_error = error_text.lower()
    authentication_markers = ("401", "authentication", "invalid api key", "invalid_api_key", "unauthorized")
    provider = get_llm_provider(provider_id)
    if provider is None or not provider.service_endpoints or not any(marker in normalized_error for marker in authentication_markers):
        return error_text
    message = tr_optional(provider.authentication_error_key, fallback_language="en")
    if not message:
        return error_text
    return message.format(base_url=base_url or "-", error=error_text)


def get_llm_provider_label(provider):
    return tr_optional(provider.label_key) or provider.default_label


def get_tts_provider_tips(provider_id):
    ui_language = st.session_state.get("ui_language", "en")
    tips_language = ui_language if ui_language in {"zh", "en"} else "en"
    return locales.get(tips_language, {}).get("Translation", {}).get(f"tts_provider_tips.{provider_id}", "")


# ── Misc helpers ────────────────────────────────────────────────────────────

@st.cache_data(ttl=30, show_spinner=False)
def get_all_fonts():
    fonts = []
    for root, dirs, files in os.walk(font_dir):
        for file in files:
            if file.endswith(".ttf") or file.endswith(".ttc"):
                fonts.append(file)
    fonts.sort()
    return fonts


@st.cache_data(ttl=30, show_spinner=False)
def get_all_songs():
    songs = []
    for root, dirs, files in os.walk(song_dir):
        for file in files:
            if file.endswith(".mp3"):
                songs.append(file)
    return songs


def open_task_folder(task_id):
    try:
        normalized_task_id = str(UUID(str(task_id)))
        tasks_root = os.path.abspath(os.path.join(root_dir, "storage", "tasks"))
        path = os.path.abspath(os.path.join(tasks_root, normalized_task_id))
        if not path.startswith(tasks_root + os.sep):
            logger.warning(f"invalid task folder path: {path}")
            return
        if os.path.isdir(path):
            webbrowser.open(f"file://{path}")
    except Exception as e:
        logger.exception(f"failed to open task folder: task_id={task_id}, error={e}")


@st.cache_resource
def init_log():
    _lvl = "DEBUG"
    return configure_terminal_logger(sys.stdout, level=_lvl, colorize=True)


init_log()


def tr_optional(key, fallback_language=""):
    loc = locales.get(st.session_state.get("ui_language", "en"), {})
    value = loc.get("Translation", {}).get(key, "")
    if not value and fallback_language:
        fallback_loc = locales.get(fallback_language, {})
        value = fallback_loc.get("Translation", {}).get(key, "")
    return value if value else ""


def render_onboarding_tour():
    return


def youtube_error_message(error: str, failed_stage: str | None) -> str:
    error_lower = error.lower()
    if failed_stage == "materials":
        if any(k in error_lower for k in ("playability", "video unavailable", "player-response")):
            return tr("YouTube Error Playability")
        if any(k in error_lower for k in ("provider_pot_failed", "provider_unreachable", "provider_ping_failed")):
            return tr("YouTube Error Provider")
        if any(k in error_lower for k in ("browser_pot_failed", "browser_launch_failed", "browser_navigation_failed", "playwright_unavailable")):
            return tr("YouTube Error Browser")
        if "no" in error_lower and ("found" in error_lower or "result" in error_lower):
            return tr("YouTube Error No Results")
        if "quality" in error_lower or "resolution" in error_lower:
            return tr("YouTube Error Quality")
        if "download" in error_lower or "403" in error_lower:
            return tr("YouTube Error Download")
        if "generic_download_error" in error_lower or "ytdlp_browser_failed" in error_lower:
            return tr("YouTube Error Generic")
    return tr("Video Generation Failed")


# ── Generation task rendering ───────────────────────────────────────────────

def render_generation_logs(task_id):
    if config.ui.get("hide_log", False):
        return
    log_records = webui_task.get_task_logs(task_id)
    if not log_records:
        return
    st.code("\n".join(log_records))


def render_generation_task_snapshot(task_id, task):
    if not task:
        st.info(tr("Generating Video"))
        render_generation_logs(task_id)
        return
    state = normalize_task_state(task.get("state"))
    progress = max(0, min(100, int(task.get("progress", 0) or 0)))
    if state == const.TASK_STATE_PROCESSING:
        st.info(tr("Generating Video"))
        if task.get("video_source") == "youtube":
            if progress < 30:
                st.caption(tr("YouTube Progress Search"))
            elif progress < 60:
                st.caption(tr("YouTube Progress Download"))
            else:
                st.caption(tr("YouTube Progress Quality"))
        st.progress(progress, text=f"{tr('Task Progress')}: {progress}%")
        render_generation_logs(task_id)
        return
    if state == const.TASK_STATE_FAILED:
        error = str(task.get("error") or "").strip()
        failed_stage = task.get("failed_stage")
        if task.get("video_source") == "youtube":
            message = youtube_error_message(error, failed_stage)
        else:
            message = tr("Video Generation Failed")
        st.error(f"{message}: {error}" if error and message == tr("Video Generation Failed") else message if message else f"{tr('Video Generation Failed')}: {error}")
        render_generation_logs(task_id)
        return
    video_files = task.get("videos") or []
    if state != const.TASK_STATE_COMPLETE or not video_files:
        st.error(tr("Video Generation Failed"))
        render_generation_logs(task_id)
        return
    st.success(tr("Video Generation Completed"))
    for warning in task.get("warnings") or []:
        if isinstance(warning, Mapping) and warning.get("code") == "sonilo_bgm_failed":
            st.warning(tr("Sonilo BGM Fallback Warning").format(index=warning.get("video_index", "")))
        elif isinstance(warning, Mapping) and warning.get("code") == "elevenlabs_bgm_failed":
            st.warning(tr("ElevenLabs BGM Fallback Warning").format(index=warning.get("video_index", "")))
        else:
            st.warning(str(warning))
    try:
        player_cols = st.columns(len(video_files) * 2 + 1)
        for i, url in enumerate(video_files):
            with player_cols[i * 2 + 1]:
                thumbnails = task.get("thumbnails") or []
                if i < len(thumbnails) and thumbnails[i]:
                    try:
                        st.image(thumbnails[i], use_container_width=True)
                    except Exception:
                        pass
                st.video(url)
                if not os.path.isfile(url):
                    logger.warning(f"generated video is unavailable for download: task_id={task_id}, video_file={url}")
                    continue
                download_label = tr("Download Video")
                if len(video_files) > 1:
                    download_label = f"{download_label} {i + 1}"
                download_name = build_video_download_name(task.get("video_subject"), i + 1, len(video_files))
                filename = os.path.basename(url)
                download_url = f"/api/v1/download/{task_id}/{filename}"
                st.link_button(download_label, url=download_url, key=f"download_generated_video_{task_id}_{i}", icon=":material/download:", use_container_width=True, help=download_label)
    except Exception as exc:
        logger.exception(f"failed to render generated video preview: task_id={task_id}, video_files={video_files}, error={exc}")
    render_generation_logs(task_id)
    if st.session_state.get("handled_generation_task_id") != task_id:
        st.session_state["handled_generation_task_id"] = task_id
        if config.ui.get("open_task_folder_on_completion", True):
            open_task_folder(task_id)
        logger.info(f"{tr('Video Generation Completed')}: task_id={task_id}")


@st.fragment(run_every=webui_task.TASK_LOG_REFRESH_INTERVAL_SECONDS)
def render_running_generation_task(task_id):
    try:
        task = webui_api_client.api_get_task(task_id)
    except Exception as exc:
        logger.exception(f"failed to query WebUI generation task: task_id={task_id}, error={exc}")
        st.error(tr("Video Generation Failed"))
        return
    state = normalize_task_state((task or {}).get("state"))
    if state in {const.TASK_STATE_COMPLETE, const.TASK_STATE_FAILED}:
        remove_active_generation_task(task_id)
        st.rerun(scope="app")
    render_generation_task_snapshot(task_id, task)


def render_current_generation_task():
    task_id = st.session_state.get("current_generation_task_id", "")
    if not task_id:
        return
    try:
        task = webui_api_client.api_get_task(task_id)
    except Exception as exc:
        logger.exception(f"failed to query current WebUI task: task_id={task_id}, error={exc}")
        st.error(tr("Video Generation Failed"))
        return
    state = normalize_task_state((task or {}).get("state"))
    if state in {const.TASK_STATE_COMPLETE, const.TASK_STATE_FAILED}:
        remove_active_generation_task(task_id)
        render_generation_task_snapshot(task_id, task)
        return
    render_running_generation_task(task_id)


# ── Cache management ────────────────────────────────────────────────────────

@st.cache_data(ttl=30, show_spinner=False)
def get_video_cache_stats(max_age_days=None):
    return cache_manager.get_video_cache_stats(max_age_days=max_age_days)


def format_file_size(size_bytes):
    size = float(max(0, size_bytes))
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.2f} {unit}"
        size /= 1024
    return f"{size_bytes} B"


# ── Settings transfer helpers ───────────────────────────────────────────────

def is_credential_config_key(key):
    return str(key).endswith(CREDENTIAL_KEY_SUFFIXES)


def is_backup_config_key(section_name, key):
    if is_credential_config_key(key):
        return True
    return key in CREDENTIAL_COMPANION_KEYS.get(section_name, ())


def credential_widget_state_keys(section_name, key):
    if section_name == "app":
        default_widget_key = f"{key}_input"
    else:
        default_widget_key = f"{section_name}_{key}_input"
    return (default_widget_key, *CREDENTIAL_WIDGET_STATE_ALIASES.get((section_name, key), ()))


def normalize_backup_value(value):
    if isinstance(value, list):
        items = [str(item).strip() for item in value if isinstance(item, (str, int, float)) and str(item).strip()]
        return items or None
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        text = str(value).strip()
        return text or None
    return None


def collect_key_backup(config_sections):
    backup = {}
    for section_name, section in config_sections.items():
        if section_name in KEY_BACKUP_EXCLUDED_SECTIONS:
            continue
        entries = {}
        for key, value in section.items():
            if not is_backup_config_key(section_name, key):
                continue
            normalized_value = normalize_backup_value(value)
            if normalized_value is not None:
                entries[key] = normalized_value
        if entries:
            backup[section_name] = entries
    return backup


def count_backup_keys(backup):
    return sum(len(entries) for entries in backup.values())


def build_key_backup_payload(config_sections, app_version):
    return {
        "schema": KEY_BACKUP_SCHEMA,
        "version": KEY_BACKUP_VERSION,
        "app_version": str(app_version),
        "keys": collect_key_backup(config_sections),
    }


def load_transfer_payload(raw_bytes, schema, version):
    payload = json.loads(raw_bytes.decode("utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("exported file must contain a JSON object")
    if payload.get("schema") != schema:
        raise ValueError(f"unexpected schema: {payload.get('schema')!r}")
    if payload.get("version") != version:
        raise ValueError(f"unsupported version: {payload.get('version')!r}")
    return payload


def parse_key_backup(raw_bytes, config_sections):
    payload = load_transfer_payload(raw_bytes, KEY_BACKUP_SCHEMA, KEY_BACKUP_VERSION)
    keys = payload.get("keys")
    if not isinstance(keys, dict):
        raise ValueError("key backup file has no keys object")
    restored = {}
    for section_name, entries in keys.items():
        if section_name not in config_sections:
            continue
        if section_name in KEY_BACKUP_EXCLUDED_SECTIONS:
            continue
        if not isinstance(entries, dict):
            continue
        section_entries = {}
        for key, value in entries.items():
            if not is_backup_config_key(section_name, key):
                continue
            normalized_value = normalize_backup_value(value)
            if normalized_value is not None:
                section_entries[key] = normalized_value
        if section_entries:
            restored[section_name] = section_entries
    if not restored:
        raise ValueError("key backup file contains no restorable keys")
    return restored


def build_settings_preset_payload(params, app_version):
    preset_params = {key: value for key, value in params.items() if key not in PRESET_EXCLUDED_PARAM_KEYS}
    return {
        "schema": SETTINGS_PRESET_SCHEMA,
        "version": SETTINGS_PRESET_VERSION,
        "app_version": str(app_version),
        "params": preset_params,
    }


def parse_settings_preset(raw_bytes):
    payload = load_transfer_payload(raw_bytes, SETTINGS_PRESET_SCHEMA, SETTINGS_PRESET_VERSION)
    preset_params = payload.get("params")
    if not isinstance(preset_params, dict):
        raise ValueError("settings preset file has no params object")
    params_input = {key: value for key, value in preset_params.items() if key not in PRESET_EXCLUDED_PARAM_KEYS}
    params_input.setdefault("video_subject", "")
    return VideoParams.model_validate(params_input).model_dump(mode="json")


def apply_key_backup(restored_keys):
    restored_count = 0
    for section_name, entries in restored_keys.items():
        for key, value in entries.items():
            _set_runtime_config(section_name, key, value)
            for widget_key in credential_widget_state_keys(section_name, key):
                st.session_state.pop(widget_key, None)
            restored_count += 1
    for cache_key in list(st.session_state.keys()):
        if str(cache_key).startswith("elevenlabs_voices_"):
            del st.session_state[cache_key]
    return restored_count


def apply_pending_settings_preset():
    preset_params = st.session_state.pop("settings_preset_payload", None)
    if not preset_params:
        return False
    apply_restored_params(preset_params)
    logger.info("applied imported settings preset")
    return True


# ── Voice preview helpers ───────────────────────────────────────────────────

def get_voice_preview_sample(voice_name: str) -> str:
    if voice.is_elevenlabs_voice(voice_name):
        parts = voice_name.split(":", 2)
        display = parts[2] if len(parts) >= 3 else ""
        vietnamese_chars = set("àáâãèéêìíòóôõùúýăđơưÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝĂĐƠƯ")
        if any(char in vietnamese_chars for char in display):
            return "Xin chào, đây là đoạn âm thanh thử nghiệm giọng nói."
    return tr("Voice Example")


def voice_preview_fingerprint(*, preview_type, content, tts_server, voice_name, voice_rate, voice_volume, provider_signature):
    payload = {
        "preview_type": preview_type, "content": content, "tts_server": tts_server,
        "voice_name": voice_name, "voice_rate": voice_rate, "voice_volume": voice_volume,
        "provider_signature": provider_signature,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def credential_signature(value: str) -> str:
    normalized_value = str(value or "")
    if not normalized_value:
        return ""
    return hashlib.sha256(normalized_value.encode("utf-8")).hexdigest()


def get_voice_preview_provider_signature(tts_server: str) -> dict:
    if tts_server == "azure-tts-v2":
        return {"speech_region": config.azure.get("speech_region", ""), "credential": credential_signature(config.azure.get("speech_key", ""))}
    if tts_server == "siliconflow":
        return {"credential": credential_signature(config.siliconflow.get("api_key", ""))}
    if tts_server == "gemini-tts":
        return {"credential": credential_signature(config.app.get("gemini_api_key", ""))}
    if tts_server == "mimo-tts":
        return {"credential": credential_signature(config.app.get("mimo_api_key", ""))}
    if tts_server == "minimax-tts":
        return {
            "base_url": voice.get_minimax_tts_endpoint(),
            "model_id": config.minimax_tts.get("model_id", ""),
            "voice_id": config.minimax_tts.get("voice_id", ""),
            "credential": credential_signature(voice.get_minimax_tts_api_key()),
        }
    if tts_server == "elevenlabs":
        return {"model_id": config.elevenlabs.get("model_id", ""), "credential": credential_signature(config.elevenlabs.get("api_key", ""))}
    return {}


def estimate_voiceover_duration_range(text: str, voice_rate: float) -> tuple[float, float] | None:
    normalized_text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized_text:
        return None
    script_chars = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", normalized_text)
    remaining_text = re.sub(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", " ", normalized_text)
    words = re.findall(r"\b[\w]+(?:[-'’][\w]+)*\b", remaining_text, re.UNICODE)
    punctuation_count = len(re.findall(r"[,，.。!?！？;；:：]", normalized_text))
    base_seconds = len(script_chars) / 4.2 + len(words) / 2.6 + punctuation_count * 0.12
    if base_seconds <= 0:
        return None
    normalized_rate = max(float(voice_rate or 1.0), 0.1)
    estimated_seconds = base_seconds / normalized_rate
    return (round(max(estimated_seconds * 0.85, 1.0), 1), round(max(estimated_seconds * 1.15, 1.0), 1))


# ── LLM provider helpers ────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def get_groq_model_ids(api_key: str, base_url: str) -> list[str]:
    if not api_key:
        return []
    normalized_base_url = (base_url or "https://api.groq.com/openai/v1").strip().rstrip("/")
    models_url = f"{normalized_base_url}/models"
    try:
        response = requests.get(models_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", [])
        model_ids = []
        for item in data:
            if isinstance(item, dict):
                model_id = item.get("id")
                if isinstance(model_id, str) and model_id.strip():
                    model_ids.append(model_id.strip())
        return sorted(set(model_ids))
    except Exception as e:
        logger.warning(f"failed to fetch groq models: {e}")
        return []


def get_material_api_keys(config_key):
    api_keys = config.app.get(config_key, [])
    if isinstance(api_keys, str):
        api_keys = [api_keys]
    return ", ".join(api_keys)


def save_material_api_keys(config_key, value):
    normalized_value = value.replace(" ", "")
    _set_runtime_config("app", config_key, normalized_value.split(",") if normalized_value else [])


# ── Aliases for backward compatibility with page imports ───────────────────
# These aliases allow page modules to import private-style names from shared.

def _get_material_api_keys(config_key):
    return get_material_api_keys(config_key)


def _save_material_api_keys(config_key, value):
    return save_material_api_keys(config_key, value)


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


def _current_loomloom_video_quote_context(params):
    token = _effective_loomloom_api_token()
    scene_count = int(st.session_state.get("loomloom_video_scene_count", 1) or 1)
    prompts = _loomloom_video_scene_prompts(params.video_terms, params.video_subject or params.video_script, scene_count)
    if not token or not prompts:
        return None, ""
    try:
        batch = _create_loomloom_video_backend().prepare_video_batch(
            subject=params.video_subject or params.video_script,
            scene_prompts=prompts,
            aspect_ratio=str(params.video_aspect.value if isinstance(params.video_aspect, VideoAspect) else params.video_aspect),
        )
    except (loomloom.LoomLoomError, ValueError):
        return None, ""
    fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return batch, _loomloom_video_signature(batch, fingerprint)


def _loomloom_video_scene_prompts(video_terms, subject, scene_count):
    if isinstance(video_terms, str):
        terms = [term.strip() for term in re.split(r"[,，\n]", video_terms) if term.strip()]
    elif isinstance(video_terms, list):
        terms = [str(term or "").strip() for term in video_terms if str(term or "").strip()]
    else:
        terms = []
    fallback = str(subject or "").strip()
    if not terms and fallback:
        terms = [fallback]
    if not terms:
        return ()
    return tuple(
        (
            terms[index % len(terms)]
            if index < len(terms)
            else f"{terms[index % len(terms)]}; alternative camera angle {index + 1}"
        )
        for index in range(int(scene_count))
    )


def _loomloom_video_signature(batch, credential_fingerprint):
    payload = {
        "inputRows": [dict(row) for row in batch.input_rows],
        "credentialFingerprint": str(credential_fingerprint or "").strip(),
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _loomloom_script_signature(*, subject, language, candidate_count, duration_seconds, style, credential_fingerprint):
    payload = {
        "subject": str(subject or "").strip(),
        "language": str(language or "auto").strip() or "auto",
        "candidateCount": int(candidate_count),
        "durationSeconds": int(duration_seconds),
        "style": str(style or "").strip(),
        "credentialFingerprint": str(credential_fingerprint or "").strip(),
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _estimate_voiceover_duration_range(text, voice_rate):
    return estimate_voiceover_duration_range(text, voice_rate)


def _get_voice_preview_sample(voice_name):
    return get_voice_preview_sample(voice_name)


def _voice_preview_fingerprint(*, preview_type, content, tts_server, voice_name, voice_rate, voice_volume, provider_signature):
    return voice_preview_fingerprint(
        preview_type=preview_type, content=content, tts_server=tts_server,
        voice_name=voice_name, voice_rate=voice_rate, voice_volume=voice_volume,
        provider_signature=provider_signature,
    )


def _credential_signature(value):
    return credential_signature(value)


def _get_voice_preview_provider_signature(tts_server):
    return get_voice_preview_provider_signature(tts_server)


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


# ── More aliases for settings page ─────────────────────────────────────────

def _build_key_backup_payload(config_sections, app_version):
    return build_key_backup_payload(config_sections, app_version)


def _count_backup_keys(backup):
    return count_backup_keys(backup)


def _collect_key_backup(config_sections):
    return collect_key_backup(config_sections)


def _load_transfer_payload(raw_bytes, schema, version):
    return load_transfer_payload(raw_bytes, schema, version)


def _parse_key_backup(raw_bytes, config_sections):
    return parse_key_backup(raw_bytes, config_sections)


def _build_settings_preset_payload(params, app_version):
    return build_settings_preset_payload(params, app_version)


def _parse_settings_preset(raw_bytes):
    return parse_settings_preset(raw_bytes)


def _apply_key_backup(restored_keys):
    return apply_key_backup(restored_keys)


def _apply_restored_params(params):
    return apply_restored_params(params)
