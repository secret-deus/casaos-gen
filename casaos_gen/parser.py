"""Parsing utilities to transform docker-compose files into CasaOS metadata."""

from __future__ import annotations



import copy
import logging
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .constants import (
    STORE_FOLDER_PLACEHOLDER,
    build_cdn_icon_url,
    build_cdn_screenshot_urls,
    build_cdn_thumbnail_url,
)
from .infer import (
    collect_port_pairs,
    infer_author,
    infer_category,
    infer_main_port,
    infer_main_service,
)
from .models import AppMeta, CasaOSMeta, EnvItem, PortItem, ServiceMeta, VolumeItem



logger = logging.getLogger(__name__)



def load_compose_file(path: Path) -> Dict:

    """Load a docker-compose YAML file into a python dictionary."""

    if not path.exists():

        raise FileNotFoundError(f"Compose file not found: {path}")



    logger.info("Loading compose file: %s", path)

    with path.open("r", encoding="utf-8") as handle:

        data = yaml.safe_load(handle) or {}

    if not isinstance(data, dict):

        raise ValueError("Compose file did not produce a mapping")

    return data





def extract_envs(service: Dict) -> List[EnvItem]:

    env_data = service.get("environment", []) or []

    items: List[EnvItem] = []

    if isinstance(env_data, dict):

        iterable = env_data.items()

    else:

        iterable = []

        for entry in env_data:

            if isinstance(entry, str):

                key, _, _ = entry.partition("=")

                iterable.append((key.strip(), ""))

            elif isinstance(entry, dict):

                for key, value in entry.items():

                    iterable.append((str(key), value))



    for key, _ in iterable:

        key = str(key).strip()

        if key:

            items.append(EnvItem(container=key))

    return items





def extract_ports(service: Dict) -> List[PortItem]:

    items: List[PortItem] = []

    for _, container in collect_port_pairs(service):

        if container:

            items.append(PortItem(container=container))

    return items





def extract_volumes(service: Dict) -> List[VolumeItem]:

    volumes = service.get("volumes", []) or []

    items: List[VolumeItem] = []

    for entry in volumes:

        container_path = parse_volume_entry(entry)

        if container_path:

            items.append(VolumeItem(container=container_path))

    return items





def parse_volume_entry(entry) -> Optional[str]:

    if isinstance(entry, str):

        cleaned = entry.strip()

        if not cleaned:

            return None

        parts = cleaned.split(":")

        if len(parts) >= 2:

            return parts[1]

        return parts[0]



    if isinstance(entry, dict):

        target = entry.get("target") or entry.get("container")

        return str(target).strip() if target else None

    return None





def build_casaos_meta(compose_data: Dict) -> CasaOSMeta:

    services = compose_data.get("services") or {}

    if not services:

        raise ValueError("Compose file must include services")



    services_copy = copy.deepcopy(services)

    main_service = infer_main_service(services_copy)

    port_map = infer_main_port(services_copy.get(main_service, {}))

    category = infer_category(services_copy, preferred_service=main_service)

    author = infer_author(services_copy, preferred_service=main_service)

    title = str(compose_data.get("name") or main_service or "").strip() or main_service
    tagline = f"{title} on CasaOS"
    description = (
        f"{title} is a self-hosted application stack deployed via Docker Compose.\n\n"
        "Key Features:\n"
        "- Runs multiple services as a single stack.\n"
        "- Supports persistent storage and environment configuration.\n"
        "- Ready to be imported and managed in CasaOS.\n"
    )

    # Default to a predictable CDN URL shape so users can either:
    # - pass params.yml app.store_folder to generate real links, or
    # - keep the placeholder and replace it later.
    icon = build_cdn_icon_url(STORE_FOLDER_PLACEHOLDER)
    thumbnail = build_cdn_thumbnail_url(STORE_FOLDER_PLACEHOLDER)
    screenshot_links = build_cdn_screenshot_urls(STORE_FOLDER_PLACEHOLDER)

    app_meta = AppMeta(

        title=title,
        tagline=tagline,
        description=description,
        category=category,

        author=author,

        main=main_service,

        port_map=port_map,
        icon=icon,
        thumbnail=thumbnail,
        screenshot_link=screenshot_links,

    )



    svc_meta: Dict[str, ServiceMeta] = {}

    for name, svc in services_copy.items():

        svc_meta[name] = ServiceMeta(

            envs=extract_envs(svc),

            ports=extract_ports(svc),

            volumes=extract_volumes(svc),

        )



    return CasaOSMeta(app=app_meta, services=svc_meta)







def _normalize_multilang(value, languages: List[str]) -> Dict[str, str]:
    if isinstance(value, dict):
        return {lang: str(value.get(lang, "") or "") for lang in languages}
    if value is None:
        return {lang: "" for lang in languages}
    text = str(value)
    return {lang: text for lang in languages}


def build_xcasaos_template(compose_data: Dict, languages: List[str]) -> Dict:
    """Return a compose document with x-casaos blocks shaped to the template.

    - Non x-casaos data is preserved.
    - x-casaos descriptions are normalized to multi-lang dicts with all languages present.
    - If a description is missing, an empty string is used for every locale.
    """
    data = copy.deepcopy(compose_data)
    services = data.get("services") or {}

    # App-level x-casaos
    app_block = data.get("x-casaos") or {}
    app_multis = {}
    for field in ("title", "tagline", "description"):
        app_multis[field] = _normalize_multilang(app_block.get(field), languages)
    app_singles_defaults = {
        "category": "",
        "author": "",
        "developer": "fromxiaobai",
        "architectures": ["amd64", "arm64"],
        "icon": "",
        "thumbnail": "",
        "screenshot_link": [],
        "index": "/",
        "main": "",
        "port_map": "",
        "scheme": "http",
    }
    app_singles = {}
    for field, default in app_singles_defaults.items():
        app_singles[field] = app_block.get(field, default)
    data["x-casaos"] = {**app_multis, **app_singles}

    for name, svc in services.items():
        x_block = svc.get("x-casaos") or {}

        def normalize_items(kind: str, fallback_builder):
            raw_items = x_block.get(kind)
            if raw_items:
                normalized = []
                for entry in raw_items:
                    container = entry.get("container")
                    desc = _normalize_multilang(entry.get("description"), languages)
                    normalized.append({"container": container, "description": desc})
                return normalized
            normalized = []
            for item in fallback_builder(svc):
                normalized.append({"container": item.container, "description": _normalize_multilang("", languages)})
            return normalized

        envs = normalize_items("envs", extract_envs)
        ports = normalize_items("ports", extract_ports)
        volumes = normalize_items("volumes", extract_volumes)
        svc["x-casaos"] = {"envs": envs, "ports": ports, "volumes": volumes}

    data["services"] = services
    return data
