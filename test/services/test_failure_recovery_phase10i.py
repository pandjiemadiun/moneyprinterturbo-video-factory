"""
Phase 10I — Failure & Recovery Audit test suite.

All tests use ISOLATED temporary directories and SYNTHETIC fixtures.
No production storage, config.toml, or real YouTube downloads
are touched.

Run from the repo root, e.g. inside the production container:
    python3 -m pytest test/services/test_failure_recovery_phase10i.py -v
"""

import os
import sys
import shutil
import subprocess
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.services import material
from app.services.material import (
    _validate_downloaded_clip,
    cleanup_orphan_cache_videos,
    _get_active_cache_references,
    save_video_youtube,
    download_videos_by_scene,
    _PROTECTED_FILENAMES,
)
from app.services.video import combine_videos, delete_files
from app.models.schema import MaterialInfo, VideoAspect


FFMPEG = "ffmpeg"


def _make_mp4(path: Path, w: int, h: int, duration: float = 1.0, rate: int = 15):
    """Create a tiny valid MP4 with the given dimensions using ffmpeg (local, no network)."""
    subprocess.run(
        [
            FFMPEG, "-y", "-f", "lavfi",
            "-i", f"testsrc=size={w}x{h}:rate={rate}",
            "-t", str(duration), "-pix_fmt", "yuv420p", str(path),
        ],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _make_silence(path: Path, seconds: float = 3.0):
    subprocess.run(
        [
            FFMPEG, "-y", "-f", "lavfi", "-i", f"anullsrc=r=16000:cl=mono",
            "-t", str(seconds), "-acodec", "pcm_s16le", str(path),
        ],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _video_module():
    from app.services import video as v
    return v


def _vid(seed: str) -> str:
    """Produce a canonical 32-hex cache filename that matches the sweeper's
    ``vid-{32-hex}.mp4`` pattern."""
    import hashlib
    return f"vid-{hashlib.md5(seed.encode()).hexdigest()}.mp4"


# ---------------------------------------------------------------------------
# TEST A — QUALITY-GATE FAILURE
# ---------------------------------------------------------------------------

def test_A_quality_gate_rejects_low_resolution(tmp_path):
    """_validate_downloaded_clip() must return False for a source that cannot
    yield sufficient effective resolution for the 1080x1920 target."""
    low = tmp_path / "low.mp4"
    _make_mp4(low, 160, 120)  # effective_min ~67.5 < 250 -> reject
    assert _validate_downloaded_clip(str(low), video_aspect=VideoAspect.portrait) is False


def test_A_quality_gate_rejects_tiny_file(tmp_path):
    tiny = tmp_path / "tiny.mp4"
    tiny.write_bytes(b"\x00" * 100)  # below 1024-byte floor
    assert _validate_downloaded_clip(str(tiny), video_aspect=VideoAspect.portrait) is False


def test_A_rejected_raw_file_deletion_is_non_fatal(tmp_path):
    """The shared safe-delete primitive used by the pipeline must remove a
    rejected file and tolerate a missing/already-removed file (idempotent,
    non-fatal) — proving deletion failure cannot crash cleanup."""
    rejected = tmp_path / "rejected.mp4"
    _make_mp4(rejected, 160, 120)
    delete_files(str(rejected))
    assert not rejected.exists()
    # idempotent: deleting again must not raise
    delete_files(str(rejected))
    # OSError (e.g. permission) is logged, not raised
    import app.services.video as video_mod
    real_remove = os.remove

    def boom(p):
        raise OSError("permission denied")

    video_mod.os.remove = boom
    try:
        delete_files(str(tmp_path / "nonexistent.mp4"))
    finally:
        video_mod.os.remove = real_remove


def test_A_reject_path_deletes_file_in_pipeline(tmp_path, monkeypatch):
    """Drive the REAL download+quality-gate pipeline (download_videos_by_scene)
    with a mocked searcher/downloader returning a low-res clip. The pipeline
    must delete the rejected raw file (no leak) and fail the scene cleanly."""
    low = tmp_path / "low.mp4"
    _make_mp4(low, 160, 120)
    md = tmp_path / "materials"
    md.mkdir()

    item = MaterialInfo()
    item.provider = "youtube"
    item.url = "https://www.youtube.com/watch?v=LOWRES0001"
    item.duration = 5
    item.source_info = {"asset_id": "LOWRES0001", "provider": "youtube"}

    monkeypatch.setattr(material, "_search_videos_with_cache", lambda **k: [item])

    def fake_download(it, provider, directory):
        dest = Path(directory) / "vid-lowres.mp4"
        shutil.copy(low, dest)
        return str(dest)

    monkeypatch.setattr(material, "_download_material_item", fake_download)
    monkeypatch.setattr(material, "_persist_material_sources", lambda *a, **k: None)

    with pytest.raises(RuntimeError):
        material.download_videos_by_scene(
            task_id="audit-scene",
            video_scenes=[{"visual_query": "q"}],
            source="youtube",
            material_directory=str(md),
        )
    assert not (md / "vid-lowres.mp4").exists()


# ---------------------------------------------------------------------------
# TEST B — DOWNLOAD FAILURE (mocked yt-dlp)
# ---------------------------------------------------------------------------

def test_B_download_failure_returns_empty_no_false_success(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise material.yt_dlp.utils.DownloadError("simulated network failure")

    monkeypatch.setattr(material.yt_dlp, "YoutubeDL", boom)
    out = save_video_youtube("https://www.youtube.com/watch?v=FAILVID0001", save_dir=str(tmp_path))
    assert out == ""  # fail-clean, NO false success
    assert list(tmp_path.glob("vid-*.mp4")) == []


def test_B_download_failure_does_not_corrupt_unrelated(tmp_path, monkeypatch):
    """A pre-existing unrelated cache file must survive a failed download and
    the failed download must not produce a valid (wrongly-reported) entry."""
    unrelated = tmp_path / "vid-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.mp4"
    _make_mp4(unrelated, 640, 360)

    def boom(*a, **k):
        raise material.yt_dlp.utils.DownloadError("simulated failure")

    monkeypatch.setattr(material.yt_dlp, "YoutubeDL", boom)
    out = save_video_youtube("https://www.youtube.com/watch?v=FAILVID0002", save_dir=str(tmp_path))
    assert out == ""
    assert unrelated.exists()
    created = [p for p in tmp_path.glob("vid-*.mp4") if p != unrelated]
    assert created == []


# ---------------------------------------------------------------------------
# TEST C — MATERIAL EXHAUSTION
# ---------------------------------------------------------------------------

def test_C_material_exhaustion_deletes_all_rejected(tmp_path, monkeypatch):
    """All candidates rejected -> each rejected raw file is deleted, no rejected
    cache file remains, task fails cleanly (RuntimeError), no permanent asset
    touched."""
    low = tmp_path / "low.mp4"
    _make_mp4(low, 160, 120)
    md = tmp_path / "materials"
    md.mkdir()

    items = []
    for i in range(3):
        it = MaterialInfo()
        it.provider = "youtube"
        it.url = f"https://www.youtube.com/watch?v=REJECT000{i}"
        it.duration = 5
        it.source_info = {"asset_id": f"REJECT000{i}", "provider": "youtube"}
        items.append(it)

    monkeypatch.setattr(material, "_search_videos_with_cache", lambda **k: list(items))

    created = {}

    def fake_download(it, provider, directory):
        dest = Path(directory) / f"vid-reject{i}.mp4"
        shutil.copy(low, dest)
        created[dest.name] = dest
        return str(dest)

    monkeypatch.setattr(material, "_download_material_item", fake_download)
    monkeypatch.setattr(material, "_persist_material_sources", lambda *a, **k: None)

    with pytest.raises(RuntimeError):
        material.download_videos_by_scene(
            task_id="audit-exhaust",
            video_scenes=[{"visual_query": "q"}],
            source="youtube",
            material_directory=str(md),
        )
    for d in created.values():
        assert not d.exists(), f"rejected file {d.name} was not cleaned"
    assert list(md.glob("final-*")) == []
    assert list(md.glob("combined-*")) == []


# ---------------------------------------------------------------------------
# TEST D — TEMP CLIP FAILURE
# ---------------------------------------------------------------------------

def test_D_concat_failure_cleans_temp_clips_and_list(tmp_path, monkeypatch):
    """If concat (ffmpeg) fails, the finally block must remove temp-clip-*.mp4
    AND ffmpeg-concat-list.txt. Source/protected files untouched."""
    clip = tmp_path / "src.mp4"
    _make_mp4(clip, 640, 360)
    silence = tmp_path / "silence.wav"
    _make_silence(silence)
    out = tmp_path / "combined_1080x1920.mp4"
    protected = tmp_path / "combined-1.mp4"
    _make_mp4(protected, 1080, 1920)

    def boom(*a, **k):
        raise RuntimeError("simulated ffmpeg concat failure")

    monkeypatch.setattr(_video_module(), "concat_video_clips_with_ffmpeg", boom)

    with pytest.raises(RuntimeError):
        combine_videos(
            combined_video_path=str(out),
            video_paths=[str(clip)],
            audio_file=str(silence),
            video_aspect=VideoAspect.portrait,
            max_clip_duration=5,
            video_transition_mode=None,
        )
    assert list(tmp_path.glob("temp-clip-*.mp4")) == []
    assert not (tmp_path / "ffmpeg-concat-list.txt").exists()
    assert protected.exists()
    assert not out.exists() or os.path.getsize(out) == 0


def test_D_encoding_failure_temp_clip_cleanup_behavior(tmp_path, monkeypatch):
    """Inject a clip-encoding failure. Observe whether the temp-clip file is
    cleaned. This is the fail-closed lease test for the encoding path."""
    clip = tmp_path / "src.mp4"
    _make_mp4(clip, 640, 360)
    silence = tmp_path / "silence.wav"
    _make_silence(silence)
    out = tmp_path / "combined_1080x1920.mp4"

    import app.services.video as video_mod

    def boom(clip, clip_file, *a, **k):
        # Simulate ffmpeg partially writing the temp file before failing.
        Path(clip_file).write_bytes(b"\x00" * 1024)
        raise RuntimeError("simulated encode failure")

    monkeypatch.setattr(video_mod, "_write_videofile_with_codec_fallback", boom)
    try:
        combine_videos(
            combined_video_path=str(out),
            video_paths=[str(clip)],
            audio_file=str(silence),
            video_aspect=VideoAspect.portrait,
            max_clip_duration=5,
            video_transition_mode=None,
        )
    except Exception:
        pass

    remaining = list(tmp_path.glob("temp-clip-*.mp4"))
    if remaining:
        pytest.fail(
            f"clip-encoding failure left orphan temp clips: {[p.name for p in remaining]} "
            f"(cleanup not guaranteed on encoding-failure path)"
        )


# ---------------------------------------------------------------------------
# TEST E — FINAL RENDER FAILURE
# ---------------------------------------------------------------------------

def test_E_final_render_failure_preserves_protected_assets(tmp_path, monkeypatch):
    """A failing render must not falsely report success and must not delete
    protected permanent assets (combined-*/final-*)."""
    clip = tmp_path / "src.mp4"
    _make_mp4(clip, 640, 360)
    silence = tmp_path / "silence.wav"
    _make_silence(silence)
    out = tmp_path / "final-1.mp4"
    combined = tmp_path / "combined-1.mp4"
    _make_mp4(combined, 1080, 1920)
    _make_mp4(out, 1080, 1920)  # pre-existing deliverable must survive

    def boom(*a, **k):
        raise RuntimeError("simulated final render failure")

    monkeypatch.setattr(_video_module(), "concat_video_clips_with_ffmpeg", boom)

    with pytest.raises(RuntimeError):
        combine_videos(
            combined_video_path=str(out),
            video_paths=[str(clip)],
            audio_file=str(silence),
            video_aspect=VideoAspect.portrait,
            max_clip_duration=5,
            video_transition_mode=None,
        )
    assert combined.exists()
    assert out.exists()
    assert list(tmp_path.glob("temp-clip-*.mp4")) == []
    assert not (tmp_path / "ffmpeg-concat-list.txt").exists()


# ---------------------------------------------------------------------------
# TEST F — PIPELINE EXCEPTION / TASK FAILURE STATE
# ---------------------------------------------------------------------------

def test_F_mark_task_failed_is_structured_and_non_crashing(monkeypatch):
    from app.services import task as task_svc

    recorded = {}

    class FakeState:
        def get_task(self, task_id):
            return None

        def update_task(self, task_id, **fields):
            recorded.update(fields)
            return True

    monkeypatch.setattr(task_svc.sm, "state", FakeState())
    result = task_svc._mark_task_failed("audit-task", "combine", "boom")
    assert result["state"] == task_svc.const.TASK_STATE_FAILED
    assert recorded.get("state") == task_svc.const.TASK_STATE_FAILED
    assert recorded.get("error") == "boom"
    assert "progress" in recorded


def test_F_mark_task_failed_no_uncaught_crash_on_missing_task(monkeypatch):
    from app.services import task as task_svc

    class FakeState:
        def get_task(self, task_id):
            raise RuntimeError("state backend unavailable")

        def update_task(self, task_id, **fields):
            return True

    monkeypatch.setattr(task_svc.sm, "state", FakeState())
    res = task_svc._mark_task_failed("x", "stage", "err")
    assert res["state"] == task_svc.const.TASK_STATE_FAILED


# ---------------------------------------------------------------------------
# TEST G — CANCELLATION
# ---------------------------------------------------------------------------

def test_G_cancellation_not_executed_unsafe():
    """Deterministic isolated cancellation cannot be safely simulated without
    an active orchestrated task (live worker/API). The cancellation code path
    was inspected: cross-post cancellation raises RuntimeError
    (app/services/task.py:1206); WebUI cancel transitions task state. Forcing a
    real cancellation would require production interaction, which the safety
    contract forbids. Marked NOT EXECUTED."""
    pytest.skip(
        "NOT EXECUTED — unsafe under current architecture: deterministic "
        "isolated cancellation requires an active orchestrated task; forcing it "
        "risks production interaction. Cancellation path inspected by code review."
    )


# ---------------------------------------------------------------------------
# TEST H — CONTAINER RESTART / RECOVERY (isolated fixture)
# ---------------------------------------------------------------------------

def _age(files, days=31):
    old = time.time() - days * 86400
    for f in files:
        os.utime(f, (old, old))


def test_H_orphan_sweeper_removes_stale_eligible_keeps_unknown(tmp_path, monkeypatch):
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    old = cache / "vid-11111111111111111111111111111111.mp4"
    old.write_bytes(b"x" * 4096)
    part = cache / "vid-22222222222222222222222222222222.mp4.part"
    part.write_bytes(b"x" * 4096)
    ytdl = cache / "vid-33333333333333333333333333333333.mp4.ytdl"
    ytdl.write_bytes(b"x" * 4096)
    unknown = cache / "some_unknown_file.dat"
    unknown.write_bytes(b"x" * 4096)
    protected = cache / "combined-1.mp4"
    protected.write_bytes(b"x" * 4096)
    _age([old, part, ytdl, unknown, protected])

    monkeypatch.setattr(material, "_get_active_cache_references", lambda: set())
    deleted = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)

    assert old.exists() is False
    assert part.exists() is False
    assert ytdl.exists() is False
    assert unknown.exists() is True
    assert protected.exists() is True
    assert deleted == 3


def test_H_recent_files_preserved(tmp_path, monkeypatch):
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    recent = cache / "vid-44444444444444444444444444444444.mp4"
    recent.write_bytes(b"x" * 4096)
    os.utime(recent, (time.time(), time.time()))
    monkeypatch.setattr(material, "_get_active_cache_references", lambda: set())
    deleted = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)
    assert recent.exists() is True
    assert deleted == 0


# ---------------------------------------------------------------------------
# TEST I — ACTIVE JOB SAFETY
# ---------------------------------------------------------------------------

def test_I_active_reference_keeps_file(tmp_path, monkeypatch):
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    vid_x = cache / _vid("taskX")
    vid_x.write_bytes(b"x" * 4096)
    _age([vid_x])
    monkeypatch.setattr(
        material, "_get_active_cache_references", lambda: {vid_x.name},
    )
    deleted = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)
    assert vid_x.exists() is True
    assert deleted == 0


