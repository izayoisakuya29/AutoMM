"""Kimi Code 官方 CLI 适配器。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .base import (
    Invocation,
    LLMProvider,
    ProviderAuthError,
    ProviderConfigError,
    ProviderError,
    build_env,
)
from .parsing import looks_like_auth_error, parse_json_text
from .paths import expand_path, project_path

_REQUIRED_HELP = ("-m", "--model", "-p", "--prompt", "--output-format")


class KimiCodeProvider(LLMProvider):
    backend = "kimi_code"

    def _executable(self) -> str:
        value = str(self.config.get("executable", "node"))
        found = shutil.which(value)
        if found:
            return found
        candidate = project_path(value)
        if candidate.is_file():
            return str(candidate)
        raise ProviderConfigError(f"找不到 Kimi CLI 的 Node 可执行文件：{value}")

    def _main_js(self) -> Path:
        args = self.config.get("executable_args") or []
        if not args:
            raise ProviderConfigError("Kimi profile 的 executable_args 必须包含 main.mjs")
        path = project_path(args[0])
        if not path.is_file():
            raise ProviderConfigError(f"Kimi CLI main.mjs 不存在：{path}")
        return path

    def _home(self) -> Path:
        home = project_path(self.config.get("kimi_code_home", "runtime/kimi-code-home"))
        home.mkdir(parents=True, exist_ok=True)
        return home

    def _api_key(self) -> str:
        env_name = str(self.config.get("api_key_env", "KIMI_API_KEY"))
        value = os.environ.get(env_name)
        if value:
            return value
        key_file = self.config.get("api_key_file")
        if key_file:
            path = expand_path(key_file)
            if path.is_file():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    raise ProviderConfigError(f"Kimi api_key_file 不是合法 JSON：{path}") from exc
                if isinstance(data, dict) and data.get("apiKey"):
                    return str(data["apiKey"])
        raise ProviderConfigError("Kimi API key 缺失：请设置 api_key_env 或 api_key_file")

    def probe(self) -> dict[str, Any]:
        executable = self._executable()
        main_js = self._main_js()
        version = subprocess.run(
            [executable, str(main_js), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
        )
        if version.returncode != 0:
            raise ProviderError(f"Kimi CLI 版本探测失败：{(version.stderr or version.stdout).strip()[-500:]}")
        help_result = subprocess.run(
            [executable, str(main_js), "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
        )
        help_text = help_result.stdout + help_result.stderr
        missing = [flag for flag in _REQUIRED_HELP if flag not in help_text]
        if help_result.returncode != 0 or missing:
            raise ProviderConfigError(f"Kimi CLI 缺少必需参数：{missing}")
        return {
            "executable": executable,
            "main_js": str(main_js),
            "version": (version.stdout + version.stderr).strip().splitlines()[:1],
        }

    def prepare(self, prompt: str, output_path: Path) -> Invocation:
        model = str(self.config.get("model") or "")
        if not model:
            raise ProviderConfigError("Kimi profile 缺少 model")
        max_chars = int(self.config.get("max_prompt_chars", 30000))
        if len(prompt) > max_chars:
            raise ProviderConfigError(
                f"Kimi prompt 长度 {len(prompt)} 超过 max_prompt_chars={max_chars}"
            )
        command = [
            self._executable(),
            str(self._main_js()),
            "-m",
            model,
            "-p",
            prompt,
            "--output-format",
            "text",
        ]
        command.extend(str(item) for item in (self.config.get("extra_args") or []))

        env_extra: dict[str, Any] = {
            "KIMI_CODE_HOME": str(self._home()),
            "KIMI_API_KEY": self._api_key(),
        }
        base_url = self.config.get("base_url")
        if base_url:
            env_extra["KIMI_CODE_BASE_URL"] = str(base_url)
        env_extra.update(self.config.get("extra_env") or {})
        return Invocation(
            command=command,
            stdin=None,
            env=build_env(env_extra),
            output_path=output_path,
            meta={"model": model, "kimi_code_home": str(self._home())},
        )

    def extract_response(
        self,
        invocation: Invocation,
        stdout: str,
        stderr: str,
        returncode: int,
    ) -> dict[str, Any]:
        if returncode == 75:
            detail = (stderr or stdout).strip()[-2000:]
            raise ProviderError(f"Kimi Code 可重试失败（退出码 75）：{detail}")
        if returncode != 0:
            detail = (stderr or stdout).strip()[-2000:]
            if looks_like_auth_error(detail):
                raise ProviderAuthError(f"Kimi Code 认证失败：{detail}")
            raise ProviderError(f"Kimi Code 退出码 {returncode}：{detail}")
        text = (stdout or "").strip()
        if not text:
            raise ProviderError("Kimi Code 未产生最终响应文本")
        return parse_json_text(text)
