"""Exercise actual Tk widgets and worker-to-UI communication without paid calls."""
import json
import time
from pathlib import Path

import pytest

from lib import studio_timeline_ui as ui
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
