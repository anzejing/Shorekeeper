"""ConfigService — load, read, write, persist, and reload application config."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable

import yaml
from pydantic import BaseModel

from app.config.schema import AppConfig

log = logging.getLogger(__name__)

# Default config file path
_DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "data"


class ConfigService:
    """Singleton service for application configuration.

    Priority: .env (via pydantic env vars) > config.yaml > defaults.
    Runtime changes are persisted to config.yaml and trigger reload callbacks.
    """

    _instance: ConfigService | None = None
    _lock = threading.Lock()

    def __init__(self, config_dir: Path | None = None) -> None:
        self._config_dir = config_dir or _DEFAULT_CONFIG_DIR
        self._config_file = self._config_dir / "config.yaml"
        self._callbacks: list[Callable[[str, Any], None]] = []
        self._app_config = self._load()

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls, config_dir: Path | None = None) -> ConfigService:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(config_dir=config_dir)
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
        """Load config from YAML file, falling back to defaults."""
        if self._config_file.exists():
            try:
                raw = yaml.safe_load(self._config_file.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return AppConfig.model_validate(raw)
                log.warning("config.yaml is not a dict, using defaults")
            except Exception:
                log.exception("Failed to parse config.yaml, using defaults")
        else:
            log.info("config.yaml not found, creating with defaults")
            self._save(AppConfig())
        return AppConfig()

    def _save(self, config: AppConfig) -> None:
        """Persist config to YAML file."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
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