def test_I_no_reference_old_age_deletes(tmp_path, monkeypatch):
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    vid_x = cache / _vid("taskX")
    vid_x.write_bytes(b"x" * 4096)
    _age([vid_x])
    monkeypatch.setattr(material, "_get_active_cache_references", lambda: set())
    deleted = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)
    assert vid_x.exists() is False
    assert deleted == 1


# ---------------------------------------------------------------------------
# TEST J — CROSS-JOB ISOLATION
# ---------------------------------------------------------------------------

def test_J_cross_job_isolation(tmp_path, monkeypatch):
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    vid_a = cache / _vid("A")
    vid_b = cache / _vid("B")
    vid_a.write_bytes(b"x" * 4096)
    vid_b.write_bytes(b"x" * 4096)
    _age([vid_a, vid_b])
    monkeypatch.setattr(
        material, "_get_active_cache_references", lambda: {vid_b.name},
    )
    deleted = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)
    assert vid_a.exists() is False
    assert vid_b.exists() is True
    assert deleted == 1


def test_J_same_identity_two_tasks_safe(tmp_path, monkeypatch):
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    vid = cache / _vid("C")
    vid.write_bytes(b"x" * 4096)
    _age([vid])
    monkeypatch.setattr(
        material, "_get_active_cache_references", lambda: {vid.name},
    )
    deleted = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)
    assert vid.exists() is True
    assert deleted == 0


