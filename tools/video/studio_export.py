"""Isolated local timeline exporter. Does not change any pipeline renderer."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable

from lib.studio_timeline import (
    FPS, HEIGHT, WIDTH, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS,
    TimelineItem, audio_frames, timeline_frames, transition_frames,
)
from tools.base_tool import BaseTool, ToolResult, ToolRuntime, ToolStability, ToolStatus, ToolTier

Progress = Callable[[float, str], None]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ExportCancelled(RuntimeError):
    pass


def _check_cancel(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise ExportCancelled("Exportação cancelada. Os arquivos originais foram preservados.")


def probe_media(path: str | Path) -> dict:
    source = Path(path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError(f"Selecione um arquivo local: {source}")
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe não encontrado no PATH. Verifique a instalação do FFmpeg.")
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_format",
         "-show_streams", "-of", "json", str(source)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        creationflags=NO_WINDOW,
    )
    if result.returncode:
        raise ValueError(f"Não foi possível ler {source.name}: {result.stderr[-1500:]}")
    return json.loads(result.stdout)


def wav_duration(path: str | Path) -> float:
    data = probe_media(path)
    if data.get("format", {}).get("format_name") != "wav":
        raise ValueError("Selecione um áudio no formato WAV.")
    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    if not streams:
        raise ValueError("O WAV não contém uma faixa de áudio.")
    try:
        duration = float(streams[0].get("duration") or data["format"]["duration"])
        audio_frames(duration)
    except (KeyError, TypeError, ValueError):
        raise ValueError("Não foi possível determinar a duração do WAV.") from None
    return duration


def _run_ffmpeg(args: list[str], cancel: threading.Event | None, timeout: float) -> None:
    _check_cancel(cancel)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
               "-filter_threads", "1", "-filter_complex_threads", "1", *args]
    # Drain stderr to disk so neither a full pipe nor a large error can hang the GUI.
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=errors, creationflags=NO_WINDOW)
        started = time.monotonic()
        try:
            while process.poll() is None:
                _check_cancel(cancel)
                if time.monotonic() - started > timeout:
                    raise RuntimeError("FFmpeg excedeu o tempo limite deste trecho.")
                try:
                    process.wait(timeout=0.15)
                except subprocess.TimeoutExpired:
                    pass
            _check_cancel(cancel)
            if process.returncode:
                errors.seek(max(0, errors.tell() - 4000))
                raise RuntimeError("FFmpeg não concluiu o trecho: " + errors.read().decode("utf-8", "replace"))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def _input_args(item: TimelineItem) -> list[str]:
    args = ["-protocol_whitelist", "file,pipe", "-threads", "2"]
    if item.path.suffix.lower() in IMAGE_EXTENSIONS:
        args += ["-loop", "1", "-framerate", str(FPS)]
    return [*args, "-i", str(item.path)]


def _segment_filter(item: TimelineItem, start: int, count: int) -> str:
    # Expand anamorphic pixels first; then fit without cropping or distortion.
    # Clones extend a short clip; a longer clip is trimmed, never sped up.
    return (
        f"setpts=PTS-STARTPTS,fps={FPS},"
        "scale=trunc(iw*sar/2)*2:ih,setsar=1,"
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"format=yuv420p,tpad=stop_mode=clone:stop_duration={item.frames / FPS:.9f},"
        f"trim=start_frame={start}:end_frame={start + count},"
        f"settb=1/{FPS},setpts=N"
    )


def _encoding(frames: int) -> list[str]:
    return ["-an", "-frames:v", str(frames), "-c:v", "libx264", "-preset", "medium",
            "-crf", "20", "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-fps_mode", "cfr", "-threads", "2", "-video_track_timescale", "90000",
            "-map_metadata", "-1"]


def verify_export(path: Path, duration: float) -> dict:
    data = probe_media(path)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    expected_frames = audio_frames(duration)
    if (video.get("codec_name"), video.get("width"), video.get("height"),
            video.get("avg_frame_rate"), video.get("pix_fmt")) != ("h264", WIDTH, HEIGHT, "30/1", "yuv420p"):
        raise RuntimeError("O MP4 não corresponde ao perfil H.264, 1920x1080, 30 fps, yuv420p.")
    if int(video.get("nb_frames", 0)) != expected_frames:
        raise RuntimeError("O número de quadros exportados não corresponde à duração do WAV.")
    if audio.get("codec_name") != "aac" or abs(float(audio.get("duration", 0)) - duration) > 0.05:
        raise RuntimeError("O áudio do MP4 está ausente ou não corresponde à duração completa do WAV.")
    if abs(float(video.get("start_time", 0)) - float(audio.get("start_time", 0))) > 1 / FPS:
        raise RuntimeError("Os inícios do áudio e do vídeo não estão sincronizados.")
    if abs(float(video.get("duration", 0)) - expected_frames / FPS) > 1 / FPS:
        raise RuntimeError("A duração do vídeo exportado é inconsistente.")
    return {"width": WIDTH, "height": HEIGHT, "fps": FPS, "video_codec": "h264",
            "audio_codec": "aac", "frames": expected_frames, "wav_duration": duration,
            "video_duration": float(video["duration"]), "audio_duration": float(audio["duration"])}


def render_timeline(items: list[TimelineItem], wav: Path, output: Path,
                    progress: Progress | None = None, cancel: threading.Event | None = None) -> dict:
    """Render disjoint bodies and transitions; bounded memory, no giant filter graph."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg não encontrado no PATH.")
    _check_cancel(cancel)
    items = [replace(item, path=Path(item.path).expanduser().resolve(strict=True)) for item in items]
    wav = Path(wav).expanduser().resolve(strict=True)
    output = Path(output).expanduser().absolute()
    # Check before resolving, so a dangling symlink cannot become an output target.
    if output.exists() or output.is_symlink():
        raise FileExistsError("O destino já existe. Escolha um novo nome; nenhum arquivo será sobrescrito.")
    output = output.resolve()
    if output.suffix.lower() != ".mp4":
        raise ValueError("O arquivo de saída precisa ter a extensão .mp4.")
    if output in {wav, *(item.path for item in items)}:
        raise ValueError("A saída não pode substituir uma mídia original ou o WAV.")
    frame_count = timeline_frames(items)
    duration = wav_duration(wav)
    if frame_count != audio_frames(duration):
        raise ValueError(
            f"Timeline: {frame_count / FPS:.3f} s; WAV: {duration:.3f} s. "
            "Use Ajustar ao WAV antes de exportar."
        )
    for path in {item.path for item in items}:
        _check_cancel(cancel)
        if path.suffix.lower() not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
            raise ValueError(f"Formato de mídia não suportado: {path.name}")
        metadata = probe_media(path)
        if not any(s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
                   for s in metadata.get("streams", [])):
            raise ValueError(f"O arquivo não contém imagem ou vídeo: {path.name}")
        if path.suffix.lower() in VIDEO_EXTENSIONS:
            try:
                media_duration = float(metadata.get("format", {}).get("duration", 0))
            except (ValueError, TypeError):
                media_duration = 0
            if not math.isfinite(media_duration) or media_duration <= 0:
                raise ValueError(f"Duração de clipe inválida: {path.name}")
    # Detect accidental source edits during export before publishing any result.
    sources = {wav, *(item.path for item in items)}
    original_stats = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in sources}
    overlaps = transition_frames(items)
    total_parts = len(items) + sum(bool(n) for n in overlaps)
    done = 0

    def report(fraction: float, message: str) -> None:
        if progress:
            progress(fraction, message)

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".studio-export-", dir=output.parent) as temporary:
        work = Path(temporary).resolve()
        if not work.is_relative_to(output.parent.resolve()):
            raise RuntimeError("Diretório temporário fora da pasta de exportação.")
        parts: list[Path] = []
        for index, item in enumerate(items):
            incoming = overlaps[index - 1] if index else 0
            body_frames = item.frames - incoming - overlaps[index]
            part = work / f"part-{len(parts):05d}.mp4"
            report(done / (total_parts + 2), f"Renderizando item {index + 1}/{len(items)}: {item.path.name}")
            _run_ffmpeg([*_input_args(item), "-map", "0:v:0", "-vf",
                         _segment_filter(item, incoming, body_frames), *_encoding(body_frames), str(part)],
                        cancel, max(120, item.frames / FPS * 30))
            parts.append(part)
            done += 1
            overlap = overlaps[index]
            if overlap:
                next_item = items[index + 1]
                transition = "fade" if item.transition == "crossfade" else "fadeblack"
                graph = (
                    f"[0:v:0]{_segment_filter(item, item.frames - overlap, overlap)}[a];"
                    f"[1:v:0]{_segment_filter(next_item, 0, overlap)}[b];"
                    f"[a][b]xfade=transition={transition}:duration={overlap / FPS:.9f}:offset=0[v]"
                )
                part = work / f"part-{len(parts):05d}.mp4"
                report(done / (total_parts + 2), f"Aplicando {item.transition} após item {index + 1}")
                _run_ffmpeg([*_input_args(item), *_input_args(next_item), "-filter_complex", graph,
                             "-map", "[v]", *_encoding(overlap), str(part)],
                            cancel, max(120, item.frames / FPS * 30))
                parts.append(part)
                done += 1
        # Only generated relative names appear in the concat file, never user paths.
        playlist = work / "parts.txt"
        playlist.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
        rendered = work / "result.mp4"
        report(done / (total_parts + 2), "Sincronizando o WAV completo e finalizando o MP4…")
        _run_ffmpeg(["-f", "concat", "-safe", "1", "-i", str(playlist),
                     "-protocol_whitelist", "file,pipe", "-i", str(wav),
                     "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                     "-movflags", "+faststart", "-map_metadata", "-1", str(rendered)],
                    cancel, max(120, duration * 10))
        report((done + 1) / (total_parts + 2), "Conferindo resolução, codecs, quadros e sincronização…")
        verified = verify_export(rendered, duration)
        for path, original in original_stats.items():
            if (path.stat().st_size, path.stat().st_mtime_ns) != original:
                raise RuntimeError(f"A fonte mudou durante a exportação: {path.name}. Exporte novamente.")
        _check_cancel(cancel)
        # Exclusive creation also protects against a destination appearing during render.
        with output.open("xb") as destination:
            try:
                with rendered.open("rb") as source:
                    while chunk := source.read(1024 * 1024):
                        _check_cancel(cancel)
                        destination.write(chunk)
            except BaseException:
                destination.close()
                output.unlink()  # only the incomplete file created exclusively above
                raise
        report(1.0, "MP4 exportado e verificado.")
    return {"output": str(output), **verified}


class StudioExport(BaseTool):
    name = "studio_export"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "video_post"
    provider = "ffmpeg"
    runtime = ToolRuntime.LOCAL
    stability = ToolStability.BETA
    dependencies = ["cmd:ffmpeg", "cmd:ffprobe"]
    install_instructions = "FFmpeg com libx264, AAC e xfade, e ffprobe no PATH. https://ffmpeg.org/download.html"
    agent_skills = ["ffmpeg"]
    capabilities = ["local_timeline", "cut", "crossfade", "fade", "wav_sync", "mp4_export"]
    input_schema = {
        "type": "object", "required": ["items", "wav_path", "output_path"],
        "properties": {
            "items": {"type": "array", "minItems": 1, "items": {
                "type": "object", "required": ["path", "duration"], "properties": {
                    "path": {"type": "string"}, "duration": {"type": "number", "exclusiveMinimum": 0},
                    "transition": {"enum": ["cut", "crossfade", "fade"]},
                    "transition_duration": {"type": "number", "exclusiveMinimum": 0},
                }}},
            "wav_path": {"type": "string"}, "output_path": {"type": "string"},
        },
    }
    side_effects = ["creates a new MP4, never overwrites sources or existing outputs"]
    user_visible_verification = ["Play the MP4 and inspect transitions and WAV synchronization"]

    def check_available(self) -> bool:
        """Compatibility probe; keep dependency checks in the BaseTool contract.

        This checks the required binaries, not their codec/filter support. A real
        export and verify_export remain necessary to validate the installed build.
        """
        return self.get_status() == ToolStatus.AVAILABLE

    def execute(self, inputs: dict, *, progress: Progress | None = None,
                cancel: threading.Event | None = None) -> ToolResult:
        try:
            items = [TimelineItem(path=Path(i["path"]), duration=i["duration"],
                                  transition=i.get("transition", "cut"),
                                  transition_duration=i.get("transition_duration", 0.5)) for i in inputs["items"]]
            result = render_timeline(items, Path(inputs["wav_path"]), Path(inputs["output_path"]), progress, cancel)
            return ToolResult(success=True, data=result, artifacts=[result["output"]], cost_usd=0)
        except ExportCancelled as exc:
            return ToolResult(success=False, data={"cancelled": True}, error=str(exc))
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
