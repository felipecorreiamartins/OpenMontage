"""Reproducible local UI + FFmpeg QA using the approved WAV as read-only input.

Run from the repository: .venv/Scripts/python.exe scripts/validate_studio_stage3.py
Creates a unique QA directory under projects/openmontage-studio. No paid APIs.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.studio_timeline import APPROVED_WAV
from lib import studio_timeline_ui as ui
from openmontage_studio import OpenMontageStudio
from tools.video.studio_export import NO_WINDOW, StudioExport, verify_export, wav_duration


def run(*args):
    result = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-nostdin", "-n", *map(str, args)],
                            capture_output=True, timeout=120, creationflags=NO_WINDOW)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace"))
    return result.stdout


def fingerprint(path):
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"sha256": sha, "size": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns}


def wait_for_ui(app, editor, errors):
    deadline = time.monotonic() + 180
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


def main():
    tool = StudioExport()
    assert tool.check_available(), "FFmpeg e ffprobe precisam estar no PATH"
    output_dir = ROOT / "projects" / "openmontage-studio" / ("qa-stage3-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
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
    before = {str(p): fingerprint(p) for p in [APPROVED_WAV, *paths]}
    output = output_dir / "timeline-approved-wav-1080p.mp4"
    app = OpenMontageStudio()
    app.withdraw()
    errors = []
    try:
        with patch.object(ui.messagebox, "showerror", side_effect=lambda *a, **_k: errors.append(a)):
            editor = app._open_timeline()
            editor.withdraw()
            editor.output_dir = output_dir
            editor.add_paths(paths)
            editor.items = [replace(i, duration=1, transition=t, transition_duration=0.3)
                            for i, t in zip(editor.items, ("crossfade", "fade", "cut", "cut"))]
            editor._refresh(0)
            editor.adjust_to_wav()
            wait_for_ui(app, editor, errors)
            with patch.object(ui.filedialog, "asksaveasfilename", return_value=str(output)):
                editor.export_button.invoke()
                wait_for_ui(app, editor, errors)
            assert editor.last_output == output and editor.open_button.instate(["!disabled"])
            result = verify_export(output, wav_duration(APPROVED_WAV))
            # Decode every frame/sample, with decoding failures treated as errors.
            run("-xerror", "-i", output, "-f", "null", "-")
            # Compare with a direct AAC conversion of the untouched WAV. Exact
            # decoded equality proves that export added no gain, mix or effects.
            reference = output_dir / "approved-wav-aac-reference.m4a"
            run("-i", APPROVED_WAV, "-map", "0:a:0", "-c:a", "aac", "-b:a", "192k",
                "-map_metadata", "-1", reference)
            exported_audio = run("-i", output, "-map", "0:a:0", "-f", "s16le", "pipe:1")
            reference_audio = run("-i", reference, "-map", "0:a:0", "-f", "s16le", "pipe:1")
            assert exported_audio == reference_audio, "Export changed the approved audio beyond AAC encoding"
            run("-i", output, "-vf", "fps=4,scale=384:216,tile=4x4", "-frames:v", "1", output_dir / "frames.png")
            after = {str(p): fingerprint(p) for p in [APPROVED_WAV, *paths]}
            assert before == after, "A source changed during validation"
            report = {
                "output": str(output), "verification": result, "sources_unchanged": before == after,
                "before": before, "after": after,
                "timeline": [{**asdict(i), "path": str(i.path)} for i in editor.items],
                "ui_status": editor.status.get(), "full_decode": "passed",
                "availability": tool.check_available(),
                "audio_matches_direct_aac": exported_audio == reference_audio,
                "decoded_audio_sha256": hashlib.sha256(exported_audio).hexdigest(),
                "scope": "Synthetic local media plus the entire approved WAV; no long-form benchmark.",
            }
            (output_dir / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=True, indent=2))
    finally:
        app._close_studio()


if __name__ == "__main__":
    main()