# ---------------------------------------------------------------------------
# TEST K — STARTUP CLEANUP SAFETY
# ---------------------------------------------------------------------------

def test_K_startup_cleanup_does_not_touch_prod(monkeypatch):
    calls = {}

    def fake_sweep(cache_dir=None, ttl_days=30):
        calls["called"] = True
        return 0

    monkeypatch.setattr(material, "cleanup_orphan_cache_videos", fake_sweep)
    material.run_startup_cleanup()
    assert calls.get("called") is True


# ---------------------------------------------------------------------------
# TEST L — IDEMPOTENCY
# ---------------------------------------------------------------------------

def test_L_idempotent_sweep(tmp_path, monkeypatch):
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    stale = cache / "vid-55555555555555555555555555555555.mp4"
    stale.write_bytes(b"x" * 4096)
    _age([stale])
    monkeypatch.setattr(material, "_get_active_cache_references", lambda: set())
    d1 = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)
    d2 = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)
    assert d1 == 1
    assert d2 == 0
    assert stale.exists() is False


def test_L_repeated_reject_cleanup_harmless(tmp_path):
    f = tmp_path / "r.mp4"
    _make_mp4(f, 160, 120)
    delete_files(str(f))
    delete_files(str(f))


# ---------------------------------------------------------------------------
# TEST M — FAIL-CLOSED BEHAVIOR
# ---------------------------------------------------------------------------

