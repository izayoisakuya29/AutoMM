"""Codex 可执行文件发现。"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

from .paths import project_path

_CODEX_VERSION_PATTERN = re.compile(r"OpenAI\.Codex_([0-9.]+)_")


def _codex_version_key(candidate: Path) -> tuple[int, ...]:
    match = _CODEX_VERSION_PATTERN.search(str(candidate))
    if not match:
        return (0,)
    parts = [int(part) for part in match.group(1).split(".") if part.isdigit()]
    return tuple(parts) or (0,)


def find_codex_executable(config: dict[str, Any]) -> str | None:
    value = str(config.get("executable", "auto"))
    if value and value != "auto":
        found = shutil.which(value)
        if found:
            return found
        candidate = project_path(value)
        if candidate.is_file():
            return str(candidate)
        return None
    found = shutil.which("codex")
    if found:
        return found
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    try:
        candidates = sorted(
            (program_files / "WindowsApps").glob("OpenAI.Codex_*/app/resources/codex.exe"),
            key=_codex_version_key,
        )
    except OSError:
        candidates = []
    return str(candidates[-1]) if candidates else None
