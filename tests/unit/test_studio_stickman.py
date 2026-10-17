"""Unit tests for the OpenMontage Studio Stickman engine (Etapa 8 / 8.1)."""
from __future__ import annotations

import math
import re
import threading
from pathlib import Path

import pytest

from lib.studio_stickman import (
    ACTIONS, CHARACTERS, CHARACTER_LABELS, PRESET_KEYS, PRESET_LABELS,
    SCENARIOS, STICKMAN_CREATOR, STICKMAN_LICENSE, STICKMAN_SOURCE,
    MAX_DURATION_SECONDS, _SEATED, _TORSO_FOLLOWERS,
    build_spec, build_timeline_js, render_composition_html,
    render_stickman_scene, validate_spec,
)
from tools.base_tool import ToolResult


def test_validate_spec_accepts_demo_preset():
    spec = build_spec("demonstracao_escritorio", 20)
    assert validate_spec(spec) is spec
    assert spec["scenario"] == "escritorio"
    assert spec["character"] == "heroi"
    assert spec["duration_seconds"] == 20.0
    actions = [beat["action"] for beat in spec["beats"]]
    assert actions == ["caminhar", "sentar", "digitar", "comemorar", "repouso"]


@pytest.mark.parametrize("preset", PRESET_KEYS)
def test_every_preset_builds_and_validates(preset):
    template_default = build_spec(preset, 20)["duration_seconds"]
    assert template_default == 20.0
    spec = build_spec(preset, 20)
    assert spec["preset"] == preset
    assert spec["scenario"] in SCENARIOS
    assert spec["character"] in CHARACTERS


def test_build_spec_scales_beats_to_duration():
    short = build_spec("demonstracao_escritorio", 10)
    long = build_spec("demonstracao_escritorio", 20)
    assert short["beats"][-1]["start"] + short["beats"][-1]["duration"] == pytest.approx(10.0, abs=0.05)
    assert long["beats"][-1]["start"] + long["beats"][-1]["duration"] == pytest.approx(20.0, abs=0.05)
    assert short["beats"][0]["duration"] == pytest.approx(long["beats"][0]["duration"] / 2, abs=0.05)


def test_build_spec_rejects_unknown_preset_and_character():
    with pytest.raises(ValueError, match="Preset"):
        build_spec("inexistente", 20)
    with pytest.raises(ValueError, match="Personagem"):
        build_spec("demonstracao_escritorio", 20, "fantasma")


def test_build_spec_enforces_min_duration():
    with pytest.raises(ValueError, match="ao menos"):
        build_spec("demonstracao_escritorio", 5)


def test_validate_spec_rejects_bad_inputs():
    with pytest.raises(ValueError):
        validate_spec("não é dict")
    with pytest.raises(ValueError, match="Cenário"):
        validate_spec({"scenario": "marte", "character": "heroi",
                       "duration_seconds": 10, "beats": [{"action": "repouso", "start": 0, "duration": 1}]})
    with pytest.raises(ValueError, match="Personagem"):
        validate_spec({"scenario": "rua", "character": "robo",
                       "duration_seconds": 10, "beats": [{"action": "repouso", "start": 0, "duration": 1}]})
    with pytest.raises(ValueError, match="a[çc][ãa]o|ação|acao|Beat"):
        validate_spec({"scenario": "rua", "character": "heroi", "duration_seconds": 10,
                       "beats": [{"action": "voar", "start": 0, "duration": 1}]})
    with pytest.raises(ValueError, match="cadeira"):
        validate_spec({"scenario": "rua", "character": "heroi", "duration_seconds": 10,
                       "beats": [{"action": "sentar", "start": 0, "duration": 1}]})
    with pytest.raises(ValueError, match="escritorio"):
        validate_spec({"scenario": "casa", "character": "heroi", "duration_seconds": 10,
                       "beats": [{"action": "digitar", "start": 0, "duration": 1}]})
    with pytest.raises(ValueError, match="ordem"):
        validate_spec({"scenario": "rua", "character": "heroi", "duration_seconds": 10,
                       "beats": [{"action": "repouso", "start": 5, "duration": 1},
                                 {"action": "parar", "start": 1, "duration": 1}]})
    with pytest.raises(ValueError, match="após o fim"):
        validate_spec({"scenario": "rua", "character": "heroi", "duration_seconds": 10,
                       "beats": [{"action": "repouso", "start": 9, "duration": 5}]})
    with pytest.raises(ValueError, match="to_x"):
        validate_spec({"scenario": "rua", "character": "heroi", "duration_seconds": 10,
                       "beats": [{"action": "caminhar", "start": 0, "duration": 5, "to_x": 5000}]})
    with pytest.raises(ValueError, match="máximo"):
        validate_spec({"scenario": "rua", "character": "heroi",
                       "duration_seconds": MAX_DURATION_SECONDS + 1,
                       "beats": [{"action": "repouso", "start": 0, "duration": 1}]})


