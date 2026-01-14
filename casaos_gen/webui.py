"""FastAPI-based Web UI for CasaOS compose generation and editing."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import uvicorn
import yaml
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .compose_normalize import normalize_compose_for_appstore
from .i18n import DEFAULT_LANGUAGES, load_translation_map, wrap_multilang
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
from .yaml_out import dump_yaml

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency during tests
    OpenAI = None

logger = logging.getLogger(__name__)
LLM_CONFIG_PATH = Path("llm_config.json")
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
INDEX_HTML = FRONTEND_DIR / "index.html"


@dataclass
class WebState:
    compose_data: Optional[dict] = None
    compose_text: str = ""
    meta: Optional[CasaOSMeta] = None
    languages: List[str] = field(default_factory=lambda: list(DEFAULT_LANGUAGES))
    translation_map: Dict[str, Dict[str, str]] = field(default_factory=load_translation_map)
    llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: str = "gpt-4.1-mini"
    llm_temperature: float = 0.2


STATE = WebState()
app = FastAPI(title="CasaOS Compose Generator UI")

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


def _require_meta() -> CasaOSMeta:
    if STATE.meta is None or STATE.compose_data is None:
        raise HTTPException(status_code=400, detail="No compose metadata is loaded yet.")
    return STATE.meta


def _parse_service_target(target: str) -> Tuple[str, str, str]:
    parts = target.split(":")
    if len(parts) < 4 or parts[0] != "service":
        raise HTTPException(
            status_code=400,
            detail="Target must look like service:NAME:type:key (e.g. service:web:port:8080)",
        )
    service_name = parts[1]
    field_type = parts[2]
    identifier = ":".join(parts[3:])
    return service_name, field_type, identifier


def _propagate_translation(text: str) -> None:
    if not text:
        return
    entry = STATE.translation_map.setdefault(text, {})
    for lang in STATE.languages:
        if lang == "en_US":
            continue
        entry[lang] = text


def _ensure_stage2_structure(require_meta: bool = False) -> None:
    if STATE.compose_data is None:
        raise HTTPException(status_code=400, detail="No compose file loaded.")
    if STATE.compose_data.get("x-casaos"):
        return
    if STATE.meta is None:
        if require_meta:
            raise HTTPException(status_code=400, detail="Stage 1 metadata unavailable. Run Stage 1 first.")
        return
    STATE.compose_data = render_compose(
        STATE.compose_data,
        STATE.meta,
        languages=STATE.languages,
        translation_map_override=STATE.translation_map,
    )


def _require_llm_client():
    if OpenAI is None:
        raise HTTPException(status_code=500, detail="openai package is not installed.")

    client_kwargs = {}
    if STATE.llm_api_key:
        client_kwargs["api_key"] = STATE.llm_api_key
    if STATE.llm_base_url:
        client_kwargs["base_url"] = STATE.llm_base_url
    try:
        return OpenAI(**client_kwargs)
    except Exception as exc:  # pragma: no cover - defensive logging
        raise HTTPException(status_code=400, detail=f"Failed to initialize LLM client: {exc}") from exc


def _resolve_app_stage2_value(field_path: str):
    compose = STATE.compose_data or {}
    scope = compose.get("x-casaos") or {}
    for key in field_path.split("."):
        if not isinstance(scope, dict):
            return None
        scope = scope.get(key)
        if scope is None:
            return None
    return scope


def _resolve_service_stage2_multilang(service_name: str, field_type: str, identifier: str):
    compose = STATE.compose_data or {}
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


def _resolve_service_stage2_single(service_name: str, field_path: str):
    compose = STATE.compose_data or {}
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


def _collect_target_context(target: Optional[str]) -> str:
    if not target:
        return (
            "Target: general editing mode. Help the user craft CasaOS metadata for compose files and "
            "provide concise rewrites that are safe to copy into every locale."
        )

    lines = [f"Target field: {target}"]

    if target.startswith("app."):
        field_path = target.split(".", 1)[1]
        if STATE.meta:
            attr_name = field_path.split(".", 1)[0]
            if hasattr(STATE.meta.app, attr_name):
                lines.append(f"Stage 1 value: {getattr(STATE.meta.app, attr_name)}")
        stage2_value = _resolve_app_stage2_value(field_path)
        if stage2_value is not None:
            lines.append(f"Stage 2 value: {stage2_value}")
        return "\n".join(lines)

    parts = target.split(":")
    if len(parts) >= 4 and parts[0] == "service" and parts[2] in {"env", "port", "volume"}:
        service_name, field_type = parts[1], parts[2]
        identifier = ":".join(parts[3:])
        if STATE.meta:
            service_meta = STATE.meta.services.get(service_name)
            if service_meta:
                collection = getattr(service_meta, f"{field_type}s", [])
                entry = next((item for item in collection if item.container == identifier), None)
                if entry:
                    lines.append(f"Stage 1 value: {entry.description}")
        stage2_value = _resolve_service_stage2_multilang(service_name, field_type, identifier)
        if stage2_value is not None:
            lines.append(f"Stage 2 value: {stage2_value}")
        return "\n".join(lines)

    if len(parts) >= 3 and parts[0] == "service":
        service_name = parts[1]
        field_path = ":".join(parts[2:])
        stage2_value = _resolve_service_stage2_single(service_name, field_path)
        if stage2_value is not None:
            lines.append(f"Stage 2 value: {stage2_value}")
        return "\n".join(lines)

    return "\n".join(lines)


def _build_assistant_prompt(context: str) -> str:
    base = (
        "You are an AI writing partner embedded in a CasaOS compose visual editor. "
        "Users will ask for help rewriting metadata that describes docker-compose applications. "
        "Respond with actionable prose that can be copied verbatim into the metadata. "
        "Keep answers under 120 words when possible. "
        "When asked to rewrite a multi-language field, craft a single neutral English draft that can be propagated across all locales, "
        "avoiding language-specific mentions."
    )
    return f"{base}\n\nContext:\n{context}"


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
    <p>Frontend assets are missing. Please build the UI under the frontend/ directory.</p>
  </body>
</html>
""".strip()


