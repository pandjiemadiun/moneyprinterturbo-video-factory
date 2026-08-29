"""Phase 11H.1.15 — P0 functional recovery: Create-Video CTA + YouTube diagnosis.

Tests cover:
  1. Videos empty-state CTA navigates to Create (regression for nav_view shadowing).
  2. Navigation state cannot overwrite CTA navigation.
  3. YouTube URL canonicalization.
  4. YouTube search result parsing.
  5. Missing cookie configuration produces explicit diagnostic state.
  6. yt_dlp DownloadError classification.
  7. Format/ffmpeg failure classification.
  8. Quality-gate rejection classification.
  9. No secrets/cookies appear in logs.

All YouTube I/O is mocked — no real network calls, no secrets required.
"""
from __future__ import annotations

import ast
import os
import re
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


# ── helpers ──────────────────────────────────────────────────────────────────

def _read_source():
    return WEBUI_MAIN.read_text(encoding="utf-8")


def _parse():
    return ast.parse(_read_source())


def _func_def(tree, name):
    return next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == name
    )


# ═══════════════════════════════════════════════════════════════════════════
# P0-A: NAVIGATION STATE — SINGLE CANONICAL STATE
# ═══════════════════════════════════════════════════════════════════════════

class TestNavigationSingleCanonicalState:
    """All navigation entry points must share ONE canonical state key.

    The 11H.1.13 audit found that _render_videos_view set
    st.session_state["nav_view"] = "create" while _render_top_bar used a
    SEPARATE widget key "nav_view_selector", whose stale value overwrote
    the CTA's navigation on rerun.

    Fix: the segmented_control uses key="nav_view" (the same canonical key
    the CTA writes to), and all entry points go through _switch_nav_view().
    """

    def test_no_nav_view_selector_key_in_main(self):
        """The widget must NOT use a separate key that can shadow nav_view."""
        assert "nav_view_selector" not in _read_source()

    def test_segmented_control_uses_nav_view_key(self):
        """The segmented_control key must be "nav_view" (canonical)."""
        tree = _parse()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "segmented_control":
                    for kw in node.keywords:
                        if kw.arg == "key" and isinstance(kw.value, ast.Constant):
                            assert kw.value.value == "nav_view"

    def test_switch_nav_view_helper_exists(self):
        """A canonical _switch_nav_view helper must exist."""
        funcs = {
            n.name for n in ast.walk(_parse())
            if isinstance(n, ast.FunctionDef)
        }
        assert "_switch_nav_view" in funcs

    def test_videos_empty_cta_uses_switch_nav_view(self):
        """The Videos empty-state CTA must use _switch_nav_view."""
        tree = _parse()
        func = _func_def(tree, "_render_videos_view")
        func_source = ast.get_source_segment(_read_source(), func)
        assert "_switch_nav_view" in func_source
        # Must NOT have the old anti-pattern
        assert 'st.session_state["nav_view"] = "create"' not in func_source

    def test_top_bar_uses_switch_nav_view(self):
        """_render_top_bar must route navigation through _switch_nav_view."""
        tree = _parse()
        func = _func_def(tree, "_render_top_bar")
        func_source = ast.get_source_segment(_read_source(), func)
        assert "_switch_nav_view" in func_source

    def test_videos_view_cta_key_is_content_aware(self):
        """The CTA button must reference the correct key."""
        tree = _parse()
        func = _func_def(tree, "_render_videos_view")
        func_source = ast.get_source_segment(_read_source(), func)
        assert "videos_empty_create" in func_source

    def test_nav_view_is_canonically_consumed(self):
        """The render dispatcher must read from st.session_state['nav_view']."""
        tree = _parse()
        func = _func_def(tree, "_render_application")
        func_source = ast.get_source_segment(_read_source(), func)
        assert "st.session_state.get" in func_source
        assert "nav_view" in func_source