def test_validate_spec_requires_beats():
    with pytest.raises(ValueError, match="beat"):
        validate_spec({"scenario": "rua", "character": "heroi",
                       "duration_seconds": 10, "beats": []})


def test_render_composition_html_contract():
    spec = build_spec("demonstracao_escritorio", 20)
    html = render_composition_html(spec)
    assert 'data-composition-id="stickman"' in html
    assert 'data-duration="20.000"' in html
    assert 'window.__timelines["stickman"]' in html
    assert "gsap.timeline({ paused: true })" in html
    assert "gsap.min.js" in html
    assert "repeat: -1" not in html
    assert "Math.random" not in html
    assert "Date.now" not in html
    for joint in ("sm-torso", "sm-head", "sm-armR-1", "sm-armR-2",
                  "sm-armL-1", "sm-armL-2", "sm-legR-1", "sm-legR-2",
                  "sm-legL-1", "sm-legL-2", "sm-root", "sm-body"):
        assert joint in html
    assert "rotation:" in html
    assert "yoyo: true" in html


def test_render_composition_html_scenario_assets():
    office = render_composition_html(build_spec("demonstracao_escritorio", 20))
    assert "#a97c56" in office and "#38bdf8" in office
    street = render_composition_html(build_spec("caminhar_rua", 15))
    assert "#fde68a" in street and "viewBox" in street
    home = render_composition_html(build_spec("pausa_casa", 15))
    assert "#d97706" in home
    abstract = render_composition_html(build_spec("gestos_abstratos", 12))
    assert "#c4b5fd" in abstract


def test_render_composition_html_sit_and_type_markers():
    html = render_composition_html(build_spec("demonstracao_escritorio", 20))
    assert "y: 845.0" in html
    assert "#sm-armR-2, #sm-armL-2" in html
    assert "x: 1105.0" in html


def test_characters_have_distinct_style():
    hero = render_composition_html(build_spec("gestos_abstratos", 12, "heroi"))
    guide = render_composition_html(build_spec("gestos_abstratos", 12, "guia"))
    assert "#2563eb" in hero and "#d97706" in guide
    assert CHARACTER_LABELS["heroi"] != CHARACTER_LABELS["guia"]


def test_all_actions_are_covered_by_presets():
    covered = set()
    for preset in PRESET_KEYS:
        for beat in build_spec(preset, 20)["beats"]:
            covered.add(beat["action"])
    assert covered <= set(ACTIONS)
    assert {"caminhar", "correr", "sentar", "digitar", "apontar", "gesto",
            "comemorar", "pensar", "repouso", "parar"} <= covered


def test_timeline_js_is_registered_and_finite():
    spec = build_spec("gestos_abstratos", 12)
    js = build_timeline_js(spec, {"start_x": 480.0, "stand_y": 790.0,
                                  "sit_y": 845.0, "walk_to_x": 960.0, "far_x": 1500.0})
    assert 'window.__timelines["stickman"]' in js
    assert "repeat: -1" not in js
    assert js.count("tl.to(") > 10


def _fake_tool_result(success=True, error=None, data=None):
    return ToolResult(success=success, error=error, data=data or {})


