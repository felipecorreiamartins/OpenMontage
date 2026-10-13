"""Kokoro local TTS provider for OpenMontage."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool, Determinism, ExecutionMode, ResourceProfile,
    RetryPolicy, ToolResult, ToolRuntime, ToolStability,
    ToolStatus, ToolTier,
)


class KokoroTTS(BaseTool):
    name = "kokoro_tts"
    version = "0.1.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "kokoro"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = []
    capabilities = ["text_to_speech", "offline_generation"]
    supports = {
        "voice_cloning": False,
        "multilingual": True,
        "offline": True,
        "native_audio": True,
    }
    best_for = ["natural English narration", "offline YouTube videos"]
    not_good_for = ["voice cloning"]

    input_schema = {
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {"type": "string"},
            "voice": {"type": "string", "default": "am_echo"},
            "voice_id": {"type": "string"},
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=12, ram_mb=2048, vram_mb=0,
        disk_mb=500, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=[])
    idempotency_key_fields = ["text", "voice"]
    side_effects = ["writes audio file to output_path"]
    user_visible_verification = ["Listen to generated audio"]

    PYTHON = Path(r"D:\YouTube-Automacao\.venv-kokoro\Scripts\python.exe")
    RUNNER = Path(r"D:\YouTube-Automacao\kokoro_runner.py")

    def get_status(self) -> ToolStatus:
        if self.PYTHON.is_file() and self.RUNNER.is_file():
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if self.get_status() != ToolStatus.AVAILABLE:
            return ToolResult(success=False, error="Kokoro environment or runner not found.")

        text = str(inputs.get("text", "")).strip()
        if not text:
            return ToolResult(success=False, error="Narration text is empty.")

        voice = inputs.get("voice_id") or inputs.get("voice") or "am_echo"
        output = Path(inputs.get("output_path") or "kokoro_output.wav").resolve()
        output.parent.mkdir(parents=True, exist_ok=True)

        start = time.time()
        temp_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", encoding="utf-8",
                delete=False
            ) as temp:
                temp.write(text)
                temp_path = Path(temp.name)

            env = os.environ.copy()
            env["HF_HOME"] = r"D:\YouTube-Automacao\Modelos-IA"

            proc = subprocess.run(
                [
                    str(self.PYTHON),
                    str(self.RUNNER),
                    "--text-file", str(temp_path),
                    "--output", str(output),
                    "--voice", str(voice),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1800,
                env=env,
            )

            if proc.returncode != 0:
                return ToolResult(
                    success=False,
                    error=f"Kokoro failed: {proc.stderr[-3000:]}"
                )

            if not output.is_file():
                return ToolResult(success=False, error="Kokoro output file missing.")

            return ToolResult(
                success=True,
                data={
                    "provider": self.provider,
                    "voice": voice,
                    "text_length": len(text),
                    "output": str(output),
                    "format": "wav",
                },
                artifacts=[str(output)],
                model="kokoro-82m",
                duration_seconds=round(time.time() - start, 2),
            )

        except Exception as exc:
            return ToolResult(success=False, error=f"Kokoro error: {exc}")

        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