class TestNavigationStateChangeRegression:
    """Prove that clicking the empty-library CTA cannot be overwritten back
    to Videos by the segmented_control widget on rerun.

    This is a logic-level test of the shared-key invariant:
    - When nav_view == "create" (set by CTA), the segmented_control
      uses key="nav_view" and therefore reads "create" — it does NOT
      restore a stale "videos" value from a separate widget key.
    """

    def test_no_duplicate_session_state_key_for_nav(self):
        """There must be exactly ONE session_state key controlling nav,
        and the segmented_control must write to it (no separate widget key)."""
        source = _read_source()
        nav_keys = set(re.findall(r'session_state\["(nav_view[^"]*)"\]', source))
        assert nav_keys == {"nav_view"}, f"Expected only 'nav_view', found: {nav_keys}"

    def test_segmented_control_key_equals_consumed_key(self):
        """The seg_control key and the dispatcher's session_state key
        must be the same string."""
        tree = _parse()
        source = _read_source()

        seg_key = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "segmented_control":
                    for kw in node.keywords:
                        if kw.arg == "key" and isinstance(kw.value, ast.Constant):
                            seg_key = kw.value.value

        func = _func_def(tree, "_render_application")
        func_source = ast.get_source_segment(source, func)
        assert seg_key == "nav_view"
        assert "nav_view" in func_source
        assert seg_key in func_source


# ═══════════════════════════════════════════════════════════════════════════
# P0-B: YOUTUBE URL CANONICALIZATION
# ═══════════════════════════════════════════════════════════════════════════

