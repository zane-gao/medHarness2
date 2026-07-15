from __future__ import annotations

import json
import subprocess

import fitz
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


def test_parse_json_object_accepts_a_full_markdown_json_fence():
    result = parse_json_object("```json\n{\"ok\": true}\n```", context="test")

    assert result == {"ok": True}


def test_parse_json_object_extracts_json_object_from_surrounding_prose():
    assert parse_json_object("Result follows: {\"ok\": true} end.", context="test") == {"ok": True}


def test_openai_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = LLMClient(AppConfig(llm=LLMConfig(provider="openai", max_retries=1)))
    with pytest.raises(LLMClientError):
        client.call("hello", payload_classification="synthetic_test")


def test_call_can_override_provider_endpoint_and_runtime_options(monkeypatch):
    monkeypatch.setenv("DMX_API_KEY", "test-only-secret")
    captured = {}

    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"ok": true}'}}]}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = json
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("requests.post", fake_post)
    client = LLMClient(AppConfig(llm=LLMConfig(provider="mock", model="default-model")))

    result = client.call(
        "Return JSON.",
        provider="chat_completions",
        base_url="https://www.DMXAPI.cn/v1",
        api_key_env="DMX_API_KEY",
        model="gpt-5.5",
        timeout_sec=123,
        max_retries=1,
        max_tokens=321,
        seed=17,
        response_format="json",
        payload_classification="synthetic_test",
    )

    assert json.loads(result) == {"ok": True}
    assert captured["url"] == "https://www.DMXAPI.cn/v1/chat/completions"
    assert captured["payload"]["model"] == "gpt-5.5"
    assert captured["payload"]["max_tokens"] == 321
    assert captured["payload"]["seed"] == 17
    assert captured["timeout"] == 123
    assert "test-only-secret" not in json.dumps(captured["payload"])


def test_chat_completions_can_omit_temperature_for_models_that_reject_it(monkeypatch):
    monkeypatch.setenv("DMX_API_KEY", "test-only-secret")
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"ok": true}'}}]}

    def fake_post(url, headers, json, timeout):
        captured["payload"] = json
        return _Response()

    monkeypatch.setattr("requests.post", fake_post)
    client = LLMClient(AppConfig(llm=LLMConfig(provider="mock")))

    client.call(
        "Return JSON.",
        provider="chat_completions",
        api_key_env="DMX_API_KEY",
        base_url="https://www.DMXAPI.cn/v1",
        model="claude-opus-4-8",
        omit_temperature=True,
        response_format="json",
        payload_classification="synthetic_test",
    )

    assert "temperature" not in captured["payload"]


def test_chat_completions_honors_retry_after_for_rate_limits(monkeypatch):
    monkeypatch.setenv("DMX_API_KEY", "test-only-secret")
    calls = 0
    sleeps = []

    class Response:
        status_code = 429
        headers = {"Retry-After": "7"}

        def raise_for_status(self):
            return None

        def json(self):
            return {"error": {"message": "rate limited"}}

    def fake_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        return Response()

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("time.sleep", lambda value: sleeps.append(value))
    client = LLMClient(AppConfig(llm=LLMConfig(provider="mock", max_retries=2)))
    with pytest.raises(LLMClientError):
        client.call("hello", provider="chat_completions", api_key_env="DMX_API_KEY", max_retries=2, payload_classification="synthetic_test")
    assert calls == 2
    assert sleeps == [7.0]


def test_chat_completions_preserves_structured_provider_error_details(monkeypatch):
    monkeypatch.setenv("DMX_API_KEY", "test-only-secret")

    class _Response:
        status_code = 403

        def json(self):
            return {
                "error": {
                    "code": "insufficient_user_quota",
                    "type": "quota_error",
                    "message": "Insufficient balance for token reservation.",
                }
            }

        def raise_for_status(self):
            raise AssertionError("structured HTTP errors should be handled before raise_for_status")

    monkeypatch.setattr("requests.post", lambda *args, **kwargs: _Response())
    client = LLMClient(AppConfig(llm=LLMConfig(provider="mock")))

    with pytest.raises(LLMClientError) as exc_info:
        client.call(
            "Return JSON.",
            provider="chat_completions",
            api_key_env="DMX_API_KEY",
            base_url="https://www.DMXAPI.cn/v1",
            model="gpt-5.6-terra",
            max_retries=1,
            response_format="json",
            payload_classification="synthetic_test",
        )

    message = str(exc_info.value)
    assert "HTTP 403" in message
    assert "insufficient_user_quota" in message
    assert "quota_error" in message
    assert "Insufficient balance" in message
    assert "test-only-secret" not in message


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


