from __future__ import annotations

import pytest

from medharness2.config import AppConfig, LLMConfig
from medharness2.llm_client import LLMClient, LLMClientError, build_mock_client
from medharness2.utils.io import parse_json_object


def test_mock_client_returns_text():
    client = LLMClient(AppConfig(llm=LLMConfig(provider="mock")))
    result = client.call("hello", image_path="img.dcm")
    assert "mock response" in result
    assert "img.dcm" in result


def test_build_mock_client_returns_json():
    client = build_mock_client({"ok": True})
    result = parse_json_object(client.call("return json"), context="mock")
    assert result == {"ok": True}


def test_parse_json_object_rejects_invalid_json():
    with pytest.raises(ValueError):
        parse_json_object("not json", context="test")


def test_openai_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = LLMClient(AppConfig(llm=LLMConfig(provider="openai", max_retries=1)))
    with pytest.raises(LLMClientError):
        client.call("hello")
