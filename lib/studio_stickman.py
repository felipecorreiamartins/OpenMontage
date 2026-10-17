"""Stickman animation engine for OpenMontage Studio (Etapa 8).

Reusable 2D character system rendered through the existing HyperFrames
runtime (`hyperframes_compose` operation ``render_existing``): the module
generates a deterministic HTML/CSS/SVG + GSAP composition — articulated
stickman (head, torso, arms, legs), reusable scenarios/objects and a list
of timed action beats — then renders it to a silent 1920x1080 · 30 fps MP4.

No new HTTP clients, no new renderers, no schema changes: the structured
spec is a plain JSON dict (saved as a sidecar next to the workspace) and
scenes.json keeps its Etapa 4–7 contract (provenance on association).

Failures never raise from the render path: `render_stickman_scene` returns
an ``ok=False`` summary with a human-readable ``error``. Only input
validation (`validate_spec`, `build_spec`) raises `ValueError`.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable, Optional

from lib.studio_hyperframes import (
    datetime_stamp,
    format_unavailable_error,
    hyperframes_status,
    probe_scene,
    unique_dir,
    unique_path,
    validate_duration,
)

STICKMAN_SOURCE = "stickman"
STICKMAN_CREATOR = "OpenMontage Studio (Stickman)"
STICKMAN_LICENSE = "Gerado localmente (SVG/GSAP); sem licença externa."

WIDTH, HEIGHT, FPS = 1920, 1080, 30
MAX_DURATION_SECONDS = 30.0
DEFAULT_DURATION_SECONDS = 20.0

MP4_SUBDIR = "stickman"
WORKSPACE_SUBDIR = "stickman-workspaces"

ProgressFn = Callable[[float, str], None]

ACTIONS = (
    "entrar", "caminhar", "correr", "parar", "sentar", "levantar",
    "digitar", "apontar", "gesto", "comemorar", "pensar", "repouso",
)
CHAIR_ACTIONS = {"sentar", "levantar"}
DESK_ACTIONS = {"digitar"}

SCENARIOS = ("escritorio", "rua", "casa", "abstrato")
SCENARIO_LABELS = {
    "escritorio": "Escritório (mesa, cadeira, computador)",
    "rua": "Rua (calçada, prédios, poste)",
    "casa": "Casa (sofá, mesa, luminária)",
    "abstrato": "Ambiente abstrato",
}
CHARACTERS = ("heroi", "guia")
CHARACTER_LABELS = {"heroi": "Herói (azul)", "guia": "Guia (âmbar)"}

# Static scene anchors (SVG user units, 1920x1080 frame, ground at y=900).
_ANCHORS = {
    "escritorio": {"start_x": 180.0, "stand_y": 790.0, "sit_y": 845.0,
                   "walk_to_x": 1105.0, "far_x": 1500.0},
    "rua": {"start_x": -140.0, "stand_y": 790.0, "sit_y": 845.0,
            "walk_to_x": 760.0, "far_x": 1620.0},
    "casa": {"start_x": 180.0, "stand_y": 790.0, "sit_y": 845.0,
             "walk_to_x": 455.0, "far_x": 1500.0},
    "abstrato": {"start_x": 480.0, "stand_y": 790.0, "sit_y": 845.0,
                 "walk_to_x": 960.0, "far_x": 1500.0},
}

_PRESET_TEMPLATES: dict[str, dict[str, Any]] = {
    "demonstracao_escritorio": {
        "label": "Demonstração — Escritório (entra, senta, trabalha)",
        "scenario": "escritorio",
        "default_duration": 20.0,
        "min_duration": 8.0,
        "beats": [
            {"action": "caminhar", "frac": (0.00, 0.30)},
            {"action": "sentar", "frac": (0.30, 0.38)},
            {"action": "digitar", "frac": (0.38, 0.72)},
            {"action": "comemorar", "frac": (0.72, 0.88)},
            {"action": "repouso", "frac": (0.88, 1.00)},
        ],
    },
    "caminhar_rua": {
        "label": "Caminhar e correr na rua",
        "scenario": "rua",
        "default_duration": 15.0,
        "min_duration": 6.0,
        "beats": [
            {"action": "caminhar", "frac": (0.00, 0.28), "to_x": 760.0},
            {"action": "parar", "frac": (0.28, 0.34)},
            {"action": "apontar", "frac": (0.34, 0.50)},
            {"action": "correr", "frac": (0.50, 0.78), "to_x": 1620.0},
            {"action": "parar", "frac": (0.78, 0.84)},
            {"action": "repouso", "frac": (0.84, 1.00)},
        ],
    },
    "pausa_casa": {
        "label": "Pausa em casa (sofá, pensar, levantar)",
        "scenario": "casa",
        "default_duration": 15.0,
        "min_duration": 6.0,
        "beats": [
            {"action": "caminhar", "frac": (0.00, 0.26), "to_x": 455.0},
            {"action": "sentar", "frac": (0.26, 0.34)},
            {"action": "repouso", "frac": (0.34, 0.58)},
            {"action": "pensar", "frac": (0.58, 0.74)},
            {"action": "levantar", "frac": (0.74, 0.84)},
            {"action": "repouso", "frac": (0.84, 1.00)},
        ],
    },
    "gestos_abstratos": {
        "label": "Gestos e emoções (cenário abstrato)",
        "scenario": "abstrato",
        "default_duration": 12.0,
        "min_duration": 5.0,
        "beats": [
            {"action": "repouso", "frac": (0.00, 0.12)},
            {"action": "apontar", "frac": (0.12, 0.30)},
            {"action": "gesto", "frac": (0.30, 0.52)},
            {"action": "comemorar", "frac": (0.52, 0.72)},
            {"action": "pensar", "frac": (0.72, 0.88)},
            {"action": "repouso", "frac": (0.88, 1.00)},
        ],
    },
}

PRESET_KEYS = tuple(_PRESET_TEMPLATES)
PRESET_LABELS = {key: tpl["label"] for key, tpl in _PRESET_TEMPLATES.items()}


def preset_default_duration(preset: str) -> float:
    """Return the recommended default duration (seconds) for a preset."""
    template = _PRESET_TEMPLATES.get(str(preset).strip())
    if template is None:
        raise ValueError(
            f"Preset inválido: {preset!r}. Use um de: {', '.join(PRESET_KEYS)}."
        )
    return float(template["default_duration"])

_CHARACTER_STYLE = {
    "heroi": {"stroke": "#1f2937", "torso": "#2563eb", "head": "#f8fafc"},
    "guia": {"stroke": "#292524", "torso": "#d97706", "head": "#fffbeb"},
}

_IDLE = {"torso": 0, "head": 0, "armR1": 6, "armR2": 4, "armL1": -6,
         "armL2": -4, "legR1": 2, "legR2": -3, "legL1": -2, "legL2": -3}
# Seated pose (Etapa 8.1). Rotation sign: NEGATIVE = forward (toward +x,
# the facing direction), POSITIVE = backward. Thighs swing forward (-88)
# so knees clear the chair; shins return vertical (+88 relative); forearms
# reach forward toward the desk/keyboard.
_SEATED = {"torso": -4, "head": 4, "armR1": -52, "armR2": -28, "armL1": -48,
           "armL2": -26, "legR1": -88, "legR2": 88, "legL1": -84, "legL2": 84}

_JOINT_IDS = {
    "torso": "sm-torso", "head": "sm-head",
    "armR1": "sm-armR-1", "armR2": "sm-armR-2",
    "armL1": "sm-armL-1", "armL2": "sm-armL-2",
    "legR1": "sm-legR-1", "legR2": "sm-legR-2",
    "legL1": "sm-legL-1", "legL2": "sm-legL-2",
}
# The upper-body group (head + arms) must receive the same rotation as the
# torso rect so the shoulders/head stay welded to the spine (Etapa 8.1).
_TORSO_FOLLOWERS = ("sm-torso", "sm-upper")

_WALK_POSES = [
    {"legR1": -30, "legR2": 6, "legL1": 24, "legL2": 38, "armR1": 28, "armR2": 16, "armL1": -28, "armL2": -16},
    {"legR1": -3, "legR2": 38, "legL1": 3, "legL2": 12, "armR1": 8, "armR2": 8, "armL1": -8, "armL2": -8},
    {"legR1": 24, "legR2": 38, "legL1": -30, "legL2": 6, "armR1": -28, "armR2": -16, "armL1": 28, "armL2": 16},
    {"legR1": 3, "legR2": 12, "legL1": -3, "legL2": 38, "armR1": -8, "armR2": -8, "armL1": 8, "armL2": 8},
]
_WALK_CYCLE = 0.6
_RUN_CYCLE = 0.42


def validate_spec(spec: Any) -> dict[str, Any]:
    """Validate a stickman scene spec; raises ValueError with guidance."""
    if not isinstance(spec, dict):
        raise ValueError("Spec Stickman: informe um objeto de cena válido.")
    scenario = str(spec.get("scenario", "")).strip()
    if scenario not in SCENARIOS:
        raise ValueError(
            f"Cenário inválido: {scenario!r}. Use um de: {', '.join(SCENARIOS)}."
        )
    character = str(spec.get("character", "")).strip()
    if character not in CHARACTERS:
        raise ValueError(
            f"Personagem inválido: {character!r}. Use um de: {', '.join(CHARACTERS)}."
        )
    duration = validate_duration(spec.get("duration_seconds"))
    if duration > MAX_DURATION_SECONDS:
        raise ValueError(
            f"Duração: máximo de {MAX_DURATION_SECONDS:.0f} s para uma cena Stickman."
        )
    beats = spec.get("beats")
    if not isinstance(beats, list) or not beats:
        raise ValueError("Spec Stickman: informe ao menos um beat de ação.")
    previous_start = -1.0
    for index, beat in enumerate(beats, start=1):
        if not isinstance(beat, dict):
            raise ValueError(f"Beat {index}: informe um objeto com action/start/duration.")
        action = str(beat.get("action", "")).strip()
        if action not in ACTIONS:
            raise ValueError(
                f"Beat {index}: ação inválida {action!r}. Use uma de: {', '.join(ACTIONS)}."
            )
        if action in CHAIR_ACTIONS and scenario not in ("escritorio", "casa"):
            raise ValueError(
                f"Beat {index}: a ação {action!r} exige cenário com cadeira "
                "(escritorio ou casa)."
            )
        if action in DESK_ACTIONS and scenario != "escritorio":
            raise ValueError(
                f"Beat {index}: a ação {action!r} exige o cenário escritorio."
            )
        try:
            start = float(beat.get("start"))
            beat_duration = float(beat.get("duration"))
        except (TypeError, ValueError):
            raise ValueError(f"Beat {index}: start/duration precisam ser números.") from None
        if not math.isfinite(start) or not math.isfinite(beat_duration):
            raise ValueError(f"Beat {index}: start/duration precisam ser finitos.")
        if start < 0 or beat_duration <= 0:
            raise ValueError(f"Beat {index}: start ≥ 0 e duration > 0.")
        if start < previous_start - 1e-9:
            raise ValueError(f"Beat {index}: beats devem estar em ordem crescente de start.")
        previous_start = start
        if start + beat_duration > duration + 0.05:
            raise ValueError(
                f"Beat {index}: termina em {start + beat_duration:.2f}s, "
                f"após o fim da cena ({duration:.2f}s)."
            )
        to_x = beat.get("to_x")
        if to_x is not None:
            try:
                to_x_f = float(to_x)
            except (TypeError, ValueError):
                raise ValueError(f"Beat {index}: to_x precisa ser um número.") from None
            if not math.isfinite(to_x_f) or not 0 <= to_x_f <= WIDTH:
                raise ValueError(f"Beat {index}: to_x deve ficar entre 0 e {WIDTH}.")
    return spec


def build_spec(
    preset: str,
    duration_seconds: Any,
    character: str = "heroi",
) -> dict[str, Any]:
    """Build a validated stickman spec from a preset + duration."""
    key = str(preset).strip()
    template = _PRESET_TEMPLATES.get(key)
    if template is None:
        raise ValueError(
            f"Preset inválido: {key!r}. Use um de: {', '.join(PRESET_KEYS)}."
        )
    character = str(character).strip()
    if character not in CHARACTERS:
        raise ValueError(
            f"Personagem inválido: {character!r}. Use um de: {', '.join(CHARACTERS)}."
        )
    duration = validate_duration(duration_seconds)
    if duration > MAX_DURATION_SECONDS:
        raise ValueError(
            f"Duração: máximo de {MAX_DURATION_SECONDS:.0f} s para uma cena Stickman."
        )
    if duration < float(template["min_duration"]) - 1e-9:
        raise ValueError(
            f"Duração: o preset {template['label']!r} pede ao menos "
            f"{template['min_duration']:.0f} s."
        )
    beats = []
    for entry in template["beats"]:
        start_frac, end_frac = entry["frac"]
        beat = {
            "action": entry["action"],
            "start": round(duration * start_frac, 3),
            "duration": round(duration * (end_frac - start_frac), 3),
        }
        if "to_x" in entry:
            beat["to_x"] = entry["to_x"]
        beats.append(beat)
    spec = {
        "version": "1",
        "title": template["label"],
        "preset": key,
        "scenario": template["scenario"],
        "character": character,
        "duration_seconds": duration,
        "beats": beats,
    }
    validate_spec(spec)
    return spec


# ----------------------------------------------------------------------
# SVG scene generation
# ----------------------------------------------------------------------

def _scenario_svg(scenario: str) -> tuple[str, dict[str, float]]:
    """Return (background fill color, static SVG shapes) + scene anchors."""
    anchors = dict(_ANCHORS[scenario])
    if scenario == "escritorio":
        svg = f"""
    <rect x="0" y="0" width="1920" height="900" fill="#eef2f7"/>
    <rect x="0" y="900" width="1920" height="180" fill="#c8d2de"/>
    <rect x="250" y="170" width="280" height="300" rx="8" fill="#cfe8ff" stroke="#94a3b8" stroke-width="6"/>
    <line x1="390" y1="170" x2="390" y2="470" stroke="#94a3b8" stroke-width="4"/>
    <line x1="250" y1="320" x2="530" y2="320" stroke="#94a3b8" stroke-width="4"/>
    <rect x="1000" y="752" width="470" height="16" rx="4" fill="#a97c56"/>
    <rect x="1020" y="768" width="14" height="132" fill="#8c6644"/>
    <rect x="1436" y="768" width="14" height="132" fill="#8c6644"/>
    <rect x="1250" y="662" width="180" height="100" rx="8" fill="#111827"/>
    <rect x="1260" y="672" width="160" height="80" rx="4" fill="#38bdf8"/>
    <rect x="1325" y="762" width="30" height="18" fill="#374151"/>
    <rect x="1290" y="744" width="100" height="10" rx="4" fill="#374151"/>
    <rect x="1062" y="738" width="150" height="14" rx="5" fill="#374151"/>
    <rect x="1092" y="838" width="126" height="12" rx="5" fill="#4b5563"/>
    <rect x="1090" y="748" width="12" height="96" rx="4" fill="#4b5563"/>
    <rect x="1148" y="850" width="8" height="46" fill="#374151"/>
    <rect x="1120" y="890" width="64" height="8" rx="4" fill="#374151"/>"""
        return svg, anchors
    if scenario == "rua":
        svg = f"""
    <rect x="0" y="0" width="1920" height="900" fill="#dbeafe"/>
    <circle cx="1620" cy="160" r="70" fill="#fde68a"/>
    <rect x="60" y="300" width="240" height="600" fill="#94a3b8"/>
    <rect x="340" y="220" width="200" height="680" fill="#64748b"/>
    <rect x="1200" y="260" width="260" height="640" fill="#7c8aa0"/>
    <rect x="1500" y="360" width="360" height="540" fill="#94a3b8"/>
    <g fill="#e2e8f0">
      <rect x="90" y="340" width="40" height="50"/><rect x="160" y="340" width="40" height="50"/>
      <rect x="90" y="430" width="40" height="50"/><rect x="160" y="430" width="40" height="50"/>
      <rect x="380" y="260" width="40" height="50"/><rect x="450" y="260" width="40" height="50"/>
      <rect x="380" y="350" width="40" height="50"/><rect x="450" y="350" width="40" height="50"/>
      <rect x="1240" y="300" width="40" height="50"/><rect x="1320" y="300" width="40" height="50"/>
      <rect x="1240" y="390" width="40" height="50"/><rect x="1320" y="390" width="40" height="50"/>
    </g>
    <rect x="0" y="900" width="1920" height="180" fill="#cbd5e1"/>
    <rect x="0" y="900" width="1920" height="10" fill="#94a3b8"/>
    <rect x="980" y="560" width="14" height="340" fill="#334155"/>
    <path d="M987 560 q60 -50 0 -90 q-60 40 0 90" fill="#facc15"/>
    <g stroke="#94a3b8" stroke-width="5">
      <line x1="600" y1="940" x2="760" y2="940"/>
      <line x1="820" y1="940" x2="980" y2="940"/>
      <line x1="1040" y1="940" x2="1200" y2="940"/>
    </g>"""
        return svg, anchors
    if scenario == "casa":
        svg = f"""
    <rect x="0" y="0" width="1920" height="900" fill="#fef3c7"/>
    <rect x="0" y="900" width="1920" height="180" fill="#d6c3a5"/>
    <rect x="180" y="180" width="220" height="320" rx="6" fill="#fde68a" stroke="#b45309" stroke-width="6"/>
    <rect x="300" y="180" width="4" height="320" fill="#b45309"/>
    <rect x="260" y="820" width="400" height="26" rx="8" fill="#b45309"/>
    <rect x="250" y="700" width="420" height="120" rx="14" fill="#d97706"/>
    <rect x="250" y="700" width="420" height="40" rx="12" fill="#f59e0b"/>
    <rect x="280" y="826" width="16" height="70" fill="#78350f"/>
    <rect x="620" y="826" width="16" height="70" fill="#78350f"/>
    <rect x="780" y="800" width="240" height="16" rx="6" fill="#a16207"/>
    <rect x="800" y="816" width="12" height="80" fill="#713f12"/>
    <rect x="988" y="816" width="12" height="80" fill="#713f12"/>
    <rect x="1440" y="620" width="14" height="280" fill="#78350f"/>
    <path d="M1410 620 h74 l-16 -70 h-42 z" fill="#fbbf24"/>
    <rect x="1500" y="760" width="180" height="140" rx="10" fill="#92400e"/>"""
        return svg, anchors
    svg = f"""
    <rect x="0" y="0" width="1920" height="900" fill="#f5f3ff"/>
    <rect x="0" y="900" width="1920" height="180" fill="#ddd6fe"/>
    <circle cx="320" cy="260" r="110" fill="#c4b5fd" opacity="0.8"/>
    <circle cx="1600" cy="220" r="150" fill="#a78bfa" opacity="0.6"/>
    <circle cx="1200" cy="380" r="60" fill="#8b5cf6" opacity="0.5"/>
    <circle cx="700" cy="200" r="40" fill="#ddd6fe"/>
    <rect x="0" y="898" width="1920" height="4" fill="#8b5cf6"/>
    <g stroke="#c4b5fd" stroke-width="3" opacity="0.7">
      <line x1="0" y1="780" x2="1920" y2="780"/>
      <line x1="0" y1="660" x2="1920" y2="660"/>
      <line x1="240" y1="900" x2="240" y2="1080"/>
      <line x1="720" y1="900" x2="720" y2="1080"/>
      <line x1="1200" y1="900" x2="1200" y2="1080"/>
      <line x1="1680" y1="900" x2="1680" y2="1080"/>
    </g>"""
    return svg, anchors


def _character_svg(character: str, start_x: float, stand_y: float) -> str:
    """Emit the articulated stickman SVG.

    Etapa 8.1 rig: each rotating group (``.sm-rot``) contains only its own
    limb shape plus a nested static offset for the child joint, so the
    fill-box pivot (50% 0%) always lands on the joint. The torso rect
    rotates alone (pivot 50% 100% = hips). Head + arms live in a sibling
    ``#sm-upper`` group that receives the *same* torso rotation; a large
    invisible anchor rect keeps its fill-box stable so the hip pivot
    (50% ~71%) stays fixed regardless of arm/head motion.
    """
    style = _CHARACTER_STYLE[character]
    stroke, torso, head = style["stroke"], style["torso"], style["head"]

    def limb(pid: str, w: float, h: float, fill: str, child: str = "") -> str:
        return (
            f'<g class="sm-rot" id="{pid}">'
            f'<rect x="{-w / 2}" y="0" width="{w}" height="{h}" rx="{w / 2}" fill="{fill}"/>'
            f"{child}</g>"
        )

    arm_r2 = (
        f'<g transform="translate(0,42)">'
        f'{limb("sm-armR-2", 10, 40, stroke)}'
        f'<circle cx="0" cy="44" r="7" fill="{head}" stroke="{stroke}" stroke-width="3"/>'
        f"</g>"
    )
    arm_l2 = (
        f'<g transform="translate(0,42)">'
        f'{limb("sm-armL-2", 10, 40, stroke)}'
        f'<circle cx="0" cy="44" r="7" fill="{head}" stroke="{stroke}" stroke-width="3"/>'
        f"</g>"
    )
    leg_r2 = (
        f'<g transform="translate(0,55)">'
        f'{limb("sm-legR-2", 10, 52, stroke)}'
        f'<rect x="-4" y="46" width="22" height="9" rx="4.5" fill="{stroke}"/>'
        f"</g>"
    )
    leg_l2 = (
        f'<g transform="translate(0,55)">'
        f'{limb("sm-legL-2", 10, 52, stroke)}'
        f'<rect x="-4" y="46" width="22" height="9" rx="4.5" fill="{stroke}"/>'
        f"</g>"
    )
    return f"""
  <g id="sm-root" transform="translate({start_x:.1f},{stand_y:.1f})">
    <g id="sm-body">
      <g transform="translate(0,0)">{limb("sm-legL-1", 12, 55, stroke, leg_l2)}</g>
      <g transform="translate(0,0)">{limb("sm-legR-1", 12, 55, stroke, leg_r2)}</g>
      <g class="sm-torso-rot" id="sm-torso">
        <rect x="-9" y="-95" width="18" height="95" rx="9" fill="{torso}"/>
      </g>
      <g class="sm-upper" id="sm-upper">
        <rect x="-150" y="-200" width="300" height="270" fill="none"/>
        <g transform="translate(0,-85)">{limb("sm-armL-1", 11, 42, stroke, arm_l2)}</g>
        <g transform="translate(0,-85)">{limb("sm-armR-1", 11, 42, stroke, arm_r2)}</g>
        <g transform="translate(0,-95)">
          <g class="sm-head" id="sm-head">
            <rect x="-2" y="-58" width="4" height="60" fill="none"/>
            <circle cx="0" cy="-30" r="28" fill="{head}" stroke="{stroke}" stroke-width="5"/>
            <circle cx="12" cy="-34" r="3.5" fill="{stroke}"/>
          </g>
        </g>
      </g>
    </g>
  </g>"""


# ----------------------------------------------------------------------
# GSAP timeline emission (deterministic, seek-safe)
# ----------------------------------------------------------------------

def _tween(sel: str, vars_js: str, at: float) -> str:
    return f'  tl.to("{sel}", {{{vars_js}}}, {at:.3f});'


def _joint_tween(pose: dict[str, float], at: float, duration: float,
                 ease: str = "power2.inOut") -> list[str]:
    lines = []
    for key, value in pose.items():
        if key == "torso":
            for joint_id in _TORSO_FOLLOWERS:
                lines.append(_tween(
                    f"#{joint_id}",
                    f"rotation: {value:.1f}, duration: {duration:.3f}, ease: \"{ease}\"",
                    at,
                ))
            continue
        joint_id = _JOINT_IDS[key]
        lines.append(_tween(
            f"#{joint_id}",
            f"rotation: {value:.1f}, duration: {duration:.3f}, ease: \"{ease}\"",
            at,
        ))
    return lines


def _root_tween(at: float, duration: float, x: Optional[float] = None,
                y: Optional[float] = None, ease: str = "power2.inOut") -> str:
    parts = []
    if x is not None:
        parts.append(f"x: {x:.1f}")
    if y is not None:
        parts.append(f"y: {y:.1f}")
    parts.append(f"duration: {duration:.3f}")
    parts.append(f'ease: "{ease}"')
    return _tween("#sm-root", ", ".join(parts), at)


def _emit_walk(lines: list[str], at: float, duration: float, to_x: float,
               from_x: float, stand_y: float, cycle: float) -> float:
    lines.append(_root_tween(at, duration, x=to_x, y=stand_y, ease="none"))
    step = cycle / 4.0
    steps = max(1, int(math.floor(duration / step)))
    poses = _WALK_POSES
    for i in range(steps):
        pose = poses[i % 4]
        pose_duration = min(step, duration - i * step)
        if pose_duration <= 1e-4:
            break
        lines.extend(_joint_tween(pose, at + i * step, pose_duration, ease="sine.inOut"))
    remainder = duration - steps * step
    if remainder > 1e-3:
        lines.extend(_joint_tween(
            poses[steps % 4], at + steps * step, remainder, ease="sine.inOut"))
    # Settle to idle so the next action starts from a neutral pose (Etapa 8.1).
    settle = min(0.28, duration * 0.2)
    if settle > 0.05:
        lines.extend(_joint_tween(dict(_IDLE), at + duration - settle, settle,
                                  ease="power2.out"))
    return duration


def _emit_run(lines: list[str], at: float, duration: float, to_x: float,
              stand_y: float) -> float:
    lines.append(_root_tween(at, duration, x=to_x, y=stand_y, ease="none"))
    lines.extend(_joint_tween({"torso": -8}, at, min(0.2, duration), "power2.out"))
    step = _RUN_CYCLE / 4.0
    steps = max(1, int(math.floor(duration / step)))
    for i in range(steps):
        pose = dict(_WALK_POSES[i % 4])
        pose = {k: (v * 1.35 if k.startswith(("leg", "arm")) else v)
                for k, v in pose.items()}
        pose_duration = min(step, duration - i * step)
        if pose_duration <= 1e-4:
            break
        lines.extend(_joint_tween(pose, at + i * step, pose_duration, ease="sine.inOut"))
    remainder = duration - steps * step
    if remainder > 1e-3:
        pose = {k: (v * 1.35 if k.startswith(("leg", "arm")) else v)
                for k, v in _WALK_POSES[steps % 4].items()}
        lines.extend(_joint_tween(pose, at + steps * step, remainder, ease="sine.inOut"))
    settle = min(0.3, duration * 0.18)
    if settle > 0.05:
        lines.extend(_joint_tween(dict(_IDLE), at + duration - settle, settle,
                                  ease="power2.out"))
    return duration


def _emit_yoyo(lines: list[str], sel: str, vars_js: str, at: float,
               half: float, total: float) -> None:
    repeats = max(0, int(math.floor(total / half)) - 1)
    lines.append(_tween(
        sel, f"{vars_js}, duration: {half:.3f}, repeat: {repeats}, "
             f'yoyo: true, ease: "sine.inOut"', at))


def _rest_pose(state: dict[str, float]) -> dict[str, float]:
    """Return the resting joint pose matching the current sit/stand state."""
    return dict(_SEATED) if state.get("seated") else dict(_IDLE)


def _emit_action(lines: list[str], action: str, at: float, duration: float,
                 beat: dict[str, Any], anchors: dict[str, float],
                 state: dict[str, float]) -> None:
    if action in ("entrar", "caminhar"):
        to_x = float(beat.get("to_x", anchors["walk_to_x"]))
        _emit_walk(lines, at, duration, to_x, state["x"], anchors["stand_y"], _WALK_CYCLE)
        state["x"] = to_x
        state["y"] = anchors["stand_y"]
        state["seated"] = 0.0
    elif action == "correr":
        to_x = float(beat.get("to_x", anchors["far_x"]))
        _emit_run(lines, at, duration, to_x, anchors["stand_y"])
        state["x"] = to_x
        state["y"] = anchors["stand_y"]
        state["seated"] = 0.0
        lines.extend(_joint_tween(dict(_IDLE), at + duration, 0.35, "power2.out"))
    elif action == "parar":
        lines.extend(_joint_tween(_rest_pose(state), at, min(0.35, duration), "power2.out"))
        if not state.get("seated"):
            lines.append(_root_tween(at, min(0.35, duration), y=anchors["stand_y"]))
    elif action == "sentar":
        d = min(duration, 1.4)
        lines.extend(_joint_tween(dict(_SEATED), at, d))
        lines.append(_root_tween(at, d, y=anchors["sit_y"]))
        state["y"] = anchors["sit_y"]
        state["seated"] = 1.0
    elif action == "levantar":
        d = min(duration, 1.2)
        lines.extend(_joint_tween(dict(_IDLE), at, d))
        lines.append(_root_tween(at, d, y=anchors["stand_y"]))
        state["y"] = anchors["stand_y"]
        state["seated"] = 0.0
    elif action == "digitar":
        # Forearms forward/up to the keyboard; tiny yoyo on the wrists only.
        lines.extend(_joint_tween({
            "torso": -6, "head": -8, "armR1": -84, "armR2": -8,
            "armL1": -80, "armL2": -10,
        }, at, min(0.45, duration), "power2.out"))
        loop_at = at + min(0.45, duration)
        loop_total = max(0.2, duration - min(0.45, duration))
        half = 0.16
        repeats = max(0, int(math.floor(loop_total / half)) - 1)
        lines.append(_tween(
            "#sm-armR-2, #sm-armL-2",
            f"rotation: 18, duration: {half:.3f}, repeat: {repeats}, "
            f'yoyo: true, ease: "sine.inOut"', loop_at))
        lines.append(_tween(
            "#sm-head",
            f"rotation: -12, duration: {half * 2:.3f}, repeat: "
            f"{max(0, int(math.floor(loop_total / (half * 2))) - 1)}, "
            f'yoyo: true, ease: "sine.inOut"', loop_at))
    elif action == "apontar":
        d = min(duration * 0.45, 0.6)
        lines.extend(_joint_tween({
            "torso": -3, "armR1": -92, "armR2": -4, "armL1": 6, "armL2": 4,
        }, at, d, "power2.out"))
        hold = max(0.2, duration - 2 * d)
        _emit_yoyo(lines, "#sm-armR-2", "rotation: 12", at + d, 0.22, hold)
        lines.extend(_joint_tween(_rest_pose(state), at + d + hold,
                                  min(0.5, duration - d - hold)))
    elif action == "gesto":
        lines.extend(_joint_tween({
            "armR1": -140, "armR2": -24, "armL1": 10, "armL2": 8, "head": 8,
        }, at, min(0.45, duration), "power2.out"))
        loop_at = at + min(0.45, duration)
        loop_total = max(0.2, duration - min(0.45, duration) - 0.3)
        _emit_yoyo(lines, "#sm-armR-2", "rotation: 55", loop_at, 0.2, loop_total)
        rest = _rest_pose(state)
        lines.extend(_joint_tween(
            {k: rest[k] for k in ("armR1", "armR2", "head")},
            at + duration - 0.3, 0.3, "power2.in"))
    elif action == "comemorar":
        lines.extend(_joint_tween({
            "armR1": -150, "armR2": -14, "armL1": 150, "armL2": 14, "head": 8,
        }, at, min(0.4, duration), "power2.out"))
        loop_at = at + min(0.4, duration)
        loop_total = max(0.2, duration - min(0.4, duration) - 0.3)
        _emit_yoyo(lines, "#sm-armR-2", "rotation: 30", loop_at, 0.18, loop_total)
        _emit_yoyo(lines, "#sm-armL-2", "rotation: -30", loop_at, 0.18, loop_total)
        if not state.get("seated"):
            hop = max(0.25, min(0.4, duration / 4))
            hops = max(1, int(math.floor(loop_total / (hop * 2))))
            for i in range(hops):
                t0 = loop_at + i * hop * 2
                lines.append(_root_tween(t0, hop, y=state["y"] - 30, ease="power2.out"))
                lines.append(_root_tween(t0 + hop, hop, y=state["y"], ease="power2.in"))
        lines.extend(_joint_tween(_rest_pose(state), at + duration - 0.3, 0.3))
    elif action == "pensar":
        lines.extend(_joint_tween({
            "armR1": -55, "armR2": -118, "head": 10, "torso": -2,
        }, at, min(0.5, duration), "power2.out"))
        _emit_yoyo(lines, "#sm-head", "rotation: 14", at + 0.5, 0.35,
                   max(0.2, duration - 1.0))
        rest = _rest_pose(state)
        lines.extend(_joint_tween(
            {k: rest[k] for k in ("armR1", "armR2", "head", "torso")},
            at + duration - 0.4, 0.4, "power2.in"))
    elif action == "repouso":
        lines.extend(_joint_tween(_rest_pose(state), at, min(0.4, duration), "power2.out"))
        if duration > 1.2:
            _emit_yoyo(lines, "#sm-head", "rotation: 3", at + 0.4, 0.6,
                       duration - 0.8)


def build_timeline_js(spec: dict[str, Any], anchors: dict[str, float]) -> str:
    """Emit the synchronous GSAP timeline body for one validated spec."""
    duration = float(spec["duration_seconds"])
    start_x = anchors["start_x"]
    state = {"x": start_x, "y": anchors["stand_y"], "seated": 0.0}
    lines = [
        "  window.__timelines = window.__timelines || {};",
        "  const tl = gsap.timeline({ paused: true });",
        # Explicit pivots (Etapa 8.1): GSAP defaults SVG transformOrigin to
        # the bbox centre; pin each joint to its anatomical pivot instead.
        '  gsap.set(".sm-rot", { transformOrigin: "50% 0%" });',
        '  gsap.set("#sm-torso", { transformOrigin: "50% 100%" });',
        '  gsap.set("#sm-upper", { transformOrigin: "50% 71.4%" });',
        '  gsap.set("#sm-head", { transformOrigin: "50% 96.7%" });',
        f'  gsap.set("#sm-root", {{ x: {start_x:.1f}, y: {anchors["stand_y"]:.1f} }});',
    ]
    for beat in spec["beats"]:
        action = str(beat["action"])
        at = float(beat["start"])
        beat_duration = float(beat["duration"])
        _emit_action(lines, action, at, beat_duration, beat, anchors, state)
    lines.append('  window.__timelines["stickman"] = tl;')
    return "\n".join(lines)


# ----------------------------------------------------------------------
# HTML composition
# ----------------------------------------------------------------------

def render_composition_html(spec: dict[str, Any]) -> str:
    """Build the HyperFrames-contract HTML for a validated stickman spec."""
    validate_spec(spec)
    duration = float(spec["duration_seconds"])
    scenario_shapes, anchors = _scenario_svg(spec["scenario"])
    character = _character_svg(
        spec["character"], anchors["start_x"], anchors["stand_y"])
    timeline_js = build_timeline_js(spec, anchors)
    title = str(spec.get("title") or "Cena Stickman")
    bg = _CHARACTER_BG.get(spec["scenario"], "#f5f5f5")
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
  <style>
    body {{ margin: 0; background: #000; }}
    #root {{ position: relative; width: 1920px; height: 1080px; overflow: hidden; }}
    .clip {{ position: absolute; inset: 0; }}
    #sm-scene {{ position: absolute; inset: 0; background: {bg}; }}
    #sm-svg {{ position: absolute; inset: 0; width: 100%; height: 100%; }}
    .sm-rot {{ transform-box: fill-box; transform-origin: 50% 0%; }}
    .sm-torso-rot {{ transform-box: fill-box; transform-origin: 50% 100%; }}
    .sm-upper {{ transform-box: fill-box; transform-origin: 50% 71.4%; }}
    .sm-head {{ transform-box: fill-box; transform-origin: 50% 96.7%; }}
  </style>
</head>
<body>
  <div id="root" data-composition-id="stickman" data-width="{WIDTH}" data-height="{HEIGHT}" data-duration="{duration:.3f}">
    <div id="sm-scene" class="clip" data-start="0" data-duration="{duration:.3f}" data-track-index="1">
      <svg id="sm-svg" viewBox="0 0 {WIDTH} {HEIGHT}" xmlns="http://www.w3.org/2000/svg">
{scenario_shapes}
{character}
      </svg>
    </div>
  </div>
  <script>
{timeline_js}
  </script>
</body>
</html>
"""


