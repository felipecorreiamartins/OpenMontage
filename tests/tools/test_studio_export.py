"""Local FFmpeg integration tests: decode outputs, don't only inspect commands."""
import hashlib
import shutil
import subprocess
import threading
import time

import pytest

from lib.studio_timeline import TimelineItem, fit_to_audio
from tools.video import studio_export as exporter

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required"
)


def ffmpeg(*args):
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n", *map(str, args)],
        capture_output=True, timeout=60, creationflags=exporter.NO_WINDOW,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout


def fingerprint(paths):
    return {str(p): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in paths}


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    folder = tmp_path_factory.mktemp("mídias d'origem")
    red, blue, clip, wav = (folder / name for name in ("vermelho.png", "azul.png", "clipe.mp4", "voz.wav"))
    ffmpeg("-f", "lavfi", "-i", "color=red:s=320x180", "-frames:v", "1", red)
    ffmpeg("-f", "lavfi", "-i", "color=blue:s=320x180", "-frames:v", "1", blue)
    # Portrait, 24fps, short moving clip, with its own audio that must be ignored.
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=120x200:r=24:d=0.5", "-f", "lavfi", "-i",
           "sine=frequency=1800:duration=0.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", clip)
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1.6", "-c:a", "pcm_s16le", wav)
    return red, blue, clip, wav


