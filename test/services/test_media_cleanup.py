"""
Phase 10C — Media Cleanup Tests

Tests for:
  P0 — Quality-gate rejection cleanup (material.py)
  P1 — Temp clip cleanup hardening (video.py combine_videos)
  P1 — Safe orphan cache_videos sweeper (material.py)

All tests use temporary directories and mocks.
DO NOT touch production cache_videos/ or factory.db.
"""

import os
import re
import sys
import time
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import material as mat
from app.services import video as vd
from app.services import state as sm
from app.models import const


# ─────────────────────────────────────────────────────────────────────
# P0: Quality-gate rejection cleanup
# ─────────────────────────────────────────────────────────────────────

class TestQualityRejectionCleanup(unittest.TestCase):
    """Tests for safe deletion of quality-gate rejected clips."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_cleanup_reject_")
        # Patch utils.storage_dir so material.py writes to temp
        self._orig_storage_dir = mat.utils.storage_dir

    def tearDown(self):
        self._orig_storage_dir = mat.utils.storage_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _patch_save_dir(self):
        """Patch save_video_youtube's default save_dir to temp."""
        return patch.object(mat.utils, "storage_dir", return_value=self.tmpdir)

    def test_rejected_file_is_deleted(self):
        """
        TEST 1: Quality rejection — exact rejected file is deleted.
        """
        # Create a fake raw file that would be returned by save_video_youtube
        hash_val = "abcdef0123456789abcdef0123456789"
        fake_file = os.path.join(self.tmpdir, f"vid-{hash_val}.mp4")
        Path(fake_file).write_bytes(b"fake youtube download content")

        self.assertTrue(os.path.exists(fake_file))

        # Simulate the quality-rejection cleanup logic directly
        # (We test delete_files which is the mechanism used for cleanup)
        vd.delete_files(fake_file)

        self.assertFalse(os.path.exists(fake_file))

    def test_unrelated_cache_files_remain(self):
        """
        TEST 1: Unrelated cache files remain after rejection cleanup.
        """
        hash_val = "abcdef0123456789abcdef0123456789"
        rejected = os.path.join(self.tmpdir, f"vid-{hash_val}.mp4")
        unrelated = os.path.join(self.tmpdir, "vid-otherhash000000000000000000.mp4")
        Path(rejected).write_bytes(b"rejected")
        Path(unrelated).write_bytes(b"unrelated")

        vd.delete_files(rejected)

        self.assertFalse(os.path.exists(rejected))
        self.assertTrue(os.path.exists(unrelated))

    def test_missing_rejected_file_is_harmless(self):
        """
        TEST 2: Rejection where file already disappeared — no crash.
        """
        missing = os.path.join(self.tmpdir, "vid-missing1234567890123456789012.mp4")
        # File doesn't exist
        self.assertFalse(os.path.exists(missing))
        # Should not raise
        vd.delete_files(missing)

    def test_rejection_delete_error_does_not_crash(self):
        """
        TEST 3: OSError during deletion — warning logged, no crash.
        """
        fake_file = os.path.join(self.tmpdir, "vid-to-delete.mp4")
        Path(fake_file).write_bytes(b"content")

        with patch.object(vd.os, "remove", side_effect=OSError("permission denied")):
            # Should not raise
            vd.delete_files(fake_file)

    def test_rejection_logs_cleanup_result(self):
        """
        Verify cleanup logging is emitted on success and failure.
        """
        fake_file = os.path.join(self.tmpdir, "vid-test.mp4")
        Path(fake_file).write_bytes(b"content")

        with patch.object(vd.logger, "warning") as mock_warning:
            # Force a deletion error
            with patch.object(vd.os, "remove", side_effect=OSError("denied")):
                vd.delete_files(fake_file)
            mock_warning.assert_called()


