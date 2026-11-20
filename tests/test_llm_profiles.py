from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from automm.llm.base import ProviderConfigError
from automm.llm.codex_paths import find_codex_executable
from automm.llm.profiles import (
    load_agent_registry,
    load_profile,
    profile_warnings,
    resolve_profile,
    validate_agent_profiles,
    validate_profiles,
)


def make_runtime(tmp_path: Path) -> dict:
    home = tmp_path / "dsh-home"
    (home / "profiles" / "headless").mkdir(parents=True)
    key_file = tmp_path / "kimi-key.json"
    key_file.write_text(json.dumps({"apiKey": "test-key"}), encoding="utf-8")
    main_js = tmp_path / "main.mjs"
    main_js.write_text("", encoding="utf-8")
    return {
        "default_profile": "deepseek",
        "profiles": {
            "deepseek": {
                "harness": "dsh_headless",
                "executable": sys.executable,
                "dsh_home": str(home),
                "dsh_profile": "headless",
                "provider": "deepseek-official",
                "model": "deepseek-v4-pro",
            },
            "openai": {
                "harness": "codex_exec",
                "executable": sys.executable,
                "model": "gpt-6-luna",
                "bypass_approvals": True,
            },
            "kimi": {
                "harness": "kimi_code",
                "executable": sys.executable,
                "executable_args": [str(main_js)],
                "api_key_file": str(key_file),
                "model": "kimi-code/kimi-for-coding",
                "max_prompt_chars": 30000,
            },
        },
    }


def test_resolve_profile_uses_default(tmp_path: Path) -> None:
    config = make_runtime(tmp_path)
    agents = {"sanity-checker": {"prompt": "agents/sanity-checker.md", "stages": []}}
    resolved = resolve_profile("sanity-checker", runtime_config=config, agent_registry=agents)
    assert resolved["name"] == "deepseek"
    assert resolved["harness"] == "dsh_headless"


def test_resolve_profile_uses_agent_override(tmp_path: Path) -> None:
    config = make_runtime(tmp_path)
    agents = {
        "sanity-checker": {
            "prompt": "agents/sanity-checker.md",
            "stages": [],
            "profile": "openai",
        }
    }
    resolved = resolve_profile("sanity-checker", runtime_config=config, agent_registry=agents)
    assert resolved["name"] == "openai"
    assert resolved["harness"] == "codex_exec"


def test_resolve_profile_rejects_missing_agent(tmp_path: Path) -> None:
    with pytest.raises(ProviderConfigError, match="未注册"):
        resolve_profile("missing", runtime_config=make_runtime(tmp_path), agent_registry={})


def test_load_profile_rejects_disabled_profile(tmp_path: Path) -> None:
    config = make_runtime(tmp_path)
    config["profiles"]["openai"]["enabled"] = False
    with pytest.raises(ProviderConfigError, match="已禁用"):
        load_profile("openai", config)


def test_load_profile_rejects_openjiuwen(tmp_path: Path) -> None:
    config = make_runtime(tmp_path)
    config["profiles"]["openjiuwen"] = {"harness": "openjiuwen"}
    with pytest.raises(ProviderConfigError, match="openjiuwen"):
        load_profile("openjiuwen", config)


def test_validate_profiles_accepts_valid_config(tmp_path: Path) -> None:
    config = make_runtime(tmp_path)
    assert validate_profiles(config) == []
    assert validate_agent_profiles(config, {"sanity-checker": {"profile": "kimi"}}) == []


def test_validate_profiles_reports_unknown_field(tmp_path: Path) -> None:
    config = make_runtime(tmp_path)
    config["profiles"]["deepseek"]["models"] = []
    errors = validate_profiles(config)
    assert any("未知字段" in error for error in errors)


def test_validate_profiles_reports_missing_kimi_key(tmp_path: Path) -> None:
    config = make_runtime(tmp_path)
    config["profiles"]["kimi"].pop("api_key_file")
    errors = validate_profiles(config)
    assert any("api_key" in error for error in errors)


def test_profile_warnings_for_missing_kimi_env(tmp_path: Path) -> None:
    config = make_runtime(tmp_path)
    config["profiles"]["kimi"].pop("api_key_file")
    config["profiles"]["kimi"]["api_key_env"] = "AUTOMM_TEST_MISSING_KIMI_KEY"
    warnings = profile_warnings(config, environ={})
    assert any("AUTOMM_TEST_MISSING_KIMI_KEY" in warning for warning in warnings)


def test_validate_profiles_allows_disabled_openjiuwen(tmp_path: Path) -> None:
    config = make_runtime(tmp_path)
    config["profiles"]["openjiuwen"] = {"harness": "openjiuwen", "enabled": False}
    assert validate_profiles(config) == []


def test_validate_profiles_rejects_enabled_openjiuwen(tmp_path: Path) -> None:
    config = make_runtime(tmp_path)
    config["profiles"]["openjiuwen"] = {"harness": "openjiuwen"}
    errors = validate_profiles(config)
    assert any("openjiuwen" in error for error in errors)


def test_load_agent_registry_requires_registry_key() -> None:
    with pytest.raises(ProviderConfigError, match="registry"):
        load_agent_registry({})


def test_load_agent_registry_rejects_non_string_registry() -> None:
    with pytest.raises(ProviderConfigError, match="registry"):
        load_agent_registry({"registry": ["config/agent_registry.yaml"]})


def test_load_agent_registry_wraps_missing_registry(project_root: Path) -> None:
    with pytest.raises(ProviderConfigError, match="registry"):
        load_agent_registry({"registry": "config/does-not-exist-registry.yaml"})