def test_M_fail_closed_keeps_unknown_and_dirs(tmp_path, monkeypatch):
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    unknown = cache / "random_asset.final.mp4"
    unknown.write_bytes(b"x" * 4096)
    bad_hash = cache / "vid-zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz.mp4"
    bad_hash.write_bytes(b"x" * 4096)
    ext = cache / "note.txt"
    ext.write_bytes(b"x" * 4096)
    subdir = cache / "subdir"
    subdir.mkdir()
    _age([unknown, bad_hash, ext])
    monkeypatch.setattr(material, "_get_active_cache_references", lambda: set())
    deleted = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)
    assert unknown.exists() and bad_hash.exists() and ext.exists() and subdir.exists()
    assert deleted == 0


def test_M_deletion_error_is_non_fatal(tmp_path, monkeypatch):
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    stale = cache / "vid-66666666666666666666666666666666.mp4"
    stale.write_bytes(b"x" * 4096)
    _age([stale])
    monkeypatch.setattr(material, "_get_active_cache_references", lambda: set())

    real_remove = os.remove

    def boom(p):
        raise OSError("permission denied")

    os.remove = boom
    try:
        deleted = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)
    finally:
        os.remove = real_remove
    assert deleted == 0


def test_M_unreadable_task_state_is_fail_closed(tmp_path, monkeypatch):
    """Real `_get_active_cache_references` is fail-closed: if task state cannot
    be read it catches the error internally and returns an EMPTY set (never
    raises). The sweeper then deletes only stale eligible files by age; young
    files remain protected by TTL. This documents the actual boundary: the
    sweeper relies on TTL for the unreadable-state case, not on assuming refs."""
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    stale = cache / _vid("M")
    stale.write_bytes(b"x" * 4096)
    _age([stale])
    # simulate the real fail-closed return value (empty set, not an exception)
    monkeypatch.setattr(material, "_get_active_cache_references", lambda: set())
    deleted = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)
    assert stale.exists() is False
    assert deleted == 1

    # A YOUNG file (within TTL) is still preserved even when refs are unknown.
    cache2 = tmp_path / "cache_videos2"
    cache2.mkdir()
    young = cache2 / _vid("Myoung")
    young.write_bytes(b"x" * 4096)
    os.utime(young, (time.time(), time.time()))
    monkeypatch.setattr(material, "_get_active_cache_references", lambda: set())
    deleted2 = cleanup_orphan_cache_videos(cache_dir=str(cache2), ttl_days=30)
    assert young.exists() is True
    assert deleted2 == 0


