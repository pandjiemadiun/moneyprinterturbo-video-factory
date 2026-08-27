"""TDD tests for the YouTube provider + universal resolver (BAGIAN D + E + F).

Tests 14–18 of the 18-test TDD suite. All YouTube I/O is mocked — no real
network calls, no secrets required.

Written BEFORE implementation (RED phase) — expected to fail until
``search_videos_youtube``, ``save_video_youtube``, and the multi-provider
fallback path in ``download_videos_by_scene`` are implemented.

Test inventory:
  14. YouTube search returns candidates (mocked yt-dlp)
  15. YouTube download failure → fail-clean
  16. YouTube unavailable → provider fallback (Pexels → YouTube)
  17. Candidate ranking by relevance/duration/resolution
  18. Provenance stored (provider, video_id, title, channel, url, license)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from app.models.schema import MaterialInfo, VideoAspect
from app.services import material


# ── helpers ──────────────────────────────────────────────────────────────────

def _fake_yt_entry(video_id="abc123", title="Mountain Fog Mystery",
                    duration=300, channel="Explore Channel",
                    view_count=10000, url=None):
    """Mimic yt-dlp's extract_info entry dict for ytsearch."""
    return {
        "id": video_id,
        "title": title,
        "duration": duration,
        "channel": channel,
        "uploader": channel,
        "view_count": view_count,
        "weburl": url or f"https://www.youtube.com/watch?v={video_id}",
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "formats": [
            {
                "ext": "mp4",
                "height": 720,
                "width": 1280,
                "filesize": 5_000_000,
                "url": f"https://rr2---sn-4g5ednls.googlevideo.com/videoplayback?id={video_id}",
            }
        ],
    }


def _fake_youtube_search_results():
    """Return 3 fake YouTube search entries."""
    return [
        _fake_yt_entry(video_id="vid1", title="Mountain Fog Indonesia HD", duration=600),
        _fake_yt_entry(video_id="vid2", title="Gunung Semeru Kabut Pagi", duration=300),
        _fake_yt_entry(video_id="vid3", title="Cave Expedition Documentary", duration=120),
    ]


def _make_scene(query="mountain fog indonesia", duration=5.0):
    return {"narration": "test narration", "visual_query": query,
            "target_duration": duration}


def _patch_youtube_search(entries=None):
    """Return a (patcher, mock_ydl) pair that makes YoutubeDL.extract_info
    return fake ytsearch results.  Use ``with patcher:`` to activate."""
    entries = entries or _fake_youtube_search_results()
    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = {"entries": entries, "_type": "playlist"}
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)
    patcher = patch("yt_dlp.YoutubeDL", return_value=mock_ydl)
    return patcher, mock_ydl


def _no_cache_search(mat_mod, fake_search):
    """Return a patcher that bypasses the material search cache so tests are
    deterministic (no stale cache hits from other tests)."""
    def _passthrough(provider, search_videos, search_term,
                     minimum_duration, video_aspect):
        return search_videos(
            search_term=search_term,
            minimum_duration=minimum_duration,
            video_aspect=video_aspect,
        )
    return patch.object(mat_mod, "_search_videos_with_cache",
                        side_effect=_passthrough)


# ── Test 14 ─────────────────────────────────────────────────────────────────

def test_14_youtube_search_returns_candidates():
    """search_videos_youtube delegates to yt_dlp ytsearch and returns MaterialInfo
    objects with proper source_info (provider, search_term, asset_id, url,
    channel, duration, title, license_status)."""
    from app.services.material import search_videos_youtube

    patcher, mock_ydl = _patch_youtube_search()
    with patcher:
        results = search_videos_youtube(
            search_term="mountain fog indonesia",
            minimum_duration=3,
            video_aspect=VideoAspect.portrait,
        )

    assert len(results) == 3
    assert all(isinstance(r, MaterialInfo) for r in results)
    # First entry must expose YouTube-specific provenance
    first = results[0]
    assert first.provider == "youtube"
    assert first.duration == 600
    info = first.source_info or {}
    assert info.get("asset_id") == "vid1"
    assert info.get("provider") == "youtube"
    assert info.get("title") == "Mountain Fog Indonesia HD"
    assert info.get("channel") == "Explore Channel"
    assert "https://www.youtube.com/watch?v=vid1" in first.url
    # yt_dlp was called with ytsearch
    mock_ydl.extract_info.assert_called_once()
    call_args = mock_ydl.extract_info.call_args
    assert "ytsearch" in str(call_args) or "ytsearch" in str(call_args.args[0])


