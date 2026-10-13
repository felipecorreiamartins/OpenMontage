"""Real FFmpeg checks for manual documentary gains and canonical edit inputs."""

from copy import deepcopy
import math
from pathlib import Path
import shutil
import struct
import subprocess
import wave

import pytest

from lib.audio_mix_plan import documentary_mix_inputs
from tools.audio.audio_mixer import AudioMixer
from tools.video.video_compose import VideoCompose


def _tone(path: Path, *, frequency=440, duration=2, amplitude=0.06):
    rate = 24000
    samples = [int(32767 * amplitude * math.sin(2 * math.pi * frequency * i / rate))
               for i in range(int(duration * rate))]
    with wave.open(str(path), "wb") as out:
        out.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        out.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _rms(path, start=0, end=None):
    with wave.open(str(path), "rb") as audio:
        audio.setpos(int(start * audio.getframerate()))
        count = audio.getnframes() if end is None else int((end - start) * audio.getframerate())
        raw = audio.readframes(count)
    samples = struct.unpack(f"<{len(raw) // 2}h", raw)
    return math.sqrt(sum(s * s for s in samples) / len(samples))


needs_ffmpeg = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required"
)


def _plan(tmp_path, gain=3):
    _tone(tmp_path / "voice.wav")
    _tone(tmp_path / "music.wav", frequency=220, duration=4)
    edits = {
        "total_duration_seconds": 4,
        "audio": {
            "narration": {"segments": [
                {"asset_id": "voice", "start_seconds": 1, "end_seconds": 2},
            ]},
            "music": {"asset_id": "music", "volume": 0.3, "ducking": True},
        },
        "metadata": {"audio_mix": {
            "narration_gain_db": gain, "duck_level": -35,
            "master_gain_db": 3, "normalize": False,
        }},
    }
    assets = {"assets": [{"id": "voice", "path": "voice.wav"},
                         {"id": "music", "path": str(tmp_path / "music.wav")}]}
    return edits, assets


@pytest.mark.parametrize("gain", [None, "missing"])
def test_adapter_never_guesses_narration_gain(tmp_path, gain):
    edits, assets = _plan(tmp_path, gain)
    if gain == "missing":
        del edits["metadata"]["audio_mix"]["narration_gain_db"]
    with pytest.raises(ValueError, match="narration_gain_db"):
        documentary_mix_inputs(edits, assets, tmp_path)


def test_adapter_resolves_assets_without_mutating_approved_edits(tmp_path):
    edits, assets = _plan(tmp_path)
    original = deepcopy((edits, assets))
    params = documentary_mix_inputs(edits, assets, tmp_path)
    assert (edits, assets) == original
    assert params["tracks"][0]["path"] == str(tmp_path / "voice.wav")
    assert params["tracks"][0]["duration_seconds"] == 1
    assert params["tracks"][1]["volume"] == 0.3
    assert params["target_duration"] == 4
    assert params["peak_limit_db"] == -1
    assets["assets"][0]["path"] = "missing.wav"
    with pytest.raises(ValueError, match="Audio file not found"):
        documentary_mix_inputs(edits, assets, tmp_path)


@needs_ffmpeg
def test_voice_and_final_gain_have_measured_six_db_effect(tmp_path):
    voice = tmp_path / "voice.wav"
    _tone(voice)
    outputs = []
    for gain in (0, 3):
        output = tmp_path / f"gain-{gain}.wav"
        result = AudioMixer().execute({
            "operation": "full_mix", "tracks": [{"path": str(voice), "role": "speech"}],
            "normalize": False, "narration_gain_db": gain, "master_gain_db": gain,
            "output_path": str(output),
        })
        assert result.success, result.error
        outputs.append(output)
    delta_db = 20 * math.log10(_rms(outputs[1]) / _rms(outputs[0]))
    assert delta_db == pytest.approx(6, abs=0.03)


@needs_ffmpeg
def test_duck_level_is_honored_by_full_mix(tmp_path):
    silent = tmp_path / "silent.wav"
    music = tmp_path / "music.wav"
    _tone(silent, amplitude=0)
    _tone(music, frequency=220, amplitude=0.8)
    rms = []
    levels = (None, -20, -35)
    for level in levels:
        output = tmp_path / f"duck-{level}.wav"
        params = {
            "operation": "full_mix", "tracks": [
                {"path": str(silent), "role": "speech"},
                {"path": str(music), "role": "music"},
            ],
            "normalize": False, "output_path": str(output),
        }
        if level is None:
            params["ducking"] = {"enabled": False}
        else:
            params["duck_level"] = level
        result = AudioMixer().execute(params)
        assert result.success, result.error
        rms.append(_rms(output))

    for index, level in ((1, -20), (2, -35)):
        attenuation = 20 * math.log10(rms[index] / rms[0])
        # FFmpeg's sidechaincompress mixes 10% dry music back into the output;
        # with silence as the detector this reads up to 0.5 dB below the target.
        assert attenuation == pytest.approx(level, abs=0.6)


@needs_ffmpeg
def test_full_mix_reports_approved_balance(tmp_path):
    voice = tmp_path / "voice.wav"
    music = tmp_path / "music.wav"
    _tone(voice)
    _tone(music, frequency=220, amplitude=0.8)
    output = tmp_path / "approved-balance.wav"
    result = AudioMixer().execute({
        "operation": "full_mix", "tracks": [
            {"path": str(voice), "role": "speech"},
            {"path": str(music), "role": "music"},
        ],
        "narration_gain_db": 3, "duck_level": -35,
        "master_gain_db": 3, "normalize": False,
        "output_path": str(output),
    })
    assert result.success, result.error
    assert result.data["narration_gain_db"] == 3
    assert result.data["duck_level"] == -35
    assert result.data["master_gain_db"] == 3
    assert result.data["normalized"] is False


