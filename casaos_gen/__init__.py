"""CasaOS compose generator package."""
from __future__ import annotations

import logging

from .exceptions import (
    CasaOSGenError,
    ComposeParseError,
    LLMError,
    LLMResponseError,
    LLMUnavailableError,
    ParamsError,
    VersionError,
)
from .models import AppMeta, CasaOSMeta, EnvItem, PortItem, ServiceMeta, VolumeItem
from .utils import as_text, normalize_multilang, parse_llm_json

logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "AppMeta",
    "CasaOSGenError",
    "CasaOSMeta",
    "ComposeParseError",
    "EnvItem",
    "LLMError",
    "LLMResponseError",
    "LLMUnavailableError",
    "ParamsError",
    "PortItem",
    "ServiceMeta",
    "VersionError",
    "VolumeItem",
    "as_text",
    "normalize_multilang",
    "parse_llm_json",
]
