"""Version manager for CasaOS metadata."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .models import CasaOSMeta

logger = logging.getLogger(__name__)


class VersionManager:
    """管理 CasaOS 元数据的版本控制"""

    def __init__(self, work_dir: Path | str = ".casaos-gen"):
        """
        初始化版本管理器

        Args:
            work_dir: 工作目录路径，默认为 .casaos-gen
        """
        self.work_dir = Path(work_dir)
        self.history_dir = self.work_dir / "history"
        self.config_file = self.work_dir / "config.json"
        self.current_meta_file = self.work_dir / "meta.current.json"
        self.compose_hash_file = self.work_dir / "compose.hash"
        self.compose_backup_file = self.work_dir / "compose.old.yml"

        self._init_dirs()

    def _init_dirs(self):
        """初始化工作目录"""
        self.work_dir.mkdir(exist_ok=True)
        self.history_dir.mkdir(exist_ok=True)
        logger.debug(f"版本管理目录初始化: {self.work_dir}")

    def compute_compose_hash(self, compose_path: Path) -> str:
        """
        计算 compose 文件的 SHA256 哈希

        Args:
            compose_path: compose 文件路径

        Returns:
            SHA256 哈希值
        """
        if not compose_path.exists():
            return ""
        return hashlib.sha256(compose_path.read_bytes()).hexdigest()

    def has_compose_changed(self, compose_path: Path) -> bool:
        """
        检查 compose 文件是否变化

        Args:
            compose_path: compose 文件路径

        Returns:
            True 如果文件变化或首次检测
        """
        if not self.compose_hash_file.exists():
            logger.info("首次检测 compose 文件")
            return True

        old_hash = self.compose_hash_file.read_text(encoding="utf-8").strip()
        new_hash = self.compute_compose_hash(compose_path)

        if old_hash != new_hash:
            logger.info(f"Compose 文件已变化 (旧哈希: {old_hash[:8]}... → 新哈希: {new_hash[:8]}...)")
            return True

        logger.info("Compose 文件未变化")
        return False

    def save_current_meta(self, meta: CasaOSMeta):
        """
        保存当前元数据

        Args:
            meta: CasaOS 元数据对象
        """
        json_data = meta.model_dump_json(indent=2)
        self.current_meta_file.write_text(json_data, encoding="utf-8")
        logger.info(f"元数据已保存到: {self.current_meta_file}")

    def load_current_meta(self) -> Optional[CasaOSMeta]:
        """
        加载当前元数据

        Returns:
            CasaOS 元数据对象，如果不存在则返回 None
        """
        if not self.current_meta_file.exists():
            logger.info("未找到当前元数据文件")
            return None

        try:
            json_text = self.current_meta_file.read_text(encoding="utf-8")
            meta = CasaOSMeta.model_validate_json(json_text)
            logger.info(f"元数据加载成功: {self.current_meta_file}")
            return meta
        except Exception as e:
            logger.error(f"加载元数据失败: {e}")
            return None

    def backup_to_history(self) -> Optional[Path]:
        """
        备份当前版本到历史目录

        Returns:
            备份文件路径，如果没有当前文件则返回 None
        """
        if not self.current_meta_file.exists():
            logger.warning("没有当前元数据文件可备份")
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = self.history_dir / f"meta.{timestamp}.json"

        shutil.copy2(self.current_meta_file, backup_file)
        logger.info(f"已备份到: {backup_file}")

        # 清理超出限制的历史版本
        self._cleanup_old_versions()

        return backup_file

    def _cleanup_old_versions(self):
        """保留最新的 N 个版本"""
        config = self._load_config()
        max_versions = config.get("max_history_versions", 3)

        versions = sorted(self.history_dir.glob("meta.*.json"), reverse=True)

        if len(versions) > max_versions:
            logger.info(f"清理旧版本，保留最新 {max_versions} 个")
            for old_version in versions[max_versions:]:
                old_version.unlink()
                logger.debug(f"删除旧版本: {old_version.name}")

    def _load_config(self) -> Dict:
        """
        加载配置文件

        Returns:
            配置字典
        """
        if not self.config_file.exists():
            default_config = {
                "max_history_versions": 3,
                "enable_version_control": True,
                "auto_backup_before_update": True,
            }
            return default_config

        try:
            config_text = self.config_file.read_text(encoding="utf-8")
            return json.loads(config_text)
        except Exception as e:
            logger.error(f"加载配置失败: {e}，使用默认配置")
            return {
                "max_history_versions": 3,
                "enable_version_control": True,
                "auto_backup_before_update": True,
            }

    def save_config(self, config: Dict):
        """
        保存配置文件

        Args:
            config: 配置字典
        """
        self.config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
        logger.info(f"配置已保存到: {self.config_file}")

    def list_history(self) -> List[Dict]:
        """
        列出所有历史版本

        Returns:
            版本信息列表，每项包含 file, timestamp, size
        """
        versions = []
        for meta_file in sorted(self.history_dir.glob("meta.*.json"), reverse=True):
            versions.append(
                {
                    "file": meta_file.name,
                    "timestamp": meta_file.stat().st_mtime,
                    "size": meta_file.stat().st_size,
                    "path": str(meta_file),
                }
            )
        return versions

    def rollback_to_version(self, version_file: str):
        """
        回滚到指定版本

        Args:
            version_file: 版本文件名 (例如: meta.20260108_143022.json)

        Raises:
            FileNotFoundError: 如果版本文件不存在
        """
        src = self.history_dir / version_file
        if not src.exists():
            raise FileNotFoundError(f"版本文件不存在: {version_file}")

        # 备份当前版本（如果存在）
        if self.current_meta_file.exists():
            logger.info("备份当前版本...")
            self.backup_to_history()

        # 恢复指定版本
        shutil.copy2(src, self.current_meta_file)
        logger.info(f"已回滚到版本: {version_file}")

    def update_compose_hash(self, compose_path: Path):
        """
        更新 compose 文件的哈希值

        Args:
            compose_path: compose 文件路径
        """
        new_hash = self.compute_compose_hash(compose_path)
        self.compose_hash_file.write_text(new_hash, encoding="utf-8")
        logger.debug(f"已更新 compose 哈希: {new_hash[:8]}...")

    def backup_compose_file(self, compose_path: Path):
        """
        备份 compose 文件（用于下次对比）

        Args:
            compose_path: compose 文件路径
        """
        if compose_path.exists():
            shutil.copy2(compose_path, self.compose_backup_file)
            logger.debug(f"已备份 compose 文件到: {self.compose_backup_file}")

    def get_backed_up_compose(self) -> Optional[Path]:
        """
        获取备份的 compose 文件路径

        Returns:
            备份文件路径，如果不存在则返回 None
        """
        if self.compose_backup_file.exists():
            return self.compose_backup_file
        return None
