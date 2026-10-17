"""Thin stock-search helper for OpenMontage Studio (Etapa 6).

Wraps the existing stock_sources / direct_clip_search tools without
re-implementing HTTP, adapters, or downloads. All side effects
(download, thumbnail, API calls) live inside the tool; this module only
shapes inputs/outputs for the Studio UI and attaches provenance to
SceneEntry values.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from lib.studio_scenes import SceneEntry
from lib.studio_timeline import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS

STOCK_SOURCE_NAMES = ("pexels", "pixabay_video", "wikimedia")
STOCK_DOWNLOAD_SUBDIR = "stock"

_KIND_CHOICES = ("video", "image", "any")


def available_stock_source_names() -> list[str]:
    """Return which of the three Studio sources are currently available."""
    from tools.video.stock_sources import available_sources

    names = {s.name for s in available_sources()}
    return [name for name in STOCK_SOURCE_NAMES if name in names]


def stock_install_instructions(missing: list[str]) -> str:
    """Human-readable setup hint for sources that are not available."""
    lines: list[str] = []
    for name in missing:
        if name == "pexels":
            lines.append("  PEXELS_API_KEY — free at https://www.pexels.com/api/")
        elif name == "pixabay_video":
            lines.append("  PIXABAY_API_KEY — free at https://pixabay.com/api/docs/")
        elif name == "wikimedia":
            lines.append("  wikimedia — works without an API key (network only)")
        else:
            lines.append(f"  {name}")
    return "\n".join(lines)


def normalize_kind(kind: str) -> str:
    if kind not in _KIND_CHOICES:
        raise ValueError(f"kind inválido: {kind!r} (esperado video, image ou any)")
    return kind


def build_search_input(
    *,
    query: str,
    output_dir: Path,
    kind: str = "video",
    sources: list[str] | None = None,
    clips_per_query: int = 3,
    timeout_seconds: float = 120.0,
    slot_id: str | None = None,
) -> dict[str, Any]:
    """Shape a DirectClipSearch.execute() input dict."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query precisa ser um texto não vazio.")
    normalized_kind = normalize_kind(kind)
    count = max(1, min(int(clips_per_query), 20))
    query_entry: dict[str, Any] = {"query": query.strip(), "kind": normalized_kind}
    if slot_id:
        query_entry["slot_id"] = slot_id
    payload: dict[str, Any] = {
        "output_dir": str(output_dir),
        "queries": [query_entry],
        "clips_per_query": count,
        "timeout_seconds": max(1.0, float(timeout_seconds)),
    }
    if sources:
        payload["sources"] = list(sources)
    return payload


def run_stock_search(inputs: dict[str, Any]) -> dict[str, Any]:
    """Run DirectClipSearch and return a plain dict summary for the UI.

    Never raises for tool-level failures — returns ok=False with error.
    """
    from tools.video.direct_clip_search import DirectClipSearch

    result = DirectClipSearch().execute(inputs)
    # A timeout is unsuccessful but can still carry downloaded candidates.
    data = result.data or {}
    return {
        "ok": result.success,
        "error": (result.error or "Falha na busca de mídia stock.") if not result.success else "",
        "clips": list(data.get("clips", [])),
        "errors": list(data.get("errors", [])),
        "timed_out": bool(data.get("timed_out", False)),
        "resolved_sources": list(data.get("resolved_sources", [])),
    }


def stock_clip_path(clip: dict[str, Any]) -> Path:
    """Validate a downloaded candidate before associating or adding it."""
    raw = clip.get("path")
    if not isinstance(raw, (str, Path)) or not str(raw).strip():
        raise ValueError("O clipe selecionado não tem caminho de arquivo.")
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Arquivo de mídia não encontrado: {path}")
    if path.suffix.lower() not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
        raise ValueError(f"Imagem ou clipe não suportado: {path.name}")
    return path


def scene_with_clip(entry: SceneEntry, clip: dict[str, Any]) -> SceneEntry:
    """Return a copy of entry with media + provenance filled from a clip record."""
    path = stock_clip_path(clip)
    return replace(
        entry,
        media=path,
        source=str(clip.get("source", "")),
        source_id=str(clip.get("source_id", "")),
        source_url=str(clip.get("source_url", "")),
        creator=str(clip.get("creator", "")),
        license=str(clip.get("license", "")),
    )


def _credits_line(entry: SceneEntry) -> str:
    source = entry.source or "?"
    creator = entry.creator or "desconhecido"
    license_text = entry.license or "licença não informada"
    link = entry.source_url or ""
    line = f"- `{entry.id}` — {source} | {creator} | {license_text}"
    if link:
        line += f" | {link}"
    return line


def write_credits(scenes: tuple[SceneEntry, ...] | list[SceneEntry], path: Path) -> Path:
    """Write a CREDITS.md listing every scene with stock provenance."""
    with_prov = [entry for entry in scenes if entry.has_provenance]
    lines = [
        "# Créditos de mídia stock",
        "",
        "Gerado pelo OpenMontage Studio. Verifique os termos de cada fonte antes de publicar.",
        "",
    ]
    if with_prov:
        lines.extend(_credits_line(entry) for entry in with_prov)
    else:
        lines.append("_Nenhuma mídia stock associada ainda._")
    lines.append("")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines), encoding="utf-8")
    return destination.resolve()
