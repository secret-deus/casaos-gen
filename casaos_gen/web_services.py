"""Business logic helpers for the CasaOS Web UI, extracted from webui.py.

This module contains session management, LLM interaction helpers, stage-2 field
update logic, and translation utilities that were previously inline in webui.py.
Route handlers in webui.py delegate to these functions to keep routing thin.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, Request, Response

from .i18n import DEFAULT_LANGUAGES, TRANSLATION_MAP
from .models import CasaOSMeta
from .pipeline import render_compose
from .llm_translate import LLMTranslationError
from .utils import as_text

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None

logger = logging.getLogger(__name__)

LLM_CONFIG_PATH = Path("llm_config.json")

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LLMConfig:
    """Global LLM configuration shared across all sessions."""
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: str = "gpt-4.1-mini"
    temperature: float = 0.2


@dataclass
class SessionState:
    """Per-session state isolated by cookie."""
    compose_data: Optional[dict] = None
    compose_text: str = ""
    meta: Optional[CasaOSMeta] = None
    languages: List[str] = field(default_factory=lambda: list(DEFAULT_LANGUAGES))
    translation_map: Dict[str, Dict[str, str]] = field(
        default_factory=lambda: {key: dict(value) for key, value in TRANSLATION_MAP.items()}
    )
    last_access: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Session management (thread-safe)
# ---------------------------------------------------------------------------

_SESSIONS: Dict[str, SessionState] = {}
_SESSIONS_LOCK = threading.Lock()
_SESSION_COOKIE = "casaos_sid"
_SESSION_TTL = 3600 * 4  # 4 hours

LLM_CFG = LLMConfig()


def get_session(request: Request, response: Response) -> SessionState:
    """Get or create a session for the current request (thread-safe)."""
    now = time.time()
    with _SESSIONS_LOCK:
        expired = [k for k, v in _SESSIONS.items() if now - v.last_access > _SESSION_TTL]
        for sid in expired:
            del _SESSIONS[sid]
        sid = request.cookies.get(_SESSION_COOKIE)
        if sid and sid in _SESSIONS:
            _SESSIONS[sid].last_access = now
            return _SESSIONS[sid]
        sid = uuid.uuid4().hex
        session = SessionState()
        _SESSIONS[sid] = session
    response.set_cookie(
        key=_SESSION_COOKIE, value=sid, httponly=True, samesite="lax", max_age=_SESSION_TTL
    )
    return session


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def safe_llm_config_dict() -> dict:
    """Return LLM config with api_key masked (never expose raw key via API)."""
    return {
        "base_url": LLM_CFG.base_url,
        "api_key": bool(LLM_CFG.api_key),
        "model": LLM_CFG.model,
        "temperature": LLM_CFG.temperature,
    }


def require_llm_client():
    """Build and return an OpenAI client from the global LLM config."""
    if OpenAI is None:
        raise HTTPException(status_code=500, detail="openai package is not installed.")
    client_kwargs = {}
    if LLM_CFG.api_key:
        client_kwargs["api_key"] = LLM_CFG.api_key
    if LLM_CFG.base_url:
        client_kwargs["base_url"] = LLM_CFG.base_url
    try:
        return OpenAI(**client_kwargs)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=400, detail=f"Failed to initialize LLM client: {exc}") from exc


def parse_llm_json_response(content: str) -> Dict[str, Any]:
    """Parse JSON from LLM response, raising HTTPException on failure."""
    from .utils import parse_llm_json
    try:
        return parse_llm_json(content)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"LLM returned invalid JSON: {exc}") from exc


# ---------------------------------------------------------------------------
# LLM config persistence
# ---------------------------------------------------------------------------

def load_llm_config() -> None:
    """Load LLM config from disk."""
    if LLM_CONFIG_PATH.exists():
        try:
            data = json.loads(LLM_CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Failed to parse llm_config.json")
            return
        LLM_CFG.base_url = data.get("base_url")
        LLM_CFG.api_key = data.get("api_key")
        LLM_CFG.model = data.get("model", LLM_CFG.model)
        LLM_CFG.temperature = data.get("temperature", LLM_CFG.temperature)


def save_llm_config(
    base_url: Optional[str],
    api_key: Optional[str],
    model: Optional[str],
    temperature: Optional[float],
) -> None:
    """Save LLM config to disk and update global state."""
    if base_url is not None:
        LLM_CFG.base_url = base_url or None
    if api_key is not None:
        LLM_CFG.api_key = api_key or None
    if model is not None:
        LLM_CFG.model = model or LLM_CFG.model
    if temperature is not None:
        LLM_CFG.temperature = temperature
    LLM_CONFIG_PATH.write_text(
        json.dumps(
            {
                "base_url": LLM_CFG.base_url,
                "api_key": LLM_CFG.api_key,
                "model": LLM_CFG.model,
                "temperature": LLM_CFG.temperature,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def require_meta(session: SessionState) -> CasaOSMeta:
    """Return session meta or raise 400."""
    if session.meta is None or session.compose_data is None:
        raise HTTPException(status_code=400, detail="No compose metadata is loaded yet.")
    return session.meta


def parse_service_target(target: str) -> Tuple[str, str, str]:
    """Parse a target like ``service:NAME:type:key``."""
    parts = target.split(":")
    if len(parts) < 4 or parts[0] != "service":
        raise HTTPException(
            status_code=400,
            detail="Target must look like service:NAME:type:key (e.g. service:web:port:8080)",
        )
    return parts[1], parts[2], ":".join(parts[3:])


# ---------------------------------------------------------------------------
# Translation / stage-2 helpers
# ---------------------------------------------------------------------------

def propagate_translation(text: str, session: SessionState) -> None:
    """Copy *text* as the value for every non-English locale in the session translation map."""
    if not text:
        return
    entry = session.translation_map.setdefault(text, {})
    for lang in session.languages:
        if lang == "en_US":
            continue
        entry[lang] = text


def ensure_stage2_structure(session: SessionState, require_meta: bool = False) -> None:
    """Lazily render stage-2 x-casaos blocks into ``session.compose_data``."""
    if session.compose_data is None:
        raise HTTPException(status_code=400, detail="No compose file loaded.")
    if session.compose_data.get("x-casaos"):
        return
    if session.meta is None:
        if require_meta:
            raise HTTPException(status_code=400, detail="Stage 1 metadata unavailable. Run Stage 1 first.")
        return
    try:
        session.compose_data = render_compose(
            session.compose_data,
            session.meta,
            languages=session.languages,
            translation_map_override=session.translation_map,
            auto_translate=True,
            llm_model=LLM_CFG.model,
            llm_temperature=LLM_CFG.temperature,
            llm_api_key=LLM_CFG.api_key,
            llm_base_url=LLM_CFG.base_url,
        )
    except Exception as exc:
        logger.warning(
            "Stage 2 auto-translate failed; falling back to translation table/copy behavior: %s",
            exc,
        )
        session.compose_data = render_compose(
            session.compose_data,
            session.meta,
            languages=session.languages,
            translation_map_override=session.translation_map,
            auto_translate=False,
        )


def build_translation_prompt(text: str, languages: List[str], source_language: Optional[str]) -> str:
    """Build the prompt for translating *text* into *languages*."""
    language_list = json.dumps(languages, ensure_ascii=False)
    source_hint = (
        f"The source text locale is '{source_language}'. The value for that locale MUST match SOURCE_TEXT exactly."
        if source_language
        else "Detect the source language automatically. If SOURCE_TEXT is already written in one of the target locales, keep that locale EXACTLY equal to SOURCE_TEXT (no rewriting)."
    )
    return f"""