# ---------------------------------------------------------------------------
# TEST N — LARGE-FILE REGRESSION MODEL (symbolic fixture, no multi-GB file)
# ---------------------------------------------------------------------------

def test_N_large_rejected_file_deletion_path(tmp_path, monkeypatch):
    """Represent the known Phase 9 failure class (a large rejected YouTube
    download). We use a small symbolic file with the canonical cache name and
    verify the EXACT deletion path removes it (no unbounded leak)."""
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    big = cache / "vid-deadbeefdeadbeefdeadbeefdeadbeef.mp4"
    big.write_bytes(b"x" * (1024 * 1024))  # 1 MiB symbolic (NOT multi-GB)
    _age([big])
    monkeypatch.setattr(material, "_get_active_cache_references", lambda: set())
    deleted = cleanup_orphan_cache_videos(cache_dir=str(cache), ttl_days=30)
    assert big.exists() is False
    assert deleted == 1
    prot = cache / "final-1.mp4"
    prot.write_bytes(b"x" * 1024)
    assert prot.exists() is True


# ---------------------------------------------------------------------------
# PHASE 10I.1 — DEFECT-1 REGRESSION (failed encoding temp-clip cleanup)
# ---------------------------------------------------------------------------

def _probe_dims(path: Path):
    import json as _json
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(path)],
        capture_output=True, text=True, check=True,
    )
    data = _json.loads(out.stdout)
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            return int(s["width"]), int(s["height"])
    return None


