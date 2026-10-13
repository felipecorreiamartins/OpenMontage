"""Translate approved documentary audio edits into AudioMixer inputs.

This is a parameter adapter, not a production orchestrator. The stage director
still owns asset selection, checkpoints and execution through the registry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def documentary_mix_inputs(
    edit_decisions: dict[str, Any],
    asset_manifest: dict[str, Any],
    project_dir: str | Path,
) -> dict[str, Any]:
    """Resolve canonical narration/music/SFX assets without guessing voice gain.

    ``metadata.audio_mix`` must contain the entire approved manual balance.
    Asset paths are absolute, project-relative, or repository-relative paths
    starting with ``projects/``. Inputs/artifacts are never mutated.
    """
    project = Path(project_dir).resolve()
    settings = dict(edit_decisions.get("metadata", {}).get("audio_mix", {}))
    required = {"narration_gain_db", "duck_level", "master_gain_db", "normalize"}
    missing = sorted(key for key in required if settings.get(key) is None)
    if missing:
        raise ValueError("Approved audio_mix settings missing: " + ", ".join(missing))
    allowed = required | {"ducking", "loudnorm_target", "peak_limit_db"}
    unknown = sorted(set(settings) - allowed)
    if unknown:
        raise ValueError("Unsupported audio_mix settings: " + ", ".join(unknown))
    if not isinstance(settings["normalize"], bool):
        raise ValueError("audio_mix.normalize must be a boolean")
    # Preserve the approved +3 dB gains, then cap exceptional peaks at -1 dBFS.
    # Existing non-documentary mixer calls remain unchanged unless they opt in.
    if settings.get("peak_limit_db") is None:
        settings["peak_limit_db"] = -1

    assets = {asset["id"]: asset for asset in asset_manifest.get("assets", [])}

    def track(asset_id: str, role: str, **timing: Any) -> dict[str, Any]:
        if asset_id not in assets:
            raise ValueError(f"Audio asset not found: {asset_id}")
        path = Path(assets[asset_id]["path"])
        if not path.is_absolute():
            if path.parts and path.parts[0] == "projects":
                path = Path(__file__).resolve().parents[1] / path
            else:
                path = project / path
        path = path.resolve()
        if not path.is_file():
            raise ValueError(f"Audio file not found for {asset_id}: {path}")
        return {"path": str(path), "role": role, **timing}

    audio = edit_decisions.get("audio", {})
    segments = audio.get("narration", {}).get("segments", [])
    if not segments:
        raise ValueError("The documentary narration mix requires approved narration segments")
    tracks = []
    for segment in segments:
        timing = {"start_seconds": segment["start_seconds"]}
        if "end_seconds" in segment:
            duration = float(segment["end_seconds"]) - float(segment["start_seconds"])
            if duration <= 0:
                raise ValueError("Narration end_seconds must be after start_seconds")
            timing["duration_seconds"] = duration
        tracks.append(track(segment["asset_id"], "speech", **timing))
    music = audio.get("music", {})
    if music.get("asset_id"):
        tracks.append(track(
            music["asset_id"], "music",
            **{key: music[key] for key in ("volume", "fade_in_seconds", "fade_out_seconds")
               if key in music},
        ))
    if "ducking" in music and "ducking" in settings and music["ducking"] != settings["ducking"]:
        raise ValueError("Conflicting ducking settings in audio.music and metadata.audio_mix")
    if "ducking" in music:
        settings["ducking"] = music["ducking"]
    ducking = settings.get("ducking", True)
    if isinstance(ducking, dict):
        unsupported = set(ducking) - {"enabled", "attack_ms", "release_ms"}
        if unsupported:
            raise ValueError("Unsupported documentary ducking settings: " + ", ".join(sorted(unsupported)))
    for effect in audio.get("sfx", []):
        tracks.append(track(effect["asset_id"], "sfx", **{
            key: effect[key] for key in ("start_seconds", "volume") if key in effect
        }))
    duration = edit_decisions.get("total_duration_seconds")
    if duration is None:
        raise ValueError("edit_decisions.total_duration_seconds is required")
    return {
        **settings,
        "operation": "full_mix",
        "tracks": tracks,
        "preserve_speech_volume": True,
        "target_duration": duration,
        "output_path": str(project / "assets" / "audio" / "mixed_audio.wav"),
    }