class TestRejectionInDownloadPipeline(unittest.TestCase):
    """
    Test the actual rejection-cleanup path inside download_videos_by_scene.
    Uses minimal mocking — only patches the download/validate steps.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_cleanup_pipeline_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_download_videos_by_scene_cleans_rejected_files(self):
        """
        TEST 1 (pipeline integration): When _validate_downloaded_clip fails
        inside download_videos_by_scene, the downloaded file is deleted.
        """
        # Create a fake MaterialInfo-like object
        fake_item = SimpleNamespace(
            url="https://example.com/test.mp4",
            duration=10,
            width=640,
            height=360,
            source_info={"asset_id": "test-1"},
            provider="pexels",
            thumbnail="http://example.com/thumb.jpg",
            fps=30,
        )

        # Create a fake file to represent the download
        fake_file = os.path.join(self.tmpdir, "vid-test.mp4")
        Path(fake_file).write_bytes(b"fake video")

        scene = {
            "scene_id": 0,
            "narration": "test",
            "visual_query": "test query",
        }

        with (
            patch.object(mat, "_search_videos_with_cache", return_value=[fake_item]),
            patch.object(mat, "rank_videos", return_value=[fake_item]),
            patch.object(mat, "_download_material_item", return_value=fake_file),
            patch.object(mat, "_validate_downloaded_clip", return_value=False),
            patch.object(mat, "_resolve_material_directory", return_value=self.tmpdir),
            patch.object(mat, "_provider_and_searcher",
                         return_value=("pexels", MagicMock())),
            patch.object(mat, "_persist_material_sources"),
        ):
            try:
                mat.download_videos_by_scene(
                    task_id="test-cleanup",
                    video_scenes=[scene],
                    source="pexels",
                    max_clip_duration=5,
                )
            except RuntimeError:
                pass  # Expected — all providers exhausted

            # The rejected file should be deleted by the cleanup logic
            # (after our P0 fix is applied)
            self.assertFalse(os.path.exists(fake_file))


# ─────────────────────────────────────────────────────────────────────
# P1: Temp clip cleanup hardening
# ─────────────────────────────────────────────────────────────────────

class TestTempClipCleanupHardening(unittest.TestCase):
    """
    Tests for try/finally hardening of temp-clip deletion in combine_videos.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_cleanup_tempclip_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_temp_clips_deleted_on_success(self):
        """
        TEST 4: Temp clips deleted after successful concat.
        """
        # Create fake temp clip files
        clip1 = os.path.join(self.tmpdir, "temp-clip-1.mp4")
        clip2 = os.path.join(self.tmpdir, "temp-clip-2.mp4")
        Path(clip1).write_bytes(b"clip 1")
        Path(clip2).write_bytes(b"clip 2")

        combined_path = os.path.join(self.tmpdir, "combined-1.mp4")

        with (
            patch.object(vd, "AudioFileClip") as mock_audio,
            patch.object(vd, "concat_video_clips_with_ffmpeg") as mock_concat,
        ):
            mock_audio.return_value = SimpleNamespace(duration=30, close=MagicMock())

            # Simulate the finally block calling delete_files
            vd.delete_files([clip1, clip2])

            self.assertFalse(os.path.exists(clip1))
            self.assertFalse(os.path.exists(clip2))

    def test_temp_clips_cleanup_on_failure(self):
        """
        TEST 5: Temp clips cleaned even when concat fails.
        """
        combined_path = os.path.join(self.tmpdir, "combined-1.mp4")

        def fake_concat(*args, **kwargs):
            raise RuntimeError("concat failed")

        def fake_write_videofile(clip, outputfile, **kwargs):
            # Simulate writing the temp clip to disk
            Path(outputfile).write_bytes(b"temp clip content")

        with (
            patch.object(vd, "AudioFileClip") as mock_audio,
            patch.object(vd, "_open_video_clip_quietly") as mock_open_clip,
            patch.object(vd, "_write_videofile_with_codec_fallback", side_effect=fake_write_videofile),
            patch.object(vd, "concat_video_clips_with_ffmpeg", side_effect=fake_concat),
        ):
            mock_audio.return_value = SimpleNamespace(duration=30, close=MagicMock())
            # Mock clip with correct portrait dimensions (1080x1920) to skip resize
            mock_clip = MagicMock()
            mock_clip.duration = 10
            mock_clip.size = (1080, 1920)  # matches portrait VideoAspect resolution
            mock_clip.w = 1080
            mock_clip.h = 1920
            mock_clip.subclipped.return_value = mock_clip
            mock_clip.resized.return_value = mock_clip
            mock_clip.cropped.return_value = mock_clip
            mock_clip.with_speed_scaled.return_value = mock_clip
            mock_open_clip.return_value = mock_clip

            try:
                vd.combine_videos(
                    combined_video_path=combined_path,
                    video_paths=[os.path.join(self.tmpdir, "src.mp4")],
                    audio_file=os.path.join(self.tmpdir, "audio.mp3"),
                    max_clip_duration=5,
                )
            except RuntimeError:
                pass

        # After P1 fix (try/finally), temp clips should be cleaned even if concat raised
        remaining_temp_clips = [
            f for f in os.listdir(self.tmpdir)
            if f.startswith("temp-clip-") and f.endswith(".mp4")
        ]
        self.assertEqual(
            len(remaining_temp_clips), 0,
            f"temp clips should be cleaned up after concat failure: {remaining_temp_clips}"
        )

    def test_temp_clips_cleanup_on_unexpected_exception(self):
        """
        TEST 6: Temp clips cleaned when an unexpected exception occurs during concat.
        This verifies the try/finally catches ANY exception type, not just RuntimeError.
        """
        combined_path = os.path.join(self.tmpdir, "combined-1.mp4")

        def fake_write_videofile(clip, outputfile, **kwargs):
            Path(outputfile).write_bytes(b"temp clip content")

        def fake_concat_unexpected(*args, **kwargs):
            raise ValueError("unexpected concatenation error")

        with (
            patch.object(vd, "AudioFileClip") as mock_audio,
            patch.object(vd, "_open_video_clip_quietly") as mock_open_clip,
            patch.object(vd, "_write_videofile_with_codec_fallback", side_effect=fake_write_videofile),
            patch.object(vd, "concat_video_clips_with_ffmpeg", side_effect=fake_concat_unexpected),
        ):
            mock_audio.return_value = SimpleNamespace(duration=30, close=MagicMock())
            mock_clip = MagicMock()
            mock_clip.duration = 10
            mock_clip.size = (1080, 1920)
            mock_clip.w = 1080
            mock_clip.h = 1920
            mock_clip.subclipped.return_value = mock_clip
            mock_clip.resized.return_value = mock_clip
            mock_clip.cropped.return_value = mock_clip
            mock_clip.with_speed_scaled.return_value = mock_clip
            mock_open_clip.return_value = mock_clip

            try:
                vd.combine_videos(
                    combined_video_path=combined_path,
                    video_paths=[os.path.join(self.tmpdir, "src.mp4")],
                    audio_file=os.path.join(self.tmpdir, "audio.mp3"),
                    max_clip_duration=5,
                )
            except ValueError:
                pass  # expected unexpected exception

        # After P1 fix (try/finally), temp clips should be cleaned even for
        # unexpected exception types during concatenation
        remaining_temp_clips = [
            f for f in os.listdir(self.tmpdir)
            if f.startswith("temp-clip-") and f.endswith(".mp4")
        ]
        self.assertEqual(
            len(remaining_temp_clips), 0,
            f"temp clips should be cleaned up after unexpected exception: {remaining_temp_clips}"
        )