def test_render_stickman_scene_success(tmp_path, monkeypatch):
    monkeypatch.setattr("lib.studio_stickman.hyperframes_status", lambda: {"available": True, "reasons": [], "runtime": {}})
    from tools.video import hyperframes_compose

    def fake_execute(self, inputs):
        out = Path(inputs["output_path"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00" * 128)
        return _fake_tool_result(data={"steps": {"render": {"exit_code": 0}}})

    monkeypatch.setattr(hyperframes_compose.HyperFramesCompose, "execute", fake_execute)
    monkeypatch.setattr("lib.studio_stickman.probe_scene", lambda path: {
        "probed": True, "width": 1920, "height": 1080, "fps": 30.0,
        "silent": True, "duration_seconds": 12.0,
    })
    events = []
    summary = render_stickman_scene(
        output_dir=tmp_path,
        spec=build_spec("gestos_abstratos", 12),
        progress=lambda fraction, message: events.append((fraction, message)),
    )
    assert summary["ok"] is True
    assert Path(summary["output"]).is_file()
    workspace = Path(summary["workspace"])
    assert (workspace / "index.html").is_file()
    assert (workspace / "spec.json").is_file()
    assert summary["duration_seconds"] == 12.0
    assert summary["silent"] is True
    assert summary["preset"] == "gestos_abstratos"
    assert events and events[-1][0] == 1.0
    assert "Stickman" in events[-1][1]


def test_render_stickman_scene_invalid_spec(tmp_path):
    summary = render_stickman_scene(output_dir=tmp_path, spec={"scenario": "marte"})
    assert summary["ok"] is False
    assert "Cenário" in summary["error"]


def test_render_stickman_scene_runtime_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr("lib.studio_stickman.hyperframes_status", lambda: {
        "available": False, "reasons": ["node not found on PATH"],
        "install_instructions": "Instale o Node 22+.", "runtime": {},
    })
    summary = render_stickman_scene(
        output_dir=tmp_path, spec=build_spec("gestos_abstratos", 12))
    assert summary["ok"] is False
    assert "node not found" in summary["error"]
    assert "Instale o Node" in summary["error"]


def test_render_stickman_scene_tool_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("lib.studio_stickman.hyperframes_status", lambda: {"available": True, "reasons": [], "runtime": {}})
    from tools.video import hyperframes_compose

    monkeypatch.setattr(
        hyperframes_compose.HyperFramesCompose, "execute",
        lambda self, inputs: _fake_tool_result(success=False, error="check failed",
                                               data={"steps": {}}))
    summary = render_stickman_scene(
        output_dir=tmp_path, spec=build_spec("gestos_abstratos", 12))
    assert summary["ok"] is False
    assert "check failed" in summary["error"]


def test_render_stickman_scene_cancel_discards_result(tmp_path, monkeypatch):
    monkeypatch.setattr("lib.studio_stickman.hyperframes_status", lambda: {"available": True, "reasons": [], "runtime": {}})
    from tools.video import hyperframes_compose

    def fake_execute(self, inputs):
        out = Path(inputs["output_path"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00" * 64)
        return _fake_tool_result(data={"steps": {}})

    monkeypatch.setattr(hyperframes_compose.HyperFramesCompose, "execute", fake_execute)
    monkeypatch.setattr("lib.studio_stickman.probe_scene", lambda path: {
        "probed": True, "width": 1920, "height": 1080, "fps": 30.0,
        "silent": True, "duration_seconds": 12.0,
    })
    cancel = threading.Event()
    cancel.set()
    summary = render_stickman_scene(
        output_dir=tmp_path, spec=build_spec("gestos_abstratos", 12),
        cancel_event=cancel)
    assert summary["ok"] is False
    assert summary["cancelled"] is True
    assert "cancelada" in summary["error"]


def test_render_stickman_scene_never_overwrites_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr("lib.studio_stickman.hyperframes_status", lambda: {"available": True, "reasons": [], "runtime": {}})
    from tools.video import hyperframes_compose

    def fake_execute(self, inputs):
        out = Path(inputs["output_path"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00" * 64)
        return _fake_tool_result(data={"steps": {}})

    monkeypatch.setattr(hyperframes_compose.HyperFramesCompose, "execute", fake_execute)
    monkeypatch.setattr("lib.studio_stickman.probe_scene", lambda path: {
        "probed": True, "width": 1920, "height": 1080, "fps": 30.0,
        "silent": True, "duration_seconds": 12.0,
    })
    spec = build_spec("gestos_abstratos", 12)
    first = render_stickman_scene(output_dir=tmp_path, spec=spec)
    second = render_stickman_scene(output_dir=tmp_path, spec=spec)
    assert first["ok"] and second["ok"]
    assert first["output"] != second["output"]
    assert first["workspace"] != second["workspace"]
    assert Path(first["output"]).is_file() and Path(second["output"]).is_file()


def test_provenance_constants_are_local():
    assert STICKMAN_SOURCE == "stickman"
    assert "Stickman" in STICKMAN_CREATOR
    assert "localmente" in STICKMAN_LICENSE


def test_preset_labels_cover_all_keys():
    assert set(PRESET_LABELS) == set(PRESET_KEYS)
    assert all(PRESET_LABELS[key].strip() for key in PRESET_KEYS)


def test_preset_default_duration():
    from lib.studio_stickman import preset_default_duration
    assert preset_default_duration("demonstracao_escritorio") == 20.0
    assert preset_default_duration("caminhar_rua") == 15.0
    with pytest.raises(ValueError):
        preset_default_duration("inexistente")


# ----------------------------------------------------------------------
# Etapa 8.1 — joint geometry and intermediate-frame validation.
# Rotation convention: NEGATIVE = forward (toward +x / facing direction),
# POSITIVE = backward. Geometry constants mirror _character_svg.
# ----------------------------------------------------------------------

_THIGH_LEN = 55.0
_SHIN_TO_FOOT_BOTTOM = 55.0  # foot rect bottom (y=55) inside the shin group
_UPPER_ARM_LEN = 42.0
_FOREARM_TO_HAND = 44.0  # hand circle centre inside the forearm group
_SHOULDER_Y = -85.0
_GROUND_Y = 900.0
_SIT_Y = 845.0
_STAND_Y = 790.0
_WALK_TO_X = 1105.0
_DESK_TOP_Y = 752.0
_DESK_X0, _DESK_X1 = 1000.0, 1470.0
_CHAIR_SEAT_Y = 838.0
_OFFICE_ANCHORS = {"start_x": 180.0, "stand_y": _STAND_Y, "sit_y": _SIT_Y,
                   "walk_to_x": _WALK_TO_X, "far_x": 1500.0}


def _rot(x: float, y: float, deg: float) -> tuple[float, float]:
    r = math.radians(deg)
    return (x * math.cos(r) - y * math.sin(r),
            x * math.sin(r) + y * math.cos(r))


def _leg_joints(pose: dict[str, float], side: str) -> dict[str, object]:
    thigh = _rot(0.0, _THIGH_LEN, pose[f"leg{side}1"])
    total = pose[f"leg{side}1"] + pose[f"leg{side}2"]
    foot = _rot(0.0, _SHIN_TO_FOOT_BOTTOM, total)
    return {"knee": thigh,
            "foot_bottom": (thigh[0] + foot[0], thigh[1] + foot[1]),
            "total_angle": total}


def _arm_joints(pose: dict[str, float], side: str) -> dict[str, object]:
    elbow = _rot(0.0, _UPPER_ARM_LEN, pose[f"arm{side}1"])
    total = pose[f"arm{side}1"] + pose[f"arm{side}2"]
    hand = _rot(0.0, _FOREARM_TO_HAND, total)
    return {"elbow": elbow,
            "hand": (elbow[0] + hand[0], elbow[1] + hand[1]),
            "total_angle": total}


def test_seated_pose_feet_reach_ground():
    """Seated shins are vertical and both feet rest on the ground (y=900)."""
    for side in ("R", "L"):
        leg = _leg_joints(_SEATED, side)
        foot_abs_y = _SIT_Y + leg["foot_bottom"][1]
        assert foot_abs_y == pytest.approx(_GROUND_Y, abs=10.0), (
            f"side {side}: foot bottom at {foot_abs_y:.1f}, ground {_GROUND_Y}")
        assert abs(leg["total_angle"]) <= 10.0, (
            f"side {side}: shin total angle {leg['total_angle']:.1f} not vertical")


def test_seated_pose_knees_forward_under_desk():
    """Thighs swing forward (negative) so knees land in front of the hips, under the desk."""
    assert _SEATED["legR1"] < 0 and _SEATED["legL1"] < 0
    for side in ("R", "L"):
        leg = _leg_joints(_SEATED, side)
        knee_x = _WALK_TO_X + leg["knee"][0]
        knee_y = _SIT_Y + leg["knee"][1]
        assert leg["knee"][0] > 20, (
            f"side {side}: knee not forward (x={leg['knee'][0]:.1f})")
        assert _DESK_TOP_Y < knee_y < _CHAIR_SEAT_Y + 30, (
            f"side {side}: knee y={knee_y:.1f} not under the desk")
        assert _DESK_X0 < knee_x < _DESK_X1, (
            f"side {side}: knee x={knee_x:.1f} outside the desk span")


def test_typing_pose_hands_forward_at_desk():
    """Typing brings both hands forward near keyboard/desk height."""
    typing = dict(_SEATED)
    typing.update({"armR1": -84.0, "armR2": -8.0, "armL1": -80.0,
                   "armL2": -10.0, "torso": -6.0})
    assert typing["armR1"] < 0 and typing["armL1"] < 0
    for side in ("R", "L"):
        arm = _arm_joints(typing, side)
        assert arm["hand"][0] > 40, (
            f"side {side}: hand not forward (x={arm['hand'][0]:.1f})")
        hand_abs_y = _SIT_Y + _SHOULDER_Y + arm["hand"][1]
        assert 700.0 <= hand_abs_y <= 800.0, (
            f"side {side}: hand y={hand_abs_y:.1f} not near the keyboard")


def test_timeline_walk_root_tween_is_linear_intermediate():
    """The walk emits a single root tween across intermediate x positions."""
    js = build_timeline_js(build_spec("demonstracao_escritorio", 20),
                           dict(_OFFICE_ANCHORS))
    assert ('tl.to("#sm-root", {x: 1105.0, y: 790.0, '
            'duration: 6.000, ease: "none"}, 0.000);') in js


def test_timeline_sit_tween_is_not_instant():
    """The sit transition animates the root over 1.4 s (intermediate frames)."""
    js = build_timeline_js(build_spec("demonstracao_escritorio", 20),
                           dict(_OFFICE_ANCHORS))
    assert ('tl.to("#sm-root", {y: 845.0, '
            'duration: 1.400, ease: "power2.inOut"}, 6.000);') in js


def test_timeline_walk_emits_intermediate_pose_steps():
    """Walking emits many intermediate joint poses, not just start/end."""
    js = build_timeline_js(build_spec("demonstracao_escritorio", 20),
                           dict(_OFFICE_ANCHORS))
    leg_lines = [line for line in js.splitlines()
                 if "#sm-legR-1" in line and "rotation" in line]
    assert len(leg_lines) >= 8


def test_timeline_sit_then_type_then_celebrate_order():
    """Root sits at 6 s, typing yoyo follows, celebration arms rise last."""
    js = build_timeline_js(build_spec("demonstracao_escritorio", 20),
                           dict(_OFFICE_ANCHORS))
    sit_pos = js.find('y: 845.0')
    type_pos = js.find("#sm-armR-2, #sm-armL-2")
    celebrate_pos = js.find("rotation: -150.0")
    assert 0 <= sit_pos < type_pos < celebrate_pos


def test_seated_celebrate_does_not_hop():
    """Celebration while seated must not lift the root (no hop tweens)."""
    js = build_timeline_js(build_spec("demonstracao_escritorio", 20),
                           dict(_OFFICE_ANCHORS))
    root_times = [float(t) for t in re.findall(
        r'tl\.to\("#sm-root", \{[^}]*\}, ([\d.]+)\);', js)]
    assert root_times, "expected at least the walk and sit root tweens"
    assert all(t < 14.4 for t in root_times), (
        f"unexpected root tween during seated celebration: {root_times}")


def test_torso_rotation_drives_both_followers():
    """Torso rotation is applied to #sm-torso and #sm-upper together."""
    assert set(_TORSO_FOLLOWERS) == {"sm-torso", "sm-upper"}
    js = build_timeline_js(build_spec("demonstracao_escritorio", 20),
                           dict(_OFFICE_ANCHORS))
    assert 'tl.to("#sm-torso", {rotation: -6.0' in js
    assert 'tl.to("#sm-upper", {rotation: -6.0' in js


def test_svg_extremities_stay_nested_in_parents():
    """Hands/feet/head remain nested inside their parent limb groups."""
    html = render_composition_html(build_spec("demonstracao_escritorio", 20))
    arm_r2 = html.find('id="sm-armR-2"')
    hand_r = html.find('cy="44"', arm_r2)
    assert 0 <= arm_r2 < hand_r < arm_r2 + 400
    leg_r2 = html.find('id="sm-legR-2"')
    foot_r = html.find('y="46" width="22"', leg_r2)
    assert 0 <= leg_r2 < foot_r < leg_r2 + 400
    upper = html.find('id="sm-upper"')
    head = html.find('id="sm-head"')
    assert 0 <= upper < head
    assert 'fill="none"' in html[upper:upper + 300]  # stable fill-box anchor
