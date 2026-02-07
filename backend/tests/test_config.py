"""
Tests for the configuration module.
"""

import os
from pathlib import Path

import pytest
import yaml

from ungula.config import (
    DatabaseConfig,
    EmbeddingsConfig,
    LLMConfig,
    RedisConfig,
    ServerConfig,
    Settings,
    UngulaConfig,
    get_ungula_home,
    get_workspace_dir,
    init_ungula_dirs,
    load_config,
    load_workspace_file,
    load_yaml_config,
    merge_configs,
    save_config,
    save_workspace_file,
)


class TestConfigModels:
    """Tests for configuration Pydantic models."""

    def test_database_config_defaults(self):
        """Test DatabaseConfig has correct defaults."""
        config = DatabaseConfig()
        assert config.type == "sqlite"
        assert config.path == "ungula.db"

    def test_redis_config_defaults(self):
        """Test RedisConfig has correct defaults."""
        config = RedisConfig()
        assert config.host == "localhost"
        assert config.port == 6379
        assert config.db == 0
        assert config.password is None

    def test_embeddings_config_defaults(self):
        """Test EmbeddingsConfig has correct defaults."""
        config = EmbeddingsConfig()
        assert config.provider == "local"
        assert config.model == "all-MiniLM-L6-v2"
        assert config.openai_api_key is None

    def test_llm_config_defaults(self):
        """Test LLMConfig has correct defaults."""
        config = LLMConfig()
        assert config.default_provider == "openrouter"
        assert config.openrouter.enabled is True
        assert config.ollama.base_url == "http://localhost:11434"

    def test_server_config_defaults(self):
        """Test ServerConfig has correct defaults."""
        config = ServerConfig()
        assert config.host == "0.0.0.0"
        assert config.port == 8001
        assert config.reload is False
        assert config.workers == 1
        assert "http://localhost:3000" in config.cors_origins

    def test_ungula_config_defaults(self):
        """Test UngulaConfig has correct defaults."""
        config = UngulaConfig()
        assert isinstance(config.database, DatabaseConfig)
        assert isinstance(config.redis, RedisConfig)
        assert isinstance(config.embeddings, EmbeddingsConfig)
        assert isinstance(config.llm, LLMConfig)
        assert isinstance(config.server, ServerConfig)
        assert config.agents == []
        assert config.personas == []
        assert config.nodes == []


class TestSettings:
    """Tests for Settings class."""

    def test_settings_from_env(self, ungula_home: Path):
        """Test Settings loads from environment variables."""
        os.environ["UNGULA_SERVER_PORT"] = "9000"
        os.environ["UNGULA_REDIS_HOST"] = "redis.example.com"

        try:
            settings = Settings()
            assert settings.server_port == 9000
            assert settings.redis_host == "redis.example.com"
        finally:
            del os.environ["UNGULA_SERVER_PORT"]
            del os.environ["UNGULA_REDIS_HOST"]

    def test_settings_home_from_env(self, temp_dir: Path):
        """Test Settings uses UNGULA_HOME from environment."""
        test_home = temp_dir / "custom_home"
        test_home.mkdir()
        os.environ["UNGULA_HOME"] = str(test_home)

        try:
            settings = Settings()
            assert settings.home == test_home
        finally:
            del os.environ["UNGULA_HOME"]


class TestPathFunctions:
    """Tests for path utility functions."""

    def test_get_ungula_home(self, ungula_home: Path):
        """Test get_ungula_home returns correct path."""
        assert get_ungula_home() == ungula_home

    def test_get_workspace_dir(self, ungula_home: Path):
        """Test get_workspace_dir returns correct path."""
        assert get_workspace_dir() == ungula_home / "workspace"


class TestInitDirs:
    """Tests for directory initialization."""

    def test_init_ungula_dirs(self, ungula_home: Path):
        """Test init_ungula_dirs creates all directories."""
        # Remove existing dirs
        import shutil

        shutil.rmtree(ungula_home)

        # Re-initialize
        init_ungula_dirs()

        # Check directories exist
        assert ungula_home.exists()
        assert (ungula_home / "workspace").exists()
        assert (ungula_home / "workspace" / "memory").exists()
        assert (ungula_home / "data").exists()
        assert (ungula_home / "logs").exists()
        assert (ungula_home / "skills").exists()
        assert (ungula_home / "nodes").exists()


