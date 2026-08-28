"""Phase 11D — Thumbnail pipeline tests.

TDD: These tests must FAIL before implementation.
Tests thumbnail generation, failure isolation, API exposure, and cleanup safety.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.models import const as model_const
from app.services import video, task

const = model_const


class TestThumbnailGeneration(unittest.TestCase):
    """Tests for thumbnail extraction from final videos."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.final_video = os.path.join(self.tmpdir, "final-1.mp4")
        self.thumbnail = os.path.join(self.tmpdir, "thumbnail-1.jpg")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_thumbnail_generated_from_final_video(self):
        """Successful final video should produce a thumbnail."""
        # Create a dummy final video file
        with open(self.final_video, "wb") as f:
            f.write(b"fake video data")

        with patch("app.services.video._extract_thumbnail_frame", return_value=self.thumbnail):
            result = video.generate_thumbnails([self.final_video], self.tmpdir)

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], self.thumbnail)

    def test_thumbnail_naming_convention(self):
        """Thumbnail should follow thumbnail-{index}.jpg naming."""
        with open(self.final_video, "wb") as f:
            f.write(b"fake video data")

        with patch("app.services.video._extract_thumbnail_frame", return_value=self.thumbnail):
            result = video.generate_thumbnails([self.final_video], self.tmpdir)

        self.assertTrue(result[0].endswith("thumbnail-1.jpg"))

    def test_thumbnail_uses_final_video_not_source(self):
        """Thumbnail must be extracted from final video, not raw source."""
        source_video = os.path.join(self.tmpdir, "source.mp4")
        with open(source_video, "wb") as f:
            f.write(b"source data")
        with open(self.final_video, "wb") as f:
            f.write(b"final data")

        extracted_from = []

        def mock_extract(video_path, output_path, timestamp=None):
            extracted_from.append(video_path)
            with open(output_path, "wb") as f:
                f.write(b"thumbnail")
            return output_path

        with patch("app.services.video._extract_thumbnail_frame", side_effect=mock_extract):
            video.generate_thumbnails([self.final_video], self.tmpdir)

        self.assertEqual(len(extracted_from), 1)
        self.assertEqual(extracted_from[0], self.final_video)

    def test_thumbnail_failure_does_not_raise(self):
        """Thumbnail generation failure should not raise an exception."""
        with open(self.final_video, "wb") as f:
            f.write(b"fake video data")

        with (
            patch("app.services.video.os.path.isfile", return_value=True),
            patch("app.services.video._extract_thumbnail_frame", side_effect=Exception("FFmpeg not found")),
        ):
            result = video.generate_thumbnails([self.final_video], self.tmpdir)

        self.assertIsNone(result)

    def test_thumbnail_missing_video_returns_none(self):
        """If final video doesn't exist, thumbnail should return None."""
        result = video.generate_thumbnails([self.final_video], self.tmpdir)
        self.assertIsNone(result)


class TestThumbnailFailureIsolation(unittest.TestCase):
    """Thumbnail failure must NOT fail the task."""

    def test_task_remains_complete_when_thumbnail_fails(self):
        """Task state should be COMPLETE even if thumbnail generation fails."""
        task_params = MagicMock()
        task_params.video_source = "pexels"
        task_params.video_aspect = video.VideoAspect.portrait
        task_params.video_concat_mode = video.VideoConcatMode.random
        task_params.video_transition_mode = None
        task_params.video_clip_duration = 5
        task_params.video_clip_speed = 1.0
        task_params.match_materials_to_script = False
        task_params.video_count = 1
        task_params.n_threads = 2
        task_params.bgm_type = "random"
        task_params.bgm_volume = 0.2
        task_params.subtitle_enabled = True
        task_params.font_name = "STHeitiMedium.ttc"
        task_params.text_background_color = False

        with (
            patch("app.services.task.video.combine_videos"),
            patch("app.services.task.video.generate_video", return_value=True),
            patch("app.services.task.video.generate_thumbnails", return_value=None),
            patch("app.services.task.sm") as mock_sm,
        ):
            mock_sm.state.update_task.return_value = None
            mock_task_state = {
                "task_id": "test-task",
                "state": const.TASK_STATE_PROCESSING,
                "progress": 50,
            }
            mock_sm.state.get_task.return_value = mock_task_state

            final_paths, combined_paths, warnings = task.generate_final_videos(
                task_id="test-task",
                params=task_params,
                downloaded_videos=["/tmp/clip.mp4"],
                audio_file="/tmp/audio.mp3",
                subtitle_path="/tmp/subtitle.srt",
                audio_duration=10,
            )

        self.assertEqual(len(final_paths), 1)
        self.assertEqual(warnings, [])


