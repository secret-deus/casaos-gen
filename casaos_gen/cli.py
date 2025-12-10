"""Command line interface for CasaOS compose generation."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List

from .i18n import DEFAULT_LANGUAGES
from .main import (
    load_meta_json,
    run_stage_one,
    save_meta_json,
    stage_two_from_meta,
    write_final_compose,
)
from .parser import load_compose_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="casaos-gen",
        description="Generate CasaOS-ready docker-compose files.",
    )
    parser.add_argument("input_file", type=Path, help="Path to docker-compose.yml")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("casaos-compose.yml"),
        help="Output CasaOS compose path (stage=all/2).",
    )
    parser.add_argument(
        "--stage",
        choices=["all", "1", "2"],
        default="all",
        help="Pipeline stage to run.",
    )
    parser.add_argument(
        "--model",
        default="gpt-4.1-mini",
        help="LLM model identifier for stage 1.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="LLM temperature for stage 1.",
    )
    parser.add_argument(
        "--meta-output",
        type=Path,
        help="Where to write the CasaOSMeta JSON when stage 1 data should be saved.",
    )
    parser.add_argument(
        "--meta-input",
        type=Path,
        help="Existing CasaOSMeta JSON to consume when running stage=2.",
    )
    parser.add_argument(
        "--translations",
        type=Path,
        help="Optional translations.yml override.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated compose without writing to disk.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    languages = DEFAULT_LANGUAGES

    try:
        if args.stage == "1":
            _, meta = run_stage_one(args.input_file, args.model, args.temperature)
            if args.meta_output:
                save_meta_json(meta, args.meta_output)
            else:
                print(meta.to_json())
            return 0

        if args.stage == "2":
            if not args.meta_input:
                parser.error("--meta-input is required when stage=2")
            compose = load_compose_file(args.input_file)
            meta = load_meta_json(args.meta_input)
        else:  # stage all
            compose, meta = run_stage_one(args.input_file, args.model, args.temperature)
            if args.meta_output:
                save_meta_json(meta, args.meta_output)

        final_compose = stage_two_from_meta(
            compose,
            meta,
            languages=languages,
            translation_file=args.translations,
        )
        write_final_compose(final_compose, args.output, args.dry_run)
        return 0
    except Exception as exc:  # pragma: no cover - protects CLI UX
        logging.error("casaos-gen failed: %s", exc)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

