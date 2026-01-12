"""High level orchestration helpers consumed by the CLI."""
from __future__ import annotations

import logging
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from . import models
from .llm_stage1 import run_stage1_llm
from .pipeline import render_compose
from .parser import build_casaos_meta, load_compose_file
from .template_stage import build_params_from_files, build_template_from_files
from .yaml_out import write_compose_file
from .console import write_stdout_text

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
    return render_compose(
        compose_data,
        meta,
        languages=languages,
        translation_file=translation_file,
        translation_map_override=translation_map_override,
    )


def write_final_compose(data: Dict, output_path: Path, dry_run: bool) -> None:
    if dry_run:
        logger.info("Dry run enabled; compose not written to disk.")
        preview = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        write_stdout_text(preview)
        return
    write_compose_file(data, output_path)


def run_template_stage(
    compose_path: Path,
    params_path: Optional[Path] = None,
    languages: Optional[List[str]] = None,
) -> Dict:
    """Build a CasaOS template compose without calling LLMs."""
    return build_template_from_files(compose_path, params_path=params_path, languages=languages)


def run_params_stage(compose_path: Path) -> Dict:
    """Generate a params.yml skeleton from a normal docker-compose.yml."""
    return build_params_from_files(compose_path)