You are a professional translator for software app store listings.

Translate the SOURCE_TEXT into these target locales:
{language_list}

{source_hint}

Rules:
- Return ONLY valid JSON (no Markdown fences, no commentary).
- The JSON MUST be an object where keys are exactly the locale codes above (no extra keys).
- Values MUST be plain strings.
- Preserve Markdown formatting, links, bullet lists, and line breaks.
- Keep product names, environment variable names, port numbers, and file paths unchanged.
- Do NOT add, remove, or reorder content.

SOURCE_TEXT:
{text}
""".strip()


def translate_multilang_with_llm(text: str, source_language: Optional[str], session: SessionState) -> Dict[str, str]:
    """Call LLM to translate *text* into all session languages."""
    client = require_llm_client()
    prompt = build_translation_prompt(text, session.languages, source_language)
    temperature = max(0.0, min(float(LLM_CFG.temperature), 0.3))
    try:
        response = client.chat.completions.create(
            model=LLM_CFG.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=400, detail=f"LLM translation failed: {exc}") from exc

    content = response.choices[0].message.content or ""
    data = parse_llm_json_response(content)

    translations: Dict[str, str] = {}
    for lang in session.languages:
        value = data.get(lang)
        translations[lang] = "" if value is None else str(value)

    if source_language and source_language in translations:
        translations[source_language] = text

    english_text = translations.get("en_US") or ""
    for lang in session.languages:
        if translations[lang].strip():
            continue
        translations[lang] = english_text.strip() or text

    return translations


def update_translation_map_from_multilang(translations: Dict[str, str], session: SessionState) -> None:
    """Merge *translations* into the session translation map keyed by en_US text."""
    english_text = str(translations.get("en_US") or "").strip()
    if not english_text:
        return
    entry = session.translation_map.setdefault(english_text, {})
    for lang in session.languages:
        if lang == "en_US":
            continue
        candidate = str(translations.get(lang) or "").strip()
        if candidate:
            entry[lang] = candidate


def sync_meta_from_multilang_target(target: str, translations: Dict[str, str], session: SessionState) -> None:
    """Keep Stage-1 meta in sync after a multilang stage-2 update."""
    meta = session.meta
    if meta is None:
        return
    english_text = str(translations.get("en_US") or "").strip()
    if not english_text:
        return
    if target in {"app.title", "app.tagline", "app.description"}:
        setattr(meta.app, target.split(".", 1)[1], english_text)
        return
    parts = target.split(":")
    if len(parts) >= 4 and parts[0] == "service" and parts[2] in {"env", "port", "volume"}:
        service_name, field_type, identifier = parse_service_target(target)
        svc = meta.services.get(service_name)
        if not svc:
            return
        items = {"env": svc.envs, "port": svc.ports, "volume": svc.volumes}.get(field_type)
        if items is None:
            return
        target_item = next((item for item in items if item.container == identifier), None)
        if target_item is None:
            return
        target_item.description = english_text


# ---------------------------------------------------------------------------
# Compose seeding (x-casaos -> meta)
# ---------------------------------------------------------------------------

def seed_meta_from_existing_compose(meta: CasaOSMeta, compose_data: Dict[str, Any]) -> None:
    """Hydrate Stage-1 meta from existing x-casaos blocks in compose."""
    app_block = compose_data.get("x-casaos")
    if not isinstance(app_block, dict):
        return

    for fld in ("title", "tagline", "description"):
        text = as_text(app_block.get(fld)).strip()
        if text:
            setattr(meta.app, fld, text)

    for fld in ("category", "author", "developer", "main", "port_map", "scheme", "index"):
        value = app_block.get(fld)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            setattr(meta.app, fld, text)

    services = compose_data.get("services") or {}
    if not isinstance(services, dict):
        return

    for service_name, service in services.items():
        if not isinstance(service, dict):
            continue
        service_meta = meta.services.get(service_name)
        if not service_meta:
            continue
        svc_block = service.get("x-casaos") or {}
        if not isinstance(svc_block, dict):
            continue
        for list_key, attr_name in (("envs", "envs"), ("ports", "ports"), ("volumes", "volumes")):
            items = svc_block.get(list_key) or []
            if not isinstance(items, list):
                continue
            meta_items = getattr(service_meta, attr_name, [])
            for entry in items:
                if not isinstance(entry, dict):
                    continue
                container = str(entry.get("container") or "").strip()
                description = as_text(entry.get("description")).strip()
                if not container or not description:
                    continue
                target_item = next((item for item in meta_items if item.container == container), None)
                if target_item:
                    target_item.description = description


# ---------------------------------------------------------------------------
# Assistant / chat context
# ---------------------------------------------------------------------------

def collect_target_context(target: Optional[str], session: SessionState) -> str:
    """Build context string for the AI assistant about the target field."""
    if not target:
        return (
            "Target: general editing mode. Help the user craft CasaOS metadata for compose files and "
            "provide concise rewrites that are safe to copy into every locale."
        )

    lines = [f"Target field: {target}"]

    if target.startswith("app."):
        field_path = target.split(".", 1)[1]
        if session.meta:
            attr_name = field_path.split(".", 1)[0]
            if hasattr(session.meta.app, attr_name):
                lines.append(f"Stage 1 value: {getattr(session.meta.app, attr_name)}")
        stage2_value = _resolve_app_stage2_value(field_path, session)
        if stage2_value is not None:
            lines.append(f"Stage 2 value: {stage2_value}")
        return "\n".join(lines)

    parts = target.split(":")
    if len(parts) >= 4 and parts[0] == "service" and parts[2] in {"env", "port", "volume"}:
        service_name, field_type = parts[1], parts[2]
        identifier = ":".join(parts[3:])
        if session.meta:
            service_meta = session.meta.services.get(service_name)
            if service_meta:
                collection = getattr(service_meta, f"{field_type}s", [])
                entry = next((item for item in collection if item.container == identifier), None)
                if entry:
                    lines.append(f"Stage 1 value: {entry.description}")
        stage2_value = _resolve_service_stage2_multilang(service_name, field_type, identifier, session)
        if stage2_value is not None:
            lines.append(f"Stage 2 value: {stage2_value}")
        return "\n".join(lines)

    if len(parts) >= 3 and parts[0] == "service":
        service_name = parts[1]
        field_path = ":".join(parts[2:])
        stage2_value = _resolve_service_stage2_single(service_name, field_path, session)
        if stage2_value is not None:
            lines.append(f"Stage 2 value: {stage2_value}")
        return "\n".join(lines)

    return "\n".join(lines)


def build_assistant_prompt(context: str) -> str:
    """Build the system prompt for the assistant chat endpoint."""
    base = (
        "You are an AI writing partner embedded in a CasaOS compose visual editor. "
        "Users will ask for help rewriting metadata that describes docker-compose applications. "
        "Respond with actionable prose that can be copied verbatim into the metadata. "
        "Keep answers under 120 words when possible. "
        "When asked to rewrite a multi-language field, craft a single neutral English draft that can be propagated across all locales, "
        "avoiding language-specific mentions."
    )
    return f"{base}\n\nContext:\n{context}"


# ---------------------------------------------------------------------------
# Stage-2 value resolution (internal)
# ---------------------------------------------------------------------------

def _resolve_app_stage2_value(field_path: str, session: SessionState):
    compose = session.compose_data or {}
    scope = compose.get("x-casaos") or {}
    for key in field_path.split("."):
        if not isinstance(scope, dict):
            return None
        scope = scope.get(key)
        if scope is None:
            return None
    return scope


def _resolve_service_stage2_multilang(service_name: str, field_type: str, identifier: str, session: SessionState):
    compose = session.compose_data or {}
    services = compose.get("services") or {}
    service = services.get(service_name) or {}
    x_block = service.get("x-casaos") or {}
    plural_map = {"env": "envs", "port": "ports", "volume": "volumes"}
    collection_name = plural_map.get(field_type)
    if not collection_name:
        return None
    items = x_block.get(collection_name) or []
    for item in items:
        if item.get("container") == identifier:
            return item.get("description")
    return None


def _resolve_service_stage2_single(service_name: str, field_path: str, session: SessionState):
    compose = session.compose_data or {}
    services = compose.get("services") or {}
    service = services.get(service_name) or {}
    scope = service.get("x-casaos") or {}
    for key in field_path.split("."):
        if not isinstance(scope, dict):
            return None
        scope = scope.get(key)
        if scope is None:
            return None
    return scope