@needs_ffmpeg
def test_peak_limiter_caps_output_after_approved_gains(tmp_path):
    voice = tmp_path / "hot-voice.wav"
    _tone(voice, amplitude=0.9)
    output = tmp_path / "limited.wav"
    result = AudioMixer().execute({
        "operation": "full_mix", "tracks": [{"path": str(voice), "role": "speech"}],
        "normalize": False, "narration_gain_db": 3, "master_gain_db": 3,
        "peak_limit_db": -1, "output_path": str(output),
    })
    assert result.success, result.error
    assert result.data["narration_gain_db"] == 3
    assert result.data["master_gain_db"] == 3
    assert result.data["peak_limit_db"] == -1
    with wave.open(str(output), "rb") as audio:
        raw = audio.readframes(audio.getnframes())
    samples = struct.unpack(f"<{len(raw) // 2}h", raw)
    peak_dbfs = 20 * math.log10(max(abs(sample) for sample in samples) / 32768)
    assert peak_dbfs <= -0.95


@needs_ffmpeg
def test_canonical_segment_end_is_trimmed_before_scheduling(tmp_path):
    edits, assets = _plan(tmp_path, gain=0)
    edits["audio"].pop("music")
    params = documentary_mix_inputs(edits, assets, tmp_path)
    result = AudioMixer().execute(params)
    assert result.success, result.error
    assert _rms(params["output_path"], 0, 0.8) == 0
    assert _rms(params["output_path"], 1.1, 1.8) > 100
    assert _rms(params["output_path"], 2.2, 3.8) == 0


@needs_ffmpeg
@pytest.mark.parametrize("with_music", [True, False])
def test_multiple_narration_segments_keep_single_segment_volume(tmp_path, with_music):
    edits, assets = _plan(tmp_path, gain=0)
    edits["audio"]["music"]["volume"] = 0
    if not with_music:
        edits["audio"].pop("music")
    baseline = AudioMixer().execute(documentary_mix_inputs(edits, assets, tmp_path))
    assert baseline.success, baseline.error
    baseline_rms = _rms(baseline.data["output"], 1.2, 1.8)
    edits["audio"]["narration"]["segments"].append(
        {"asset_id": "voice", "start_seconds": 2, "end_seconds": 3}
    )
    extended = AudioMixer().execute(documentary_mix_inputs(edits, assets, tmp_path))
    assert extended.success, extended.error
    for start, end in ((1.2, 1.8), (2.2, 2.8)):
        assert 20 * math.log10(_rms(extended.data["output"], start, end) / baseline_rms) == pytest.approx(0, abs=0.03)


@pytest.mark.parametrize("key,value", [
    ("narration_gain_db", float("nan")), ("master_gain_db", float("inf")),
    ("master_gain_db", 99), ("duck_level", 1), ("duck_level", "invalid"),
    ("peak_limit_db", 1), ("peak_limit_db", -13), ("peak_limit_db", float("nan")),
    ("target_duration", float("inf")),
])
def test_invalid_levels_fail_before_running_ffmpeg(tmp_path, monkeypatch, key, value):
    voice = tmp_path / "voice.wav"
    _tone(voice)
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid inputs reached FFmpeg")
    monkeypatch.setattr(AudioMixer, "run_command", forbidden)
    result = AudioMixer().execute({
        "operation": "full_mix", "tracks": [{"path": str(voice), "role": "speech"}],
        key: value, "output_path": str(tmp_path / "out.wav"),
    })
    assert not result.success
    assert key in result.error


@needs_ffmpeg
def test_mix_passes_through_video_composition(tmp_path):
    edits, assets = _plan(tmp_path)
    before = deepcopy((edits, assets))
    params = documentary_mix_inputs(edits, assets, tmp_path)
    mixed = AudioMixer().execute(params)
    assert mixed.success, mixed.error
    assert (edits, assets) == before
    video, output = tmp_path / "source.mp4", tmp_path / "final.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "color=c=blue:s=320x180:d=4:r=30", "-c:v", "libx264", str(video),
    ], check=True, capture_output=True, timeout=30)
    # Exercise the existing media composition operation. This synthetic test
    # does not select or alter a production project's locked render runtime.
    composed = VideoCompose().execute({
        "operation": "compose",
        "edit_decisions": {
            "cuts": [{"source": str(video), "in_seconds": 0, "out_seconds": 4}],
            "metadata": {"compose_target": {"width": 320, "height": 180}},
        },
        "audio_path": mixed.data["output"], "output_path": str(output),
    })
    assert composed.success, composed.error
    extracted = tmp_path / "extracted.wav"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(output),
        "-vn", "-ar", "24000", "-ac", "1", str(extracted),
    ], check=True, capture_output=True, timeout=30)
    with wave.open(str(extracted), "rb") as audio:
        assert audio.getnframes() / audio.getframerate() == pytest.approx(4, abs=0.15)
    # Narration remains audible through AAC muxing, with the same level.
    assert 20 * math.log10(_rms(extracted, 1.2, 1.8) / _rms(params["output_path"], 1.2, 1.8)) == pytest.approx(0, abs=0.3)
