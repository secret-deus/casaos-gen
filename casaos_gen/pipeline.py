"""Pipeline helpers for CasaOS compose generation."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .i18n import DEFAULT_LANGUAGES, load_translation_map
from .llm_translate import translate_texts_with_llm
from .llm_stage1 import run_stage1_llm
from .models import CasaOSMeta
from .parser import build_casaos_meta
from .constants import CDN_BASE, STORE_FOLDER_PLACEHOLDER
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


def _replace_store_folder_placeholder(value: str, store_folder: str) -> str:
    if not store_folder:
        return value
    if STORE_FOLDER_PLACEHOLDER not in value:
        return value
    return value.replace(STORE_FOLDER_PLACEHOLDER, store_folder)


def _apply_text_field(meta: CasaOSMeta, field: str, value: Any) -> None:
    text = _as_text(value).strip()
    if text:
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

        store_folder = _as_text(app_params.get("store_folder")).strip()

        icon_value = _as_text(app_params.get("icon"))
        thumbnail_value = _as_text(app_params.get("thumbnail"))
        screenshot_value = app_params.get("screenshot_link")
        if screenshot_value is None:
            screenshot_value = app_params.get("screenshot_links")
        screenshot_links = _clean_list(_as_list(screenshot_value))

        if icon_value.strip():
            meta.app.icon = _replace_store_folder_placeholder(icon_value, store_folder)
        elif store_folder:
            meta.app.icon = f"{CDN_BASE}/{store_folder}/icon.png"

        if thumbnail_value.strip():
            meta.app.thumbnail = _replace_store_folder_placeholder(thumbnail_value, store_folder)
        elif store_folder:
            meta.app.thumbnail = f"{CDN_BASE}/{store_folder}/thumbnail.png"

        if screenshot_links:
            meta.app.screenshot_link = [
                _replace_store_folder_placeholder(item, store_folder) for item in screenshot_links
            ]
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
    prompt_instructions: Optional[str] = None,
) -> CasaOSMeta:
    return run_stage1_llm(
        meta,
        model=model,
        temperature=temperature,
        client=client,
        api_key=api_key,
        base_url=base_url,
        prompt_instructions=prompt_instructions,
    )


def render_compose(
    compose_data: Dict,
    meta: CasaOSMeta,
    languages: Optional[List[str]] = None,
    translation_file: Optional[Path] = None,
    translation_map_override: Optional[Dict[str, Dict[str, str]]] = None,
    auto_translate: bool = False,
    llm_model: str = "gpt-4.1-mini",
    llm_temperature: float = 0.2,
    llm_client: Optional[object] = None,
    llm_api_key: Optional[str] = None,
    llm_base_url: Optional[str] = None,
) -> Dict:
    langs = languages or DEFAULT_LANGUAGES
    if not auto_translate:
        if translation_map_override is not None:
            translation_map = translation_map_override
        else:
            translation_map = load_translation_map(translation_file)
        return build_final_compose(compose_data, meta, langs, translation_map)

    translation_map = _build_translation_map_with_llm(
        compose_data,
        meta,
        langs,
        translation_map_override=translation_map_override,
        translation_file=translation_file,
        model=llm_model,
        temperature=llm_temperature,
        client=llm_client,
        api_key=llm_api_key,
        base_url=llm_base_url,
    )
    compose_out = build_final_compose(compose_data, meta, langs, translation_map)
    _apply_llm_translated_tips(compose_out, langs, translation_map)
    return compose_out


def _seed_translation_map_from_compose(
    compose_data: Dict[str, Any],
    languages: List[str],
    translation_map: Dict[str, Dict[str, str]],
) -> None:
    """Best-effort: preserve existing translations found in x-casaos blocks."""

    def ingest_multilang(payload: Any) -> None:
        if payload is None:
            return
        if isinstance(payload, dict):
            english_text = _as_text(payload).strip()
            if not english_text:
                return
            entry = translation_map.setdefault(english_text, {})
            for lang in languages:
                if lang == "en_US":
                    continue
                candidate = str(payload.get(lang) or "").strip()
                if candidate and not str(entry.get(lang) or "").strip():
                    entry[lang] = candidate
            return
        english_text = str(payload).strip()
        if english_text:
            translation_map.setdefault(english_text, {})

    app_x = compose_data.get("x-casaos")
    if isinstance(app_x, dict):
        for field in ("title", "tagline", "description"):
            ingest_multilang(app_x.get(field))
        tips = app_x.get("tips")
        if isinstance(tips, dict):
            for section_value in tips.values():
                ingest_multilang(section_value)

    services = compose_data.get("services") or {}
    if not isinstance(services, dict):
        return
    for svc in services.values():
        if not isinstance(svc, dict):
            continue
        svc_x = svc.get("x-casaos")
        if not isinstance(svc_x, dict):
            continue
        for list_name in ("envs", "ports", "volumes"):
            items = svc_x.get(list_name) or []
            if not isinstance(items, list):
                continue
            for entry in items:
                if not isinstance(entry, dict):
                    continue
                ingest_multilang(entry.get("description"))


def _collect_stage2_texts(
    compose_data: Dict[str, Any],
    meta: CasaOSMeta,
) -> List[str]:
    texts: List[str] = []
    app = meta.app
    for field in ("title", "tagline", "description"):
        value = getattr(app, field, "")
        if str(value).strip():
            texts.append(str(value).strip())

    for svc in meta.services.values():
        for env in svc.envs:
            if env.multilang and env.description.strip():
                texts.append(env.description.strip())
        for port in svc.ports:
            if port.multilang and port.description.strip():
                texts.append(port.description.strip())
        for vol in svc.volumes:
            if vol.multilang and vol.description.strip():
                texts.append(vol.description.strip())

    app_x = compose_data.get("x-casaos")
    if isinstance(app_x, dict):
        tips = app_x.get("tips")
        if isinstance(tips, dict):
            for payload in tips.values():
                english_text = _as_text(payload).strip()
                if english_text:
                    texts.append(english_text)

    return texts


def _missing_languages(
    english_text: str,
    languages: List[str],
    translation_map: Dict[str, Dict[str, str]],
) -> List[str]:
    def looks_like_sentence(text: str) -> bool:
        stripped = text.strip()
        if len(stripped) < 8:
            return False
        if any(ch.isspace() for ch in stripped):
            return True
        if any(ch in ".,;:!?-" for ch in stripped):
            return True
        return False

    entry = translation_map.get(english_text) or {}
    missing: List[str] = []
    for lang in languages:
        if lang == "en_US":
            continue
        candidate = str(entry.get(lang) or "").strip()
        if not candidate:
            missing.append(lang)
            continue
        # If a previous run "filled" locales by copying the English text, treat
        # that as missing so we can replace it with a real translation.
        if lang.startswith("en_"):
            continue
        if candidate == english_text.strip() and looks_like_sentence(english_text):
            missing.append(lang)
    return missing


def _build_translation_map_with_llm(
    compose_data: Dict[str, Any],
    meta: CasaOSMeta,
    languages: List[str],
    *,
    translation_map_override: Optional[Dict[str, Dict[str, str]]],
    translation_file: Optional[Path],
    model: str,
    temperature: float,
    client: Optional[object],
    api_key: Optional[str],
    base_url: Optional[str],
) -> Dict[str, Dict[str, str]]:
    """Build/extend a translation map by translating missing phrases via LLM."""

    if translation_map_override is not None:
        translation_map = translation_map_override
    elif translation_file is not None:
        translation_map = load_translation_map(translation_file)
    else:
        translation_map = {}

    _seed_translation_map_from_compose(compose_data, languages, translation_map)

    candidates = _collect_stage2_texts(compose_data, meta)
    needed = [
        text
        for text in candidates
        if text.strip() and _missing_languages(text, languages, translation_map)
    ]
    if not needed:
        return translation_map

    translations_by_text = translate_texts_with_llm(
        needed,
        languages,
        model=model,
        temperature=temperature,
        client=client,
        api_key=api_key,
        base_url=base_url,
        source_language="en_US",
    )

    for english_text, translations in translations_by_text.items():
        entry = translation_map.setdefault(english_text, {})
        for lang in languages:
            if lang == "en_US":
                continue
            existing = str(entry.get(lang) or "").strip()
            should_override_english_copy = (
                bool(existing)
                and (not lang.startswith("en_"))
                and existing == english_text.strip()
                and (len(english_text.strip()) >= 8)
                and ((" " in english_text.strip()) or any(ch in ".,;:!?-" for ch in english_text.strip()))
            )
            if existing and not should_override_english_copy:
                continue
            candidate = str(translations.get(lang) or "").strip()
            entry[lang] = candidate if candidate else english_text

    return translation_map


def _apply_llm_translated_tips(
    compose_data: Dict[str, Any],
    languages: List[str],
    translation_map: Dict[str, Dict[str, str]],
) -> None:
    """Ensure x-casaos.tips sections are full multi-language dicts.

    Tips are not part of CasaOSMeta, but they are multi-language fields in the
    final YAML and should follow the same translation behavior as app fields.
    """

    app_x = compose_data.get("x-casaos")
    if not isinstance(app_x, dict):
        return
    tips = app_x.get("tips")
    if not isinstance(tips, dict):
        return

    from .i18n import wrap_multilang

    for section, payload in list(tips.items()):
        english_text = _as_text(payload).strip()
        if not english_text:
            continue
        tips[section] = wrap_multilang(english_text, languages, translation_map)


def build_template_compose_from_data(
    compose_data: Dict,
    params: Optional[Dict] = None,
    languages: Optional[List[str]] = None,
) -> Dict:
    return build_template_compose(compose_data, params=params, languages=languages)
