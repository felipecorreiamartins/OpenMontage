"""Availability must work even on machines without FFmpeg installed."""

import pytest

from tools.base_tool import DependencyError, ToolStatus
from tools.video.studio_export import StudioExport


@pytest.mark.parametrize("missing", [None, "ffmpeg", "ffprobe", "both"])
def test_availability_matches_dependency_contract(monkeypatch, missing):
    monkeypatch.setattr(
        "tools.base_tool.shutil.which",
        lambda command: None if missing in (command, "both") else f"/bin/{command}",
    )
    tool = StudioExport()
    available = missing is None
    assert tool.check_available() is available
    assert tool.get_status() == (ToolStatus.AVAILABLE if available else ToolStatus.UNAVAILABLE)
    assert tool.get_info()["status"] == tool.get_status().value
    if available:
        tool.check_dependencies()
    else:
        with pytest.raises(DependencyError):
            tool.check_dependencies()


def test_availability_refreshes_when_dependencies_change(monkeypatch):
    tool = StudioExport()
    monkeypatch.setattr("tools.base_tool.shutil.which", lambda command: f"/bin/{command}")
    assert tool.check_available() is True
    monkeypatch.setattr("tools.base_tool.shutil.which", lambda _command: None)
    assert tool.check_available() is False
