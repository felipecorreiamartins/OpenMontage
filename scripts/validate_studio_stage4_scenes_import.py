"""Reproducible local QA for scenes.json import/export + FFmpeg export (stage 4).

Run from the repository: .venv/Scripts/python.exe scripts/validate_studio_stage4_scenes_import.py
Uses synthetic media plus the approved WAV as a read-only input. No paid APIs.
Never modifies the approved narration WAV or the approved mix profile.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.studio_scenes import load_scenes, save_scenes, scenes_to_items
from lib.studio_timeline import APPROVED_WAV, TimelineItem
from lib import studio_timeline_ui as ui
from openmontage_studio import OpenMontageStudio
from tools.video.studio_export import NO_WINDOW, StudioExport, verify_export, wav_duration


def run(*args):
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
    deadline = time.monotonic() + 300
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


def write_plan(path, media_paths, wav=None, duration=1.0, transitions=("crossfade", "fade", "cut", "cut")):
    scenes = []
    for index, media in enumerate(media_paths):
        scene = {
            "id": f"cena-{index + 1:02d}",
            "media": str(media),
            "duration_seconds": duration,
            "transition": transitions[index % len(transitions)],
            "transition_duration": 0.3,
            "note": f"QA scene {index + 1}",
        }
        scenes.append(scene)
    payload = {"version": "1.0", "title": "QA Stage 4", "scenes": scenes,
               "metadata": {"generated_by": "validate_studio_stage4"}}
    if wav is not None:
        payload["wav"] = str(wav)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main():
    tool = StudioExport()
    assert tool.check_available(), "FFmpeg e ffprobe precisam estar no PATH"
    assert APPROVED_WAV.is_file(), f"WAV aprovado não encontrado: {APPROVED_WAV}"

    output_dir = ROOT / "projects" / "openmontage-studio" / ("qa-stage4-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    output_dir.mkdir(parents=True, exist_ok=False)
    sources = output_dir / "sources"
    sources.mkdir()
    red, blue, green = [sources / name for name in ("01-red.png", "03-blue.png", "04-green.png")]
    clip = sources / "02-moving-portrait.mp4"
    for path, color in ((red, "red"), (blue, "blue"), (green, "lime")):
        run("-f", "lavfi", "-i", f"color={color}:s=640x360", "-frames:v", "1", path)
    run("-f", "lavfi", "-i", "testsrc2=s=240x400:r=24:d=0.5", "-f", "lavfi", "-i",
        "sine=frequency=1800:duration=0.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", clip)
    paths = [red, clip, blue, green]
    other_wav = output_dir / "not-approved.wav"
    run("-f", "lavfi", "-i", "sine=frequency=220:duration=1", str(other_wav))

    protected = [APPROVED_WAV, other_wav, *paths]
    before = {str(p): fingerprint(p) for p in protected}

    app = OpenMontageStudio()
    app.withdraw()
    errors = []
    results = {}
    try:
        with patch.object(ui.messagebox, "showerror", side_effect=lambda *a, **_k: errors.append(a)):
            editor = app._open_timeline()
            editor.withdraw()
            editor.output_dir = output_dir

            # --- A) Import a plan into an empty timeline (wav == approved) ---
            plan_path = write_plan(output_dir / "plan-import.json", paths, wav=APPROVED_WAV)
            confirmations = []
            with patch.object(ui.filedialog, "askopenfilename", return_value=str(plan_path)), \
                 patch.object(ui.messagebox, "askyesno",
                              side_effect=lambda *a, **k: confirmations.append(a[0] if a else "") or True):
                editor.import_plan()
                wait_for_ui(app, editor, errors)
            assert len(editor.items) == 4, f"expected 4 imported scenes, got {len(editor.items)}"
            assert Path(editor.wav_path.get()).resolve() == APPROVED_WAV.resolve()
            assert not confirmations, f"no confirmation expected when importing into an empty timeline with the approved WAV: {confirmations}"
            results["import_scenes"] = len(editor.items)
            results["import_auto_fit"] = editor.status.get()

            # --- B) Export MP4 through the UI from the imported plan ---
            output = output_dir / "timeline-stage4-approved-wav-1080p.mp4"
            with patch.object(ui.filedialog, "asksaveasfilename", return_value=str(output)):
                editor.export_button.invoke()
                wait_for_ui(app, editor, errors)
            assert editor.last_output == output and editor.open_button.instate(["!disabled"])
            verification = verify_export(output, wav_duration(APPROVED_WAV))
            run("-xerror", "-i", output, "-f", "null", "-")
            reference = output_dir / "approved-wav-aac-reference.m4a"
            run("-i", APPROVED_WAV, "-map", "0:a:0", "-c:a", "aac", "-b:a", "192k",
                "-map_metadata", "-1", reference)
            exported_audio = run("-i", output, "-map", "0:a:0", "-f", "s16le", "pipe:1")
            reference_audio = run("-i", reference, "-map", "0:a:0", "-f", "s16le", "pipe:1")
            assert exported_audio == reference_audio, "Export changed the approved audio beyond AAC encoding"
            run("-i", output, "-vf", "fps=4,scale=384:216,tile=4x4", "-frames:v", "1", output_dir / "frames.png")
            results["mp4"] = str(output)
            results["verification"] = verification
            results["audio_matches_direct_aac"] = True

            # --- C) Export plan (scenes.json) from the timeline and reload it ---
            exported_plan = output_dir / "plan-exported.json"
            with patch.object(ui.filedialog, "asksaveasfilename", return_value=str(exported_plan)):
                editor.export_plan()
            assert not errors and exported_plan.is_file()
            reloaded = load_scenes(exported_plan)
            assert scenes_to_items(reloaded) == editor.items, "Round-tripped plan does not match the timeline"
            assert reloaded.wav == APPROVED_WAV.resolve()
            results["exported_plan"] = str(exported_plan)
            results["plan_roundtrip"] = "passed"

            # --- D) Atomic import: a missing file blocks the whole plan ---
            keep_items = list(editor.items)
            atomic_plan = write_plan(output_dir / "plan-atomic.json",
                                     [paths[0], output_dir / "missing-scene.mp4"])
            errors.clear()
            with patch.object(ui.filedialog, "askopenfilename", return_value=str(atomic_plan)), \
                 patch.object(ui.messagebox, "askyesno", return_value=True):
                editor.import_plan()
            assert errors, "atomic import of a plan with a missing file must report an error"
            assert "arquivo de mídia não encontrado" in str(errors[0][1])
            assert editor.items == keep_items, "failed import must not touch the timeline"
            assert Path(editor.wav_path.get()).resolve() == APPROVED_WAV.resolve()
            results["atomic_import"] = "blocked_and_preserved"
            errors.clear()

            # --- E) Plan with a different WAV: declining keeps the approved WAV ---
            swap_plan = write_plan(output_dir / "plan-other-wav.json", [red], wav=other_wav)
            prompts = []

            def wav_only_swap_confirm(*args, **_kwargs):
                message = args[0] if args else ""
                prompts.append(message)
                return "Substituir timeline" in message

            with patch.object(ui.filedialog, "askopenfilename", return_value=str(swap_plan)), \
                 patch.object(ui.messagebox, "askyesno", side_effect=wav_only_swap_confirm):
                editor.import_plan()
                wait_for_ui(app, editor, errors)
            assert any("Trocar WAV" in prompt for prompt in prompts), prompts
            assert Path(editor.wav_path.get()).resolve() == APPROVED_WAV.resolve(), "declined WAV swap must keep the approved WAV"
            assert len(editor.items) == 1, "items should import even when the WAV swap is declined"
            results["wav_swap_declined"] = "approved_wav_preserved"

            after = {str(p): fingerprint(p) for p in protected}
            assert before == after, "A protected source changed during validation"
            results["sources_unchanged"] = True
            results["fingerprints"] = {"before": before, "after": after}
            results["full_decode"] = "passed"
            results["availability"] = tool.check_available()
            results["approved_wav_sha256"] = before[str(APPROVED_WAV)]["sha256"]
            results["ui_status"] = editor.status.get()
            results["scope"] = ("scenes.json import/export + FFmpeg export; synthetic local media "
                                "plus the entire approved WAV as read-only input.")
            report_path = output_dir / "validation.json"
            report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(results, ensure_ascii=True, indent=2))
    finally:
        app._close_studio()


if __name__ == "__main__":
    main()
