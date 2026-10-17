import shutil
import subprocess

import pytest

from lib import studio_hyperframes as hf
from tools.base_tool import ToolResult


def _patch_runtime(monkeypatch, **overrides):
    from tools.video.hyperframes_compose import HyperFramesCompose

    check = {
        "runtime_available": True,
        "node_major": 24,
        "ffmpeg_available": True,
        "npx_available": True,
        "npm_package": "hyperframes",
        "npm_package_version": "0.8.155",
        "reasons": [],
    }
    check.update(overrides)
    monkeypatch.setattr(HyperFramesCompose, "_runtime_check", lambda self: check)
    return check


def test_status_available_reports_runtime_and_instructions(monkeypatch):
    _patch_runtime(monkeypatch)
    status = hf.hyperframes_status()
    assert status["available"] is True
    assert status["reasons"] == []
    assert "npx hyperframes" in status["install_instructions"]
    assert status["runtime"]["npm_package_version"] == "0.8.155"


def test_status_unavailable_lists_reasons_and_install_help(monkeypatch):
    _patch_runtime(monkeypatch, runtime_available=False,
                   reasons=["node not found on PATH"])
    status = hf.hyperframes_status()
    assert status["available"] is False
    message = hf.format_unavailable_error(status)
    assert "node not found on PATH" in message
    assert "Node.js" in message
    assert "npx hyperframes" in message


@pytest.mark.parametrize("value,expected", [
    ("3", 3.0), ("3,5", 3.5), (2, 2.0), (1 / 30, 1 / 30),
])
def test_validate_duration_accepts_frame_level_minimum(value, expected):
    assert hf.validate_duration(value) == pytest.approx(expected)


@pytest.mark.parametrize("value", ["0", "-1", "abc", "", None, 31, 120])
def test_validate_duration_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="Dura"):
        hf.validate_duration(value)


def test_build_test_edit_decisions_shapes_single_text_card():
    edit = hf.build_test_edit_decisions("  Título  ", "legenda", 4.0)
    assert edit["render_runtime"] == "hyperframes"
    assert edit["metadata"]["title"]
    assert len(edit["cuts"]) == 1
    cut = edit["cuts"][0]
    assert cut["type"] == "text_card"
    assert cut["text"] == "Título"
    assert cut["subtitle"] == "legenda"
    assert cut["in_seconds"] == 0.0
    assert cut["out_seconds"] == 4.0
    assert "audio" not in edit
    assert "narration" not in edit


def test_build_test_edit_decisions_requires_text():
    with pytest.raises(ValueError, match="texto"):
        hf.build_test_edit_decisions("   ")


def test_unique_path_and_dir_never_overwrite(tmp_path):
    target = tmp_path / "cena.mp4"
    assert hf.unique_path(target) == target
    target.write_bytes(b"existing")
    first = hf.unique_path(target)
    assert first != target and not first.exists()
    first.write_bytes(b"second")
    second = hf.unique_path(target)
    assert second not in (target, first) and not second.exists()

    directory = tmp_path / "workspace"
    assert hf.unique_dir(directory) == directory
    directory.mkdir()
    moved = hf.unique_dir(directory)
    assert moved != directory and not moved.exists()


def test_render_fails_fast_when_runtime_unavailable(monkeypatch, tmp_path):
    _patch_runtime(monkeypatch, runtime_available=False,
                   reasons=["npx not found on PATH"])
    summary = hf.render_test_scene(output_dir=tmp_path, text="Cena")
    assert summary["ok"] is False
    assert "HyperFrames indisponível" in summary["error"]
    assert "npx not found on PATH" in summary["error"]
    assert "npx hyperframes" in summary["error"]
    assert list(tmp_path.iterdir()) == []


