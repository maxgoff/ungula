"""
Tests for the plugin architecture: types, loader, registry, installer, manager.

Covers plugin manifest parsing, directory scanning, plugin registration delegation,
plugin installation/uninstallation, and the manager orchestration layer.
"""

import shutil
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from ungula.plugins.installer import PluginInstaller
from ungula.plugins.loader import PluginLoader
from ungula.plugins.manager import PluginManager
from ungula.plugins.registry import PluginRegistry
from ungula.plugins.types import LoadedPlugin, PluginManifest, PluginType


# ===========================================================================
# PluginType
# ===========================================================================


class TestPluginType:
    """Tests for PluginType enum."""

    def test_channel_value(self):
        assert PluginType.CHANNEL.value == "channel"

    def test_tool_value(self):
        assert PluginType.TOOL.value == "tool"

    def test_provider_value(self):
        assert PluginType.PROVIDER.value == "provider"

    def test_memory_value(self):
        assert PluginType.MEMORY.value == "memory"

    def test_all_values(self):
        values = {pt.value for pt in PluginType}
        assert values == {"channel", "tool", "provider", "memory"}


# ===========================================================================
# PluginManifest
# ===========================================================================


class TestPluginManifest:
    """Tests for PluginManifest Pydantic model."""

    def test_minimal_manifest(self):
        m = PluginManifest(name="test-plugin", type=PluginType.TOOL)
        assert m.name == "test-plugin"
        assert m.type == PluginType.TOOL
        assert m.version == "0.0.0"
        assert m.entry_point == "main.py"
        assert m.config_schema == {}
        assert m.requires == {}

    def test_full_manifest(self):
        m = PluginManifest(
            name="my-channel",
            version="1.2.3",
            type=PluginType.CHANNEL,
            description="A custom channel",
            entry_point="channel.py",
            config_schema={"type": "object", "properties": {"api_key": {"type": "string"}}},
            requires={"python": ">=3.11", "packages": ["some-lib>=1.0"]},
        )
        assert m.name == "my-channel"
        assert m.version == "1.2.3"
        assert m.type == PluginType.CHANNEL
        assert m.description == "A custom channel"
        assert m.entry_point == "channel.py"
        assert "api_key" in m.config_schema["properties"]

    def test_from_dict(self):
        data = {
            "name": "from-dict",
            "type": "tool",
            "version": "0.1.0",
        }
        m = PluginManifest(**data)
        assert m.name == "from-dict"
        assert m.type == PluginType.TOOL

    def test_missing_name_raises(self):
        with pytest.raises(Exception):
            PluginManifest(type=PluginType.TOOL)

    def test_missing_type_raises(self):
        with pytest.raises(Exception):
            PluginManifest(name="test")

    def test_invalid_type_raises(self):
        with pytest.raises(Exception):
            PluginManifest(name="test", type="invalid")


# ===========================================================================
# LoadedPlugin
# ===========================================================================


class TestLoadedPlugin:
    """Tests for LoadedPlugin dataclass."""

    def test_properties(self):
        manifest = PluginManifest(name="test", type=PluginType.TOOL)
        plugin = LoadedPlugin(manifest=manifest, plugin_dir=Path("/tmp/test"))
        assert plugin.name == "test"
        assert plugin.plugin_type == PluginType.TOOL
        assert plugin.enabled is False
        assert plugin.module is None
        assert plugin.error is None

    def test_to_dict(self):
        manifest = PluginManifest(name="test", version="1.0", type=PluginType.CHANNEL, description="desc")
        plugin = LoadedPlugin(manifest=manifest, plugin_dir=Path("/plugins/test"), enabled=True)
        d = plugin.to_dict()
        assert d["name"] == "test"
        assert d["version"] == "1.0"
        assert d["type"] == "channel"
        assert d["description"] == "desc"
        assert d["enabled"] is True
        assert d["path"] == "/plugins/test"
        assert d["error"] is None

    def test_to_dict_with_error(self):
        manifest = PluginManifest(name="broken", type=PluginType.TOOL)
        plugin = LoadedPlugin(manifest=manifest, plugin_dir=Path("/tmp"), error="failed to load")
        d = plugin.to_dict()
        assert d["error"] == "failed to load"


