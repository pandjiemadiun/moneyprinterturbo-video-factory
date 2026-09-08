"""Regression guards for the undefined-name crash class (audit F821 cluster).

These tests prove the runtime ``NameError`` crashes surfaced during the audit
are fixed and cannot silently regress:

* ``webui/pages/create.py`` referenced ``logger``, ``hashlib``, ``uuid4``,
  ``mimetypes`` and ``math`` without importing them -> the "Generate Video"
  submit handler raised ``NameError`` inside its ``try`` block, was swallowed
  by the bare ``except`` and ``submit_generation`` was *never* called -> every
  Generate Video click failed before submission.
* ``webui/pages/settings.py`` referenced ``logger`` without importing it ->
  the key-backup/restore handlers raised ``NameError``.
* ``app/services/material.py`` ``_reframe_landscape_to_portrait`` referenced
  ``src_width`` / ``src_height`` without ever assigning them -> landscape->
  portrait reframe always failed. (Functional proof lives in
  ``test/services/test_reframing.py`` -- this file covers the import class.)

No production network, no production jobs, no Streamlit widget runtime.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from webui.shared import VOICE_MODE_NONE


def test_create_page_imports_required_names():
    """create.py must bind every name its handlers reference at import time."""
    import webui.pages.create as create

    missing = [
        name
        for name in ("logger", "hashlib", "uuid4", "mimetypes")
        if name not in dir(create)
    ]
    assert missing == [], f"create.py is missing imports: {missing}"


def test_settings_page_imports_logger():
    """settings.py must import the `logger` used by its key-restore handlers."""
    import webui.pages.settings as settings

    assert "logger" in dir(settings), "settings.py must `from loguru import logger`"


def test_handle_generation_submit_reaches_api_without_nameerror():
    """The Generate Video path must reach submit_generation (no NameError).

    Before the fix: ``logger.info("Start Generating Video")`` executed inside
    the ``try`` block (before ``submit_generation``), raised ``NameError``
    (logger was never imported), was swallowed by the broad ``except Exception``
    and ``submit_generation`` was never reached. After the fix the handler
    reaches the API call and stores the returned task id.

    Streamlit + task submission + config persistence are mocked, so no real
    API call (8080) is made and no config.toml is written.
    """
    import webui.pages.create as create

    # --- Streamlit surface: session_state behaves as a plain dict ---
    mock_st = MagicMock()
    mock_st.session_state = {"pending_generation_task_id": None}
    create.st = mock_st

    # --- Mock the side-effecting collaborators (no API / no config write) ---
    create.webui_task = MagicMock()
    create.webui_task.submit_generation.return_value = "api-task-id"
    create._save_runtime_config = MagicMock()
    create.add_active_generation_task = MagicMock()
    create.remove_active_generation_task = MagicMock()
    create._get_reusable_full_voice_preview = MagicMock(return_value=None)
    create.utils = MagicMock()
    create.utils.to_json.return_value = "{}"
    create.tr = lambda s, **kw: s

    # `loomloom` is a valid source with no API-key guard; `video_subject` is set
    # so the empty-form guard is skipped; voice_mode is not UPLOAD, so the
    # audio-upload guard is skipped.
    params = SimpleNamespace(
        video_subject="a short audit subject",
        video_script=None,
        video_source="loomloom",
    )

    create._handle_generation_submit(
        params,
        uploaded_files=None,
        uploaded_audio_file=None,
        voice_mode=VOICE_MODE_NONE,
    )

    assert create.webui_task.submit_generation.called, (
        "Generate Video did not call submit_generation -- handler aborted via "
        "NameError on an undefined import (logger / uuid4 / ...)"
    )
    assert mock_st.session_state.get("current_generation_task_id") == "api-task-id"
