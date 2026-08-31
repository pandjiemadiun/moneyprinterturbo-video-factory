"""Tests for provider variable fix across all material paths."""

import pytest
from app.services.material import (
    _can_reframe_to_portrait,
    _matches_video_aspect,
    VideoAspect,
)


class TestProviderVariableFix:
    """Verify provider identity resolves correctly in all paths."""

    def test_legacy_path_uses_item_provider(self):
        """Legacy _download_videos_by_script_order uses item.provider."""
        import inspect
        from app.services import material
        source = inspect.getsource(material._download_videos_by_script_order)
        # Verify the fix is present
        assert "item, item.provider, material_directory" in source

    def test_scene_aware_path_uses_defined_provider(self):
        """Scene-aware download_videos_by_scene uses defined provider."""
        import inspect
        from app.services import material
        source = inspect.getsource(material.download_videos_by_scene)
        # Verify provider is defined in scope
        assert "provider, remote_search_videos = _provider_and_searcher(src)" in source


class TestPortraitReframing:
    """Test landscape-to-portrait reframing logic."""

    def test_native_portrait_preferred(self):
        """Native portrait candidates should be preferred over landscape."""
        assert _matches_video_aspect(1080, 1920, VideoAspect.portrait) is True

    def test_landscape_rejected_for_portrait(self):
        """Landscape should be rejected by native aspect check."""
        assert _matches_video_aspect(1920, 1080, VideoAspect.portrait) is False

    def test_can_reframe_full_hd_landscape(self):
        """1920x1080 landscape can be reframed to portrait."""
        assert _can_reframe_to_portrait(1920, 1080, 1080, 1920) is True

    def test_cannot_reframe_low_res_landscape(self):
        """720p landscape cannot be reframed to 1080x1920."""
        assert _can_reframe_to_portrait(1280, 720, 1080, 1920) is False

    def test_portrait_not_eligible_for_reframing(self):
        """Portrait source is not eligible for landscape-to-portrait reframing."""
        assert _can_reframe_to_portrait(1080, 1920, 1080, 1920) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
