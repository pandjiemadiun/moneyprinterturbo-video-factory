"""Phase 7B — P1 scene-duration primitive: SubMaker word-span alignment.

edge_tts is configured with boundary="WordBoundary" (see
``voice.create_edge_tts_communicate``), so ``sub_maker.cues`` are per-WORD
``Subtitle(content, start, end)`` objects. We map each ``ScenePlan.narration``
to an ordered, contiguous word-span (advancing the search position per scene
so repeated word sequences map to the correct occurrence) and derive
(scene_index, start, end, duration) from ACTUAL TTS timing — never word count,
never target_duration, never SRT-cue count.
"""
import re
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from app.services.scene_durations import compute_scene_durations


class _Cue:
    """Minimal stand-in for edge_tts Subtitle (per-word cue)."""

    def __init__(self, content, start, end):
        self.content = content
        self.start = timedelta(seconds=start)
        self.end = timedelta(seconds=end)


class _SubMaker:
    def __init__(self, cues):
        self.cues = cues


def _cues_from_words(words, per_word_duration=1.0, base=0.0):
    cues = []
    t = base
    for w in words:
        cues.append(_Cue(w, t, t + per_word_duration))
        t += per_word_duration
    return cues


# --- normal / punctuation ---------------------------------------------------

def test_basic_word_span_mapping():
    scenes = [
        {"narration": "Berikut panduan", "visual_query": "x"},
        {"narration": "Satu dua tiga", "visual_query": "y"},
    ]
    cues = _cues_from_words(["Berikut", "panduan", "Satu", "dua", "tiga"])
    spans = compute_scene_durations(scenes, _SubMaker(cues))
    assert len(spans) == 2
    assert spans[0] == {"scene_index": 0, "start": 0.0, "end": 2.0, "duration": 2.0}
    assert spans[1] == {"scene_index": 1, "start": 2.0, "end": 5.0, "duration": 3.0}


def test_commas_and_periods():
    # punctuation must not break the contiguous word match
    scenes = [{"narration": "Satu, dua, dan tiga.", "visual_query": "x"}]
    cues = _cues_from_words(["Satu", "dua", "dan", "tiga"])
    spans = compute_scene_durations(scenes, _SubMaker(cues))
    assert spans[0]["start"] == 0.0
    assert spans[0]["end"] == 4.0


def test_apostrophes():
    scenes = [{"narration": "Anda's uang harus aman", "visual_query": "x"}]
    # edge_tts emits "Anda's" as one word cue -> tokenizes to anda,s ; must still match
    cues = _cues_from_words(["Anda's", "uang", "harus", "aman"])
    spans = compute_scene_durations(scenes, _SubMaker(cues))
    assert spans[0]["duration"] == 4.0


def test_numbers_in_text():
    scenes = [{"narration": "aturan 50/30/20 penting", "visual_query": "x"}]
    cues = _cues_from_words(["aturan", "50/30/20", "penting"])
    spans = compute_scene_durations(scenes, _SubMaker(cues))
    assert spans[0]["start"] == 0.0
    assert spans[0]["end"] == 3.0


def test_indonesian_words_match():
    scenes = [{"narration": "Kami harus melunasi hutang dengan disiplin", "visual_query": "x"}]
    cues = _cues_from_words(["Kami", "harus", "melunasi", "hutang", "dengan", "disiplin"])
    spans = compute_scene_durations(scenes, _SubMaker(cues))
    assert spans[0]["duration"] == 6.0


def test_repeated_word_sequences_map_to_distinct_occurrences():
    scenes = [
        {"narration": "hutang bayar hutang", "visual_query": "x"},
        {"narration": "hutang selesai", "visual_query": "y"},
    ]
    cues = _cues_from_words(
        ["hutang", "bayar", "hutang", "hutang", "selesai"]
    )
    spans = compute_scene_durations(scenes, _SubMaker(cues))
    # scene 0 -> cues 0..2 ; scene 1 -> cues 3..4 (NOT re-mapped to scene 0's words)
    assert spans[0]["start"] == 0.0
    assert spans[0]["end"] == 3.0
    assert spans[1]["start"] == 3.0
    assert spans[1]["end"] == 5.0


def test_repeated_full_scene_narration():
    scenes = [
        {"narration": "hutang bayar", "visual_query": "x"},
        {"narration": "hutang bayar", "visual_query": "y"},
    ]
    cues = _cues_from_words(["hutang", "bayar", "hutang", "bayar"])
    spans = compute_scene_durations(scenes, _SubMaker(cues))
    assert spans[0]["start"] == 0.0 and spans[0]["end"] == 2.0
    assert spans[1]["start"] == 2.0 and spans[1]["end"] == 4.0


