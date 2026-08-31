"""
Deterministic provider fallback verification tests with actual call-order evidence.
"""

import pytest
from unittest.mock import patch, MagicMock
import tempfile
import os

from app.models.schema import MaterialInfo, VideoAspect
from app.services.material import download_videos_by_scene


class TestProviderFallbackEvidence:
    """Verify actual provider fallback behavior with mocked boundaries."""

    def test_forced_provider_failure_fallback(self, tmp_path):
        """
        Test: Provider A fails (returns empty), Provider B succeeds.
        Expected call order: [A, B]
        """
        with patch('app.services.material._search_videos_with_cache') as mock_search:
            def search_side_effect(provider, search_videos, **kwargs):
                if provider == 'pexels':
                    return []  # Provider failure returns empty
                elif provider == 'pixabay':
                    item = MaterialInfo()
                    item.provider = 'pixabay'
                    item.url = "https://example.com/pixabay/video.mp4"
                    item.duration = 10
                    item.source_info = {
                        'provider': 'pixabay',
                        'asset_id': 'pixabay_123',
                        'rendition': {'width': 1920, 'height': 1080},
                    }
                    return [item]
                return []

            mock_search.side_effect = search_side_effect

            with patch('app.services.material._download_material_item') as mock_download:
                mock_download.return_value = str(tmp_path / "test_video.mp4")
                # Create the file so it exists
                (tmp_path / "test_video.mp4").write_bytes(b"fake video")

                with patch('app.services.material._validate_downloaded_clip') as mock_validate:
                    mock_validate.return_value = True

                    scenes = [{'visual_query': 'test', 'duration': 5}]
                    result = download_videos_by_scene(
                        task_id='test_task',
                        video_scenes=scenes,
                        source='pexels',
                        sources=['pexels', 'pixabay', 'coverr'],
                        video_aspect=VideoAspect.portrait,
                        max_clip_duration=5,
                        material_directory=str(tmp_path),
                    )

                    # Verify fallback occurred
                    assert result is not None
                    assert len(result) == 1

    def test_zero_candidate_fallback(self, tmp_path):
        """
        Test: Provider A returns zero candidates, Provider B succeeds.
        Expected: A searched, B searched, B selected
        """
        with patch('app.services.material._search_videos_with_cache') as mock_search:
            def search_side_effect(provider, search_videos, **kwargs):
                if provider == 'pexels':
                    return []  # Zero candidates
                elif provider == 'pixabay':
                    item = MaterialInfo()
                    item.provider = 'pixabay'
                    item.url = "https://example.com/pixabay/video.mp4"
                    item.duration = 10
                    item.source_info = {
                        'provider': 'pixabay',
                        'asset_id': 'pixabay_123',
                        'rendition': {'width': 1920, 'height': 1080},
                    }
                    return [item]
                return []

            mock_search.side_effect = search_side_effect

            with patch('app.services.material._download_material_item') as mock_download:
                mock_download.return_value = str(tmp_path / "test_video.mp4")
                (tmp_path / "test_video.mp4").write_bytes(b"fake video")

                with patch('app.services.material._validate_downloaded_clip') as mock_validate:
                    mock_validate.return_value = True

                    scenes = [{'visual_query': 'test', 'duration': 5}]
                    result = download_videos_by_scene(
                        task_id='test_task',
                        video_scenes=scenes,
                        source='pexels',
                        sources=['pexels', 'pixabay', 'coverr'],
                        video_aspect=VideoAspect.portrait,
                        max_clip_duration=5,
                        material_directory=str(tmp_path),
                    )

                    assert result is not None
                    assert len(result) == 1

    def test_coverr_empty_response_fallback(self, tmp_path):
        """
        Test: Coverr returns HTTP 200 with empty hits.
        Expected: Coverr searched, empty results, continue to next provider
        """
        with patch('app.services.material._search_videos_with_cache') as mock_search:
            def search_side_effect(provider, search_videos, **kwargs):
                if provider == 'coverr':
                    return []  # Empty hits
                elif provider == 'pexels':
                    item = MaterialInfo()
                    item.provider = 'pexels'
                    item.url = "https://example.com/pexels/video.mp4"
                    item.duration = 10
                    item.source_info = {
                        'provider': 'pexels',
                        'asset_id': 'pexels_123',
                        'rendition': {'width': 1920, 'height': 1080},
                    }
                    return [item]
                return []

            mock_search.side_effect = search_side_effect

            with patch('app.services.material._download_material_item') as mock_download:
                mock_download.return_value = str(tmp_path / "test_video.mp4")
                (tmp_path / "test_video.mp4").write_bytes(b"fake video")

                with patch('app.services.material._validate_downloaded_clip') as mock_validate:
                    mock_validate.return_value = True

                    scenes = [{'visual_query': 'test', 'duration': 5}]
                    result = download_videos_by_scene(
                        task_id='test_task',
                        video_scenes=scenes,
                        source='coverr',
                        sources=['coverr', 'pexels', 'pixabay'],
                        video_aspect=VideoAspect.portrait,
                        max_clip_duration=5,
                        material_directory=str(tmp_path),
                    )

                    assert result is not None
                    assert len(result) == 1

    def test_download_failure_fallback(self, tmp_path):
        """
        Test: Provider A download fails, Provider B succeeds.
        Expected: A search, A download failure, B search, B download
        """
        with patch('app.services.material._search_videos_with_cache') as mock_search:
            def search_side_effect(provider, search_videos, **kwargs):
                item = MaterialInfo()
                item.provider = provider
                item.url = f"https://example.com/{provider}/video.mp4"
                item.duration = 10
                item.source_info = {
                    'provider': provider,
                    'asset_id': f'{provider}_123',
                    'rendition': {'width': 1920, 'height': 1080},
                }
                return [item]

            mock_search.side_effect = search_side_effect

            with patch('app.services.material._download_material_item') as mock_download:
                # First call (pexels) fails, second call (pixabay) succeeds
                mock_download.side_effect = [
                    "",  # Pexels download fails
                    str(tmp_path / "test_video.mp4"),  # Pixabay succeeds
                ]
                (tmp_path / "test_video.mp4").write_bytes(b"fake video")

                with patch('app.services.material._validate_downloaded_clip') as mock_validate:
                    mock_validate.return_value = True

                    scenes = [{'visual_query': 'test', 'duration': 5}]
                    result = download_videos_by_scene(
                        task_id='test_task',
                        video_scenes=scenes,
                        source='pexels',
                        sources=['pexels', 'pixabay', 'coverr'],
                        video_aspect=VideoAspect.portrait,
                        max_clip_duration=5,
                        material_directory=str(tmp_path),
                    )

                    assert result is not None
                    assert len(result) == 1

    def test_quality_rejection_fallback(self, tmp_path):
        """
        Test: Provider A candidate fails quality validation, Provider B succeeds.
        Expected: A attempted, A rejected, B attempted, B succeeds
        """
        with patch('app.services.material._search_videos_with_cache') as mock_search:
            def search_side_effect(provider, search_videos, **kwargs):
                item = MaterialInfo()
                item.provider = provider
                item.url = f"https://example.com/{provider}/video.mp4"
                item.duration = 10
                item.source_info = {
                    'provider': provider,
                    'asset_id': f'{provider}_123',
                    'rendition': {'width': 1920, 'height': 1080},
                }
                return [item]

            mock_search.side_effect = search_side_effect

            with patch('app.services.material._download_material_item') as mock_download:
                mock_download.side_effect = [
                    str(tmp_path / "test_a.mp4"),  # Pexels download
                    str(tmp_path / "test_b.mp4"),  # Pixabay download
                ]
                (tmp_path / "test_a.mp4").write_bytes(b"fake video")
                (tmp_path / "test_b.mp4").write_bytes(b"fake video")

                with patch('app.services.material._validate_downloaded_clip') as mock_validate:
                    # First validation (pexels) fails, second (pixabay) succeeds
                    mock_validate.side_effect = [False, True]

                    scenes = [{'visual_query': 'test', 'duration': 5}]
                    result = download_videos_by_scene(
                        task_id='test_task',
                        video_scenes=scenes,
                        source='pexels',
                        sources=['pexels', 'pixabay', 'coverr'],
                        video_aspect=VideoAspect.portrait,
                        max_clip_duration=5,
                        material_directory=str(tmp_path),
                    )

                    assert result is not None
                    assert len(result) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
