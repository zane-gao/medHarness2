from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import base64
import mimetypes
import re
import tempfile
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import requests

from medharness2.config import AppConfig, LLMConfig, load_config, resolve_existing_path
from medharness2.privacy import ExternalPayloadPolicy


class LLMClientError(RuntimeError):
    """Raised when the configured LLM provider cannot complete a request."""


_RETRYABLE_HTTP_STATUS = {408, 409, 425, 429}


def _is_retryable_status(status: Any) -> bool:
    try:
        code = int(status)
    except (TypeError, ValueError):
        return False
    return code in _RETRYABLE_HTTP_STATUS or 500 <= code <= 599


class LLMClient:
    def __init__(self, config: AppConfig | None = None):
        self.config = config or load_config()
        self.privacy_policy = ExternalPayloadPolicy(self.config.privacy)
        self._local_hf_cache: dict[tuple[str, str, str], tuple[Any, Any]] = {}

    def call(self, prompt: str, image_path: str | None = None, **kwargs: Any) -> str:
        provider = str(kwargs.pop("provider", None) or self.config.llm.provider).lower()
        classification = str(kwargs.pop("payload_classification", "") or "")
        if self.config.privacy.enforce_external and provider in {
            "openai",
            "openai_responses",
            "chat_completions",
            "openai_chat",
            "codex_proxy",
            "codex",
        }:
            self.privacy_policy.validate_external(prompt, image_path=image_path, classification=classification)
        if provider == "mock":
            return self._mock_response(prompt, image_path=image_path, **kwargs)
        if provider in {"openai", "openai_responses"}:
            return self._call_openai_responses(prompt, image_path=image_path, **kwargs)
        # chat_completions：OpenAI 兼容 /chat/completions（codex 代理走这条）。
        if provider in {"chat_completions", "openai_chat", "codex_proxy", "codex"}:
            return self._call_chat_completions(prompt, image_path=image_path, **kwargs)
        if provider in {"local_vlm_cli", "medharness_cli_vlm"}:
            return self._call_local_vlm_cli(prompt, image_path=image_path, **kwargs)
        if provider in {"local_hf_vlm", "hf_vlm_local"}:
            return self._call_local_hf_vlm(prompt, image_path=image_path, **kwargs)
        raise LLMClientError(f"Unsupported LLM provider: {provider}")

    def _mock_response(self, prompt: str, image_path: str | None = None, **kwargs: Any) -> str:
        response_json = kwargs.get("response_json")
        if response_json is not None:
            return json.dumps(response_json, ensure_ascii=False)
        if kwargs.get("json_mode"):
            return "{}"
        suffix = f" image={image_path}" if image_path else ""
        return f"mock response for prompt length {len(prompt)}{suffix}"

    def _call_openai_responses(self, prompt: str, image_path: str | None = None, **kwargs: Any) -> str:
        llm = self.config.llm
        api_key_env = kwargs.get("api_key_env") or llm.api_key_env
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise LLMClientError(f"Missing API key environment variable: {api_key_env}")
        payload: dict[str, Any] = {
            "model": kwargs.get("model") or llm.model,
            "input": self._build_input(prompt, image_path),
        }
        if not kwargs.get("omit_temperature"):
            payload["temperature"] = kwargs.get("temperature", llm.temperature)
        seed = kwargs.get("seed", llm.seed)
        if seed is not None:
            payload["seed"] = int(seed)
        if kwargs.get("response_format") == "json":
            payload["text"] = {"format": {"type": "json_object"}}
        data = json.dumps(payload).encode("utf-8")
        endpoint = str(kwargs.get("base_url") or llm.base_url).rstrip("/") + "/responses"
        request = urllib.request.Request(
            endpoint,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        last_error: Exception | None = None
        max_retries = max(1, int(kwargs.get("max_retries") or llm.max_retries))
        timeout_sec = int(kwargs.get("timeout_sec") or llm.timeout_sec)
        for attempt in range(max_retries):
            response = None
            try:
                with urllib.request.urlopen(request, timeout=timeout_sec) as response:
                    body = json.loads(response.read().decode("utf-8"))
                body_error = _structured_body_error(body)
                if body_error:
                    raise LLMClientError(f"OpenAI Responses API returned an error: {body_error}")
                return self._extract_text(body)
            except LLMClientError as exc:
                # A valid HTTP response carrying an API/schema error is not a
                # transport failure; retry only when a retryable status is known.
                last_error = exc
                status = getattr(response, "status", getattr(response, "status_code", 0))
                if not _is_retryable_status(status) or attempt + 1 >= max_retries:
                    break
                delay = _retry_after_seconds(response)
                time.sleep(delay if delay is not None else llm.retry_initial_sec * (2**attempt))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt + 1 >= max_retries:
                    break
                retry_response = response
                if isinstance(exc, urllib.error.HTTPError):
                    retry_response = exc
                status = getattr(retry_response, "status", getattr(retry_response, "status_code", 0))
                if isinstance(exc, urllib.error.HTTPError) and not _is_retryable_status(status):
                    break
                delay = _retry_after_seconds(retry_response) if _is_retryable_status(status) else None
                time.sleep(delay if delay is not None else llm.retry_initial_sec * (2**attempt))
        raise LLMClientError(f"OpenAI Responses API call failed: {last_error}")

    def _call_chat_completions(self, prompt: str, image_path: str | None = None, **kwargs: Any) -> str:
        """OpenAI 兼容 /chat/completions。支持 per-call 覆盖 api_key_env / model，
        用于多模型评委（GPT key 与 Claude key 路由到同一代理的不同模型）。"""
        llm = self.config.llm
        # per-call 覆盖优先，其次取配置默认；这样评委循环能对同一 client 传不同 key/model。
        api_key_env = kwargs.get("api_key_env") or llm.api_key_env
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise LLMClientError(f"Missing API key environment variable: {api_key_env}")
        messages = [{"role": "user", "content": self._build_chat_content(prompt, image_path)}]
        payload: dict[str, Any] = {
            "model": kwargs.get("model") or llm.model,
            "messages": messages,
        }
        if not kwargs.get("omit_temperature"):
            payload["temperature"] = kwargs.get("temperature", llm.temperature)
        seed = kwargs.get("seed", llm.seed)
        if seed is not None:
            payload["seed"] = int(seed)
        max_tokens = kwargs.get("max_tokens") or llm.chat_max_tokens
        if max_tokens:
            payload["max_tokens"] = int(max_tokens)
        if kwargs.get("response_format") == "json":
            payload["response_format"] = {"type": "json_object"}
        endpoint = str(kwargs.get("base_url") or llm.base_url).rstrip("/") + "/chat/completions"
        last_error: Exception | None = None
        max_retries = max(1, int(kwargs.get("max_retries") or llm.max_retries))
        timeout_sec = int(kwargs.get("timeout_sec") or llm.timeout_sec)
        for attempt in range(max_retries):
            response = None
            try:
                response = requests.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=timeout_sec,
                )
                provider_error = _structured_provider_error(response)
                if provider_error:
                    raise LLMClientError(
                        f"Chat Completions HTTP {getattr(response, 'status_code', 'unknown')}: "
                        f"{provider_error}"
                    )
                response.raise_for_status()
                body = response.json()
                return self._extract_chat_text(body)
            except LLMClientError as exc:
                last_error = exc
                status = getattr(response, "status_code", 0)
                if not _is_retryable_status(status) or attempt + 1 >= max_retries:
                    break
                delay = _retry_after_seconds(response)
                time.sleep(delay if delay is not None else llm.retry_initial_sec * (2**attempt))
            except requests.RequestException as exc:
                last_error = exc
                if attempt + 1 >= max_retries:
                    break
                status = getattr(getattr(exc, "response", None), "status_code", 0)
                delay = _retry_after_seconds(getattr(exc, "response", None)) if _is_retryable_status(status) else None
                time.sleep(delay if delay is not None else llm.retry_initial_sec * (2**attempt))
            except ValueError as exc:
                # Invalid JSON/schema from a successful response is a provider
                # contract failure, not a safe request to repeat.
                last_error = exc
                break
        raise LLMClientError(f"Chat Completions API call failed: {last_error}")

    @staticmethod
    def _build_chat_content(prompt: str, image_path: str | None) -> Any:
        """chat/completions 的 content：有可读图像时用多模态 image_url，否则纯文本。"""
        if image_path:
            path = Path(image_path)
            if path.exists() and path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                return [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _file_data_url(path)}},
                ]
            return f"{prompt}\n\nAssociated image or volume path: {image_path}"
        return prompt

    @staticmethod
    def _extract_chat_text(response: dict[str, Any]) -> str:
        if response.get("error"):
            raise LLMClientError(str(response["error"].get("message") or response["error"]))
        choices = response.get("choices") or []
        for choice in choices:
            message = choice.get("message") or {}
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content
            if isinstance(content, list):  # 兼容分块 content
                parts = [c.get("text", "") for c in content if isinstance(c, dict)]
                joined = "".join(parts).strip()
                if joined:
                    return joined
        raise LLMClientError("Chat Completions response contained no content")

    def _call_local_vlm_cli(self, prompt: str, image_path: str | None = None, **kwargs: Any) -> str:
        llm = self.config.llm
        script = resolve_existing_path(llm.local_cli_script)
        if not script.exists():
            raise LLMClientError(f"Local VLM CLI script not found: {script}")
        with tempfile.TemporaryDirectory(prefix="medharness2_local_vlm_") as tmpdir:
            tmp = Path(tmpdir)
            input_jsonl = tmp / "input.jsonl"
            output_jsonl = tmp / "generation.jsonl"
            image_paths = self._local_vlm_image_paths(image_path, tmp)
            row = {
                "case_id": kwargs.get("case_id") or "medharness2_llm_call",
                "modality": kwargs.get("modality") or "generic_image",
                "body_part": kwargs.get("body_part") or "unknown",
                "image_paths": image_paths,
                "volume_path": None,
                "reference_report": "",
                "prompt": prompt,
            }
            input_jsonl.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            cmd = [
                llm.local_cli_python_bin,
                str(script),
                "--config",
                str(resolve_existing_path(llm.local_cli_config_path)),
                "--model-key",
                kwargs.get("model") or llm.model,
                "--input-jsonl",
                str(input_jsonl),
                "--output-jsonl",
                str(output_jsonl),
                "--limit",
                "1",
                "--device",
                llm.local_cli_device,
                "--dtype",
                llm.local_cli_dtype,
                "--max-new-tokens",
                str(kwargs.get("max_new_tokens") or llm.local_cli_max_new_tokens),
            ]
            try:
                subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=llm.local_cli_timeout_sec,
                )
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or exc.stdout or "")[-1000:]
                raise LLMClientError(f"Local VLM CLI call failed: {detail}") from exc
            except subprocess.TimeoutExpired as exc:
                raise LLMClientError("Local VLM CLI call timed out") from exc
            return self._read_local_vlm_output(output_jsonl)

    def _call_local_hf_vlm(self, prompt: str, image_path: str | None = None, **kwargs: Any) -> str:
        llm = self.config.llm
        with tempfile.TemporaryDirectory(prefix="medharness2_local_hf_vlm_") as tmpdir:
            image_paths = self._local_hf_image_paths(image_path, Path(tmpdir))
            return self._generate_local_hf_vlm(
                prompt,
                image_paths,
                int(kwargs.get("max_new_tokens") or llm.local_hf_max_new_tokens),
            )

    @staticmethod
    def _build_input(prompt: str, image_path: str | None) -> str | list[dict[str, Any]]:
        if image_path:
            path = Path(image_path)
            if path.exists() and path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                return [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            {"type": "input_image", "image_url": _file_data_url(path)},
                        ],
                    }
                ]
            if path.exists() and path.is_file() and path.suffix.lower() == ".pdf":
                return [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_file", "filename": path.name, "file_data": _file_data_url(path)},
                            {"type": "input_text", "text": prompt},
                        ],
                    }
                ]
            return f"{prompt}\n\nAssociated image or volume path: {image_path}"
        return prompt

    @staticmethod
    def _extract_text(response: dict[str, Any]) -> str:
        output = response.get("output") or []
        chunks: list[str] = []
        for item in output:
            for content in item.get("content") or []:
                if content.get("type") == "output_text" and content.get("text") is not None:
                    chunks.append(str(content["text"]))
        if chunks:
            return "\n".join(chunks)
        if response.get("output_text"):
            return str(response["output_text"])
        return json.dumps(response, ensure_ascii=False)

    def _local_vlm_image_paths(self, image_path: str | None, tmp: Path) -> list[str]:
        if not image_path:
            return []
        path = Path(image_path).expanduser()
        if path.exists() and path.suffix.lower() == ".pdf":
            return self._render_pdf_pages(path, tmp)
        return [str(path.resolve())]

    def _local_hf_image_paths(self, image_path: str | None, tmp: Path) -> list[str]:
        if not image_path:
            return []
        path = Path(image_path).expanduser()
        if path.exists() and path.suffix.lower() == ".pdf":
            return self._render_pdf_pages(path, tmp, max_pages=self.config.llm.local_hf_pdf_max_pages)
        return [str(path.resolve())]

    def _render_pdf_pages(self, pdf: Path, tmp: Path, *, max_pages: int | None = None) -> list[str]:
        try:
            import fitz
        except Exception as exc:
            raise LLMClientError("PyMuPDF is required for local VLM PDF OCR") from exc
        try:
            doc = fitz.open(pdf)
        except Exception as exc:
            raise LLMClientError(f"Could not open PDF for local VLM OCR: {pdf}") from exc
        paths: list[str] = []
        page_limit = max(1, int(max_pages if max_pages is not None else self.config.llm.local_cli_pdf_max_pages))
        for index, page in enumerate(doc[:page_limit]):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            out = tmp / f"pdf_page_{index + 1}.png"
            pixmap.save(out)
            paths.append(str(out))
        return paths

    def _generate_local_hf_vlm(self, prompt: str, image_paths: list[str], max_new_tokens: int) -> str:
        model, processor = self._load_local_hf_vlm()
        images = self._load_images(image_paths)
        if hasattr(processor, "apply_chat_template"):
            content = [{"type": "image"} for _ in images]
            content.append({"type": "text", "text": prompt})
            messages = [{"role": "user", "content": content}]
            text = processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
            inputs = processor(text=[text], images=images or None, return_tensors="pt")
        else:
            inputs = processor(text=prompt, images=images or None, return_tensors="pt")
        target_device = getattr(model, "device", None)
        if target_device is not None:
            inputs = {key: value.to(target_device) if hasattr(value, "to") else value for key, value in inputs.items()}
        import torch

        with torch.no_grad():
            generated_ids = model.generate(**inputs, max_new_tokens=max_new_tokens)
        decoded = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
        return _strip_prompt(decoded, prompt)

    def _load_local_hf_vlm(self) -> tuple[Any, Any]:
        model_path = self.config.llm.local_hf_model_path
        if not model_path:
            raise LLMClientError("local_hf_model_path is required for local_hf_vlm")
        cache_key = (model_path, self.config.llm.local_hf_device, self.config.llm.local_hf_dtype)
        cached = self._local_hf_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoProcessor
        except Exception as exc:
            raise LLMClientError("torch, transformers, and Pillow are required for local_hf_vlm") from exc
        try:
            from transformers import AutoModelForImageTextToText  # type: ignore
        except Exception:
            AutoModelForImageTextToText = None
        try:
            from transformers import AutoModelForVision2Seq  # type: ignore
        except Exception:
            AutoModelForVision2Seq = None

        processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True, local_files_only=True)
        dtype = self.config.llm.local_hf_dtype.lower()
        torch_dtype = torch.bfloat16 if dtype == "bf16" else torch.float16 if dtype == "fp16" else torch.float32
        load_kwargs: dict[str, Any] = {
            "torch_dtype": torch_dtype,
            "trust_remote_code": True,
            "local_files_only": True,
        }
        device = self.config.llm.local_hf_device
        if device.startswith("cuda"):
            load_kwargs["device_map"] = "auto"
        model_cls = AutoModelForImageTextToText or AutoModelForVision2Seq or AutoModelForCausalLM
        model = model_cls.from_pretrained(model_path, **load_kwargs)
        if not device.startswith("cuda"):
            model = model.to(device)
        model.eval()
        self._local_hf_cache[cache_key] = (model, processor)
        return model, processor

    @staticmethod
    def _load_images(image_paths: list[str]) -> list[Any]:
        try:
            from PIL import Image
        except Exception as exc:
            raise LLMClientError("Pillow is required for local_hf_vlm image loading") from exc
        return [Image.open(path).convert("RGB") for path in image_paths]

    @staticmethod
    def _read_local_vlm_output(output_jsonl: Path) -> str:
        if not output_jsonl.exists():
            raise LLMClientError("Local VLM CLI did not write an output JSONL")
        with output_jsonl.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                text = row.get("generated_text") or row.get("generated_report") or row.get("prediction_text") or row.get("Pred") or ""
                return str(text).strip()
        raise LLMClientError("Local VLM CLI output JSONL was empty")


