"""Phase 11H.1.16 regression tests for YouTube PO-token recovery.

Tests the new _classify_youtube_failure, _youtube_runtime_diagnostics,
_build_youtube_ydl_opts, _run_youtube_download_attempt,
_fetch_po_token_from_provider, _fetch_po_token_via_browser helpers, and
the 2-attempt save_video_youtube strategy (bgutil → browser → direct).

Existing contract tests (test_15, test_15_b) in test_youtube_provider.py
must continue passing — they mock yt_dlp.YoutubeDL directly.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.services import material
from app.services.material import (
    _build_youtube_ydl_opts,
    _classify_youtube_failure,
    _fetch_po_token_from_provider,
    _fetch_po_token_via_browser,
    _record_youtube_failure,
    _run_youtube_download_attempt,
    _youtube_runtime_diagnostics,
    save_video_youtube,
)
from app.utils import utils


# ── helpers ──────────────────────────────────────────────────────────────────

def _mock_ydl(download_returns_path=True, raises=None):
    mock_ydl = MagicMock()
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)
    if raises:
        mock_ydl.download.side_effect = raises
    elif download_returns_path:
        def _fake_download(urls, **kwargs):
            return [{"_filename": "/tmp/fake.mp4"}]
        mock_ydl.download = _fake_download
    return mock_ydl


# ── Test 19: failure classification ─────────────────────────────────────────

@pytest.mark.parametrize("error_msg,expected", [
    ("ERROR: YouTube said: Unable to extract video data", "playability_blocked"),
    ("ERROR: Video unavailable", "playability_blocked"),
    ("HTTP Error 403: Forbidden", "bot_detected"),
    ("Sign in to confirm you are not a bot", "bot_detected"),
    ("PO token provider unreachable", "provider_unreachable"),
    ("PO token provider ping failed", "provider_ping_failed"),
    ("yt-dlp PO token extraction failed", "provider_pot_failed"),
    ("nodriver is not installed", "playwright_unavailable"),
    ("browser launch failed: chromium not found", "browser_launch_failed"),
    ("browser navigation failed", "browser_navigation_failed"),
    ("browser PO token extraction failed", "browser_pot_failed"),
    ("yt-dlp with browser PO token failed", "ytdlp_browser_failed"),
    ("some random error", "generic_download_error"),
])
def test_19_classify_youtube_failure(error_msg, expected):
    assert _classify_youtube_failure(error_msg) == expected


# ── Test 20: runtime diagnostics ─────────────────────────────────────────────

def test_20_youtube_runtime_diagnostics(monkeypatch):
    monkeypatch.setattr(material, "yt_dlp", MagicMock())
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os, "access", lambda p, m: True)
    monkeypatch.setattr(material.shutil, "which", lambda p: "/usr/bin/ffmpeg")

    cfg = {
        "youtube_cookies_file": "/tmp/cookies.txt",
        "youtube_po_token_provider_url": "http://127.0.0.1:4416",
        "youtube_browser_fallback": True,
        "youtube_max_provider_attempts": 2,
    }
    monkeypatch.setattr(material.config, "app", cfg)

    diag = _youtube_runtime_diagnostics()
    assert diag["yt_dlp_installed"] is True
    assert diag["cookies_file_configured"] is True
    assert diag["cookies_file_exists"] is True
    assert diag["cookies_file_readable"] is True
    assert diag["ffmpeg_available"] is True
    assert diag["po_token_provider_configured"] is True
    assert diag["browser_fallback_enabled"] is True
    assert diag["max_provider_attempts"] == 2


# ── Test 21: yt-dlp options builder ─────────────────────────────────────────

def test_21_build_youtube_ydl_opts():
    video_path = "/tmp/vid-abc123.mp4"
    opts = _build_youtube_ydl_opts(video_path)
    assert opts["outtmpl"] == video_path
    assert opts["format"].startswith("bestvideo")
    assert opts["extractor_args"]["youtube"]["player_client"] == ["web"]
    assert "po_token" not in opts["extractor_args"]["youtube"]

    opts_with_token = _build_youtube_ydl_opts(
        video_path, po_token="tok_123", player_client="mweb"
    )
    assert opts_with_token["extractor_args"]["youtube"]["player_client"] == ["mweb"]
    assert opts_with_token["extractor_args"]["youtube"]["po_token"] == ["tok_123"]


# ── Test 22: single download attempt ────────────────────────────────────────

def test_22_run_youtube_download_attempt_success(tmp_path, monkeypatch):
    video_path = str(tmp_path / "vid-xyz.mp4")
    # Simulate yt-dlp writing the file
    def fake_download(urls, **kwargs):
        Path(video_path).write_text("fake")
        return [{"_filename": video_path}]

    mock_ydl = MagicMock()
    mock_ydl.download = fake_download
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        saved, err = _run_youtube_download_attempt(
            "https://youtube.com/watch?v=xyz", video_path, attempt_label="bgutil"
        )
    assert saved == video_path
    assert err is None


def test_22_b_run_youtube_download_attempt_failure(tmp_path):
    video_path = str(tmp_path / "vid-xyz.mp4")
    mock_ydl = _mock_ydl(raises=Exception("network error"))
    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        saved, err = _run_youtube_download_attempt(
            "https://youtube.com/watch?v=xyz", video_path, attempt_label="direct"
        )
    assert saved == ""
    assert "direct" in err
    assert "network error" in err


# ── Test 23: PO token provider fetch ────────────────────────────────────────

def test_23_fetch_po_token_from_provider_success(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.json.return_value = {"pot": "tok_abc123"}

    with patch.object(material.requests, "get", return_value=mock_resp):
        token = _fetch_po_token_from_provider("http://127.0.0.1:4416")
    assert token == "tok_abc123"


def test_23_b_fetch_po_token_from_provider_not_found(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.status_code = 404

    with patch.object(material.requests, "get", return_value=mock_resp):
        token = _fetch_po_token_from_provider("http://127.0.0.1:4416")
    assert token is None


# ── Test 24: browser PO token fallback ───────────────────────────────────────

def test_24_fetch_po_token_via_browser_nodriver_missing(monkeypatch):
    with patch.dict(sys.modules, {"nodriver": None}):
        token = _fetch_po_token_via_browser("https://youtube.com/watch?v=abc")
    assert token is None


def test_24_b_fetch_po_token_via_browser_extracts_token(monkeypatch):
    mock_page = MagicMock()
    mock_page.evaluate.return_value = "tok_from_browser"
    mock_browser = MagicMock()
    mock_browser.get.return_value = mock_page
    mock_browser.quit = MagicMock()

    mock_nd = MagicMock()
    mock_nd.start = MagicMock(return_value=mock_browser)

    def fake_asyncio_run(coro):
        return "tok_from_browser"

    with patch.dict(sys.modules, {"nodriver": mock_nd}):
        with patch("asyncio.run", side_effect=fake_asyncio_run):
            token = _fetch_po_token_via_browser("https://youtube.com/watch?v=abc")
    assert token == "tok_from_browser"


# ── Test 25: save_video_youtube 2-attempt strategy ───────────────────────────

def test_25_save_video_youtube_bgutil_success(tmp_path, monkeypatch):
    video_url = "https://www.youtube.com/watch?v=aB3kZ9qWe1s"
    identity = material._youtube_video_identity(video_url)
    url_hash = utils.md5(identity)
    video_path = str(tmp_path / f"vid-{url_hash}.mp4")

    def fake_download(urls, **kwargs):
        Path(video_path).write_text("fake")
        return [{"_filename": video_path}]

    mock_ydl = MagicMock()
    mock_ydl.download = fake_download
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)

    cfg = {
        "youtube_cookies_file": "",
        "youtube_po_token_provider_url": "http://127.0.0.1:4416",
        "youtube_player_client": "web",
        "youtube_browser_fallback": True,
        "youtube_max_provider_attempts": 2,
    }
    monkeypatch.setattr(material.config, "app", cfg)

    with patch.object(material, "_fetch_po_token_from_provider", return_value="tok_123"):
        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            result = save_video_youtube(video_url=video_url, save_dir=str(tmp_path))

    assert result and Path(result).exists()
    Path(result).unlink(missing_ok=True)


def test_25_b_save_video_youtube_no_auth_falls_back_to_direct(tmp_path, monkeypatch):
    video_url = "https://www.youtube.com/watch?v=aB3kZ9qWe1s"
    identity = material._youtube_video_identity(video_url)
    url_hash = utils.md5(identity)
    video_path = str(tmp_path / f"vid-{url_hash}.mp4")

    def fake_download(urls, **kwargs):
        Path(video_path).write_text("fake")
        return [{"_filename": video_path}]

    mock_ydl = MagicMock()
    mock_ydl.download = fake_download
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)

    cfg = {
        "youtube_cookies_file": "",
        "youtube_po_token_provider_url": "",
        "youtube_player_client": "web",
        "youtube_browser_fallback": True,
        "youtube_max_provider_attempts": 2,
    }
    monkeypatch.setattr(material.config, "app", cfg)

    with patch.object(material, "_fetch_po_token_via_browser", return_value=None):
        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            result = save_video_youtube(video_url=video_url, save_dir=str(tmp_path))

    assert result and Path(result).exists()
    Path(result).unlink(missing_ok=True)


def test_25_c_save_video_youtube_all_attempts_fail(tmp_path, monkeypatch):
    video_url = "https://www.youtube.com/watch?v=aB3kZ9qWe1s"

    mock_ydl = MagicMock()
    mock_ydl.download = MagicMock()
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)

    cfg = {
        "youtube_cookies_file": "",
        "youtube_po_token_provider_url": "http://127.0.0.1:4416",
        "youtube_player_client": "web",
        "youtube_browser_fallback": True,
        "youtube_max_provider_attempts": 2,
    }
    monkeypatch.setattr(material.config, "app", cfg)

    with patch.object(material, "_fetch_po_token_from_provider", return_value=None):
        with patch.object(material, "_fetch_po_token_via_browser", return_value=None):
            with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
                result = save_video_youtube(video_url=video_url, save_dir=str(tmp_path))

    assert result == ""


# ── Test 26: no infinite retry ───────────────────────────────────────────────

def test_26_no_infinite_retry(monkeypatch):
    call_count = {"fetch_provider": 0, "fetch_browser": 0, "download": 0}

    def mock_fetch_provider(url):
        call_count["fetch_provider"] += 1
        return "tok_123"

    def mock_fetch_browser(url):
        call_count["fetch_browser"] += 1
        return None

    def fake_download(urls, **kwargs):
        call_count["download"] += 1
        return []

    mock_ydl = MagicMock()
    mock_ydl.download = fake_download
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)

    cfg = {
        "youtube_cookies_file": "",
        "youtube_po_token_provider_url": "http://127.0.0.1:4416",
        "youtube_player_client": "web",
        "youtube_browser_fallback": True,
        "youtube_max_provider_attempts": 2,
    }
    monkeypatch.setattr(material.config, "app", cfg)

    with patch.object(material, "_fetch_po_token_from_provider", side_effect=mock_fetch_provider):
        with patch.object(material, "_fetch_po_token_via_browser", side_effect=mock_fetch_browser):
            with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
                result = save_video_youtube(
                    video_url="https://youtube.com/watch?v=abc",
                    save_dir="/tmp",
                )

    assert result == ""
    assert call_count["fetch_provider"] <= 2
    assert call_count["fetch_browser"] <= 2
    assert call_count["download"] <= 2


# ── Test 27: source metadata includes video_id ───────────────────────────────

def test_27_search_videos_youtube_includes_video_id(monkeypatch):
    from app.services.material import search_videos_youtube
    from app.models.schema import VideoAspect

    entries = [
        {
            "id": "vid123",
            "title": "Test Video",
            "duration": 300,
            "channel": "TestChannel",
            "weburl": "https://www.youtube.com/watch?v=vid123",
            "url": "https://www.youtube.com/watch?v=vid123",
            "formats": [],
        }
    ]

    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = {"entries": entries, "_type": "playlist"}
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        results = search_videos_youtube(
            search_term="test", minimum_duration=3, video_aspect=VideoAspect.portrait
        )

    assert len(results) == 1
    info = results[0].source_info or {}
    assert info.get("video_id") == "vid123"
    assert info.get("asset_id") == "vid123"


# ── Test 28: secret safety ───────────────────────────────────────────────────

def test_28_no_secrets_in_logs(monkeypatch, caplog):
    import logging
    caplog.set_level(logging.WARNING)

    _record_youtube_failure("bot_detected", "secret_key=ABC123 should not appear")
    assert "ABC123" not in caplog.text

    _record_youtube_failure("generic_download_error", "http://user:pass@example.com/video")
    assert "user:pass" not in caplog.text


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