def test_local_vlm_cli_provider_invokes_legacy_runner(monkeypatch, tmp_path):
    script = tmp_path / "run_report_generation.py"
    script.write_text("# fake runner\n", encoding="utf-8")
    config = tmp_path / "reportgen_models.yaml"
    config.write_text("models: {}\n", encoding="utf-8")
    image = tmp_path / "report_page.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    calls = []

    def fake_run(cmd, check, capture_output, text, timeout):
        calls.append(cmd)
        input_path = cmd[cmd.index("--input-jsonl") + 1]
        output_path = cmd[cmd.index("--output-jsonl") + 1]
        row = json.loads(open(input_path, encoding="utf-8").read())
        assert row["prompt"] == "Extract the report text."
        assert row["image_paths"] == [str(image.resolve())]
        assert row["modality"] == "generic_image"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"case_id": row["case_id"], "generated_text": "FINDINGS: Local OCR."}) + "\n")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = LLMClient(
        AppConfig(
            llm=LLMConfig(
                provider="local_vlm_cli",
                model="qwen25vl_7b_instruct",
                local_cli_python_bin="/opt/local/python",
                local_cli_script=str(script),
                local_cli_config_path=str(config),
                local_cli_device="cuda:0",
                local_cli_dtype="bf16",
                local_cli_max_new_tokens=256,
                local_cli_timeout_sec=30,
            )
        )
    )
    result = client.call("Extract the report text.", image_path=str(image))
    assert result == "FINDINGS: Local OCR."
    assert calls[0][0] == "/opt/local/python"
    assert calls[0][calls[0].index("--model-key") + 1] == "qwen25vl_7b_instruct"


def test_local_hf_vlm_provider_renders_pdf_before_generation(monkeypatch, tmp_path):
    pdf = tmp_path / "report.pdf"
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    doc.save(pdf)
    model_dir = tmp_path / "qwen3-vl-4b"
    model_dir.mkdir()
    seen = {}

    def fake_generate(self, prompt, image_paths, max_new_tokens):
        seen["prompt"] = prompt
        seen["image_paths"] = image_paths
        seen["max_new_tokens"] = max_new_tokens
        return "FINDINGS: Local HF OCR."

    monkeypatch.setattr(LLMClient, "_generate_local_hf_vlm", fake_generate)
    client = LLMClient(
        AppConfig(
            llm=LLMConfig(
                provider="local_hf_vlm",
                model="qwen3-vl-4b",
                local_hf_model_path=str(model_dir),
                local_hf_max_new_tokens=96,
            )
        )
    )
    result = client.call("Extract the report text.", image_path=str(pdf))
    assert result == "FINDINGS: Local HF OCR."
    assert seen["prompt"] == "Extract the report text."
    assert seen["max_new_tokens"] == 96
    assert seen["image_paths"] and seen["image_paths"][0].endswith(".png")


def test_local_hf_vlm_loader_reuses_cached_model(tmp_path):
    model_dir = tmp_path / "qwen3-vl-4b"
    model_dir.mkdir()
    client = LLMClient(
        AppConfig(
            llm=LLMConfig(
                provider="local_hf_vlm",
                local_hf_model_path=str(model_dir),
                local_hf_device="cuda:0",
                local_hf_dtype="bf16",
            )
        )
    )
    cache_key = (str(model_dir), "cuda:0", "bf16")
    client._local_hf_cache[cache_key] = ("model", "processor")
    assert client._load_local_hf_vlm() == ("model", "processor")