def rgb_at(path, time):
    return tuple(ffmpeg("-ss", str(time), "-i", path, "-frames:v", "1", "-vf", "scale=1:1",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"))


@pytest.mark.parametrize("transition", ["cut", "crossfade", "fade"])
def test_real_transitions_frame_count_audio_and_source_preservation(media, tmp_path, transition):
    red, blue, _, wav = media
    original = fingerprint(media)
    overlap = 0 if transition == "cut" else 0.4
    items = [TimelineItem(red, (1.6 + overlap) / 2, transition, 0.4),
             TimelineItem(blue, (1.6 + overlap) / 2)]
    output = tmp_path / "saída d'água.mp4"
    progress = []
    report = exporter.render_timeline(items, wav, output, lambda n, text: progress.append(n))
    assert (report["width"], report["height"], report["fps"], report["frames"]) == (1920, 1080, 30, 48)
    assert report["audio_duration"] == pytest.approx(1.6, abs=0.025)
    assert progress[-1] == 1 and progress == sorted(progress)
    # Decode the entire movie to catch concat/PTS errors hidden by metadata.
    ffmpeg("-v", "error", "-xerror", "-i", output, "-f", "null", "-")
    first, last = rgb_at(output, 0.1), rgb_at(output, 1.4)
    assert first[0] > 200 and first[2] < 20
    assert last[2] > 200 and last[0] < 20
    middle = rgb_at(output, 0.8)
    if transition == "crossfade":
        assert middle[0] > 60 and middle[2] > 60 and middle[1] < 20
    elif transition == "fade":
        # FFmpeg fadeblack has an asymmetric curve; inspect the whole overlap
        # rather than assuming that black is exactly at its temporal midpoint.
        pixels = ffmpeg("-i", output, "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1")
        assert min(max(pixels[n * 3:n * 3 + 3]) for n in range(18, 30)) < 10
    else:
        assert middle[2] > 200 and middle[0] < 20
    assert fingerprint(media) == original
    assert not list(tmp_path.glob(".studio-export-*"))


def test_mixed_image_clip_and_consecutive_transitions(media, tmp_path):
    red, blue, clip, wav = media
    items = fit_to_audio([TimelineItem(red, 1, "crossfade", 0.2),
                          TimelineItem(clip, 2, "fade", 0.2), TimelineItem(blue, 1)], 1.6)
    result = exporter.StudioExport().execute({
        "items": [{"path": str(i.path), "duration": i.duration, "transition": i.transition,
                   "transition_duration": i.transition_duration} for i in items],
        "wav_path": str(wav), "output_path": str(tmp_path / "mixed.mp4"),
    })
    assert result.success, result.error
    assert result.cost_usd == 0 and result.data["frames"] == 48
    ffmpeg("-xerror", "-i", result.data["output"], "-f", "null", "-")


def test_single_clip_holds_last_frame_and_ignores_clip_audio(media, tmp_path):
    _, _, clip, wav = media
    output = tmp_path / "hold.mp4"
    exporter.render_timeline([TimelineItem(clip, 1.6)], wav, output)
    assert rgb_at(output, 0.8) == rgb_at(output, 1.4)
    samples = ffmpeg("-i", output, "-vn", "-f", "s16le", "-ac", "1", "-ar", "48000", "pipe:1")
    import array
    pcm = array.array("h", samples)
    # A 440 Hz WAV must win over the source clip's 1800 Hz audio.
    window = pcm[4800:24000]
    crossings = sum(a <= 0 < b for a, b in zip(window, window[1:]))
    assert 430 < crossings / 0.4 < 450


def test_rejects_existing_destination_and_wrong_timeline_without_writing(media, tmp_path):
    red, _, _, wav = media
    destination = tmp_path / "existing.mp4"
    destination.write_bytes(b"existing export")
    with pytest.raises(FileExistsError):
        exporter.render_timeline([TimelineItem(red, 1.6)], wav, destination)
    assert destination.read_bytes() == b"existing export"
    with pytest.raises(ValueError, match="Ajustar ao WAV"):
        exporter.render_timeline([TimelineItem(red, 1)], wav, tmp_path / "wrong.mp4")
    assert not (tmp_path / "wrong.mp4").exists()


def test_cancel_and_ffmpeg_failure_remove_only_own_temporary_outputs(media, tmp_path, monkeypatch):
    red, _, _, wav = media
    original = fingerprint(media)
    cancelled = threading.Event()
    destination = tmp_path / "cancelled.mp4"
    with pytest.raises(exporter.ExportCancelled):
        exporter.render_timeline([TimelineItem(red, 1.6)], wav, destination,
                                 lambda *_: cancelled.set(), cancelled)
    assert not destination.exists()
    monkeypatch.setattr(exporter, "_run_ffmpeg", lambda *_: (_ for _ in ()).throw(RuntimeError("test failure")))
    with pytest.raises(RuntimeError, match="test failure"):
        exporter.render_timeline([TimelineItem(red, 1.6)], wav, destination)
    assert not destination.exists() and not list(tmp_path.glob(".studio-export-*"))
    assert fingerprint(media) == original


def test_destination_created_during_render_is_never_overwritten(media, tmp_path):
    red, _, _, wav = media
    destination = tmp_path / "race.mp4"
    def progress(_fraction, message):
        if message.startswith("Conferindo"):
            destination.write_bytes(b"another application's file")
    with pytest.raises(FileExistsError):
        exporter.render_timeline([TimelineItem(red, 1.6)], wav, destination, progress)
    assert destination.read_bytes() == b"another application's file"


def test_missing_or_invalid_sources_fail_as_tool_results(media, tmp_path):
    red, _, _, wav = media
    for inputs in ({}, {"items": [{"path": str(tmp_path / "absent.png"), "duration": 1.6}],
                       "wav_path": str(wav), "output_path": str(tmp_path / "missing.mp4")}):
        result = exporter.StudioExport().execute(inputs)
        assert not result.success and result.error
    assert not list(tmp_path.glob("*.mp4"))


def test_cancelling_a_running_ffmpeg_terminates_the_process(tmp_path, monkeypatch):
    cancel = threading.Event()
    real_popen = subprocess.Popen
    processes = []
    def track(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(exporter.subprocess, "Popen", track)
    timer = threading.Timer(0.4, cancel.set)
    started = time.monotonic()
    timer.start()
    try:
        with pytest.raises(exporter.ExportCancelled):
            exporter._run_ffmpeg(["-re", "-f", "lavfi", "-i", "color=s=160x90:r=30",
                                 "-t", "30", "-f", "null", "-"], cancel, 60)
    finally:
        timer.cancel()
    assert time.monotonic() - started < 6
    assert len(processes) == 1 and processes[0].poll() is not None
