from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from automm.llm.base import ProviderConfigError
from automm.llm.profiles import (
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
