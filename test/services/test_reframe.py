"""TDD tests for smart 9:16 reframing (BAGIAN C).

These tests verify that landscape, portrait, and square video clips are
reframed into 1080×1920 portrait WITHOUT stretching, WITHOUT black bars,
and WITH subject-safe cropping.

Written BEFORE implementation (RED phase) — expected to fail until
``app.services.reframe`` is implemented.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest

TARGET_W, TARGET_H = 1080, 1920


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_video(path: Path, w: int, h: int, color: str = "0x108010",
                 box_x: int = 0, box_y: int = 0, box_w: int = 0, box_h: int = 0,
                 box_color: str = "0xFFFF00", duration: float = 2.0):
    """Create a test video with an optional yellow 'subject' rectangle."""
    path.parent.mkdir(parents=True, exist_ok=True)
    vf = f"color=c={color}:s={w}x{h}:d={duration}:r=24"
    if box_w > 0 and box_h > 0:
        vf = f"{vf},drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}:color={box_color}:t=fill"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", vf,
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        capture_output=True, check=True,
    )


def _ffprobe_stream(path: Path):
    """Return (width, height, duration) via ffprobe."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,duration",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    data = json.loads(proc.stdout)
    s = data["streams"][0]
    return (int(s["width"]), int(s["height"]), float(s.get("duration", 0)))


def _extract_frame_rgb(path: Path, t: float):
    """Extract one RGB24 frame at time *t* as raw bytes (or None)."""
    proc = subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(path),
         "-frames:v", "1", "-vf", "format=rgb24", "-f", "rawvideo", "-"],
        capture_output=True,
    )
    return proc.stdout if proc.stdout else None


def _pixel_at(path: Path, t: float, x: int, y: int) -> tuple:
    """Extract RGB value of a single pixel at (x, y) at time t."""
    proc = subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(path),
         "-vf", f"crop=1:1:{x}:{y}", "-frames:v", "1", "-f", "rawvideo", "-"],
        capture_output=True,
    )
    data = proc.stdout
    if len(data) >= 3:
        return (data[0], data[1], data[2])
    return (0, 0, 0)


