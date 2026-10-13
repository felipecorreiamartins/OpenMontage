"""Exercise actual Tk widgets and worker-to-UI communication without paid calls."""
import time
from pathlib import Path

import pytest

from lib import studio_timeline_ui as ui
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
