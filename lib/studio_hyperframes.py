"""HyperFrames test-scene helper for OpenMontage Studio (Etapa 7).

Thin wrapper around the existing `hyperframes_compose` tool: no new HTTP
clients and no new renderers. The tool owns scaffold → lint → validate →
render; this module only shapes inputs for the Studio UI, guarantees unique
output names (existing files are never overwritten) and verifies the MP4
contract (1920x1080, 30 fps, silent) with ffprobe when it is available.

Failures never raise: `render_test_scene` returns an ``ok=False`` summary
with a human-readable ``error`` so the Tk worker thread cannot crash the
Studio. Only input validation (`validate_duration`) raises `ValueError`,
which the UI reports before any work starts.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Optional

from tools.video.studio_export import NO_WINDOW

HYPERFRAMES_SOURCE = "hyperframes"
HYPERFRAMES_CREATOR = "OpenMontage Studio (HyperFrames)"
HYPERFRAMES_LICENSE = "Gerado localmente (HTML/CSS/GSAP); sem licença externa."

WIDTH, HEIGHT, FPS = 1920, 1080, 30
DEFAULT_DURATION_SECONDS = 3.0
MAX_DURATION_SECONDS = 30.0

MP4_SUBDIR = "hyperframes"
WORKSPACE_SUBDIR = "hyperframes-workspaces"

ProgressFn = Callable[[float, str], None]


def hyperframes_status() -> dict[str, Any]:
    """Availability snapshot for the HyperFrames runtime. Never raises."""
    try:
        from tools.video.hyperframes_compose import HyperFramesCompose

        tool = HyperFramesCompose()
        runtime = tool._runtime_check()
        instructions = tool.install_instructions
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "available": False,
            "reasons": [f"não foi possível consultar o runtime HyperFrames: {exc}"],
            "install_instructions": "",
            "runtime": {},
        }
    return {
        "available": bool(runtime.get("runtime_available")),
        "reasons": [str(reason) for reason in runtime.get("reasons", [])],
        "install_instructions": instructions,
        "runtime": runtime,
    }


def format_unavailable_error(status: dict[str, Any]) -> str:
    """Compose one readable message with reasons + install instructions."""
    reasons = "; ".join(status.get("reasons", [])) or "motivo não informado"
    message = f"HyperFrames indisponível nesta máquina: {reasons}."
    instructions = str(status.get("install_instructions", "")).strip()
    if instructions:
        message += f"\n\nComo habilitar:\n{instructions}"
    return message


def validate_duration(duration_seconds: Any) -> float:
    """Validate a scene duration in seconds; raises ValueError with guidance."""
    try:
        value = float(str(duration_seconds).replace(",", "."))
    except (TypeError, ValueError):
        raise ValueError("Duração: informe um número de segundos válido.") from None
    if not math.isfinite(value * FPS) or value < 1 / FPS - 0.0000005:
        raise ValueError("Duração: o mínimo é 1 quadro (1/30 s).")
    if value > MAX_DURATION_SECONDS:
        raise ValueError(
            f"Duração: máximo de {MAX_DURATION_SECONDS:.0f} s para uma cena de teste."
        )
    return value


def build_test_edit_decisions(
    text: str,
    subtitle: str = "",
    duration_seconds: float = DEFAULT_DURATION_SECONDS,
) -> dict[str, Any]:
    """Shape a minimal edit_decisions payload for one animated text card."""
    clean = str(text).strip()
    if not clean:
        raise ValueError("Texto da cena: informe um texto não vazio.")
    duration = validate_duration(duration_seconds)
    cut: dict[str, Any] = {
        "type": "text_card",
        "text": clean,
        "in_seconds": 0.0,
        "out_seconds": duration,
    }
    if str(subtitle).strip():
        cut["subtitle"] = str(subtitle).strip()
    return {
        "render_runtime": "hyperframes",
        "metadata": {"title": "Cena de teste HyperFrames"},
        "cuts": [cut],
    }


def unique_path(path: Path) -> Path:
    """Return `path`, or a non-colliding sibling — existing files are kept."""
    if not path.exists() and not path.is_symlink():
        return path
    for index in range(1, 10000):
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    return path.with_name(f"{path.stem}-{int(time.time())}{path.suffix}")


def unique_dir(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 10000):
        candidate = path.with_name(f"{path.name}-{index}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.name}-{int(time.time())}")


def probe_scene(path: Path) -> dict[str, Any]:
    """Verify the MP4 contract with ffprobe; raises ValueError when off-spec.

    When ffprobe is missing the check is skipped (probed=False) — the export
    pipeline already requires ffprobe, so this helper stays permissive.
    """
    probe = shutil.which("ffprobe")
    target = Path(path)
    if not probe:
        return {"probed": False, "width": None, "height": None, "fps": None,
                "silent": None, "duration_seconds": None}
    if not target.is_file():
        raise ValueError(f"MP4 não encontrado: {target}")
    proc = subprocess.run(
        [probe, "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height,r_frame_rate",
         "-show_entries", "format=duration", "-of", "json", str(target)],
        capture_output=True, timeout=120, creationflags=NO_WINDOW,
    )
    if proc.returncode:
        raise ValueError(
            "ffprobe não conseguiu ler o MP4 gerado: "
            + proc.stderr.decode("utf-8", "replace").strip()[:400]
        )
    try:
        data = json.loads(proc.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Resposta inválida do ffprobe: {exc}") from None
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError("O MP4 gerado não tem trilha de vídeo.")
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    rate = str(video.get("r_frame_rate", ""))
    fps_value = None
    if rate and "/" in rate:
        numerator, _, denominator = rate.partition("/")
        try:
            fps_value = round(int(numerator) / int(denominator), 3)
        except (ValueError, ZeroDivisionError):
            fps_value = None
    width = video.get("width")
    height = video.get("height")
    silent = not audio_streams
    try:
        duration = float(data.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    if width != WIDTH or height != HEIGHT or fps_value != FPS or not silent:
        raise ValueError(
            "MP4 fora do contrato: esperado "
            f"{WIDTH}×{HEIGHT} a {FPS} fps sem áudio; obtido "
            f"{width}×{height} a {fps_value} fps"
            + ("" if silent else f" com {len(audio_streams)} trilha(s) de áudio")
            + "."
        )
    return {"probed": True, "width": width, "height": height,
            "fps": fps_value, "silent": silent, "duration_seconds": duration}


def render_test_scene(
    *,
    output_dir: Path,
    text: str,
    subtitle: str = "",
    duration_seconds: Any = DEFAULT_DURATION_SECONDS,
    progress: Optional[ProgressFn] = None,
    cancel_event: Any = None,
) -> dict[str, Any]:
    """Render one animated test scene to a silent 1920x1080 30 fps MP4.

    Returns a summary dict: ``ok=True`` with ``output``/``duration_seconds``/
    ``probe``, or ``ok=False`` with a human-readable ``error`` (and
    ``cancelled=True`` when the Studio cancel event fired).
    """
    def report(fraction: float, message: str) -> None:
        if progress is None:
            return
        try:
            progress(fraction, message)
        except Exception:  # pragma: no cover - UI progress is best effort
            pass

    def failure(error: str, **extra: Any) -> dict[str, Any]:
        return {"ok": False, "error": error, "output": "", "workspace": "",
                "width": WIDTH, "height": HEIGHT, "fps": FPS,
                "duration_seconds": 0.0, **extra}

    try:
        duration = validate_duration(duration_seconds)
        edit_decisions = build_test_edit_decisions(text, subtitle, duration)
    except ValueError as exc:
        return failure(str(exc))

    report(0.03, "Verificando dependências do HyperFrames (Node, FFmpeg, npx)…")
    status = hyperframes_status()
    if not status["available"]:
        return failure(format_unavailable_error(status), cancelled=False)

    base = Path(output_dir).expanduser()
    stamp = datetime_stamp()
    output = unique_path(base / MP4_SUBDIR / f"cena-hyperframes-{stamp}.mp4")
    workspace = unique_dir(base / WORKSPACE_SUBDIR / f"cena-hyperframes-{stamp}")
    output.parent.mkdir(parents=True, exist_ok=True)
    workspace.parent.mkdir(parents=True, exist_ok=True)

    report(0.10, "Renderizando a cena HyperFrames (scaffold, lint, validação e render)…")
    try:
        from tools.video.hyperframes_compose import HyperFramesCompose

        result = HyperFramesCompose().execute({
            "operation": "render",
            "workspace_path": str(workspace),
            "output_path": str(output),
            "edit_decisions": edit_decisions,
            "asset_manifest": {},
            "fps": FPS,
            "quality": "standard",
        })
    except Exception as exc:
        return failure(f"Falha inesperada ao renderizar com o HyperFrames: {type(exc).__name__}: {exc}")

    steps = (result.data or {}).get("steps", {})
    if not result.success:
        return failure(
            f"Falha no HyperFrames: {result.error or 'erro desconhecido'}",
            steps=steps,
        )
    if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
        return {
            "ok": False, "cancelled": True,
            "error": f"Geração cancelada. MP4 já gravado em {output} (não usado na montagem).",
            "output": str(output), "workspace": str(workspace),
            "width": WIDTH, "height": HEIGHT, "fps": FPS,
            "duration_seconds": duration, "steps": steps,
        }

    report(0.9, "Verificando o MP4 gerado (1920×1080 · 30 fps · silencioso)…")
    try:
        probe = probe_scene(output)
    except ValueError as exc:
        return failure(str(exc), output=str(output), workspace=str(workspace), steps=steps)
    if not output.is_file():
        return failure(
            f"O HyperFrames terminou mas o MP4 não foi gravado: {output}",
            workspace=str(workspace), steps=steps,
        )

    real_duration = probe.get("duration_seconds") or duration
    report(1.0, f"Cena HyperFrames pronta: {output.name}")
    return {
        "ok": True,
        "error": "",
        "output": str(output),
        "workspace": str(workspace),
        "width": probe.get("width") or WIDTH,
        "height": probe.get("height") or HEIGHT,
        "fps": probe.get("fps") or FPS,
        "duration_seconds": float(real_duration),
        "silent": probe.get("silent"),
        "probed": probe.get("probed", False),
        "quality": "standard",
        "runtime_version": status["runtime"].get("npm_package_version"),
        "steps": steps,
    }


def datetime_stamp() -> str:
    from datetime import datetime

    return f"{datetime.now():%Y%m%d-%H%M%S-%f}"
