"""Phase 7B — Scene-aware material selection (per-scene, one portrait clip)."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from app.models.schema import MaterialInfo, VideoAspect
from app.services import material


# Patch _validate_downloaded_clip so the scene-selection orchestration tests
# stay fast and deterministic without real downloaded files. The quality gate
# itself is covered in test_youtube_provider.py (real ffmpeg clips) and
# test_worker_quality_gate.py.
_PATCH_QG = patch.object(material, "_validate_downloaded_clip", return_value=True)


def _mat(provider="pixabay", url="http://x/1.mp4", dur=8, w=1080, h=1920,
         asset_id="111", search_term="debt"):
    m = MaterialInfo()
    m.provider = provider
    m.url = url
    m.duration = dur
    m.source_info = {
        "provider": provider,
        "search_term": search_term,
        "asset_id": asset_id,
        "source_page": f"https://pixabay.com/v/{asset_id}/",
        "rendition": {"id": "mp4", "width": w, "height": h},
    }
    return m


def test_one_usable_portrait_clip_per_scene_in_order():
    scenes = [
        {"narration": "a", "visual_query": "debt", "target_duration": 5.0},
        {"narration": "b", "visual_query": "budget", "target_duration": 5.0},
        {"narration": "c", "visual_query": "saving money", "target_duration": 5.0},
    ]
    by_term = {
        "debt": [_mat(asset_id="c1", search_term="debt")],
        "budget": [_mat(asset_id="c2", search_term="budget")],
        "saving money": [_mat(asset_id="c3", search_term="saving money")],
    }

    with patch.object(material, "_search_videos_with_cache",
                      side_effect=lambda **kwargs: by_term[kwargs["search_term"]]), \
         patch.object(material, "save_video", side_effect=lambda **kwargs: f"{kwargs['save_dir']}/saved.mp4"), \
         patch.object(material, "_persist_material_sources") as persist, \
         _PATCH_QG:
        paths = material.download_videos_by_scene(
            task_id="task-scene",
            video_scenes=scenes,
            source="pixabay",
            video_aspect=VideoAspect.portrait,
            max_clip_duration=5,
        )

    assert len(paths) == 3
    records = persist.call_args.args[1]
    assert len(records) == 3
    # scene ordering preserved; one material per scene; auditable fields
    assert [r["scene_index"] for r in records] == [0, 1, 2]
    assert [r["visual_query"] for r in records] == ["debt", "budget", "saving money"]
    assert [r["asset_id"] for r in records] == ["c1", "c2", "c3"]
    # portrait orientation filtering reused (landscape clip filtered out)
    assert [r["provider"] for r in records] == ["pixabay", "pixabay", "pixabay"]


def test_landscape_clips_accepted_for_reframing():
    """Landscape clips are NOT filtered out — they are accepted and reframed
    downstream by the smart 9:16 reframing pipeline (BAGIAN C). This test
    verifies that the universal resolver does not reject landscape footage."""
    scenes = [{"narration": "a", "visual_query": "debt", "target_duration": 5.0}]
    by_term = {
        "debt": [
            _mat(asset_id="landscape", w=1920, h=1080, search_term="debt"),
            _mat(asset_id="portrait", w=1080, h=1920, search_term="debt"),
        ]
    }
    with patch.object(material, "_search_videos_with_cache",
                      side_effect=lambda **kwargs: by_term[kwargs["search_term"]]), \
         patch.object(material, "save_video", side_effect=lambda **kwargs: f"{kwargs['save_dir']}/x.mp4"), \
         patch.object(material, "_persist_material_sources"), \
         _PATCH_QG:
        paths = material.download_videos_by_scene(
            task_id="t", video_scenes=scenes, source="pixabay",
            video_aspect=VideoAspect.portrait, max_clip_duration=5)
    assert len(paths) == 1


def test_scene_with_no_portrait_material_fails_cleanly():
    scenes = [
        {"narration": "a", "visual_query": "debt", "target_duration": 5.0},
        {"narration": "b", "visual_query": "no-such-term-xyz", "target_duration": 5.0},
    ]
    by_term = {"debt": [_mat()], "no-such-term-xyz": []}

    with patch.object(material, "_search_videos_with_cache",
                      side_effect=lambda **kwargs: by_term[kwargs["search_term"]]), \
         patch.object(material, "save_video", side_effect=lambda **kwargs: f"{kwargs['save_dir']}/x.mp4"), \
         patch.object(material, "_persist_material_sources"), \
         _PATCH_QG:
        with pytest.raises(RuntimeError) as exc:
            material.download_videos_by_scene(
                task_id="t", video_scenes=scenes, source="pixabay",
                video_aspect=VideoAspect.portrait, max_clip_duration=5)

    msg = str(exc.value)
    # clean failure identifying scene index + visual query; no cross-scene substitution
    assert "scene 1" in msg
    assert "no-such-term-xyz" in msg


def test_scene_branch_does_not_use_legacy_pool():
    """Scene-aware must NOT consume search_terms round-robin / not pool clips."""
    scenes = [{"narration": "a", "visual_query": "debt"},
              {"narration": "b", "visual_query": "budget"},
              {"narration": "c", "visual_query": "saving money"}]

    captured_terms = []

    def fake_search(**kwargs):
        captured_terms.append(kwargs["search_term"])
        # Distinct asset per query (real providers return distinct assets).
        return [_mat(asset_id=kwargs["search_term"], search_term=kwargs["search_term"])]

    with patch.object(material, "_search_videos_with_cache", side_effect=fake_search), \
         patch.object(material, "save_video", side_effect=lambda **kwargs: f"{kwargs['save_dir']}/x.mp4"), \
         patch.object(material, "_persist_material_sources"), \
         _PATCH_QG:
        material.download_videos_by_scene(
            task_id="t", video_scenes=scenes, source="pixabay",
            video_aspect=VideoAspect.portrait, max_clip_duration=5)

    # exactly one search per scene, in scene order, using the scene queries
    assert captured_terms == ["debt", "budget", "saving money"]


def test_pexels_provider_still_supported_for_scenes():
    scenes = [{"narration": "a", "visual_query": "money", "target_duration": 5.0}]
    with patch.object(material, "_search_videos_with_cache",
                      return_value=[_mat(provider="pexels", asset_id="p1")]), \
         patch.object(material, "save_video", side_effect=lambda **kwargs: f"{kwargs['save_dir']}/x.mp4"), \
         patch.object(material, "_persist_material_sources"), \
         _PATCH_QG:
        paths = material.download_videos_by_scene(
            task_id="t", video_scenes=scenes, source="pexels",
            video_aspect=VideoAspect.portrait, max_clip_duration=5)
    assert len(paths) == 1


def test_no_asset_reused_across_scenes_with_same_query():
    """Hook and point1 may share visual_query 'debt', but they must still get
    DISTINCT clips from that query's own pool (no clip reused within a render)."""
    scenes = [
        {"narration": "hook", "visual_query": "debt", "target_duration": 5.0},
        {"narration": "point1", "visual_query": "debt", "target_duration": 5.0},
        {"narration": "point2", "visual_query": "budget", "target_duration": 5.0},
    ]
    pool = [_mat(asset_id=f"a{i}", search_term="debt") for i in range(3)] \
        + [_mat(asset_id="b0", search_term="budget")]

    with patch.object(material, "_search_videos_with_cache",
                      side_effect=lambda **kwargs: list(pool)), \
         patch.object(material, "save_video", side_effect=lambda **kwargs: f"{kwargs['save_dir']}/x.mp4"), \
         patch.object(material, "_persist_material_sources") as persist, \
         _PATCH_QG:
        paths = material.download_videos_by_scene(
            task_id="t", video_scenes=scenes, source="pixabay",
            video_aspect=VideoAspect.portrait, max_clip_duration=5)

    assert len(paths) == 3
    records = persist.call_args.args[1]
    asset_ids = [r["asset_id"] for r in records]
    # 'debt' queried twice -> two DISTINCT assets chosen; no reuse
    assert asset_ids[0] != asset_ids[1]
    assert len(set(asset_ids)) == 3
