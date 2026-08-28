"""Phase 10H.1 — YouTube cache-identity canonicalization regression tests.

Isolated (mocked yt-dlp), no real downloads, no secrets.  Validates that
distinct videos never collide in cache_videos/, equivalent supported URLs for
the same video share one identity, malformed/non-YouTube URLs fail safe, and
the resulting filename still matches the recognized sweeper pattern.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from app.services import material

CACHE_FILE_RE = re.compile(r"^vid-[0-9a-f]{32}\.mp4$")


def test_cache_distinct_videos_never_collide():
    a = material._youtube_video_identity("https://www.youtube.com/watch?v=AAA11111111")
    b = material._youtube_video_identity("https://www.youtube.com/watch?v=BBB22222222")
    assert a != b
    assert a == "yt:AAA11111111"
    assert b == "yt:BBB22222222"


def test_cache_equivalent_urls_share_identity():
    base = "AAA11111111"
    urls = [
        f"https://www.youtube.com/watch?v={base}",
        f"https://www.youtube.com/watch?v={base}&feature=youtu.be",
        f"https://www.youtube.com/watch?v={base}&t=30&list=PLxyz",
        f"https://youtu.be/{base}",
        f"https://youtu.be/{base}?t=10",
        f"https://www.youtube.com/shorts/{base}",
        f"https://m.youtube.com/watch?v={base}",
        f"https://music.youtube.com/watch?v={base}",
        f"https://www.youtube.com/embed/{base}",
    ]
    ids = {material._youtube_video_identity(u) for u in urls}
    assert ids == {"yt:" + base}, f"equivalent URLs diverged: {ids}"


def test_cache_deterministic():
    u = "https://www.youtube.com/watch?v=AAA11111111"
    assert material._youtube_video_identity(u) == material._youtube_video_identity(u)


def test_cache_malformed_url_safe():
    assert material._youtube_video_identity("https://www.youtube.com/watch?v=SHORT") is None
    assert material._youtube_video_identity("https://youtu.be/") is None
    assert material._youtube_video_identity("https://www.youtube.com/watch?v=") is None
    assert material._youtube_video_identity("https://example.com/v/AAA11111111") is None
    assert material._youtube_video_identity("not a url at all") is None


def test_cache_filename_pattern_compatible():
    u = "https://www.youtube.com/watch?v=AAA11111111"
    ident = material._youtube_video_identity(u)
    name = f"vid-{material.utils.md5(ident)}.mp4"
    assert CACHE_FILE_RE.match(name), name


def test_cache_unrelated_provider_unaffected():
    assert material._youtube_video_identity("https://images.pexels.com/videos/foo.mp4") is None
    assert material._youtube_video_identity("https://cdn.example.com/clip.mp4") is None


def test_cache_lookup_reuses_existing_file():
    """save_video_youtube returns the cached path without re-downloading when the
    file already exists (regression for the cache-lookup path)."""
    import os, tempfile
    tmp = tempfile.mkdtemp()
    url = "https://www.youtube.com/watch?v=LOOKUP1111a"
    ident = material._youtube_video_identity(url)
    expected = os.path.join(tmp, f"vid-{material.utils.md5(ident)}.mp4")

    mock_ydl = MagicMock()
    mock_ydl.__enter__.return_value = mock_ydl
    mock_ydl.__exit__.return_value = False
    calls = {"n": 0}

    def fake_download(urls, **kwargs):
        calls["n"] += 1
        with open(expected, "w") as f:
            f.write("bytes")
        return [{"_filename": expected}]

    mock_ydl.download = fake_download

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        first = material.save_video_youtube(url, save_dir=tmp)
        second = material.save_video_youtube(url, save_dir=tmp)
    assert first == expected and os.path.exists(first)
    assert second == expected
    assert calls["n"] == 1
    os.unlink(expected)


def test_cache_equivalent_url_variation_no_double_download():
    """Two equivalent but textually different URLs for the SAME video must resolve
    to the same cache file, so the video is not downloaded twice."""
    import os, tempfile
    tmp = tempfile.mkdtemp()
    watch = "https://www.youtube.com/watch?v=SAMEVID0001"
    youtu = "https://youtu.be/SAMEVID0001"
    ident = material._youtube_video_identity(watch)
    expected = os.path.join(tmp, f"vid-{material.utils.md5(ident)}.mp4")

    mock_ydl = MagicMock()
    mock_ydl.__enter__.return_value = mock_ydl
    mock_ydl.__exit__.return_value = False
    calls = {"n": 0}

    def fake_download(urls, **kwargs):
        calls["n"] += 1
        with open(expected, "w") as f:
            f.write("bytes")
        return [{"_filename": expected}]

    mock_ydl.download = fake_download

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        material.save_video_youtube(watch, save_dir=tmp)
        material.save_video_youtube(youtu, save_dir=tmp)
    assert calls["n"] == 1
    os.unlink(expected)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
