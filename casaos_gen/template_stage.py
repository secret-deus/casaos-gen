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

from .constants import CDN_BASE
from .i18n import DEFAULT_LANGUAGES
from .infer import infer_author, infer_category, infer_main_port, infer_main_service
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
        raise ValueError("Params file must be a YAML mapping")
    if "app" not in data:
        raise ValueError(
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
        raise ValueError("Compose file must include services")

    main_service = infer_main_service(services)
    inferred_port_map = infer_main_port(services.get(main_service, {}))
    inferred_category = infer_category(services, preferred_service=main_service)
    inferred_author = infer_author(services, preferred_service=main_service)

    app_name = str(compose_data.get("name") or main_service or "")
    store_folder = str(params_app.get("store_folder") or "<store_folder>")

    icon = str(
        params_app.get("icon")
        or f"{CDN_BASE}/{store_folder}/icon.png"
    )

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

    thumbnail = params_app.get("thumbnail")
    if thumbnail is None:
        thumbnail = f"{CDN_BASE}/{store_folder}/thumbnail.png"

    architectures = _as_list(params_app.get("architectures"), ["amd64", "arm64"])

    author = str(params_app.get("author") or inferred_author or "")
    developer = str(params_app.get("developer") or "fromxiaobai")
    category = str(params_app.get("category") or inferred_category or "")

    title = params_app.get("title") or app_name
    tagline = params_app.get("tagline") or ""
    description = params_app.get("description") or ""

    app_block: Dict[str, Any] = {
        "title": title,
        "tagline": tagline,
        "description": description,
        "category": category,
        "author": author,
        "developer": developer,
        "architectures": architectures,
        "icon": icon,
        "thumbnail": thumbnail,
        "screenshot_link": screenshot_links,
        "main": str(params_app.get("main") or main_service),
        "port_map": str(params_app.get("port_map") or inferred_port_map or ""),
        "scheme": str(params_app.get("scheme") or "http"),
        "index": str(params_app.get("index") or "/"),
    }

    data = copy.deepcopy(compose_data)
    data["x-casaos"] = app_block

    services_block = data.get("services") or {}
    for name, svc in services_block.items():
        overrides = params_services.get(name)
        if isinstance(overrides, dict):
            svc["x-casaos"] = overrides

    langs = languages or DEFAULT_LANGUAGES
    return build_xcasaos_template(data, langs)


def build_params_skeleton(compose_data: Dict[str, Any]) -> Dict[str, Any]:
    """Build a params.yml skeleton from a normal docker-compose.yml dict."""
    services = compose_data.get("services") or {}
    if not services:
        raise ValueError("Compose file must include services")

    main_service = infer_main_service(services)
    inferred_port_map = infer_main_port(services.get(main_service, {}))
    inferred_category = infer_category(services, preferred_service=main_service)
    inferred_author = infer_author(services, preferred_service=main_service)
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
            "category": inferred_category,
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