def _log_deprecated(endpoint: str, replacement: str) -> None:
    logger.warning("%s is deprecated; use %s instead.", endpoint, replacement)


class FieldUpdate(BaseModel):
    target: str
    value: str
    propagate_all_languages: bool = False


class ComposeText(BaseModel):
    text: str


class Stage2MultiUpdate(BaseModel):
    target: str
    value: str


class Stage2SingleUpdate(BaseModel):
    target: str
    value: str


class AssistantMessage(BaseModel):
    role: str
    content: str


class AssistantChatRequest(BaseModel):
    messages: List[AssistantMessage]
    target: Optional[str] = None


def _update_meta_field(meta: CasaOSMeta, payload: FieldUpdate) -> None:
    if payload.target.startswith("app."):
        field = payload.target.split(".", 1)[1]
        if not hasattr(meta.app, field):
            raise HTTPException(status_code=400, detail=f"Unknown app field: {field}")
        setattr(meta.app, field, payload.value)
        return

    service_name, field_type, identifier = _parse_service_target(payload.target)
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


def _update_stage2_multi_field(payload: Stage2MultiUpdate) -> None:
    _ensure_stage2_structure(require_meta=True)
    compose = STATE.compose_data or {}

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
        for lang in STATE.languages:
            multilang[lang] = payload.value
        return

    service_name, field_type, identifier = _parse_service_target(payload.target)
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
    for lang in STATE.languages:
        desc[lang] = payload.value
    _propagate_translation(payload.value)


def _update_stage2_single_field(payload: Stage2SingleUpdate) -> None:
    _ensure_stage2_structure(require_meta=True)
    compose = STATE.compose_data or {}

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


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(content=_load_index_html())


@app.get("/api/state")
async def get_state() -> dict:
    return {
        "languages": STATE.languages,
        "has_compose": STATE.compose_data is not None,
        "has_meta": STATE.meta is not None,
        "has_stage2": bool(STATE.compose_data and STATE.compose_data.get("x-casaos")),
        "meta": STATE.meta.model_dump() if STATE.meta else None,
        "llm": {
            "base_url": STATE.llm_base_url,
            "api_key": bool(STATE.llm_api_key),
            "model": STATE.llm_model,
            "temperature": STATE.llm_temperature,
        },
    }


