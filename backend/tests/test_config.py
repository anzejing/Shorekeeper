"""Tests for configuration module."""

import pytest
from pathlib import Path
from pydantic import ValidationError

from app.config.schema import AppConfig
from app.config.service import ConfigService
from app.config.meta import build_config_items


@pytest.fixture(autouse=True)
def isolate_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Use a temporary directory for config files to isolate tests.

    清除 SHOREKEEPER_ 环境变量，避免 .env 文件干扰测试。
    """
    # 清除所有 SHOREKEEPER_ 开头的环境变量
    for key in list(__import__("os").environ):
        if key.startswith("SHOREKEEPER_"):
            monkeypatch.delenv(key, raising=False)

    ConfigService.reset_instance()
    yield tmp_path
    ConfigService.reset_instance()


class TestAppConfig:
    def test_defaults(self):
        config = AppConfig()
        assert config.server.host == "0.0.0.0"
        assert config.server.port == 8000
        assert config.log.level == "INFO"
        assert config.ui.theme == "system"

    def test_validation_port_range(self):
        with pytest.raises(ValidationError):
            AppConfig.model_validate({"server": {"port": 99999}})

    def test_validation_search_max_results_range(self):
        with pytest.raises(ValidationError):
            AppConfig.model_validate({"search": {"max_results": 99}})


class TestConfigService:
    def test_singleton(self, tmp_path: Path):
        svc1 = ConfigService.get_instance(data_dir=tmp_path)
        svc2 = ConfigService.get_instance(data_dir=tmp_path)
        assert svc1 is svc2

    def test_get(self, tmp_path: Path):
        svc = ConfigService.get_instance(data_dir=tmp_path)
        assert svc.get("server.port") == 8000
        assert svc.get("search.max_results") == 10

    def test_get_invalid_key(self, tmp_path: Path):
        svc = ConfigService.get_instance(data_dir=tmp_path)
        with pytest.raises(KeyError):
            svc.get("nonexistent.field")

    def test_set_and_get(self, tmp_path: Path):
        svc = ConfigService.get_instance(data_dir=tmp_path)
        svc.set("server.port", 9000)
        assert svc.get("server.port") == 9000

    def test_set_invalid_value(self, tmp_path: Path):
        svc = ConfigService.get_instance(data_dir=tmp_path)
        with pytest.raises((ValidationError, ValueError)):
            svc.set("server.port", 99999)

    def test_set_invalid_key(self, tmp_path: Path):
        svc = ConfigService.get_instance(data_dir=tmp_path)
        with pytest.raises(KeyError):
            svc.set("nonexistent.field", "value")

    def test_set_triggers_callback(self, tmp_path: Path):
        svc = ConfigService.get_instance(data_dir=tmp_path)
        events: list[tuple] = []
        svc.on_change(lambda k, v: events.append((k, v)))
        svc.set("log.level", "DEBUG")
        assert events == [("log.level", "DEBUG")]

    def test_reset(self, tmp_path: Path):
        svc = ConfigService.get_instance(data_dir=tmp_path)
        svc.set("server.port", 9000)
        svc.reset()
        assert svc.get("server.port") == 8000

    def test_persistence(self, tmp_path: Path):
        svc = ConfigService.get_instance(data_dir=tmp_path)
        svc.set("server.port", 9000)

        # Create a new instance from the same dir — should load persisted value
        ConfigService.reset_instance()
        svc2 = ConfigService.get_instance(data_dir=tmp_path)
        assert svc2.get("server.port") == 9000

    def test_creates_config_yaml_on_first_run(self, tmp_path: Path):
        ConfigService.get_instance(data_dir=tmp_path)
        assert (tmp_path / "config.yaml").exists()


class TestBuildConfigItems:
    def test_returns_groups(self, tmp_path: Path):
        svc = ConfigService.get_instance(data_dir=tmp_path)
        items = build_config_items(svc.config)
        group_names = [g["group"] for g in items]
        assert "服务器" in group_names
        assert "日志" in group_names
        assert "Runtime" not in group_names  # 模型配置已迁移至数据库

    def test_select_type_has_options(self, tmp_path: Path):
        svc = ConfigService.get_instance(data_dir=tmp_path)
        items = build_config_items(svc.config)
        log_group = next(g for g in items if g["group"] == "日志")
        level_item = next(i for i in log_group["items"] if i["key"] == "log.level")
        assert level_item["type"] == "select"
        assert "DEBUG" in level_item["options"]
