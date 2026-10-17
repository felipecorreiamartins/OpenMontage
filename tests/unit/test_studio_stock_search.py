from pathlib import Path

import pytest

from lib.studio_scenes import SceneEntry
from lib.studio_stock_search import (
    STOCK_SOURCE_NAMES,
    available_stock_source_names,
    build_search_input,
    normalize_kind,
    run_stock_search,
    scene_with_clip,
    stock_install_instructions,
    write_credits,
)


def test_stock_source_names_are_the_three_planned():
    assert STOCK_SOURCE_NAMES == ("pexels", "pixabay_video", "wikimedia")


def test_available_stock_source_names_filters_to_known_set(monkeypatch):
    class FakeSource:
        def __init__(self, name):
            self.name = name

    fake = [FakeSource("pexels"), FakeSource("unsplash"), FakeSource("wikimedia")]
    monkeypatch.setattr(
        "tools.video.stock_sources.available_sources",
        lambda: fake,
        raising=False,
    )
    names = available_stock_source_names()
    assert names == ["pexels", "wikimedia"]


def test_normalize_kind_accepts_three_values():
    assert normalize_kind("video") == "video"
    assert normalize_kind("image") == "image"
    assert normalize_kind("any") == "any"


def test_normalize_kind_rejects_bad_value():
    with pytest.raises(ValueError, match="kind inválido"):
        normalize_kind("audio")


def test_build_search_input_shapes_tool_payload(tmp_path):
    payload = build_search_input(
        query="sunset over mountains",
        output_dir=tmp_path,
        kind="image",
        sources=["pexels", "wikimedia"],
        clips_per_query=5,
        timeout_seconds=30.0,
        slot_id="cena-01",
    )
    assert payload["output_dir"] == str(tmp_path)
    assert payload["clips_per_query"] == 5
    assert payload["timeout_seconds"] == 30.0
    assert payload["sources"] == ["pexels", "wikimedia"]
    assert payload["queries"] == [
        {"query": "sunset over mountains", "kind": "image", "slot_id": "cena-01"}
    ]


def test_build_search_input_clamps_count_and_strips_query(tmp_path):
    payload = build_search_input(query="  pad  ", output_dir=tmp_path, clips_per_query=99)
    assert payload["queries"][0]["query"] == "pad"
    assert payload["clips_per_query"] == 20
    assert "slot_id" not in payload["queries"][0]


def test_build_search_input_rejects_empty_query(tmp_path):
    with pytest.raises(ValueError, match="query"):
        build_search_input(query="   ", output_dir=tmp_path)


def test_stock_install_instructions_mentions_pixabay_key():
    text = stock_install_instructions(["pexels", "pixabay_video", "wikimedia"])
    assert "PEXELS_API_KEY" in text
    assert "PIXABAY_API_KEY" in text
    assert "wikimedia" in text


def test_scene_with_clip_fills_media_and_provenance(tmp_path):
    media = tmp_path / "pexels_123.mp4"
    media.write_bytes(b"\x00")
    entry = SceneEntry(id="cena-01", duration=3.0, note="abertura")
    clip = {
        "path": str(media),
        "source": "pexels",
        "source_id": "123",
        "source_url": "https://www.pexels.com/photo/123/",
        "creator": "Joey Farina",
        "license": "Pexels License",
    }
    updated = scene_with_clip(entry, clip)
    assert updated.media == media
    assert updated.source == "pexels"
    assert updated.source_id == "123"
    assert updated.source_url == "https://www.pexels.com/photo/123/"
    assert updated.creator == "Joey Farina"
    assert updated.license == "Pexels License"
    assert updated.has_provenance is True
    assert updated.note == "abertura"
    assert updated.duration == 3.0


def test_scene_with_clip_requires_path():
    entry = SceneEntry(id="x", duration=1.0)
    with pytest.raises(ValueError, match="caminho"):
        scene_with_clip(entry, {"path": ""})


def test_write_credits_lists_only_provenance_scenes(tmp_path):
    s1 = SceneEntry(id="c1", duration=2.0, source="pexels", creator="A",
                    license="Pexels License", source_url="https://x/1")
    s2 = SceneEntry(id="c2", duration=2.0)
    dest = write_credits([s1, s2], tmp_path / "CREDITS.md")
    text = dest.read_text(encoding="utf-8")
    assert "c1" in text
    assert "pexels" in text
    assert "A" in text
    assert "Pexels License" in text
    assert "c2" not in text


def test_write_credits_empty_placeholder(tmp_path):
    dest = write_credits([SceneEntry(id="c1", duration=1.0)], tmp_path / "CREDITS.md")
    assert "Nenhuma mídia stock" in dest.read_text(encoding="utf-8")


def test_run_stock_search_failure_returns_ok_false(monkeypatch):
    class FakeResult:
        success = False
        error = "No stock sources available."
        data = None

    class FakeTool:
        def execute(self, inputs):
            return FakeResult()

    monkeypatch.setattr(
        "tools.video.direct_clip_search.DirectClipSearch",
        FakeTool,
        raising=False,
    )
    summary = run_stock_search({"output_dir": ".", "queries": [{"query": "x"}]})
    assert summary["ok"] is False
    assert "No stock sources" in summary["error"]
    assert summary["clips"] == []


def test_run_stock_search_success_passthrough(monkeypatch):
    class FakeResult:
        success = True
        error = ""
        data = {
            "clips": [{"path": "a.mp4", "source": "pexels"}],
            "errors": [],
            "timed_out": False,
            "resolved_sources": ["pexels"],
        }

    class FakeTool:
        def execute(self, inputs):
            return FakeResult()

    monkeypatch.setattr(
        "tools.video.direct_clip_search.DirectClipSearch",
        FakeTool,
        raising=False,
    )
    summary = run_stock_search({"output_dir": ".", "queries": [{"query": "x"}]})
    assert summary["ok"] is True
    assert summary["clips"] == [{"path": "a.mp4", "source": "pexels"}]
    assert summary["resolved_sources"] == ["pexels"]


def test_run_stock_search_preserves_partial_results_on_timeout(monkeypatch):
    from tools.base_tool import ToolResult

    clip = {"path": "downloaded.mp4", "source": "pexels"}
    monkeypatch.setattr("tools.video.direct_clip_search.DirectClipSearch.execute",
                        lambda _self, inputs: ToolResult(
                            success=False, error="Download timed out", data={
                                "timed_out": True, "clips": [clip],
                                "errors": [{"error": "slow source"}], "resolved_sources": ["pexels"],
                            }))
    summary = run_stock_search({})
    assert summary["ok"] is False
    assert summary["timed_out"] is True
    assert summary["error"] == "Download timed out"
    assert summary["clips"] == [clip]
    assert summary["errors"] == [{"error": "slow source"}]
    assert summary["resolved_sources"] == ["pexels"]


@pytest.mark.parametrize("media", [None, "missing.mp4", "directory.mp4", "audio.wav"])
def test_scene_with_clip_rejects_invalid_media(tmp_path, media):
    entry = SceneEntry(id="cena-01", duration=2.0)
    path = tmp_path / media if media else None
    if media == "directory.mp4":
        path.mkdir()
    elif media == "audio.wav":
        path.write_bytes(b"approved audio remains unchanged")
    with pytest.raises(ValueError):
        scene_with_clip(entry, {"path": str(path) if path else None})
    assert entry.media is None
    if media == "audio.wav":
        assert path.read_bytes() == b"approved audio remains unchanged"
