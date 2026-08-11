"""ConfigService — load, read, write, persist, and reload application config."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable

import yaml
from pydantic import BaseModel

from app.config.schema import AppConfig

log = logging.getLogger(__name__)

# 环境变量前缀
_ENV_PREFIX = "SHOREKEEPER_"

# 数据目录：优先环境变量，默认 ~/.shorekeeper/
_DEFAULT_DATA_DIR = Path(
    os.environ.get("SHOREKEEPER_DATA_DIR", str(Path.home() / ".shorekeeper"))
)


class ConfigService:
    """Singleton service for application configuration.

    Priority: .env (via pydantic env vars) > config.yaml > defaults.
    Runtime changes are persisted to config.yaml and trigger reload callbacks.
    """

    _instance: ConfigService | None = None
    _lock = threading.Lock()

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir or _DEFAULT_DATA_DIR
        self._config_file = self._data_dir / "config.yaml"
        self._callbacks: list[Callable[[str, Any], None]] = []
        # 确保数据目录存在
        self._data_dir.mkdir(parents=True, exist_ok=True)
        (self._data_dir / "skills").mkdir(exist_ok=True)
        (self._data_dir / "logs").mkdir(exist_ok=True)
        self._app_config = self._load()

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls, data_dir: Path | None = None) -> ConfigService:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(data_dir=data_dir)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for testing)."""
        with cls._lock:
            cls._instance = None

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    def _load(self) -> AppConfig:
        """Load config from YAML file, then override with environment variables."""
        raw: dict[str, Any] = {}

        # 1. 从 YAML 文件加载
        if self._config_file.exists():
            try:
                loaded = yaml.safe_load(self._config_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    raw = loaded
                else:
                    log.warning("config.yaml is not a dict, using defaults")
            except Exception:
                log.exception("Failed to parse config.yaml, using defaults")
        else:
            log.info("config.yaml not found, creating with defaults")

        # 2. 用环境变量覆盖（格式：SHOREKEEPER_SECTION_KEY）
        raw = self._apply_env_overrides(raw)

        # 3. 验证并返回
        config = AppConfig.model_validate(raw)
        if not self._config_file.exists():
            self._save(config)
        return config

    @staticmethod
    def _apply_env_overrides(raw: dict[str, Any]) -> dict[str, Any]:
        """用 SHOREKEEPER_ 前缀的环境变量覆盖配置。

        格式：SHOREKEEPER_SECTION_KEY → config.section.key
        例如：SHOREKEEPER_LOG_LEVEL → log.level

        注意：SHOREKEEPER_RUNTIME_*（旧模型配置）已废弃，
        模型配置迁移至数据库（models_config 模块），不再支持环境变量覆盖。
        """
        for key, value in os.environ.items():
            if not key.startswith(_ENV_PREFIX):
                continue
            parts = key[len(_ENV_PREFIX):].lower().split("_", 1)
            if len(parts) != 2:
                continue
            section, field = parts
            if section == "runtime":
                # 旧 runtime 段已废弃，跳过（避免在配置中产生无用 runtime 键）
                continue
            if section not in raw:
                raw[section] = {}
            if isinstance(raw[section], dict):
                raw[section][field] = value
                log.debug("Config override from env: %s.%s", section, field)
        return raw

    def _save(self, config: AppConfig) -> None:
        """Persist config to YAML file."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        data = config.model_dump()
        self._config_file.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    def reload(self) -> None:
        """Reload config from disk."""
        self._app_config = self._load()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    @property
    def data_dir(self) -> Path:
        """数据根目录。"""
        return self._data_dir

    @property
    def config(self) -> AppConfig:
        return self._app_config

    def get(self, key: str) -> Any:
        """Get a config value by dot-separated key (e.g. 'server.port')."""
        parts = key.split(".")
        obj: Any = self._app_config
        for part in parts:
            if isinstance(obj, BaseModel) and part in type(obj).model_fields:
                obj = getattr(obj, part)
            else:
                raise KeyError(f"Config key not found: {key}")
        return obj

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def set(self, key: str, value: Any) -> None:
        """Set a config value by dot-separated key, validate, persist, and notify."""
        parts = key.split(".")
        if len(parts) < 2:
            raise ValueError(f"Config key must be in 'group.field' format: {key}")

        group_name = parts[0]
        field_name = parts[1]

        # Validate the group exists
        if not isinstance(self._app_config, BaseModel) or group_name not in type(self._app_config).model_fields:
            raise KeyError(f"Config group not found: {group_name}")

        group_obj = getattr(self._app_config, group_name)
        if not isinstance(group_obj, BaseModel) or field_name not in type(group_obj).model_fields:
            raise KeyError(f"Config field not found: {key}")

        # Build updated group with new value to trigger Pydantic validation
        group_data = group_obj.model_dump()
        group_data[field_name] = value
        updated_group = type(group_obj).model_validate(group_data)

        # Apply to app config
        setattr(self._app_config, group_name, updated_group)

        # Validate whole config
        self._app_config = AppConfig.model_validate(self._app_config.model_dump())

        # Persist
        self._save(self._app_config)

        # Notify callbacks
        for cb in self._callbacks:
            try:
                cb(key, value)
            except Exception:
                log.exception("Config reload callback failed for key=%s", key)

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset all config to defaults and persist."""
        self._app_config = AppConfig()
        self._save(self._app_config)
        for cb in self._callbacks:
            try:
                cb("*", None)
            except Exception:
                log.exception("Config reload callback failed during reset")

    # ------------------------------------------------------------------
    # Reload callbacks
    # ------------------------------------------------------------------

    def on_change(self, callback: Callable[[str, Any], None]) -> None:
        """Register a callback for config changes."""
        self._callbacks.append(callback)