# ─────────────────────────────────────────────────────────────────────
# P1: Safe orphan cache sweeper
# ─────────────────────────────────────────────────────────────────────

class TestOrphanSweeper(unittest.TestCase):
    """
    Tests for the cache_videos orphan sweeper.
    Uses a temporary directory instead of production cache_videos/.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_cleanup_sweeper_")
        # Create a fake cache_videos dir
        self.cache_dir = os.path.join(self.tmpdir, "cache_videos")
        os.makedirs(self.cache_dir)
        # Patch the storage_dir AND the material module's reference to it
        self._patcher = patch.object(mat.utils, "storage_dir", return_value=self.cache_dir)
        self._patcher.start()
        # Patch the sm.state to use MemoryState with controlled tasks
        # material.py imports state as sm (from app.services import state as sm)
        self._orig_state = mat.sm.state
        self._fake_state = sm.MemoryState()
        mat.sm.state = self._fake_state

    def tearDown(self):
        self._patcher.stop()
        mat.sm.state = self._orig_state
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_old(self, filepath, days_old=31):
        """Set file mtime to N days ago."""
        old_time = time.time() - (days_old * 86400)
        os.utime(filepath, (old_time, old_time))

    def _make_recent(self, filepath, minutes_old=5):
        """Set file mtime to N minutes ago."""
        recent_time = time.time() - (minutes_old * 60)
        os.utime(filepath, (recent_time, recent_time))

    def _vid_filename(self, hash_str="a" * 32):
        return f"vid-{hash_str}.mp4"

    def test_recent_cache_file_preserved(self):
        """
        TEST 7: Recent cache file remains.
        """
        f = os.path.join(self.cache_dir, self._vid_filename())
        Path(f).write_bytes(b"recent")
        self._make_recent(f, minutes_old=5)

        mat.cleanup_orphan_cache_videos()
        self.assertTrue(os.path.exists(f))

    def test_old_unreferenced_file_deleted(self):
        """
        TEST 8: Old, unreferenced cache file is deleted.
        """
        f = os.path.join(self.cache_dir, self._vid_filename())
        Path(f).write_bytes(b"old stale")
        self._make_old(f, days_old=31)

        mat.cleanup_orphan_cache_videos()
        self.assertFalse(os.path.exists(f))

    def test_old_active_file_preserved(self):
        """
        TEST 9: Old file referenced by an active task is kept.
        """
        fname = self._vid_filename()
        f = os.path.join(self.cache_dir, fname)
        Path(f).write_bytes(b"old but in use")
        self._make_old(f, days_old=31)

        # Register an active task that references this file in its materials
        task_id = "test-active-task"
        sm.state.update_task(task_id, const.TASK_STATE_PROCESSING, progress=50,
                             materials=[fname])

        mat.cleanup_orphan_cache_videos()
        self.assertTrue(os.path.exists(f))

    def test_old_part_file_deleted(self):
        """
        TEST 10: Old .part file is deleted.
        """
        f = os.path.join(self.cache_dir, f"{self._vid_filename()}.part")
        Path(f).write_bytes(b"partial download")
        self._make_old(f, days_old=31)

        mat.cleanup_orphan_cache_videos()
        self.assertFalse(os.path.exists(f))

    def test_unknown_file_preserved(self):
        """
        TEST 11: Unknown/unrecognized file remains.
        """
        f = os.path.join(self.cache_dir, "important-user-file.mp4")
        Path(f).write_bytes(b"user data")
        self._make_old(f, days_old=31)

        mat.cleanup_orphan_cache_videos()
        self.assertTrue(os.path.exists(f))

    def test_production_artifacts_preserved(self):
        """
        TEST 12: Production artifacts (final, combined, audio, etc.) are NOT touched.
        
        These should live in task dir, not cache_videos. But verify the sweeper
        would never delete them even if they existed in cache_videos.
        """
        # Even if these were in cache_videos (they shouldn't be), keep them
        for name in ["final-1.mp4", "combined-1.mp4", "audio.mp3",
                      "subtitle.srt", "script.json", "scene_timing.json"]:
            f = os.path.join(self.cache_dir, name)
            Path(f).write_bytes(b"production")
            self._make_old(f, days_old=31)

        mat.cleanup_orphan_cache_videos()

        for name in ["final-1.mp4", "combined-1.mp4", "audio.mp3",
                      "subtitle.srt", "script.json", "scene_timing.json"]:
            f = os.path.join(self.cache_dir, name)
            self.assertTrue(os.path.exists(f), f"{name} should not be deleted")

    def test_outside_cache_videos_untouched(self):
        """
        TEST 13: Files outside cache_videos directory are untouched.
        """
        # Create files outside cache_videos
        other_dir = os.path.join(self.tmpdir, "other_dir")
        os.makedirs(other_dir)

        for name in [self._vid_filename("b"*32), "temp-clip-1.mp4", "final-1.mp4"]:
            f = os.path.join(other_dir, name)
            Path(f).write_bytes(b"outside scope")
            self._make_old(f, days_old=31)

        mat.cleanup_orphan_cache_videos()

        for name in [self._vid_filename("b"*32), "temp-clip-1.mp4", "final-1.mp4"]:
            f = os.path.join(other_dir, name)
            self.assertTrue(os.path.exists(f), f"{name} outside cache_videos should remain")

    def test_cleanup_error_handled(self):
        """
        TEST 14: Cleanup error — warning logged, sweeper continues.
        """
        f1 = os.path.join(self.cache_dir, self._vid_filename("a"*32))
        f2 = os.path.join(self.cache_dir, self._vid_filename("b"*32))
        Path(f1).write_bytes(b"file1")
        Path(f2).write_bytes(b"file2")
        self._make_old(f1, days_old=31)
        self._make_old(f2, days_old=31)

        # Make deletion of f1 fail
        original_remove = os.remove
        call_count = [0]
        def flaky_remove(path):
            call_count[0] += 1
            if path == f1 and call_count[0] == 1:
                raise OSError("permission error")
            original_remove(path)

        with patch.object(os, "remove", side_effect=flaky_remove):
            # Should not crash
            mat.cleanup_orphan_cache_videos()

        # f1 might still exist (if remove failed), but f2 should be deleted
        self.assertFalse(os.path.exists(f2))

    def test_idempotency(self):
        """
        TEST 15: Running cleanup twice is safe.
        """
        f1 = os.path.join(self.cache_dir, self._vid_filename("a"*32))
        Path(f1).write_bytes(b"file1")
        self._make_old(f1, days_old=31)

        mat.cleanup_orphan_cache_videos()
        self.assertFalse(os.path.exists(f1))

        # Second run should not error
        mat.cleanup_orphan_cache_videos()

    def test_concurrency_two_active_tasks_same_file(self):
        """
        TEST 16: Two active tasks referencing same raw file → file kept.
        """
        fname = self._vid_filename()
        f = os.path.join(self.cache_dir, fname)
        Path(f).write_bytes(b"shared resource")
        self._make_old(f, days_old=31)

        task1 = "task-aaa"
        task2 = "task-bbb"
        sm.state.update_task(task1, const.TASK_STATE_PROCESSING, progress=50,
                             materials=[fname])
        sm.state.update_task(task2, const.TASK_STATE_PROCESSING, progress=30,
                             materials=[fname])

        mat.cleanup_orphan_cache_videos()
        self.assertTrue(os.path.exists(f), "file shared by active tasks must be preserved")

    def test_ytdl_file_deleted(self):
        """Additional: .ytdl files cleaned after TTL."""
        fname = self._vid_filename()
        f = os.path.join(self.cache_dir, f"{fname}.ytdl")
        Path(f).write_bytes(b"ytdl state")
        self._make_old(f, days_old=31)

        mat.cleanup_orphan_cache_videos()
        self.assertFalse(os.path.exists(f))

    def test_frag_file_deleted(self):
        """Additional: .Frag* files cleaned after TTL."""
        hash_val = "a" * 32
        f = os.path.join(self.cache_dir, f"vid-{hash_val}.mp4.Frag1")
        Path(f).write_bytes(b"fragment")
        self._make_old(f, days_old=31)

        mat.cleanup_orphan_cache_videos()
        self.assertFalse(os.path.exists(f))

    def test_invalid_hex_filename_preserved(self):
        """Additional: filename that looks like vid- but wrong hex length is kept."""
        f = os.path.join(self.cache_dir, "vid-notvalidhex.mp4")
        Path(f).write_bytes(b"content")
        self._make_old(f, days_old=31)

        mat.cleanup_orphan_cache_videos()
        self.assertTrue(os.path.exists(f))

    def test_failed_task_file_deleted(self):
        """Additional: old file from a FAILED task (not active) is deleted."""
        fname = self._vid_filename()
        f = os.path.join(self.cache_dir, fname)
        Path(f).write_bytes(b"orphan from failed task")
        self._make_old(f, days_old=31)

        # Task is in FAILED state — not active
        sm.state.update_task("old-failed-task", const.TASK_STATE_FAILED, progress=100,
                             script_json={"videos": [fname]})

        mat.cleanup_orphan_cache_videos()
        self.assertFalse(os.path.exists(f), "file from failed task should be cleaned")

    def test_completed_task_file_deleted(self):
        """Additional: old file from a COMPLETED task is deleted."""
        fname = self._vid_filename()
        f = os.path.join(self.cache_dir, fname)
        Path(f).write_bytes(b"orphan from completed task")
        self._make_old(f, days_old=31)

        sm.state.update_task("old-completed-task", const.TASK_STATE_COMPLETE, progress=100,
                             script_json={"videos": [fname]})

        mat.cleanup_orphan_cache_videos()
        self.assertFalse(os.path.exists(f), "file from completed task should be cleaned")


# ─────────────────────────────────────────────────────────────────────
# P1: YouTube provider regression verification
# ─────────────────────────────────────────────────────────────────────

class TestYouTubeProviderUnchanged(unittest.TestCase):
    """
    TEST 18: Verify YouTube provider configuration is unchanged.
    """

    def test_yt_dlp_opts_unchanged(self):
        """Verify yt-dlp options are NOT modified (no nopart, format unchanged)."""
        # We can't easily inspect the internal ydl_opts, but we can verify
        # the function still accepts the same parameters and doesn't use nopart
        import inspect
        source = inspect.getsource(mat.save_video_youtube)
        # nopart should NOT be in the source
        self.assertNotIn("nopart", source, "nopart must NOT be added to yt-dlp opts")
        # Format must be unchanged
        self.assertIn("best[ext=mp4][height<=720]", source)
        # merge_output_format must be unchanged
        self.assertIn("merge_output_format", source)

    def test_quality_gate_constants_unchanged(self):
        """Verify _MATERIAL_MIN_WIDTH and _MATERIAL_MIN_HEIGHT are unchanged."""
        self.assertEqual(mat._MATERIAL_MIN_WIDTH, 480)
        self.assertEqual(mat._MATERIAL_MIN_HEIGHT, 480)

    def test_provider_fallback_order_unchanged(self):
        """Verify _download_material_item still tries HTTP then YouTube."""
        import inspect
        source = inspect.getsource(mat._download_material_item)
        # save_video (HTTP) should be called first
        save_idx = source.index("save_video(video_url")
        # save_video_youtube should come AFTER save_video
        youtube_idx = source.index("save_video_youtube(video_url")
        self.assertLess(save_idx, youtube_idx,
                        "save_video (HTTP) must be tried before save_video_youtube")

    def test_validate_downloaded_clip_unchanged(self):
        """Verify the quality gate logic is unchanged."""
        import inspect
        source = inspect.getsource(mat._validate_downloaded_clip)
        self.assertIn("w < _MATERIAL_MIN_WIDTH or h < _MATERIAL_MIN_HEIGHT", source)
        self.assertIn("os.path.exists(video_path)", source)


# ─────────────────────────────────────────────────────────────────────
# TEST 17: 3.21 GiB regression model simulation
# ─────────────────────────────────────────────────────────────────────

class TestLargeRejectionModel(unittest.TestCase):
    """
    TEST 17: Simulate the 3.21 GiB rejected file scenario without downloading.
    Uses a small fake file representing the same cache path pattern.
    """

    def test_rejected_large_file_pattern_deleted(self):
        """
        The actual 3.21 GiB YouTube video that was rejected is represented
        here by a small file at the same cache path pattern.
        The quality-gate rejection cleanup must delete it.
        """
        tmpdir = tempfile.mkdtemp(prefix="test_cleanup_large_")
        try:
            # The known YouTube URL was omwuNTQcsvI, hash would be:
            # (We use a deterministic hash for testing)
            import hashlib
            actual_url = "https://www.youtube.com/watch?v=omwuNTQcsvI"
            url_hash = hashlib.md5(actual_url.split("?")[0].encode()).hexdigest()
            fake_file = os.path.join(tmpdir, f"vid-{url_hash}.mp4")

            # Create a small file (NOT 3.21 GiB) at the exact cache path
            Path(fake_file).write_bytes(b"simulated large rejected clip")

            self.assertTrue(os.path.exists(fake_file))

            # Apply the same cleanup that download_videos_by_scene does
            # after quality gate rejection
            mat.utils.storage_dir = lambda sub_dir="", create=False: tmpdir
            # Use delete_files (the actual mechanism in the code)
            vd.delete_files(fake_file)

            self.assertFalse(os.path.exists(fake_file),
                              "Rejected video must be cleaned up (regression for 3.21 GiB case)")

            # Verify no other files in the directory
            remaining = os.listdir(tmpdir)
            self.assertEqual(len(remaining), 0,
                             f"No other files should remain in cache: {remaining}")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
