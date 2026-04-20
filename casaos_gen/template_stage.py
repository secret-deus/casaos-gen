"""Template stage: build a CasaOS-ready compose without LLMs.

This stage is meant for users who want a modular, parameterized workflow:
- Start from a normal docker-compose.yml
- Provide a small params.yml (app/service overrides)
- Produce a CasaOS compose template with required x-casaos metadata

Multi-language fields accept either:
  - a single string (replicated to all locales), or
  - a dict of locales -> text.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .exceptions import ComposeParseError, ParamsError

from .constants import CDN_BASE, STORE_FOLDER_PLACEHOLDER
from .i18n import DEFAULT_LANGUAGES
from .infer import (
    infer_author,
    infer_category,
    infer_docs,
    infer_main_port,
    infer_main_service,
    infer_release_notes,
    infer_repo,
    infer_support,
    infer_update_at,
    infer_version,
    infer_website,
)
from .parser import build_xcasaos_template, extract_envs, extract_ports, extract_volumes

logger = logging.getLogger(__name__)


def load_template_params(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {}
    if not path.exists():
        raise FileNotFoundError(f"Params file not found: {path}")
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ParamsError("Params file must be a YAML mapping")
    if "app" not in data:
        raise ParamsError(
            "Params file must include top-level 'app:' mapping. "
            "If you passed a compose YAML by mistake, generate a params file first "
            "with: casaos-gen <compose.yml> --stage params"
        )
    return data


def _as_list(value: Any, default: List[str]) -> List[str]:
    if value is None:
        return list(default)
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value]
    return list(default)


def _replace_store_folder_placeholder(value: str, store_folder: str) -> str:
    if STORE_FOLDER_PLACEHOLDER not in value:
        return value
    return value.replace(STORE_FOLDER_PLACEHOLDER, store_folder)


def build_template_compose(
    compose_data: Dict[str, Any],
    params: Optional[Dict[str, Any]] = None,
    languages: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build a CasaOS template compose from normal compose + user params."""
    params = params or {}
    params_app = params.get("app") or {}
    params_services = params.get("services") or {}

    services = compose_data.get("services") or {}
    if not services:
        raise ComposeParseError("Compose file must include services")

    main_service = infer_main_service(services)
    inferred_port_map = infer_main_port(services.get(main_service, {}))
    inferred_category = infer_category(services, preferred_service=main_service)
    inferred_author = infer_author(services, preferred_service=main_service)
    inferred_version = infer_version(services, preferred_service=main_service)
    inferred_update_at = infer_update_at(services, preferred_service=main_service)
    inferred_release_notes = infer_release_notes(services, preferred_service=main_service)
    inferred_website = infer_website(services, preferred_service=main_service)
    inferred_repo = infer_repo(services, preferred_service=main_service)
    inferred_support = infer_support(services, preferred_service=main_service)
    inferred_docs = infer_docs(services, preferred_service=main_service)

    app_name = str(compose_data.get("name") or main_service or "")
    store_folder = str(params_app.get("store_folder") or "<store_folder>")

    icon_param = str(params_app.get("icon") or "").strip()
    if icon_param:
        icon = _replace_store_folder_placeholder(icon_param, store_folder)
    else:
        icon = f"{CDN_BASE}/{store_folder}/icon.png"

    screenshot_link = (
        params_app.get("screenshot_link")
        or params_app.get("screenshot_links")
    )
    screenshot_links = _as_list(
        screenshot_link,
        [
            f"{CDN_BASE}/{store_folder}/screenshot-1.png",
            f"{CDN_BASE}/{store_folder}/screenshot-2.png",
            f"{CDN_BASE}/{store_folder}/screenshot-3.png",
        ],
    )
    screenshot_links = [
        _replace_store_folder_placeholder(str(item), store_folder) for item in screenshot_links
    ]

    thumbnail = params_app.get("thumbnail")
    if thumbnail is None:
        thumbnail = f"{CDN_BASE}/{store_folder}/thumbnail.png"
    else:
        thumbnail = _replace_store_folder_placeholder(str(thumbnail), store_folder)

    architectures = _as_list(params_app.get("architectures"), ["amd64", "arm64"])

    author = str(params_app.get("author") or inferred_author or "")
    developer = str(params_app.get("developer") or "fromxiaobai")
    category = str(params_app.get("category") or inferred_category or "")

    title = params_app.get("title") or app_name
    tagline = params_app.get("tagline") or ""
    description = params_app.get("description") or ""
    release_notes = params_app.get("releaseNotes") or inferred_release_notes or ""

    app_block: Dict[str, Any] = {
        "title": title,
        "tagline": tagline,
        "description": description,
        "releaseNotes": release_notes,
        "category": category,
        "author": author,
        "developer": developer,
        "architectures": architectures,
        "icon": icon,
        "thumbnail": thumbnail,
        "screenshot_link": screenshot_links,
        "version": str(params_app.get("version") or inferred_version or ""),
        "updateAt": str(params_app.get("updateAt") or inferred_update_at or ""),
        "website": str(params_app.get("website") or inferred_website or ""),
        "repo": str(params_app.get("repo") or inferred_repo or ""),
        "support": str(params_app.get("support") or inferred_support or ""),
        "docs": str(params_app.get("docs") or inferred_docs or ""),
        "main": str(params_app.get("main") or main_service),
        "port_map": str(params_app.get("port_map") or inferred_port_map or ""),
        "scheme": str(params_app.get("scheme") or "http"),
        "index": str(params_app.get("index") or "/"),
    }
    if "tips" in params_app:
        app_block["tips"] = params_app.get("tips")

    data = copy.deepcopy(compose_data)
    existing_app_x = data.get("x-casaos")
    if not isinstance(existing_app_x, dict):
        existing_app_x = {}
    data["x-casaos"] = {**existing_app_x, **app_block}

    services_block = data.get("services") or {}
    for name, svc in services_block.items():
        if isinstance(svc, dict) and not str(svc.get("restart") or "").strip():
            svc["restart"] = "unless-stopped"
        if isinstance(svc, dict) and not str(svc.get("container_name") or "").strip():
            svc["container_name"] = name
        overrides = params_services.get(name)
        if isinstance(overrides, dict):
            existing_x = svc.get("x-casaos")
            if not isinstance(existing_x, dict):
                existing_x = {}
            svc["x-casaos"] = {**existing_x, **overrides}

    langs = languages or DEFAULT_LANGUAGES
    return build_xcasaos_template(data, langs)