def build_mock_client(response_json: dict[str, Any] | None = None) -> LLMClient:
    config = AppConfig(llm=LLMConfig(provider="mock"))
    client = LLMClient(config=config)
    if response_json is not None:
        original_call = client.call

        def call(prompt: str, image_path: str | None = None, **kwargs: Any) -> str:
            kwargs.pop("response_json", None)
            return original_call(prompt, image_path=image_path, response_json=response_json, **kwargs)

        client.call = call  # type: ignore[method-assign]
    return client


def _retry_after_seconds(response: Any) -> float | None:
    if response is None:
        return None
    try:
        value = response.headers.get("Retry-After")
    except AttributeError:
        return None
    try:
        delay = float(value)
    except (TypeError, ValueError):
        try:
            parsed = parsedate_to_datetime(str(value))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            delay = parsed.timestamp() - time.time()
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0.0, min(delay, 300.0))


def _file_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _structured_provider_error(response: Any) -> str:
    try:
        status_code = int(getattr(response, "status_code", 200))
    except (TypeError, ValueError):
        status_code = 200
    if status_code < 400:
        return ""
    try:
        payload = response.json()
    except Exception:
        return "request rejected without a JSON error body"
    if not isinstance(payload, dict):
        return "request rejected with a non-object JSON error body"
    error = payload.get("error")
    error = error if isinstance(error, dict) else {}
    details = []
    for label, value in (
        ("code", error.get("code") or payload.get("code")),
        ("type", error.get("type") or payload.get("type")),
        ("message", error.get("message") or payload.get("message")),
    ):
        if value not in (None, ""):
            details.append(f"{label}={_safe_provider_error_text(value)}")
    return "; ".join(details) or "request rejected without structured error fields"


def _structured_body_error(payload: Any) -> str:
    """Return a safe provider error summary for an HTTP-200 error envelope."""
    if not isinstance(payload, dict) or not payload.get("error"):
        return ""
    error = payload.get("error")
    if isinstance(error, dict):
        details = []
        for label in ("code", "type", "message"):
            value = error.get(label)
            if value not in (None, ""):
                details.append(f"{label}={_safe_provider_error_text(value)}")
        return "; ".join(details) or "provider returned an error object"
    return _safe_provider_error_text(error)


def _safe_provider_error_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._-]+", "Bearer <redacted>", text)
    text = re.sub(
        r"(?i)\b(?:sk|key|token)[-_][A-Za-z0-9._-]{8,}",
        "<redacted>",
        text,
    )
    return text[:500]


def _strip_prompt(decoded: str, prompt: str) -> str:
    text = decoded.strip()
    if prompt and prompt in text:
        text = text.split(prompt, 1)[-1].strip()
    for prefix in ("assistant\n", "assistant:", "Assistant\n", "Assistant:", "model\n", "model:"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    return text
