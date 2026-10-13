import json
from pathlib import Path

import pytest

from lib.studio_scenes import (
    DEFAULT_DURATION_SECONDS, SCENES_VERSION, SceneEntry, ScenePlan,
    load_scenes, quantize_items, save_plan, save_scenes, scenes_to_items,
)
from lib.studio_timeline import (
    FPS, TimelineItem, audio_frames, fit_to_audio, timeline_frames,
)


def media_file(tmp_path: Path, name: str = "clip.mp4") -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00")
    return path.resolve()


def write_plan(tmp_path: Path, data, name: str = "scenes.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def minimal_plan(tmp_path: Path, **scene_overrides) -> dict:
    media = media_file(tmp_path, "01-establishing.mp4")
    scene = {"id": "cena-01", "media": str(media), **scene_overrides}
    return {"version": SCENES_VERSION, "scenes": [scene]}


def test_load_applies_defaults_and_keeps_identity_fields(tmp_path):
    plan = load_scenes(write_plan(tmp_path, minimal_plan(tmp_path)))
    assert plan.version == SCENES_VERSION
    assert plan.title == ""
    assert plan.wav is None
    assert plan.metadata == {}
    entry = plan.scenes[0]
    assert entry.id == "cena-01"
    assert entry.media.is_file()
    assert entry.duration == DEFAULT_DURATION_SECONDS
    assert entry.transition == "cut"
    assert entry.transition_duration == 0.5
    assert entry.note == ""


def test_load_quantizes_durations_to_whole_frames(tmp_path):
    data = minimal_plan(tmp_path, duration_seconds=12.033, transition="crossfade", transition_duration=0.517)
    entry = load_scenes(write_plan(tmp_path, data)).scenes[0]
    assert entry.duration == 361 / FPS
    assert entry.transition_duration == 16 / FPS


def test_relative_media_and_wav_resolve_against_plan_directory(tmp_path):
    plans = tmp_path / "plans"
    plans.mkdir()
    media = media_file(tmp_path, "plans/footage/scene.mp4")
    data = {
        "version": SCENES_VERSION,
        "wav": "audio/mix.wav",
        "scenes": [{"id": "a", "media": "footage/scene.mp4"}],
    }
    plan = load_scenes(write_plan(plans, data))
    assert plan.scenes[0].media == media
    assert plan.wav == (plans / "audio" / "mix.wav").resolve()


def test_title_note_and_metadata_are_preserved(tmp_path):
    data = minimal_plan(tmp_path, note="Plano aberto ao amanhecer")
    data["title"] = "História do Teatro"
    data["metadata"] = {"generated_by": "manual"}
    plan = load_scenes(write_plan(tmp_path, data))
    assert plan.title == "História do Teatro"
    assert plan.metadata == {"generated_by": "manual"}
    assert plan.scenes[0].note == "Plano aberto ao amanhecer"


def test_scenes_to_items_preserves_order_paths_and_transitions(tmp_path):
    media_a = media_file(tmp_path, "a.mp4")
    media_b = media_file(tmp_path, "b.png")
    data = {
        "version": SCENES_VERSION,
        "scenes": [
            {"id": "a", "media": str(media_a), "duration_seconds": 4, "transition": "fade", "transition_duration": 0.5},
            {"id": "b", "media": str(media_b)},
        ],
    }
    items = scenes_to_items(load_scenes(write_plan(tmp_path, data)))
    assert [item.path for item in items] == [media_a.resolve(), media_b.resolve()]
    assert [item.frames for item in items] == [120, 150]
    assert [item.transition for item in items] == ["fade", "cut"]


@pytest.mark.parametrize("mutation,expected", [
    ({"version": "0.9"}, "Versão do plano não suportada"),
    ({"scenes": []}, "'scenes' precisa ser uma lista"),
    ({"scenes": "no"}, "'scenes' precisa ser uma lista"),
    ({"extra": 1}, "Chave desconhecida"),
    ({"title": 5}, "'title' precisa ser texto"),
    ({"metadata": []}, "'metadata' precisa ser um objeto"),
    ({"wav": ""}, "'wav' precisa ser"),
    ({"wav": 7}, "'wav' precisa ser"),
])
def test_invalid_plan_envelope_is_rejected(tmp_path, mutation, expected):
    data = minimal_plan(tmp_path)
    data.update(mutation)
    with pytest.raises(ValueError, match=expected):
        load_scenes(write_plan(tmp_path, data))


@pytest.mark.parametrize("scene_mutation,expected", [
    ({"id": ""}, "'id' precisa ser"),
    ({"media": 5}, "'media' precisa ser"),
    ({"media": str(Path("missing-file.mp4"))}, "arquivo de mídia não encontrado"),
    ({"duration_seconds": 0}, "maior que zero"),
    ({"duration_seconds": -2}, "maior que zero"),
    ({"duration_seconds": "10"}, "precisa ser um número"),
    ({"duration_seconds": True}, "precisa ser um número"),
    ({"duration_seconds": 0.01}, "mínimo é 1 quadro"),
    ({"transition": "wipe"}, "transição desconhecida"),
    ({"transition_duration": 0}, "maior que zero"),
    ({"note": 3}, "'note' precisa ser texto"),
    ({"narration": 3}, "'narration' precisa ser texto"),
    ({"surprise": 1}, "chave desconhecida"),
])
def test_invalid_scene_is_rejected_with_position_and_id(tmp_path, scene_mutation, expected):
    data = minimal_plan(tmp_path)
    data["scenes"][0].update(scene_mutation)
    with pytest.raises(ValueError, match=expected) as excinfo:
        load_scenes(write_plan(tmp_path, data))
    message = str(excinfo.value)
    assert message.startswith("Cena 1")
    if "id" not in scene_mutation:
        assert "(cena-01)" in message


def test_scene_must_be_an_object(tmp_path):
    data = minimal_plan(tmp_path)
    data["scenes"] = ["not-a-scene"]
    with pytest.raises(ValueError, match="Cena 1: precisa ser um objeto"):
        load_scenes(write_plan(tmp_path, data))


def test_duplicate_ids_are_rejected_at_the_second_scene(tmp_path):
    first = media_file(tmp_path, "a.mp4")
    second = media_file(tmp_path, "b.mp4")
    data = {
        "version": SCENES_VERSION,
        "scenes": [
            {"id": "repetida", "media": str(first)},
            {"id": "repetida", "media": str(second)},
        ],
    }
    with pytest.raises(ValueError, match="Cena 2 \\(repetida\\): id duplicado"):
        load_scenes(write_plan(tmp_path, data))


def test_validation_is_atomic_one_bad_scene_blocks_the_whole_plan(tmp_path):
    good = media_file(tmp_path, "good.mp4")
    data = {
        "version": SCENES_VERSION,
        "scenes": [
            {"id": "ok", "media": str(good)},
            {"id": "quebrada", "media": str(tmp_path / "ausente.mp4")},
        ],
    }
    with pytest.raises(ValueError, match="Cena 2 \\(quebrada\\)"):
        load_scenes(write_plan(tmp_path, data))


def test_invalid_json_and_non_object_documents_are_rejected(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{nope", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON inválido"):
        load_scenes(broken)
    list_path = tmp_path / "list.json"
    list_path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="objeto JSON"):
        load_scenes(list_path)


def test_sixty_scene_plan_fits_a_twenty_minute_wav_exactly(tmp_path):
    scenes = []
    for index in range(60):
        media = media_file(tmp_path, f"shots/{index:03d}.mp4")
        scenes.append({
            "id": f"cena-{index + 1:02d}",
            "media": str(media),
            "duration_seconds": 20,
            "transition": "crossfade" if index % 3 == 0 else "cut",
            "transition_duration": 0.5,
        })
    items = scenes_to_items(load_scenes(write_plan(tmp_path, {"version": SCENES_VERSION, "scenes": scenes})))
    assert len(items) == 60
    fitted = fit_to_audio(items, 1200.0)
    assert timeline_frames(fitted) == audio_frames(1200.0)
    assert 0 <= timeline_frames(fitted) / FPS - 1200.0 < 1 / FPS


def test_save_rejects_empty_timelines(tmp_path):
    with pytest.raises(ValueError, match="pelo menos uma imagem"):
        save_scenes(tmp_path / "scenes.json", [])


def test_save_then_load_round_trip_is_stable(tmp_path):
    media_a = media_file(tmp_path, "a.mp4")
    media_b = media_file(tmp_path, "b.png")
    items = [
        TimelineItem(media_a, 4.0, "crossfade", 0.5),
        TimelineItem(media_b, 7.777, "cut", 0.5),
    ]
    path = save_scenes(tmp_path / "plans" / "doc.json", items,
                       title="Documentário", wav=tmp_path / "mix.wav",
                       metadata={"generated_by": "manual"})
    plan = load_scenes(path)
    assert plan.title == "Documentário"
    assert plan.wav == (tmp_path / "mix.wav").resolve()
    assert plan.metadata == {"generated_by": "manual"}
    assert scenes_to_items(plan) == quantize_items(items)
    assert [entry.id for entry in plan.scenes] == ["cena-01", "cena-02"]


def test_saved_plan_is_schema_shaped_and_readable_as_utf8(tmp_path):
    media = media_file(tmp_path, "cena.mp4")
    path = save_scenes(tmp_path / "scenes.json", [TimelineItem(media, 2.0, "fade", 0.5)],
                       title="São João — edição")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == {"version", "title", "scenes"}
    assert data["version"] == SCENES_VERSION
    assert data["title"] == "São João — edição"
    scene = data["scenes"][0]
    assert set(scene) == {"id", "media", "duration_seconds", "transition", "transition_duration", "note"}
    assert scene["duration_seconds"] == pytest.approx(2.0)
    assert scene["transition"] == "fade"


def test_plan_dataclasses_are_constructible_directly():
    entry = SceneEntry(id="x", media=Path("a.mp4"), duration=1.0)
    plan = ScenePlan(scenes=(entry,), title="t")
    assert plan.version == SCENES_VERSION
    assert scenes_to_items(plan) == [TimelineItem(Path("a.mp4"), 1.0, "cut", 0.5)]


def test_planning_scene_without_media_is_valid_and_skipped_by_default(tmp_path):
    data = {
        "version": SCENES_VERSION,
        "scenes": [
            {"id": "planejada", "duration_seconds": 3, "note": "Planejar imagem", "narration": "Era uma vez."},
            {"id": "com-media", "media": str(media_file(tmp_path, "real.mp4")), "duration_seconds": 2},
        ],
    }
    plan = load_scenes(write_plan(tmp_path, data))
    assert plan.scenes[0].media is None
    assert plan.scenes[0].narration == "Era uma vez."
    assert plan.planning_count == 1
    items = scenes_to_items(plan)
    assert [item.path.name for item in items] == ["real.mp4"]


def test_include_planning_raises_for_media_less_scenes(tmp_path):
    plan = ScenePlan(scenes=(SceneEntry(id="p", media=None, duration=1.0),))
    with pytest.raises(ValueError, match="não tem 'media'"):
        scenes_to_items(plan, include_planning=True)


def test_save_plan_roundtrips_planning_scenes_without_inventing_media(tmp_path):
    plan = ScenePlan(
        scenes=(
            SceneEntry(id="cena-01", media=None, duration=4.0, transition="cut",
                       note="Planejar imagem/clipe para: …", narration="Abertura do documentário."),
            SceneEntry(id="cena-02", media=media_file(tmp_path, "ok.png"), duration=2.0,
                       transition="fade", narration="Meio."),
        ),
        title="Documentário",
        metadata={"generated_by": "unit-test"},
    )
    path = save_plan(tmp_path / "planning.json", plan)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "media" not in data["scenes"][0]
    assert data["scenes"][0]["narration"] == "Abertura do documentário."
    reloaded = load_scenes(path)
    assert reloaded.planning_count == 1
    assert scenes_to_items(reloaded) == [TimelineItem(plan.scenes[1].media, 2.0, "fade", 0.5)]
