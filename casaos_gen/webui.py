"""FastAPI-based Web UI for CasaOS compose generation and editing.

Route definitions only. Business logic lives in web_services.py.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import List, Optional

import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .compose_normalize import normalize_compose_for_appstore
from .i18n import wrap_multilang
from .llm_translate import LLMTranslationError
from .models import CasaOSMeta
from .pipeline import (
    apply_params_to_meta,
    build_meta,
    build_template_compose_from_data,
    fill_meta_with_llm,
    parse_compose_text,
    parse_params_text,
    render_compose,
)
from .web_services import (
    LLM_CFG,
    SessionState,
    _SESSIONS,
    _SESSIONS_LOCK,
    build_assistant_prompt,
    collect_target_context,
    ensure_stage2_structure,
    get_session,
    load_llm_config,
    parse_service_target,
    propagate_translation,
    require_llm_client,
    require_meta,
    safe_llm_config_dict,
    save_llm_config,
    seed_meta_from_existing_compose,
    sync_meta_from_multilang_target,
    translate_multilang_with_llm,
    update_translation_map_from_multilang,
)
from .yaml_out import dump_yaml

# Re-export for test compatibility
LLMConfig = type(LLM_CFG)

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent
LEGACY_FRONTEND_DIR = BASE_DIR / "frontend"
MODERN_FRONTEND_DIST_DIR = BASE_DIR / "web" / "dist"
LEGACY_INDEX_HTML = LEGACY_FRONTEND_DIR / "index.html"
MODERN_INDEX_HTML = MODERN_FRONTEND_DIST_DIR / "index.html"
LOG_DIR = BASE_DIR / ".casaos-gen" / "logs"
WEBUI_LOG_PATH = LOG_DIR / "webui.log"


def _resolve_frontend_index() -> Path:
    mode = os.getenv("CASAOS_WEBUI_FRONTEND", "auto").strip().lower()
    if mode == "legacy":
        return LEGACY_INDEX_HTML
    if mode == "modern":
        return MODERN_INDEX_HTML if MODERN_INDEX_HTML.exists() else LEGACY_INDEX_HTML
    return MODERN_INDEX_HTML if MODERN_INDEX_HTML.exists() else LEGACY_INDEX_HTML


INDEX_HTML = _resolve_frontend_index()

app = FastAPI(title="CasaOS Compose Generator UI")

if LEGACY_FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(LEGACY_FRONTEND_DIR)), name="static")

if (MODERN_FRONTEND_DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(MODERN_FRONTEND_DIST_DIR / "assets")), name="assets")


def configure_web_logging() -> None:
    """Ensure webui/backend logs are visible in terminal and persisted to disk."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    has_console = any(
        isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler)
        for handler in root_logger.handlers
    )
    if not has_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    target_log = str(WEBUI_LOG_PATH.resolve())
    has_file = any(
        isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", "") == target_log
        for handler in root_logger.handlers
    )
    if not has_file:
        file_handler = logging.FileHandler(WEBUI_LOG_PATH, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    logging.getLogger("casaos_gen").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class FieldUpdate(BaseModel):
    target: str
    value: str
    propagate_all_languages: bool = False
    sync_stage2: bool = True


class ComposeText(BaseModel):
    text: str


class Stage2MultiUpdate(BaseModel):
    target: str
    value: str
    language: Optional[str] = None
    overwrite_all_languages: bool = True


class Stage2SingleUpdate(BaseModel):
    target: str
    value: str


class AssistantMessage(BaseModel):
    role: str
    content: str


class AssistantChatRequest(BaseModel):
    messages: List[AssistantMessage]
    target: Optional[str] = None


# ---------------------------------------------------------------------------
# Internal helpers (thin wrappers kept in routes file for readability)
# ---------------------------------------------------------------------------

def _load_index_html() -> str:
    if INDEX_HTML.exists():
        return INDEX_HTML.read_text(encoding="utf-8")
    logger.warning("Frontend index.html missing at %s", INDEX_HTML)
    return """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>CasaOS Compose UI</title>
  </head>
  <body>
    <p>Frontend assets are missing. Build the UI under the web/ directory or use the legacy frontend/ assets.</p>
  </body>
</html>
""".strip()


def _log_deprecated(endpoint: str, replacement: str) -> None:
    logger.warning("%s is deprecated; use %s instead.", endpoint, replacement)


def _update_meta_field(meta: CasaOSMeta, payload: FieldUpdate) -> None:
    if payload.target.startswith("app."):
        field = payload.target.split(".", 1)[1]
        if not hasattr(meta.app, field):
            raise HTTPException(status_code=400, detail=f"Unknown app field: {field}")
        setattr(meta.app, field, payload.value)
        return

    service_name, field_type, identifier = parse_service_target(payload.target)
    service_meta = meta.services.get(service_name)
    if not service_meta:
        raise HTTPException(status_code=404, detail=f"Service {service_name} not found in metadata.")

    collection_map = {
        "env": service_meta.envs,
        "port": service_meta.ports,
        "volume": service_meta.volumes,
    }
    items = collection_map.get(field_type)
    if items is None:
        raise HTTPException(status_code=400, detail=f"Unknown field type: {field_type}")

    target_item = next((item for item in items if item.container == identifier), None)
    if target_item is None:
        raise HTTPException(
            status_code=404, detail=f"{field_type} entry {identifier} not found for service {service_name}."
        )
    target_item.description = payload.value


def _update_stage2_multi_field(payload: Stage2MultiUpdate, session: SessionState) -> List[str]:
    ensure_stage2_structure(session, require_meta=True)
    compose = session.compose_data or {}
    overwrite_all = bool(payload.overwrite_all_languages)
    language = (payload.language or "").strip()
    warnings: List[str] = []
    if not overwrite_all:
        if not language:
            raise HTTPException(
                status_code=400,
                detail="language is required when overwrite_all_languages is false.",
            )
        if language not in session.languages:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown language '{language}'. Available: {', '.join(session.languages)}",
            )

    source_language = language or None
    if source_language and source_language.lower() in {"auto", "detect"}:
        source_language = None
    if source_language and source_language not in session.languages:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown language '{source_language}'. Available: {', '.join(session.languages)}",
        )

    translations = None
    if overwrite_all:
        try:
            translations = translate_multilang_with_llm(payload.value, source_language, session)
        except HTTPException as exc:  # pragma: no cover
            logger.warning(
                "LLM translation failed during multi-language update; falling back to copy behavior: %s",
                exc.detail,
            )
            translations = {lang: payload.value for lang in session.languages}
            warnings.append("LLM unavailable; copied input to all locales (no translation performed).")
        sync_meta_from_multilang_target(payload.target, translations, session)
        if payload.target in {"app.title", "app.tagline", "app.description", "app.releaseNotes"} or payload.target.startswith("service:"):
            update_translation_map_from_multilang(translations, session)

    if payload.target.startswith("app."):
        field_path = payload.target.split(".", 1)[1]
        block = compose.setdefault("x-casaos", {})
        scope = block
        parts = field_path.split(".")
        for key in parts[:-1]:
            scope = scope.setdefault(key, {})
        multilang = scope.setdefault(parts[-1], {})
        if not isinstance(multilang, dict):
            multilang = {}
            scope[parts[-1]] = multilang
        if overwrite_all:
            for lang in session.languages:
                multilang[lang] = translations.get(lang, payload.value) if translations else payload.value
        else:
            multilang[language] = payload.value
        return warnings

    service_name, field_type, identifier = parse_service_target(payload.target)
    services = compose.get("services") or {}
    service = services.get(service_name)
    if not service:
        raise HTTPException(status_code=404, detail=f"Service {service_name} not present in compose.")

    plural_map = {"env": "envs", "port": "ports", "volume": "volumes"}
    list_name = plural_map.get(field_type)
    if list_name is None:
        raise HTTPException(status_code=400, detail=f"Unknown field type: {field_type}")

    x_block = service.setdefault("x-casaos", {})
    items = x_block.setdefault(list_name, [])
    target_item = None
    for entry in items:
        if entry.get("container") == identifier:
            target_item = entry
            break
    if target_item is None:
        target_item = {"container": identifier, "description": {}}
        items.append(target_item)
    desc = target_item.setdefault("description", {})
    if not isinstance(desc, dict):
        desc = {}
        target_item["description"] = desc
    if overwrite_all:
        for lang in session.languages:
            desc[lang] = translations.get(lang, payload.value) if translations else payload.value
    else:
        desc[language] = payload.value
    return warnings