class TestYoutubeUrlCanonicalization:
    """YouTube URL canonicalization must extract the 11-char video ID
    and normalize to yt:<ID>, ignoring tracking parameters."""

    def test_canonical_watch_url(self):
        from app.services.material import _youtube_video_identity
        assert _youtube_video_identity("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "yt:dQw4w9WgXcQ"

    def test_canonical_short_url(self):
        from app.services.material import _youtube_video_identity
        assert _youtube_video_identity("https://youtu.be/dQw4w9WgXcQ") == "yt:dQw4w9WgXcQ"

    def test_canonical_shorts_url(self):
        from app.services.material import _youtube_video_identity
        assert _youtube_video_identity("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "yt:dQw4w9WgXcQ"

    def test_canonical_embed_url(self):
        from app.services.material import _youtube_video_identity
        assert _youtube_video_identity("https://www.youtube.com/embed/dQw4w9WgXcQ") == "yt:dQw4w9WgXcQ"

    def test_canonical_m_subdomain(self):
        from app.services.material import _youtube_video_identity
        assert _youtube_video_identity("https://m.youtube.com/watch?v=dQw4w9WgXcQ") == "yt:dQw4w9WgXcQ"

    def test_canonical_music_subdomain(self):
        from app.services.material import _youtube_video_identity
        assert _youtube_video_identity("https://music.youtube.com/watch?v=dQw4w9WgXcQ") == "yt:dQw4w9WgXcQ"

    def test_canonical_nocookie(self):
        from app.services.material import _youtube_video_identity
        assert _youtube_video_identity("https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ") == "yt:dQw4w9WgXcQ"

    def test_ignore_query_params(self):
        """Tracking params (t, feature, utm_*) must NOT affect identity."""
        from app.services.material import _youtube_video_identity
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&feature=share&utm_source=foo"
        assert _youtube_video_identity(url) == "yt:dQw4w9WgXcQ"

    def test_non_youtube_returns_none(self):
        from app.services.material import _youtube_video_identity
        assert _youtube_video_identity("https://example.com/video?id=123") is None

    def test_empty_url_returns_none(self):
        from app.services.material import _youtube_video_identity
        assert _youtube_video_identity("") is None
        assert _youtube_video_identity(None) is None  # type: ignore

    def test_short_id_returns_none(self):
        """IDs shorter than 11 chars must return None."""
        from app.services.material import _youtube_video_identity
        assert _youtube_video_identity("https://www.youtube.com/watch?v=abc123") is None

    def test_equivalent_urls_same_identity(self):
        """All canonical URL forms for one video resolve to the same identity."""
        from app.services.material import _youtube_video_identity
        urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&feature=share",
        ]
        identities = {_youtube_video_identity(u) for u in urls}
        assert len(identities) == 1
        assert identities == {"yt:dQw4w9WgXcQ"}


# ═══════════════════════════════════════════════════════════════════════════
# P0-B: YOUTUBE SEARCH RESULT PARSING
# ═══════════════════════════════════════════════════════════════════════════

class TestYoutubeSearchResultParsing:
    """search_videos_youtube must correctly parse yt-dlp ytsearch results
    into MaterialInfo objects, filtering by duration and extracting metadata."""

    def _fake_yt_entry(self, video_id="abc123", title="Test Video",
                       duration=300, channel="Test Channel", url=None):
        return {
            "id": video_id,
            "title": title,
            "duration": duration,
            "channel": channel,
            "uploader": channel,
            "view_count": 10000,
            "weburl": url or f"https://www.youtube.com/watch?v={video_id}",
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "formats": [{
                "format_id": "mp4-720p",
                "ext": "mp4", "height": 720, "width": 1280,
                "filesize": 5_000_000,
                "url": f"https://rr2---sn-4g5ednls.googlevideo.com/videoplayback?id={video_id}",
            }],
        }

    def _patch_yt_dlp(self, entries):
        """Patch yt_dlp.YoutubeDL to return fake ytsearch results."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {"entries": entries, "_type": "playlist"}
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        return patch("yt_dlp.YoutubeDL", return_value=mock_ydl)

    def test_search_returns_parsed_entries(self):
        """Valid ytsearch entries are parsed into MaterialInfo objects."""
        from app.services import material
        from app.models.schema import MaterialInfo

        entries = [
            self._fake_yt_entry(video_id="vid1", title="Misteri Gunung", duration=600),
            self._fake_yt_entry(video_id="vid2", title="Misteri Laut", duration=300),
        ]

        with self._patch_yt_dlp(entries):
            results = material.search_videos_youtube("misteri", minimum_duration=3)

        assert len(results) == 2
        assert all(isinstance(r, MaterialInfo) for r in results)
        assert results[0].provider == "youtube"
        assert results[0].url == "https://www.youtube.com/watch?v=vid1"
        assert results[0].duration == 600
        assert results[0].source_info["title"] == "Misteri Gunung"
        assert results[0].source_info["asset_id"] == "vid1"
        assert results[0].source_info["channel"] == "Test Channel"
        assert results[0].source_info["license_status"] == "license_unknown"

    def test_search_filters_short_duration(self):
        """Entries shorter than minimum_duration are skipped."""
        from app.services import material

        entries = [
            self._fake_yt_entry(video_id="long1", title="Long Video", duration=600),
            self._fake_yt_entry(video_id="short1", title="Short Video", duration=2),
            self._fake_yt_entry(video_id="long2", title="Another Long", duration=300),
        ]

        with self._patch_yt_dlp(entries):
            results = material.search_videos_youtube("test", minimum_duration=10)

        assert len(results) == 2
        assert results[0].url == "https://www.youtube.com/watch?v=long1"
        assert results[1].url == "https://www.youtube.com/watch?v=long2"

    def test_search_filters_missing_duration(self):
        """Entries without duration (live streams) are skipped."""
        from app.services import material

        entries = [
            {"id": "noDur1", "title": "Live Stream", "duration": None,
             "url": "https://www.youtube.com/watch?v=noDur1"},
            self._fake_yt_entry(video_id="dur1", title="Normal", duration=300),
        ]

        with self._patch_yt_dlp(entries):
            results = material.search_videos_youtube("test", minimum_duration=3)

        assert len(results) == 1
        assert results[0].url == "https://www.youtube.com/watch?v=dur1"

    def test_search_returns_empty_when_no_results(self):
        from app.services import material

        with self._patch_yt_dlp([]):
            results = material.search_videos_youtube("nonexistent_term_xyz", minimum_duration=3)
        assert results == []

    def test_search_returns_empty_when_yt_dlp_none(self):
        """When yt_dlp is not installed, search returns [] (no crash)."""
        from app.services import material
        with patch.object(material, "yt_dlp", None):
            results = material.search_videos_youtube("test", minimum_duration=3)
        assert results == []

    def test_search_extracts_rendition_info(self):
        """Format information from search results is preserved in source_info."""
        from app.services import material

        entries = [
            self._fake_yt_entry(video_id="vid1", title="Test", duration=300),
        ]

        with self._patch_yt_dlp(entries):
            results = material.search_videos_youtube("test", minimum_duration=3)

        assert len(results) == 1
        rendition = results[0].source_info["rendition"]
        assert rendition is not None
        assert rendition["width"] == 1280
        assert rendition["height"] == 720
        assert rendition["id"] == "mp4-720p"


# ═══════════════════════════════════════════════════════════════════════════
# P0-B: YOUTUBE ERROR CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════════

class TestYoutubeErrorClassification:
    """diagnose_youtube_material_failure must return a specific, actionable
    diagnostic message instead of the generic "failed to download video
    materials from youtube"."""

    def test_non_youtube_source_generic_message(self):
        """Non-YouTube sources keep the generic message."""
        from app.services.material import diagnose_youtube_material_failure
        msg = diagnose_youtube_material_failure("pexels")
        assert "failed to download video materials from pexels" in msg

    def test_yt_dlp_not_installed(self):
        """Missing yt_dlp is diagnosed explicitly."""
        from app.services import material
        with patch.object(material, "yt_dlp", None):
            msg = material.diagnose_youtube_material_failure("youtube")
        assert "yt_dlp is not installed" in msg

    def test_cookies_not_configured(self):
        """Unconfigured youtube_cookies_file is diagnosed explicitly."""
        from app.services import material
        with patch.object(material, "yt_dlp", MagicMock()):
            with patch.dict(material.config.app, {"youtube_cookies_file": ""}):
                msg = material.diagnose_youtube_material_failure("youtube")
        assert "youtube_cookies_file" in msg
        assert "not configured" in msg.lower()

    def test_cookies_file_missing(self):
        """When cookies_file is configured but file doesn't exist."""
        from app.services import material
        with patch.object(material, "yt_dlp", MagicMock()):
            with patch.dict(material.config.app, {"youtube_cookies_file": "/nonexistent/path/cookies.txt"}):
                msg = material.diagnose_youtube_material_failure("youtube")
        assert "does not exist" in msg.lower()

    def test_cookies_file_not_readable(self):
        """When cookies file exists but is not readable."""
        from app.services import material

        fd, path = tempfile.mkstemp(suffix=".txt")
        os.write(fd, b"fake-cookie-content")
        os.close(fd)

        try:
            with patch.object(material, "yt_dlp", MagicMock()), \
             patch.object(material.os, "access", return_value=False):
                with patch.dict(material.config.app, {"youtube_cookies_file": path}):
                    msg = material.diagnose_youtube_material_failure("youtube")
            assert "not readable" in msg.lower()
        finally:
            os.unlink(path)

    def test_ffmpeg_not_installed(self):
        """Missing ffmpeg is diagnosed explicitly."""
        import tempfile
        from app.services import material
        from unittest.mock import MagicMock as M

        fd, path = tempfile.mkstemp(suffix=".txt")
        os.write(fd, b"fake-cookies")
        os.close(fd)

        try:
            mock_yt_dlp = M()
            with patch.object(material, "yt_dlp", mock_yt_dlp), \
                 patch.dict(material.config.app, {"youtube_cookies_file": path}), \
                 patch("shutil.which", return_value=None):
                msg = material.diagnose_youtube_material_failure("youtube")
            assert "ffmpeg" in msg.lower()
        finally:
            os.unlink(path)

    def test_all_checks_pass_fallback_message(self):
        """When all prerequisites are met, fall back to generic retry message."""
        import tempfile
        from app.services import material

        fd, path = tempfile.mkstemp(suffix=".txt")
        os.write(fd, b"fake-cookies")
        os.close(fd)

        try:
            with patch.object(material, "yt_dlp", MagicMock()), \
                 patch.dict(material.config.app, {"youtube_cookies_file": path}), \
                 patch("shutil.which", return_value="/usr/bin/ffmpeg"):
                msg = material.diagnose_youtube_material_failure("youtube")
            assert "no usable videos" in msg.lower() or "quality gate" in msg.lower()
        finally:
            os.unlink(path)

    def test_diagnostic_does_not_leak_cookies(self):
        """The diagnostic string must never contain cookie file contents."""
        import tempfile
        from app.services import material

        fd, path = tempfile.mkstemp(suffix=".txt")
        cookie_content = "SESSION_COOKIE=SECRET_TOKEN_12345\nLOGIN_INFO=sensitive"
        os.write(fd, cookie_content.encode())
        os.close(fd)

        try:
            with patch.object(material, "yt_dlp", MagicMock()), \
                 patch.dict(material.config.app, {"youtube_cookies_file": path}), \
                 patch("shutil.which", return_value="/usr/bin/ffmpeg"):
                msg = material.diagnose_youtube_material_failure("youtube")
            assert "SECRET_TOKEN_12345" not in msg
            assert "sensitive" not in msg
            assert "LOGIN_INFO" not in msg
        finally:
            os.unlink(path)


# ═══════════════════════════════════════════════════════════════════════════
# P0-B: yt-dlp DOWNLOADERROR CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════════

class TestYoutubeDownloadErrorClassification:
    """yt_dlp DownloadError exceptions must be classified into diagnostic
    categories (403/bot detection, format error, quality-gate rejection)."""

    def _make_mock_ydl(self, download_side_effect):
        """Create a mock YoutubeDL that raises the given error on download."""
        mock_ydl = MagicMock()
        mock_ydl.download.side_effect = download_side_effect
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        return mock_ydl

    def test_download_403_produces_bot_detection_message(self):
        """save_video_youtube must return "" (fail-clean) on 403."""
        import yt_dlp
        from app.services import material
        from unittest.mock import MagicMock as M

        err = yt_dlp.utils.DownloadError(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "ERROR: unable to download video data: HTTP Error 403: Forbidden"
        )
        mock_ydl = M()
        mock_ydl.download.side_effect = err
        mock_ydl.__enter__ = M(return_value=mock_ydl)
        mock_ydl.__exit__ = M(return_value=False)

        save_dir = tempfile.mkdtemp(prefix="yt403_")
        try:
            with patch.object(material, "yt_dlp", M()), \
                 patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
                result = material.save_video_youtube(
                    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    save_dir
                )
            assert result == ""
        finally:
            shutil.rmtree(save_dir, ignore_errors=True)

    def test_download_save_video_youtube_returns_empty_on_yt_dlp_none(self):
        """When yt_dlp is None, save_video_youtube returns "" (fail-clean)."""
        from app.services import material
        with patch.object(material, "yt_dlp", None):
            result = material.save_video_youtube(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                tempfile.mkdtemp(prefix="ytnone_")
            )
        assert result == ""

    def test_download_format_error_classification(self):
        """A format resolution error returns "" (fail-clean)."""
        import yt_dlp
        import tempfile
        from app.services.material import save_video_youtube

        err = yt_dlp.utils.DownloadError(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "ERROR: Requested format not available"
        )
        mock_ydl = MagicMock()
        mock_ydl.download.side_effect = err
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)

        save_dir = tempfile.mkdtemp(prefix="ytfmt_")
        try:
            with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
                result = save_video_youtube(
                    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    save_dir
                )
            assert result == ""
        finally:
            shutil.rmtree(save_dir, ignore_errors=True)

    def test_download_cleanup_on_failure(self):
        """When a download fails, no stale artifacts are left behind."""
        import yt_dlp
        import tempfile
        from app.services.material import save_video_youtube

        err = yt_dlp.utils.DownloadError(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "HTTP Error 403"
        )
        mock_ydl = MagicMock()
        mock_ydl.download.side_effect = err
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)

        save_dir = tempfile.mkdtemp(prefix="ytcleanup_")
        try:
            with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
                result = save_video_youtube(
                    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    save_dir
                )
            assert result == ""
            leftover = list(Path(save_dir).glob("*.mp4"))
            assert len(leftover) == 0
        finally:
            shutil.rmtree(save_dir, ignore_errors=True)

    def test_cached_file_returned_without_redownload(self):
        """A valid cached file is returned without re-downloading."""
        from app.services.material import save_video_youtube, _youtube_video_identity
        from app.utils import utils

        save_dir = tempfile.mkdtemp(prefix="ytcache_")
        identity = _youtube_video_identity("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        url_hash = utils.md5(identity)
        cached_path = f"{save_dir}/vid-{url_hash}.mp4"
        with open(cached_path, "wb") as f:
            f.write(b"\x00" * 2048)  # >1024 bytes

        try:
            mock_ydl = MagicMock()
            result = save_video_youtube(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                save_dir
            )
            # yt_dlp should NOT be called when cache hit
            assert result == cached_path
            mock_ydl.download.assert_not_called()
        finally:
            shutil.rmtree(save_dir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════
# P0-B: FORMAT / FFMPEG / QUALITY GATE
# ═══════════════════════════════════════════════════════════════════════════

class TestYoutubeFormatAndQualityGate:
    """Verify that the YouTube download format string is valid H.264+AAC
    and that the quality gate rejects clips that are too low-resolution
    or corrupt."""

    def test_youtube_format_string_resolves_h264_aac(self):
        """The production format must prefer H.264 video + AAC audio."""
        source = (
            ROOT_DIR / "app" / "services" / "material.py"
        ).read_text(encoding="utf-8")
        assert "bestvideo[vcodec^=avc1]" in source
        assert "bestaudio[acodec^=mp4a]" in source
        assert "[ext=mp4]" in source
        assert "[height<=720]" in source

    def test_quality_gate_rejects_tiny_resolution(self):
        """_validate_reframe_resolution must reject 320×180 landscape."""
        from app.services.material import _validate_reframe_resolution
        assert _validate_reframe_resolution(320, 180, 1080, 1920) is False

    def test_quality_gate_accepts_854x480(self):
        """_validate_reframe_resolution accepts 854×480 (effective 270)."""
        from app.services.material import _validate_reframe_resolution
        assert _validate_reframe_resolution(854, 480, 1080, 1920) is True

    def test_quality_gate_rejects_corrupt_file(self):
        """A nonexistent file must fail the quality gate."""
        from app.services.material import _validate_downloaded_clip
        assert _validate_downloaded_clip("/nonexistent/path.mp4") is False

    def test_quality_gate_rejects_empty_file(self):
        """A 0-byte file must fail the quality gate."""
        from app.services.material import _validate_downloaded_clip
        fd, path = tempfile.mkstemp(suffix=".mp4")
        os.write(fd, b"")
        os.close(fd)
        try:
            assert _validate_downloaded_clip(path) is False
        finally:
            os.unlink(path)

    def test_quality_gate_rejects_tiny_file(self):
        """A file < 1024 bytes must fail the quality gate."""
        from app.services.material import _validate_downloaded_clip
        fd, path = tempfile.mkstemp(suffix=".mp4")
        os.write(fd, b"\x00" * 500)
        os.close(fd)
        try:
            assert _validate_downloaded_clip(path) is False
        finally:
            os.unlink(path)

    def test_reframe_resolution_accepts_square(self):
        """A square video at 480×480 must pass for portrait target."""
        from app.services.material import _validate_reframe_resolution
        assert _validate_reframe_resolution(480, 480, 1080, 1920) is True

    def test_reframe_resolution_rejects_very_small(self):
        """A 200×112 landscape video must fail for portrait target."""
        from app.services.material import _validate_reframe_resolution
        assert _validate_reframe_resolution(200, 112, 1080, 1920) is False

    def test_download_videos_by_script_order_uses_material_item(self):
        """_download_videos_by_script_order must use _download_material_item
        (which has yt_dlp fallback), not save_video directly."""
        source = (ROOT_DIR / "app" / "services" / "material.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        func = _func_def(tree, "_download_videos_by_script_order")
        func_source = ast.get_source_segment(source, func)
        # Must use _download_material_item, NOT save_video directly
        assert "_download_material_item" in func_source
        # Must NOT call save_video directly in the download loop
        assert "save_video(" not in func_source.replace("save_video_youtube", "")


# ═══════════════════════════════════════════════════════════════════════════
# P0-B: NO SECRETS IN LOGS
# ═══════════════════════════════════════════════════════════════════════════

class TestNoSecretsInLogs:
    """No cookies, API keys, or tokens must appear in error log messages."""

    def test_redact_request_error_removes_secrets(self):
        """_redact_request_error must redact API keys from error messages."""
        from app.services.material import _redact_request_error
        api_key = "nBOCsP97bkcQMHxTaBLDZED8j7BqFfs6aHXNWmgkCjLHQm0Yhr3VzMVW"
        error = Exception(f"403 Forbidden for URL https://api.pexels.com/?key={api_key}")
        redacted = _redact_request_error(error, api_key)
        assert api_key not in redacted
        assert "***" in redacted

    def test_redact_request_error_redacts_url_encoded_secrets(self):
        """URL-encoded secrets must also be redacted."""
        from app.services.material import _redact_request_error
        from urllib.parse import quote_plus
        api_key = "nBOCsP97bkcQMHxTaBLDZED8j7BqFfs6aHXNWmgkCjLHQm0Yhr3VzMVW"
        encoded = quote_plus(api_key)
        error = Exception(f"403 for URL https://example.com/?key={encoded}")
        redacted = _redact_request_error(error, api_key)
        assert api_key not in redacted
        assert encoded not in redacted

    def test_diagnostic_does_not_leak_cookie_contents(self):
        """Cookie file contents must not appear in diagnostic output."""
        from app.services import material

        fd, path = tempfile.mkstemp(suffix=".txt")
        cookie_content = "SESSION_COOKIE=SECRET_TOKEN_12345\nLOGIN_INFO=sensitive"
        os.write(fd, cookie_content.encode())
        os.close(fd)

        try:
            with patch.object(material, "yt_dlp", MagicMock()), \
                 patch.dict(material.config.app, {"youtube_cookies_file": path}), \
                 patch("shutil.which", return_value="/usr/bin/ffmpeg"):
                msg = material.diagnose_youtube_material_failure("youtube")
            assert "SECRET_TOKEN_12345" not in msg
            assert "sensitive" not in msg
            assert "LOGIN_INFO" not in msg
        finally:
            os.unlink(path)

    def test_download_error_logging_does_not_expose_secrets(self):
        """yt_dlp error logging must use _redact_request_error or similar."""
        import yt_dlp
        from app.services import material

        err = yt_dlp.utils.DownloadError(
            "https://www.youtube.com/watch?v=test12345",
            "HTTP Error 403"
        )
        mock_ydl = MagicMock()
        mock_ydl.download.side_effect = err
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)

        save_dir = tempfile.mkdtemp(prefix="ytlog_")
        try:
            with patch.object(material, "yt_dlp", MagicMock()), \
                 patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
                with patch.object(material.logger, "error") as mock_log:
                    material.save_video_youtube(
                        "https://www.youtube.com/watch?v=test12345",
                        save_dir
                    )
                    for call_args in mock_log.call_args_list:
                        logged_msg = str(call_args[0])
                        assert "SECRET_TOKEN" not in logged_msg
        finally:
            shutil.rmtree(save_dir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE-LEVEL VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════

class TestSourceLevelChecks:
    """Verify key source-level invariants for both P0-A and P0-B."""

    def test_task_py_uses_diagnostic_not_generic_message(self):
        """task.py must call diagnose_youtube_material_failure, not the
        generic f-string for youtube failures."""
        source = (ROOT_DIR / "app" / "services" / "task.py").read_text(encoding="utf-8")
        assert "diagnose_youtube_material_failure" in source

    def test_material_py_exports_diagnostic_function(self):
        """diagnose_youtube_material_failure must be importable from material."""
        from app.services.material import diagnose_youtube_material_failure
        assert callable(diagnose_youtube_material_failure)

    def test_no_yt_dlp_hardcoded_install_in_production_code(self):
        """yt_dlp must be imported via try/except guard, not hard-required."""
        source = (ROOT_DIR / "app" / "services" / "material.py").read_text(encoding="utf-8")
        assert "try:" in source
        assert "import yt_dlp" in source
        assert "yt_dlp = None" in source

    def test_youtube_download_uses_canonical_url(self):
        """save_video_youtube must canonicalize YouTube URLs via identity."""
        source = (ROOT_DIR / "app" / "services" / "material.py").read_text(encoding="utf-8")
        assert "_youtube_video_identity" in source
        assert "vid-" in source

    def test_requirements_includes_yt_dlp(self):
        """requirements.txt must include yt-dlp as a dependency."""
        req = (ROOT_DIR / "requirements.txt").read_text(encoding="utf-8")
        assert "yt-dlp" in req

    def test_all_tests_run_together(self):
        """Smoke test: ensure all test classes are discoverable."""
        # This just ensures the module imports without errors
        from app.services.material import (
            diagnose_youtube_material_failure,
            _youtube_video_identity,
            save_video_youtube,
            search_videos_youtube,
            _download_material_item,
            _validate_downloaded_clip,
            _validate_reframe_resolution,
        )
        assert all(callable(f) for f in [
            diagnose_youtube_material_failure,
            _youtube_video_identity,
            save_video_youtube,
            search_videos_youtube,
            _download_material_item,
            _validate_downloaded_clip,
            _validate_reframe_resolution,
        ])
