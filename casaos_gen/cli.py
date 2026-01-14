"""Command line interface for CasaOS compose generation."""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List

import yaml

from .compose_normalize import normalize_compose_for_appstore
from .console import write_stdout_text
from .i18n import DEFAULT_LANGUAGES
from .incremental import (
    get_version_history,
    incremental_update,
    rollback_version,
    show_compose_diff,
)
from .pipeline import apply_params_to_meta
from .main import (
    load_meta_json,
    run_params_stage,
    run_stage_one,
    run_template_stage,
    save_meta_json,
    stage_two_from_meta,
    write_final_compose,
)
from .parser import load_compose_file
from .yaml_out import dump_yaml


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="casaos-gen",
        description="Generate CasaOS-ready docker-compose files with incremental updates.",
    )
    parser.add_argument("input_file", type=Path, nargs="?", help="Path to docker-compose.yml")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("casaos-compose.yml"),
        help="Output CasaOS compose path (stage=all/2).",
    )
    parser.add_argument(
        "--stage",
        choices=["all", "1", "2", "template", "params", "normalize"],
        default="all",
        help="Pipeline stage to run.",
    )

    # 增量更新相关参数
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Enable incremental update mode (preserve existing descriptions).",
    )
    parser.add_argument(
        "--force-regenerate",
        action="store_true",
        help="Force full regeneration (ignore cached metadata).",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path(".casaos-gen"),
        help="Version control working directory.",
    )

    # 版本管理命令
    parser.add_argument(
        "--list-versions",
        action="store_true",
        help="List all history versions and exit.",
    )
    parser.add_argument(
        "--rollback",
        type=str,
        metavar="VERSION_FILE",
        help="Rollback to specified version (e.g., meta.20260108_143022.json).",
    )
    parser.add_argument(
        "--show-diff",
        action="store_true",
        help="Show compose file diff without updating.",
    )

    parser.add_argument(
        "--params",
        type=Path,
        help="Optional params.yml (app/service overrides; used by template/all/1/2/normalize).",
    )
    parser.add_argument(
        "--params-output",
        type=Path,
        default=Path("params.generated.yml"),
        help="Where to write params.yml skeleton when stage=params.",
    )
    parser.add_argument(
        "--languages",
        nargs="*",
        help="Locales to include. Defaults to CasaOS built-in list.",
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
        "--appstore",
        action="store_true",
        help="Normalize ports/volumes for CasaOS AppStore templates (bind mounts under /DATA/AppData/$AppID).",
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
    languages = args.languages if args.languages else DEFAULT_LANGUAGES

    try:
        params = None
        store_folder = None
        if args.params:
            params = yaml.safe_load(args.params.read_text(encoding="utf-8")) or {}
            if not isinstance(params, dict):
                parser.error("--params must be a YAML mapping/object")
            store_folder_value = (params.get("app") or {}).get("store_folder")
            if store_folder_value is not None:
                store_folder = str(store_folder_value).strip() or None

        # 版本管理命令（优先处理）
        if args.list_versions:
            versions = get_version_history(args.work_dir)
            if not versions:
                print("没有历史版本")
                return 0
            print("\n历史版本列表:")
            print("-" * 70)
            for v in versions:
                timestamp = datetime.fromtimestamp(v["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
                size_kb = v["size"] / 1024
                print(f"{v['file']:<40} {timestamp}  ({size_kb:.1f} KB)")
            return 0

        if args.rollback:
            rollback_version(args.rollback, args.work_dir)
            print(f"✓ 已回滚到版本: {args.rollback}")
            return 0

        if args.show_diff:
            if not args.input_file:
                parser.error("--show-diff requires input_file")
            diff = show_compose_diff(args.input_file, args.work_dir)
            if diff is None:
                print("没有旧版本可对比")
                return 0
            if not diff.has_changes():
                print("无变更")
                return 0
            print("\n=== 变更摘要 ===")
            print(diff.summary())
            return 0

        # 必须提供 input_file（除非是版本管理命令）
        if not args.input_file:
            parser.error("the following arguments are required: input_file")

        if args.stage == "normalize":
            compose = load_compose_file(args.input_file)
            normalized = normalize_compose_for_appstore(compose, store_folder=store_folder)
            write_final_compose(normalized, args.output, args.dry_run)
            return 0

        # 增量更新流程
        if args.incremental or args.force_regenerate:
            # LLM 配置
            llm_config = {
                "model": args.model,
                "temperature": args.temperature,
            }

            # 执行增量更新
            meta, diff = incremental_update(
                compose_path=args.input_file,
                params=params,
                work_dir=args.work_dir,
                force_regenerate=args.force_regenerate,
                llm_config=llm_config,
            )
            if params:
                meta = apply_params_to_meta(meta, params)

            # 保存元数据（如果需要）
            if args.meta_output:
                save_meta_json(meta, args.meta_output)

            # 生成最终 compose
            compose = load_compose_file(args.input_file)
            final_compose = stage_two_from_meta(
                compose,
                meta,
                languages=languages,
                translation_file=args.translations,
            )
            if args.appstore:
                final_compose = normalize_compose_for_appstore(final_compose, store_folder=store_folder)
            write_final_compose(final_compose, args.output, args.dry_run)
            return 0

        # 原有流程（不使用增量更新）
        if args.stage == "params":
            params = run_params_stage(args.input_file)
            yaml_text = dump_yaml(params)
            if args.dry_run:
                write_stdout_text(yaml_text)
                return 0
            args.params_output.write_text(yaml_text, encoding="utf-8")
            logging.info("Params template written to %s", args.params_output)
            return 0

        if args.stage == "template":
            compose = run_template_stage(
                args.input_file,
                params_path=args.params,
                languages=languages,
            )
            if args.appstore:
                compose = normalize_compose_for_appstore(compose, store_folder=store_folder)
            write_final_compose(compose, args.output, args.dry_run)
            return 0

        if args.stage == "1":
            _, meta = run_stage_one(args.input_file, args.model, args.temperature)
            if params:
                meta = apply_params_to_meta(meta, params)
            if args.meta_output:
                save_meta_json(meta, args.meta_output)
            # Build multi-language compose immediately using default languages
            compose = load_compose_file(args.input_file)
            final_compose = stage_two_from_meta(
                compose,
                meta,
                languages=languages,
                translation_file=args.translations,
            )
            if args.appstore:
                final_compose = normalize_compose_for_appstore(final_compose, store_folder=store_folder)
            if args.output:
                write_final_compose(final_compose, args.output, args.dry_run)
            else:
                yaml_text = dump_yaml(final_compose)
                write_stdout_text(yaml_text)
            return 0

        if args.stage == "2":
            if not args.meta_input:
                parser.error("--meta-input is required when stage=2")
            compose = load_compose_file(args.input_file)
            meta = load_meta_json(args.meta_input)
            if params:
                meta = apply_params_to_meta(meta, params)
        else:  # stage all
            compose, meta = run_stage_one(args.input_file, args.model, args.temperature)
            if params:
                meta = apply_params_to_meta(meta, params)
            if args.meta_output:
                save_meta_json(meta, args.meta_output)

        final_compose = stage_two_from_meta(
            compose,
            meta,
            languages=languages,
            translation_file=args.translations,
        )
        if args.appstore:
            final_compose = normalize_compose_for_appstore(final_compose, store_folder=store_folder)
        write_final_compose(final_compose, args.output, args.dry_run)
        return 0
    except Exception as exc:  # pragma: no cover - protects CLI UX
        logging.error("casaos-gen failed: %s", exc)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
