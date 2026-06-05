from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import base64
import mimetypes
from pathlib import Path
from typing import Any

from medharness2.config import AppConfig, LLMConfig, load_config


class LLMClientError(RuntimeError):
    """Raised when the configured LLM provider cannot complete a request."""


class LLMClient:
    def __init__(self, config: AppConfig | None = None):
        self.config = config or load_config()

    def call(self, prompt: str, image_path: str | None = None, **kwargs: Any) -> str:
        provider = self.config.llm.provider.lower()
        if provider == "mock":
            return self._mock_response(prompt, image_path=image_path, **kwargs)
        if provider in {"openai", "openai_responses"}:
            return self._call_openai_responses(prompt, image_path=image_path, **kwargs)
        raise LLMClientError(f"Unsupported LLM provider: {self.config.llm.provider}")

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
        api_key = os.environ.get(llm.api_key_env)
        if not api_key:
            raise LLMClientError(f"Missing API key environment variable: {llm.api_key_env}")
        payload: dict[str, Any] = {
            "model": kwargs.get("model") or llm.model,
            "input": self._build_input(prompt, image_path),
            "temperature": kwargs.get("temperature", llm.temperature),
        }
        if kwargs.get("response_format") == "json":
            payload["text"] = {"format": {"type": "json_object"}}
        data = json.dumps(payload).encode("utf-8")
        endpoint = llm.base_url.rstrip("/") + "/responses"
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
        for attempt in range(max(1, llm.max_retries)):
            try:
                with urllib.request.urlopen(request, timeout=llm.timeout_sec) as response:
                    body = json.loads(response.read().decode("utf-8"))
                return self._extract_text(body)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt + 1 >= max(1, llm.max_retries):
                    break
                time.sleep(llm.retry_initial_sec * (2**attempt))
        raise LLMClientError(f"OpenAI Responses API call failed: {last_error}")

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


def _file_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"
