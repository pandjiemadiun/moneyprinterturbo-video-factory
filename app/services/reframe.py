"""Smart 9:16 reframing module (BAGIAN C).

Converts any landscape / portrait / square video input into a 1080×1920
portrait clip **without stretching** by using the scale-to-cover + crop
technique:

    scale  =  W:H:force_original_aspect_ratio=increase   (fill target, pad overflow)
    crop   =  W:H                                         (cut excess, center)

When ``use_content_aware=True`` the crop offset is nudged toward the
detected content / subject area (via FFmpeg's ``cropdetect`` filter) so that
off-center subjects are not sliced off.

Design constraints honoured:
  * NEVER stretch pixels — ``force_original_aspect_ratio=increase`` preserves
    the input pixel aspect ratio; only the crop window changes position.
  * ALWAYS produce exactly ``target_w × target_h``.
  * ALWAYS include a safe center-crop fallback when content detection finds
    nothing useful.
  * Face detection is OPTIONAL (requires a model file).  When unavailable the
    module silently degrades to content-aware cropdetect + center crop.

No ML / heavy runtime dependency required.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_TARGET_W = 1080
DEFAULT_TARGET_H = 1920
# Minimum black-detection threshold for cropdetect (lower = more aggressive)
_CROPDETECT_LIMIT = 24
# Sample this many frames for cropdetect (0 = all)
_CROPDETECT_FRAMES = 5


def _probe_dimensions(video_path: str) -> Tuple[int, int, float]:
    """Return (width, height, duration) of a video via ffprobe."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,duration",
         "-of", "json", str(video_path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise FileNotFoundError(f"ffprobe failed for {video_path}")
    import json
    data = json.loads(proc.stdout)
    if not data.get("streams"):
        raise ValueError(f"No video stream in {video_path}")
    s = data["streams"][0]
    w = int(s["width"])
    h = int(s["height"])
    dur = float(s.get("duration", 0))
    return w, h, dur


def _has_audio(video_path: str) -> bool:
    """Check if the video has an audio stream."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0",
         str(video_path)],
        capture_output=True, text=True,
    )
    return bool(proc.stdout.strip())


def compute_crop_offset(
    video_path: str,
    target_w: int = DEFAULT_TARGET_W,
    target_h: int = DEFAULT_TARGET_H,
    use_face_detection: bool = True,
) -> Tuple[int, int]:
    """Compute the (x, y) crop offset to centre on the detected subject.

    Strategy (priority order):
      1. Face detection via OpenCV ``FaceDetectorYN`` (if model available).
      2. FFmpeg ``cropdetect`` on a sample of frames (content-bounding-box).
      3. Center crop fallback.

    Returns ``(x, y)`` — the top-left corner of the crop window in the
    *scaled-to-cover* frame coordinates.
    """
    src_w, src_h, _ = _probe_dimensions(video_path)

    # Scale-to-cover: both dimensions >= target
    if src_w / src_h > target_w / target_h:
        # Source is wider — scale by height
        scaled_w = round(src_w * target_h / src_h)
        scaled_h = target_h
    else:
        # Source is taller or equal — scale by width
        scaled_w = target_w
        scaled_h = round(src_h * target_w / src_w)

    if scaled_w <= target_w and scaled_h <= target_h:
        # Source already covers target exactly — centred, no offset
        return (0, 0)

    # --- 1. Face detection (optional) ---
    face_xy = _detect_faces(video_path, src_w, src_h, scaled_w, scaled_h,
                            target_w, target_h)
    if face_xy is not None:
        return face_xy

    # --- 2. Content-aware cropdetect ---
    content_xy = _detect_content_bounds(video_path, scaled_w, scaled_h,
                                        target_w, target_h)
    if content_xy is not None:
        return content_xy

    # --- 3. Center crop fallback ---
    cx = (scaled_w - target_w) // 2
    cy = (scaled_h - target_h) // 2
    return (max(0, cx), max(0, cy))


def _detect_faces(
    video_path: str,
    src_w: int, src_h: int,
    scaled_w: int, scaled_h: int,
    target_w: int, target_h: int,
) -> Optional[Tuple[int, int]]:
    """Try to find a face in a sample frame and return the crop offset.

    Uses OpenCV's ``FaceDetectorYN_create`` neural-network detector when a
    model file is available.  Returns ``None`` if no face found or OpenCV is
    not importable.
    """
    try:
        import cv2  # noqa: F401
    except (ImportError, Exception):
        return None

    try:
        # Try to find a face detection model
        model_path = _find_face_model()
        if model_path is None:
            return None

        face_detector = cv2.FaceDetectorYN_create(model_path, "", (src_w, src_h))
        if face_detector is None or face_detector.empty():
            return None

        # Extract one frame and run detection
        frame = _extract_frame(video_path, 0.1, src_w, src_h)
        if frame is None:
            return None

        faces = face_detector.detect(frame)
        if faces is None or len(faces) == 0:
            return None

        # Use the first face's bounding box
        # faces[1] contains the face rectangles (x, y, w, h) in some formats
        face = faces[1][0] if hasattr(faces[1], '__getitem__') and len(faces[1]) > 0 else faces[0]
        if hasattr(face, '__getitem__'):
            fx, fy, fw, fh = int(face[0]), int(face[1]), int(face[2]), int(face[3])
        else:
            fx, fy, fw, fh = 0, 0, src_w, src_h

        face_cx = (fx + fw / 2) * (scaled_w / src_w)
        face_cy = (fy + fh / 2) * (scaled_h / src_h)

        cx = int(face_cx - target_w / 2)
        cy = int(face_cy - target_h / 2)
        cx = max(0, min(cx, scaled_w - target_w))
        cy = max(0, min(cy, scaled_h - target_h))
        return (cx, cy)

    except Exception as exc:
        logger.debug(f"face detection skipped: {exc}")
        return None


def _find_face_model() -> Optional[str]:
    """Look for an OpenCV face detection model in common locations."""
    candidates = [
        os.environ.get("OPENCV_FACE_MODEL", ""),
        "/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml",
        "/usr/share/opencv/haarcascades/haarcascade_frontalface_default.xml",
    ]
    # Also check OpenCV's data directory
    try:
        import cv2
        if hasattr(cv2, "data") and cv2.data:
            d = cv2.data.__dict__.get("haarcascades", "")
            if d:
                candidates.append(str(Path(d) / "haarcascade_frontalface_default.xml"))
    except Exception:
        pass

    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def _extract_frame(video_path: str, t: float, w: int, h: int):
    """Extract a single RGB frame at time *t* using FFmpeg."""
    proc = subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(video_path),
         "-frames:v", "1", "-vf", "format=rgb24",
         "-f", "rawvideo", "-"],
        capture_output=True,
    )
    if not proc.stdout:
        return None
    try:
        import cv2
        import numpy as np
        arr = np.frombuffer(proc.stdout, dtype=np.uint8)
        frame = arr.reshape((h, w, 3))
        return frame
    except Exception:
        return None


def _detect_content_bounds(
    video_path: str,
    scaled_w: int, scaled_h: int,
    target_w: int, target_h: int,
) -> Optional[Tuple[int, int]]:
    """Use FFmpeg's cropdetect on a few frames to find the content bounding box.

    Returns the crop offset (x, y) in the *scaled-to-cover* frame, or ``None``
    if cropdetect does not provide a useful offset.
    """
    # Build a filter chain: scale to cover dims + cropdetect
    vf = f"scale={scaled_w}:{scaled_h},cropdetect={_CROPDETECT_LIMIT}:16:5"

    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path), "-vf", vf,
         "-frames:v", str(_CROPDETECT_FRAMES), "-f", "null", "-"],
        capture_output=True, text=True,
    )

    # Parse all "crop=W:H:X:Y" lines from stderr
    crops = []
    crop_pattern = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")
    for line in proc.stderr.splitlines():
        m = crop_pattern.search(line)
        if m:
            cw, ch, cx, cy = map(int, m.groups())
            crops.append((cw, ch, cx, cy))

    if not crops:
        return None

    # Take the last (stable) cropdetect result
    cw, ch, cx, cy = crops[-1]

    # If the detected crop is essentially the full frame, there's nothing
    # to offset — fall back to center crop.
    if abs(cw - scaled_w) / scaled_w < 0.05 or abs(ch - scaled_h) / scaled_h < 0.05:
        return None

    # The content center in the scaled frame
    content_cx = cx + cw / 2
    content_cy = cy + ch / 2

    # Compute crop top-left to centre on content
    offset_x = content_cx - target_w / 2
    offset_y = content_cy - target_h / 2

    # Clamp to valid range
    offset_x = max(0, min(int(offset_x), scaled_w - target_w))
    offset_y = max(0, min(int(offset_y), scaled_h - target_h))
    return (offset_x, offset_y)


def reframe_to_portrait(
    video_path: str,
    output_path: str,
    target_w: int = DEFAULT_TARGET_W,
    target_h: int = DEFAULT_TARGET_H,
    use_content_aware: bool = True,
    use_face_detection: bool = True,
) -> str:
    """Reframe *video_path* into ``target_w × target_h`` portrait.

    Uses scale-to-cover + crop — **never** stretches pixels.

    Parameters
    ----------
    video_path
        Source video (any aspect ratio).
    output_path
        Destination path for the reframed MP4.
    target_w, target_h
        Output dimensions (default 1080×1920).
    use_content_aware
        When True, use FFmpeg cropdetect to offset the crop toward the
        detected content.  Falls back to center crop when content is
        undeterminable.
    use_face_detection
        When True, attempt face detection (requires OpenCV model).
        Silently degrades to content-aware / center crop if unavailable.

    Returns
    -------
    str — the output_path on success, "" on failure.
    """
    if not os.path.exists(video_path):
        logger.error(f"reframe: input not found: {video_path}")
        return ""

    # Validate input via ffprobe
    try:
        src_w, src_h, src_dur = _probe_dimensions(video_path)
    except Exception as exc:
        logger.error(f"reframe: cannot probe {video_path}: {exc}")
        return ""

    # Guard against sub-frame-length videos
    if src_dur < 0.01:
        logger.warning(f"reframe: video too short ({src_dur}s), padding to 0.1s")
        src_dur = max(src_dur, 0.1)

    # If already exact dimensions, just copy / re-encode
    if src_w == target_w and src_h == target_h:
        # Still run through ffmpeg to normalise encoding (ensures yuv420p, h264)
        cmd = [
            "ffmpeg", "-y", "-i", str(video_path),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac" if _has_audio(video_path) else "copy",
            str(output_path),
        ]
    else:
        # --- Build scale-to-cover + crop filter chain ---
        # The scale filter uses force_original_aspect_ratio=increase, which
        # scales the input so BOTH dimensions >= target, preserving aspect
        # ratio. The crop then cuts the target window from the oversized frame.
        # We compute the crop offset in the *scaled* coordinate space.

        src_ratio = src_w / src_h
        target_ratio = target_w / target_h

        # Compute scale-to-cover dimensions (as FFmpeg would produce)
        if src_ratio > target_ratio:
            # Source is wider → scale by height
            scaled_w = round(src_w * target_h / src_h)
            scaled_h = target_h
        else:
            # Source is taller or equal → scale by width
            scaled_w = target_w
            scaled_h = round(src_h * target_w / src_w)

        if scaled_w <= target_w and scaled_h <= target_h:
            # Already covers target (exact ratio): just scale
            filter_vf = f"scale={target_w}:{target_h}"
        else:
            if use_content_aware:
                offset_x, offset_y = compute_crop_offset(
                    video_path, target_w, target_h,
                    use_face_detection=use_face_detection,
                )
            else:
                # Pure center crop — offset so the target window is centred
                # in the scaled frame
                offset_x = max(0, (scaled_w - target_w) // 2)
                offset_y = max(0, (scaled_h - target_h) // 2)

            filter_vf = (
                f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
                f"crop={target_w}:{target_h}:{offset_x}:{offset_y}"
            )

        # Preserve audio if present, else no audio track
        audio_args = []
        if _has_audio(video_path):
            audio_args = ["-c:a", "aac"]
        else:
            audio_args = ["-an"]

        cmd = [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vf", filter_vf,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            *audio_args,
            str(output_path),
        ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        logger.error(f"reframe: ffmpeg failed for {video_path}: {proc.stderr[:500]}")
        # Clean up partial output
        if os.path.exists(output_path):
            os.unlink(output_path)
        return ""

    # Verify output
    try:
        out_w, out_h, _ = _probe_dimensions(output_path)
        if out_w != target_w or out_h != target_h:
            logger.error(f"reframe: output dimensions {out_w}x{out_h} != {target_w}x{target_h}")
            return ""
    except Exception:
        logger.error(f"reframe: output verification failed for {output_path}")
        return ""

    return str(output_path)


def reframe_video(
    video_path: str,
    output_path: str,
    target_w: int = DEFAULT_TARGET_W,
    target_h: int = DEFAULT_TARGET_H,
    use_content_aware: bool = True,
) -> bool:
    """Convenience wrapper returning bool. See :func:`reframe_to_portrait`."""
    result = reframe_to_portrait(video_path, output_path, target_w, target_h,
                                  use_content_aware=use_content_aware)
    return bool(result)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python -m app.services.reframe <input> <output> [W H]")
        sys.exit(1)
    w = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_TARGET_W
    h = int(sys.argv[4]) if len(sys.argv) > 4 else DEFAULT_TARGET_H
    ok = reframe_video(sys.argv[1], sys.argv[2], w, h)
    print(f"OK={ok}")