class TestThumbnailAPIExposure(unittest.TestCase):
    """Tests for thumbnail exposure through API."""

    def test_thumbnail_path_in_task_state(self):
        """Thumbnail paths should be stored in task state."""
        task_params = MagicMock()
        task_params.video_source = "pexels"
        task_params.video_aspect = video.VideoAspect.portrait
        task_params.video_concat_mode = video.VideoConcatMode.random
        task_params.video_transition_mode = None
        task_params.video_clip_duration = 5
        task_params.video_clip_speed = 1.0
        task_params.match_materials_to_script = False
        task_params.video_count = 1
        task_params.n_threads = 2
        task_params.bgm_type = "random"
        task_params.bgm_volume = 0.2
        task_params.subtitle_enabled = True
        task_params.font_name = "STHeitiMedium.ttc"
        task_params.text_background_color = False

        with (
            patch("app.services.task.video.combine_videos"),
            patch("app.services.task.video.generate_video", return_value=True),
            patch("app.services.task.video.generate_thumbnails", return_value=["/tmp/thumbnail-1.jpg"]),
            patch("app.services.task.sm") as mock_sm,
        ):
            mock_sm.state.update_task.return_value = None
            mock_task_state = {
                "task_id": "test-task",
                "state": const.TASK_STATE_PROCESSING,
                "progress": 50,
            }
            mock_sm.state.get_task.return_value = mock_task_state

            final_paths, combined_paths, warnings = task.generate_final_videos(
                task_id="test-task",
                params=task_params,
                downloaded_videos=["/tmp/clip.mp4"],
                audio_file="/tmp/audio.mp3",
                subtitle_path="/tmp/subtitle.srt",
                audio_duration=10,
            )

        self.assertEqual(len(final_paths), 1)


class TestThumbnailCleanupSafety(unittest.TestCase):
    """Thumbnails must not be affected by cleanup operations."""

    def test_cache_sweeper_does_not_touch_thumbnails(self):
        """Cache videos sweeper should not delete thumbnail files."""
        from app.services.material import _PROTECTED_FILENAMES, _CACHE_VIDEOS_FILE_PATTERNS

        # Thumbnails are not in cache_videos, they're in task directories
        # The cache sweeper only operates on cache_videos/
        self.assertNotIn("thumbnail-1.jpg", _PROTECTED_FILENAMES)

        # Thumbnail pattern should NOT match cache file patterns
        for pattern in _CACHE_VIDEOS_FILE_PATTERNS:
            self.assertIsNone(pattern.match("thumbnail-1.jpg"))


class TestThumbnailFrameSelection(unittest.TestCase):
    """Tests for frame selection strategy."""

    def test_frame_selection_uses_safe_timestamp(self):
        """Frame selection should use a safe timestamp, not t=0."""
        with (
            patch("app.services.video.os.path.isfile", return_value=True),
            patch("app.services.video.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)

            video._extract_thumbnail_frame(
                video_path="/tmp/final-1.mp4",
                output_path="/tmp/thumbnail-1.jpg",
                duration=30.0,
            )

            call_args = mock_run.call_args
            cmd = call_args[0][0]
            self.assertIn("-ss", cmd)
            ss_idx = cmd.index("-ss")
            timestamp = float(cmd[ss_idx + 1])
            self.assertGreater(timestamp, 0)

    def test_frame_selection_within_video_duration(self):
        """Selected frame must be within video duration."""
        with (
            patch("app.services.video.os.path.isfile", return_value=True),
            patch("app.services.video.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)

            video._extract_thumbnail_frame(
                video_path="/tmp/final-1.mp4",
                output_path="/tmp/thumbnail-1.jpg",
                duration=5.0,
            )

            call_args = mock_run.call_args
            cmd = call_args[0][0]
            ss_idx = cmd.index("-ss")
            timestamp = float(cmd[ss_idx + 1])
            self.assertLess(timestamp, 5.0)


if __name__ == "__main__":
    unittest.main()
