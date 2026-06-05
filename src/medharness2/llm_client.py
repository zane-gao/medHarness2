from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import base64
import mimetypes
import tempfile
from pathlib import Path
from typing import Any

from medharness2.config import AppConfig, LLMConfig, load_config


class LLMClientError(RuntimeError):
    """Raised when the configured LLM provider cannot complete a request."""


class LLMClient:
    def __init__(self, config: AppConfig | None = None):
        self.config = config or load_config()
        self._local_hf_cache: dict[tuple[str, str, str], tuple[Any, Any]] = {}

    def call(self, prompt: str, image_path: str | None = None, **kwargs: Any) -> str:
        provider = self.config.llm.provider.lower()
        if provider == "mock":
            return self._mock_response(prompt, image_path=image_path, **kwargs)
        if provider in {"openai", "openai_responses"}:
            return self._call_openai_responses(prompt, image_path=image_path, **kwargs)
        if provider in {"local_vlm_cli", "medharness_cli_vlm"}:
            return self._call_local_vlm_cli(prompt, image_path=image_path, **kwargs)
        if provider in {"local_hf_vlm", "hf_vlm_local"}:
            return self._call_local_hf_vlm(prompt, image_path=image_path, **kwargs)
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

    def _call_local_vlm_cli(self, prompt: str, image_path: str | None = None, **kwargs: Any) -> str:
        llm = self.config.llm
        script = Path(llm.local_cli_script)
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
                llm.local_cli_config_path,
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


def _file_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _strip_prompt(decoded: str, prompt: str) -> str:
    text = decoded.strip()
    if prompt and prompt in text:
        text = text.split(prompt, 1)[-1].strip()
    for prefix in ("assistant\n", "assistant:", "Assistant\n", "Assistant:", "model\n", "model:"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    return text