def build_params_skeleton(compose_data: Dict[str, Any]) -> Dict[str, Any]:
    """Build a params.yml skeleton from a normal docker-compose.yml dict."""
    services = compose_data.get("services") or {}
    if not services:
        raise ComposeParseError("Compose file must include services")

    main_service = infer_main_service(services)
    inferred_port_map = infer_main_port(services.get(main_service, {}))
    inferred_category = infer_category(services, preferred_service=main_service)
    inferred_author = infer_author(services, preferred_service=main_service)
    inferred_version = infer_version(services, preferred_service=main_service)
    inferred_update_at = infer_update_at(services, preferred_service=main_service)
    inferred_release_notes = infer_release_notes(services, preferred_service=main_service)
    inferred_website = infer_website(services, preferred_service=main_service)
    inferred_repo = infer_repo(services, preferred_service=main_service)
    inferred_support = infer_support(services, preferred_service=main_service)
    inferred_docs = infer_docs(services, preferred_service=main_service)
    app_name = str(compose_data.get("name") or main_service or "")

    params: Dict[str, Any] = {
        "app": {
            "store_folder": "",
            "author": inferred_author,
            "developer": "fromxiaobai",
            "architectures": ["amd64", "arm64"],
            "title": app_name,
            "tagline": "",
            "description": "",
            "releaseNotes": inferred_release_notes,
            "category": inferred_category,
            "version": inferred_version,
            "updateAt": inferred_update_at,
            "website": inferred_website,
            "repo": inferred_repo,
            "support": inferred_support,
            "docs": inferred_docs,
            "main": main_service,
            "port_map": inferred_port_map,
            "scheme": "http",
            "index": "/",
        },
        "services": {},
    }

    services_params: Dict[str, Any] = {}
    for name, svc in services.items():
        envs = [{"container": item.container, "description": ""} for item in extract_envs(svc)]
        ports = [{"container": item.container, "description": ""} for item in extract_ports(svc)]
        volumes = [{"container": item.container, "description": ""} for item in extract_volumes(svc)]
        services_params[name] = {"envs": envs, "ports": ports, "volumes": volumes}
    params["services"] = services_params
    return params


def build_params_from_files(compose_path: Path) -> Dict[str, Any]:
    from .parser import load_compose_file

    compose_data = load_compose_file(compose_path)
    return build_params_skeleton(compose_data)


def build_template_from_files(
    compose_path: Path,
    params_path: Optional[Path] = None,
    languages: Optional[List[str]] = None,
) -> Dict[str, Any]:
    from .parser import load_compose_file

    compose_data = load_compose_file(compose_path)
    params = load_template_params(params_path)
    if params_path is None:
        logger.info("No params provided; using inferred defaults/placeholders.")
    return build_template_compose(compose_data, params=params, languages=languages)