def _update_stage2_single_field(payload: Stage2SingleUpdate, session: SessionState) -> None:
    ensure_stage2_structure(session, require_meta=True)
    compose = session.compose_data or {}

    if payload.target.startswith("app."):
        field_path = payload.target.split(".", 1)[1]
        block = compose.setdefault("x-casaos", {})
        scope = block
        parts = field_path.split(".")
        for key in parts[:-1]:
            scope = scope.setdefault(key, {})
        scope[parts[-1]] = payload.value
        return

    parts = payload.target.split(":")
    if len(parts) < 3 or parts[0] != "service":
        raise HTTPException(
            status_code=400,
            detail="Target must look like app.xxx or service:NAME:field for single-language editing.",
        )
    service_name = parts[1]
    field_path = ":".join(parts[2:])
    services = compose.get("services") or {}
    service = services.get(service_name)
    if not service:
        raise HTTPException(status_code=404, detail=f"Service {service_name} not present in compose.")
    block = service.setdefault("x-casaos", {})
    scope = block
    fragments = field_path.split(".")
    for key in fragments[:-1]:
        scope = scope.setdefault(key, {})
    scope[fragments[-1]] = payload.value


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(content=_load_index_html())


@app.get("/api/state")
async def get_state(session: SessionState = Depends(get_session)) -> dict:
    return {
        "languages": session.languages,
        "has_compose": session.compose_data is not None,
        "has_meta": session.meta is not None,
        "has_stage2": bool(session.compose_data and session.compose_data.get("x-casaos")),
        "meta": session.meta.model_dump() if session.meta else None,
        "llm": safe_llm_config_dict(),
        "compose_text": session.compose_text or "",
    }