class TestYamlConfig:
    """Tests for YAML configuration loading."""

    def test_load_yaml_config_nonexistent(self, temp_dir: Path):
        """Test loading nonexistent YAML file returns empty dict."""
        result = load_yaml_config(temp_dir / "nonexistent.yaml")
        assert result == {}

    def test_load_yaml_config_valid(self, temp_dir: Path):
        """Test loading valid YAML file."""
        config_path = temp_dir / "config.yaml"
        config_path.write_text(
            yaml.dump(
                {
                    "server": {"port": 9000},
                    "redis": {"host": "redis.example.com"},
                }
            )
        )

        result = load_yaml_config(config_path)
        assert result["server"]["port"] == 9000
        assert result["redis"]["host"] == "redis.example.com"

    def test_load_yaml_config_empty(self, temp_dir: Path):
        """Test loading empty YAML file returns empty dict."""
        config_path = temp_dir / "empty.yaml"
        config_path.write_text("")

        result = load_yaml_config(config_path)
        assert result == {}


class TestMergeConfigs:
    """Tests for configuration merging."""

    def test_merge_configs_simple(self):
        """Test simple config merge."""
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}

        result = merge_configs(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_merge_configs_nested(self):
        """Test nested config merge."""
        base = {"server": {"host": "localhost", "port": 8000}}
        override = {"server": {"port": 9000}}

        result = merge_configs(base, override)
        assert result == {"server": {"host": "localhost", "port": 9000}}

    def test_merge_configs_deep_nested(self):
        """Test deeply nested config merge."""
        base = {"a": {"b": {"c": 1, "d": 2}}}
        override = {"a": {"b": {"d": 3}}}

        result = merge_configs(base, override)
        assert result == {"a": {"b": {"c": 1, "d": 3}}}


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_defaults(self, ungula_home: Path):
        """Test load_config returns defaults when no config file exists."""
        config = load_config()
        assert isinstance(config, UngulaConfig)
        assert config.server.port == 8001

    def test_load_config_from_file(self, ungula_home: Path):
        """Test load_config reads from config file."""
        config_path = ungula_home / "config.yaml"
        config_path.write_text(
            yaml.dump(
                {
                    "server": {"port": 9000},
                    "database": {"path": "custom.db"},
                }
            )
        )

        config = load_config()
        assert config.server.port == 9000
        assert config.database.path == "custom.db"

    def test_load_config_env_override(self, ungula_home: Path):
        """Test environment variables override config file."""
        config_path = ungula_home / "config.yaml"
        config_path.write_text(yaml.dump({"server": {"port": 8000}}))

        os.environ["UNGULA_SERVER_PORT"] = "9999"

        try:
            config = load_config()
            assert config.server.port == 9999
        finally:
            del os.environ["UNGULA_SERVER_PORT"]


class TestSaveConfig:
    """Tests for save_config function."""

    def test_save_config(self, ungula_home: Path):
        """Test save_config writes configuration to file."""
        config = UngulaConfig(
            server=ServerConfig(port=9000),
            database=DatabaseConfig(path="custom.db"),
        )

        save_config(config)

        config_path = ungula_home / "config.yaml"
        assert config_path.exists()

        loaded = yaml.safe_load(config_path.read_text())
        assert loaded["server"]["port"] == 9000
        assert loaded["database"]["path"] == "custom.db"


class TestWorkspaceFiles:
    """Tests for workspace file operations."""

    def test_load_workspace_file_nonexistent(self, ungula_home: Path):
        """Test loading nonexistent workspace file returns None."""
        result = load_workspace_file("NONEXISTENT.md")
        assert result is None

    def test_save_and_load_workspace_file(self, ungula_home: Path):
        """Test saving and loading workspace file."""
        content = "# Test Content\n\nThis is a test."

        save_workspace_file("TEST.md", content)
        result = load_workspace_file("TEST.md")

        assert result == content

    def test_workspace_file_path(self, ungula_home: Path):
        """Test workspace files are saved in correct location."""
        save_workspace_file("SOUL.md", "# Soul")

        expected_path = ungula_home / "workspace" / "SOUL.md"
        assert expected_path.exists()
        assert expected_path.read_text() == "# Soul"
