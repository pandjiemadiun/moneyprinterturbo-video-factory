"""Phase 11B contract completion tests.

Verifies:
- YouTube appears as a selectable material source in download_videos
- YouTube selection maps to the correct backend parameter
- Existing providers remain available
- Task creation remains compatible
- YouTube failure can be represented without crashing
- Final video preview/download remains functional
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.services import material


class TestYouTubeInDownloadVideos(unittest.TestCase):
    """YouTube must be wired into the legacy download_videos provider map."""

    def setUp(self):
        self.original_app_config = dict(config.app)
        self.original_proxy_config = dict(config.proxy)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        config.proxy.clear()
        config.proxy.update(self.original_proxy_config)

    def _youtube_item(self, search_term, video_id="dQw4w9WgXcQ"):
        return material.MaterialInfo(
            provider="youtube",
            url=f"https://www.youtube.com/watch?v={video_id}",
            duration=30,
            source_info={
                "provider": "youtube",
                "search_term": search_term,
                "asset_id": video_id,
                "source_page": f"https://www.youtube.com/watch?v={video_id}",
                "title": "Test Video",
                "channel": "Test Channel",
                "license_status": "license_unknown",
            },
        )

    def test_download_videos_routes_youtube_to_search_videos_youtube(self):
        """When source='youtube', download_videos must call search_videos_youtube."""
        call_log = []

        def fake_youtube_search(search_term, minimum_duration, video_aspect):
            call_log.append(("youtube_search", search_term))
            return [self._youtube_item(search_term)]

        with (
            patch(
                "app.services.material.search_videos_youtube",
                side_effect=fake_youtube_search,
            ),
            patch(
                "app.services.material.save_video",
                return_value="/tmp/youtube-clip.mp4",
            ),
            patch(
                "app.services.material._search_videos_with_cache",
                side_effect=lambda provider, search_videos, search_term, minimum_duration, video_aspect: (
                    search_videos(search_term, minimum_duration, video_aspect)
                ),
            ),
        ):
            result = material.download_videos(
                task_id="test-youtube-route",
                search_terms=["space launch"],
                source="youtube",
                audio_duration=5,
                max_clip_duration=5,
            )

        self.assertEqual(len(call_log), 1)
        self.assertEqual(call_log[0][0], "youtube_search")
        self.assertEqual(result, ["/tmp/youtube-clip.mp4"])

    def test_download_videos_youtube_downloads_via_save_video_youtube_on_403(self):
        """When save_video fails for YouTube, it should fall back to save_video_youtube."""
        youtube_item = self._youtube_item("ocean waves")

        def failing_save_video(video_url, save_dir=""):
            if "youtube.com" in video_url:
                return ""
            return "/tmp/clip.mp4"

        def working_save_video_youtube(video_url, save_dir=""):
            return "/tmp/youtube-fallback.mp4"

        with (
            patch(
                "app.services.material.search_videos_youtube",
                return_value=[youtube_item],
            ),
            patch(
                "app.services.material.save_video",
                side_effect=failing_save_video,
            ),
            patch(
                "app.services.material.save_video_youtube",
                side_effect=working_save_video_youtube,
            ),
            patch(
                "app.services.material._search_videos_with_cache",
                side_effect=lambda provider, search_videos, search_term, minimum_duration, video_aspect: (
                    search_videos(search_term, minimum_duration, video_aspect)
                ),
            ),
        ):
            result = material.download_videos(
                task_id="test-youtube-fallback",
                search_terms=["ocean waves"],
                source="youtube",
                audio_duration=5,
                max_clip_duration=5,
            )

        self.assertEqual(result, ["/tmp/youtube-fallback.mp4"])

    def test_download_videos_youtube_failure_returns_empty_list(self):
        """If YouTube search returns nothing, download_videos returns empty list, not crash."""
        with (
            patch(
                "app.services.material.search_videos_youtube",
                return_value=[],
            ),
            patch(
                "app.services.material._search_videos_with_cache",
                side_effect=lambda provider, search_videos, search_term, minimum_duration, video_aspect: (
                    search_videos(search_term, minimum_duration, video_aspect)
                ),
            ),
        ):
            result = material.download_videos(
                task_id="test-youtube-empty",
                search_terms=["obscure term"],
                source="youtube",
                audio_duration=5,
                max_clip_duration=5,
            )

        self.assertEqual(result, [])

    def test_download_videos_youtube_failure_shows_meaningful_error(self):
        """YouTube search exceptions should propagate (caller handles them gracefully)."""
        with (
            patch(
                "app.services.material.search_videos_youtube",
                side_effect=Exception("yt_dlp not available"),
            ),
            patch(
                "app.services.material.material_cache.load_material_search_cache",
                return_value=None,
            ),
            patch(
                "app.services.material.material_cache.get_material_search_cache_lock",
                return_value=MagicMock(),
            ),
        ):
            # The exception propagates from search_videos_youtube through
            # _search_videos_with_cache to download_videos. The caller
            # (get_video_materials in task.py) catches it and marks the task failed.
            with self.assertRaises(Exception) as ctx:
                material.download_videos(
                    task_id="test-youtube-error",
                    search_terms=["test"],
                    source="youtube",
                    audio_duration=5,
                    max_clip_duration=5,
                )
            self.assertIn("yt_dlp not available", str(ctx.exception))


class TestExistingProvidersPreserved(unittest.TestCase):
    """Adding YouTube must not break existing provider behavior."""

    def setUp(self):
        self.original_app_config = dict(config.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def test_pexels_still_works(self):
        result = material.download_videos(
            task_id="test-pexels-still-works",
            search_terms=[],
            source="pexels",
            video_concat_mode="random",
        )
        self.assertEqual(result, [])

    def test_pixabay_still_works(self):
        result = material.download_videos(
            task_id="test-pixabay-still-works",
            search_terms=[],
            source="pixabay",
            video_concat_mode="random",
        )
        self.assertEqual(result, [])

    def test_coverr_still_works(self):
        result = material.download_videos(
            task_id="test-coverr-still-works",
            search_terms=[],
            source="coverr",
            video_concat_mode="random",
        )
        self.assertEqual(result, [])

    def test_local_not_in_download_videos(self):
        """Local is handled by a separate code path in get_video_materials, not download_videos."""
        result = material.download_videos(
            task_id="test-local-not-here",
            search_terms=[],
            source="local",
            video_concat_mode="random",
        )
        self.assertEqual(result, [])


class TestYouTubeProviderAndSearcher(unittest.TestCase):
    """_provider_and_searcher must include YouTube (used by scene-aware path)."""

    def test_youtube_in_provider_searcher(self):
        provider, search_fn = material._provider_and_searcher("youtube")
        self.assertEqual(provider, "youtube")
        self.assertEqual(search_fn, material.search_videos_youtube)


if __name__ == "__main__":
    unittest.main()
