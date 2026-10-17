"""Reproducible local QA for the HyperFrames test-scene flow (stage 7).

Run from the repository: .venv/Scripts/python.exe scripts/validate_studio_stage7_hyperframes.py

Exercises the real UI button → dialog → worker → render → plan association →
timeline → short MP4 export against the approved WAV (read-only). The render
is local (Node + FFmpeg + `npx hyperframes`); no paid APIs and no stock
network calls. When the HyperFrames runtime is unavailable the script prints
the reasons + install instructions and exits without failing, so the Studio
regressions can still run elsewhere.
Never modifies the approved narration WAV or the approved mix profile.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.studio_hyperframes import hyperframes_status, probe_scene
from lib.studio_scenes import load_scenes
from lib.studio_timeline import APPROVED_WAV
from lib import studio_timeline_ui as ui
from openmontage_studio import OpenMontageStudio
from tools.video.studio_export import NO_WINDOW, StudioExport, verify_export, wav_duration


def run_ffmpeg(*args):
    result = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-nostdin", "-n", *map(str, args)],
                            capture_output=True, timeout=300, creationflags=NO_WINDOW)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace"))
    return result.stdout


def fingerprint(path):
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"sha256": sha, "size": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns}


def wait_for_ui(app, editor, errors, timeout=900):
    deadline = time.monotonic() + timeout
    while editor.busy:
        app.update()
        if errors:
            raise RuntimeError(str(errors))
        if time.monotonic() > deadline:
            editor.cancel_event.set()
            raise TimeoutError("UI operation timed out")
        time.sleep(0.01)
    app.update()
    if errors:
        raise RuntimeError(str(errors))


def widgets(parent, widget_type):
    for child in parent.winfo_children():
        if isinstance(child, widget_type):
            yield child
        yield from widgets(child, widget_type)


def write_planning_plan(path, count=2):
    scenes = [
        {"id": f"cena-{i + 1:02d}", "duration_seconds": 2.0,
         "note": f"Planejar mídia {i + 1}", "narration": f"Narração {i + 1}."}
        for i in range(count)
    ]
    path.write_text(json.dumps({"version": "1.0", "title": "QA Stage 7", "scenes": scenes},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main():
    tool = StudioExport()
    assert tool.check_available(), "FFmpeg e ffprobe precisam estar no PATH"
    assert APPROVED_WAV.is_file(), f"WAV aprovado não encontrado: {APPROVED_WAV}"

    status = hyperframes_status()
    if not status["available"]:
        print(json.dumps({
            "skipped": True,
            "reason": "HyperFrames runtime indisponível nesta máquina",
            "reasons": status["reasons"],
            "install_instructions": status["install_instructions"],
        }, ensure_ascii=True, indent=2))
        return

    output_dir = ROOT / "projects" / "openmontage-studio" / ("qa-stage7-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    output_dir.mkdir(parents=True, exist_ok=False)
    protected = [APPROVED_WAV]
    before = {str(p): fingerprint(p) for p in protected}

    app = OpenMontageStudio()
    app.withdraw()
    errors = []
    app.report_callback_exception = lambda _type, value, _trace: errors.append(str(value))
    results = {"hyperframes_runtime": {
        "available": True,
        "version": status["runtime"].get("npm_package_version"),
        "node_major": status["runtime"].get("node_major"),
    }}
    try:
        with patch.object(ui.messagebox, "showerror", side_effect=lambda *a, **_k: errors.append(a)):
            editor = app._open_timeline()
            editor.withdraw()
            editor.output_dir = output_dir

            # --- A) Compatibility: an Etapa 5 style plan (no provenance) still loads ---
            legacy = output_dir / "plan-legacy.json"
            legacy.write_text(json.dumps({
                "version": "1.0", "title": "Legado",
                "scenes": [{"id": "cena-01", "duration_seconds": 2.0, "note": "sem proveniência"}],
            }, ensure_ascii=False), encoding="utf-8")
            legacy_plan = load_scenes(legacy)
            assert legacy_plan.planning_count == 1
            assert legacy_plan.scenes[0].has_provenance is False
            results["legacy_plan_load"] = "passed"

            # --- B) Planning plan loaded into the editor ---
            plan_path = write_planning_plan(output_dir / "plan-hyperframes.json", count=2)
            editor.current_plan = load_scenes(plan_path)
            editor.current_plan_path = plan_path
            results["planning_scenes"] = 2

            # --- C) Real UI: button → dialog → worker → real HyperFrames render ---
            button = next(b for b in widgets(editor, ttk.Button)
                          if b.cget("text") == "Cena HyperFrames…")
            button.invoke()
            app.update()
            dialog = next(child for child in editor.winfo_children()
                          if isinstance(child, tk.Toplevel) and child.title() == "Gerar cena HyperFrames")
            scene_box = next(widgets(dialog, ttk.Combobox))
            assert scene_box.get() == "cena-01", scene_box.get()
            next(b for b in widgets(dialog, ttk.Button)
                 if b.cget("text") == "Gerar cena").invoke()
            wait_for_ui(app, editor, errors, timeout=900)
            results["real_ui_dialog"] = "passed"

            # --- D) Scene associated in the plan with HyperFrames provenance ---
            entry = load_scenes(plan_path).scenes[0]
            assert entry.media is not None, "HyperFrames scene was not associated"
            assert entry.source == "hyperframes"
            assert entry.creator == "OpenMontage Studio (HyperFrames)"
            assert entry.license
            assert load_scenes(plan_path).scenes[1].media is None
            results["association"] = {
                "scene": entry.id, "media": str(entry.media),
                "source": entry.source, "license": entry.license,
            }

            # --- E) Rendered MP4 honors the 1920x1080 / 30 fps / silent contract ---
            probe = probe_scene(entry.media)
            assert probe["probed"] and probe["silent"] is True
            assert probe["width"] == 1920 and probe["height"] == 1080 and probe["fps"] == 30
            results["scene_probe"] = probe

            # --- F) Timeline got the scene with its scene-plan identity ---
            assert len(editor.items) == 1, editor.items
            assert editor._timeline_scene_ids == ["cena-01"]
            results["timeline_items"] = len(editor.items)

            # --- G) Short export against the approved WAV (read-only) ---
            editor.adjust_to_wav()
            wait_for_ui(app, editor, errors)
            assert Path(editor.wav_path.get()).resolve() == APPROVED_WAV.resolve()
            output = output_dir / "timeline-stage7-hyperframes.mp4"
            with patch.object(ui.filedialog, "asksaveasfilename", return_value=str(output)):
                editor.export_button.invoke()
                wait_for_ui(app, editor, errors)
            assert editor.last_output == output and editor.open_button.instate(["!disabled"])
            verification = verify_export(output, wav_duration(APPROVED_WAV))
            run_ffmpeg("-xerror", "-i", output, "-f", "null", "-")
            results["mp4"] = str(output)
            results["verification"] = verification

            # --- H) Approved WAV fingerprint unchanged ---
            after = {str(p): fingerprint(p) for p in protected}
            assert before == after, "The approved WAV changed during validation"
            results["approved_wav_unchanged"] = True
            results["approved_wav_sha256"] = before[str(APPROVED_WAV)]["sha256"]

            results["availability"] = tool.check_available()
            results["scope"] = ("real HyperFrames render via the Studio UI + scenes.json "
                                "association + timeline identity + FFmpeg export; approved WAV read-only.")
            report_path = output_dir / "validation.json"
            report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(results, ensure_ascii=True, indent=2))
    finally:
        app._close_studio()


if __name__ == "__main__":
    main()