# ===========================================================================
# PluginLoader
# ===========================================================================


class TestPluginLoader:
    """Tests for plugin directory scanning and loading."""

    @pytest.fixture
    def plugin_dir(self, tmp_path: Path) -> Path:
        """Create a plugin directory with test plugins."""
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        return plugins

    def _create_plugin(self, plugins_dir: Path, name: str, ptype: str = "tool",
                       entry_content: str | None = None, manifest_extra: dict | None = None) -> Path:
        """Helper to create a plugin directory with plugin.yaml."""
        pdir = plugins_dir / name
        pdir.mkdir()
        manifest = {"name": name, "type": ptype, "version": "1.0.0"}
        if manifest_extra:
            manifest.update(manifest_extra)
        (pdir / "plugin.yaml").write_text(yaml.dump(manifest))
        if entry_content is not None:
            (pdir / "main.py").write_text(entry_content)
        return pdir

    def test_scan_empty_directory(self, plugin_dir: Path):
        loader = PluginLoader()
        plugins = loader.scan_directories([plugin_dir])
        assert plugins == []

    def test_scan_finds_plugin(self, plugin_dir: Path):
        self._create_plugin(plugin_dir, "my-tool")
        loader = PluginLoader()
        plugins = loader.scan_directories([plugin_dir])
        assert len(plugins) == 1
        assert plugins[0].name == "my-tool"

    def test_scan_multiple_plugins(self, plugin_dir: Path):
        self._create_plugin(plugin_dir, "tool-a")
        self._create_plugin(plugin_dir, "tool-b", "channel")
        loader = PluginLoader()
        plugins = loader.scan_directories([plugin_dir])
        assert len(plugins) == 2
        names = {p.name for p in plugins}
        assert names == {"tool-a", "tool-b"}

    def test_scan_skips_non_directory(self, plugin_dir: Path):
        (plugin_dir / "random_file.txt").write_text("not a plugin")
        loader = PluginLoader()
        plugins = loader.scan_directories([plugin_dir])
        assert plugins == []

    def test_scan_skips_dir_without_manifest(self, plugin_dir: Path):
        (plugin_dir / "no-manifest").mkdir()
        (plugin_dir / "no-manifest" / "main.py").write_text("# nothing")
        loader = PluginLoader()
        plugins = loader.scan_directories([plugin_dir])
        assert plugins == []

    def test_scan_yml_extension(self, plugin_dir: Path):
        """plugin.yml should also be recognized."""
        pdir = plugin_dir / "yml-plugin"
        pdir.mkdir()
        manifest = {"name": "yml-plugin", "type": "tool", "version": "0.1"}
        (pdir / "plugin.yml").write_text(yaml.dump(manifest))
        loader = PluginLoader()
        plugins = loader.scan_directories([pdir.parent])
        assert len(plugins) == 1
        assert plugins[0].name == "yml-plugin"

    def test_scan_invalid_manifest(self, plugin_dir: Path):
        pdir = plugin_dir / "bad-plugin"
        pdir.mkdir()
        (pdir / "plugin.yaml").write_text("this is not valid: yaml: [")
        loader = PluginLoader()
        plugins = loader.scan_directories([plugin_dir])
        # Should still load with an error
        assert len(plugins) == 1
        assert plugins[0].error is not None

    def test_scan_invalid_manifest_fields(self, plugin_dir: Path):
        pdir = plugin_dir / "bad-fields"
        pdir.mkdir()
        (pdir / "plugin.yaml").write_text(yaml.dump({"name": "test", "type": "bogus_type"}))
        loader = PluginLoader()
        plugins = loader.scan_directories([plugin_dir])
        assert len(plugins) == 1
        assert plugins[0].error is not None

    def test_scan_loads_entry_module(self, plugin_dir: Path):
        self._create_plugin(plugin_dir, "with-entry", entry_content="LOADED = True\n")
        loader = PluginLoader()
        plugins = loader.scan_directories([plugin_dir])
        assert len(plugins) == 1
        assert plugins[0].module is not None
        assert getattr(plugins[0].module, "LOADED", None) is True

    def test_scan_no_entry_file(self, plugin_dir: Path):
        self._create_plugin(plugin_dir, "no-entry")
        loader = PluginLoader()
        plugins = loader.scan_directories([plugin_dir])
        assert len(plugins) == 1
        assert plugins[0].module is None
        assert plugins[0].error is None  # Not an error — just no module

    def test_scan_bad_entry_module(self, plugin_dir: Path):
        self._create_plugin(plugin_dir, "bad-entry", entry_content="raise RuntimeError('boom')")
        loader = PluginLoader()
        plugins = loader.scan_directories([plugin_dir])
        assert len(plugins) == 1
        assert plugins[0].error is not None
        assert "Module load error" in plugins[0].error

    def test_scan_nonexistent_directory(self):
        loader = PluginLoader()
        plugins = loader.scan_directories([Path("/nonexistent/dir")])
        assert plugins == []

    def test_scan_multiple_directories(self, tmp_path: Path):
        dir1 = tmp_path / "dir1"
        dir1.mkdir()
        dir2 = tmp_path / "dir2"
        dir2.mkdir()
        self._create_plugin(dir1, "plugin-a")
        self._create_plugin(dir2, "plugin-b", "channel")
        loader = PluginLoader()
        plugins = loader.scan_directories([dir1, dir2])
        assert len(plugins) == 2


