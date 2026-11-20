"""Harness 输出解析与错误识别。"""

from __future__ import annotations

import json
import re
from typing import Any

from .base import ProviderError

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_AUTH_CONTEXT_RE = re.compile(
    r"\b40[13]\b[^\n]*(?:unauthorized|auth(?:entication)?\b|api[ _-]?key|token|forbidden)",
    re.IGNORECASE,
)
_AUTH_PATTERNS = (
    _AUTH_CONTEXT_RE,
    re.compile(r"\bunauthorized\b", re.IGNORECASE),
    re.compile(r"authentication[_ ](?:error|failed)", re.IGNORECASE),
    re.compile(r"provider\.auth_error", re.IGNORECASE),
    re.compile(r"api[ _-]?key[^\n]*not permitted", re.IGNORECASE),
    re.compile(r"invalid\s+(?:x-)?api[ _-]?key", re.IGNORECASE),
    re.compile(r"\bforbidden\b", re.IGNORECASE),
)


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text or "")


def parse_json_text(text: str) -> dict[str, Any]:
    """从最终 assistant 文本中稳健提取 JSON 对象。"""
    text = strip_ansi(text or "").strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        pass
    else:
        if not isinstance(value, dict):
            raise ProviderError("Agent 响应不是 JSON 对象")
        return value

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"无法解析 Agent JSON 响应：{exc}") from exc
    if not isinstance(value, dict):
        raise ProviderError("Agent 响应不是 JSON 对象")
    return value


def looks_like_auth_error(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in _AUTH_PATTERNS)
