"""Helpers for producing CasaOS aware docker-compose documents."""
from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .i18n import apply_multilang_app, apply_multilang_services
from .models import CasaOSMeta

logger = logging.getLogger(__name__)


def build_final_compose(
    original_compose: Dict,
    meta: CasaOSMeta,
    languages: List[str],
    translation_map: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict:
    compose_out = copy.deepcopy(original_compose)
    services_block = compose_out.get("services") or {}
    services_i18n = apply_multilang_services(meta, languages, translation_map)
    for name, svc in services_block.items():
        if name in services_i18n:
            svc["x-casaos"] = services_i18n[name]

    compose_out["services"] = services_block
    compose_out["x-casaos"] = apply_multilang_app(meta, languages, translation_map)
    return compose_out


def write_compose_file(data: Dict, path: Path) -> None:
    yaml_text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(yaml_text)
    logger.info("CasaOS compose written to %s", path)

