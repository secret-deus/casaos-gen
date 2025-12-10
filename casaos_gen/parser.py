"""Parsing utilities to transform docker-compose files into CasaOS metadata."""
from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import yaml

from .models import AppMeta, CasaOSMeta, EnvItem, PortItem, ServiceMeta, VolumeItem

logger = logging.getLogger(__name__)

HTTP_FRIENDLY_PORTS = {"80", "443", "8080", "8000", "3000", "5000"}
PREFERRED_SERVICE_NAMES = ["web", "frontend", "app", "server", "service"]
CATEGORY_RULES = {
    "mysql": "Database",
    "mariadb": "Database",
    "postgres": "Database",
    "postgresql": "Database",
    "redis": "Database",
    "mongo": "Database",
    "nginx": "Web Server",
    "apache": "Web Server",
    "caddy": "Web Server",
    "ollama": "AI",
    "open-webui": "AI",
    "openwebui": "AI",
    "nextcloud": "Productivity",
    "immich": "Photos",
    "wordpress": "Web Server",
}


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


def infer_main_service(services: Dict[str, Dict]) -> str:
    if not services:
        raise ValueError("Compose file does not define any services")

    if len(services) == 1:
        return next(iter(services))

    def exposes_http_ports(service: Dict) -> bool:
        for host, container in collect_port_pairs(service):
            port = host or container
            if port and port in HTTP_FRIENDLY_PORTS:
                return True
        return False

    http_candidates = [name for name, svc in services.items() if exposes_http_ports(svc)]
    if http_candidates:
        logger.debug("Main service inferred from HTTP ports: %s", http_candidates[0])
        return http_candidates[0]

    for preferred in PREFERRED_SERVICE_NAMES:
        if preferred in services:
            logger.debug("Main service inferred from preferred name: %s", preferred)
            return preferred

    logger.debug("Main service defaulting to first entry")
    return next(iter(services))


def infer_main_port(service: Dict) -> str:
    for host, container in collect_port_pairs(service):
        port = host or container
        if port and port in HTTP_FRIENDLY_PORTS:
            return port

    for host, container in collect_port_pairs(service):
        port = host or container
        if port:
            return port

    return ""


def infer_category(services: Dict[str, Dict]) -> str:
    for svc in services.values():
        image = str(svc.get("image", "")).lower()
        for keyword, category in CATEGORY_RULES.items():
            if keyword in image:
                return category
    return "Utilities"


def infer_author(services: Dict[str, Dict]) -> str:
    for svc in services.values():
        image = svc.get("image")
        if not image or not isinstance(image, str):
            continue
        if "/" in image:
            author = image.split("/", 1)[0]
            if author:
                return author
    return "CasaOS User"


def collect_port_pairs(service: Dict) -> List[Tuple[Optional[str], Optional[str]]]:
    results: List[Tuple[Optional[str], Optional[str]]] = []
    for port in service.get("ports", []) or []:
        host, container = parse_port_entry(port)
        if host or container:
            results.append((host, container))
    return results


def parse_port_entry(entry) -> Tuple[Optional[str], Optional[str]]:
    def normalize(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = str(value)
        if "/" in value:
            value = value.split("/", 1)[0]
        value = value.strip()
        return value or None

    if isinstance(entry, int):
        text = str(entry)
        return text, text

    if isinstance(entry, str):
        cleaned = entry.strip()
        if "/" in cleaned:
            cleaned = cleaned.split("/", 1)[0]
        parts = cleaned.split(":")
        # Support ip:host:container, host:container, container
        if len(parts) >= 3:
            host = parts[-2]
            container = parts[-1]
        elif len(parts) == 2:
            host, container = parts
        else:
            host, container = None, parts[0]
        return normalize(host), normalize(container)

    if isinstance(entry, dict):
        host = entry.get("published") or entry.get("host")
        container = entry.get("target") or entry.get("containerPort")
        return normalize(host), normalize(container)

    return None, None


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
    category = infer_category(services_copy)
    author = infer_author(services_copy)

    app_meta = AppMeta(
        category=category,
        author=author,
        main=main_service,
        port_map=port_map,
    )

    svc_meta: Dict[str, ServiceMeta] = {}
    for name, svc in services_copy.items():
        svc_meta[name] = ServiceMeta(
            envs=extract_envs(svc),
            ports=extract_ports(svc),
            volumes=extract_volumes(svc),
        )

    return CasaOSMeta(app=app_meta, services=svc_meta)