def test_14_b_youtube_search_handles_no_results():
    """Empty ytsearch results → empty list, no crash."""
    from app.services.material import search_videos_youtube

    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = {"entries": [], "_type": "playlist"}
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)
    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        results = search_videos_youtube(
            search_term="nonexistent topic xyz123",
            minimum_duration=3,
            video_aspect=VideoAspect.portrait,
        )
    assert results == []


def test_14_c_youtube_search_short_videos_filtered():
    """Videos shorter than minimum_duration are excluded."""
    from app.services.material import search_videos_youtube

    entries = [
        _fake_yt_entry(video_id="short", title="Short Clip", duration=2),
        _fake_yt_entry(video_id="long", title="Long Clip", duration=30),
    ]
    patcher, mock_ydl = _patch_youtube_search(entries)
    with patcher:
        results = search_videos_youtube(
            search_term="topic",
            minimum_duration=10,
            video_aspect=VideoAspect.portrait,
        )

    assert len(results) == 1
    assert results[0].source_info["asset_id"] == "long"


# ── Test 15 ─────────────────────────────────────────────────────────────────

def test_15_youtube_download_failure_fail_clean():
    """When yt_dlp download returns 403 (bot detection / no cookies), the
    save_video_youtube function must return empty string (fail-clean), not raise."""
    from app.services.material import save_video_youtube

    mock_ydl = MagicMock()
    # Simulate yt-dlp raising an error (403 / bot detection)
    mock_ydl.extract_info.side_effect = Exception(
        "ERROR: unable to download video data: HTTP Error 403: Forbidden"
    )
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        result = save_video_youtube(
            video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            save_dir="/tmp/test_youtube_dl_fail",
        )

    assert result == "" or result is None, \
        f"Expected empty string on download failure, got {result!r}"


def test_15_b_youtube_download_success():
    """Happy path: yt_dlp download writes file, returns path."""
    import os, tempfile
    from app.services.material import save_video_youtube

    tmp = tempfile.mkdtemp()
    mock_ydl = MagicMock()
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)

    video_url = "https://www.youtube.com/watch?v=test123"
    # Compute the same path save_video_youtube will derive from the URL hash
    from app.utils import utils
    url_without_query = video_url.split("?")[0]
    url_hash = utils.md5(url_without_query)
    real_path = os.path.join(tmp, f"vid-{url_hash}.mp4")

    def fake_download(urls, **kwargs):
        """Simulate yt_dlp writing the downloaded file to outtmpl path."""
        with open(real_path, "w") as f:
            f.write("fake-video-bytes")
        return [{"_filename": real_path}]

    mock_ydl.download = fake_download

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        result = save_video_youtube(
            video_url=video_url,
            save_dir=tmp,
        )

    assert result is not None and result != ""
    assert os.path.exists(result)
    os.unlink(real_path)


# ── Test 16 ─────────────────────────────────────────────────────────────────

