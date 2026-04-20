"""LLM-powered translation helpers used for Stage 2 multi-language output.

This module intentionally keeps a small surface area so it can be reused by the
CLI pipeline and the FastAPI Web UI.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .constants import (
    LLM_TRANSLATION_MAX_ATTEMPTS,
    LLM_TRANSLATION_RETRY_BASE_DELAY_SECONDS,
    OPENAI_MAX_RETRIES,
    OPENAI_REQUEST_TIMEOUT_SECONDS,
)
from .lmstudio_client import build_llm_client

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional during unit tests
    OpenAI = None

logger = logging.getLogger(__name__)


class LLMTranslationError(RuntimeError):
    """Raised when LLM translation fails or returns invalid data."""


def _parse_json_object(content: str) -> Dict[str, Any]:
    """Parse JSON object from LLM response. Delegates to shared utility."""
    from .utils import parse_llm_json

    try:
        return parse_llm_json(content)
    except (json.JSONDecodeError, ValueError) as exc:
        raise LLMTranslationError(f"LLM returned invalid JSON: {exc}") from exc


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


def build_single_locale_translation_prompt(
    text: str,
    target_language: str,
    source_language: Optional[str],
) -> str:
    source_hint = f"Source locale: {source_language}." if source_language else "Detect source locale."
    return (
        f'Translate SOURCE_TEXT to locale "{target_language}". '
        f'{source_hint} '
        f'Return ONLY JSON: {{"{target_language}":"..."}}. '
        "Preserve Markdown, links, product names, environment variable names, file paths, and port numbers. "
        "No commentary.\n\n"
        f"SOURCE_TEXT:\n{text}"
    )


def _ensure_llm_client(
    client: Optional[object],
    api_key: Optional[str],
    base_url: Optional[str],
) -> object:
    if client is not None:
        return client
    if OpenAI is None:
        raise LLMTranslationError("openai package is not available; cannot translate with LLM.")
    return build_llm_client(
        openai_cls=OpenAI,
        api_key=api_key,
        base_url=base_url,
        timeout=OPENAI_REQUEST_TIMEOUT_SECONDS,
        max_retries=OPENAI_MAX_RETRIES,
    )


def _normalize_languages(languages: Sequence[str]) -> List[str]:
    normalized: List[str] = []
    seen: set[str] = set()
    for raw in languages:
        lang = str(raw or "").strip()
        if not lang or lang in seen:
            continue
        seen.add(lang)
        normalized.append(lang)
    return normalized


def _request_single_locale_translation(
    llm_client: object,
    text: str,
    target_language: str,
    *,
    model: str,
    temperature: float,
    source_language: Optional[str],
    max_attempts: int,
    retry_base_delay_seconds: float,
) -> str:
    prompt = build_single_locale_translation_prompt(text, target_language, source_language)
    safe_temperature = max(0.0, min(float(temperature), 0.3))
    max_tokens = 384 if ("\n" in text or "\r" in text or len(text) > 220) else 96
    attempts = max(1, int(max_attempts))
    base_delay = max(0.0, float(retry_base_delay_seconds))

    for attempt in range(1, attempts + 1):
        try:
            logger.info(
                "Calling LLM model %s for single-locale translation (%s, attempt %d/%d)",
                model,
                target_language,
                attempt,
                attempts,
            )
            try:
                response = llm_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=safe_temperature,
                    max_tokens=max_tokens,
                )
            except TypeError as exc:
                if "max_tokens" not in str(exc):
                    raise
                response = llm_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=safe_temperature,
                )
            content = response.choices[0].message.content or ""
            data = _parse_json_object(content)
            value = data.get(target_language)
            if value is None:
                return ""
            return str(value)
        except Exception as exc:  # pragma: no cover - network/model errors
            if isinstance(exc, LLMTranslationError):
                error = exc
            else:
                error = LLMTranslationError(f"LLM translation failed: {exc}")
            if attempt >= attempts:
                raise error

            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "Single-locale translation attempt %d/%d failed for %s; retrying in %.1fs: %s",
                attempt,
                attempts,
                target_language,
                delay,
                error,
            )
            if delay > 0:
                time.sleep(delay)

    raise LLMTranslationError("Single-locale translation failed without a concrete error.")


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
    max_attempts: int = LLM_TRANSLATION_MAX_ATTEMPTS,
    retry_base_delay_seconds: float = LLM_TRANSLATION_RETRY_BASE_DELAY_SECONDS,
) -> Dict[str, Dict[str, str]]:
    """Translate strings via repeated single-field, single-locale requests."""

    normalized_languages = _normalize_languages(languages)
    if not normalized_languages:
        raise ValueError("languages must not be empty")

    llm_client = _ensure_llm_client(client, api_key=api_key, base_url=base_url)

    results: Dict[str, Dict[str, str]] = {}
    for item_id, source_text in items.items():
        translations = {lang: "" for lang in normalized_languages}
        if source_language and source_language in normalized_languages:
            translations[source_language] = str(source_text)
        fallback_text = str(source_text)
        english_fallback = str(source_text)
        for lang in normalized_languages:
            if source_language and lang == source_language:
                continue
            translated = _request_single_locale_translation(
                llm_client,
                str(source_text),
                lang,
                model=model,
                temperature=temperature,
                source_language=source_language,
                max_attempts=max_attempts,
                retry_base_delay_seconds=retry_base_delay_seconds,
            )
            translations[lang] = translated.strip() or fallback_text
            if lang == "en_US" and translations[lang].strip():
                english_fallback = translations[lang]

        fallback_text = translations.get("en_US") or str(source_text)
        for lang in normalized_languages:
            if str(translations.get(lang) or "").strip():
                continue
            translations[lang] = str(english_fallback or fallback_text)
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
    short_text_max_chars: int = 160,
    batch_max_items: int = 4,
    batch_max_chars: int = 1200,
    max_attempts: int = LLM_TRANSLATION_MAX_ATTEMPTS,
    retry_base_delay_seconds: float = LLM_TRANSLATION_RETRY_BASE_DELAY_SECONDS,
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
                max_attempts=max_attempts,
                retry_base_delay_seconds=retry_base_delay_seconds,
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
                max_attempts=max_attempts,
                retry_base_delay_seconds=retry_base_delay_seconds,
            )
            out[text] = chunk_result.get("0") or {str(lang): text for lang in languages}
        except LLMTranslationError as exc:
            logger.warning("Long-text translation failed for %.40s..., skipping: %s", text, exc)
            errors.append(str(exc))

    if not out and errors:
        raise LLMTranslationError(f"All translation batches failed: {errors[0]}")

    return out