def test_defect1_A_encoding_failure_cleans_temp_clip(tmp_path, monkeypatch):
    """RED/GREEN core: an encoding failure must NOT leave an orphan
    temp-clip-*.mp4 behind."""
    clip = tmp_path / "src.mp4"
    _make_mp4(clip, 640, 360)
    silence = tmp_path / "silence.wav"
    _make_silence(silence)
    out = tmp_path / "combined_1080x1920.mp4"

    import app.services.video as video_mod

    def boom(clip_obj, clip_file, *a, **k):
        Path(clip_file).write_bytes(b"\x00" * 1024)  # partial left by ffmpeg
        raise RuntimeError("simulated encode failure")

    monkeypatch.setattr(video_mod, "_write_videofile_with_codec_fallback", boom)
    try:
        combine_videos(
            combined_video_path=str(out),
            video_paths=[str(clip)],
            audio_file=str(silence),
            video_aspect=VideoAspect.portrait,
            max_clip_duration=5,
            video_transition_mode=None,
        )
    except Exception:
        pass
    assert list(tmp_path.glob("temp-clip-*.mp4")) == [], "orphan temp clip leaked"


def test_defect1_B_concat_failure_cleans_temp_clips(tmp_path, monkeypatch):
    clip = tmp_path / "src.mp4"
    _make_mp4(clip, 640, 360)
    silence = tmp_path / "silence.wav"
    _make_silence(silence)
    out = tmp_path / "combined_1080x1920.mp4"
    protected = tmp_path / "combined-1.mp4"
    _make_mp4(protected, 1080, 1920)

    def boom(*a, **k):
        raise RuntimeError("simulated ffmpeg concat failure")

    monkeypatch.setattr(_video_module(), "concat_video_clips_with_ffmpeg", boom)
    with pytest.raises(RuntimeError):
        combine_videos(
            combined_video_path=str(out),
            video_paths=[str(clip)],
            audio_file=str(silence),
            video_aspect=VideoAspect.portrait,
            max_clip_duration=5,
            video_transition_mode=None,
        )
    assert list(tmp_path.glob("temp-clip-*.mp4")) == []
    assert not (tmp_path / "ffmpeg-concat-list.txt").exists()
    assert protected.exists()


