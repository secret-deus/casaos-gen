"""Helpers for LM Studio native REST API integration."""
from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Iterable, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def is_lmstudio_base_url(base_url: Optional[str]) -> bool:
    raw = str(base_url or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    return host in {"127.0.0.1", "localhost"}


def _lmstudio_api_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    scheme = parsed.scheme or "http"
    netloc = parsed.netloc or parsed.path
    root = f"{scheme}://{netloc}".rstrip("/")
    return f"{root}/api/v1/chat"


def _flatten_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def _messages_to_input(messages: Iterable[dict[str, Any]]) -> str:
    normalized = list(messages)
    if len(normalized) == 1 and str(normalized[0].get("role") or "user") == "user":
        return _flatten_message_content(normalized[0].get("content"))

    parts: list[str] = []
    for message in normalized:
        role = str(message.get("role") or "user").upper()
        content = _flatten_message_content(message.get("content"))
        if not content.strip():
            continue
        parts.append(f"{role}:\n{content}")
    return "\n\n".join(parts)


@dataclass
class _LMStudioNativeCompletions:
    api_url: str
    api_key: Optional[str]
    timeout: float

    def create(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: Optional[int] = None,
        **_: Any,
    ) -> SimpleNamespace:
        payload = {
            "model": model,
            "input": _messages_to_input(messages),
            "temperature": temperature,
            "reasoning": "off",
            "store": False,
        }
        if max_tokens is not None:
            payload["max_output_tokens"] = max_tokens
        else:
            payload["max_output_tokens"] = 4096

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            body = response.read().decode("utf-8")
        data = json.loads(body)
        output = data.get("output") or []
        content = ""
        for item in output:
            if isinstance(item, dict) and item.get("type") == "message":
                content = str(item.get("content") or "")
                break

        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            raw_response=data,
        )


@dataclass
class LMStudioNativeClient:
    api_url: str
    api_key: Optional[str]
    timeout: float

    def __post_init__(self) -> None:
        completions = _LMStudioNativeCompletions(
            api_url=self.api_url,
            api_key=self.api_key,
            timeout=self.timeout,
        )
        self.chat = SimpleNamespace(completions=completions)


def build_llm_client(
    *,
    openai_cls: Any,
    api_key: Optional[str],
    base_url: Optional[str],
    timeout: float,
    max_retries: int,
) -> object:
    if is_lmstudio_base_url(base_url):
        return LMStudioNativeClient(
            api_url=_lmstudio_api_url(str(base_url)),
            api_key=api_key or "lm-studio",
            timeout=timeout,
        )

    client_kwargs: dict[str, Any] = {"timeout": timeout, "max_retries": max_retries}
    if api_key:
        client_kwargs["api_key"] = api_key
    if base_url:
        client_kwargs["base_url"] = base_url
    return openai_cls(**client_kwargs)
