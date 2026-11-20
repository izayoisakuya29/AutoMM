"""Profile 加载、按 Agent 解析和配置校验。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from ..common import ROOT, read_yaml, resolve_project_path
from .base import ProviderConfigError
from .paths import expand_path, project_path

HARNESSES = {"dsh_headless", "codex_exec", "kimi_code", "openjiuwen"}

_COMMON_FIELDS = {
    "harness",
    "enabled",
    "executable",
    "executable_args",
    "extra_args",
    "extra_env",
    "timeout_seconds",
}
_HARNESS_FIELDS = {
    "dsh_headless": {
        "dsh_home",
        "dsh_profile",
        "provider",
        "model",
        "permission_mode",
        "approval_policy",
        "patch_config",
    },
    "codex_exec": {
        "codex_home",
        "model",
        "sandbox",
        "bypass_approvals",
        "skip_git_repo_check",
        "config_profile",
    },
    "kimi_code": {
        "kimi_code_home",
        "api_key_file",
        "api_key_env",
        "base_url",
        "model",
        "max_prompt_chars",
    },
    "openjiuwen": set(),
}


def load_runtime_config() -> dict[str, Any]:
    return read_yaml(ROOT / "config" / "agent_runtime.yaml")


def load_agent_registry(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_runtime_config()
    path = resolve_project_path(config["registry"], must_exist=True)
    return read_yaml(path).get("agents", {})


def load_profile(name: str, runtime_config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = runtime_config or load_runtime_config()
    profiles = config.get("profiles") or {}
    if not isinstance(profiles, dict):
        raise ProviderConfigError("agent_runtime.profiles 必须是映射")
    profile = profiles.get(name)
    if not isinstance(profile, dict):
        raise ProviderConfigError(f"未知 profile：{name}")
    if profile.get("enabled", True) is False:
        raise ProviderConfigError(f"profile 已禁用：{name}")
    harness = str(profile.get("harness") or "")
    if harness not in HARNESSES:
        raise ProviderConfigError(f"profile {name} 的 harness 未知：{harness}")
    if harness == "openjiuwen":
        raise ProviderConfigError("openjiuwen harness 本阶段仅保留扩展点，尚未实现")
    resolved = dict(profile)
    resolved["name"] = name
    resolved["harness"] = harness
    return resolved


def resolve_profile(
    agent: str,
    runtime_config: dict[str, Any] | None = None,
    agent_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = runtime_config or load_runtime_config()
    agents = agent_registry if agent_registry is not None else load_agent_registry(config)
    entry = agents.get(agent)
    if not isinstance(entry, dict) or entry.get("enabled", True) is False:
        raise ProviderConfigError(f"Agent 未注册或已禁用：{agent}")
    name = entry.get("profile") or config.get("default_profile")
    if not name:
        raise ProviderConfigError("未设置 default_profile")
    return load_profile(str(name), config)


def _resolves_executable(value: str | Path | None) -> bool:
    if not value:
        return False
    text = str(value)
    return bool(shutil.which(text)) or project_path(text).is_file()


def _validate_dsh(name: str, profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not _resolves_executable(profile.get("executable")):
        errors.append(f"profile {name}: dsh executable 不存在：{profile.get('executable')}")
    home = expand_path(profile.get("dsh_home", "~/.dsh"))
    if not home.is_dir():
        errors.append(f"profile {name}: dsh_home 不存在：{home}")
    else:
        dsh_profile = str(profile.get("dsh_profile", "headless"))
        if not (home / "profiles" / dsh_profile).is_dir():
            errors.append(f"profile {name}: dsh profile 不存在：{home / 'profiles' / dsh_profile}")
    for key in ("provider", "model"):
        if not profile.get(key):
            errors.append(f"profile {name}: {key} 不能为空")
    return errors


def _validate_codex(name: str, profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    from .codex_paths import find_codex_executable

    if find_codex_executable(profile) is None:
        errors.append(f"profile {name}: 找不到 codex 可执行文件")
    if not profile.get("model"):
        errors.append(f"profile {name}: model 不能为空")
    if not profile.get("bypass_approvals", True):
        sandbox = str(profile.get("sandbox", "workspace-write"))
        if sandbox not in {"read-only", "workspace-write", "danger-full-access"}:
            errors.append(f"profile {name}: sandbox 非法：{sandbox}")
    return errors


def _validate_kimi(name: str, profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not _resolves_executable(profile.get("executable", "node")):
        errors.append(f"profile {name}: kimi executable 不存在：{profile.get('executable', 'node')}")
    args = profile.get("executable_args") or []
    if not args:
        errors.append(f"profile {name}: executable_args 必须包含 main.mjs")
    else:
        main_js = project_path(args[0])
        if not main_js.is_file():
            errors.append(f"profile {name}: main.mjs 不存在：{main_js}")
    if not profile.get("model"):
        errors.append(f"profile {name}: model 不能为空")
    max_chars = profile.get("max_prompt_chars", 30000)
    if not isinstance(max_chars, int) or max_chars <= 0:
        errors.append(f"profile {name}: max_prompt_chars 必须是正整数")
    key_file = profile.get("api_key_file")
    key_env = profile.get("api_key_env")
    if not key_file and not key_env:
        errors.append(f"profile {name}: 必须提供 api_key_file 或 api_key_env")
    elif key_file and not expand_path(key_file).is_file():
        errors.append(f"profile {name}: api_key_file 不存在：{key_file}")
    return errors


def validate_profiles(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    profiles = config.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        return ["agent_runtime.profiles 必须是非空映射"]
    default = config.get("default_profile")
    if not default:
        errors.append("agent_runtime.default_profile 不能为空")
    elif default not in profiles:
        errors.append(f"default_profile 不存在：{default}")
    elif not isinstance(profiles[default], dict) or profiles[default].get("enabled", True) is False:
        errors.append(f"default_profile 已禁用：{default}")
    for name, profile in profiles.items():
        if not isinstance(profile, dict):
            errors.append(f"profile {name} 必须是映射")
            continue
        harness = profile.get("harness")
        if harness not in HARNESSES:
            errors.append(f"profile {name}: 未知 harness：{harness}")
            continue
        allowed = _COMMON_FIELDS | _HARNESS_FIELDS[harness]
        for key in profile:
            if key not in allowed:
                errors.append(f"profile {name}: 未知字段：{key}")
        if harness == "openjiuwen":
            errors.append(f"profile {name}: openjiuwen 本阶段仅保留扩展点，尚未实现")
            continue
        if profile.get("enabled", True) is False:
            continue
        if harness == "dsh_headless":
            errors.extend(_validate_dsh(name, profile))
        elif harness == "codex_exec":
            errors.extend(_validate_codex(name, profile))
        elif harness == "kimi_code":
            errors.extend(_validate_kimi(name, profile))
    return errors


def validate_agent_profiles(config: dict[str, Any], agents: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    profiles = config.get("profiles") or {}
    for agent, entry in agents.items():
        if not isinstance(entry, dict):
            continue
        name = entry.get("profile")
        if not name:
            continue
        profile = profiles.get(name) if isinstance(profiles, dict) else None
        if not isinstance(profile, dict):
            errors.append(f"Agent {agent}: 未知 profile：{name}")
        elif profile.get("enabled", True) is False:
            errors.append(f"Agent {agent}: profile 已禁用：{name}")
    return errors


def profile_warnings(
    config: dict[str, Any],
    environ: dict[str, str] | None = None,
) -> list[str]:
    environ = os.environ if environ is None else environ
    warnings: list[str] = []
    profiles = config.get("profiles") or {}
    if not isinstance(profiles, dict):
        return warnings
    for name, profile in profiles.items():
        if not isinstance(profile, dict) or profile.get("harness") != "kimi_code":
            continue
        if profile.get("enabled", True) is False:
            continue
        env_name = str(profile.get("api_key_env", "KIMI_API_KEY"))
        if not environ.get(env_name) and not profile.get("api_key_file"):
            warnings.append(f"profile {name}: 环境变量 {env_name} 未设置，运行时可能需要人工阻塞")
    return warnings
