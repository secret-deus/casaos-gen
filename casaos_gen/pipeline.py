"""Pipeline helpers for CasaOS compose generation."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .i18n import DEFAULT_LANGUAGES, load_translation_map
from .llm_stage1 import run_stage1_llm
from .models import CasaOSMeta
from .parser import build_casaos_meta
from .constants import CDN_BASE
from .template_stage import build_template_compose
from .yaml_out import build_final_compose


def parse_compose_text(text: str) -> Dict:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("Compose content must be a YAML mapping.")
    return data


def parse_params_text(text: str) -> Dict:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("Params content must be a YAML mapping.")
    if "app" not in data:
        raise ValueError("Params content must include top-level 'app:' mapping.")
    return data


def _as_text(value: Any) -> str:
    if isinstance(value, dict):
        if "en_US" in value:
            return str(value.get("en_US") or "")
        for candidate in value.values():
            if candidate is not None:
                return str(candidate)
        return ""
    if value is None:
        return ""
    return str(value)


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, str):
        return [value]
    return []


def _clean_list(values: List[str]) -> List[str]:
    return [item.strip() for item in values if str(item).strip()]


def _apply_text_field(meta: CasaOSMeta, field: str, value: Any) -> None:
    text = _as_text(value)
    if text.strip():
        setattr(meta.app, field, text)


def _apply_service_descriptions(items: List[Any], payload: Any) -> None:
    if not isinstance(payload, list):
        return
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        container = _as_text(entry.get("container")).strip()
        if not container:
            continue
        description = _as_text(entry.get("description"))
        if not description.strip():
            continue
        target = next((item for item in items if item.container == container), None)
        if target:
            target.description = description


def apply_params_to_meta(meta: CasaOSMeta, params: Optional[Dict[str, Any]]) -> CasaOSMeta:
    """Overlay params.yml values onto the in-memory metadata."""
    if not params:
        return meta
    app_params = params.get("app") or {}
    if isinstance(app_params, dict):
        _apply_text_field(meta, "title", app_params.get("title"))
        _apply_text_field(meta, "tagline", app_params.get("tagline"))
        _apply_text_field(meta, "description", app_params.get("description"))
        _apply_text_field(meta, "category", app_params.get("category"))
        _apply_text_field(meta, "author", app_params.get("author"))
        _apply_text_field(meta, "developer", app_params.get("developer"))
        _apply_text_field(meta, "main", app_params.get("main"))
        _apply_text_field(meta, "port_map", app_params.get("port_map"))
        _apply_text_field(meta, "scheme", app_params.get("scheme"))
        _apply_text_field(meta, "index", app_params.get("index"))

        architectures = _clean_list(_as_list(app_params.get("architectures")))
        if architectures:
            meta.app.architectures = architectures

        icon_value = _as_text(app_params.get("icon"))
        thumbnail_value = _as_text(app_params.get("thumbnail"))
        screenshot_value = app_params.get("screenshot_link")
        if screenshot_value is None:
            screenshot_value = app_params.get("screenshot_links")
        screenshot_links = _clean_list(_as_list(screenshot_value))

        store_folder = _as_text(app_params.get("store_folder")).strip()
        if icon_value.strip():
            meta.app.icon = icon_value
        elif store_folder:
            meta.app.icon = f"{CDN_BASE}/{store_folder}/icon.png"

        if thumbnail_value.strip():
            meta.app.thumbnail = thumbnail_value
        elif store_folder:
            meta.app.thumbnail = f"{CDN_BASE}/{store_folder}/thumbnail.png"

        if screenshot_links:
            meta.app.screenshot_link = screenshot_links
        elif store_folder:
            meta.app.screenshot_link = [
                f"{CDN_BASE}/{store_folder}/screenshot-1.png",
                f"{CDN_BASE}/{store_folder}/screenshot-2.png",
                f"{CDN_BASE}/{store_folder}/screenshot-3.png",
            ]

    services_params = params.get("services") or {}
    if isinstance(services_params, dict):
        for name, svc_params in services_params.items():
            if not isinstance(svc_params, dict):
                continue
            svc_meta = meta.services.get(name)
            if not svc_meta:
                continue
            _apply_service_descriptions(svc_meta.envs, svc_params.get("envs"))
            _apply_service_descriptions(svc_meta.ports, svc_params.get("ports"))
            _apply_service_descriptions(svc_meta.volumes, svc_params.get("volumes"))

    return meta


def build_meta(compose_data: Dict) -> CasaOSMeta:
    return build_casaos_meta(compose_data)


def fill_meta_with_llm(
    meta: CasaOSMeta,
    model: str,
    temperature: float,
    client: Optional[object] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> CasaOSMeta:
    return run_stage1_llm(
        meta,
        model=model,
        temperature=temperature,
        client=client,
        api_key=api_key,
        base_url=base_url,
    )


def render_compose(
    compose_data: Dict,
    meta: CasaOSMeta,
    languages: Optional[List[str]] = None,
    translation_file: Optional[Path] = None,
    translation_map_override: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict:
    langs = languages or DEFAULT_LANGUAGES
    if translation_map_override is not None:
        translation_map = translation_map_override
    else:
        translation_map = load_translation_map(translation_file)
    return build_final_compose(compose_data, meta, langs, translation_map)


def build_template_compose_from_data(
    compose_data: Dict,
    params: Optional[Dict] = None,
    languages: Optional[List[str]] = None,
) -> Dict:
    return build_template_compose(compose_data, params=params, languages=languages)