def test_load_agent_registry_rejects_non_mapping_agents(project_root: Path) -> None:
    path = project_root / "config" / "bad-registry.yaml"
    path.write_text("agents: []\n", encoding="utf-8")
    with pytest.raises(ProviderConfigError, match="agents"):
        load_agent_registry({"registry": "config/bad-registry.yaml"})


def test_load_agent_registry_wraps_malformed_yaml(project_root: Path) -> None:
    path = project_root / "config" / "malformed-registry.yaml"
    path.write_text("agents: [unclosed\n", encoding="utf-8")
    with pytest.raises(ProviderConfigError, match="registry"):
        load_agent_registry({"registry": "config/malformed-registry.yaml"})


def test_load_agent_registry_rejects_top_level_list(project_root: Path) -> None:
    path = project_root / "config" / "list-registry.yaml"
    path.write_text("- sanity-checker\n", encoding="utf-8")
    with pytest.raises(ProviderConfigError, match="registry"):
        load_agent_registry({"registry": "config/list-registry.yaml"})


def test_load_profile_empty_config_does_not_use_defaults() -> None:
    with pytest.raises(ProviderConfigError, match="未知 profile"):
        load_profile("deepseek", {})


def test_resolve_profile_empty_config_does_not_use_defaults() -> None:
    agents = {"sanity-checker": {"prompt": "agents/sanity-checker.md", "stages": []}}
    with pytest.raises(ProviderConfigError, match="default_profile"):
        resolve_profile("sanity-checker", runtime_config={}, agent_registry=agents)


def test_validate_profiles_rejects_list_default_profile(tmp_path: Path) -> None:
    config = make_runtime(tmp_path)
    config["default_profile"] = ["deepseek"]
    errors = validate_profiles(config)
    assert any("default_profile" in error for error in errors)


def test_validate_profiles_rejects_list_harness(tmp_path: Path) -> None:
    config = make_runtime(tmp_path)
    config["profiles"]["deepseek"]["harness"] = ["dsh_headless"]
    errors = validate_profiles(config)
    assert any("未知 harness" in error for error in errors)


def test_validate_agent_profiles_rejects_list_profile(tmp_path: Path) -> None:
    config = make_runtime(tmp_path)
    errors = validate_agent_profiles(config, {"sanity-checker": {"profile": ["kimi"]}})
    assert any("profile 必须是非空字符串" in error for error in errors)


def test_validate_agent_profiles_skips_disabled_agent(tmp_path: Path) -> None:
    config = make_runtime(tmp_path)
    agents = {"sanity-checker": {"profile": "ghost", "enabled": False}}
    assert validate_agent_profiles(config, agents) == []


def test_validate_dsh_defaults_executable_to_dsh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_runtime(tmp_path)
    config["profiles"]["deepseek"].pop("executable")
    monkeypatch.setattr("automm.llm.profiles.shutil.which", lambda _name: None)
    errors = validate_profiles(config)
    assert any("dsh executable 不存在：dsh" in error for error in errors)


def test_validate_profiles_tolerates_missing_kimi_home_ancestors(tmp_path: Path) -> None:
    config = make_runtime(tmp_path)
    config["profiles"]["kimi"]["kimi_code_home"] = str(tmp_path / "runtime" / "kimi-code-home")
    errors = validate_profiles(config)
    assert not any("kimi_code_home" in error for error in errors)


def test_validate_profiles_rejects_kimi_home_below_regular_file(tmp_path: Path) -> None:
    config = make_runtime(tmp_path)
    blocked = tmp_path / "blocked"
    blocked.write_text("", encoding="utf-8")
    config["profiles"]["kimi"]["kimi_code_home"] = str(blocked / "home")
    errors = validate_profiles(config)
    assert any("kimi_code_home" in error for error in errors)


def test_validate_profiles_rejects_kimi_home_regular_file(tmp_path: Path) -> None:
    config = make_runtime(tmp_path)
    home_file = tmp_path / "kimi-home-file"
    home_file.write_text("", encoding="utf-8")
    config["profiles"]["kimi"]["kimi_code_home"] = str(home_file)
    errors = validate_profiles(config)
    assert any("kimi_code_home" in error for error in errors)


def test_validate_profiles_null_kimi_home_defaults_without_runtime(
    project_root: Path, tmp_path: Path
) -> None:
    config = make_runtime(tmp_path)
    config["profiles"]["kimi"]["kimi_code_home"] = None
    runtime = project_root / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    errors = validate_profiles(config)
    assert not any("kimi_code_home" in error for error in errors)


def test_find_codex_executable_sorts_versions_numerically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    windows_apps = tmp_path / "WindowsApps"
    for version in ("1.9.0.0", "1.10.0.0"):
        target = windows_apps / f"OpenAI.Codex_{version}_x64__test" / "app" / "resources"
        target.mkdir(parents=True)
        (target / "codex.exe").write_text("", encoding="utf-8")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.setattr("automm.llm.codex_paths.shutil.which", lambda _name: None)

    found = find_codex_executable({})

    assert found is not None
    assert "1.10.0.0" in found


def test_profile_warnings_for_missing_kimi_key_file(tmp_path: Path) -> None:
    config = make_runtime(tmp_path)
    config["profiles"]["kimi"]["api_key_file"] = str(tmp_path / "absent-key.json")
    warnings = profile_warnings(config, environ={})
    assert any("KIMI_API_KEY" in warning for warning in warnings)


def test_profile_warnings_suppressed_when_key_file_exists(tmp_path: Path) -> None:
    config = make_runtime(tmp_path)
    assert profile_warnings(config, environ={}) == []
