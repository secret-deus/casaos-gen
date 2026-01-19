"""Post-processing helpers for CasaOS AppStore-style compose templates.

This module focuses on rewriting *service runtime fields* (ports/volumes) and
filling predictable app media links (icon/thumbnail/screenshot_link) when they
are missing.

Additionally, it applies lightweight AppStore conventions that are safe to
auto-fix (restart policy defaults, container_name defaults, and keeping
top-level name/x-casaos.main/port_map consistent when present). It intentionally
does NOT rewrite x-casaos descriptions.
"""

from __future__ import annotations

import copy
import hashlib
import logging
import random
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
    - Service names are lowercased (and depends_on updated) when safe.
    - restart/container_name defaults are applied when missing.
    - If x-casaos exists, ensure name/main/port_map stay consistent.
    """
    data: Dict[str, Any] = copy.deepcopy(compose_data)
    _ensure_app_media_links(data, store_folder=store_folder)

    services = data.get("services") or {}
    if isinstance(services, dict):
        services = _lowercase_service_names(data)
        main_service = _ensure_compose_name_and_main(data)
        app_data_root = build_app_data_root(app_id_var)
        used_appdata_sources: set[str] = set()
        for name, svc in services.items():
            if not isinstance(svc, dict):
                continue
            _ensure_service_defaults(name, svc)
            _ensure_image_tag(name, svc)
            _normalize_service_environment(svc)
            _normalize_service_ports(svc)
            _normalize_service_volumes(
                name,
                svc,
                app_data_root=app_data_root,
                used_appdata_sources=used_appdata_sources,
            )
        if main_service:
            _ensure_main_service_port_map(data, main_service)
    data["services"] = services

    _drop_top_level_volumes_if_unused(data)
    return data


def _lowercase_service_names(data: Dict[str, Any]) -> Dict[str, Any]:
    services = data.get("services") or {}
    if not isinstance(services, dict) or not services:
        return services if isinstance(services, dict) else {}

    normalized: Dict[str, Any] = {}
    rename_map: Dict[str, str] = {}
    collisions: Dict[str, list[str]] = {}

    for name, svc in services.items():
        if not isinstance(name, str):
            normalized[name] = svc
            continue
        lowered = name.strip().lower()
        if not lowered:
            normalized[name] = svc
            continue
        if lowered in normalized and name != lowered:
            collisions.setdefault(lowered, []).append(name)
            continue
        normalized[lowered] = svc
        if name != lowered:
            rename_map[name] = lowered

    if collisions:
        logger.warning("Service name lowercasing skipped due to collisions: %s", collisions)
        return services

    if rename_map:
        _rewrite_depends_on(normalized, rename_map)
        data["services"] = normalized
    return normalized


def _rewrite_depends_on(services: Dict[str, Any], rename_map: Dict[str, str]) -> None:
    for svc in services.values():
        if not isinstance(svc, dict):
            continue
        depends = svc.get("depends_on")
        if isinstance(depends, list):
            svc["depends_on"] = [rename_map.get(str(item), item) for item in depends]
            continue
        if isinstance(depends, dict):
            rewritten = {}
            for key, value in depends.items():
                new_key = rename_map.get(str(key), key)
                rewritten[new_key] = value
            svc["depends_on"] = rewritten


def _ensure_compose_name_and_main(data: Dict[str, Any]) -> str:
    services = data.get("services") or {}
    service_names = list(services.keys()) if isinstance(services, dict) else []

    x_casaos = data.get("x-casaos")
    if not isinstance(x_casaos, dict):
        x_casaos = None

    candidates = []
    if x_casaos and isinstance(x_casaos.get("main"), str) and x_casaos.get("main").strip():
        candidates.append(x_casaos["main"])
    if isinstance(data.get("name"), str) and str(data.get("name")).strip():
        candidates.append(str(data.get("name")))
    if service_names:
        candidates.append(str(service_names[0]))

    main = next((str(item).strip() for item in candidates if str(item).strip()), "")
    main = main.lower()
    if not main:
        return ""

    if isinstance(services, dict) and main not in services:
        logger.warning("Main service '%s' not found; defaulting to first service.", main)
        main = str(service_names[0]).strip().lower() if service_names else ""
        if not main:
            return ""

    data["name"] = main
    if x_casaos is not None:
        x_casaos["main"] = main
        data["x-casaos"] = x_casaos
    return main


def _ensure_service_defaults(service_name: str, service: Dict[str, Any]) -> None:
    if not str(service.get("restart") or "").strip():
        service["restart"] = "unless-stopped"
    if not str(service.get("container_name") or "").strip():
        service["container_name"] = service_name


def _ensure_image_tag(service_name: str, service: Dict[str, Any]) -> None:
    image = service.get("image")
    if not isinstance(image, str):
        return
    cleaned = image.strip()
    if not cleaned:
        return
    if "@" in cleaned:
        return
    if not _image_has_tag(cleaned):
        logger.warning("Service %s image has no tag; defaulting to ':latest'.", service_name)
        service["image"] = f"{cleaned}:latest"
        return
    if cleaned.rsplit(":", 1)[-1].lower() == "latest":
        logger.warning("Service %s image uses ':latest'; prefer a pinned version.", service_name)


def _image_has_tag(image: str) -> bool:
    # If the final ':' appears after the final '/', treat it as a tag separator.
    last_slash = image.rfind("/")
    last_colon = image.rfind(":")
    return last_colon > last_slash


def _normalize_service_environment(service: Dict[str, Any]) -> None:
    env = service.get("environment")
    if isinstance(env, dict):
        _normalize_env_mapping(env)
        return
    if isinstance(env, list):
        service["environment"] = _normalize_env_list(env)


def _normalize_env_mapping(env: Dict[str, Any]) -> None:
    for key, replacement in (("TZ", "$TZ"), ("PUID", "$PUID"), ("PGID", "$PGID")):
        if key in env:
            env[key] = replacement


def _normalize_env_list(env: list[Any]) -> list[Any]:
    normalized: list[Any] = []
    for entry in env:
        if not isinstance(entry, str) or "=" not in entry:
            normalized.append(entry)
            continue
        key, _, value = entry.partition("=")
        key = key.strip()
        if key == "TZ":
            normalized.append("TZ=$TZ")
            continue
        if key == "PUID":
            normalized.append("PUID=$PUID")
            continue
        if key == "PGID":
            normalized.append("PGID=$PGID")
            continue
        normalized.append(entry)
    return normalized


def _ensure_main_service_port_map(data: Dict[str, Any], main_service: str) -> None:
    x_casaos = data.get("x-casaos")
    if not isinstance(x_casaos, dict):
        return
    services = data.get("services")
    if not isinstance(services, dict):
        return
    service = services.get(main_service)
    if not isinstance(service, dict):
        return
    ports = service.get("ports")
    if not isinstance(ports, list) or not ports:
        return

    primary = next((entry for entry in ports if isinstance(entry, dict)), None)
    if not isinstance(primary, dict):
        return

    target = primary.get("target")
    target_text = str(target).strip() if target is not None else ""
    published = str(primary.get("published") or "").strip()

    requested_port_map = str(x_casaos.get("port_map") or "").strip()
    if requested_port_map and requested_port_map != published:
        if requested_port_map.isdigit():
            port_value = int(requested_port_map)
            if 0 < port_value < 65536:
                primary["published"] = requested_port_map
                x_casaos["port_map"] = requested_port_map
                return
        else:
            primary["published"] = requested_port_map
            x_casaos["port_map"] = requested_port_map
            return

    if published and not published.isdigit():
        # Respect template variables like "$PORT" and keep x-casaos in sync.
        x_casaos["port_map"] = published
        return

    used_ports = _collect_published_ports(services)
    seed = hashlib.sha256(f"{main_service}::port_map".encode("utf-8")).hexdigest()
    rng = random.Random(int(seed[:8], 16))

    if (
        (not published)
        or (published == target_text)
        or (not published.isdigit())
        or int(published) <= 0
        or int(published) >= 30000
    ):
        allocated = _allocate_random_port(rng, used_ports)
        primary["published"] = str(allocated)
        published = str(allocated)

    x_casaos["port_map"] = published


def _collect_published_ports(services: Dict[str, Any]) -> set[int]:
    used: set[int] = set()
    for svc in services.values():
        if not isinstance(svc, dict):
            continue
        ports = svc.get("ports")
        if not isinstance(ports, list):
            continue
        for entry in ports:
            if not isinstance(entry, dict):
                continue
            published = entry.get("published")
            if published is None:
                continue
            text = str(published).strip()
            if text.isdigit():
                used.add(int(text))
    return used


def _allocate_random_port(rng: random.Random, used_ports: set[int]) -> int:
    # CasaOS AppStore templates typically use a random port < 30000.
    for _ in range(2000):
        candidate = rng.randint(20000, 29999)
        if candidate not in used_ports:
            used_ports.add(candidate)
            return candidate
    # Fallback: linear probe (still < 30000)
    for candidate in range(20000, 30000):
        if candidate not in used_ports:
            used_ports.add(candidate)
            return candidate
    return 20000


def _ensure_app_media_links(data: Dict[str, Any], store_folder: Optional[str]) -> None:
    x_casaos = data.get("x-casaos")
    if not isinstance(x_casaos, dict):
        return

    folder = (store_folder or "").strip() or _infer_store_folder(data) or STORE_FOLDER_PLACEHOLDER

    icon_value = str(x_casaos.get("icon") or "")
    if STORE_FOLDER_PLACEHOLDER in icon_value:
        x_casaos["icon"] = icon_value.replace(STORE_FOLDER_PLACEHOLDER, folder)
    elif not icon_value.strip():
        x_casaos["icon"] = build_cdn_icon_url(folder)

    thumbnail_value = str(x_casaos.get("thumbnail") or "")
    if STORE_FOLDER_PLACEHOLDER in thumbnail_value:
        x_casaos["thumbnail"] = thumbnail_value.replace(STORE_FOLDER_PLACEHOLDER, folder)
    elif not thumbnail_value.strip():
        x_casaos["thumbnail"] = build_cdn_thumbnail_url(folder)

    screenshots = x_casaos.get("screenshot_link")
    if isinstance(screenshots, list):
        replaced = []
        changed = False
        for item in screenshots:
            text = "" if item is None else str(item)
            if STORE_FOLDER_PLACEHOLDER in text:
                next_text = text.replace(STORE_FOLDER_PLACEHOLDER, folder)
                changed = changed or next_text != text
                replaced.append(next_text)
            else:
                replaced.append(text)
        if changed:
            x_casaos["screenshot_link"] = replaced
            screenshots = replaced

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
            normalized.append(
                {
                    "target": entry,
                    "published": str(entry),
                    "protocol": "tcp",
                }
            )
            continue
        if isinstance(entry, str):
            mapping = _normalize_port_string(entry)
            if mapping is not None:
                normalized.append(mapping)
            continue
    service["ports"] = normalized


def _normalize_port_mapping(entry: Dict[str, Any]) -> Dict[str, Any]:
    # Some YAML parsers can load a short-syntax port mapping like `- 880:8080`
    # as a 1-item dict `{880: 8080}`. Convert that to long syntax.
    if len(entry) == 1:
        host, container = next(iter(entry.items()))
        host_text = str(host).strip()
        container_text = str(container).strip()
        if container_text:
            return {
                "target": _as_int_if_digits(container_text),
                "published": host_text or container_text,
                "protocol": "tcp",
            }

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

    protocol = str(entry.get("protocol") or "").strip().lower() or "tcp"
    target_value = _as_int_if_digits(target)
    published_value = str(published).strip() if published is not None and str(published).strip() else str(target_value)

    out: Dict[str, Any] = {
        "target": target_value,
        "published": published_value,
        "protocol": protocol,
    }
    # Preserve optional "mode" if provided.
    if "mode" in entry and str(entry.get("mode") or "").strip():
        out["mode"] = entry.get("mode")
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

    target_value = _as_int_if_digits(container)
    published_value = str(host).strip() if host else str(target_value)
    return {
        "target": target_value,
        "published": published_value,
        "protocol": protocol,
    }


def _extract_port_protocol(entry: str) -> Optional[str]:
    if "/" not in entry:
        return None
    proto = entry.rsplit("/", 1)[1].strip().lower()
    if not proto:
        return None
    if proto in {"tcp", "udp", "sctp"}:
        return proto
    return None


def _normalize_service_volumes(
    service_name: str,
    service: Dict[str, Any],
    app_data_root: str,
    used_appdata_sources: set[str],
) -> None:
    raw_volumes = service.get("volumes")
    if not raw_volumes:
        return
    if not isinstance(raw_volumes, list):
        return

    normalized = []
    for entry in raw_volumes:
        if isinstance(entry, dict):
            volume = _normalize_volume_mapping(
                service_name,
                entry,
                app_data_root,
                used_appdata_sources,
            )
            if volume is not None:
                normalized.append(volume)
            continue
        if isinstance(entry, str):
            volume = _normalize_volume_string(
                service_name,
                entry,
                app_data_root,
                used_appdata_sources,
            )
            if volume is not None:
                normalized.append(volume)
            continue
    service["volumes"] = normalized


def _normalize_volume_mapping(
    service_name: str,
    entry: Dict[str, Any],
    app_data_root: str,
    used_appdata_sources: set[str],
) -> Optional[Dict[str, Any]]:
    target = entry.get("target") or entry.get("container") or entry.get("destination")
    if not target or not str(target).strip():
        return None

    source_value = entry.get("source") or entry.get("src") or entry.get("volume")
    target_text = str(target).strip()

    if isinstance(source_value, str) and _is_explicit_bind_source(source_value):
        out: Dict[str, Any] = {"type": "bind", "source": source_value.strip(), "target": target_text}
        if bool(entry.get("read_only")):
            out["read_only"] = True
        return out

    source_path = _build_appdata_bind_source(
        service_name=service_name,
        target=target_text,
        app_data_root=app_data_root,
        used_appdata_sources=used_appdata_sources,
        original_source=str(source_value) if isinstance(source_value, str) else None,
    )
    out = {"type": "bind", "source": source_path, "target": target_text}
    if bool(entry.get("read_only")):
        out["read_only"] = True
    return out


def _normalize_volume_string(
    service_name: str,
    entry: str,
    app_data_root: str,
    used_appdata_sources: set[str],
) -> Optional[Dict[str, Any]]:
    source, target, mode = _parse_volume_spec(entry)
    if target is None:
        return None
    if not str(target).strip():
        return None

    target_text = str(target).strip()

    if isinstance(source, str) and source.strip() and _is_explicit_bind_source(source):
        out: Dict[str, Any] = {"type": "bind", "source": source.strip(), "target": target_text}
    else:
        source_path = _build_appdata_bind_source(
            service_name=service_name,
            target=target_text,
            app_data_root=app_data_root,
            used_appdata_sources=used_appdata_sources,
            original_source=source,
        )
        out = {"type": "bind", "source": source_path, "target": target_text}

    if mode and _is_read_only_mode(mode):
        out["read_only"] = True
    return out


def _is_explicit_bind_source(source: str) -> bool:
    """Return True if the source is an explicit host path/variable that we should keep.

    For AppStore templates, we still normalize the syntax, but we should not rewrite
    real host paths like `/DATA/Media/Music` into `/DATA/AppData/$AppID/...`.
    """
    text = str(source).strip()
    if not text:
        return False
    if text.startswith("/"):
        return True
    if text.startswith("${") or text.startswith("$"):
        return True
    # Windows drive path (e.g. C:\data). Not typical for CasaOS but keep explicit paths.
    if len(text) >= 3 and text[1] == ":" and text[2] in {"\\", "/"}:
        return True
    return False


def _build_appdata_bind_source(
    service_name: str,
    target: str,
    app_data_root: str,
    used_appdata_sources: set[str],
    original_source: Optional[str] = None,
) -> str:
    """Build a /DATA/AppData/$AppID/... source path for a container mount target."""
    target_text = str(target).strip()
    candidate_subpath = _relative_source_to_appdata_subpath(original_source) or ""

    if not candidate_subpath:
        last_segment = target_text.rstrip("/").split("/")[-1] if target_text else ""
        candidate_subpath = _sanitize_segment(last_segment) or "data"

    # Prefer `/DATA/AppData/$AppID/<candidate>` to match common CasaOS templates.
    source_path = f"{app_data_root}/{candidate_subpath}"
    if source_path in used_appdata_sources:
        safe_service = _sanitize_segment(service_name) or "service"
        source_path = f"{app_data_root}/{safe_service}-{candidate_subpath}"
    if source_path in used_appdata_sources:
        flattened = _sanitize_segment(target_text.strip("/").replace("/", "-"))
        flattened = flattened or f"{_sanitize_segment(candidate_subpath.replace('/', '-')) or 'data'}-path"
        safe_service = _sanitize_segment(service_name) or "service"
        source_path = f"{app_data_root}/{safe_service}-{flattened}"

    used_appdata_sources.add(source_path)
    return source_path


def _relative_source_to_appdata_subpath(source: Optional[str]) -> str:
    """Convert a relative host source path into an AppData subpath.

    Examples:
    - "./data" -> "data"
    - "./data/mysql" -> "data/mysql"
    - ".\\data\\mysql" -> "data/mysql"

    If the path looks unsafe (contains "..") or is an absolute/variable path,
    returns an empty string so callers can fall back to target-derived names.
    """
    if source is None:
        return ""

    text = str(source).strip()
    if not text:
        return ""

    # If it's already an explicit host path/variable, do not treat it as relative.
    if _is_explicit_bind_source(text):
        return ""

    # Only attempt to preserve the source structure for obvious relative paths.
    if not (text.startswith(".") or "/" in text or "\\" in text):
        return ""

    normalized = text.replace("\\", "/").lstrip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")

    segments = [segment for segment in normalized.split("/") if segment and segment != "."]
    if not segments:
        return ""
    if any(segment == ".." for segment in segments):
        return ""

    safe_segments = [_sanitize_segment(segment) for segment in segments]
    safe_segments = [segment for segment in safe_segments if segment]
    return "/".join(safe_segments)


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
