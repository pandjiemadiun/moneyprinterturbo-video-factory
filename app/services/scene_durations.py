"""Phase 7B — authoritative per-scene durations from actual TTS timing (P1).

MoneyPrinterTurbo's edge_tts path is configured with ``boundary="WordBoundary"``
(see ``app.services.voice.create_edge_tts_communicate``), so every
``edge_tts.SubMaker.cues`` entry is a *per-word* ``Subtitle`` carrying
``.content`` (the input word), ``.start`` and ``.end`` (as ``timedelta``).
The SRT hand-off (`voice.create_subtitle`) then groups those per-word cues
into punctuated *clauses* — which is exactly why **SRT cue count != scene
count** (a single point sentence is split into several clauses).

To avoid that counting trap entirely we map each ``ScenePlan.narration``
directly onto the per-word SubMaker timeline:
  * tokenize both the scene narration and every cue ``.content`` with the same
    normalization (lowercase, alphanumeric tokens only) — this drops the
    "N. " list-number formatting and is invariant to punctuation/whitespace;
  * find each scene's narration as an ordered, contiguous token subsequence,
    advancing a shared cursor so repeated word sequences map to the *correct*
    occurrence (the second "hutang bayar" is not matched to the first);
  * derive (scene_index, start, end, duration) from the matched cue span.

``target_duration`` is never used here — it is only a planning hint.
"""
from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: Any) -> list[str]:
    """Normalize text to a lowercase alphanumeric token stream.

    Mirrors how edge_tts exposes word boundary ``.content`` while stripping the
    punctuation / list-number formatting introduced by ``_build_script`` so the
    scene narration (e.g. "Daftar dan catat ...") aligns to the cues of the
    spoken line "1. Daftar dan catat ...".
    """
    return _TOKEN_RE.findall((text or "").lower())


def _cue_words(cue: Any) -> list[str]:
    """Tokenize a single SubMaker cue.

    Tolerates both the current edge_tts ``Subtitle.content`` attribute and a
    generic ``text`` attribute (some test doubles / future providers).
    """
    content = getattr(cue, "content", None)
    if content is None:
        content = getattr(cue, "text", "")
    return _tokenize(content)


def compute_scene_durations(
    video_scenes: list[dict],
    sub_maker: Any,
) -> list[dict]:
    """Map every scene in ``video_scenes`` to its authoritative TTS duration.

    Args:
        video_scenes: ordered list of ``{"narration", "visual_query", ...}``.
        sub_maker: an ``edge_tts.SubMaker`` (or compatible duck-typed object)
            whose ``.cues`` are per-word subtitles with ``.content``/``.start``
            /``.end`` (``.end`` exposing ``total_seconds()``).

    Returns:
        ``[{"scene_index", "start", "end", "duration"} ...]`` in scene order,
        durations in seconds derived from the real TTS word timestamps.

    Raises:
        RuntimeError: if the SubMaker is missing/empty, a scene narration is
            empty, or a scene's narration cannot be matched to a contiguous
            word span (e.g. the spoken text drifted from the planned script).
    """
    if sub_maker is None:
        raise RuntimeError(
            "scene-aware mode requires a TTS SubMaker with word cues"
        )

    cues = getattr(sub_maker, "cues", None)
    if not cues:
        raise RuntimeError(
            "scene-aware mode requires a SubMaker with word cues, but it is empty"
        )

    # Flatten cue words into (token, cue_index) so a multi-token cue still maps
    # its words back to the owning cue's start/end boundary.
    cue_tokens: list[tuple[str, int]] = []
    for cue_index, cue in enumerate(cues):
        for token in _cue_words(cue):
            cue_tokens.append((token, cue_index))

    if not cue_tokens:
        raise RuntimeError(
            "SubMaker contains no tokenizable words; cannot map scenes to TTS timing"
        )

    def _cue_total_seconds(cue, attr: str) -> float:
        value = getattr(cue, attr)
        # edge_tts Subtitle.start/end are datetime.timedelta.
        if hasattr(value, "total_seconds"):
            return value.total_seconds()
        # Tolerate numeric 100ns / seconds fallbacks from test doubles.
        return float(value)

    spans: list[dict] = []  # per-scene start_s / word_end_s (before gap-fill)
    cursor = 0  # shared search position advances per scene (handles repeats)

    for scene_index, scene in enumerate(video_scenes):
        narration = scene.get("narration", "")
        tokens = _tokenize(narration)
        if not tokens:
            raise RuntimeError(
                f"scene {scene_index} narration is empty; cannot map to TTS timing"
            )

        start_cue = end_cue = None
        j = cursor
        while j < len(cue_tokens):
            k = 0
            jj = j
            while k < len(tokens) and jj < len(cue_tokens) and cue_tokens[jj][0] == tokens[k]:
                k += 1
                jj += 1
            if k == len(tokens):
                start_cue = cue_tokens[j][1]
                end_cue = cue_tokens[jj - 1][1]
                cursor = jj
                break
            j += 1

        if start_cue is None:
            raise RuntimeError(
                f"scene {scene_index} narration cannot be mapped to a TTS word "
                f"span: {narration[:80]!r}"
            )

        spans.append(
            {
                "scene_index": scene_index,
                "start": _cue_total_seconds(cues[start_cue], "start"),
                "word_end": _cue_total_seconds(cues[end_cue], "end"),
            }
        )

    # Tile the timeline continuously. edge_tts emits inter-scene pauses
    # (sentence / paragraph boundaries) which produce NO word cues, so without
    # this each scene's word span would leave a silent gap -> sum(durations) <
    # audio_duration and the per-scene clips could not fill the audio without a
    # loop. By ending scene *i* at scene *i+1*'s start (the last scene extends to
    # the final cue end == the authoritative audio duration), the per-scene
    # intervals partition the full audio: sum(durations) == audio_duration, each
    # scene's narration still lies within its own interval, and no loop is
    # needed. Scene boundaries remain cue-start-derived (real TTS timing);
    # ``target_duration`` is still never used.
    last_end = _cue_total_seconds(cues[-1], "end")
    durations: list[dict] = []
    for i, span in enumerate(spans):
        end = spans[i + 1]["start"] if i + 1 < len(spans) else last_end
        durations.append(
            {
                "scene_index": span["scene_index"],
                "start": span["start"],
                "end": end,
                "duration": end - span["start"],
            }
        )

    return durations
