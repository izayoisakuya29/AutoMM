"""Codex 可执行文件发现。"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

from .paths import project_path

_CODEX_VERSION_PATTERN = re.compile(r"OpenAI\.Codex_([0-9.]+)_")
_APPX_REPOSITORY = (
    r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion"
    r"\AppModel\Repository\Packages"
)


def _appx_codex_candidates() -> list[Path]:
    """通过当前用户 AppX 注册表定位包根，绕开 WindowsApps 目录枚举限制。"""
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []
    candidates: list[Path] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _APPX_REPOSITORY) as repository:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(repository, index)
                except OSError:
                    break
                index += 1
                if not name.startswith("OpenAI.Codex_"):
                    continue
                try:
                    with winreg.OpenKey(repository, name) as package:
                        root_folder, _ = winreg.QueryValueEx(package, "PackageRootFolder")
                except OSError:
                    continue
                candidate = Path(str(root_folder)) / "app" / "resources" / "codex.exe"
                if candidate.is_file():
                    candidates.append(candidate)
    except OSError:
        return candidates
    return candidates


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
        candidates = list((program_files / "WindowsApps").glob("OpenAI.Codex_*/app/resources/codex.exe"))
    except OSError:
        candidates = []
    if not candidates:
        # Windows 11 默认禁止普通进程枚举 WindowsApps，退回 AppX 注册表。
        candidates = _appx_codex_candidates()
    candidates.sort(key=_codex_version_key)
    return str(candidates[-1]) if candidates else None
