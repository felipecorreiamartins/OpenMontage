from pathlib import Path

import pytest

from lib.studio_timeline import (
    FPS, TimelineItem, audio_frames, fit_to_audio, move_item,
    seconds_to_frames, timeline_frames,
)


def item(seconds=2, transition="cut", overlap=0.5):
    return TimelineItem(Path("image.png"), seconds, transition, overlap)


@pytest.mark.parametrize("seconds,frames", [("1,5", 45), (1 / 30, 1), ("0.033333", 1), (2.01, 60)])
def test_duration_is_quantized_to_whole_frames(seconds, frames):
    assert seconds_to_frames(seconds) == frames


@pytest.mark.parametrize("seconds", [0, -1, "no", "", None, "nan", "inf", 0.01])
def test_invalid_duration_is_rejected(seconds):
    with pytest.raises(ValueError):
        seconds_to_frames(seconds)


def test_overlaps_reduce_duration_and_last_transition_is_not_applied():
    items = [item(2, "crossfade"), item(3, "fade"), item(1, "fade", 99)]
    assert timeline_frames(items) == 150


def test_transition_must_leave_a_body_between_both_overlaps():
    with pytest.raises(ValueError, match="entrada e saída"):
        timeline_frames([item(2, "fade"), item(1, "fade"), item()])


@pytest.mark.parametrize("duration", [1.1, 3.775, 60.01, 1200.123])
def test_fit_preserves_order_sources_transitions_and_covers_entire_audio(duration):
    items = [item(2, "crossfade"), item(3, "fade"), item()]
    original = list(items)
    fitted = fit_to_audio(items, duration)
    assert items == original
    assert timeline_frames(fitted) == audio_frames(duration)
    assert 0 <= timeline_frames(fitted) / FPS - duration < 1 / FPS
    assert [(i.path, i.transition, i.transition_duration) for i in fitted] == [
        (i.path, i.transition, i.transition_duration) for i in original
    ]


def test_short_wav_and_empty_timeline_fail_clearly():
    with pytest.raises(ValueError, match="curto demais"):
        fit_to_audio([item(2, "fade"), item()], 0.1)
    with pytest.raises(ValueError, match="Adicione"):
        timeline_frames([])


def test_reordering_keeps_every_item_and_rejects_invalid_positions():
    items = [item(1), item(2), item(3)]
    original = list(items)
    assert move_item(items, 2, -1) == 1
    assert items == [original[0], original[2], original[1]]
    with pytest.raises(ValueError):
        move_item(items, 0, -1)


def test_fitting_is_stable_when_already_at_target():
    items = fit_to_audio([item(2, "fade"), item(3), item()], 3.775)
    assert fit_to_audio(items, 3.775) == items
    minimum_body = [item(1 / FPS), item(299 / FPS)]
    assert fit_to_audio(minimum_body, 10) == minimum_body