def test_render_rejects_bad_duration_before_any_work(monkeypatch, tmp_path):
    _patch_runtime(monkeypatch)
    summary = hf.render_test_scene(output_dir=tmp_path, text="Cena", duration_seconds=0)
    assert summary["ok"] is False
    assert "Dura" in summary["error"]
    assert list(tmp_path.iterdir()) == []


def test_render_success_writes_unique_mp4_and_reports_progress(monkeypatch, tmp_path):
    _patch_runtime(monkeypatch)
    captured = {}

    def fake_execute(self, inputs):
        captured.update(inputs)
        output = inputs["output_path"]
        Path = __import__("pathlib").Path
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_bytes(b"\x00" * 32)
        return ToolResult(success=True, data={"steps": {"render": {"exit_code": 0}}})

    from tools.video.hyperframes_compose import HyperFramesCompose
    monkeypatch.setattr(HyperFramesCompose, "execute", fake_execute)
    monkeypatch.setattr(hf, "probe_scene", lambda path: {
        "probed": True, "width": 1920, "height": 1080, "fps": 30,
        "silent": True, "duration_seconds": 3.003,
    })
    progress = []
    summary = hf.render_test_scene(
        output_dir=tmp_path, text="Cena", subtitle="Etapa 7", duration_seconds=3,
        progress=lambda fraction, message: progress.append((fraction, message)),
    )
    assert summary["ok"] is True, summary["error"]
    output = __import__("pathlib").Path(summary["output"])
    assert output.is_file()
    assert output.parent.name == hf.MP4_SUBDIR
    assert output.name.startswith("cena-hyperframes-")
    assert summary["width"] == 1920 and summary["height"] == 1080
    assert summary["fps"] == 30 and summary["silent"] is True
    assert summary["duration_seconds"] == pytest.approx(3.003)
    assert summary["runtime_version"] == "0.8.155"
    assert captured["operation"] == "render"
    assert captured["fps"] == 30
    assert captured["edit_decisions"]["render_runtime"] == "hyperframes"
    assert captured["output_path"] == summary["output"]
    assert [fraction for fraction, _ in progress] == [0.03, 0.10, 0.9, 1.0]
    assert "1920" in progress[2][1]