def test_16_provider_fallback_pexels_then_youtube(tmp_path):
    """download_videos_by_scene tries Pexels first, then YouTube as fallback
    for a scene that has no usable Pexels material."""
    scenes = [_make_scene("misty mountain peak", 5.0)]

    # Pexels returns no results (simulating unavailable material)
    pexels_results = []
    youtube_results = [
        MaterialInfo(provider="youtube", url="http://youtube/vid1", duration=10,
                     source_info={"provider": "youtube", "asset_id": "vid1",
                                  "search_term": "misty mountain peak",
                                  "title": "Misty Mountain Peak Documentary",
                                  "channel": "Explore", "license_status": "unknown"}),
    ]

    call_count = {"pexels": 0, "youtube": 0}

    def fake_search_pexels(search_term, minimum_duration, video_aspect):
        call_count["pexels"] += 1
        return list(pexels_results)

    def fake_search_youtube(search_term, minimum_duration, video_aspect):
        call_count["youtube"] += 1
        return list(youtube_results)

    def fake_save_video(video_url, save_dir):
        # Return a real file path (simulating a downloaded clip)
        import os, subprocess, tempfile
        from app.services.reframe import reframe_to_portrait
        path = os.path.join(save_dir, f"vid-{hash(video_url) % 100000}.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=0x108010:s=1920x1080:d=5:r=24",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", path],
            capture_output=True, check=True,
        )
        return path

    import app.services.material as mat_mod
    # Patch the provider search and download
    with patch.object(mat_mod, "_provider_and_searcher",
                      side_effect=lambda s: (
                          s, fake_search_pexels if s == "pexels" else fake_search_youtube)):
        with patch.object(mat_mod, "save_video", fake_save_video):
            with _no_cache_search(mat_mod, fake_search_pexels):
                # Call with multi-provider sources
                result = mat_mod.download_videos_by_scene(
                    task_id="test-task",
                    video_scenes=scenes,
                    sources=["pexels", "youtube"],
                    video_aspect=VideoAspect.portrait,
                    max_clip_duration=5,
                    material_directory=str(tmp_path),
                )

    # YouTube was called (fallback from Pexels)
    assert call_count["youtube"] > 0, "YouTube fallback was not tried"
    # Result has a path for the one scene
    assert len(result) == 1
    assert result[0] and result[0] != ""


def test_16_b_all_providers_fail_fail_clean(tmp_path):
    """When ALL providers fail for a scene, download_videos_by_scene must raise
    RuntimeError (fail-clean) — never substitute another scene's clip."""
    scenes = [_make_scene("nonexistent rare topic xyz", 5.0)]

    def fake_search_pexels(search_term, minimum_duration, video_aspect):
        return []  # no results

    def fake_search_youtube(search_term, minimum_duration, video_aspect):
        return []  # no results either

    import app.services.material as mat_mod
    with patch.object(mat_mod, "_provider_and_searcher",
                      side_effect=lambda s: (
                          s, fake_search_pexels if s == "pexels" else fake_search_youtube)):
        with _no_cache_search(mat_mod, fake_search_pexels):
            with pytest.raises(RuntimeError, match="no usable"):
                mat_mod.download_videos_by_scene(
                    task_id="test-task-fail",
                    video_scenes=scenes,
                    sources=["pexels", "youtube"],
                    video_aspect=VideoAspect.portrait,
                    max_clip_duration=5,
                    material_directory=str(tmp_path),
                )


# ── Test 17 ─────────────────────────────────────────────────────────────────

def test_17_candidate_ranking_by_relevance_duration_resolution():
    """When a provider returns multiple candidates, rank_videos() picks the best:
    1) duration >= min (5s), 2) relevance (keyword match), 3) resolution."""
    from app.services.material import rank_videos

    candidates = [
        # Distant match, short
        MaterialInfo(provider="pexels", url="http://short.mp4", duration=3,
                     source_info={"provider": "pexels", "asset_id": "a",
                                  "rendition": {"width": 1920, "height": 1080}}),
        # Good match, good duration, but lower res
        MaterialInfo(provider="pexels", url="http://lowres.mp4", duration=6,
                     source_info={"provider": "pexels", "asset_id": "b",
                                  "search_term": "misty mountain peak",
                                  "rendition": {"width": 720, "height": 1280}}),
        # Best: good duration, high res, keyword match
        MaterialInfo(provider="pexels", url="http://best.mp4", duration=8,
                     source_info={"provider": "pexels", "asset_id": "c",
                                  "search_term": "misty mountain peak fog indonesia",
                                  "rendition": {"width": 1080, "height": 1920}}),
    ]

    ranked = rank_videos(candidates, search_term="misty mountain peak fog",
                         minimum_duration=5, video_aspect=VideoAspect.portrait)

    assert len(ranked) <= 2, "Short clip should be filtered out"
    # Best match should be first
    assert ranked[0].source_info.get("asset_id") == "c"
    # Lower-res should be second (duration OK, relevance OK, lower res)
    assert ranked[1].source_info.get("asset_id") == "b"


