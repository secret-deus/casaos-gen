"""Helpers for producing CasaOS aware docker-compose documents."""
from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from yaml.representer import SafeRepresenter

from .i18n import apply_multilang_app, apply_multilang_services
from .models import CasaOSMeta

logger = logging.getLogger(__name__)


class CasaOSQuotedStr(str):
    """A string that must be rendered with double quotes in YAML."""


class _CasaOSYamlDumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:  # type: ignore[override]
        # PyYAML defaults to "indentless" sequences under mappings, producing:
        #   key:
        #   - item
        # Force indentation so it becomes:
        #   key:
        #     - item
        return super().increase_indent(flow, False)


def _represent_casaos_quoted_str(dumper: yaml.SafeDumper, data: CasaOSQuotedStr) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style='"')


_CasaOSYamlDumper.add_representer(CasaOSQuotedStr, _represent_casaos_quoted_str)


def _represent_multiline_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    """Prefer literal block scalars for multi-line strings.

    This keeps long x-casaos descriptions readable (no '\\n\\' wrapping from double-quoted YAML scalars).
    """
    if "\n" in data or "\r" in data:
        normalized = data.replace("\r\n", "\n").replace("\r", "\n")
        return dumper.represent_scalar("tag:yaml.org,2002:str", normalized, style="|")
    return SafeRepresenter.represent_str(dumper, data)


_CasaOSYamlDumper.add_representer(str, _represent_multiline_str)


def _prepare_for_yaml_dump(data: Any) -> Any:
    if isinstance(data, dict):
        prepared: Dict[Any, Any] = {}
        for key, value in data.items():
            prepared_value = _prepare_for_yaml_dump(value)

            if key in {"published", "port_map"} and prepared_value is not None:
                text = str(prepared_value)
                if text.strip():
                    prepared[key] = CasaOSQuotedStr(text)
                    continue

            if key == "container" and prepared_value is not None:
                text = str(prepared_value).strip()
                if text.isdigit():
                    prepared[key] = CasaOSQuotedStr(text)
                    continue

            prepared[key] = prepared_value
        return prepared

    if isinstance(data, list):
        return [_prepare_for_yaml_dump(item) for item in data]

    return data


def _normalize_multilang(value: Any, languages: List[str]) -> Dict[str, str]:
    if isinstance(value, dict):
        return {lang: str(value.get(lang, "") or "") for lang in languages}
    if value is None:
        return {lang: "" for lang in languages}
    text = str(value)
    return {lang: text for lang in languages}


def _normalize_tips(value: Any, languages: List[str]) -> Any:
    if value is None:
        return None
    if not isinstance(value, dict):
        return value
    normalized: Dict[str, Any] = {}
    for section, payload in value.items():
        normalized[section] = _normalize_multilang(payload, languages)
    return normalized


def dump_yaml(data: Any) -> str:
    """Serialize data into YAML with CasaOS-friendly indentation."""
    prepared = _prepare_for_yaml_dump(data)
    return yaml.dump(
        prepared,
        Dumper=_CasaOSYamlDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=4096,
    )


def build_final_compose(
    original_compose: Dict,
    meta: CasaOSMeta,
    languages: List[str],
    translation_map: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict:
    compose_out = copy.deepcopy(original_compose)
    services_block = compose_out.get("services") or {}
    if not isinstance(services_block, dict):
        services_block = {}

    existing_app_x = compose_out.get("x-casaos")
    if not isinstance(existing_app_x, dict):
        existing_app_x = {}

    app_id = str(meta.app.main or "").strip().lower()
    if app_id:
        compose_out["name"] = app_id

    services_i18n = apply_multilang_services(meta, languages, translation_map)
    for name, svc in services_block.items():
        if not isinstance(svc, dict):
            continue
        if not str(svc.get("restart") or "").strip():
            svc["restart"] = "unless-stopped"
        if not str(svc.get("container_name") or "").strip():
            svc["container_name"] = name
        if name in services_i18n:
            existing_x = svc.get("x-casaos")
            if not isinstance(existing_x, dict):
                existing_x = {}
            svc["x-casaos"] = {**existing_x, **services_i18n[name]}

    compose_out["services"] = services_block
    generated_app_x = apply_multilang_app(meta, languages, translation_map)
    if app_id:
        generated_app_x["main"] = app_id
    compose_out["x-casaos"] = {**existing_app_x, **generated_app_x}
    tips = _normalize_tips(compose_out["x-casaos"].get("tips"), languages)
    if tips is not None:
        compose_out["x-casaos"]["tips"] = tips
    return compose_out


def write_compose_file(data: Dict, path: Path) -> None:
    yaml_text = dump_yaml(data)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(yaml_text)
    logger.info("CasaOS compose written to %s", path)
