"""Regression test for the Phase 8F/8G black-frame tail defect.

Root cause (confirmed read-only in Phase 8F):
`generate_video()` composes
    video_clip = CompositeVideoClip([video_clip, *text_clips])
The composite duration is driven by subtitle `TextClip` end timestamps (taken
straight from the SRT) and can extend *past* the real video layer
(`combined-1.mp4`). CompositeVideoClip then renders the
[video_end, subtitle_end] gap as its DEFAULT black background while subtitles
remain visible.

Invariant under test:
    FINAL VIDEO STREAM DURATION  <=  REAL VIDEO-LAYER DURATION  (+ jitter)
and the last real frame must be actual footage (not a black canvas).
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# mirror test/services/test_video.py: add project root to python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.services import video as vd  # noqa: E402


def _ffprobe_video_duration(path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=duration", "-of",
         "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def _frame_luma(path, t):
    """Decode one frame at t -> (mean_luma, near_black_pct<8); None if no frame."""
    proc = subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{t:.4f}", "-i", str(path),
         "-frames:v", "1", "-vf", "format=gray", "-f", "rawvideo", "-"],
        capture_output=True,
    )
    data = proc.stdout
    if not data:
        return None
    n = len(data)
    return (round(sum(data) / n, 2),
            round(100.0 * sum(1 for b in data if b < 8) / n, 2))


class _RegenRealClip:
    """Minimal fixture: 10s green video + 10.5s voice + SRT that outlasts video."""

    VIDEO_DUR = 10.0

    @staticmethod
    def make(directory: Path) -> dict:
        directory.mkdir(parents=True, exist_ok=True)
        video = directory / "combined.mp4"
        audio = directory / "voice.wav"
        subtitle = directory / "subtitle.srt"
        # 10s bright-green 1080x1920 footage (luma ~150, never black).
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", "color=c=0x00ff00:s=1080x1920:d=10:r=30",
             "-frames:v", "300", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             str(video)],
            capture_output=True, check=True,
        )
        # 10.5s voice track — longer than the video layer (mirrors real renders).
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", "sine=frequency=440:d=10.5:sample_rate=22050",
             "-c:a", "pcm_s16le", str(audio)],
            capture_output=True, check=True,
        )
        # Last cue ends at 10.5s -> outlasts the 10s video layer (triggers bug).
        # Trailing blank line so the final SRT cue is parsed by moviepy's
        # file_to_subtitles (it flushes a cue on the blank separator).
        subtitle.write_text(
            "1\n00:00:00,000 --> 00:00:05,000\nHello world opening\n\n"
            "2\n00:00:09,000 --> 00:00:10,500\nFinal call to action\n\n"
        )
        return {"video": str(video), "audio": str(audio),
                "subtitle": str(subtitle)}


class TestGenerateVideoBlackTail(unittest.TestCase):
    """The final VIDEO stream must never be padded with black frames merely
    because subtitle TextClips or audio outlast the real video layer."""

    def test_final_video_does_not_extend_past_real_video_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            assets = _RegenRealClip.make(d)
            params = vd.VideoParams(
                video_subject="black tail regression",
                subtitle_enabled=True,
                bgm_type="none",
                bgm_volume=0.0,
            )
            output = str(d / "final-1.mp4")
            vd.generate_video(
                video_path=assets["video"],
                audio_path=assets["audio"],
                subtitle_path=assets["subtitle"],
                output_file=output,
                params=params,
            )

            src_vdur = _ffprobe_video_duration(assets["video"])
            final_vdur = _ffprobe_video_duration(output)

            # 1 encoding frame + margin (well below the 0.5s black tail bug).
            tol = 2.0 / 30.0 + 0.1
            self.assertLessEqual(
                final_vdur, src_vdur + tol,
                f"final video stream ({final_vdur:.3f}s) extends past the real "
                f"video layer ({src_vdur:.3f}s) -> black tail introduced by "
                f"subtitle composition",
            )

            last = _frame_luma(output, max(0.0, final_vdur * 0.99))
            self.assertIsNotNone(last, "expected a final video frame")
            mean, near_black = last
            self.assertLess(
                near_black, 50.0,
                f"final frame is near-black (mean={mean}, near_black={near_black}%) "
                f"-> black tail reached the last frame",
            )

            # The timestamp that the BUG turns black (video_end + 0.25s) must
            # NOT exist as a black frame: after the fix the stream ends at the
            # real layer, so there is no frame here; if one exists it is real.
            buggy_tail_t = src_vdur + 0.25
            tail = _frame_luma(output, buggy_tail_t)
            if tail is not None:
                self.assertLess(
                    tail[1], 50.0,
                    f"frame at {buggy_tail_t:.2f}s is near-black "
                    f"(mean={tail[0]}, near_black={tail[1]}%) -> black tail present",
                )


if __name__ == "__main__":
    unittest.main()