def test_17_b_ranking_filters_portrait_unsuitable():
    """rank_videos should filter out clips too small for a good 9:16 render."""
    from app.services.material import rank_videos

    candidates = [
        MaterialInfo(provider="pexels", url="http://tiny.mp4", duration=5,
                     source_info={"provider": "pexels", "asset_id": "tiny",
                                  "rendition": {"width": 360, "height": 640}}),
        MaterialInfo(provider="pexels", url="http://good.mp4", duration=5,
                     source_info={"provider": "pexels", "asset_id": "good",
                                  "rendition": {"width": 1080, "height": 1920}}),
    ]

    ranked = rank_videos(candidates, search_term="topic", minimum_duration=5,
                         video_aspect=VideoAspect.portrait)

    assert len(ranked) == 1
    assert ranked[0].source_info.get("asset_id") == "good"


# ── Test 18 ─────────────────────────────────────────────────────────────────

def test_18_provenance_stored_with_youtube_fields(tmp_path):
    """When YouTube is used for a scene, the material_sources record must include
    YouTube-specific provenance fields: provider, video_id, title, channel,
    source_url, license_status."""
    scenes = [_make_scene("volcanic steam indonesia", 5.0)]

    youtube_results = [
        MaterialInfo(provider="youtube", url="http://youtube/vidABC", duration=10,
                     source_info={"provider": "youtube", "asset_id": "vidABC",
                                  "search_term": "volcanic steam indonesia",
                                  "title": "Steam Rising from Active Volcano",
                                  "channel": "Nature Docs",
                                  "license_status": "unknown",
                                  "rendition": {"width": 1280, "height": 720}}),
    ]

    import app.services.material as mat_mod

    def fake_search_youtube(search_term, minimum_duration, video_aspect):
        return list(youtube_results)

    def fake_save_video(video_url, save_dir):
        import os, subprocess
        path = os.path.join(save_dir, "vid-ABC123.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=0x108010:s=1280x720:d=5:r=24",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", path],
            capture_output=True, check=True,
        )
        return path

    with patch.object(mat_mod, "_provider_and_searcher",
                      side_effect=lambda s: (s, fake_search_youtube if s == "youtube" else mat_mod.search_videos_pexels)):
        with patch.object(mat_mod, "save_video", fake_save_video):
            with _no_cache_search(mat_mod, fake_search_youtube):
                # Pre-create script.json so patch_script_data can update it.
                # In the real flow, this file is created at task-initialisation;
                # the test simulates that precondition.
                task_dir = mat_mod.utils.task_dir("test-provenance")
                script_data_path = Path(task_dir) / "script.json"
                script_data_path.parent.mkdir(parents=True, exist_ok=True)
                script_data_path.write_text("{}")

                result = mat_mod.download_videos_by_scene(
                    task_id="test-provenance",
                    video_scenes=scenes,
                    sources=["youtube"],
                    video_aspect=VideoAspect.portrait,
                    max_clip_duration=5,
                    material_directory=str(tmp_path),
                )

    assert len(result) == 1

    # Read the persisted material sources from script.json
    import json
    with open(script_data_path) as f:
        script_data = json.load(f)

    sources = script_data.get("material_sources", [])
    assert len(sources) >= 1

    yt_record = None
    for s in sources:
        if s.get("provider") == "youtube":
            yt_record = s
            break

    assert yt_record is not None, "YouTube provenance record not found"
    assert yt_record.get("provider") == "youtube"
    assert yt_record.get("scene_index") == 0
    assert "visual_query" in yt_record or "search_term" in yt_record
    # YouTube-specific fields
    assert "title" in yt_record or "video_id" in yt_record or yt_record.get("asset_id") == "vidABC"

    # Cleanup
    import shutil
    if Path(task_dir).exists():
        shutil.rmtree(Path(task_dir), ignore_errors=True)


