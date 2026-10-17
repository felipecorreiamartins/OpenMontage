"""Reproducible local QA for stock media search + scene association (stage 6).

Run from the repository: .venv/Scripts/python.exe scripts/validate_studio_stage6_stock.py
Uses synthetic media plus the approved WAV as a read-only input. No paid APIs,
no network. Stock search is mocked; the real tool contract is unit-tested separately.
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


def wait_for_ui(app, editor, errors):
    deadline = time.monotonic() + 120
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


def write_planning_plan(path, count=2):
    scenes = [
        {"id": f"cena-{i + 1:02d}", "duration_seconds": 2.0,
         "note": f"Planejar mídia {i + 1}", "narration": f"Narração {i + 1}."}
        for i in range(count)
    ]
    path.write_text(json.dumps({"version": "1.0", "title": "QA Stage 6", "scenes": scenes},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def widgets(parent, widget_type):
    for child in parent.winfo_children():
        if isinstance(child, widget_type):
            yield child
        yield from widgets(child, widget_type)


def main():
    tool = StudioExport()
    assert tool.check_available(), "FFmpeg e ffprobe precisam estar no PATH"
    assert APPROVED_WAV.is_file(), f"WAV aprovado não encontrado: {APPROVED_WAV}"

    output_dir = ROOT / "projects" / "openmontage-studio" / ("qa-stage6-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    output_dir.mkdir(parents=True, exist_ok=False)
    protected = [APPROVED_WAV]
    before = {str(p): fingerprint(p) for p in protected}

    app = OpenMontageStudio()
    app.withdraw()
    errors = []
    app.report_callback_exception = lambda _type, value, _trace: errors.append(str(value))
    results = {}
    try:
        with patch.object(ui.messagebox, "showerror", side_effect=lambda *a, **_k: errors.append(a)):
            editor = app._open_timeline()
            editor.withdraw()
            editor.output_dir = output_dir

            # --- A) Load a planning-only plan into the editor ---
            plan_path = write_planning_plan(output_dir / "plan-stock.json", count=2)
            editor.current_plan = load_scenes(plan_path)
            editor.current_plan_path = plan_path
            assert editor.current_plan.planning_count == 2
            results["planning_scenes"] = 2

            # --- B) Search stock with a mocked transport (no network) ---
            fake_clip = output_dir / "stock" / "pexels_42.mp4"
            fake_clip.parent.mkdir(parents=True, exist_ok=True)
            run_ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=1.0",
                       "-c:v", "libx264", "-pix_fmt", "yuv420p", fake_clip)
            distractor = output_dir / "stock" / "pexels_41.mp4"
            run_ffmpeg("-f", "lavfi", "-i", "color=c=blue:s=320x240:r=30:d=1.0",
                       "-c:v", "libx264", "-pix_fmt", "yuv420p", distractor)
            fake_summary = {
                "ok": True, "error": "",
                "clips": [{
                    "path": str(fake_clip), "source": "pexels", "source_id": "42",
                    "source_url": "https://www.pexels.com/photo/42/",
                    "creator": "QA Photographer", "license": "Pexels License",
                    "kind": "video",
                }],
                "errors": [], "timed_out": False,
            }
            fake_summary["clips"].insert(0, {
                **fake_summary["clips"][0], "path": str(distractor), "source_id": "41",
            })
            with patch.object(ui, "available_stock_source_names", return_value=["pexels"]), \
                 patch.object(ui, "run_stock_search", return_value=fake_summary):
                editor.search_stock("cena-02", "sunset over mountains", "video", 3, ["pexels"])
                wait_for_ui(app, editor, errors)
            results["stock_search"] = "mocked_ok"

            # --- C) Select the second result through the actual Tk dialog/button ---
            dialog = next(child for child in editor.winfo_children()
                          if isinstance(child, tk.Toplevel) and child.title() == "Resultados stock — cena-02")
            tree = next(widgets(dialog, ttk.Treeview))
            assert tree.selection() == (tree.get_children()[0],)
            tree.selection_set(tree.get_children()[1])
            next(button for button in widgets(dialog, ttk.Button)
                 if button.cget("text") == "Usar nesta cena").invoke()
            assert not dialog.winfo_exists(), errors
            reloaded = load_scenes(plan_path)
            assert reloaded.scenes[0].media is None, "Unselected scene was changed"
            entry = reloaded.scenes[1]
            assert entry.media == fake_clip.resolve()
            assert entry.source == "pexels"
            assert entry.source_id == "42"
            assert entry.creator == "QA Photographer"
            assert entry.license == "Pexels License"
            assert entry.has_provenance is True
            results["provenance"] = {
                "source": entry.source, "source_id": entry.source_id,
                "creator": entry.creator, "license": entry.license,
            }
            results["selected_result"] = 2
            results["associated_scene"] = entry.id
            results["real_stock_dialog"] = "passed"

            # --- D) CREDITS.md written next to the plan ---
            credits = plan_path.parent / "CREDITS.md"
            assert credits.is_file(), "CREDITS.md not written"
            text = credits.read_text(encoding="utf-8")
            assert "pexels" in text and "QA Photographer" in text
            results["credits"] = str(credits)

            # --- E) Import the updated plan into the timeline and export MP4 ---
            with patch.object(ui.filedialog, "askopenfilename", return_value=str(plan_path)), \
                 patch.object(ui.messagebox, "askyesno", return_value=True):
                editor.import_plan()
                wait_for_ui(app, editor, errors)
            assert len(editor.items) == 1, f"expected 1 media scene after association, got {len(editor.items)}"
            assert Path(editor.wav_path.get()).resolve() == APPROVED_WAV.resolve()

            output = output_dir / "timeline-stage6-stock.mp4"
            with patch.object(ui.filedialog, "asksaveasfilename", return_value=str(output)):
                editor.export_button.invoke()
                wait_for_ui(app, editor, errors)
            assert editor.last_output == output and editor.open_button.instate(["!disabled"])
            verification = verify_export(output, wav_duration(APPROVED_WAV))
            run_ffmpeg("-xerror", "-i", output, "-f", "null", "-")
            results["mp4"] = str(output)
            results["verification"] = verification

            # --- F) WAV fingerprint unchanged ---
            after = {str(p): fingerprint(p) for p in protected}
            assert before == after, "The approved WAV changed during validation"
            results["approved_wav_unchanged"] = True
            results["approved_wav_sha256"] = before[str(APPROVED_WAV)]["sha256"]

            results["availability"] = tool.check_available()
            results["scope"] = ("stock search (mocked) + scene association + CREDITS.md + "
                                "scenes.json round-trip + FFmpeg export; approved WAV read-only.")
            report_path = output_dir / "validation.json"
            report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(results, ensure_ascii=True, indent=2))
    finally:
        app._close_studio()


if __name__ == "__main__":
    main()
