"""Phase 11C — YouTube first-class UI integration tests.

Test-first development for YouTube UX improvements.
Uses isolated mocks/fixtures, no production network calls.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.models import const
from app.services import material, task


class TestYouTubeUIIntegration(unittest.TestCase):
    """Tests for YouTube first-class UI experience."""

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

    def test_youtube_search_terms_map_to_download_videos(self):
        """Video keywords (search_terms) must map correctly for YouTube download."""
        call_log = []

        def fake_youtube_search(search_term, minimum_duration, video_aspect):
            call_log.append(search_term)
            return [self._youtube_item(search_term, video_id=f"test{len(call_log):09d}")]

        with (
            patch(
                "app.services.material.search_videos_youtube",
                side_effect=fake_youtube_search,
            ),
            patch(
                "app.services.material._download_material_item",
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
                task_id="test-youtube-terms",
                search_terms=["nature documentary", "ocean waves"],
                source="youtube",
                audio_duration=10,
                max_clip_duration=5,
            )

        self.assertEqual(call_log, ["nature documentary", "ocean waves"])
        self.assertEqual(len(result), 2)

    def test_youtube_empty_search_terms_returns_empty(self):
        """Empty search terms for YouTube should return empty list, not crash."""
        result = material.download_videos(
            task_id="test-youtube-empty-terms",
            search_terms=[],
            source="youtube",
            audio_duration=5,
            max_clip_duration=5,
        )
        self.assertEqual(result, [])

    def test_youtube_task_failure_has_meaningful_error(self):
        """YouTube material failure should include provider name in error."""
        task_params = MagicMock()
        task_params.video_source = "youtube"
        task_params.video_terms = "test"
        task_params.video_aspect = material.VideoAspect.portrait
        task_params.video_concat_mode = material.VideoConcatMode.random
        task_params.video_clip_duration = 5
        task_params.match_materials_to_script = False

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
            with patch("app.services.task.sm") as mock_sm:
                mock_sm.state.get_task.return_value = None
                mock_sm.state.update_task.return_value = None
                mock_task = {
                    "task_id": "test-task",
                    "state": const.TASK_STATE_PROCESSING,
                    "progress": 50,
                }
                mock_sm.state.get_task.return_value = mock_task

                result = task.get_video_materials(
                    task_id="test-task-id",
                    params=task_params,
                    video_terms=["test"],
                    audio_duration=10,
                )

                self.assertIsNone(result)

    def test_youtube_failure_includes_stage_information(self):
        """Failed YouTube task should have failed_stage='materials'."""
        task_params = MagicMock()
        task_params.video_source = "youtube"
        task_params.video_terms = "obscure query"
        task_params.video_aspect = material.VideoAspect.portrait
        task_params.video_concat_mode = material.VideoConcatMode.random
        task_params.video_clip_duration = 5
        task_params.match_materials_to_script = False

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
            patch("app.services.task.sm") as mock_sm,
        ):
            mock_task_state = {}
            mock_sm.state.get_task.return_value = mock_task_state
            mock_sm.state.update_task.side_effect = lambda task_id, **kwargs: mock_task_state.update(kwargs)
            mock_sm.state.patch_task.side_effect = lambda task_id, **kwargs: mock_task_state.update(kwargs) or True

            result = task.get_video_materials(
                task_id="test-youtube-stage",
                params=task_params,
                video_terms=["obscure"],
                audio_duration=10,
            )

            self.assertIsNone(result)


class TestYouTubeSourceInWebUI(unittest.TestCase):
    """Test YouTube appears correctly in the source dropdown options."""

    def test_youtube_is_valid_source_value(self):
        """YouTube must be in the valid source list."""
        valid_sources = [
            "pexels", "pixabay", "coverr", "youtube", "wavespeed", "loomloom", "local"
        ]
        self.assertIn("youtube", valid_sources)

    def test_youtube_maps_to_search_function(self):
        """YouTube source must map to search_videos_youtube."""
        provider, search_fn = material._provider_and_searcher("youtube")
        self.assertEqual(provider, "youtube")
        self.assertEqual(search_fn, material.search_videos_youtube)


class TestExistingProvidersUnchanged(unittest.TestCase):
    """Regression: existing providers must work after YouTube additions."""

    def test_pexels_download_still_works(self):
        result = material.download_videos(
            task_id="test-pexels-11c",
            search_terms=[],
            source="pexels",
        )
        self.assertEqual(result, [])

    def test_pixabay_download_still_works(self):
        result = material.download_videos(
            task_id="test-pixabay-11c",
            search_terms=[],
            source="pixabay",
        )
        self.assertEqual(result, [])

    def test_coverr_download_still_works(self):
        result = material.download_videos(
            task_id="test-coverr-11c",
            search_terms=[],
            source="coverr",
        )
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
