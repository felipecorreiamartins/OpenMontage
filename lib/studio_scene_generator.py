"""Local narration-to-scenes.json planner. No APIs, no invented media files."""

from __future__ import annotations

import math
import re
from pathlib import Path

from lib.studio_scenes import (
    DEFAULT_TRANSITION_DURATION, SCENES_VERSION, SceneEntry, ScenePlan, save_plan,
)
from lib.studio_timeline import FPS, audio_frames, seconds_to_frames

MIN_SCENE_SECONDS = 2.0
MAX_SENTENCES_PER_SCENE = 3
_MAX_NOTE_WORDS = 12

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def split_narration_scenes(text: str) -> list[str]:
    """Split narration into scene-sized text segments (paragraphs, then sentences)."""
    if not isinstance(text, str):
        raise ValueError("O texto da narração precisa ser uma string.")
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        raise ValueError("Cole ou escreva o texto da narração antes de gerar o plano.")
    segments: list[str] = []
    for paragraph in re.split(r"\n\s*\n", cleaned):
        paragraph = _normalize_whitespace(paragraph)
        if not paragraph:
            continue
        sentences = [s for s in (_normalize_whitespace(part) for part in _SENTENCE_SPLIT.split(paragraph)) if s]
        if not sentences:
            continue
        buffer: list[str] = []
        for sentence in sentences:
            buffer.append(sentence)
            if len(buffer) >= MAX_SENTENCES_PER_SCENE:
                segments.append(" ".join(buffer))
                buffer = []
        if buffer:
            if segments and len(buffer) == 1 and len(segments[-1].split()) < 4:
                segments[-1] = f"{segments[-1]} {buffer[0]}"
            else:
                segments.append(" ".join(buffer))
    if not segments:
        raise ValueError("Não foi possível derivar cenas do texto da narração.")
    return segments


def visual_note(segment: str) -> str:
    """Planning hint derived from the segment itself — never invents media paths."""
    words = segment.split()
    snippet = " ".join(words[:_MAX_NOTE_WORDS])
    if len(words) > _MAX_NOTE_WORDS:
        snippet += "…"
    return f"Planejar imagem/clipe para: {snippet}"


def _distribute_frames(word_counts: list[int], total_frames: int, count: int) -> list[int]:
    total_words = sum(word_counts)
    if total_words <= 0:
        raise ValueError("O texto da narração não contém palavras para distribuir durações.")
    min_frames = max(1, int(math.floor(MIN_SCENE_SECONDS * FPS)))
    if count * min_frames > total_frames:
        if count > total_frames:
            raise ValueError(
                f"O WAV tem só {total_frames} quadro(s) para {count} cena(s); "
                "reduza o número de cenas ou use um WAV mais longo."
            )
        base = total_frames // count
        frames = [base] * count
        for index in range(total_frames - base * count):
            frames[index] += 1
        return frames
    frames = [max(min_frames, total_frames * weight // total_words) for weight in word_counts]
    drift = total_frames - sum(frames)
    order = sorted(range(count), key=lambda i: (-word_counts[i], i))
    step = 1 if drift >= 0 else -1
    remaining = abs(drift)
    position = 0
    while remaining:
        index = order[position % count]
        if frames[index] + step >= min_frames:
            frames[index] += step
            remaining -= 1
        position += 1
        if position > count * (abs(drift) + 1) + count:
            break
    return frames


def generate_plan(text: str, wav_duration: float, *, title: str = "",
                  wav: Path | str | None = None) -> ScenePlan:
    """Build a planning-only ScenePlan with durations proportional to the WAV."""
    if isinstance(wav_duration, bool) or not isinstance(wav_duration, (int, float)):
        raise ValueError("A duração do WAV precisa ser um número de segundos.")
    wav_duration = float(wav_duration)
    if not math.isfinite(wav_duration) or wav_duration <= 0:
        raise ValueError("A duração do WAV precisa ser positiva e finita.")
    segments = split_narration_scenes(text)
    word_counts = [max(1, len(segment.split())) for segment in segments]
    total_frames = audio_frames(wav_duration)
    frames = _distribute_frames(word_counts, total_frames, len(segments))
    transitions = ("crossfade", "cut", "fade", "cut")
    entries = []
    for index, (segment, frame_count) in enumerate(zip(segments, frames)):
        entries.append(SceneEntry(
            id=f"cena-{index + 1:02d}",
            media=None,
            duration=frame_count / FPS,
            transition=transitions[index % len(transitions)],
            transition_duration=DEFAULT_TRANSITION_DURATION,
            note=visual_note(segment),
            narration=segment,
        ))
    return ScenePlan(
        scenes=tuple(entries),
        version=SCENES_VERSION,
        title=title,
        wav=Path(wav) if wav is not None else None,
        metadata={
            "generated_by": "studio_scene_generator",
            "wav_duration_seconds": wav_duration,
            "scene_count": len(entries),
            "planning_only": True,
        },
    )


def generate_plan_file(text: str, wav_duration: float, destination: str | Path,
                       *, title: str = "", wav: Path | str | None = None) -> Path:
    """Generate a planning scenes.json and write it to disk."""
    plan = generate_plan(text, wav_duration, title=title, wav=wav)
    return save_plan(destination, plan)
