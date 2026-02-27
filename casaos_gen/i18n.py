"""Internationalization utilities for CasaOS metadata."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .models import CasaOSMeta

logger = logging.getLogger(__name__)

TRANSLATIONS_PATH = Path(__file__).with_name("translations.yml")
DEFAULT_LANGUAGES = [
    "de_DE",
    "el_GR",
    "en_GB",
    "en_US",
    "fr_FR",
    "hr_HR",
    "it_IT",
    "ja_JP",
    "ko_KR",
    "nb_NO",
    "pt_PT",
    "ru_RU",
    "sv_SE",
    "tr_TR",
    "zh_CN",
]


def load_translation_map(path: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    target = path or TRANSLATIONS_PATH
    if not target.exists():
        logger.warning("Translation file missing at %s", target)
        return {}
    with target.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    cleaned: Dict[str, Dict[str, str]] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, dict):
            cleaned[key] = {str(lang): str(text) for lang, text in value.items()}
    return cleaned


TRANSLATION_MAP = load_translation_map()


def wrap_multilang(
    english: str,
    languages: List[str],
    translation_map: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, str]:
    translations = translation_map or TRANSLATION_MAP
    text = english or ""
    lookup_key = text.strip()
    result: Dict[str, str] = {}
    for lang in languages:
        if not lang:
            continue
        if lang == "en_US":
            result[lang] = text
            continue
        localized = translations.get(lookup_key, {}).get(lang)
        result[lang] = localized if localized else text
    if "en_US" not in result:
        result["en_US"] = text
    return result


def apply_multilang_app(
    meta: CasaOSMeta,
    languages: List[str],
    translation_map: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict:
    translations = translation_map or TRANSLATION_MAP
    app = meta.app
    return {
        "title": wrap_multilang(app.title, languages, translations),
        "tagline": wrap_multilang(app.tagline, languages, translations),
        "description": wrap_multilang(app.description, languages, translations),
        "category": app.category,
        "author": app.author,
        "developer": app.developer,
        "icon": app.icon,
        "thumbnail": app.thumbnail,
        "screenshot_link": app.screenshot_link,
        "main": app.main,
        "port_map": app.port_map,
        "architectures": app.architectures,
        "index": app.index,
        "scheme": app.scheme,
    }


def apply_multilang_services(
    meta: CasaOSMeta,
    languages: List[str],
    translation_map: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, Dict]:
    translations = translation_map or TRANSLATION_MAP
    results: Dict[str, Dict] = {}
    for name, svc in meta.services.items():
        svc_block = {"envs": [], "ports": [], "volumes": []}
        for env in svc.envs:
            # 检查是否需要多语言化
            if env.multilang:
                desc = wrap_multilang(env.description, languages, translations)
            else:
                desc = env.description  # 保持单语言
            svc_block["envs"].append({"container": env.container, "description": desc})

        for port in svc.ports:
            if port.multilang:
                desc = wrap_multilang(port.description, languages, translations)
            else:
                desc = port.description
            svc_block["ports"].append({"container": port.container, "description": desc})

        for vol in svc.volumes:
            if vol.multilang:
                desc = wrap_multilang(vol.description, languages, translations)
            else:
                desc = vol.description
            svc_block["volumes"].append({"container": vol.container, "description": desc})

        results[name] = svc_block
    return results