# ===========================================================================
# PluginRegistry
# ===========================================================================


class TestPluginRegistry:
    """Tests for plugin registration delegation."""

    def test_register_tool_plugin(self):
        from ungula.tools.base import Tool, ToolResult

        class FakeTool(Tool):
            name = "fake"
            description = "Fake tool"
            parameters = []
            async def execute(self, **kwargs: Any) -> ToolResult:
                return ToolResult(success=True, output="ok")

        # Create a module-like object
        import types
        module = types.ModuleType("fake_module")
        module.FakeTool = FakeTool

        tool_registry = MagicMock()
        plugin_registry = PluginRegistry(tool_registry=tool_registry)
        manifest = PluginManifest(name="tool-plugin", type=PluginType.TOOL)
        plugin = LoadedPlugin(manifest=manifest, plugin_dir=Path("/tmp"), module=module)

        result = plugin_registry.register_plugin(plugin)
        assert result is True
        tool_registry.register.assert_called_once()

    def test_register_plugin_without_module(self):
        plugin_registry = PluginRegistry()
        manifest = PluginManifest(name="no-module", type=PluginType.TOOL)
        plugin = LoadedPlugin(manifest=manifest, plugin_dir=Path("/tmp"))
        result = plugin_registry.register_plugin(plugin)
        assert result is False

    def test_register_channel_plugin(self):
        import types
        module = types.ModuleType("channel_mod")
        module.register = MagicMock()

        channel_registry = MagicMock()
        plugin_registry = PluginRegistry(channel_registry=channel_registry)
        manifest = PluginManifest(name="chan-plugin", type=PluginType.CHANNEL)
        plugin = LoadedPlugin(manifest=manifest, plugin_dir=Path("/tmp"), module=module)

        result = plugin_registry.register_plugin(plugin)
        assert result is True
        module.register.assert_called_once_with(channel_registry)

    def test_register_provider_plugin(self):
        import types
        module = types.ModuleType("provider_mod")
        module.register = MagicMock()

        provider_registry = MagicMock()
        plugin_registry = PluginRegistry(provider_registry=provider_registry)
        manifest = PluginManifest(name="prov-plugin", type=PluginType.PROVIDER)
        plugin = LoadedPlugin(manifest=manifest, plugin_dir=Path("/tmp"), module=module)

        result = plugin_registry.register_plugin(plugin)
        assert result is True
        module.register.assert_called_once_with(provider_registry)

    def test_register_memory_plugin_unsupported(self):
        import types
        module = types.ModuleType("memory_mod")

        plugin_registry = PluginRegistry()
        manifest = PluginManifest(name="mem-plugin", type=PluginType.MEMORY)
        plugin = LoadedPlugin(manifest=manifest, plugin_dir=Path("/tmp"), module=module)

        result = plugin_registry.register_plugin(plugin)
        assert result is False

    def test_register_tool_no_registry(self):
        import types
        module = types.ModuleType("tool_mod")

        plugin_registry = PluginRegistry(tool_registry=None)
        manifest = PluginManifest(name="tool-p", type=PluginType.TOOL)
        plugin = LoadedPlugin(manifest=manifest, plugin_dir=Path("/tmp"), module=module)

        result = plugin_registry.register_plugin(plugin)
        assert result is False

    def test_register_channel_no_register_function(self):
        import types
        module = types.ModuleType("chan_mod_no_register")

        channel_registry = MagicMock()
        plugin_registry = PluginRegistry(channel_registry=channel_registry)
        manifest = PluginManifest(name="chan-no-reg", type=PluginType.CHANNEL)
        plugin = LoadedPlugin(manifest=manifest, plugin_dir=Path("/tmp"), module=module)

        result = plugin_registry.register_plugin(plugin)
        assert result is False


