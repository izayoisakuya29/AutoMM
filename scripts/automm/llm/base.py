"""LLM harness 抽象：把 Agent 调用从具体 CLI 后端解耦。"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ENV_DROP_PREFIXES = ("ANTHROPIC_", "CLAUDE", "OPENAI_", "DEEPSEEK_")


class ProviderError(RuntimeError):
    """可重试的 harness 探测或调用失败（映射为 agent_transport）。"""


class ProviderConfigError(RuntimeError):
    """profile、可执行文件或凭据配置错误（映射为 external_human_required）。"""


class ProviderAuthError(RuntimeError):
    """CLI 明确报告认证失败（映射为 external_human_required）。"""


@dataclass
class Invocation:
    """一次 harness 调用的完整构造。"""

    command: list[str]
    stdin: str | None = None
    env: dict[str, str] | None = None
    output_path: Path | None = None
    meta: dict[str, Any] | None = None


def build_env(extra: dict[str, Any] | None = None) -> dict[str, str]:
    """构造子进程环境：保留系统变量，移除宿主会话的 provider 变量。"""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(_ENV_DROP_PREFIXES)
    }
    if extra:
        env.update({str(key): str(value) for key, value in extra.items() if value is not None})
    return env


class LLMProvider(ABC):
    backend: str = ""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    @abstractmethod
    def probe(self) -> dict[str, Any]:
        """探测可执行文件与必需能力；配置问题抛 ProviderConfigError。"""

    @abstractmethod
    def prepare(self, prompt: str, output_path: Path) -> Invocation:
        """构造一次调用；output_path 为结构化输出文件的期望位置。"""

    @abstractmethod
    def extract_response(
        self,
        invocation: Invocation,
        stdout: str,
        stderr: str,
        returncode: int,
    ) -> dict[str, Any]:
        """从运行产物提取并解析 JSON 响应；失败抛 ProviderError 或 ProviderAuthError。"""