_CHARACTER_BG = {
    "escritorio": "#eef2f7",
    "rua": "#dbeafe",
    "casa": "#fef3c7",
    "abstrato": "#f5f3ff",
}


# ----------------------------------------------------------------------
# Render entry point
# ----------------------------------------------------------------------

def render_stickman_scene(
    *,
    output_dir: Path,
    spec: dict[str, Any],
    progress: Optional[ProgressFn] = None,
    cancel_event: Any = None,
) -> dict[str, Any]:
    """Render one stickman scene to a silent 1920x1080 30 fps MP4.

    Returns a summary dict: ``ok=True`` with ``output``/``duration_seconds``/
    ``probe``/``spec``, or ``ok=False`` with a human-readable ``error``
    (and ``cancelled=True`` when the Studio cancel event fired).
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
                "duration_seconds": 0.0, "spec": spec, **extra}

    try:
        validated = validate_spec(spec)
    except ValueError as exc:
        return failure(str(exc))

    report(0.03, "Verificando dependências do HyperFrames (Node, FFmpeg, npx)…")
    status = hyperframes_status()
    if not status["available"]:
        return failure(format_unavailable_error(status), cancelled=False)

    report(0.10, "Gerando a composição Stickman (SVG articulado + GSAP)…")
    try:
        html = render_composition_html(validated)
    except Exception as exc:  # pragma: no cover - generator should not fail
        return failure(f"Falha ao gerar o HTML Stickman: {type(exc).__name__}: {exc}")

    stamp = datetime_stamp()
    base = Path(output_dir).expanduser()
    output = unique_path(base / MP4_SUBDIR / f"cena-stickman-{stamp}.mp4")
    workspace = unique_dir(base / WORKSPACE_SUBDIR / f"cena-stickman-{stamp}")
    output.parent.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "index.html").write_text(html, encoding="utf-8")
    (workspace / "spec.json").write_text(
        json.dumps(validated, ensure_ascii=False, indent=2), encoding="utf-8")

    report(0.15, "Renderizando a cena Stickman (check + render HyperFrames)…")
    try:
        from tools.video.hyperframes_compose import HyperFramesCompose

        result = HyperFramesCompose().execute({
            "operation": "render_existing",
            "workspace_path": str(workspace),
            "output_path": str(output),
            "fps": FPS,
            "quality": "standard",
            "skip_contrast": True,
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
            "duration_seconds": float(validated["duration_seconds"]),
            "spec": validated, "steps": steps,
        }

    report(0.92, "Verificando o MP4 gerado (1920×1080 · 30 fps · silencioso)…")
    if not output.is_file():
        return failure(
            f"O HyperFrames terminou mas o MP4 não foi gravado: {output}",
            workspace=str(workspace), steps=steps,
        )
    try:
        probe = probe_scene(output)
    except ValueError as exc:
        return failure(str(exc), output=str(output), workspace=str(workspace), steps=steps)

    real_duration = probe.get("duration_seconds") or validated["duration_seconds"]
    report(1.0, f"Cena Stickman pronta: {output.name}")
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
        "preset": validated.get("preset"),
        "scenario": validated.get("scenario"),
        "character": validated.get("character"),
        "spec": validated,
        "runtime_version": status["runtime"].get("npm_package_version"),
        "steps": steps,
    }
