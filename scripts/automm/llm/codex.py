"""Codex CLI 适配器：OpenAI 原生协议。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ..common import ROOT, read_json, resolve_project_path
from .base import (
    Invocation,
    LLMProvider,
    ProviderAuthError,
    ProviderConfigError,
    ProviderError,
    build_env,
)
from .codex_paths import find_codex_executable
from .parsing import looks_like_auth_error
from .paths import expand_path

_REQUIRED_FLAGS = (
    "--output-schema",
    "--output-last-message",
    "--skip-git-repo-check",
    "--json",
    "--sandbox",
    "--approve-for-me",
    "--cd",
)


class CodexProvider(LLMProvider):
    backend = "codex_exec"

    def _executable(self) -> str:
        executable = find_codex_executable(self.config)
        if not executable:
            raise ProviderConfigError("找不到 Codex CLI：请检查 PATH 或 WindowsApps 安装")
        return executable

    def _codex_home(self) -> Path:
        return expand_path(self.config.get("codex_home", "~/.codex"))

    def probe(self) -> dict[str, Any]:
        executable = self._executable()
        version = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
        )
        if version.returncode != 0:
            raise ProviderError(f"Codex 版本探测失败：{(version.stderr or version.stdout).strip()[-500:]}")
        help_result = subprocess.run(
            [executable, "exec", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
        )
        help_text = help_result.stdout + help_result.stderr
        missing = [flag for flag in _REQUIRED_FLAGS if flag not in help_text]
        if help_result.returncode != 0 or missing:
            raise ProviderConfigError(f"Codex CLI 缺少必需能力：{missing}")
        return {
            "executable": executable,
            "version": (version.stdout + version.stderr).strip().splitlines()[:1],
        }

    def prepare(self, prompt: str, output_path: Path) -> Invocation:
        model = str(self.config.get("model") or "")
        if not model:
            raise ProviderConfigError("Codex profile 缺少 model")
        schema_path = resolve_project_path(self.config["output_schema"], must_exist=True)
        command = [
            self._executable(),
            "exec",
            "-",
            "-C",
            str(ROOT),
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
            "--json",
            "--color",
            "never",
        ]
        if self.config.get("skip_git_repo_check", True):
            command.append("--skip-git-repo-check")
        command.extend(["--model", model])
        config_profile = self.config.get("config_profile")
        if config_profile:
            command.extend(["-p", str(config_profile)])
        if self.config.get("bypass_approvals", True):
            command.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            sandbox = str(self.config.get("sandbox", "workspace-write"))
            command.extend(["--sandbox", sandbox, "--approve-for-me"])
        command.extend(str(item) for item in (self.config.get("extra_args") or []))

        env = build_env(
            {
                "CODEX_HOME": str(self._codex_home()),
                **(self.config.get("extra_env") or {}),
            }
        )
        return Invocation(
            command=command,
            stdin=prompt,
            env=env,
            output_path=output_path,
            meta={"model": model, "codex_home": str(self._codex_home())},
        )

    def extract_response(
        self,
        invocation: Invocation,
        stdout: str,
        stderr: str,
        returncode: int,
    ) -> dict[str, Any]:
        if returncode != 0:
            detail = (stderr or stdout).strip()[-2000:]
            if looks_like_auth_error(detail):
                raise ProviderAuthError(f"Codex 认证失败：{detail}")
            raise ProviderError(f"Codex Agent 退出码 {returncode}：{detail}")
        output_path = invocation.output_path
        if output_path is None or not output_path.exists():
            raise ProviderError("Agent 未生成 response.json")
        return read_json(output_path)