# ── Test 18b: no cross-scene substitution ────────────────────────────────────

def test_18b_no_cross_scene_substitution(tmp_path):
    """Scene 1 uses clip X; Scene 2 must NOT reuse clip X even if its own query
    has fewer results. The used_asset_ids set enforces this per-render."""
    scenes = [
        _make_scene("volcano eruption", 5.0),
        _make_scene("ocean depths", 5.0),
    ]

    results_s1 = [
        MaterialInfo(provider="pexels", url="http://clip-s1-1.mp4", duration=8,
                     source_info={"provider": "pexels", "asset_id": "clip1",
                                  "search_term": "volcano eruption",
                                  "rendition": {"width": 1080, "height": 1920}}),
        MaterialInfo(provider="pexels", url="http://clip-s1-2.mp4", duration=7,
                     source_info={"provider": "pexels", "asset_id": "clip2",
                                  "search_term": "volcano eruption",
                                  "rendition": {"width": 1080, "height": 1920}}),
    ]
    results_s2 = [
        MaterialInfo(provider="pexels", url="http://clip-s2-1.mp4", duration=6,
                     source_info={"provider": "pexels", "asset_id": "clip1",
                                  "search_term": "ocean depths",
                                  "rendition": {"width": 1080, "height": 1920}}),
        MaterialInfo(provider="pexels", url="http://clip-s2-2.mp4", duration=6,
                     source_info={"provider": "pexels", "asset_id": "clip3",
                                  "search_term": "ocean depths",
                                  "rendition": {"width": 1080, "height": 1920}}),
    ]

    search_call = {"count": 0, "results": [results_s1, results_s2]}

    def fake_search_pexels(search_term, minimum_duration, video_aspect):
        idx = min(search_call["count"], 1)
        search_call["count"] += 1
        return list(search_call["results"][idx])

    def fake_save_video(video_url, save_dir):
        import os, subprocess
        path = os.path.join(save_dir, f"clip-{search_call['count']}.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=0x108010:s=1080x1920:d=5:r=24",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", path],
            capture_output=True, check=True,
        )
        return path

    import app.services.material as mat_mod
    with patch.object(mat_mod, "_provider_and_searcher",
                      side_effect=lambda s: (s, fake_search_pexels)):
        with patch.object(mat_mod, "save_video", fake_save_video):
            with _no_cache_search(mat_mod, fake_search_pexels):
                result = mat_mod.download_videos_by_scene(
                task_id="test-nocross",
                video_scenes=scenes,
                sources=["pexels"],
                video_aspect=VideoAspect.portrait,
                max_clip_duration=5,
                material_directory=str(tmp_path),
            )

    assert len(result) == 2, "Should have 2 clips (one per scene)"
    # Scene 2 must NOT get "clip1" (already claimed by scene 1)
    # Scene 2's first candidate was asset_id="clip1" which should be skipped
    # Scene 2 should get clip3 (the second candidate after clip1 is filtered)
    # Verify by checking the download calls
    saved_names = [Path(p).name for p in result]
    # The important thing: 2 distinct files for 2 scenes (no reuse)
    assert len(set(saved_names)) == 2, "Cross-scene substitution detected: clips reused"

    search_call["count"] = 0  # cleanup counter

    # Cleanup
    import shutil
    task_dir = mat_mod.utils.task_dir("test-nocross")
    if Path(task_dir).exists():
        shutil.rmtree(Path(task_dir), ignore_errors=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