def test_whitespace_normalization():
    scenes = [{"narration": "  hutang    bayar  ", "visual_query": "x"}]
    cues = _cues_from_words(["hutang", "bayar"])
    spans = compute_scene_durations(scenes, _SubMaker(cues))
    assert spans[0]["duration"] == 2.0


# --- error / stop conditions ---

def test_empty_narration_raises():
    scenes = [{"narration": "", "visual_query": "x"}]
    cues = _cues_from_words(["a"])
    with pytest.raises(RuntimeError):
        compute_scene_durations(scenes, _SubMaker(cues))


def test_unmappable_scene_raises():
    scenes = [{"narration": "kata yang tidak ada di audio", "visual_query": "x"}]
    cues = _cues_from_words(["hutang", "bayar"])
    with pytest.raises(RuntimeError):
        compute_scene_durations(scenes, _SubMaker(cues))


def test_none_sub_maker_raises():
    with pytest.raises(RuntimeError):
        compute_scene_durations([{"narration": "x", "visual_query": "y"}], None)


def test_empty_cues_raises():
    scenes = [{"narration": "x", "visual_query": "y"}]
    with pytest.raises(RuntimeError):
        compute_scene_durations(scenes, _SubMaker([]))


def test_scene_index_is_sequential():
    scenes = [
        {"narration": "a b", "visual_query": "x"},
        {"narration": "c d", "visual_query": "y"},
        {"narration": "e f", "visual_query": "z"},
    ]
    cues = _cues_from_words(["a", "b", "c", "d", "e", "f"])
    spans = compute_scene_durations(scenes, _SubMaker(cues))
    assert [s["scene_index"] for s in spans] == [0, 1, 2]


# --- inter-scene pause / gap tiling ---------------------------------------
#
# edge_tts emits sentence/paragraph pauses between scenes as SILENCE, which
# produces no word cues. Without gap-filling the scene word-spans would leave
# silent holes -> sum(durations) < audio_duration and the per-scene clips
# could not cover the audio without a loop. The primitive fills each scene's
# end up to the next scene's start (the last scene to the final cue end) so the
# intervals partition the whole audio.


def test_inter_scene_silence_gaps_are_tiled_continuously():
    scenes = [
        {"narration": "a b", "visual_query": "x"},
        {"narration": "c d", "visual_query": "y"},
    ]
    # a,b at 0-2s ; SILENCE gap 2-4s (no cues) ; c,d at 4-6s. Audio ends at 6s.
    cues = [
        _Cue("a", 0.0, 1.0),
        _Cue("b", 1.0, 2.0),
        _Cue("c", 4.0, 5.0),
        _Cue("d", 5.0, 6.0),
    ]
    spans = compute_scene_durations(scenes, _SubMaker(cues))
    # scene 0's word span ends at 2.0 but its interval must extend to the next
    # scene's start (4.0) so it absorbs the silent pause.
    assert spans[0] == {"scene_index": 0, "start": 0.0, "end": 4.0, "duration": 4.0}
    # last scene extends to the final cue end == authoritative audio duration.
    assert spans[1] == {"scene_index": 1, "start": 4.0, "end": 6.0, "duration": 2.0}
    assert sum(s["duration"] for s in spans) == 6.0


def test_sum_of_durations_equals_audio_end_with_gaps():
    scenes = [
        {"narration": "a b", "visual_query": "x"},
        {"narration": "c d", "visual_query": "y"},
        {"narration": "e f", "visual_query": "z"},
    ]
    # a,b at 0-2 ; [gap] ; c,d at 3-5 ; [gap] ; e,f at 6-8. Audio ends at 8s.
    cues = [
        _Cue("a", 0.0, 1.0),
        _Cue("b", 1.0, 2.0),
        _Cue("c", 3.0, 4.0),
        _Cue("d", 4.0, 5.0),
        _Cue("e", 6.0, 7.0),
        _Cue("f", 7.0, 8.0),
    ]
    spans = compute_scene_durations(scenes, _SubMaker(cues))
    assert [s["start"] for s in spans] == [0.0, 3.0, 6.0]
    assert [s["end"] for s in spans] == [3.0, 6.0, 8.0]
    assert sum(s["duration"] for s in spans) == 8.0  # == audio_duration

