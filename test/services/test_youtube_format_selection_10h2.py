"""Phase 10H.2 — YouTube format-selection regression tests.

Isolated (mocked yt-dlp for configuration checks; offline format parsing for
resolution checks).  No real downloads, no secrets.  Validates that
``save_video_youtube`` uses the evidence-based selector (best H.264 MP4 video
<=720p + AAC audio, merged to MP4, with a safe progressive fallback), never
exceeds 720p, and prefers DASH 720p H.264 over the old 360p progressive pick.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from app.services import material

# Expected selector (kept in sync with save_video_youtube).  Documented here so a
# regression test fails loudly if the runtime string drifts from the design.
EXPECTED_FORMAT = (
    "bestvideo[vcodec^=avc1][ext=mp4][height<=720]+bestaudio[acodec^=mp4a]/best"
)


def _fmt(format_id, ext, vcodec, acodec, width=None, height=None):
    d = {"format_id": format_id, "ext": ext, "vcodec": vcodec,
         "acodec": acodec, "url": "https://x"}
    if width is not None:
        d["width"] = width
    if height is not None:
        d["height"] = height
    return d


def test_format_selector_configuration():
    """save_video_youtube passes the exact evidence-based selector + MP4 merge."""
    mock_ydl = MagicMock()
    mock_ydl.__enter__.return_value = mock_ydl
    mock_ydl.__exit__.return_value = False

    captured = {}

    def _ctor(opts=None, **kw):
        captured.update(opts or {})
        return mock_ydl

    with patch("yt_dlp.YoutubeDL", side_effect=_ctor):
        material.save_video_youtube(
            "https://www.youtube.com/watch?v=CFGTEST000", save_dir="/tmp/__noop"
        )
    assert captured.get("format") == EXPECTED_FORMAT, captured.get("format")
    assert captured.get("merge_output_format") == "mp4"
    assert "height<=720" in captured["format"]          # never exceeds 720p
    assert "bestvideo" in captured["format"]            # video-only DASH preferred
    assert "bestaudio" in captured["format"]            # separate audio stream
    assert captured["format"].endswith("/best")         # safe fallback present


def test_format_selector_picks_720p_h264_over_360p_progressive():
    """Offline format resolution: the new selector must choose 720p H.264 + AAC
    DASH streams, NOT the 360p progressive format the old selector chose."""
    import yt_dlp
    fmts = [
        _fmt("18", "mp4", "avc1.42001E", "mp4a.40.2", 640, 360),   # progressive 360p
        _fmt("136", "mp4", "avc1.4d401f", "none", 1280, 720),      # DASH 720p H.264
        _fmt("398", "mp4", "av01.0.05M.08", "none", 1280, 720),    # DASH 720p AV1
        _fmt("140", "m4a", "none", "mp4a.40.2"),                   # AAC audio
        _fmt("251", "webm", "none", "opus"),                       # opus audio
    ]
    ctx = {"formats": fmts}
    ydl = yt_dlp.YoutubeDL()
    chosen = list(ydl.build_format_selector(EXPECTED_FORMAT)(ctx))
    merged = "136+140"
    assert any(merged in f["format_id"] for f in chosen), (
        f"expected 720p H264+AAC ({merged}), got {[f['format_id'] for f in chosen]}")
    assert any(f.get("vcodec") == "avc1.4d401f" for f in chosen)
    assert any(f.get("acodec") == "mp4a.40.2" for f in chosen)
    # Document the old behavior regression: the old selector would pick 360p.
    old_chosen = [f["format_id"] for f in list(
        ydl.build_format_selector("best[ext=mp4][height<=720]")(ctx))]
    assert old_chosen == ["18"], f"old selector should have been 360p, got {old_chosen}"


def test_format_selector_does_not_exceed_720p():
    """Even when 1080p H.264 is available, the selector must stay <=720p."""
    import yt_dlp
    fmts = [
        _fmt("18", "mp4", "avc1.42001E", "mp4a.40.2", 640, 360),
        _fmt("136", "mp4", "avc1.4d401f", "none", 1280, 720),
        _fmt("137", "mp4", "avc1.640028", "none", 1920, 1080),     # 1080p H.264
        _fmt("140", "m4a", "none", "mp4a.40.2"),
    ]
    ctx = {"formats": fmts}
    ydl = yt_dlp.YoutubeDL()
    chosen = list(ydl.build_format_selector(EXPECTED_FORMAT)(ctx))
    for f in chosen:
        if f.get("height"):
            assert f["height"] <= 720, f"exceeded 720p: {f['format_id']}"
    assert any("136" in f["format_id"] for f in chosen), \
        f"expected 720p (136) selected, got {[f['format_id'] for f in chosen]}"


def test_format_selector_fallback_when_no_h264_dash():
    """When only progressive 360p + webm audio exist (no H.264 DASH), the
    selector safely falls back to the progressive MP4 (no crash, still MP4)."""
    import yt_dlp
    fmts = [
        _fmt("18", "mp4", "avc1.42001E", "mp4a.40.2", 640, 360),
        _fmt("251", "webm", "none", "opus"),
    ]
    ctx = {"formats": fmts}
    ydl = yt_dlp.YoutubeDL()
    chosen = list(ydl.build_format_selector(EXPECTED_FORMAT)(ctx))
    ids = [f["format_id"] for f in chosen]
    assert "18" in ids, f"fallback should pick progressive 360p, got {ids}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
