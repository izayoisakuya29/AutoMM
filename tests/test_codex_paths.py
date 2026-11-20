from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from automm.llm.codex_paths import _appx_codex_candidates


class _FakeKey:
    def __init__(self, name: str) -> None:
        self.name = name

    def __enter__(self) -> _FakeKey:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _fake_winreg(packages: dict[str, str | None]) -> types.ModuleType:
    module = types.ModuleType("winreg")
    module.HKEY_CURRENT_USER = object()
    module.enum_calls = []
    names = list(packages)

    def open_key(_key: object, path: str) -> _FakeKey:
        return _FakeKey(path)

    def enum_key(_key: _FakeKey, index: int) -> str:
        module.enum_calls.append(index)
        if index >= len(names):
            raise OSError("枚举结束")
        return names[index]

    def query_value_ex(key: _FakeKey, name: str) -> tuple[str, int]:
        root = packages.get(key.name)
        if name != "PackageRootFolder" or root is None:
            raise OSError("缺少 PackageRootFolder")
        return root, 1

    module.OpenKey = open_key
    module.EnumKey = enum_key
    module.QueryValueEx = query_value_ex
    return module


def test_appx_codex_candidates_parses_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = tmp_path / "good"
    exe = good / "app" / "resources" / "codex.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("", encoding="utf-8")
    no_executable = tmp_path / "no-executable"
    no_executable.mkdir()
    packages = {
        "OpenAI.Codex_1.0.0_x64__good": str(good),
        "OpenAI.Codex_2.0.0_x64__noexe": str(no_executable),
        "OpenAI.Codex_3.0.0_x64__noroot": None,
        "Other.Vendor_1.0_x64__other": str(good),
    }
    fake = _fake_winreg(packages)
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr("automm.llm.codex_paths.os", types.SimpleNamespace(name="nt"))

    assert _appx_codex_candidates() == [exe]
    assert fake.enum_calls == list(range(len(packages) + 1))


def test_appx_codex_candidates_ignores_registry_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExplodingWinreg(types.ModuleType):
        def OpenKey(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("非 Windows 不应访问注册表")

    monkeypatch.setitem(sys.modules, "winreg", ExplodingWinreg("winreg"))
    monkeypatch.setattr("automm.llm.codex_paths.os", types.SimpleNamespace(name="posix"))

    assert _appx_codex_candidates() == []
