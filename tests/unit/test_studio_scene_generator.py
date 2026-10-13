import json
import math
from pathlib import Path

import pytest

from lib.studio_scene_generator import (
    MIN_SCENE_SECONDS, generate_plan, generate_plan_file, split_narration_scenes, visual_note,
)
from lib.studio_scenes import SCENES_VERSION, load_scenes, scenes_to_items
from lib.studio_timeline import FPS, audio_frames

LONG_NARRATION = """
A catedral foi construída no século dezoito por artesãos esquecidos.

Suas abóbadas guardam séculos de silêncio e luz. Visitantes descem a nave em silêncio.

Cada pedra conta uma história de fé e trabalho. No altar, a madeira ainda respira o tempo.
O coro ressoa mesmo quando o silêncio volta. Ao anoitecer, as velas devolvem o calor.
"""


def test_split_rejects_empty_text():
    with pytest.raises(ValueError, match="texto da narração"):
        split_narration_scenes("   \n\n  ")


def test_split_groups_paragraphs_and_caps_sentences_per_scene():
    segments = split_narration_scenes(LONG_NARRATION)
    assert len(segments) >= 3
    assert all(segment.strip() for segment in segments)
    joined = " ".join(segments).replace("  ", " ")
    assert "catedral" in joined and "velas" in joined
    # Long source sentences may exceed the soft sentence pack; paragraphs stay intact.
    assert max(len(segment.split()) for segment in segments) <= 40


def test_visual_note_is_planning_hint_not_media():
    note = visual_note("Uma tomada aérea do rio ao amanhecer revela a cidade acordando.")
    assert note.startswith("Planejar imagem/clipe para:")
    assert "/" not in note.split("para:", 1)[1].split()[0]


def test_generate_plan_durations_are_proportional_and_cover_wav():
    wav_duration = 120.0
    plan = generate_plan(LONG_NARRATION, wav_duration, title="QA")
    assert plan.version == SCENES_VERSION
    assert plan.title == "QA"
    assert plan.metadata["planning_only"] is True
    assert plan.planning_count == len(plan.scenes)
    assert all(entry.media is None for entry in plan.scenes)
    assert all(entry.narration for entry in plan.scenes)
    assert all(entry.note.startswith("Planejar imagem/clipe para:") for entry in plan.scenes)
    assert scenes_to_items(plan) == []
    total = sum(entry.duration * FPS for entry in plan.scenes)
    assert abs(total - audio_frames(wav_duration)) <= len(plan.scenes)
    words = [len(entry.narration.split()) for entry in plan.scenes]
    longest = max(range(len(words)), key=lambda i: words[i])
    shortest = min(range(len(words)), key=lambda i: words[i])
    assert plan.scenes[longest].duration >= plan.scenes[shortest].duration


def test_generate_plan_respects_minimum_scene_duration():
    plan = generate_plan("Um. Dois. Três. Quatro. Cinco. Seis.", 20.0)
    assert all(entry.duration + 1e-9 >= MIN_SCENE_SECONDS for entry in plan.scenes)
    frames = [int(round(entry.duration * FPS)) for entry in plan.scenes]
    assert sum(frames) == audio_frames(20.0)


def test_generate_plan_rejects_bad_wav_duration():
    for bad in (0, -1, float("nan"), float("inf"), "3.5", True):
        with pytest.raises(ValueError):
            generate_plan(LONG_NARRATION, bad)


def test_generate_plan_rejects_wav_too_short_for_many_scenes():
    text = " ".join(f"Frase número {i} aqui." for i in range(80))
    with pytest.raises(ValueError, match="quadro"):
        generate_plan(text, 0.1)


def test_generate_plan_file_is_loadable_planning_only(tmp_path):
    destination = tmp_path / "plans" / "doc.json"
    path = generate_plan_file(LONG_NARRATION, 30.0, destination, title="Doc")
    assert path == destination.resolve()
    plan = load_scenes(path)
    assert plan.planning_count == len(plan.scenes)
    assert scenes_to_items(plan) == []
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == SCENES_VERSION
    assert data["metadata"]["generated_by"] == "studio_scene_generator"
    assert math.isfinite(plan.metadata["wav_duration_seconds"])
    assert plan.metadata["wav_duration_seconds"] == 30.0