@app.post("/api/reset")
async def reset_state(session: SessionState = Depends(get_session)) -> dict:
    session.compose_data = None
    session.compose_text = None
    session.meta = None
    session.translation_map = {}
    return {"status": "ok"}


@app.post("/api/llm")
async def set_llm_config_endpoint(
    stage: str = Form("stage1"),
    base_url: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
    temperature: Optional[float] = Form(None),
) -> dict:
    save_llm_config(base_url, api_key, model, temperature, stage=stage)
    return {"status": "ok", "llm": safe_llm_config_dict()}


@app.post("/api/compose")
async def load_compose(file: UploadFile = File(...), session: SessionState = Depends(get_session)) -> dict:
    try:
        text = (await file.read()).decode("utf-8")
        compose_data = parse_compose_text(text)
        meta = build_meta(compose_data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse compose file: {exc}") from exc
    seed_meta_from_existing_compose(meta, compose_data)
    session.compose_data = compose_data
    session.compose_text = text
    session.meta = meta
    return {"status": "ok", "message": "Compose loaded.", "meta": meta.model_dump()}


@app.post("/api/compose-text")
async def load_compose_text(payload: ComposeText, session: SessionState = Depends(get_session)) -> dict:
    raw_text = payload.text or ""
    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="Compose text is empty.")
    try:
        compose_data = parse_compose_text(raw_text)
        meta = build_meta(compose_data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse compose text: {exc}") from exc
    seed_meta_from_existing_compose(meta, compose_data)
    session.compose_data = compose_data
    session.compose_text = raw_text
    session.meta = meta
    return {"status": "ok", "message": "Compose loaded.", "meta": meta.model_dump()}


@app.post("/api/meta/fill")
async def fill_metadata(
    mode: Optional[str] = Form(None),
    use_llm: Optional[bool] = Form(None),
    use_params: Optional[bool] = Form(None),
    params_json: Optional[str] = Form(None),
    params_file: Optional[UploadFile] = File(None),
    model: Optional[str] = Form(None),
    temperature: Optional[float] = Form(None),
    llm_base_url: Optional[str] = Form(None),
    llm_api_key: Optional[str] = Form(None),
    llm_prompt: Optional[str] = Form(None),
    session: SessionState = Depends(get_session),
) -> dict:
    if session.compose_data is None:
        raise HTTPException(status_code=400, detail="No compose file loaded.")
    warnings: List[str] = []

    mode_value = (mode or "").strip().lower()
    use_llm_value = None if use_llm is None else bool(use_llm)
    use_params_value = None if use_params is None else bool(use_params)
    if use_llm_value is None and use_params_value is None:
        if mode_value == "params":
            use_params_value = True
            use_llm_value = False
        else:
            use_llm_value = True
            use_params_value = False
    else:
        if use_llm_value is None:
            use_llm_value = False
        if use_params_value is None:
            use_params_value = False

    logger.info(
        "Stage 1 fill requested (use_llm=%s, use_params=%s, model=%s, temp=%s, llm_base_url=%s, llm_api_key=%s)",
        use_llm_value,
        use_params_value,
        model or LLM_CFG.stage1.model,
        temperature if temperature is not None else LLM_CFG.stage1.temperature,
        bool((llm_base_url or "").strip()),
        bool((llm_api_key or "").strip() or LLM_CFG.stage1.api_key),
    )

    if not use_llm_value and not use_params_value:
        meta = session.meta or build_meta(session.compose_data)
        session.meta = meta
        return {
            "status": "ok",
            "message": "No fill requested; metadata unchanged.",
            "meta": meta.model_dump(),
        }

    params = None
    if use_params_value:
        if params_file is not None:
            try:
                params_text = (await params_file.read()).decode("utf-8")
                params = parse_params_text(params_text)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Failed to parse params file: {exc}") from exc
        elif params_json:
            try:
                params = json.loads(params_json)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail=f"Failed to parse params JSON: {exc}") from exc
            if not isinstance(params, dict):
                raise HTTPException(status_code=400, detail="Params JSON must be an object.")
            if "app" not in params:
                raise HTTPException(status_code=400, detail="Params JSON must include top-level 'app'.")
        else:
            params = {"app": {}}

    meta = session.meta or build_meta(session.compose_data)
    if use_params_value:
        meta = apply_params_to_meta(meta, params)

    if use_llm_value:
        model_name = model or LLM_CFG.stage1.model
        temp_value = LLM_CFG.stage1.temperature if temperature is None else temperature
        try:
            meta = fill_meta_with_llm(
                meta,
                model=model_name,
                temperature=temp_value,
                api_key=llm_api_key or LLM_CFG.stage1.api_key,
                base_url=llm_base_url or LLM_CFG.stage1.base_url,
                prompt_instructions=llm_prompt,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Stage 1 LLM fill failed; continuing without LLM: %s", exc)
            warnings.append(
                "LLM unavailable; skipped LLM metadata fill. Configure Base URL/API key, or disable 'Use LLM'."
            )
        if use_params_value:
            meta = apply_params_to_meta(meta, params)

    session.meta = meta

    mode_label = " + ".join(
        part for part in ("LLM" if use_llm_value else "", "Params" if use_params_value else "") if part
    )
    return {
        "status": "ok",
        "message": f"Metadata updated ({mode_label}).",
        "meta": meta.model_dump(),
        "warnings": warnings,
    }


@app.post("/api/render")
async def render_stage2(
    model: Optional[str] = Form(None),
    temperature: Optional[float] = Form(None),
    llm_base_url: Optional[str] = Form(None),
    llm_api_key: Optional[str] = Form(None),
    session: SessionState = Depends(get_session),
) -> dict:
    if session.compose_data is None:
        raise HTTPException(status_code=400, detail="No compose file loaded.")
    if session.meta is None:
        raise HTTPException(status_code=400, detail="Stage 1 metadata unavailable.")
    warnings: List[str] = []
    model_name = model or LLM_CFG.stage2.model
    temp_value = LLM_CFG.stage2.temperature if temperature is None else temperature
    api_key_value = llm_api_key or LLM_CFG.stage2.api_key
    base_url_value = llm_base_url or LLM_CFG.stage2.base_url
    logger.info(
        "Stage 2 render requested (model=%s, temp=%s, llm_base_url=%s, llm_api_key=%s, locales=%d)",
        model_name,
        temp_value,
        bool((base_url_value or "").strip()),
        bool(api_key_value),
        len(session.languages),
    )
    try:
        session.compose_data = render_compose(
            session.compose_data,
            session.meta,
            languages=session.languages,
            translation_map_override=session.translation_map,
            auto_translate=True,
            llm_model=model_name,
            llm_temperature=temp_value,
            llm_api_key=api_key_value,
            llm_base_url=base_url_value,
        )
    except Exception as exc:
        logger.warning(
            "Stage 2 render failed with LLM auto-translate; falling back to translation table/copy behavior: %s",
            exc,
        )
        warnings.append(
            "LLM unavailable; rendered Stage 2 without auto-translation "
            f"(other locales will copy en_US unless present in the translation table). Reason: {exc}"
        )
        session.compose_data = render_compose(
            session.compose_data,
            session.meta,
            languages=session.languages,
            translation_map_override=session.translation_map,
            auto_translate=False,
        )
    return {"status": "ok", "compose": session.compose_data, "warnings": warnings}


@app.post("/api/upload")
async def upload_compose(
    file: UploadFile = File(...),
    run_stage1: bool = Form(False),
    model: str = Form("gpt-4.1-mini"),
    temperature: float = Form(0.2),
    llm_base_url: Optional[str] = Form(None),
    llm_api_key: Optional[str] = Form(None),
    llm_prompt: Optional[str] = Form(None),
    session: SessionState = Depends(get_session),
) -> dict:
    _log_deprecated("/api/upload", "/api/compose + /api/meta/fill (+ /api/render)")
    content = await file.read()
    try:
        text = content.decode("utf-8")
        compose_data = parse_compose_text(text)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse compose file: {exc}") from exc
    skeleton = build_meta(compose_data)
    meta = skeleton
    if run_stage1:
        meta = fill_meta_with_llm(
            skeleton,
            model=model,
            temperature=temperature,
            api_key=llm_api_key,
            base_url=llm_base_url,
            prompt_instructions=llm_prompt,
        )
    try:
        template_compose = render_compose(
            compose_data,
            meta,
            languages=session.languages,
            translation_map_override=session.translation_map,
            auto_translate=True,
            llm_model=model,
            llm_temperature=temperature,
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("Stage 2 build failed; falling back to minimal template: %s", exc)
        template_compose = compose_data
        template_compose["x-casaos"] = {
            "title": wrap_multilang(meta.app.title, session.languages, session.translation_map),
            "tagline": wrap_multilang(meta.app.tagline, session.languages, session.translation_map),
            "description": wrap_multilang(meta.app.description, session.languages, session.translation_map),
            "releaseNotes": wrap_multilang(meta.app.releaseNotes, session.languages, session.translation_map),
        }

    session.compose_data = template_compose
    session.compose_text = text
    session.meta = meta
    return {
        "message": "Compose uploaded.",
        "meta": meta.model_dump(),
        "deprecated": True,
        "replacement": "/api/compose + /api/meta/fill (+ /api/render)",
    }


@app.post("/api/template", response_class=PlainTextResponse)
async def build_template(
    compose_file: UploadFile = File(...),
    params_file: Optional[UploadFile] = File(None),
    session: SessionState = Depends(get_session),
) -> PlainTextResponse:
    _log_deprecated("/api/template", "/api/compose + /api/meta/fill + /api/export")
    try:
        compose_text = (await compose_file.read()).decode("utf-8")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to read compose file: {exc}") from exc
    try:
        compose_data = parse_compose_text(compose_text)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse compose file: {exc}") from exc

    params = {}
    if params_file is not None:
        try:
            params_text = (await params_file.read()).decode("utf-8")
            params = parse_params_text(params_text)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to parse params file: {exc}") from exc

    try:
        template_compose = build_template_compose_from_data(
            compose_data,
            params=params,
            languages=session.languages,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Template generation failed: {exc}") from exc

    session.compose_data = template_compose
    session.compose_text = compose_text
    session.meta = None

    yaml_text = dump_yaml(template_compose)
    return PlainTextResponse(yaml_text, media_type="text/yaml")


@app.post("/api/meta/update")
async def update_meta_field(payload: FieldUpdate, session: SessionState = Depends(get_session)) -> dict:
    meta = require_meta(session)
    _update_meta_field(meta, payload)
    if payload.propagate_all_languages:
        propagate_translation(payload.value, session)
    if payload.sync_stage2 and session.compose_data and isinstance(session.compose_data.get("x-casaos"), dict):
        app_x = session.compose_data["x-casaos"]
        if payload.target in ("app.title", "app.tagline", "app.description", "app.releaseNotes"):
            attr_name = payload.target.split(".", 1)[1]
            app_x[attr_name] = wrap_multilang(payload.value, session.languages, session.translation_map)
    return {"status": "ok", "meta": meta.model_dump()}


@app.post("/api/stage2/update-multi")
async def update_stage2_multi_field(payload: Stage2MultiUpdate, session: SessionState = Depends(get_session)) -> dict:
    warnings = _update_stage2_multi_field(payload, session)
    return {"status": "ok", "compose": session.compose_data, "warnings": warnings}


@app.post("/api/stage2/update-single")
async def update_stage2_single_field(payload: Stage2SingleUpdate, session: SessionState = Depends(get_session)) -> dict:
    _update_stage2_single_field(payload, session)
    return {"status": "ok", "compose": session.compose_data}


@app.post("/api/assistant/chat")
async def assistant_chat(payload: AssistantChatRequest, session: SessionState = Depends(get_session)) -> dict:
    if not payload.messages:
        raise HTTPException(status_code=400, detail="At least one message is required.")
    client = require_llm_client()
    context = collect_target_context(payload.target, session)
    system_prompt = build_assistant_prompt(context)
    chat_messages = [{"role": "system", "content": system_prompt}]
    chat_messages.extend({"role": msg.role, "content": msg.content} for msg in payload.messages)
    try:
        response = client.chat.completions.create(
            model=LLM_CFG.stage1.model,
            messages=chat_messages,
            temperature=LLM_CFG.stage1.temperature,
        )
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=400, detail=f"LLM request failed: {exc}") from exc
    answer = response.choices[0].message.content or ""
    return {"status": "ok", "message": answer.strip(), "context": context}


@app.post("/api/export", response_class=PlainTextResponse)
async def export_compose(session: SessionState = Depends(get_session)) -> PlainTextResponse:
    if session.compose_data is None:
        raise HTTPException(status_code=400, detail="No compose file loaded.")
    ensure_stage2_structure(session)
    compose = session.compose_data
    if not compose.get("x-casaos"):
        raise HTTPException(status_code=400, detail="Stage 2 data unavailable. Run Stage 1 first.")
    compose = normalize_compose_for_appstore(compose)
    yaml_text = dump_yaml(compose)
    return PlainTextResponse(yaml_text, media_type="text/yaml")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(host: str = "127.0.0.1", port: int = 8001) -> None:
    """Launch the FastAPI web UI using uvicorn."""
    configure_web_logging()
    logger.info("Starting CasaOS web UI on %s:%s", host, port)
    logger.info("Backend log file: %s", WEBUI_LOG_PATH)
    logger.info("Serving frontend entry: %s", INDEX_HTML)
    uvicorn.run("casaos_gen.webui:app", host=host, port=port, reload=False, log_level="info", access_log=True)


if __name__ == "__main__":  # pragma: no cover
    run()
