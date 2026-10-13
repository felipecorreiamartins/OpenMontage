"""scenes.json plan loader/saver for OpenMontage Studio timelines."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

from lib.studio_timeline import FPS, TRANSITIONS, TimelineItem, seconds_to_frames

SCENES_VERSION = "1.0"
DEFAULT_DURATION_SECONDS = 5.0
DEFAULT_TRANSITION = "cut"
DEFAULT_TRANSITION_DURATION = 0.5

_TOP_LEVEL_KEYS = frozenset({"version", "title", "wav", "scenes", "metadata"})
_SCENE_KEYS = frozenset({"id", "media", "duration_seconds", "transition", "transition_duration", "note"})


def _scene_error(position: int, scene_id: object, message: str) -> ValueError:
    label = f"Cena {position}" + (f" ({scene_id})" if isinstance(scene_id, str) and scene_id else "")
    return ValueError(f"{label}: {message}")


def _require_plain_number(value: object, message: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(message)
    return float(value)


@dataclass(frozen=True)
class SceneEntry:
    id: str
    media: Path
    duration: float = DEFAULT_DURATION_SECONDS
    transition: str = DEFAULT_TRANSITION
    transition_duration: float = DEFAULT_TRANSITION_DURATION
    note: str = ""


@dataclass(frozen=True)
class ScenePlan:
    scenes: tuple[SceneEntry, ...]
    version: str = SCENES_VERSION
    title: str = ""
    wav: Path | None = None
    metadata: dict = field(default_factory=dict)


def _resolve_plan_path(raw: str, plan_dir: Path) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = plan_dir / candidate
    return candidate.resolve()


def load_scenes(path: str | Path) -> ScenePlan:
    """Parse and fully validate a scenes.json plan; raises ValueError before any partial result."""
    plan_path = Path(path).expanduser()
    try:
        raw = plan_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Não foi possível ler o plano: {exc}") from None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON inválido no plano de cenas: {exc}") from None
    if not isinstance(data, dict):
        raise ValueError("O plano precisa ser um objeto JSON com 'version' e 'scenes'.")
    unknown = sorted(set(data) - _TOP_LEVEL_KEYS)
    if unknown:
        raise ValueError(f"Chave desconhecida no plano: {', '.join(unknown)}.")
    version = data.get("version")
    if version != SCENES_VERSION:
        raise ValueError(f"Versão do plano não suportada: {version!r} (esperado {SCENES_VERSION!r}).")
    title = data.get("title", "")
    if not isinstance(title, str):
        raise ValueError("'title' precisa ser texto.")
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("'metadata' precisa ser um objeto.")
    raw_scenes = data.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("'scenes' precisa ser uma lista com pelo menos uma cena.")
    plan_dir = plan_path.expanduser().resolve().parent
    wav_raw = data.get("wav")
    wav: Path | None = None
    if wav_raw is not None:
        if not isinstance(wav_raw, str) or not wav_raw.strip():
            raise ValueError("'wav' precisa ser um caminho de arquivo não vazio.")
        wav = _resolve_plan_path(wav_raw, plan_dir)
    entries: list[SceneEntry] = []
    seen_ids: set[str] = set()
    for index, raw_scene in enumerate(raw_scenes, start=1):
        if not isinstance(raw_scene, dict):
            raise _scene_error(index, None, "precisa ser um objeto com 'id' e 'media'.")
        unknown_scene = sorted(set(raw_scene) - _SCENE_KEYS)
        if unknown_scene:
            raise _scene_error(index, raw_scene.get("id"), f"chave desconhecida: {', '.join(unknown_scene)}.")
        scene_id = raw_scene.get("id")
        if not isinstance(scene_id, str) or not scene_id.strip():
            raise _scene_error(index, None, "'id' precisa ser um texto não vazio.")
        if scene_id in seen_ids:
            raise _scene_error(index, scene_id, f"id duplicado: {scene_id!r}.")
        seen_ids.add(scene_id)
        media_raw = raw_scene.get("media")
        if not isinstance(media_raw, str) or not media_raw.strip():
            raise _scene_error(index, scene_id, "'media' precisa ser um caminho de arquivo não vazio.")
        media = _resolve_plan_path(media_raw, plan_dir)
        if not media.is_file():
            raise _scene_error(index, scene_id, f"arquivo de mídia não encontrado: {media}")
        duration = DEFAULT_DURATION_SECONDS
        if "duration_seconds" in raw_scene:
            try:
                value = _require_plain_number(
                    raw_scene["duration_seconds"],
                    "'duration_seconds' precisa ser um número.",
                )
            except ValueError as exc:
                raise _scene_error(index, scene_id, str(exc)) from None
            if value <= 0:
                raise _scene_error(index, scene_id, "duration_seconds deve ser maior que zero.")
            try:
                duration = seconds_to_frames(value, "duration_seconds") / FPS
            except ValueError as exc:
                raise _scene_error(index, scene_id, str(exc)) from None
        transition = raw_scene.get("transition", DEFAULT_TRANSITION)
        if transition not in TRANSITIONS:
            raise _scene_error(index, scene_id, f"transição desconhecida: {transition!r}.")
        transition_duration = DEFAULT_TRANSITION_DURATION
        if "transition_duration" in raw_scene:
            try:
                value = _require_plain_number(
                    raw_scene["transition_duration"],
                    "'transition_duration' precisa ser um número.",
                )
            except ValueError as exc:
                raise _scene_error(index, scene_id, str(exc)) from None
            if value <= 0:
                raise _scene_error(index, scene_id, "transition_duration deve ser maior que zero.")
            try:
                transition_duration = seconds_to_frames(value, "transition_duration") / FPS
            except ValueError as exc:
                raise _scene_error(index, scene_id, str(exc)) from None
        note = raw_scene.get("note", "")
        if not isinstance(note, str):
            raise _scene_error(index, scene_id, "'note' precisa ser texto.")
        entries.append(SceneEntry(
            id=scene_id,
            media=media,
            duration=duration,
            transition=transition,
            transition_duration=transition_duration,
            note=note,
        ))
    return ScenePlan(scenes=tuple(entries), title=title, wav=wav, metadata=metadata)


def scenes_to_items(plan: ScenePlan) -> list[TimelineItem]:
    """Convert a validated plan into frame-quantized timeline items."""
    return [
        TimelineItem(
            path=entry.media,
            duration=entry.duration,
            transition=entry.transition,
            transition_duration=entry.transition_duration,
        )
        for entry in plan.scenes
    ]


def save_scenes(path: str | Path, items: list[TimelineItem] | tuple[TimelineItem, ...],
                *, title: str = "", wav: Path | str | None = None,
                metadata: dict | None = None) -> Path:
    """Write timeline items as a frame-quantized scenes.json plan."""
    if not items:
        raise ValueError("Adicione pelo menos uma imagem ou um clipe antes de exportar o plano.")
    if not isinstance(title, str):
        raise ValueError("'title' precisa ser texto.")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("'metadata' precisa ser um objeto.")
    scenes = []
    for position, item in enumerate(items, start=1):
        scenes.append({
            "id": f"cena-{position:02d}",
            "media": str(item.path),
            "duration_seconds": item.frames / FPS,
            "transition": item.transition,
            "transition_duration": seconds_to_frames(item.transition_duration) / FPS,
            "note": "",
        })
    payload: dict = {"version": SCENES_VERSION, "scenes": scenes}
    if title:
        payload["title"] = title
    if wav is not None:
        payload["wav"] = str(wav)
    if metadata is not None:
        payload["metadata"] = metadata
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination.resolve()


def quantize_items(items: list[TimelineItem] | tuple[TimelineItem, ...]) -> list[TimelineItem]:
    """Snap durations to whole frames the way a load(save(items)) round-trip does."""
    return [
        replace(
            item,
            duration=item.frames / FPS,
            transition_duration=seconds_to_frames(item.transition_duration) / FPS,
        )
        for item in items
    ]
