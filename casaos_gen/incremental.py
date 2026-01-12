"""Incremental update pipeline for CasaOS metadata."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional

from .diff_engine import ComposeDiff, compute_compose_diff, merge_meta_with_diff
from .models import CasaOSMeta
from .parser import build_casaos_meta, load_compose_file
from .version_manager import VersionManager

logger = logging.getLogger(__name__)


def incremental_update(
    compose_path: Path,
    params: Optional[Dict] = None,
    work_dir: Path | str = ".casaos-gen",
    force_regenerate: bool = False,
    llm_config: Optional[Dict] = None,
) -> tuple[CasaOSMeta, ComposeDiff | None]:
    """
    增量更新主流程

    Args:
        compose_path: 新的 compose 文件路径
        params: 用户 params 字典（可选）
        work_dir: 版本管理工作目录
        force_regenerate: 强制重新生成（忽略历史）
        llm_config: LLM 配置 (model, api_key, base_url, temperature)

    Returns:
        (更新后的元数据, 差异报告) 如果没有差异则 diff 为 None
    """
    vm = VersionManager(work_dir)

    # Step 1: 检查 compose 是否变化
    if not force_regenerate and not vm.has_compose_changed(compose_path):
        cached_meta = vm.load_current_meta()
        if cached_meta:
            logger.info("✓ Compose 文件未变化，使用缓存")
            return cached_meta, None
        # 缓存不存在，继续生成
        logger.info("缓存不存在，继续生成")

    # Step 2: 加载新 compose 数据
    new_compose = load_compose_file(compose_path)
    old_meta = vm.load_current_meta()

    if old_meta is None or force_regenerate:
        # 首次生成 或 强制重新生成
        logger.info("→ 执行完整生成流程")
        new_meta = build_casaos_meta(new_compose)
        diff = None

        # 应用 params（如果提供）
        if params:
            new_meta = apply_params_to_meta(new_meta, params)

        # 调用 LLM 填充（如果配置了）
        if llm_config:
            new_meta = _run_llm_fill(new_meta, new_compose, llm_config)
    else:
        # 增量更新
        logger.info("→ 检测到已有版本，执行增量更新")

        # Step 3: 加载旧 compose 文件（如果存在）
        old_compose_path = vm.get_backed_up_compose()
        if old_compose_path:
            old_compose = load_compose_file(old_compose_path)
        else:
            # 没有备份，无法对比，执行完整流程
            logger.warning("没有旧版 compose 备份，执行完整流程")
            new_meta = build_casaos_meta(new_compose)
            if params:
                new_meta = apply_params_to_meta(new_meta, params)
            if llm_config:
                new_meta = _run_llm_fill(new_meta, new_compose, llm_config)
            diff = None

            # 保存并备份
            _save_and_backup(vm, new_meta, compose_path, old_meta)
            return new_meta, diff

        # Step 4: 计算差异
        diff = compute_compose_diff(old_compose, new_compose)

        # Step 5: 打印变更摘要
        print("\n=== 变更摘要 ===")
        print(diff.summary())
        print()

        # Step 6: 生成新骨架并合并
        new_meta = build_casaos_meta(new_compose)
        new_meta = merge_meta_with_diff(old_meta, new_meta, diff)

        # 应用 params（如果提供）
        if params:
            new_meta = apply_params_to_meta(new_meta, params)

        # Step 7: 只对新增/空白字段调用 AI
        if llm_config and diff.added_fields:
            logger.info(f"→ 对 {len(diff.added_fields)} 个新字段调用 AI")
            new_meta = _run_llm_fill(
                new_meta, new_compose, llm_config, only_fill_empty=True
            )
        elif llm_config:
            # 没有新增字段但可能有空白字段
            new_meta = _run_llm_fill(
                new_meta, new_compose, llm_config, only_fill_empty=True
            )

    # Step 8: 保存并备份
    _save_and_backup(vm, new_meta, compose_path, old_meta)

    return new_meta, diff


def _save_and_backup(
    vm: VersionManager,
    new_meta: CasaOSMeta,
    compose_path: Path,
    old_meta: Optional[CasaOSMeta],
):
    """保存新版本并备份旧版本"""
    config = vm._load_config()

    # 备份旧版本
    if old_meta and config.get("auto_backup_before_update", True):
        vm.backup_to_history()

    # 保存新版本
    vm.save_current_meta(new_meta)
    vm.update_compose_hash(compose_path)
    vm.backup_compose_file(compose_path)

    logger.info("✓ 版本更新完成")


def _run_llm_fill(
    meta: CasaOSMeta,
    compose_data: Dict,
    llm_config: Dict,
    only_fill_empty: bool = False,
) -> CasaOSMeta:
    """
    运行 LLM 填充

    Args:
        meta: 元数据
        compose_data: compose 数据
        llm_config: LLM 配置
        only_fill_empty: 是否只填充空白字段
    """
    from .llm_stage1 import run_stage1_llm

    # 如果 only_fill_empty，检查是否有空白字段
    if only_fill_empty:
        has_empty = _has_empty_descriptions(meta)
        if not has_empty:
            logger.info("✓ 所有字段已填充，跳过 AI 调用")
            return meta

    return run_stage1_llm(
        structure=meta,
        model=llm_config.get("model", "gpt-4.1-mini"),
        temperature=llm_config.get("temperature", 0.2),
        api_key=llm_config.get("api_key"),
        base_url=llm_config.get("base_url"),
    )


def _has_empty_descriptions(meta: CasaOSMeta) -> bool:
    """检查元数据中是否有空白的 description"""
    # 检查 app 级别
    if not meta.app.title.strip():
        return True
    if not meta.app.tagline.strip():
        return True
    if not meta.app.description.strip():
        return True

    # 检查服务级别
    for svc in meta.services.values():
        for port in svc.ports:
            if not port.description.strip():
                return True
        for env in svc.envs:
            if not env.description.strip():
                return True
        for vol in svc.volumes:
            if not vol.description.strip():
                return True

    return False


def apply_params_to_meta(meta: CasaOSMeta, params: Dict) -> CasaOSMeta:
    """
    将 params 参数应用到元数据

    Args:
        meta: 元数据
        params: 用户 params 字典

    Returns:
        更新后的元数据
    """
    app_params = params.get("app", {})

    # 应用 app 级别参数
    if app_params.get("title"):
        meta.app.title = app_params["title"]
    if app_params.get("tagline"):
        meta.app.tagline = app_params["tagline"]
    if app_params.get("description"):
        meta.app.description = app_params["description"]
    if app_params.get("category"):
        meta.app.category = app_params["category"]
    if app_params.get("author"):
        meta.app.author = app_params["author"]
    if app_params.get("developer"):
        meta.app.developer = app_params["developer"]
    if app_params.get("icon"):
        meta.app.icon = app_params["icon"]
    if app_params.get("thumbnail"):
        meta.app.thumbnail = app_params["thumbnail"]
    if app_params.get("screenshot_link"):
        meta.app.screenshot_link = app_params["screenshot_link"]
    if app_params.get("index"):
        meta.app.index = app_params["index"]
    if app_params.get("scheme"):
        meta.app.scheme = app_params["scheme"]
    if app_params.get("architectures"):
        meta.app.architectures = app_params["architectures"]

    # 应用 services 级别参数
    services_params = params.get("services", {})
    for svc_name, svc_params in services_params.items():
        if svc_name not in meta.services:
            continue

        svc_meta = meta.services[svc_name]

        # 应用端口参数
        ports_params = svc_params.get("ports", [])
        port_map = {p.container: p for p in svc_meta.ports}
        for port_param in ports_params:
            container = port_param.get("container")
            if container and container in port_map:
                desc = port_param.get("description", "")
                if desc:
                    port_map[container].description = desc

        # 应用环境变量参数
        envs_params = svc_params.get("envs", [])
        env_map = {e.container: e for e in svc_meta.envs}
        for env_param in envs_params:
            container = env_param.get("container")
            if container and container in env_map:
                desc = env_param.get("description", "")
                if desc:
                    env_map[container].description = desc

        # 应用存储卷参数
        volumes_params = svc_params.get("volumes", [])
        vol_map = {v.container: v for v in svc_meta.volumes}
        for vol_param in volumes_params:
            container = vol_param.get("container")
            if container and container in vol_map:
                desc = vol_param.get("description", "")
                if desc:
                    vol_map[container].description = desc

    logger.info("已应用 params 参数")
    return meta


def get_version_history(work_dir: Path | str = ".casaos-gen"):
    """
    获取版本历史

    Args:
        work_dir: 版本管理工作目录

    Returns:
        版本信息列表
    """
    vm = VersionManager(work_dir)
    return vm.list_history()


def rollback_version(version_file: str, work_dir: Path | str = ".casaos-gen"):
    """
    回滚到指定版本

    Args:
        version_file: 版本文件名
        work_dir: 版本管理工作目录
    """
    vm = VersionManager(work_dir)
    vm.rollback_to_version(version_file)


def show_compose_diff(
    compose_path: Path, work_dir: Path | str = ".casaos-gen"
) -> Optional[ComposeDiff]:
    """
    显示 compose 文件的差异（不实际更新）

    Args:
        compose_path: compose 文件路径
        work_dir: 版本管理工作目录

    Returns:
        差异报告，如果没有旧版本则返回 None
    """
    vm = VersionManager(work_dir)

    old_compose_path = vm.get_backed_up_compose()
    if not old_compose_path:
        logger.info("没有旧版 compose 备份，无法对比")
        return None

    old_compose = load_compose_file(old_compose_path)
    new_compose = load_compose_file(compose_path)

    diff = compute_compose_diff(old_compose, new_compose)
    return diff