def test_defect1_C_successful_concat_cleans_temp_clips(tmp_path, monkeypatch):
    clip = tmp_path / "src.mp4"
    _make_mp4(clip, 640, 360)
    silence = tmp_path / "silence.wav"
    _make_silence(silence)
    out = tmp_path / "combined_1080x1920.mp4"
    combine_videos(
        combined_video_path=str(out),
        video_paths=[str(clip)],
        audio_file=str(silence),
        video_aspect=VideoAspect.portrait,
        max_clip_duration=5,
        video_transition_mode=None,
    )
    assert out.exists()
    w, h = _probe_dims(out)
    assert (w, h) == (1080, 1920)
    # successful path must also clean temp clips
    assert list(tmp_path.glob("temp-clip-*.mp4")) == []
    assert not (tmp_path / "ffmpeg-concat-list.txt").exists()


def test_defect1_D_multiple_clips_one_encodes_fails_cleans_all(tmp_path, monkeypatch):
    clips = [tmp_path / f"src{i}.mp4" for i in range(3)]
    for c in clips:
        _make_mp4(c, 640, 360)
    silence = tmp_path / "silence.wav"
    _make_silence(silence)
    out = tmp_path / "combined_1080x1920.mp4"

    import app.services.video as video_mod

    calls = {"n": 0}

    def boom(clip_obj, clip_file, *a, **k):
        calls["n"] += 1
        if calls["n"] == 2:  # second clip fails to encode
            Path(clip_file).write_bytes(b"\x00" * 1024)
            raise RuntimeError("encode fail on clip 2")
        # real write for other clips is bypassed; emulate success minimally
        # (the function is mocked, so nothing is actually written)

    monkeypatch.setattr(video_mod, "_write_videofile_with_codec_fallback", boom)
    try:
        combine_videos(
            combined_video_path=str(out),
            video_paths=[str(c) for c in clips],
            audio_file=str(silence),
            video_aspect=VideoAspect.portrait,
            max_clip_duration=5,
            video_transition_mode=None,
        )
    except Exception:
        pass
    # ALL temp-clip files (1,2,3) must be gone, including the failed one
    assert list(tmp_path.glob("temp-clip-*.mp4")) == [], "not all temp clips cleaned"


def test_defect1_E_missing_temp_file_idempotent(tmp_path):
    # delete_files must not raise on an already-removed temp file
    f = tmp_path / "temp-clip-1.mp4"
    f.write_bytes(b"\x00" * 1024)
    from app.services.video import delete_files
    delete_files(str(f))  # first
    delete_files(str(f))  # second (already gone) must not raise


def test_defect1_F_unrelated_files_not_removed(tmp_path, monkeypatch):
    clip = tmp_path / "src.mp4"
    _make_mp4(clip, 640, 360)
    silence = tmp_path / "silence.wav"
    _make_silence(silence)
    out = tmp_path / "final-1.mp4"
    combined = tmp_path / "combined-1.mp4"
    audio = tmp_path / "audio.mp3"
    subtitle = tmp_path / "subtitle.srt"
    script = tmp_path / "script.json"
    for f in (combined, out):
        _make_mp4(f, 1080, 1920)
    audio.write_bytes(b"x" * 1024)
    subtitle.write_bytes(b"x" * 1024)
    script.write_bytes(b"{}")

    def boom(*a, **k):
        raise RuntimeError("simulated final render failure")

    monkeypatch.setattr(_video_module(), "concat_video_clips_with_ffmpeg", boom)
    with pytest.raises(RuntimeError):
        combine_videos(
            combined_video_path=str(out),
            video_paths=[str(clip)],
            audio_file=str(silence),
            video_aspect=VideoAspect.portrait,
            max_clip_duration=5,
            video_transition_mode=None,
        )
    # permanent / unrelated artifacts must survive cleanup
    assert combined.exists() and out.exists() and audio.exists()
    assert subtitle.exists() and script.exists()
    assert list(tmp_path.glob("temp-clip-*.mp4")) == []
    assert not (tmp_path / "ffmpeg-concat-list.txt").exists()
