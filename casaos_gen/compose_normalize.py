"""Post-processing helpers for CasaOS AppStore-style compose templates.

This module focuses on rewriting *service runtime fields* (ports/volumes) and
filling predictable app media links (icon/thumbnail/screenshot_link) when they
are missing.

It intentionally does NOT touch x-casaos descriptions/content (beyond the media
links) so you can run it on already-generated YAML without losing metadata.
"""

from __future__ import annotations

import copy
import logging
import re
from typing import Any, Dict, Optional, Tuple

from .constants import (
    STORE_FOLDER_PLACEHOLDER,
    build_app_data_root,
    build_cdn_icon_url,
    build_cdn_screenshot_urls,
    build_cdn_thumbnail_url,
)
from .infer import parse_port_entry

logger = logging.getLogger(__name__)

_SANITIZE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


def normalize_compose_for_appstore(
    compose_data: Dict[str, Any],
    store_folder: Optional[str] = None,
    app_id_var: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a deep-copied compose dict normalized for CasaOS AppStore templates.

    - Ports are converted into long syntax (target/published/protocol).
    - Volumes are converted into bind mounts under /DATA/AppData/$AppID/...
    - Top-level named volume definitions are removed if unused after conversion.
    - App media links are filled (only if missing/empty) under x-casaos.
    """
    data: Dict[str, Any] = copy.deepcopy(compose_data)
    _ensure_app_media_links(data, store_folder=store_folder)

    services = data.get("services") or {}
    if isinstance(services, dict):
        app_data_root = build_app_data_root(app_id_var)
        for name, svc in services.items():
            if not isinstance(svc, dict):
                continue
            _normalize_service_ports(svc)
            _normalize_service_volumes(name, svc, app_data_root=app_data_root)
    data["services"] = services

    _drop_top_level_volumes_if_unused(data)
    return data


def _ensure_app_media_links(data: Dict[str, Any], store_folder: Optional[str]) -> None:
    x_casaos = data.get("x-casaos")
    if not isinstance(x_casaos, dict):
        return

    folder = (store_folder or "").strip() or _infer_store_folder(data) or STORE_FOLDER_PLACEHOLDER

    if not str(x_casaos.get("icon") or "").strip():
        x_casaos["icon"] = build_cdn_icon_url(folder)
    if not str(x_casaos.get("thumbnail") or "").strip():
        x_casaos["thumbnail"] = build_cdn_thumbnail_url(folder)

    screenshots = x_casaos.get("screenshot_link")
    if not isinstance(screenshots, list) or not any(str(item).strip() for item in screenshots):
        x_casaos["screenshot_link"] = build_cdn_screenshot_urls(folder)


def _infer_store_folder(data: Dict[str, Any]) -> str:
    x_casaos = data.get("x-casaos")
    if isinstance(x_casaos, dict):
        title = x_casaos.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        if isinstance(title, dict):
            for key in ("en_US", "en_GB", "zh_CN"):
                candidate = title.get(key)
                if candidate and str(candidate).strip():
                    return str(candidate).strip()
            for candidate in title.values():
                if candidate and str(candidate).strip():
                    return str(candidate).strip()

    name = data.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return ""


def _normalize_service_ports(service: Dict[str, Any]) -> None:
    raw_ports = service.get("ports")
    if not raw_ports:
        return
    if not isinstance(raw_ports, list):
        return

    normalized = []
    for entry in raw_ports:
        if isinstance(entry, dict):
            normalized.append(_normalize_port_mapping(entry))
            continue
        if isinstance(entry, int):
            normalized.append({"target": entry, "protocol": "tcp"})
            continue
        if isinstance(entry, str):
            mapping = _normalize_port_string(entry)
            if mapping is not None:
                normalized.append(mapping)
            continue
    service["ports"] = normalized


def _normalize_port_mapping(entry: Dict[str, Any]) -> Dict[str, Any]:
    target = entry.get("target")
    if target is None:
        target = entry.get("containerPort")
    if target is None:
        target = entry.get("container")
    if target is None:
        return dict(entry)

    published = entry.get("published")
    if published is None:
        published = entry.get("host")

    out: Dict[str, Any] = dict(entry)
    out["target"] = _as_int_if_digits(target)
    if published is not None and str(published).strip():
        out["published"] = str(published).strip()
    else:
        out.pop("published", None)
    out.pop("host", None)
    out.setdefault("protocol", "tcp")
    return out


def _normalize_port_string(entry: str) -> Optional[Dict[str, Any]]:
    cleaned = entry.strip()
    if not cleaned:
        return None
    protocol = _extract_port_protocol(cleaned) or "tcp"
    host, container = parse_port_entry(cleaned)
    if not container and host:
        container = host
        host = None
    if not container:
        return None

    out: Dict[str, Any] = {"target": _as_int_if_digits(container), "protocol": protocol}
    if host:
        out["published"] = str(host)
    return out


def _extract_port_protocol(entry: str) -> Optional[str]:
    if "/" not in entry:
        return None
    proto = entry.rsplit("/", 1)[1].strip().lower()
    if not proto:
        return None
    if proto in {"tcp", "udp", "sctp"}:
        return proto
    return None


def _normalize_service_volumes(service_name: str, service: Dict[str, Any], app_data_root: str) -> None:
    raw_volumes = service.get("volumes")
    if not raw_volumes:
        return
    if not isinstance(raw_volumes, list):
        return

    normalized = []
    for entry in raw_volumes:
        if isinstance(entry, dict):
            volume = _normalize_volume_mapping(service_name, entry, app_data_root)
            if volume is not None:
                normalized.append(volume)
            continue
        if isinstance(entry, str):
            volume = _normalize_volume_string(service_name, entry, app_data_root)
            if volume is not None:
                normalized.append(volume)
            continue
    service["volumes"] = normalized


def _normalize_volume_mapping(
    service_name: str, entry: Dict[str, Any], app_data_root: str
) -> Optional[Dict[str, Any]]:
    target = entry.get("target") or entry.get("container") or entry.get("destination")
    if not target or not str(target).strip():
        return None

    # If source looks like a named volume, keep it as the AppData subdir name.
    source_value = entry.get("source") or entry.get("src") or entry.get("volume")
    subdir = ""
    if isinstance(source_value, str) and _looks_like_named_volume(source_value):
        subdir = source_value.strip()
    else:
        subdir = _derive_appdata_subdir(service_name, str(target))

    out: Dict[str, Any] = {
        "type": "bind",
        "source": f"{app_data_root}/{subdir}",
        "target": str(target),
        "bind": {"create_host_path": True},
    }
    if bool(entry.get("read_only")):
        out["read_only"] = True
    return out


def _normalize_volume_string(service_name: str, entry: str, app_data_root: str) -> Optional[Dict[str, Any]]:
    source, target, mode = _parse_volume_spec(entry)
    if target is None:
        return None
    if not str(target).strip():
        return None

    if source and _looks_like_named_volume(source):
        subdir = source.strip()
    else:
        subdir = _derive_appdata_subdir(service_name, str(target))

    out: Dict[str, Any] = {
        "type": "bind",
        "source": f"{app_data_root}/{subdir}",
        "target": str(target),
        "bind": {"create_host_path": True},
    }
    if mode and _is_read_only_mode(mode):
        out["read_only"] = True
    return out


def _parse_volume_spec(entry: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    cleaned = entry.strip()
    if not cleaned:
        return None, None, None

    parts = cleaned.split(":")
    if len(parts) == 1:
        return None, cleaned, None
    if len(parts) >= 3 and _looks_like_volume_mode(parts[-1]):
        mode = parts[-1]
        target = parts[-2]
        source = ":".join(parts[:-2])
        return source, target, mode

    target = parts[-1]
    source = ":".join(parts[:-1])
    return source, target, None


def _looks_like_volume_mode(value: str) -> bool:
    text = value.strip().lower()
    if not text:
        return False
    # Common compose short-syntax volume modes.
    if text in {"ro", "rw", "z", "Z", "cached", "delegated", "consistent"}:
        return True
    # Combined modes like "ro,Z"
    parts = [part.strip() for part in text.split(",") if part.strip()]
    return any(part in {"ro", "rw", "z", "Z"} for part in parts)


def _is_read_only_mode(value: str) -> bool:
    parts = [part.strip().lower() for part in value.split(",") if part.strip()]
    return "ro" in parts


def _looks_like_named_volume(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if text.startswith((".", "/", "~")):
        return False
    if text.startswith("${") or text.startswith("$"):
        return False
    if "/" in text or "\\" in text:
        return False
    # Windows drive prefix (e.g. C:\)
    if len(text) >= 2 and text[1] == ":":
        return False
    return True


def _derive_appdata_subdir(service_name: str, target: str) -> str:
    cleaned_target = str(target).strip()
    last_segment = cleaned_target.rstrip("/").split("/")[-1] if cleaned_target else ""
    last_segment = last_segment or service_name

    safe_service = _sanitize_segment(service_name)
    safe_segment = _sanitize_segment(last_segment)
    if not safe_segment:
        safe_segment = safe_service or "data"
    return f"{safe_service}-{safe_segment}" if safe_service else safe_segment


def _sanitize_segment(value: str) -> str:
    candidate = _SANITIZE_SEGMENT_RE.sub("-", str(value).strip())
    candidate = candidate.strip("-._")
    return candidate


def _as_int_if_digits(value: Any) -> Any:
    text = str(value).strip()
    return int(text) if text.isdigit() else value


def _drop_top_level_volumes_if_unused(data: Dict[str, Any]) -> None:
    volumes = data.get("volumes")
    if not isinstance(volumes, dict) or not volumes:
        return

    referenced = set()
    services = data.get("services") or {}
    if isinstance(services, dict):
        for svc in services.values():
            if not isinstance(svc, dict):
                continue
            for entry in svc.get("volumes") or []:
                if isinstance(entry, str):
                    source, _, _ = _parse_volume_spec(entry)
                    if source and _looks_like_named_volume(source):
                        referenced.add(source.strip())
                elif isinstance(entry, dict):
                    if str(entry.get("type") or "").strip() not in {"", "volume"}:
                        continue
                    source = entry.get("source")
                    if isinstance(source, str) and _looks_like_named_volume(source):
                        referenced.add(source.strip())

    if not referenced:
        data.pop("volumes", None)
        return

    for name in list(volumes.keys()):
        if name not in referenced:
            volumes.pop(name, None)
    if not volumes:
        data.pop("volumes", None)

