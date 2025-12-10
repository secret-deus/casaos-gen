"""High level orchestration helpers consumed by the CLI."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from . import models
from .i18n import DEFAULT_LANGUAGES, load_translation_map
from .llm_stage1 import run_stage1_llm
from .parser import build_casaos_meta, load_compose_file
from .yaml_out import build_final_compose, write_compose_file

logger = logging.getLogger(__name__)


def prepare_structure(compose_path: Path) -> Tuple[Dict, models.CasaOSMeta]:
    compose_data = load_compose_file(compose_path)
    meta = build_casaos_meta(compose_data)
    return compose_data, meta


def run_stage_one(
    compose_path: Path,
    model_name: str,
    temperature: float,
) -> Tuple[Dict, models.CasaOSMeta]:
    compose, skeleton = prepare_structure(compose_path)
    filled = run_stage1_llm(skeleton, model=model_name, temperature=temperature)
    return compose, filled


def save_meta_json(meta: models.CasaOSMeta, output_path: Path) -> None:
    output_path.write_text(meta.to_json(), encoding="utf-8")
    logger.info("Stage 1 metadata written to %s", output_path)


def load_meta_json(meta_path: Path) -> models.CasaOSMeta:
    raw = meta_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    return models.CasaOSMeta.model_validate(data)


def stage_two_from_meta(
    compose_data: Dict,
    meta: models.CasaOSMeta,
    languages: Optional[List[str]] = None,
    translation_file: Optional[Path] = None,
    translation_map_override: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict:
    langs = languages or DEFAULT_LANGUAGES
    if translation_map_override is not None:
        translation_map = translation_map_override
    else:
        translation_map = load_translation_map(translation_file)
    final_compose = build_final_compose(compose_data, meta, langs, translation_map)
    return final_compose


def write_final_compose(data: Dict, output_path: Path, dry_run: bool) -> None:
    if dry_run:
        logger.info("Dry run enabled; compose not written to disk.")
        preview = yaml.safe_dump(data, sort_keys=False)
        print(preview)
        return
    write_compose_file(data, output_path)