# ===========================================================================
# PluginInstaller
# ===========================================================================


class TestPluginInstaller:
    """Tests for plugin installation and uninstallation."""

    @pytest.fixture
    def install_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "installed"
        d.mkdir()
        return d

    @pytest.fixture
    def installer(self, install_dir: Path) -> PluginInstaller:
        return PluginInstaller(install_dir)

    @pytest.fixture
    def source_plugin(self, tmp_path: Path) -> Path:
        src = tmp_path / "source-plugin"
        src.mkdir()
        manifest = {"name": "test-installer", "type": "tool", "version": "1.0"}
        (src / "plugin.yaml").write_text(yaml.dump(manifest))
        (src / "main.py").write_text("# plugin code\n")
        return src

    def test_install_from_path(self, installer: PluginInstaller, source_plugin: Path, install_dir: Path):
        result = installer.install_from_path(source_plugin)
        assert result["success"] is True
        assert result["name"] == "test-installer"
        assert (install_dir / "test-installer" / "plugin.yaml").exists()
        assert (install_dir / "test-installer" / "main.py").exists()

    def test_install_no_manifest(self, installer: PluginInstaller, tmp_path: Path):
        empty = tmp_path / "empty-plugin"
        empty.mkdir()
        result = installer.install_from_path(empty)
        assert result["success"] is False
        assert "No plugin.yaml" in result["error"]

    def test_install_invalid_manifest(self, installer: PluginInstaller, tmp_path: Path):
        bad = tmp_path / "bad-manifest"
        bad.mkdir()
        (bad / "plugin.yaml").write_text("not valid yaml [[[")
        result = installer.install_from_path(bad)
        assert result["success"] is False

    def test_install_overwrites_existing(self, installer: PluginInstaller, source_plugin: Path, install_dir: Path):
        # Install once
        installer.install_from_path(source_plugin)
        # Modify source and re-install
        (source_plugin / "extra.txt").write_text("new file")
        result = installer.install_from_path(source_plugin)
        assert result["success"] is True
        assert (install_dir / "test-installer" / "extra.txt").exists()

    def test_uninstall(self, installer: PluginInstaller, source_plugin: Path, install_dir: Path):
        installer.install_from_path(source_plugin)
        assert (install_dir / "test-installer").exists()
        result = installer.uninstall("test-installer")
        assert result is True
        assert not (install_dir / "test-installer").exists()

    def test_uninstall_nonexistent(self, installer: PluginInstaller):
        result = installer.uninstall("no-such-plugin")
        assert result is False

    def test_install_with_packages(self, installer: PluginInstaller, tmp_path: Path):
        """Test that package installation is attempted (mocked)."""
        src = tmp_path / "pkg-plugin"
        src.mkdir()
        manifest = {
            "name": "pkg-plugin",
            "type": "tool",
            "version": "1.0",
            "requires": {"packages": ["nonexistent-pkg-12345"]},
        }
        (src / "plugin.yaml").write_text(yaml.dump(manifest))
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = installer.install_from_path(src)
            assert result["success"] is True
            mock_run.assert_called_once()

    def test_install_dir_created(self, tmp_path: Path):
        new_dir = tmp_path / "new_install_dir"
        installer = PluginInstaller(new_dir)
        assert new_dir.exists()


# ===========================================================================
# PluginManager
# ===========================================================================