@app.post("/api/llm")
async def set_llm_config(
    base_url: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
    temperature: Optional[float] = Form(None),
) -> dict:
    save_llm_config(base_url, api_key, model, temperature)
    return {
        "status": "ok",
        "llm": {
            "base_url": STATE.llm_base_url,
            "api_key": bool(STATE.llm_api_key),
            "model": STATE.llm_model,
            "temperature": STATE.llm_temperature,
        },
    }


@app.post("/api/compose")
async def load_compose(file: UploadFile = File(...)) -> dict:
    try:
        text = (await file.read()).decode("utf-8")
        compose_data = parse_compose_text(text)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse compose file: {exc}") from exc
    meta = build_meta(compose_data)
    STATE.compose_data = compose_data
    STATE.compose_text = text
    STATE.meta = meta
    return {"status": "ok", "message": "Compose loaded.", "meta": meta.model_dump()}


@app.post("/api/compose-text")
async def load_compose_text(payload: ComposeText) -> dict:
    raw_text = payload.text or ""
    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="Compose text is empty.")
    try:
        compose_data = parse_compose_text(raw_text)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse compose text: {exc}") from exc
    meta = build_meta(compose_data)
    STATE.compose_data = compose_data
    STATE.compose_text = raw_text
    STATE.meta = meta
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
) -> dict:
    if STATE.compose_data is None:
        raise HTTPException(status_code=400, detail="No compose file loaded.")

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

    if not use_llm_value and not use_params_value:
        raise HTTPException(status_code=400, detail="Select at least one of LLM or params.")

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

    meta = STATE.meta or build_meta(STATE.compose_data)
    if use_params_value:
        meta = apply_params_to_meta(meta, params)

    if use_llm_value:
        model_name = model or STATE.llm_model
        temp_value = STATE.llm_temperature if temperature is None else temperature
        meta = fill_meta_with_llm(
            meta,
            model=model_name,
            temperature=temp_value,
            api_key=llm_api_key or STATE.llm_api_key,
            base_url=llm_base_url or STATE.llm_base_url,
        )
        if use_params_value:
            meta = apply_params_to_meta(meta, params)

    STATE.meta = meta

    mode_label = " + ".join(
        part for part in ("LLM" if use_llm_value else "", "Params" if use_params_value else "") if part
    )
    return {"status": "ok", "message": f"Metadata updated ({mode_label}).", "meta": meta.model_dump()}


@app.post("/api/render")
async def render_stage2() -> dict:
    if STATE.compose_data is None:
        raise HTTPException(status_code=400, detail="No compose file loaded.")
    if STATE.meta is None:
        raise HTTPException(status_code=400, detail="Stage 1 metadata unavailable.")
    STATE.compose_data = render_compose(
        STATE.compose_data,
        STATE.meta,
        languages=STATE.languages,
        translation_map_override=STATE.translation_map,
    )
    return {"status": "ok", "compose": STATE.compose_data}


