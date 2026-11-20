from __future__ import annotations

import pytest

from automm.llm.base import ProviderError
from automm.llm.parsing import looks_like_auth_error, parse_json_text, strip_ansi


def test_strip_ansi_removes_color_codes() -> None:
    assert strip_ansi("\x1b[31mhello\x1b[0m") == "hello"


def test_parse_json_text_strips_ansi_fences_and_prose() -> None:
    text = '\x1b[32mprefix\n```json\n{"a": 1}\n```\nsuffix\x1b[0m'
    assert parse_json_text(text) == {"a": 1}


def test_parse_json_text_rejects_array() -> None:
    with pytest.raises(ProviderError, match="不是 JSON 对象"):
        parse_json_text("[1, 2]")


def test_parse_json_text_rejects_array_of_objects() -> None:
    with pytest.raises(ProviderError, match="不是 JSON 对象"):
        parse_json_text('[{"a": 1}]')


def test_parse_json_text_rejects_quoted_json_string() -> None:
    with pytest.raises(ProviderError, match="不是 JSON 对象"):
        parse_json_text('"{\\"a\\": 1}"')


def test_parse_json_text_uses_first_fenced_block() -> None:
    text = '```json\n{"first": 1}\n```\nprose\n```json\n{"second": 2}\n```'
    assert parse_json_text(text) == {"first": 1}


def test_parse_json_text_rejects_invalid_json() -> None:
    with pytest.raises(ProviderError, match="无法解析"):
        parse_json_text("not json")


def test_looks_like_auth_error() -> None:
    assert looks_like_auth_error("HTTP 401 Unauthorized")
    assert looks_like_auth_error("HTTP 403 Forbidden")
    assert looks_like_auth_error("invalid api key")
    assert looks_like_auth_error("invalid x-api-key")
    assert not looks_like_auth_error("connection reset by peer")
    assert not looks_like_auth_error("permission denied")
    assert not looks_like_auth_error("request id 401234")


def test_looks_like_auth_error_recognizes_kimi_provider_auth_error() -> None:
    text = (
        "error: failed to run prompt: provider.auth_error: "
        "This API key is not permitted to access this endpoint."
    )
    assert looks_like_auth_error(text)


def test_looks_like_auth_error_recognizes_authentication_error() -> None:
    assert looks_like_auth_error("authentication_error: invalid credentials")


def test_looks_like_auth_error_rejects_bare_not_permitted() -> None:
    assert not looks_like_auth_error("sandbox: path not permitted")
