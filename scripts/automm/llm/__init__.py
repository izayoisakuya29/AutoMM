"""LLM provider 工厂。"""

from __future__ import annotations

from typing import Any

from .base import Invocation, LLMProvider, ProviderConfigError, ProviderError
from .codex import CodexProvider
from .dsh import DshHeadlessProvider

_PROVIDERS: dict[str, type[LLMProvider]] = {
    "codex_exec": CodexProvider,
    "dsh_headless": DshHeadlessProvider,
}


def get_provider(config: dict[str, Any]) -> LLMProvider:
    name = str(config.get("harness") or config.get("provider") or "")
    if name == "openjiuwen":
        raise ProviderConfigError("openjiuwen harness 本阶段仅保留扩展点，尚未实现")
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ProviderConfigError(f"未知 LLM harness：{name}")
    return cls(config)


__all__ = ["Invocation", "LLMProvider", "ProviderError", "get_provider"]