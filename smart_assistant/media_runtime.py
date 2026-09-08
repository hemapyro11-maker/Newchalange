"""Shared media executable discovery and output validation."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess


def binary(name: str) -> str | None:
    override = os.environ.get(f"NEZUKO_{name.upper()}")
    if override and pathlib.Path(override).is_file():
        return str(pathlib.Path(override).resolve())
    found = shutil.which(name)
    if found:
        return found
    if name == "ffmpeg":
        try:
            import imageio_ffmpeg
            candidate = pathlib.Path(imageio_ffmpeg.get_ffmpeg_exe())
            return str(candidate) if candidate.is_file() else None
        except (ImportError, OSError, RuntimeError):
            return None
    return None


def run(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    resolved = list(args)
    if resolved and resolved[0] in {"ffmpeg", "ffprobe", "ffplay"}:
        executable = binary(resolved[0])
        if executable is None:
            raise FileNotFoundError(f"{resolved[0]} was not found")
        resolved[0] = executable
    return subprocess.run(
        resolved, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout, shell=False,
    )


def valid_output(path: str | pathlib.Path, *, minimum_bytes: int = 64) -> bool:
    target = pathlib.Path(path)
    return target.is_file() and target.stat().st_size >= minimum_bytes


def probe(path: str | pathlib.Path) -> dict | None:
    if binary("ffprobe") is None:
        return None
    try:
        result = run(["ffprobe", "-v", "error", "-print_format", "json",
                      "-show_format", "-show_streams", str(path)], 30)
        data = json.loads(result.stdout) if result.returncode == 0 else None
        return data if isinstance(data, dict) else None
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def has_stream(path: str | pathlib.Path, kind: str) -> bool | None:
    data = probe(path)
    if data is None:
        return None
    return any(s.get("codec_type") == kind for s in data.get("streams", []))