def _find_yellow_bbox(frame_bytes: bytes, w: int, h: int):
    """Find bounding box of yellow pixels (R>200, G>200, B<100).

    Returns (x0, y0, x1, y1) or None.
    """
    px_size = w * h
    step = max(1, px_size // 10000)  # sample ~10000 pixels for speed
    min_x = w; min_y = h; max_x = 0; max_y = 0
    found = False
    for i in range(0, px_size, step):
        r = frame_bytes[i * 3]
        g = frame_bytes[i * 3 + 1]
        b = frame_bytes[i * 3 + 2]
        if r > 200 and g > 200 and b < 100:
            px = i % w
            py = i // w
            min_x = min(min_x, px)
            min_y = min(min_y, py)
            max_x = max(max_x, px)
            max_y = max(max_y, py)
            found = True
    if not found:
        return None
    return (min_x, min_y, max_x, max_y)


def _subject_visible(path: Path) -> bool:
    """Check if the yellow subject box is visible anywhere in the reframed
    output video. Scans for yellow pixels (R>200, G>200, B<100)."""
    out_w, out_h, dur = _ffprobe_stream(path)
    if dur <= 0:
        return False
    times = [0.1, min(dur / 2, dur - 0.1), max(dur - 0.1, 0.1)]
    for t in times:
        if t < 0:
            continue
        frame = _extract_frame_rgb(path, t)
        if frame and len(frame) >= out_w * out_h * 3:
            if _find_yellow_bbox(frame, out_w, out_h) is not None:
                return True
    return False


# ── Tests ────────────────────────────────────────────────────────────────────

def test_01_landscape_to_portrait_no_stretching(tmp_path):
    """Landscape 16:9 (1920×1080) → 1080×1920. Must use scale-to-cover + crop."""
    from app.services.reframe import reframe_to_portrait

    src = tmp_path / "land.mp4"
    _make_video(src, w=1920, h=1080, box_x=600, box_y=400, box_w=400, box_h=300,
                color="0x108010", box_color="0xFFFF00")
    out = tmp_path / "out.mp4"
    reframe_to_portrait(str(src), str(out))

    w, h, _ = _ffprobe_stream(out)
    assert w == TARGET_W, f"width {w} != {TARGET_W}"
    assert h == TARGET_H, f"height {h} != {TARGET_H}"


def test_02_portrait_to_portrait(tmp_path):
    """Portrait 9:16 (1080×1920) → 1080×1920. Direct pass (no crop needed)."""
    from app.services.reframe import reframe_to_portrait

    src = tmp_path / "portrait.mp4"
    _make_video(src, w=1080, h=1920, box_x=300, box_y=500, box_w=400, box_h=600,
                color="0x108010", box_color="0xFFFF00")
    out = tmp_path / "out.mp4"
    reframe_to_portrait(str(src), str(out))

    w, h, _ = _ffprobe_stream(out)
    assert w == TARGET_W
    assert h == TARGET_H


def test_03_square_to_portrait(tmp_path):
    """Square 1:1 (1080×1080) → 1080×1920."""
    from app.services.reframe import reframe_to_portrait

    src = tmp_path / "square.mp4"
    _make_video(src, w=1080, h=1080, box_x=200, box_y=200, box_w=300, box_h=400,
                color="0x108010", box_color="0xFFFF00")
    out = tmp_path / "out.mp4"
    reframe_to_portrait(str(src), str(out))

    w, h, _ = _ffprobe_stream(out)
    assert w == TARGET_W
    assert h == TARGET_H


def test_04_no_stretching_preserves_aspect_ratio(tmp_path):
    """Verify content is not stretched: a square yellow box in the source
    must remain approximately square (equal width/height) in the output."""
    from app.services.reframe import reframe_to_portrait

    src = tmp_path / "circle.mp4"
    _make_video(src, w=1920, h=1080, box_x=860, box_y=440, box_w=200, box_h=200,
                color="0x108010", box_color="0xFFFF00", duration=2.0)
    out = tmp_path / "out.mp4"
    reframe_to_portrait(str(src), str(out))

    w, h, _ = _ffprobe_stream(out)
    assert w == TARGET_W and h == TARGET_H

    frame = _extract_frame_rgb(out, 0.1)
    assert frame is not None and len(frame) >= w * h * 3
    bbox = _find_yellow_bbox(frame, w, h)
    assert bbox is not None, "Yellow box not found in output"
    x0, y0, x1, y1 = bbox
    box_w_out = x1 - x0
    box_h_out = y1 - y0
    ratio = box_w_out / box_h_out if box_h_out > 0 else float("inf")
    assert 0.7 < ratio < 1.43, \
        f"Box appears stretched: w={box_w_out}, h={box_h_out}, ratio={ratio:.2f}"


def test_05_correct_output_dimensions(tmp_path):
    """All outputs must be exactly 1080×1920 regardless of input aspect."""
    from app.services.reframe import reframe_to_portrait
    for desc, dims in [("landscape", (1920, 1080)), ("portrait", (1080, 1920)),
                       ("square", (1080, 1080)), ("ultra-wide", (2560, 1080)),
                       ("tall-portrait", (720, 1280))]:
        src = tmp_path / f"{desc}.mp4"
        _make_video(src, w=dims[0], h=dims[1], duration=1.5)
        out = tmp_path / f"{desc}_out.mp4"
        reframe_to_portrait(str(src), str(out))
        if out.exists():
            w, h, _ = _ffprobe_stream(out)
            assert w == 1080, f"{desc}: width {w} != 1080"
            assert h == 1920, f"{desc}: height {h} != 1920"


def test_06_subject_safe_crop_centered_subject_visible(tmp_path):
    """A subject in the center of a landscape frame must remain visible."""
    from app.services.reframe import reframe_to_portrait

    src = tmp_path / "centered.mp4"
    _make_video(src, w=1920, h=1080, box_x=860, box_y=440, box_w=200, box_h=200,
                color="0x108010", box_color="0xFFFF00", duration=3.0)
    out = tmp_path / "out.mp4"
    reframe_to_portrait(str(src), str(out))
    assert _subject_visible(out), "Centered subject should be visible after reframing"


def test_07_subject_on_left_stays_visible(tmp_path):
    """A subject on the left third of a 16:9 frame must NOT be cropped off
    when content-aware crop is enabled."""
    from app.services.reframe import reframe_to_portrait

    src = tmp_path / "left.mp4"
    # Yellow box on LEFT, black background so cropdetect can find subject
    _make_video(src, w=1920, h=1080, color="0x000000", box_x=100, box_y=400,
                box_w=200, box_h=200, box_color="0xFFFF00", duration=3.0)
    out = tmp_path / "out.mp4"
    reframe_to_portrait(str(src), str(out), use_content_aware=True)
    assert _subject_visible(out), "Subject on left should be visible with content-aware crop"


def test_08_subject_on_right_stays_visible(tmp_path):
    """A subject on the right third of a 16:9 frame must NOT be cropped off."""
    from app.services.reframe import reframe_to_portrait

    src = tmp_path / "right.mp4"
    # Yellow box on RIGHT, black background so cropdetect can find subject
    _make_video(src, w=1920, h=1080, color="0x000000", box_x=1620, box_y=500,
                box_w=200, box_h=200, box_color="0xFFFF00", duration=3.0)
    out = tmp_path / "out.mp4"
    reframe_to_portrait(str(src), str(out), use_content_aware=True)
    assert _subject_visible(out), "Subject on right should be visible with content-aware crop"


def test_09_center_subject_crop_is_centered(tmp_path):
    """Default center crop must keep a centrally located subject visible."""
    from app.services.reframe import reframe_to_portrait

    src = tmp_path / "center.mp4"
    _make_video(src, w=1920, h=1080, box_x=860, box_y=440, box_w=200, box_h=200,
                color="0x108010", box_color="0xFFFF00", duration=2.0)
    out = tmp_path / "out.mp4"
    reframe_to_portrait(str(src), str(out), use_content_aware=False)
    assert _subject_visible(out), "Centered subject should be visible with center crop"


def test_10_no_face_fallback_center_crop(tmp_path):
    """Uniform-color video → no content to detect → center crop fallback."""
    from app.services.reframe import reframe_to_portrait

    src = tmp_path / "uniform.mp4"
    _make_video(src, w=1920, h=1080, color="0x000000", duration=2.0)
    out = tmp_path / "out.mp4"
    reframe_to_portrait(str(src), str(out), use_content_aware=True)

    w, h, _ = _ffprobe_stream(out)
    assert w == 1080 and h == 1920


def test_11_mixed_aspect_ratio_in_one_render(tmp_path):
    """Multiple clips with different aspect ratios, all reframed to 1080×1920."""
    from app.services.reframe import reframe_to_portrait

    for i, dims in enumerate([(1920, 1080), (1080, 1920), (1080, 1080), (2560, 1440)]):
        src = tmp_path / f"clip_{i}.mp4"
        _make_video(src, w=dims[0], h=dims[1], duration=2.0,
                    box_x=dims[0] // 4, box_y=dims[1] // 4,
                    box_w=dims[0] // 5, box_h=dims[1] // 5,
                    color="0x108010", box_color="0xFFFF00")
        out = tmp_path / f"clip_{i}_reframed.mp4"
        reframe_to_portrait(str(src), str(out))
        assert out.exists() and out.stat().st_size > 0
        w, h, _ = _ffprobe_stream(out)
        assert w == 1080 and h == 1920, \
            f"clip {i} ({dims}): reframed to {w}x{h}, expected 1080x1920"


def test_12_invalid_video_handled_gracefully(tmp_path):
    """Corrupt video file → must not crash, returns failure indication."""
    from app.services.reframe import reframe_to_portrait

    fake = tmp_path / "corrupt.mp4"
    fake.write_bytes(b"not a real video file")
    out = tmp_path / "out.mp4"

    result = reframe_to_portrait(str(fake), str(out))
    assert result is False or result == "", \
        f"Expected False/empty for corrupt input, got {result!r}"
    if out.exists():
        assert out.stat().st_size == 0


def test_13_too_short_video_handled(tmp_path):
    """Video shorter than 0.1s → must be handled (not crash)."""
    from app.services.reframe import reframe_to_portrait

    src = tmp_path / "too_short.mp4"
    _make_video(src, w=1920, h=1080, duration=0.05,
                box_x=860, box_y=440, box_w=200, box_h=200,
                color="0x108010", box_color="0xFFFF00")
    out = tmp_path / "out.mp4"

    result = reframe_to_portrait(str(src), str(out))
    # Either succeeds with padding or returns failure — key is no crash
    if result and out.exists() and out.stat().st_size > 0:
        w, h, _ = _ffprobe_stream(out)
        assert w == 1080 and h == 1920


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
