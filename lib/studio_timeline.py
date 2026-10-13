"""Frame-based, non-destructive timeline model for OpenMontage Studio."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path

FPS = 30
WIDTH, HEIGHT = 1920, 1080
TRANSITIONS = ("cut", "crossfade", "fade")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpg", ".mpeg"}
APPROVED_WAV = Path(r"D:\YouTube-Automacao\Audios\audio_final_documentario.wav")


def seconds_to_frames(value: float | str, label: str = "Duração") -> int:
    try:
        seconds = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        raise ValueError(f"{label}: informe um número de segundos válido.") from None
    # The editor displays six decimals; accept its rounded representation of
    # one frame, while still rejecting genuinely shorter/invalid durations.
    if not math.isfinite(seconds * FPS) or seconds < 1 / FPS - 0.0000005:
        raise ValueError(f"{label}: o mínimo é 1 quadro (1/30 s).")
    return int(math.floor(seconds * FPS + 0.5))


def audio_frames(duration: float) -> int:
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("O WAV precisa ter duração positiva e finita.")
    # Cover the entire audio; the last frame can exceed it by less than 1/30 s.
    return max(1, math.ceil(duration * FPS - 1e-8))


@dataclass(frozen=True)
class TimelineItem:
    path: Path
    duration: float = 5.0
    transition: str = "cut"  # transition from this item to the next
    transition_duration: float = 0.5

    @property
    def frames(self) -> int:
        return seconds_to_frames(self.duration)


def transition_frames(items: list[TimelineItem] | tuple[TimelineItem, ...]) -> list[int]:
    if not items:
        raise ValueError("Adicione pelo menos uma imagem ou um clipe à timeline.")
    overlaps = []
    for index, item in enumerate(items):
        if item.transition not in TRANSITIONS:
            raise ValueError(f"Item {index + 1}: transição desconhecida.")
        item.frames
        overlaps.append(
            seconds_to_frames(item.transition_duration, "Duração da transição")
            if index < len(items) - 1 and item.transition != "cut" else 0
        )
    return overlaps


def timeline_frames(items: list[TimelineItem] | tuple[TimelineItem, ...]) -> int:
    overlaps = transition_frames(items)
    for index, item in enumerate(items):
        incoming = overlaps[index - 1] if index else 0
        if item.frames <= incoming + overlaps[index]:
            raise ValueError(
                f"Item {index + 1}: aumente a duração ou reduza as transições; "
                "as transições de entrada e saída precisam caber no item."
            )
    return sum(item.frames for item in items) - sum(overlaps)


def fit_to_audio(items: list[TimelineItem], duration: float) -> list[TimelineItem]:
    """Distribute whole frames, keeping transitions fixed and a visible body per item."""
    overlaps = transition_frames(items)
    minimum = [(overlaps[i - 1] if i else 0) + overlaps[i] + 1 for i in range(len(items))]
    available = audio_frames(duration) + sum(overlaps) - sum(minimum)
    if available < 0:
        raise ValueError("O WAV é curto demais. Reduza as transições ou remova itens.")
    if (all(item.frames >= floor for item, floor in zip(items, minimum))
            and sum(item.frames for item in items) - sum(overlaps) == audio_frames(duration)):
        return list(items)
    weights = [max(1, item.frames - floor) for item, floor in zip(items, minimum)]
    total_weight = sum(weights)
    portions = [available * weight // total_weight for weight in weights]
    remainders = [available * weight % total_weight for weight in weights]
    for i in sorted(range(len(items)), key=lambda i: (-remainders[i], i))[:available - sum(portions)]:
        portions[i] += 1
    return [replace(item, duration=(floor + part) / FPS) for item, floor, part in zip(items, minimum, portions)]


def move_item(items: list[TimelineItem], index: int, offset: int) -> int:
    target = index + offset
    if not 0 <= index < len(items) or not 0 <= target < len(items):
        raise ValueError("Não há item nessa posição da timeline.")
    items.insert(target, items.pop(index))
    return target
