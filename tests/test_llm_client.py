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


def test_openai_multimodal_input_uses_data_urls(tmp_path):
    png = tmp_path / "image.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    image_input = LLMClient._build_input("look", str(png))
    pdf_input = LLMClient._build_input("read", str(pdf))
    assert image_input[0]["content"][1]["type"] == "input_image"
    assert image_input[0]["content"][1]["image_url"].startswith("data:image/png;base64,")
    assert pdf_input[0]["content"][0]["type"] == "input_file"
    assert pdf_input[0]["content"][0]["file_data"].startswith("data:application/pdf;base64,")
