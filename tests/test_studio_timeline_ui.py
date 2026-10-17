"""Exercise actual Tk widgets and worker-to-UI communication without paid calls."""
import json
import time
from pathlib import Path
import tkinter as tk

import pytest

from lib import studio_timeline_ui as ui
from lib.studio_scene_generator import generate_plan_file
from lib.studio_scenes import load_scenes, scenes_to_items
from lib.studio_timeline import APPROVED_WAV, TimelineItem, timeline_frames
from openmontage_studio import OpenMontageStudio
from tools.base_tool import ToolResult


@pytest.fixture
def studio(monkeypatch, tmp_path):
    monkeypatch.setattr(OpenMontageStudio, "_refresh_catalog", lambda _self: None)
    monkeypatch.setattr("openmontage_studio.ROOT", tmp_path)
    app = OpenMontageStudio()
    app.withdraw()
    errors = []
    monkeypatch.setattr(ui.messagebox, "showerror", lambda *args, **kwargs: errors.append(args))
    app.update()
    yield app, errors
    if app.winfo_exists():
        if app.timeline_editor is not None and app.timeline_editor.winfo_exists():
            app.timeline_editor.destroy()
        # Cancel registered timers before tearing down Tk between tests.
        for timer in app.tk.call("after", "info"):
            app.after_cancel(timer)
        app.destroy()


def settle(app, editor):
    deadline = time.monotonic() + 5
    while editor.busy and time.monotonic() < deadline:
        app.update()
        time.sleep(0.01)
    app.update()
    assert not editor.busy, "background operation did not return to the UI"


def test_modes_share_editor_and_closing_it_preserves_timeline(studio, tmp_path):
    app, errors = studio
    source = tmp_path / "original.mp4"
    source.write_bytes(b"source selection only")
    app.notebook.select(1)
    app.update()
    assert app.current_mode == "edit"
    app.source_video.set(str(source))
    app._add_source_to_timeline()
    editor = app.timeline_editor
    editor.withdraw()
    assert editor.wav_path.get() == str(APPROVED_WAV)
    assert editor.items[0].path == source
    editor.request_close()
    app.notebook.select(2)
    app.update()
    assert app.current_mode == "custom"
    assert app._open_timeline() is editor
    assert len(editor.items) == 1 and source.read_bytes() == b"source selection only"
    assert not errors


def test_edit_reorder_remove_and_roundtrip_one_frame(studio, tmp_path):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    paths = [tmp_path / name for name in ("a.png", "b.mp4")]
    for path in paths:
        path.touch()
    editor.add_paths(paths)
    editor.move_selected(-1)
    assert [i.path for i in editor.items] == paths[::-1]
    editor.item_duration.set("1,5")
    editor.transition.set("Crossfade")
    editor.transition_duration.set("0,2")
    editor.apply_selected()
    assert editor.items[0].frames == 45 and editor.items[0].transition == "crossfade"
    editor.remove_selected()
    assert len(editor.items) == 1
    editor.items = [TimelineItem(paths[0], 1 / 30)]
    editor._refresh(0)
    editor.apply_selected()
    assert editor.items[0].frames == 1
    assert not errors