class TestPluginManager:
    """Tests for the plugin manager orchestration."""

    @pytest.fixture
    def plugin_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "plugins"
        d.mkdir()
        return d

    def _create_plugin(self, plugins_dir: Path, name: str, ptype: str = "tool") -> Path:
        pdir = plugins_dir / name
        pdir.mkdir()
        manifest = {"name": name, "type": ptype, "version": "1.0.0"}
        (pdir / "plugin.yaml").write_text(yaml.dump(manifest))
        return pdir

    @pytest.fixture
    def manager(self, plugin_dir: Path) -> PluginManager:
        registry = PluginRegistry()
        return PluginManager(plugin_dirs=[plugin_dir], plugin_registry=registry)

    @pytest.mark.asyncio
    async def test_discover(self, manager: PluginManager, plugin_dir: Path):
        self._create_plugin(plugin_dir, "disc-tool")
        plugins = await manager.discover()
        assert len(plugins) == 1
        assert plugins[0].name == "disc-tool"

    @pytest.mark.asyncio
    async def test_discover_empty(self, manager: PluginManager):
        plugins = await manager.discover()
        assert plugins == []

    @pytest.mark.asyncio
    async def test_list_plugins(self, manager: PluginManager, plugin_dir: Path):
        self._create_plugin(plugin_dir, "list-tool")
        await manager.discover()
        plugins = manager.list_plugins()
        assert len(plugins) == 1
        assert plugins[0]["name"] == "list-tool"

    @pytest.mark.asyncio
    async def test_get_plugin(self, manager: PluginManager, plugin_dir: Path):
        self._create_plugin(plugin_dir, "get-me")
        await manager.discover()
        plugin = manager.get_plugin("get-me")
        assert plugin is not None
        assert plugin.name == "get-me"

    def test_get_plugin_not_found(self, manager: PluginManager):
        assert manager.get_plugin("nonexistent") is None

    @pytest.mark.asyncio
    async def test_enable(self, manager: PluginManager, plugin_dir: Path):
        self._create_plugin(plugin_dir, "to-enable")
        await manager.discover()
        result = manager.enable("to-enable")
        assert result is True
        assert manager.get_plugin("to-enable").enabled is True

    def test_enable_nonexistent(self, manager: PluginManager):
        assert manager.enable("nope") is False

    @pytest.mark.asyncio
    async def test_enable_errored_plugin(self, manager: PluginManager, plugin_dir: Path):
        pdir = plugin_dir / "broken"
        pdir.mkdir()
        (pdir / "plugin.yaml").write_text("not valid [yaml")
        await manager.discover()
        result = manager.enable("broken")
        assert result is False

    @pytest.mark.asyncio
    async def test_disable(self, manager: PluginManager, plugin_dir: Path):
        self._create_plugin(plugin_dir, "to-disable")
        await manager.discover()
        manager.enable("to-disable")
        result = manager.disable("to-disable")
        assert result is True
        assert manager.get_plugin("to-disable").enabled is False

    def test_disable_nonexistent(self, manager: PluginManager):
        assert manager.disable("nope") is False

    @pytest.mark.asyncio
    async def test_reload(self, manager: PluginManager, plugin_dir: Path):
        self._create_plugin(plugin_dir, "reload-me")
        await manager.discover()
        assert len(manager.list_plugins()) == 1
        # Create another plugin and reload
        self._create_plugin(plugin_dir, "new-one")
        plugins = await manager.reload()
        assert len(plugins) == 2

    @pytest.mark.asyncio
    async def test_install(self, manager: PluginManager, tmp_path: Path, plugin_dir: Path):
        src = tmp_path / "install-source"
        src.mkdir()
        manifest = {"name": "installed-plugin", "type": "tool", "version": "1.0"}
        (src / "plugin.yaml").write_text(yaml.dump(manifest))
        result = manager.install(str(src))
        assert result["success"] is True
        # Should be discoverable now
        assert (plugin_dir / "installed-plugin" / "plugin.yaml").exists()

    @pytest.mark.asyncio
    async def test_uninstall(self, manager: PluginManager, plugin_dir: Path):
        self._create_plugin(plugin_dir, "uninstall-me")
        await manager.discover()
        result = manager.uninstall("uninstall-me")
        assert result is True
        assert manager.get_plugin("uninstall-me") is None
