"""Phase 7B — Scene-aware combine: trim-to-scene-duration, concat once, no loop."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from unittest.mock import patch

from app.services import video as vd
from app.models.schema import VideoConcatMode


class _FakeAudioClip:
    duration = 100.0  # long -> would trigger the legacy 5s loop if scene mode didn't bypass it

    def close(self):
        pass


class _FakeVideoClip:
    def __init__(self, duration=5.0):
        self.duration = duration
        self.size = (1080, 1920)
        self.w = 1080
        self.h = 1920

    def subclipped(self, start_time, end_time):
        return _FakeVideoClip(end_time - start_time)

    def with_speed_scaled(self, factor):
        return _FakeVideoClip(self.duration / factor)

    def close(self):
        pass

    def resized(self, new_size=None, **kwargs):
        return self

    def with_position(self, *args, **kwargs):
        return self


def test_scene_combine_trims_each_clip_to_scene_duration():
    scenes = [{"duration": 5.0}, {"duration": 7.0}, {"duration": 6.0}]
    written = []

    with tempfile.TemporaryDirectory() as tmp:
        combined = os.path.join(tmp, "combined.mp4")
        audio = os.path.join(tmp, "audio.mp3")

        def open_clip(path):
            return _FakeVideoClip(duration=50.0)

        def capture_writer(clip, *args, **kwargs):
            written.append(clip.duration)

        with patch.object(vd, "AudioFileClip", return_value=_FakeAudioClip()), \
             patch.object(vd, "_open_video_clip_quietly", side_effect=open_clip), \
             patch.object(vd, "_write_videofile_with_codec_fallback", side_effect=capture_writer), \
             patch.object(vd, "_prioritize_unique_source_clips",
                          side_effect=lambda **kwargs: kwargs["subclipped_items"]), \
             patch.object(vd, "concat_video_clips_with_ffmpeg") as concat, \
             patch.object(vd, "delete_files"):
            vd.combine_videos(
                combined_video_path=combined,
                video_paths=["a.mp4", "b.mp4", "c.mp4"],
                audio_file=audio,
                video_concat_mode=VideoConcatMode.sequential,
                max_clip_duration=5,
                scene_specs=scenes,
            )

        # one output clip per scene, trimmed to the scene (TTS) duration
        assert written == [5.0, 7.0, 6.0]
        # concatenated exactly once
        assert concat.call_count == 1
        # max_duration=None => no global 5s cycling/truncation
        assert concat.call_args.kwargs["max_duration"] is None
        # scene order preserved
        assert len(concat.call_args.kwargs["clip_files"]) == 3


def test_scene_combine_does_not_loop_clips():
    """Even with a very long audio, scene mode must NOT cycle clips."""
    scenes = [{"duration": 3.0}, {"duration": 3.0}]

    with tempfile.TemporaryDirectory() as tmp:
        combined = os.path.join(tmp, "combined.mp4")
        with patch.object(vd, "AudioFileClip", return_value=_FakeAudioClip()), \
             patch.object(vd, "_open_video_clip_quietly", return_value=_FakeVideoClip(50.0)), \
             patch.object(vd, "_write_videofile_with_codec_fallback") as writer, \
             patch.object(vd, "_prioritize_unique_source_clips",
                          side_effect=lambda **kwargs: kwargs["subclipped_items"]), \
             patch.object(vd, "concat_video_clips_with_ffmpeg") as concat, \
             patch.object(vd, "delete_files"):
            vd.combine_videos(
                combined_video_path=combined,
                video_paths=["a.mp4", "b.mp4"],
                audio_file="a.mp3",
                video_concat_mode=VideoConcatMode.sequential,
                scene_specs=scenes,
            )
        # exactly 2 clips written (one per scene), NOT a cycled list
        assert writer.call_count == 2
        assert concat.call_args.kwargs["max_duration"] is None


def test_legacy_combine_still_uses_audio_max_duration():
    """Regression: legacy path (scene_specs=None) keeps max_duration=audio_duration."""
    with tempfile.TemporaryDirectory() as tmp:
        combined = os.path.join(tmp, "combined.mp4")
        with patch.object(vd, "AudioFileClip", return_value=_FakeAudioClip()), \
             patch.object(vd, "_open_video_clip_quietly", return_value=_FakeVideoClip(50.0)), \
             patch.object(vd, "_write_videofile_with_codec_fallback"), \
             patch.object(vd, "_prioritize_unique_source_clips",
                          side_effect=lambda **kwargs: kwargs["subclipped_items"]), \
             patch.object(vd, "concat_video_clips_with_ffmpeg") as concat, \
             patch.object(vd, "delete_files"):
            vd.combine_videos(
                combined_video_path=combined,
                video_paths=["a.mp4"],
                audio_file="a.mp3",
                video_concat_mode=VideoConcatMode.random,
                scene_specs=None,
            )
        assert concat.call_args.kwargs["max_duration"] == 100.0
