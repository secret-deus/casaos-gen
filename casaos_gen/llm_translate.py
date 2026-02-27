"""LLM-powered translation helpers used for Stage 2 multi-language output.

This module intentionally keeps a small surface area so it can be reused by the
CLI pipeline and the FastAPI Web UI.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional during unit tests
    OpenAI = None

logger = logging.getLogger(__name__)


class LLMTranslationError(RuntimeError):
    """Raised when LLM translation fails or returns invalid data."""


def _parse_json_object(content: str) -> Dict[str, Any]:
    cleaned = (content or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1]

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMTranslationError(f"LLM returned invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise LLMTranslationError("LLM returned JSON that is not an object.")

    return data


def build_translation_prompt(
    items: Mapping[str, str],
    languages: Sequence[str],
    source_language: Optional[str],
) -> str:
    """Build a translation prompt for a batch of independent strings."""

    language_list = json.dumps(list(languages), ensure_ascii=False)
    source_hint = (
        f"The source text locale is '{source_language}'. For every item, the value for that locale MUST match the input SOURCE_TEXT exactly."
        if source_language
        else (
            "Detect the source language automatically for each item. "
            "If an input SOURCE_TEXT is already written in one of the target locales, keep that locale EXACTLY equal to SOURCE_TEXT (no rewriting)."
        )
    )
    items_json = json.dumps(dict(items), ensure_ascii=False, indent=2)

    return f"""
You are a professional translator for software app store listings.

Translate each SOURCE_TEXT into these target locales:
{language_list}

{source_hint}

Rules:
- Return ONLY valid JSON (no Markdown fences, no commentary).
- The JSON MUST be an object mapping each ITEM_ID to an object of locale translations.
- For each ITEM_ID, the value MUST be an object where keys are exactly the locale codes above (no extra keys).
- Values MUST be plain strings.
- Preserve Markdown formatting, links, bullet lists, and line breaks.
- Keep product names, environment variable names, port numbers, and file paths unchanged.
- Do NOT add, remove, or reorder content.

ITEMS (ITEM_ID -> SOURCE_TEXT):
{items_json}
""".strip()


def _ensure_llm_client(
    client: Optional[object],
    api_key: Optional[str],
    base_url: Optional[str],
) -> object:
    if client is not None:
        return client
    if OpenAI is None:
        raise LLMTranslationError("openai package is not available; cannot translate with LLM.")
    client_kwargs: Dict[str, Any] = {}
    if api_key:
        client_kwargs["api_key"] = api_key
    if base_url:
        client_kwargs["base_url"] = base_url
    return OpenAI(**client_kwargs)


def translate_items_with_llm(
    items: Mapping[str, str],
    languages: Sequence[str],
    *,
    model: str,
    temperature: float = 0.2,
    client: Optional[object] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    source_language: Optional[str] = "en_US",
) -> Dict[str, Dict[str, str]]:
    """Translate a batch of strings via an OpenAI-compatible Chat Completions API."""

    normalized_languages = [str(lang) for lang in languages if str(lang).strip()]
    if not normalized_languages:
        raise ValueError("languages must not be empty")

    prompt = build_translation_prompt(items, normalized_languages, source_language)
    safe_temperature = max(0.0, min(float(temperature), 0.3))
    llm_client = _ensure_llm_client(client, api_key=api_key, base_url=base_url)

    try:
        response = llm_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=safe_temperature,
        )
    except Exception as exc:  # pragma: no cover - network/model errors
        raise LLMTranslationError(f"LLM translation failed: {exc}") from exc

    content = response.choices[0].message.content or ""
    data = _parse_json_object(content)

    results: Dict[str, Dict[str, str]] = {}
    for item_id, source_text in items.items():
        raw_entry = data.get(item_id)
        if not isinstance(raw_entry, dict):
            raw_entry = {}

        translations: Dict[str, str] = {}
        for lang in normalized_languages:
            value = raw_entry.get(lang)
            translations[lang] = "" if value is None else str(value)

        if source_language and source_language in translations:
            translations[source_language] = str(source_text)

        fallback_text = translations.get("en_US") or str(source_text)
        for lang in normalized_languages:
            if str(translations.get(lang) or "").strip():
                continue
            translations[lang] = str(fallback_text)

        results[str(item_id)] = translations

    return results


def _normalize_texts(texts: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in texts:
        text = str(raw or "").strip()
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _chunk_texts(
    texts: Sequence[str],
    *,
    max_items: int,
    max_chars: int,
) -> List[List[str]]:
    chunks: List[List[str]] = []
    current: List[str] = []
    current_chars = 0

    for text in texts:
        text_len = len(text)
        would_exceed_items = current and len(current) >= max_items
        would_exceed_chars = current and (current_chars + text_len) > max_chars
        if would_exceed_items or would_exceed_chars:
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(text)
        current_chars += text_len

    if current:
        chunks.append(current)
    return chunks


def translate_texts_with_llm(
    texts: Iterable[str],
    languages: Sequence[str],
    *,
    model: str,
    temperature: float = 0.2,
    client: Optional[object] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    source_language: Optional[str] = "en_US",
    short_text_max_chars: int = 200,
    batch_max_items: int = 12,
    batch_max_chars: int = 2500,
) -> Dict[str, Dict[str, str]]:
    """Translate many strings while reducing the number of LLM calls.

    - Short single-line strings are batched.
    - Longer / multi-line strings are translated one-by-one to avoid oversized responses.
    """

    normalized = _normalize_texts(texts)
    if not normalized:
        return {}

    short_texts: List[str] = []
    long_texts: List[str] = []
    for text in normalized:
        is_multiline = "\n" in text or "\r" in text
        if not is_multiline and len(text) <= short_text_max_chars:
            short_texts.append(text)
        else:
            long_texts.append(text)

    out: Dict[str, Dict[str, str]] = {}
    errors: List[str] = []

    for chunk in _chunk_texts(short_texts, max_items=batch_max_items, max_chars=batch_max_chars):
        items = {str(idx): value for idx, value in enumerate(chunk)}
        try:
            chunk_result = translate_items_with_llm(
                items,
                languages,
                model=model,
                temperature=temperature,
                client=client,
                api_key=api_key,
                base_url=base_url,
                source_language=source_language,
            )
            for item_id, source_text in items.items():
                out[source_text] = chunk_result.get(item_id) or {str(lang): source_text for lang in languages}
        except LLMTranslationError as exc:
            logger.warning("Short-text batch translation failed, skipping batch: %s", exc)
            errors.append(str(exc))

    for text in long_texts:
        items = {"0": text}
        try:
            chunk_result = translate_items_with_llm(
                items,
                languages,
                model=model,
                temperature=temperature,
                client=client,
                api_key=api_key,
                base_url=base_url,
                source_language=source_language,
            )
            out[text] = chunk_result.get("0") or {str(lang): text for lang in languages}
        except LLMTranslationError as exc:
            logger.warning("Long-text translation failed for %.40s..., skipping: %s", text, exc)
            errors.append(str(exc))

    if not out and errors:
        raise LLMTranslationError(f"All translation batches failed: {errors[0]}")

    return out

