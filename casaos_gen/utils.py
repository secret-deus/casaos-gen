"""Shared utility functions used across the CasaOS generator modules.

Consolidates duplicated helpers (JSON parsing, text extraction, multilang
normalization) so every module references a single implementation.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON response parsing (was duplicated in llm_stage1 and llm_translate)
# ---------------------------------------------------------------------------

def parse_llm_json(content: str) -> dict:
    """Parse a JSON object from an LLM response, stripping markdown fences."""
    cleaned = (content or "").strip()

    # Strip markdown code fences
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    # Extract first JSON object if response contains leading text
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1]

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse LLM JSON: %s", exc)
        raise

    if not isinstance(data, dict):
        from .exceptions import LLMResponseError
        raise LLMResponseError("LLM returned JSON that is not an object.")

    return data


# ---------------------------------------------------------------------------
# Text extraction helpers (was duplicated in pipeline and webui)
# ---------------------------------------------------------------------------

def as_text(value: Any) -> str:
    """Extract a plain-text string from a value that may be a multilang dict."""
    if isinstance(value, dict):
        # Prefer en_US
        if "en_US" in value:
            en_value = value.get("en_US")
            if en_value is not None:
                en_text = str(en_value)
                if en_text.strip():
                    return en_text
        # Fallback: first non-empty value
        for candidate in value.values():
            if candidate is not None:
                text = str(candidate)
                if text.strip():
                    return text
        return ""
    if value is None:
        return ""
    return str(value)


def as_list(value: Any) -> List[str]:
    """Coerce a value into a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, str):
        return [value]
    return []


def clean_list(values: List[str]) -> List[str]:
    """Strip whitespace and remove empty entries."""
    return [item.strip() for item in values if str(item).strip()]


# ---------------------------------------------------------------------------
# Multilang normalization (was duplicated in parser and yaml_out)
# ---------------------------------------------------------------------------

def normalize_multilang(value: Any, languages: List[str]) -> Dict[str, str]:
    """Normalize a value into a {locale: text} dict covering all *languages*."""
    if isinstance(value, dict):
        return {lang: str(value.get(lang, "") or "") for lang in languages}
    if value is None:
        return {lang: "" for lang in languages}
    text = str(value)
    return {lang: text for lang in languages}


def normalize_tips(value: Any, languages: List[str]) -> Optional[Dict[str, Dict[str, str]]]:
    """Normalize a tips mapping so every section is a full multilang dict."""
    if value is None:
        return None
    if not isinstance(value, dict):
        return value
    normalized: Dict[str, Any] = {}
    for section, payload in value.items():
        normalized[section] = normalize_multilang(payload, languages)
    return normalized


# ---------------------------------------------------------------------------
# Version file name validation (security: prevents path traversal)
# ---------------------------------------------------------------------------

_VERSION_FILE_PATTERN = re.compile(r"^meta\.\d{8}_\d{6}\.json$")


def validate_version_filename(filename: str) -> str:
    """Validate that *filename* matches the expected version file pattern.

    Raises ``ValueError`` for unexpected names (prevents path-traversal attacks).
    """
    if not _VERSION_FILE_PATTERN.match(filename):
        from .exceptions import VersionError
        raise VersionError(
            f"Invalid version filename: {filename!r}. "
            "Expected format: meta.YYYYMMDD_HHMMSS.json"
        )
    return filename
