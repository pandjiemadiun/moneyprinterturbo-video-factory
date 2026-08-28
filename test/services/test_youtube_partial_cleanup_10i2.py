"""Phase 10I.2 — DEFECT-2 regression tests: partial YouTube download cleanup.

All tests use ISOLATED temporary directories and MOCKED yt-dlp (no real network,
no secrets, no production data). Validates that ``save_video_youtube()`` removes
partial artifacts left by yt-dlp after a failed download, while preserving
unrelated cache files and pre-existing cached files.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.services import material
from app.services.material import save_video_youtube, _youtube_video_identity
from app.utils import utils


CACHE_FILE_RE = re.compile(r"^vid-[0-9a-f]{32}\.mp4$")
CACHE_PART_RE = re.compile(r"^vid-[0-9a-f]{32}\.mp4\.part$")
CACHE_YTDL_RE = re.compile(r"^vid-[0-9a-f]{32}\.mp4\.ytdl$")
CACHE_FRAG_RE = re.compile(r"^vid-[0-9a-f]{32}\.mp4\.Frag\d+$")


def _canonical_vid_hash(video_url: str) -> str:
    """Compute the same cache filename that save_video_youtube would use."""
    identity = _youtube_video_identity(video_url)
    if identity:
        url_hash = utils.md5(identity)
    else:
        url_hash = utils.md5(video_url.split("?")[0])
    return f"vid-{url_hash}"


def _make_mock_ydl_download_error(error_message="simulated DownloadError",
                                   create_partial=False,
                                   save_dir=None,
                                   video_url=None):
    """Create a MagicMock YoutubeDL that raises DownloadError on .download().

    If create_partial is True, the mock simulates yt-dlp leaving a partial
    file at the outtmpl path before raising.
    """
    mock_ydl = MagicMock()
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)

    def boom_download(urls, **kwargs):
        if create_partial and save_dir is not None and video_url is not None:
            vid_hash = _canonical_vid_hash(video_url)
            partial_path = os.path.join(save_dir, f"{vid_hash}.mp4")
            Path(partial_path).write_bytes(b"\x00" * 512)
        raise material.yt_dlp.utils.DownloadError(error_message)

    mock_ydl.download = boom_download
    return mock_ydl


# ---------------------------------------------------------------------------
# TEST 1: partial target is removed after DownloadError
# ---------------------------------------------------------------------------

def test_defect2_partial_target_removed_after_download_error(tmp_path, monkeypatch):
    """When yt-dlp fails mid-download, the partial vid-<hash>.mp4 it created
    must be cleaned up by save_video_youtube(). The function returns ""
    and no partial artifact remains."""
    save_dir = str(tmp_path)
    video_url = "https://www.youtube.com/watch?v=FAILVID0001"

    mock_ydl = _make_mock_ydl_download_error(
        create_partial=True, save_dir=save_dir, video_url=video_url
    )

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        result = save_video_youtube(video_url, save_dir=save_dir)

    assert result == "", f"Expected empty string on failure, got {result!r}"
    vid_hash = _canonical_vid_hash(video_url)
    partial_path = tmp_path / f"{vid_hash}.mp4"
    assert not partial_path.exists(), (
        f"Partial artifact {partial_path.name} was NOT cleaned up after DownloadError"
    )


# ---------------------------------------------------------------------------
# TEST 2: .part artifact is removed after DownloadError
# ---------------------------------------------------------------------------

def test_defect2_part_artifact_removed_after_download_error(tmp_path, monkeypatch):
    """yt-dlp may leave a .part file (raw downloaded bytes). This must be
    cleaned up on failure."""
    save_dir = str(tmp_path)
    video_url = "https://www.youtube.com/watch?v=FAILVID0002"
    vid_hash = _canonical_vid_hash(video_url)

    mock_ydl = MagicMock()
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)

    def download_and_leave_part(urls, **kwargs):
        # Simulate yt-dlp leaving a .part file
        part_path = tmp_path / f"{vid_hash}.mp4.part"
        part_path.write_bytes(b"\x00" * 256)
        raise material.yt_dlp.utils.DownloadError("incomplete download")

    mock_ydl.download = download_and_leave_part

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        result = save_video_youtube(video_url, save_dir=save_dir)

    assert result == ""
    part_path = tmp_path / f"{vid_hash}.mp4.part"
    assert not part_path.exists(), (
        f".part artifact {part_path.name} was NOT cleaned up"
    )


# ---------------------------------------------------------------------------
# TEST 3: .ytdl artifact is removed after DownloadError
# ---------------------------------------------------------------------------

def test_defect2_ytdl_artifact_removed_after_download_error(tmp_path, monkeypatch):
    """yt-dlp may leave a .ytdl state file. This must be cleaned up on
    failure."""
    save_dir = str(tmp_path)
    video_url = "https://www.youtube.com/watch?v=FAILVID0003"
    vid_hash = _canonical_vid_hash(video_url)

    mock_ydl = MagicMock()
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)

    def download_and_leave_ytdl(urls, **kwargs):
        ytdl_path = tmp_path / f"{vid_hash}.mp4.ytdl"
        ytdl_path.write_bytes(b'{"extractor": "youtube"}')
        mp4_path = tmp_path / f"{vid_hash}.mp4"
        mp4_path.write_bytes(b"\x00" * 128)
        raise material.yt_dlp.utils.DownloadError("merge failed")

    mock_ydl.download = download_and_leave_ytdl

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        result = save_video_youtube(video_url, save_dir=save_dir)

    assert result == ""
    assert not (tmp_path / f"{vid_hash}.mp4.ytdl").exists()
    assert not (tmp_path / f"{vid_hash}.mp4").exists()


# ---------------------------------------------------------------------------
# TEST 4: fragment artifacts are removed after DownloadError
# ---------------------------------------------------------------------------

def test_defect2_fragment_artifacts_removed_after_download_error(tmp_path, monkeypatch):
    """yt-dlp may leave .Frag* fragment files during DASH download failure.
    These must be cleaned up."""
    save_dir = str(tmp_path)
    video_url = "https://www.youtube.com/watch?v=FAILVID0004"
    vid_hash = _canonical_vid_hash(video_url)

    mock_ydl = MagicMock()
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)

    def download_and_leave_frags(urls, **kwargs):
        frag1 = tmp_path / f"{vid_hash}.mp4.Frag1"
        frag2 = tmp_path / f"{vid_hash}.mp4.Frag2"
        frag1.write_bytes(b"fragment1")
        frag2.write_bytes(b"fragment2")
        raise material.yt_dlp.utils.DownloadError("fragment download failed")

    mock_ydl.download = download_and_leave_frags

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        result = save_video_youtube(video_url, save_dir=save_dir)

    assert result == ""
    assert not (tmp_path / f"{vid_hash}.mp4.Frag1").exists()
    assert not (tmp_path / f"{vid_hash}.mp4.Frag2").exists()


# ---------------------------------------------------------------------------
# TEST 5: unrelated cache files remain untouched
# ---------------------------------------------------------------------------

def test_defect2_unrelated_cache_files_remain(tmp_path, monkeypatch):
    """A pre-existing cache file for a DIFFERENT video must survive a failed
    download of another video."""
    save_dir = str(tmp_path)
    fail_url = "https://www.youtube.com/watch?v=FAILVID0005"
    unrelated_vid = "vid-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.mp4"
    unrelated_path = tmp_path / unrelated_vid

    # Create an unrelated pre-existing cache file
    unrelated_path.write_bytes(b"unrelated cached content")

    mock_ydl = _make_mock_ydl_download_error(
        create_partial=True, save_dir=save_dir, video_url=fail_url
    )

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        result = save_video_youtube(fail_url, save_dir=save_dir)

    assert result == ""
    assert unrelated_path.exists(), (
        "Unrelated cache file was incorrectly removed"
    )


# ---------------------------------------------------------------------------
# TEST 6: valid pre-existing cache is preserved (no double-download needed)
# ---------------------------------------------------------------------------

def test_defect2_valid_preexisting_cache_preserved(tmp_path, monkeypatch):
    """If a valid cached file already exists, save_video_youtube returns it
    without downloading. The pre-existing valid file must NOT be deleted."""
    save_dir = str(tmp_path)
    video_url = "https://www.youtube.com/watch?v=VALIDVID001"
    vid_hash = _canonical_vid_hash(video_url)
    video_path = tmp_path / f"{vid_hash}.mp4"

    # Pre-create a valid cached file
    video_path.write_bytes(b"valid cached video content")

    download_called = MagicMock()

    mock_ydl = MagicMock()
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)
    mock_ydl.download = download_called

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        result = save_video_youtube(video_url, save_dir=save_dir)

    assert result == str(video_path)
    assert video_path.exists()
    assert download_called.call_count == 0, "Should not download when cache exists"


# ---------------------------------------------------------------------------
# TEST 7: cleanup failure is non-fatal
# ---------------------------------------------------------------------------

def test_defect2_cleanup_failure_is_non_fatal(tmp_path, monkeypatch):
    """If the cleanup of partial artifacts fails (e.g. OSError), the original
    DownloadError behavior is preserved — save_video_youtube still returns ""
    and logs a warning. It must NOT return a false success."""
    save_dir = str(tmp_path)
    video_url = "https://www.youtube.com/watch?v=FAILVID0006"
    vid_hash = _canonical_vid_hash(video_url)

    mock_ydl = _make_mock_ydl_download_error(
        create_partial=True, save_dir=save_dir, video_url=video_url
    )

    # Patch os.remove to fail, simulating cleanup failure
    real_remove = os.remove

    def boom_remove(path):
        raise OSError("permission denied")

    monkeypatch.setattr(material.os, "remove", boom_remove)

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        result = save_video_youtube(video_url, save_dir=save_dir)

    assert result == "", "Must still return empty on failure even if cleanup fails"


# ---------------------------------------------------------------------------
# TEST 8: idempotency — cleanup when nothing exists
# ---------------------------------------------------------------------------

def test_defect2_idempotent_no_artifacts_no_crash(tmp_path, monkeypatch):
    """If yt-dlp fails and leaves NO artifacts behind, the function must still
    return '' without crashing (cleanup of nothing is non-fatal)."""
    save_dir = str(tmp_path)
    video_url = "https://www.youtube.com/watch?v=FAILVID0007"

    mock_ydl = _make_mock_ydl_download_error(
        create_partial=False, save_dir=None, video_url=None
    )

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        result = save_video_youtube(video_url, save_dir=save_dir)

    assert result == ""
    assert list(tmp_path.glob("vid-*")) == []


# ---------------------------------------------------------------------------
# TEST 9: generic exception (non-DownloadError) also cleans up
# ---------------------------------------------------------------------------

def test_defect2_generic_exception_cleans_partial(tmp_path, monkeypatch):
    """Non-DownloadError exceptions must also trigger partial cleanup."""
    save_dir = str(tmp_path)
    video_url = "https://www.youtube.com/watch?v=FAILVID0008"
    vid_hash = _canonical_vid_hash(video_url)

    mock_ydl = MagicMock()
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)

    def raise_generic(urls, **kwargs):
        partial = tmp_path / f"{vid_hash}.mp4"
        partial.write_bytes(b"\x00" * 100)
        raise RuntimeError("unexpected yt-dlp crash")

    mock_ydl.download = raise_generic

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        result = save_video_youtube(video_url, save_dir=save_dir)

    assert result == ""
    assert not (tmp_path / f"{vid_hash}.mp4").exists()


# ---------------------------------------------------------------------------
# TEST 10: concurrent/cache safety — valid cache not deleted by failed sibling
# ---------------------------------------------------------------------------

def test_defect2_concurrent_cache_safety(tmp_path, monkeypatch):
    """Simulate two concurrent jobs for the SAME video identity: job A has a
    pre-existing valid cache, job B fails mid-download. Job B's cleanup must
    NOT delete job A's valid cache."""
    save_dir = str(tmp_path)
    video_url = "https://www.youtube.com/watch?v=SAMEVID1000"
    vid_hash = _canonical_vid_hash(video_url)
    video_path = tmp_path / f"{vid_hash}.mp4"

    # Job A: pre-existing valid cache
    video_path.write_bytes(b"valid cached video for concurrent job A")

    mock_ydl = _make_mock_ydl_download_error(
        create_partial=True, save_dir=save_dir, video_url=video_url
    )

    # Note: save_video_youtube checks for existing file at line 1365-1367 and
    # returns early, so the download won't actually be attempted. This test
    # documents that the early-return path preserves the cache.
    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        result = save_video_youtube(video_url, save_dir=save_dir)

    assert result == str(video_path)
    assert video_path.exists(), "Concurrent job A's valid cache must survive"
    assert os.path.getsize(video_path) > 0


# ---------------------------------------------------------------------------
# TEST 11: cache filename pattern compatibility
# ---------------------------------------------------------------------------

def test_defect2_filename_pattern_matches_sweeper(tmp_path, monkeypatch):
    """The cache filename used by save_video_youtube must match the pattern
    recognized by cleanup_orphan_cache_videos, so any leftovers are still
    caught by the sweeper."""
    video_url = "https://www.youtube.com/watch?v=PATTN000001"
    vid_hash = _canonical_vid_hash(video_url)
    filename = f"{vid_hash}.mp4"
    assert CACHE_FILE_RE.match(filename), f"Filename {filename} does not match sweeper pattern"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
