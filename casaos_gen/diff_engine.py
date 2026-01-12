"""Diff engine for comparing compose files and metadata."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

from .models import CasaOSMeta, EnvItem, PortItem, ServiceMeta, VolumeItem
from .parser import extract_envs, extract_ports, extract_volumes

logger = logging.getLogger(__name__)


@dataclass
class FieldChange:
    """字段变更记录"""
    path: str  # 例如: "services.web.ports.80"
    change_type: str  # "added" | "removed" | "modified"
    old_value: Any = None
    new_value: Any = None


@dataclass
class ComposeDiff:
    """Compose 文件差异"""
    added_services: Set[str] = field(default_factory=set)
    removed_services: Set[str] = field(default_factory=set)
    added_fields: List[FieldChange] = field(default_factory=list)
    removed_fields: List[FieldChange] = field(default_factory=list)
    modified_fields: List[FieldChange] = field(default_factory=list)

    def has_changes(self) -> bool:
        """检查是否有任何变更"""
        return bool(
            self.added_services
            or self.removed_services
            or self.added_fields
            or self.removed_fields
            or self.modified_fields
        )

    def summary(self) -> str:
        """生成变更摘要"""
        lines = []
        if self.added_services:
            lines.append(f"✓ 新增服务: {', '.join(sorted(self.added_services))}")
        if self.removed_services:
            lines.append(f"✗ 删除服务: {', '.join(sorted(self.removed_services))}")
        if self.added_fields:
            lines.append(f"+ 新增字段: {len(self.added_fields)} 个")
            for fc in self.added_fields[:5]:
                lines.append(f"  + {fc.path}")
            if len(self.added_fields) > 5:
                lines.append(f"  + ... 还有 {len(self.added_fields) - 5} 个")
        if self.removed_fields:
            lines.append(f"- 删除字段: {len(self.removed_fields)} 个")
            for fc in self.removed_fields[:5]:
                lines.append(f"  - {fc.path}")
            if len(self.removed_fields) > 5:
                lines.append(f"  - ... 还有 {len(self.removed_fields) - 5} 个")
        if self.modified_fields:
            lines.append(f"~ 修改字段: {len(self.modified_fields)} 个")
        return "\n".join(lines) if lines else "无变更"


def compute_compose_diff(old_compose: Dict, new_compose: Dict) -> ComposeDiff:
    """
    对比两个 compose 文件，生成差异报告

    Args:
        old_compose: 旧版 compose 文件数据
        new_compose: 新版 compose 文件数据

    Returns:
        差异报告对象
    """
    diff = ComposeDiff()

    old_services = old_compose.get("services", {})
    new_services = new_compose.get("services", {})

    old_service_names = set(old_services.keys())
    new_service_names = set(new_services.keys())

    # 服务级别差异
    diff.added_services = new_service_names - old_service_names
    diff.removed_services = old_service_names - new_service_names

    # 对比共同服务的字段
    common_services = old_service_names & new_service_names

    for svc_name in common_services:
        old_svc = old_services[svc_name]
        new_svc = new_services[svc_name]

        # 对比端口
        _compare_ports(svc_name, old_svc, new_svc, diff)

        # 对比环境变量
        _compare_envs(svc_name, old_svc, new_svc, diff)

        # 对比存储卷
        _compare_volumes(svc_name, old_svc, new_svc, diff)

    # 对比新增服务的所有字段
    for svc_name in diff.added_services:
        new_svc = new_services[svc_name]
        for port in extract_ports(new_svc):
            diff.added_fields.append(
                FieldChange(
                    path=f"services.{svc_name}.ports.{port.container}",
                    change_type="added",
                    new_value=port.container,
                )
            )
        for env in extract_envs(new_svc):
            diff.added_fields.append(
                FieldChange(
                    path=f"services.{svc_name}.envs.{env.container}",
                    change_type="added",
                    new_value=env.container,
                )
            )
        for vol in extract_volumes(new_svc):
            diff.added_fields.append(
                FieldChange(
                    path=f"services.{svc_name}.volumes.{vol.container}",
                    change_type="added",
                    new_value=vol.container,
                )
            )

    logger.info("Compose diff computed: %s", diff.summary())
    return diff


def _compare_ports(svc_name: str, old_svc: Dict, new_svc: Dict, diff: ComposeDiff):
    """对比服务的端口配置"""
    old_ports = {p.container for p in extract_ports(old_svc)}
    new_ports = {p.container for p in extract_ports(new_svc)}

    for port in new_ports - old_ports:
        diff.added_fields.append(
            FieldChange(
                path=f"services.{svc_name}.ports.{port}",
                change_type="added",
                new_value=port,
            )
        )

    for port in old_ports - new_ports:
        diff.removed_fields.append(
            FieldChange(
                path=f"services.{svc_name}.ports.{port}",
                change_type="removed",
                old_value=port,
            )
        )


def _compare_envs(svc_name: str, old_svc: Dict, new_svc: Dict, diff: ComposeDiff):
    """对比服务的环境变量"""
    old_envs = {e.container for e in extract_envs(old_svc)}
    new_envs = {e.container for e in extract_envs(new_svc)}

    for env in new_envs - old_envs:
        diff.added_fields.append(
            FieldChange(
                path=f"services.{svc_name}.envs.{env}",
                change_type="added",
                new_value=env,
            )
        )

    for env in old_envs - new_envs:
        diff.removed_fields.append(
            FieldChange(
                path=f"services.{svc_name}.envs.{env}",
                change_type="removed",
                old_value=env,
            )
        )


def _compare_volumes(svc_name: str, old_svc: Dict, new_svc: Dict, diff: ComposeDiff):
    """对比服务的存储卷"""
    old_vols = {v.container for v in extract_volumes(old_svc)}
    new_vols = {v.container for v in extract_volumes(new_svc)}

    for vol in new_vols - old_vols:
        diff.added_fields.append(
            FieldChange(
                path=f"services.{svc_name}.volumes.{vol}",
                change_type="added",
                new_value=vol,
            )
        )

    for vol in old_vols - new_vols:
        diff.removed_fields.append(
            FieldChange(
                path=f"services.{svc_name}.volumes.{vol}",
                change_type="removed",
                old_value=vol,
            )
        )


def merge_meta_with_diff(
    old_meta: CasaOSMeta,
    new_meta: CasaOSMeta,
    diff: ComposeDiff,
) -> CasaOSMeta:
    """
    根据差异，合并旧元数据与新结构

    策略：
    1. 保留所有旧字段的 description
    2. 为新增字段保持空白 description（待 AI 填充）
    3. 删除已移除字段（自动处理，因为 new_meta 中不包含）

    Args:
        old_meta: 旧版元数据
        new_meta: 新版元数据骨架（由 build_casaos_meta 生成）
        diff: 差异报告

    Returns:
        合并后的元数据
    """
    # 保留应用级别的旧数据（如果用户修改过）
    if old_meta.app.title and old_meta.app.title != new_meta.app.title:
        # 如果旧标题不为空且与新标题不同，说明可能是用户修改过的
        logger.info(f"保留旧的 app.title: {old_meta.app.title}")
        new_meta.app.title = old_meta.app.title

    if old_meta.app.tagline and old_meta.app.tagline != f"{new_meta.app.title} on CasaOS":
        logger.info(f"保留旧的 app.tagline: {old_meta.app.tagline}")
        new_meta.app.tagline = old_meta.app.tagline

    if old_meta.app.description and len(old_meta.app.description) > 100:
        # 如果旧描述比较长，说明可能是 AI 生成或用户填写的
        logger.info("保留旧的 app.description")
        new_meta.app.description = old_meta.app.description

    # 合并服务级别的元数据
    for svc_name, new_svc in new_meta.services.items():
        if svc_name not in old_meta.services:
            # 新增服务，保持空白 description
            logger.info(f"新增服务: {svc_name}, 字段将由 AI 填充")
            continue

        old_svc = old_meta.services[svc_name]

        # 合并端口
        old_port_map = {p.container: p for p in old_svc.ports}
        for new_port in new_svc.ports:
            if new_port.container in old_port_map:
                # 保留旧 description
                old_desc = old_port_map[new_port.container].description
                if old_desc:
                    logger.debug(
                        f"保留 {svc_name}.ports.{new_port.container}.description: {old_desc}"
                    )
                    new_port.description = old_desc
            # 否则保持空白，等待 AI 填充

        # 合并环境变量
        old_env_map = {e.container: e for e in old_svc.envs}
        for new_env in new_svc.envs:
            if new_env.container in old_env_map:
                old_desc = old_env_map[new_env.container].description
                if old_desc:
                    logger.debug(
                        f"保留 {svc_name}.envs.{new_env.container}.description: {old_desc}"
                    )
                    new_env.description = old_desc

        # 合并存储卷
        old_vol_map = {v.container: v for v in old_svc.volumes}
        for new_vol in new_svc.volumes:
            if new_vol.container in old_vol_map:
                old_desc = old_vol_map[new_vol.container].description
                if old_desc:
                    logger.debug(
                        f"保留 {svc_name}.volumes.{new_vol.container}.description: {old_desc}"
                    )
                    new_vol.description = old_desc

    logger.info("元数据合并完成")
    return new_meta
