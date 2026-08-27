"""Phase 7B — ScenePlan schema + VideoParams opt-in field (MPT side)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models.schema import ScenePlan, VideoParams, VideoAspect, VideoConcatMode


def test_scene_plan_fields_and_default_duration():
    s = ScenePlan(narration="hook text", visual_query="debt")
    assert s.narration == "hook text"
    assert s.visual_query == "debt"
    # target_duration is a planning hint with a stable default.
    assert s.target_duration == 5.0


def test_scene_plan_requires_narration_and_visual_query():
    # narration missing -> validation error
    try:
        ScenePlan(visual_query="debt")
        assert False, "expected validation error when narration missing"
    except Exception:
        pass

    # visual_query missing -> validation error
    try:
        ScenePlan(narration="text")
        assert False, "expected validation error when visual_query missing"
    except Exception:
        pass


def test_scene_plan_accepts_target_duration_override():
    s = ScenePlan(narration="x", visual_query="y", target_duration=12.5)
    assert s.target_duration == 12.5


def test_video_params_default_video_scenes_is_none():
    p = VideoParams(video_subject="5 Cara Keluar dari Hutang")
    assert p.video_scenes is None


def test_video_params_accepts_scene_list():
    scenes = [
        ScenePlan(narration="a", visual_query="debt"),
        ScenePlan(narration="b", visual_query="budget"),
    ]
    p = VideoParams(video_subject="x", video_scenes=scenes)
    assert p.video_scenes == scenes


def test_video_params_coerces_dict_scenes():
    p = VideoParams(
        video_subject="x",
        video_scenes=[{"narration": "a", "visual_query": "debt", "target_duration": 5.0}],
    )
    assert p.video_scenes[0].narration == "a"
    assert p.video_scenes[0].visual_query == "debt"


def test_legacy_params_have_no_video_scenes_key_by_default():
    """When video_scenes is not supplied, the payload stays legacy (None)."""
    p = VideoParams(video_subject="5 Cara Keluar dari Hutang")
    assert getattr(p, "video_scenes", None) is None
    # legacy concat defaults preserved
    assert p.video_concat_mode == VideoConcatMode.random.value
    assert p.video_clip_duration == 5
