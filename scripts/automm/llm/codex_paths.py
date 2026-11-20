"""Codex 可执行文件发现。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .paths import project_path


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
        candidates = sorted((program_files / "WindowsApps").glob("OpenAI.Codex_*/app/resources/codex.exe"))
    except OSError:
        candidates = []
    return str(candidates[-1]) if candidates else None