def test_adjust_worker_updates_widgets_and_restores_controls(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.items = [TimelineItem(tmp_path / "image.png", 5)]
    monkeypatch.setattr(ui, "wav_duration", lambda _path: 3.775)
    editor.adjust_to_wav()
    assert editor.busy and editor.export_button.instate(["disabled"])
    settle(app, editor)
    assert timeline_frames(editor.items) == 114
    assert "3.775" in editor.wav_info.get()
    assert editor.export_button.instate(["!disabled"])
    assert not errors


@pytest.mark.parametrize("outcome", ["success", "error", "cancelled"])
def test_export_worker_results_reach_ui(studio, tmp_path, monkeypatch, outcome):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.items = [TimelineItem(tmp_path / "image.png")]
    destination = tmp_path / "new.mp4"
    monkeypatch.setattr(ui.filedialog, "asksaveasfilename", lambda **kwargs: str(destination))
    def execute(_self, inputs, *, progress, cancel):
        assert inputs["wav_path"] == str(APPROVED_WAV)
        progress(0.5, "Testing progress")
        if outcome == "success":
            return ToolResult(True, data={"output": str(destination)})
        return ToolResult(False, data={"cancelled": outcome == "cancelled"}, error=outcome)
    monkeypatch.setattr(ui.StudioExport, "execute", execute)
    editor.export()
    settle(app, editor)
    assert editor.export_button.instate(["!disabled"])
    if outcome == "success":
        assert editor.last_output == destination and editor.open_button.instate(["!disabled"])
    else:
        assert editor.last_output is None and outcome in editor.status.get()
    assert bool(errors) == (outcome == "error")


def test_existing_output_and_empty_timeline_are_rejected_in_ui(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.export()
    editor.adjust_to_wav()
    editor.items = [TimelineItem(tmp_path / "image.png")]
    destination = tmp_path / "existing.mp4"
    destination.write_bytes(b"preserve")
    monkeypatch.setattr(ui.filedialog, "asksaveasfilename", lambda **kwargs: str(destination))
    editor.export()
    assert len(errors) == 3 and not editor.busy
    assert destination.read_bytes() == b"preserve"


def test_closing_during_work_cancels_and_can_reopen(studio, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    def worker():
        assert editor.cancel_event.wait(3)
        return "cancelled", "Cancelled"
    editor._start(worker)
    editor.request_close()
    settle(app, editor)
    assert not editor.closing and editor.state() == "withdrawn"
    assert app._open_timeline() is editor
    # The polling loop must survive close/reopen.
    editor._start(lambda: ("cancelled", "second operation"))
    settle(app, editor)
    assert editor.status.get() == "second operation" and not errors


def write_plan_file(tmp_path, media_paths, name="scenes.json", wav=None, **extra):
    data = {
        "version": "1.0",
        "scenes": [
            {"id": f"cena-{i + 1:02d}", "media": str(path), "duration_seconds": 2.0}
            for i, path in enumerate(media_paths)
        ],
    }
    if wav is not None:
        data["wav"] = str(wav)
    data.update(extra)
    path = tmp_path / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_import_plan_replaces_timeline_after_confirmation(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    old = tmp_path / "old.png"
    old.touch()
    editor.items = [TimelineItem(old, 3.0)]
    media = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    for path in media:
        path.touch()
    plan_path = write_plan_file(tmp_path, media)
    monkeypatch.setattr(ui.filedialog, "askopenfilename", lambda **kwargs: str(plan_path))
    monkeypatch.setattr(ui.messagebox, "askyesno", lambda *args, **kwargs: True)
    monkeypatch.setattr(ui, "wav_duration", lambda _path: 4.0)
    editor.import_plan()
    settle(app, editor)
    assert not errors
    assert [item.path for item in editor.items] == [p.resolve() for p in media]
    assert editor.wav_path.get() == str(APPROVED_WAV)
    assert timeline_frames(editor.items) == 120


def test_import_plan_declining_replace_keeps_existing_timeline(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    old = tmp_path / "old.png"
    old.touch()
    editor.items = [TimelineItem(old, 3.0)]
    media = tmp_path / "new.mp4"
    media.touch()
    plan_path = write_plan_file(tmp_path, [media])
    monkeypatch.setattr(ui.filedialog, "askopenfilename", lambda **kwargs: str(plan_path))
    monkeypatch.setattr(ui.messagebox, "askyesno", lambda *args, **kwargs: False)
    editor.import_plan()
    assert not editor.busy and not errors
    assert editor.items == [TimelineItem(old, 3.0)]
    assert "cancelada" in editor.status.get()


def test_import_plan_with_plan_wav_requires_confirmation(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    media = tmp_path / "scene.mp4"
    media.touch()
    other_wav = tmp_path / "another.wav"
    other_wav.write_bytes(b"RIFF")
    plan_path = write_plan_file(tmp_path, [media], wav=other_wav)
    prompts = []

    def confirm(*args, **kwargs):
        prompts.append(args[0] if args else kwargs.get("message", ""))
        return False

    monkeypatch.setattr(ui.filedialog, "askopenfilename", lambda **kwargs: str(plan_path))
    monkeypatch.setattr(ui.messagebox, "askyesno", confirm)
    monkeypatch.setattr(ui, "wav_duration", lambda _path: 2.0)
    editor.import_plan()
    settle(app, editor)
    assert not errors
    assert any("Trocar WAV" in prompt for prompt in prompts)
    assert editor.wav_path.get() == str(APPROVED_WAV)
    assert len(editor.items) == 1


def test_import_invalid_plan_reports_error_and_preserves_timeline(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    keep = tmp_path / "keep.png"
    keep.touch()
    editor.items = [TimelineItem(keep, 1.0)]
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"version": "1.0", "scenes": []}), encoding="utf-8")
    monkeypatch.setattr(ui.filedialog, "askopenfilename", lambda **kwargs: str(broken))
    editor.import_plan()
    assert editor.items == [TimelineItem(keep, 1.0)]
    assert errors and "lista" in errors[0][1]


def test_export_plan_writes_roundtrippable_scenes_json(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    media = [tmp_path / "x.png", tmp_path / "y.mp4"]
    for path in media:
        path.touch()
    editor.items = [TimelineItem(p.resolve(), 2.0, "crossfade", 0.5) for p in media]
    destination = tmp_path / "plans" / "doc.json"
    monkeypatch.setattr(ui.filedialog, "asksaveasfilename", lambda **kwargs: str(destination))
    editor.export_plan()
    assert not errors and destination.is_file()
    plan = load_scenes(destination)
    assert scenes_to_items(plan) == editor.items
    assert plan.wav == Path(editor.wav_path.get()).resolve()
    assert plan.metadata["generated_by"] == "OpenMontage Studio"
    assert str(destination.resolve()) in editor.status.get()


def test_export_plan_empty_timeline_is_rejected(studio, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    monkeypatch.setattr(ui.filedialog, "asksaveasfilename", lambda **kwargs: pytest.fail("no dialog expected"))
    editor.export_plan()
    assert errors and "Timeline vazia" in errors[0][0]


def test_generate_plan_from_narration_writes_planning_only_file(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.plans_dir = tmp_path / "plans"
    infos = []
    monkeypatch.setattr(ui.messagebox, "showinfo", lambda *args, **kwargs: infos.append(args))
    editor.generate_plan(
        "A catedral foi construída no século dezoito.\n\n"
        "Suas abóbadas guardam séculos de silêncio e luz.\n\n"
        "Ao anoitecer, as velas devolvem o calor."
    )
    assert editor.busy
    settle(app, editor)
    assert not errors
    assert editor.last_plan is not None and editor.last_plan.is_file()
    assert editor.last_plan == (tmp_path / "plans" / "scenes.json").resolve()
    assert editor.last_plan.name == "scenes.json"
    plan = load_scenes(editor.last_plan)
    assert plan.planning_count == len(plan.scenes) >= 3
    assert all(entry.media is None for entry in plan.scenes)
    assert scenes_to_items(plan) == []
    assert "Plano gerado" in editor.status.get()
    assert "media" in editor.status.get()
    assert str(editor.last_plan) in editor.status.get()
    assert infos, "expected a confirmation dialog after generation"
    assert str(editor.last_plan) in infos[0][1]
    assert "Importar plano" in infos[0][1]
    assert editor.current_plan_path == editor.last_plan


def test_import_plan_dialog_opens_in_plans_dir(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.plans_dir = tmp_path / "plans"
    seen = []
    monkeypatch.setattr(ui.filedialog, "askopenfilename",
                        lambda **kwargs: seen.append(kwargs) or "")
    editor.import_plan()
    assert seen and seen[0]["initialdir"] == str(tmp_path / "plans")
    plan_path = tmp_path / "elsewhere" / "scenes.json"
    editor.current_plan_path = plan_path
    editor.import_plan()
    assert seen[-1]["initialdir"] == str(plan_path.parent)
    assert not errors


def test_import_planning_only_plan_does_not_touch_timeline(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    keep = tmp_path / "keep.png"
    keep.touch()
    editor.items = [TimelineItem(keep, 1.0)]
    plan_path = generate_plan_file(
        "Primeira parte do documentário. Segunda parte com mais detalhes. Terceira parte finaliza.",
        30.0, tmp_path / "planning.json")
    monkeypatch.setattr(ui.filedialog, "askopenfilename", lambda **kwargs: str(plan_path))
    editor.import_plan()
    assert editor.items == [TimelineItem(keep, 1.0)]
    assert errors and "planejamento" in errors[0][1].lower()
    assert Path(editor.wav_path.get()).resolve() == APPROVED_WAV.resolve()


def _make_planning_plan(tmp_path, count=2):
    scenes = [
        {"id": f"cena-{i + 1:02d}", "duration_seconds": 2.0,
         "note": f"Planejar mídia {i + 1}", "narration": f"Narração {i + 1}."}
        for i in range(count)
    ]
    path = tmp_path / "planning-stock.json"
    path.write_text(json.dumps({"version": "1.0", "scenes": scenes}, ensure_ascii=False), encoding="utf-8")
    return path


def test_open_stock_search_without_plan_shows_info(studio, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    infos = []
    monkeypatch.setattr(ui.messagebox, "showinfo", lambda *a, **k: infos.append(a))
    monkeypatch.setattr(ui.filedialog, "askopenfilename", lambda **k: pytest.fail("no dialog expected"))
    editor.open_stock_search()
    assert not editor.busy
    assert infos and "Plano necessário" in infos[0][0]


def test_open_stock_search_with_no_sources_shows_error(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    plan_path = _make_planning_plan(tmp_path)
    editor.current_plan = load_scenes(plan_path)
    editor.current_plan_path = plan_path
    monkeypatch.setattr(ui, "available_stock_source_names", lambda: [])
    editor.open_stock_search()
    assert not editor.busy
    assert errors and "nenhuma fonte" in errors[0][0].lower()


def test_search_stock_with_mocked_tool_opens_results(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.output_dir = tmp_path
    plan_path = _make_planning_plan(tmp_path)
    editor.current_plan = load_scenes(plan_path)
    editor.current_plan_path = plan_path
    clip_path = tmp_path / "stock" / "pexels_1.mp4"
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    clip_path.write_bytes(b"\x00" * 2048)
    fake_summary = {
        "ok": True,
        "error": "",
        "clips": [{
            "path": str(clip_path), "source": "pexels", "source_id": "1",
            "source_url": "https://x/1", "creator": "A. Photographer",
            "license": "Pexels License", "kind": "video",
        }],
        "errors": [],
        "timed_out": False,
    }
    monkeypatch.setattr(ui, "available_stock_source_names", lambda: ["pexels"])
    monkeypatch.setattr(ui, "run_stock_search", lambda inputs: fake_summary)
    shown = []
    monkeypatch.setattr(ui.TimelineEditor, "_show_stock_results",
                        lambda self, scene_id, summary: shown.append((scene_id, summary)))
    editor.search_stock("cena-01", "sunset", "video", 3, ["pexels"])
    assert editor.busy
    settle(app, editor)
    assert shown and shown[0][0] == "cena-01"
    assert shown[0][1]["clips"][0]["source"] == "pexels"
    assert not errors


def test_search_stock_cancel_returns_cancelled(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    monkeypatch.setattr(ui, "available_stock_source_names", lambda: ["pexels"])
    monkeypatch.setattr(ui, "run_stock_search", lambda inputs: {"ok": True, "clips": [], "errors": []})

    def worker():
        editor.cancel_event.set()
        return "cancelled", "Busca stock cancelada."

    editor._start(worker)
    editor.search_stock("cena-01", "x", "video", 3, ["pexels"])
    settle(app, editor)
    assert "cancelada" in editor.status.get() or not editor.busy


def test_apply_clip_to_scene_fills_provenance_and_writes_credits(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.output_dir = tmp_path
    plan_path = _make_planning_plan(tmp_path, count=1)
    editor.current_plan = load_scenes(plan_path)
    editor.current_plan_path = plan_path
    clip_path = tmp_path / "stock" / "pexels_99.mp4"
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    clip_path.write_bytes(b"\x00" * 2048)
    clip = {
        "path": str(clip_path), "source": "pexels", "source_id": "99",
        "source_url": "https://www.pexels.com/photo/99/",
        "creator": "Joey Farina", "license": "Pexels License", "kind": "video",
    }
    editor._apply_clip_to_scene("cena-01", clip)
    assert not editor.busy and not errors
    reloaded = load_scenes(plan_path)
    entry = reloaded.scenes[0]
    assert entry.media == clip_path.resolve()
    assert entry.source == "pexels"
    assert entry.source_id == "99"
    assert entry.creator == "Joey Farina"
    assert entry.license == "Pexels License"
    assert entry.has_provenance is True
    credits = plan_path.parent / "CREDITS.md"
    assert credits.is_file()
    text = credits.read_text(encoding="utf-8")
    assert "pexels" in text and "Joey Farina" in text
    assert "cena-01" in text


def test_apply_clip_preserves_approved_wav_hash(studio, tmp_path):
    import hashlib
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    before = hashlib.sha256(APPROVED_WAV.read_bytes()).hexdigest()
    plan_path = _make_planning_plan(tmp_path, count=1)
    editor.current_plan = load_scenes(plan_path)
    editor.current_plan_path = plan_path
    clip_path = tmp_path / "stock" / "wm_1.jpg"
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    clip_path.write_bytes(b"\x00" * 2048)
    editor._apply_clip_to_scene("cena-01", {
        "path": str(clip_path), "source": "wikimedia", "source_id": "1",
        "source_url": "", "creator": "Someone", "license": "CC BY-SA 4.0", "kind": "image",
    })
    after = hashlib.sha256(APPROVED_WAV.read_bytes()).hexdigest()
    assert before == after


def test_apply_clip_unknown_scene_reports_error(studio, tmp_path):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    plan_path = _make_planning_plan(tmp_path, count=1)
    editor.current_plan = load_scenes(plan_path)
    editor.current_plan_path = plan_path
    clip_path = tmp_path / "x.mp4"
    clip_path.write_bytes(b"\x00" * 2048)
    editor._apply_clip_to_scene("cena-99", {"path": str(clip_path), "source": "pexels"})
    assert errors and "não existe" in errors[0][1]


def test_show_stock_results_empty_clips_shows_info(studio, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    infos = []
    monkeypatch.setattr(ui.messagebox, "showinfo", lambda *a, **k: infos.append(a))
    editor._show_stock_results("cena-01", {"ok": True, "clips": [], "errors": [], "timed_out": False})
    assert infos and "Sem resultados" in infos[0][0]


def test_search_stock_builds_stock_subdir_and_passes_cancel(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.output_dir = tmp_path
    captured = {}

    def fake_run(inputs):
        captured.update(inputs)
        return {"ok": True, "clips": [], "errors": [], "timed_out": False}

    monkeypatch.setattr(ui, "available_stock_source_names", lambda: ["pexels", "wikimedia"])
    monkeypatch.setattr(ui, "run_stock_search", fake_run)
    monkeypatch.setattr(ui.TimelineEditor, "_show_stock_results", lambda *a: None)
    editor.search_stock("cena-01", "praia", "image", 5, ["pexels", "wikimedia"])
    settle(app, editor)
    assert str(tmp_path / "stock") in captured["output_dir"]
    assert captured["clips_per_query"] == 5
    assert captured["queries"][0]["kind"] == "image"
    assert captured["sources"] == ["pexels", "wikimedia"]


def _find_toplevel(parent, title):
    for child in parent.winfo_children():
        if isinstance(child, tk.Toplevel) and child.title() == title:
            return child
    return None


def _widgets(parent, widget_type):
    for child in parent.winfo_children():
        if isinstance(child, widget_type):
            yield child
        yield from _widgets(child, widget_type)


@pytest.mark.parametrize("action", ["Usar nesta cena", "Adicionar à timeline"])
def test_stock_result_buttons_use_selected_clip(studio, tmp_path, action):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    plan_path = _make_planning_plan(tmp_path)
    editor.current_plan = load_scenes(plan_path)
    editor.current_plan_path = plan_path
    clips = []
    for index in range(2):
        path = tmp_path / f"stock-{index}.mp4"
        path.write_bytes(b"selected media")
        clips.append({"path": str(path), "source": "pexels", "source_id": str(index),
                      "creator": f"Creator {index}", "license": "Pexels License", "kind": "video"})
    editor._show_stock_results("cena-02", {"ok": True, "clips": clips})
    dialog = _find_toplevel(editor, "Resultados stock — cena-02")
    tree = next(_widgets(dialog, ui.ttk.Treeview))
    assert tree.selection() == (tree.get_children()[0],)
    tree.selection_set(tree.get_children()[1])
    next(button for button in _widgets(dialog, ui.ttk.Button) if button.cget("text") == action).invoke()
    assert not errors
    assert not dialog.winfo_exists()
    if action == "Usar nesta cena":
        plan = load_scenes(plan_path)
        assert plan.scenes[0].media is None
        assert plan.scenes[1].media == Path(clips[1]["path"])
        assert plan.scenes[1].source_id == "1"
        assert "Creator 1" in (tmp_path / "CREDITS.md").read_text(encoding="utf-8")
        assert editor.items == []
    else:
        assert [item.path for item in editor.items] == [Path(clips[1]["path"])]
        assert load_scenes(plan_path).planning_count == 2


def test_stock_search_tracks_scene_after_partial_import_reorder_and_remove(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    media = tmp_path / "shared.mp4"
    media.touch()
    plan_path = _make_planning_plan(tmp_path, count=3)
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    # Two scenes deliberately share a clip: identity must not depend on the path.
    for scene in data["scenes"][1:]:
        scene["media"] = str(media)
    plan_path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(ui.filedialog, "askopenfilename", lambda **k: str(plan_path))
    monkeypatch.setattr(ui, "wav_duration", lambda _p: 4.0)
    monkeypatch.setattr(ui, "available_stock_source_names", lambda: ["pexels"])
    editor.import_plan()
    settle(app, editor)

    def assert_default(scene_id):
        editor.open_stock_search()
        dialog = _find_toplevel(editor, "Buscar mídia stock")
        combo = next(_widgets(dialog, ui.ttk.Combobox))
        assert combo.get() == scene_id
        dialog.destroy()

    assert_default("cena-02")
    editor.move_selected(1)
    assert_default("cena-02")
    editor.remove_selected()
    assert_default("cena-03")
    editor.add_paths([media])
    assert_default("cena-01")  # Manual media has no plan-scene identity.
    assert not errors


def test_stock_scene_change_refreshes_query_and_search_target(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.current_plan = load_scenes(_make_planning_plan(tmp_path))
    monkeypatch.setattr(ui, "available_stock_source_names", lambda: ["pexels"])
    calls = []
    monkeypatch.setattr(editor, "search_stock", lambda *args: calls.append(args))
    editor.open_stock_search()
    dialog = _find_toplevel(editor, "Buscar mídia stock")
    scene_box = next(_widgets(dialog, ui.ttk.Combobox))
    scene_box.set("cena-02")
    scene_box.event_generate("<<ComboboxSelected>>")
    next(button for button in _widgets(dialog, ui.ttk.Button) if button.cget("text") == "Buscar").invoke()
    assert calls == [("cena-02", "Narração 2.", "video", 3, ["pexels"])]
    assert not errors


def test_declined_import_preserves_active_stock_plan_and_wav(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    old_path = _make_planning_plan(tmp_path)
    old_plan = load_scenes(old_path)
    editor.current_plan = old_plan
    editor.current_plan_path = old_path
    media = tmp_path / "video.mp4"
    media.touch()
    editor.items = [TimelineItem(media)]
    incoming = write_plan_file(tmp_path, [media], wav=tmp_path / "other.wav")
    monkeypatch.setattr(ui.filedialog, "askopenfilename", lambda **k: str(incoming))
    prompts = []
    monkeypatch.setattr(ui.messagebox, "askyesno", lambda title, *a, **k: prompts.append(title) or False)
    editor.import_plan()
    assert prompts == ["Substituir timeline?"]
    assert editor.current_plan is old_plan
    assert editor.current_plan_path == old_path
    assert editor.wav_path.get() == str(APPROVED_WAV)
    assert editor.items == [TimelineItem(media)]
    assert not errors


@pytest.mark.parametrize("failure", ["missing", "save"])
def test_failed_stock_association_keeps_dialog_and_original_plan(studio, tmp_path, monkeypatch, failure):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    plan_path = _make_planning_plan(tmp_path)
    editor.current_plan = load_scenes(plan_path)
    editor.current_plan_path = plan_path
    before = plan_path.read_bytes()
    old_plan = editor.current_plan
    path = tmp_path / "download.mp4"
    path.touch()
    editor._show_stock_results("cena-02", {"ok": True, "clips": [{"path": str(path)}]})
    dialog = _find_toplevel(editor, "Resultados stock — cena-02")
    if failure == "missing":
        path.unlink()
    else:
        def fail_save(*args):
            raise OSError("disk unavailable")
        monkeypatch.setattr(ui, "save_plan", fail_save)
    next(button for button in _widgets(dialog, ui.ttk.Button)
         if button.cget("text") == "Usar nesta cena").invoke()
    assert dialog.winfo_exists()
    assert plan_path.read_bytes() == before
    assert editor.current_plan is old_plan
    assert errors
    dialog.destroy()


def test_stock_partial_timeout_results_can_be_associated(studio, tmp_path):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    plan_path = _make_planning_plan(tmp_path)
    editor.current_plan = load_scenes(plan_path)
    editor.current_plan_path = plan_path
    path = tmp_path / "partial.mp4"
    path.touch()
    editor._show_stock_results("cena-02", {"ok": False, "timed_out": True,
                                          "error": "timeout", "clips": [{"path": str(path)}]})
    assert "parciais" in editor.status.get()
    dialog = _find_toplevel(editor, "Resultados stock — cena-02")
    next(button for button in _widgets(dialog, ui.ttk.Button)
         if button.cget("text") == "Usar nesta cena").invoke()
    assert load_scenes(plan_path).scenes[1].media == path
    assert not errors


def test_stock_failure_without_clips_reports_error(studio):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor._show_stock_results("cena-01", {"ok": False, "error": "Source unavailable", "clips": []})
    assert errors == [("Falha na busca stock", "Source unavailable")]
    assert _find_toplevel(editor, "Resultados stock — cena-01") is None


def _hyperframes_summary(tmp_path, name="cena-hyperframes-test.mp4", duration=3.0):
    path = tmp_path / "hyperframes" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * 64)
    return {
        "ok": True, "error": "", "output": str(path),
        "workspace": str(tmp_path / "hyperframes-workspaces" / "cena-hyperframes-test"),
        "width": 1920, "height": 1080, "fps": 30,
        "duration_seconds": duration, "silent": True, "probed": True,
    }


def test_open_hyperframes_dialog_defaults_and_plan_scene(studio, tmp_path):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.current_plan = load_scenes(_make_planning_plan(tmp_path, count=2))
    editor.current_plan_path = tmp_path / "planning-stock.json"
    editor.open_hyperframes_dialog()
    dialog = _find_toplevel(editor, "Gerar cena HyperFrames")
    assert dialog is not None
    combos = list(_widgets(dialog, ui.ttk.Combobox))
    assert len(combos) == 1
    assert combos[0].get() == "cena-01"
    assert "(não associar)" in combos[0]["values"]
    assert "cena-02" in combos[0]["values"]
    checks = list(_widgets(dialog, ui.ttk.Checkbutton))
    assert checks and checks[0].instate(["selected"])
    assert not editor.busy and not errors
    dialog.destroy()


def test_open_hyperframes_dialog_without_plan_offers_timeline_only(studio):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.open_hyperframes_dialog()
    dialog = _find_toplevel(editor, "Gerar cena HyperFrames")
    assert dialog is not None
    assert list(_widgets(dialog, ui.ttk.Combobox)) == []
    assert not editor.busy and not errors
    dialog.destroy()


def test_open_hyperframes_dialog_keeps_existing_media_scene_unselected(studio, tmp_path):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    media = tmp_path / "already.mp4"
    media.touch()
    plan_path = write_plan_file(tmp_path, [media])
    editor.current_plan = load_scenes(plan_path)
    editor.current_plan_path = plan_path
    editor.open_hyperframes_dialog()
    dialog = _find_toplevel(editor, "Gerar cena HyperFrames")
    combos = list(_widgets(dialog, ui.ttk.Combobox))
    assert combos[0].get() == "(não associar)"
    dialog.destroy()


def test_generate_hyperframes_scene_validates_input_before_work(studio, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.generate_hyperframes_scene("Cena", "", "0", True, None)
    assert not editor.busy
    assert errors and "Dura" in errors[-1][1]
    editor.generate_hyperframes_scene("   ", "", "3", True, None)
    assert not editor.busy
    assert errors and errors[-1][0] == "Texto necessário"


def test_generate_hyperframes_failure_reports_clear_error(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.output_dir = tmp_path
    monkeypatch.setattr(ui, "render_test_scene", lambda **kwargs: {
        "ok": False, "error": "HyperFrames indisponível: node not found on PATH",
        "output": "", "workspace": "", "duration_seconds": 0.0,
    })
    editor.generate_hyperframes_scene("Cena", "Sub", 3.0, True, None)
    assert editor.busy
    settle(app, editor)
    assert errors == [("Falha na cena HyperFrames",
                       "HyperFrames indisponível: node not found on PATH")]
    assert editor.status.get().startswith("Falha na cena HyperFrames")
    assert editor.items == []


def test_generate_hyperframes_associates_plan_and_adds_timeline(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.output_dir = tmp_path
    plan_path = _make_planning_plan(tmp_path, count=1)
    editor.current_plan = load_scenes(plan_path)
    editor.current_plan_path = plan_path
    summary = _hyperframes_summary(tmp_path)
    monkeypatch.setattr(ui, "render_test_scene", lambda **kwargs: summary)
    editor.generate_hyperframes_scene("Cena HyperFrames", "Etapa 7", 3.0, True, "cena-01")
    assert editor.busy
    settle(app, editor)
    assert not errors
    entry = load_scenes(plan_path).scenes[0]
    assert entry.media == Path(summary["output"])
    assert entry.source == "hyperframes"
    assert entry.creator == "OpenMontage Studio (HyperFrames)"
    assert entry.has_provenance is True
    assert [item.path for item in editor.items] == [Path(summary["output"])]
    assert editor.items[0].frames == 90
    assert editor._timeline_scene_ids == ["cena-01"]
    assert "Cena HyperFrames pronta" in editor.status.get()
    assert "associada no plano" in editor.status.get()
    assert "adicionado à timeline" in editor.status.get()


def test_generate_hyperframes_timeline_only_keeps_plan_untouched(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.output_dir = tmp_path
    plan_path = _make_planning_plan(tmp_path, count=1)
    editor.current_plan = load_scenes(plan_path)
    editor.current_plan_path = plan_path
    summary = _hyperframes_summary(tmp_path, name="timeline-only.mp4", duration=2.5)
    monkeypatch.setattr(ui, "render_test_scene", lambda **kwargs: summary)
    editor.generate_hyperframes_scene("Cena", "", 2.5, True, None)
    settle(app, editor)
    assert not errors
    assert load_scenes(plan_path).scenes[0].media is None
    assert [item.path for item in editor.items] == [Path(summary["output"])]
    assert editor._timeline_scene_ids == [None]
    assert "adicionado à timeline" in editor.status.get()


def test_generate_hyperframes_plan_only_keeps_timeline_empty(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.output_dir = tmp_path
    plan_path = _make_planning_plan(tmp_path, count=1)
    editor.current_plan = load_scenes(plan_path)
    editor.current_plan_path = plan_path
    summary = _hyperframes_summary(tmp_path, name="plan-only.mp4")
    monkeypatch.setattr(ui, "render_test_scene", lambda **kwargs: summary)
    editor.generate_hyperframes_scene("Cena", "", 3.0, False, "cena-01")
    settle(app, editor)
    assert not errors
    entry = load_scenes(plan_path).scenes[0]
    assert entry.media == Path(summary["output"])
    assert editor.items == []
    assert "associada no plano" in editor.status.get()
    assert "adicionado à timeline" not in editor.status.get()


def test_generate_hyperframes_cancel_discards_result(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.output_dir = tmp_path

    def cancelled_render(**kwargs):
        kwargs["cancel_event"].set()
        return {"ok": False, "cancelled": True, "output": "", "workspace": "",
                "error": "Geração de cena HyperFrames cancelada."}

    monkeypatch.setattr(ui, "render_test_scene", cancelled_render)
    editor.generate_hyperframes_scene("Cena", "", 3.0, True, None)
    settle(app, editor)
    assert not errors
    assert "cancelada" in editor.status.get()
    assert editor.items == []


def _stickman_summary(tmp_path, name="cena-stickman-test.mp4", duration=15.0,
                      preset="demonstracao_escritorio"):
    path = tmp_path / "stickman" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * 64)
    return {
        "ok": True, "error": "", "output": str(path),
        "workspace": str(tmp_path / "stickman-workspaces" / "cena-stickman-test"),
        "width": 1920, "height": 1080, "fps": 30,
        "duration_seconds": duration, "silent": True, "probed": True,
        "preset": preset, "scenario": "escritorio", "character": "heroi",
    }


def test_open_stickman_dialog_defaults_and_plan_scene(studio, tmp_path):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.current_plan = load_scenes(_make_planning_plan(tmp_path, count=2))
    editor.current_plan_path = tmp_path / "planning-stock.json"
    editor.open_stickman_dialog()
    dialog = _find_toplevel(editor, "Gerar cena Stickman")
    assert dialog is not None
    combos = list(_widgets(dialog, ui.ttk.Combobox))
    assert len(combos) == 3
    assert combos[0].get().startswith("demonstracao_escritorio")
    assert combos[1].get().startswith("heroi")
    assert combos[2].get() == "cena-01"
    assert "(não associar)" in combos[2]["values"]
    checks = list(_widgets(dialog, ui.ttk.Checkbutton))
    assert checks and checks[0].instate(["selected"])
    dialog.destroy()


def test_open_stickman_dialog_without_plan_offers_timeline_only(studio):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.open_stickman_dialog()
    dialog = _find_toplevel(editor, "Gerar cena Stickman")
    assert dialog is not None
    combos = list(_widgets(dialog, ui.ttk.Combobox))
    assert len(combos) == 2
    assert not editor.busy and not errors
    dialog.destroy()


def test_open_stickman_dialog_duration_tracks_preset(studio):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.open_stickman_dialog()
    dialog = _find_toplevel(editor, "Gerar cena Stickman")
    presets = list(_widgets(dialog, ui.ttk.Combobox))[0]

    def duration_texts():
        values = []
        for entry in _widgets(dialog, ui.ttk.Entry):
            var_name = entry.cget("textvariable")
            if var_name:
                values.append(str(dialog.tk.globalgetvar(var_name)))
        return values

    assert "20" in " ".join(duration_texts())
    presets.set("caminhar_rua — Caminhar e correr na rua")
    presets.event_generate("<<ComboboxSelected>>")
    app.update()
    assert "15" in " ".join(duration_texts())
    dialog.destroy()


def test_generate_stickman_scene_validates_spec_before_work(studio, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.generate_stickman_scene({"scenario": "marte"}, True, None)
    assert not editor.busy
    assert errors and errors[-1][0] == "Cena Stickman inválida"
    editor.generate_stickman_scene(
        {"scenario": "rua", "character": "heroi", "duration_seconds": 10,
         "beats": [{"action": "voar", "start": 0, "duration": 1}]}, True, None)
    assert not editor.busy
    assert len(errors) == 2


def test_generate_stickman_failure_reports_clear_error(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.output_dir = tmp_path
    monkeypatch.setattr(ui, "render_stickman_scene", lambda **kwargs: {
        "ok": False, "error": "HyperFrames indisponível: node not found on PATH",
        "output": "", "workspace": "", "duration_seconds": 0.0,
    })
    editor.generate_stickman_scene(
        ui.build_stickman_spec("gestos_abstratos", 12), True, None)
    assert editor.busy
    settle(app, editor)
    assert errors == [("Falha na cena Stickman",
                       "HyperFrames indisponível: node not found on PATH")]
    assert editor.status.get().startswith("Falha na cena Stickman")
    assert editor.items == []


def test_generate_stickman_associates_plan_and_adds_timeline(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.output_dir = tmp_path
    plan_path = _make_planning_plan(tmp_path, count=1)
    editor.current_plan = load_scenes(plan_path)
    editor.current_plan_path = plan_path
    summary = _stickman_summary(tmp_path)
    monkeypatch.setattr(ui, "render_stickman_scene", lambda **kwargs: summary)
    editor.generate_stickman_scene(
        ui.build_stickman_spec("demonstracao_escritorio", 15), True, "cena-01")
    assert editor.busy
    settle(app, editor)
    assert not errors
    entry = load_scenes(plan_path).scenes[0]
    assert entry.media == Path(summary["output"])
    assert entry.source == "stickman"
    assert entry.creator == "OpenMontage Studio (Stickman)"
    assert entry.has_provenance is True
    assert [item.path for item in editor.items] == [Path(summary["output"])]
    assert editor.items[0].frames == 450
    assert editor._timeline_scene_ids == ["cena-01"]
    assert "Cena Stickman pronta" in editor.status.get()
    assert "associada no plano" in editor.status.get()


def test_generate_stickman_timeline_only_keeps_plan_untouched(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.output_dir = tmp_path
    plan_path = _make_planning_plan(tmp_path, count=1)
    editor.current_plan = load_scenes(plan_path)
    editor.current_plan_path = plan_path
    summary = _stickman_summary(tmp_path, name="timeline-only.mp4", duration=12.0,
                                preset="gestos_abstratos")
    monkeypatch.setattr(ui, "render_stickman_scene", lambda **kwargs: summary)
    editor.generate_stickman_scene(
        ui.build_stickman_spec("gestos_abstratos", 12), True, None)
    settle(app, editor)
    assert not errors
    assert load_scenes(plan_path).scenes[0].media is None
    assert [item.path for item in editor.items] == [Path(summary["output"])]
    assert editor._timeline_scene_ids == [None]


def test_generate_stickman_cancel_discards_result(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.output_dir = tmp_path

    def cancelled_render(**kwargs):
        kwargs["cancel_event"].set()
        return {"ok": False, "cancelled": True, "output": "", "workspace": "",
                "error": "Geração de cena Stickman cancelada."}

    monkeypatch.setattr(ui, "render_stickman_scene", cancelled_render)
    editor.generate_stickman_scene(
        ui.build_stickman_spec("gestos_abstratos", 12), True, None)
    settle(app, editor)
    assert not errors
    assert "cancelada" in editor.status.get()
    assert editor.items == []


def test_stock_credit_write_failure_is_visible(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    plan_path = _make_planning_plan(tmp_path)
    editor.current_plan = load_scenes(plan_path)
    editor.current_plan_path = plan_path
    path = tmp_path / "clip.mp4"
    path.touch()
    warnings = []
    def fail_credits(*args):
        raise OSError("credits read only")
    monkeypatch.setattr(ui, "write_credits", fail_credits)
    monkeypatch.setattr(ui.messagebox, "showwarning", lambda *a, **k: warnings.append(a))
    assert editor._apply_clip_to_scene("cena-02", {"path": str(path)})
    assert load_scenes(plan_path).scenes[1].media == path
    assert warnings and "Créditos não salvos" in warnings[0][0]
    assert "falha ao gravar créditos" in editor.status.get()
    assert not errors


def test_generating_new_plan_preserves_existing_plan(studio, tmp_path, monkeypatch):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.plans_dir = tmp_path
    existing = tmp_path / "scenes.json"
    existing.write_bytes(b"previous approved plan")
    monkeypatch.setattr(ui, "wav_duration", lambda _p: 4.0)
    monkeypatch.setattr(ui.messagebox, "showinfo", lambda *a, **k: None)
    editor.generate_plan("New narration for a new plan.")
    settle(app, editor)
    assert not errors
    assert existing.read_bytes() == b"previous approved plan"
    assert editor.last_plan != existing
    assert load_scenes(editor.last_plan).planning_count == 1


def test_setup_modal_dialog_binds_unmap_and_map():
    root = tk.Tk()
    root.withdraw()
    try:
        dialog = tk.Toplevel(root)
        dialog.withdraw()
        ui._setup_modal_dialog(dialog)
        assert dialog.bind("<Unmap>") != "", "missing <Unmap> binding"
        assert dialog.bind("<Map>") != "", "missing <Map> binding"
        dialog.destroy()
    finally:
        root.destroy()


def test_plan_generator_dialog_releases_grab_on_unmap_and_restores_on_map(studio):
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    editor.open_plan_generator()
    app.update()
    dialog = _find_toplevel(editor, "Gerar plano de cenas")
    assert dialog is not None, "plan generator dialog did not open"
    assert dialog.grab_current() == dialog, "grab should be set on open"
    dialog.event_generate("<Unmap>")
    app.update()
    assert dialog.grab_current() is None, "grab should be released on unmap"
    dialog.event_generate("<Map>")
    app.update()
    assert dialog.grab_current() == dialog, "grab should be re-established on map"
    dialog.destroy()


def test_stock_search_dialog_releases_grab_on_unmap_and_restores_on_map(studio, tmp_path, monkeypatch):
    import tkinter as tk_mod
    app, errors = studio
    editor = app._open_timeline()
    editor.withdraw()
    plan_path = _make_planning_plan(tmp_path, count=1)
    editor.current_plan = load_scenes(plan_path)
    editor.current_plan_path = plan_path
    monkeypatch.setattr(ui, "available_stock_source_names", lambda: ["pexels"])
    editor.open_stock_search()
    app.update()
    dialog = _find_toplevel(editor, "Buscar mídia stock")
    assert dialog is not None, "stock search dialog did not open"
    assert dialog.grab_current() == dialog, "grab should be set on open"
    dialog.event_generate("<Unmap>")
    app.update()
    assert dialog.grab_current() is None, "grab should be released on unmap"
    dialog.event_generate("<Map>")
    app.update()
    assert dialog.grab_current() == dialog, "grab should be re-established on map"
    dialog.destroy()
