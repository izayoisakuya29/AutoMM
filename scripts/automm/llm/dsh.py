"""DSH 0.2.2 headless 适配器。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from .base import (
    Invocation,
    LLMProvider,
    ProviderAuthError,
    ProviderConfigError,
    ProviderError,
    build_env,
)
from .parsing import looks_like_auth_error, parse_json_text as _parse_json_text
from .paths import expand_path, project_path


def _dsh_error_lines(stderr: str) -> str:
    """提取 DSH 自身错误行（以 `dsh:` 开头），避免把推理/工具诊断误判为认证错误。"""
    lines: list[str] = []
    for line in (stderr or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("dsh:"):
            lines.append(stripped)
    return "\n".join(lines[-20:])


class DshHeadlessProvider(LLMProvider):
    backend = "dsh_headless"

    def _executable(self) -> str:
        value = str(self.config.get("executable", "dsh"))
        candidate = project_path(value)
        if candidate.is_file():
            return str(candidate)
        found = shutil.which(value)
        if found:
            return found
        raise ProviderConfigError(f"找不到 dsh CLI：{value}")

    def _profile_name(self) -> str:
        return str(self.config.get("dsh_profile", "headless"))

    def _dsh_home_path(self) -> Path:
        return expand_path(self.config.get("dsh_home", "~/.dsh"))

    def _dsh_home(self) -> Path:
        home = self._dsh_home_path()
        if not home.is_dir():
            raise ProviderConfigError(f"dsh_home 不存在：{home}")
        if not (home / "profiles" / self._profile_name()).is_dir():
            raise ProviderConfigError(f"dsh profile 不存在：{home / 'profiles' / self._profile_name()}")
        return home

    def probe(self) -> dict[str, Any]:
        executable = self._executable()
        home = self._dsh_home()
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
        )
        if result.returncode != 0:
            raise ProviderError(f"dsh 探测失败：{(result.stderr or result.stdout).strip()[-500:]}")
        version = (result.stdout + result.stderr).strip().splitlines()[:1]
        return {"executable": executable, "version": version, "dsh_home": str(home)}

    def prepare(self, prompt: str, output_path: Path) -> Invocation:
        provider = str(self.config.get("provider") or "")
        model = str(self.config.get("model") or "")
        if not provider:
            raise ProviderConfigError("DSH profile 缺少 provider")
        if not model:
            raise ProviderConfigError("DSH profile 缺少 model")

        extra_config = self.config.get("patch_config")
        if extra_config is None:
            extra_config = {}
        elif not isinstance(extra_config, dict):
            raise ProviderConfigError("DSH patch_config 必须是映射")
        reserved = {key for key in ("provider", "model") if key in extra_config}
        if reserved:
            raise ProviderConfigError(f"DSH patch_config 不能覆盖保留字段：{sorted(reserved)}")
        patch_config: dict[str, Any] = {"provider": provider, "model": model, **extra_config}

        patch_path = output_path.parent / "dsh_patch.yml"
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        patch_path.write_text(
            yaml.safe_dump(
                [{"id": "agent-default-model", "config": patch_config}],
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        command = [
            self._executable(),
            *(str(item) for item in (self.config.get("executable_args") or [])),
            "--profile",
            self._profile_name(),
            "--patch",
            str(patch_path),
        ]
        permission_mode = str(self.config.get("permission_mode") or "workspace-write")
        command.extend(["--permission-mode", permission_mode])
        approval_policy = str(self.config.get("approval_policy") or "never")
        command.extend(["--approval-policy", approval_policy])
        command.extend(str(item) for item in (self.config.get("extra_args") or []))
        command.append("-")

        env = build_env(
            {
                "DSH_HOME": str(self._dsh_home_path()),
                **(self.config.get("extra_env") or {}),
            }
        )
        return Invocation(
            command=command,
            stdin=prompt,
            env=env,
            output_path=output_path,
            meta={
                "model": model,
                "provider": provider,
                "dsh_home": str(self._dsh_home_path()),
                "patch_path": str(patch_path),
            },
        )

    def extract_response(
        self,
        invocation: Invocation,
        stdout: str,
        stderr: str,
        returncode: int,
    ) -> dict[str, Any]:
        if returncode != 0:
            dsh_lines = _dsh_error_lines(stderr)
            detail = (dsh_lines or stderr or stdout).strip()[-2000:]
            if dsh_lines and looks_like_auth_error(dsh_lines):
                raise ProviderAuthError(f"dsh 认证失败：{detail}")
            raise ProviderError(f"dsh headless 退出码 {returncode}：{detail}")
        text = (stdout or "").strip()
        if not text:
            raise ProviderError("dsh headless 未产生最终响应文本")
        return _parse_json_text(text)
