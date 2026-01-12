"""Inference helpers for CasaOS metadata."""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

HTTP_FRIENDLY_PORTS = {"80", "443", "8080", "8000", "3000", "5000"}
PREFERRED_SERVICE_NAMES = ["web", "frontend", "app", "server", "service"]
_PORT_VAR_DEFAULT_RE = re.compile(r"^\$\{[^}:]+(?:(?::-)|-)(\d+)\}$")

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


def normalize_port_value(value: Optional[str]) -> Optional[str]:
    """Return a concrete numeric port if it can be determined.

    This keeps inference stable for compose patterns like:
    - "${WEB_PORT:-8888}:80"
    - "${WEB_PORT-8888}:80"
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return text
    match = _PORT_VAR_DEFAULT_RE.match(text)
    if match:
        return match.group(1)
    return None


def parse_port_entry(entry) -> Tuple[Optional[str], Optional[str]]:
    def normalize(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = str(value)
        if "/" in value:
            value = value.split("/", 1)[0]
        value = value.strip()
        return value or None

    def split_mapping(value: str) -> Tuple[Optional[str], str]:
        """Split 'ports' mapping while ignoring ':' inside ${...} and [IPv6]."""
        if not value:
            return None, ""
        colon_positions: List[int] = []
        brace_depth = 0
        bracket_depth = 0
        index = 0
        while index < len(value):
            ch = value[index]
            if ch == "$" and index + 1 < len(value) and value[index + 1] == "{":
                brace_depth += 1
                index += 2
                continue
            if ch == "}" and brace_depth:
                brace_depth -= 1
            elif ch == "[":
                bracket_depth += 1
            elif ch == "]" and bracket_depth:
                bracket_depth -= 1
            elif ch == ":" and brace_depth == 0 and bracket_depth == 0:
                colon_positions.append(index)
            index += 1

        if not colon_positions:
            return None, value
        if len(colon_positions) == 1:
            pos = colon_positions[0]
            return value[:pos], value[pos + 1 :]
        # ip:host:container or similar; keep the last two segments
        host_start = colon_positions[-2] + 1
        host_end = colon_positions[-1]
        return value[host_start:host_end], value[host_end + 1 :]

    if isinstance(entry, int):
        text = str(entry)
        return text, text

    if isinstance(entry, str):
        cleaned = entry.strip()
        if "/" in cleaned:
            cleaned = cleaned.split("/", 1)[0]
        host, container = split_mapping(cleaned)
        return normalize(host), normalize(container)

    if isinstance(entry, dict):
        host = entry.get("published") or entry.get("host")
        container = entry.get("target") or entry.get("containerPort")
        return normalize(host), normalize(container)

    return None, None


def collect_port_pairs(service: Dict) -> List[Tuple[Optional[str], Optional[str]]]:
    results: List[Tuple[Optional[str], Optional[str]]] = []
    for port in service.get("ports", []) or []:
        host, container = parse_port_entry(port)
        if host or container:
            results.append((host, container))
    return results


def infer_main_service(services: Dict[str, Dict]) -> str:
    if not services:
        raise ValueError("Compose file does not define any services")

    if len(services) == 1:
        return next(iter(services))

    def exposes_http_ports(service: Dict) -> bool:
        for host, container in collect_port_pairs(service):
            host_port = normalize_port_value(host)
            container_port = normalize_port_value(container)
            if (container_port and container_port in HTTP_FRIENDLY_PORTS) or (
                host_port and host_port in HTTP_FRIENDLY_PORTS
            ):
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
        host_port = normalize_port_value(host)
        container_port = normalize_port_value(container)
        if container_port and container_port in HTTP_FRIENDLY_PORTS:
            return host_port or container_port
        if host_port and host_port in HTTP_FRIENDLY_PORTS:
            return host_port

    for host, container in collect_port_pairs(service):
        host_port = normalize_port_value(host)
        container_port = normalize_port_value(container)
        if host_port:
            return host_port
        if container_port:
            return container_port

    return ""


def infer_category(services: Dict[str, Dict], preferred_service: Optional[str] = None) -> str:
    if preferred_service and preferred_service in services:
        image = str(services[preferred_service].get("image", "")).lower()
        for keyword, category in CATEGORY_RULES.items():
            if keyword in image:
                return category

    for svc in services.values():
        image = str(svc.get("image", "")).lower()
        for keyword, category in CATEGORY_RULES.items():
            if keyword in image:
                return category
    return "Utilities"


def infer_author(services: Dict[str, Dict], preferred_service: Optional[str] = None) -> str:
    if preferred_service and preferred_service in services:
        image = services[preferred_service].get("image")
        if image and isinstance(image, str) and "/" in image:
            author = image.split("/", 1)[0]
            if author:
                return author

    for svc in services.values():
        image = svc.get("image")
        if not image or not isinstance(image, str):
            continue
        if "/" in image:
            author = image.split("/", 1)[0]
            if author:
                return author
    return "CasaOS User"