@app.post("/api/upload")
async def upload_compose(
    file: UploadFile = File(...),
    run_stage1: bool = Form(False),
    model: str = Form("gpt-4.1-mini"),
    temperature: float = Form(0.2),
    llm_base_url: Optional[str] = Form(None),
    llm_api_key: Optional[str] = Form(None),
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
        )
    try:
        template_compose = render_compose(
            compose_data,
            meta,
            languages=STATE.languages,
            translation_map_override=STATE.translation_map,
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Stage 2 build failed; falling back to minimal template: %s", exc)
        template_compose = compose_data
        template_compose["x-casaos"] = {
            "title": wrap_multilang(meta.app.title, STATE.languages, STATE.translation_map),
            "tagline": wrap_multilang(meta.app.tagline, STATE.languages, STATE.translation_map),
            "description": wrap_multilang(meta.app.description, STATE.languages, STATE.translation_map),
        }

    STATE.compose_data = template_compose
    STATE.compose_text = text
    STATE.meta = meta
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
            languages=STATE.languages,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Template generation failed: {exc}") from exc

    STATE.compose_data = template_compose
    STATE.compose_text = compose_text
    STATE.meta = None

    yaml_text = dump_yaml(template_compose)
    return PlainTextResponse(yaml_text, media_type="text/yaml")


@app.post("/api/meta/update")
async def update_meta_field(payload: FieldUpdate) -> dict:
    meta = _require_meta()
    _update_meta_field(meta, payload)
    if payload.propagate_all_languages:
        _propagate_translation(payload.value)
    if STATE.compose_data and isinstance(STATE.compose_data.get("x-casaos"), dict):
        # Keep Stage 2 compose in sync for key app fields when editing Stage 1 meta.
        app_x = STATE.compose_data["x-casaos"]
        if payload.target in ("app.title", "app.tagline", "app.description"):
            attr_name = payload.target.split(".", 1)[1]
            app_x[attr_name] = wrap_multilang(payload.value, STATE.languages, STATE.translation_map)
    return {"status": "ok", "meta": meta.model_dump()}


@app.post("/api/stage2/update-multi")
async def update_stage2_multi_field(payload: Stage2MultiUpdate) -> dict:
    _update_stage2_multi_field(payload)
    return {"status": "ok", "compose": STATE.compose_data}


@app.post("/api/stage2/update-single")
async def update_stage2_single_field(payload: Stage2SingleUpdate) -> dict:
    _update_stage2_single_field(payload)
    return {"status": "ok", "compose": STATE.compose_data}


@app.post("/api/assistant/chat")
async def assistant_chat(payload: AssistantChatRequest) -> dict:
    if not payload.messages:
        raise HTTPException(status_code=400, detail="At least one message is required.")
    client = _require_llm_client()
    context = _collect_target_context(payload.target)
    system_prompt = _build_assistant_prompt(context)
    chat_messages = [{"role": "system", "content": system_prompt}]
    chat_messages.extend({"role": msg.role, "content": msg.content} for msg in payload.messages)
    try:
        response = client.chat.completions.create(
            model=STATE.llm_model,
            messages=chat_messages,
            temperature=STATE.llm_temperature,
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        raise HTTPException(status_code=400, detail=f"LLM request failed: {exc}") from exc
    answer = response.choices[0].message.content or ""
    return {"status": "ok", "message": answer.strip(), "context": context}


@app.post("/api/export", response_class=PlainTextResponse)
async def export_compose() -> PlainTextResponse:
    if STATE.compose_data is None:
        raise HTTPException(status_code=400, detail="No compose file loaded.")
    _ensure_stage2_structure()
    compose = STATE.compose_data
    if not compose.get("x-casaos"):
        raise HTTPException(status_code=400, detail="Stage 2 data unavailable. Run Stage 1 first.")
    compose = normalize_compose_for_appstore(compose)
    yaml_text = dump_yaml(compose)
    return PlainTextResponse(yaml_text, media_type="text/yaml")


def run(host: str = "127.0.0.1", port: int = 8001) -> None:
    """Launch the FastAPI web UI using uvicorn."""
    logger.info("Starting CasaOS web UI on %s:%s", host, port)
    uvicorn.run("casaos_gen.webui:app", host=host, port=port, reload=False)


if __name__ == "__main__":  # pragma: no cover
    run()
def load_llm_config() -> None:
    if LLM_CONFIG_PATH.exists():
        try:
            data = json.loads(LLM_CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Failed to parse llm_config.json")
            return
        STATE.llm_base_url = data.get("base_url")
        STATE.llm_api_key = data.get("api_key")
        STATE.llm_model = data.get("model", STATE.llm_model)
        STATE.llm_temperature = data.get("temperature", STATE.llm_temperature)


def save_llm_config(
    base_url: Optional[str],
    api_key: Optional[str],
    model: Optional[str],
    temperature: Optional[float],
) -> None:
    if base_url is not None:
        STATE.llm_base_url = base_url or None
    if api_key is not None:
        STATE.llm_api_key = api_key or None
    if model is not None:
        STATE.llm_model = model or STATE.llm_model
    if temperature is not None:
        STATE.llm_temperature = temperature
    LLM_CONFIG_PATH.write_text(
        json.dumps(
            {
                "base_url": STATE.llm_base_url,
                "api_key": STATE.llm_api_key,
                "model": STATE.llm_model,
                "temperature": STATE.llm_temperature,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


load_llm_config()


# ========== 版本管理 API ==========

from datetime import datetime
from .incremental import (
    get_version_history,
    rollback_version as rollback_to_version,
    show_compose_diff,
    incremental_update,
)


class RollbackRequest(BaseModel):
    version_file: str


class IncrementalUpdateRequest(BaseModel):
    force_regenerate: bool = False
    params: Optional[dict] = None


@app.get("/api/versions")
async def list_versions() -> dict:
    """列出所有历史版本"""
    try:
        versions = get_version_history()
        # 格式化时间戳
        formatted_versions = []
        for v in versions:
            formatted_versions.append({
                "file": v["file"],
                "timestamp": datetime.fromtimestamp(v["timestamp"]).strftime("%Y-%m-%d %H:%M:%S"),
                "size": v["size"],
                "size_kb": round(v["size"] / 1024, 1),
            })
        return {"status": "ok", "versions": formatted_versions}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list versions: {exc}") from exc


@app.post("/api/versions/rollback")
async def rollback(payload: RollbackRequest) -> dict:
    """回滚到指定版本"""
    try:
        rollback_to_version(payload.version_file)
        # 重新加载元数据
        from .version_manager import VersionManager
        vm = VersionManager()
        STATE.meta = vm.load_current_meta()
        return {
            "status": "ok",
            "message": f"已回滚到版本: {payload.version_file}",
            "meta": STATE.meta.model_dump() if STATE.meta else None,
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Rollback failed: {exc}") from exc


@app.get("/api/diff")
async def get_compose_diff() -> dict:
    """获取当前 compose 文件与历史版本的差异"""
    if STATE.compose_text is None:
        raise HTTPException(status_code=400, detail="No compose file loaded.")
    
    try:
        # 保存当前 compose 到临时文件
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False, encoding='utf-8') as f:
            f.write(STATE.compose_text)
            temp_path = Path(f.name)
        
        try:
            diff = show_compose_diff(temp_path)
        finally:
            temp_path.unlink()  # 删除临时文件
        
        if diff is None:
            return {"status": "ok", "has_diff": False, "message": "没有旧版本可对比"}
        
        return {
            "status": "ok",
            "has_diff": diff.has_changes(),
            "summary": diff.summary(),
            "added_services": list(diff.added_services),
            "removed_services": list(diff.removed_services),
            "added_fields_count": len(diff.added_fields),
            "removed_fields_count": len(diff.removed_fields),
            "modified_fields_count": len(diff.modified_fields),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to compute diff: {exc}") from exc


@app.post("/api/incremental")
async def incremental_update_api(payload: IncrementalUpdateRequest) -> dict:
    """执行增量更新"""
    if STATE.compose_text is None:
        raise HTTPException(status_code=400, detail="No compose file loaded.")
    
    try:
        # 保存当前 compose 到临时文件
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False, encoding='utf-8') as f:
            f.write(STATE.compose_text)
            temp_path = Path(f.name)
        
        try:
            # LLM 配置
            llm_config = {
                "model": STATE.llm_model,
                "temperature": STATE.llm_temperature,
                "api_key": STATE.llm_api_key,
                "base_url": STATE.llm_base_url,
            } if STATE.llm_api_key or STATE.llm_base_url else None
            
            # 执行增量更新
            meta, diff = incremental_update(
                compose_path=temp_path,
                params=payload.params,
                force_regenerate=payload.force_regenerate,
                llm_config=llm_config,
            )
        finally:
            temp_path.unlink()  # 删除临时文件
        
        # 更新状态
        STATE.meta = meta
        
        # 重新解析 compose（因为可能有新增服务）
        STATE.compose_data = parse_compose_text(STATE.compose_text)
        
        result = {
            "status": "ok",
            "message": "增量更新完成",
            "meta": meta.model_dump(),
        }
        
        if diff and diff.has_changes():
            result["diff"] = {
                "added_services": list(diff.added_services),
                "removed_services": list(diff.removed_services),
                "added_fields_count": len(diff.added_fields),
                "removed_fields_count": len(diff.removed_fields),
            }
        
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Incremental update failed: {exc}") from exc