def test_render_reuses_unique_names_on_collision(monkeypatch, tmp_path):
    _patch_runtime(monkeypatch)
    from pathlib import Path as P

    def fake_execute(self, inputs):
        target = P(inputs["output_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\x00")
        return ToolResult(success=True, data={})

    from tools.video.hyperframes_compose import HyperFramesCompose
    monkeypatch.setattr(HyperFramesCompose, "execute", fake_execute)
    monkeypatch.setattr(hf, "probe_scene", lambda path: {
        "probed": True, "width": 1920, "height": 1080, "fps": 30,
        "silent": True, "duration_seconds": 2.0,
    })
    # Freeze the timestamp so both renders target the same base name.
    monkeypatch.setattr(hf, "datetime_stamp", lambda: "fixed")
    first = hf.render_test_scene(output_dir=tmp_path, text="Uma")
    second = hf.render_test_scene(output_dir=tmp_path, text="Duas")
    assert first["ok"] and second["ok"]
    assert first["output"] != second["output"]
    assert (tmp_path / hf.MP4_SUBDIR / "cena-hyperframes-fixed.mp4").is_file()


def test_render_tool_failure_returns_readable_error(monkeypatch, tmp_path):
    _patch_runtime(monkeypatch)

    def fake_execute(self, inputs):
        return ToolResult(success=False, error="Validate failed: contrast",
                          data={"steps": {"validate": {"exit_code": 1}}})

    from tools.video.hyperframes_compose import HyperFramesCompose
    monkeypatch.setattr(HyperFramesCompose, "execute", fake_execute)
    summary = hf.render_test_scene(output_dir=tmp_path, text="Cena")
    assert summary["ok"] is False
    assert "Validate failed" in summary["error"]
    assert summary["steps"]["validate"]["exit_code"] == 1


def test_render_probe_mismatch_is_reported_not_raised(monkeypatch, tmp_path):
    _patch_runtime(monkeypatch)

    def fake_execute(self, inputs):
        from pathlib import Path as P
        target = P(inputs["output_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\x00")
        return ToolResult(success=True, data={})

    from tools.video.hyperframes_compose import HyperFramesCompose
    monkeypatch.setattr(HyperFramesCompose, "execute", fake_execute)

    def bad_probe(path):
        raise ValueError("MP4 fora do contrato: esperado 1920×1080 a 30 fps sem áudio.")

    monkeypatch.setattr(hf, "probe_scene", bad_probe)
    summary = hf.render_test_scene(output_dir=tmp_path, text="Cena")
    assert summary["ok"] is False
    assert "fora do contrato" in summary["error"]


def test_render_cancel_event_marks_cancelled(monkeypatch, tmp_path):
    _patch_runtime(monkeypatch)
    import threading
    from pathlib import Path as P

    def fake_execute(self, inputs):
        target = P(inputs["output_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\x00")
        return ToolResult(success=True, data={})

    from tools.video.hyperframes_compose import HyperFramesCompose
    monkeypatch.setattr(HyperFramesCompose, "execute", fake_execute)
    monkeypatch.setattr(hf, "probe_scene", lambda path: {
        "probed": False, "width": 1920, "height": 1080, "fps": 30,
        "silent": True, "duration_seconds": 3.0,
    })
    cancel = threading.Event()
    cancel.set()
    summary = hf.render_test_scene(output_dir=tmp_path, text="Cena", cancel_event=cancel)
    assert summary["ok"] is False
    assert summary.get("cancelled") is True
    assert "cancelada" in summary["error"]
    assert P(summary["output"]).is_file()


def test_render_unexpected_exception_is_wrapped(monkeypatch, tmp_path):
    _patch_runtime(monkeypatch)

    def boom(self, inputs):
        raise RuntimeError("npx exploded")

    from tools.video.hyperframes_compose import HyperFramesCompose
    monkeypatch.setattr(HyperFramesCompose, "execute", boom)
    summary = hf.render_test_scene(output_dir=tmp_path, text="Cena")
    assert summary["ok"] is False
    assert "RuntimeError" in summary["error"]
    assert "npx exploded" in summary["error"]


FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _make_mp4(path, size="1920x1080", with_audio=False):
    command = ["ffmpeg", "-hide_banner", "-v", "error", "-y",
               "-f", "lavfi", "-i", f"testsrc2=s={size}:r=30:d=0.2"]
    if with_audio:
        command += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-shortest"]
    command += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if with_audio:
        command += ["-c:a", "aac"]
    subprocess.run(command + [str(path)], check=True, capture_output=True, timeout=300)
    return path


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg and ffprobe are required")
def test_probe_scene_accepts_silent_1080p30(tmp_path):
    good = _make_mp4(tmp_path / "good.mp4")
    probe = hf.probe_scene(good)
    assert probe["probed"] is True
    assert probe["width"] == 1920 and probe["height"] == 1080
    assert probe["fps"] == 30
    assert probe["silent"] is True
    assert probe["duration_seconds"] > 0.1


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg and ffprobe are required")
def test_probe_scene_rejects_audio_track(tmp_path):
    noisy = _make_mp4(tmp_path / "noisy.mp4", with_audio=True)
    with pytest.raises(ValueError, match="silencioso|contrato"):
        hf.probe_scene(noisy)


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg and ffprobe are required")
def test_probe_scene_rejects_wrong_resolution(tmp_path):
    small = _make_mp4(tmp_path / "small.mp4", size="640x360")
    with pytest.raises(ValueError, match="contrato"):
        hf.probe_scene(small)


def test_probe_scene_missing_file_raises(tmp_path):
    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe is required")
    with pytest.raises(ValueError, match="n.o encontrado"):
        hf.probe_scene(tmp_path / "missing.mp4")
