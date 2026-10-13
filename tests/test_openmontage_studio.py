import json
import hashlib
from pathlib import Path

import pytest

from openmontage_studio import (
    MODE_IDS,
    duration_seconds,
    load_music_catalog,
    local_video_selection,
    mode_for_tab,
    pick_music,
)


def test_catalog_filters_missing_files_and_picks_mood_deterministically(tmp_path):
    available = tmp_path / "available.mp3"
    available.touch()
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps([
        {"nome": "Zulu", "arquivo": str(available), "humor": ["suspense"]},
        {"nome": "Alpha", "arquivo": str(available), "humor": ["suspense"]},
        {"nome": "Missing", "arquivo": str(tmp_path / "missing.mp3"), "humor": ["suspense"]},
    ]), encoding="utf-8")

    tracks = load_music_catalog(catalog)

    assert len(tracks) == 2
    assert pick_music(tracks, "SUSPENSE")["nome"] == "Alpha"
    assert pick_music(tracks, "ambient") is None


def test_catalog_rejects_non_list_json(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"track": "not a list"}), encoding="utf-8")
    try:
        load_music_catalog(catalog)
    except ValueError as exc:
        assert "lista JSON" in str(exc)
    else:
        raise AssertionError("non-list catalog should be rejected")


@pytest.mark.parametrize(
    "hours,minutes,seconds,expected",
    [("0", "8", "0", 480), ("1", "2", "3", 3723), ("", "", "5", 5)],
)
def test_custom_duration_accepts_hours_minutes_seconds(hours, minutes, seconds, expected):
    assert duration_seconds(hours, minutes, seconds) == expected


@pytest.mark.parametrize(
    "parts,message",
    [
        (("x", "0", "0"), "horas"),
        (("0", "60", "0"), "Minutos"),
        (("0", "0", "60"), "Segundos"),
        (("-1", "0", "0"), "negativos"),
        (("0", "0", "0"), "maior que zero"),
    ],
)
def test_custom_duration_rejects_invalid_values(parts, message):
    with pytest.raises(ValueError, match=message):
        duration_seconds(*parts)


def test_notebook_navigation_maps_each_tab_to_a_mode():
    assert tuple(mode_for_tab(index) for index in range(len(MODE_IDS))) == (
        "create", "edit", "custom"
    )
    with pytest.raises(ValueError, match="Aba de modo inválida"):
        mode_for_tab(-1)
    with pytest.raises(ValueError, match="Aba de modo inválida"):
        mode_for_tab(len(MODE_IDS))


def test_selecting_local_video_does_not_change_source_file(tmp_path):
    source = tmp_path / "original.mp4"
    original_bytes = b"raw user video bytes; selection must be read-only"
    source.write_bytes(original_bytes)
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    selected = local_video_selection(source)

    after = hashlib.sha256(source.read_bytes()).hexdigest()
    assert selected == source.resolve()
    assert before == after


def test_video_selection_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="Arquivo de vídeo não encontrado"):
        local_video_selection(tmp_path / "missing.mp4")
