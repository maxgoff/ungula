"""
Configuration management for Ungula.

Handles loading configuration from ~/.ungula/config.yaml, environment variables,
and provides Pydantic models for type-safe configuration access.
"""

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .sandbox.config import SandboxConfig


# Default paths
def get_ungula_home() -> Path:
    """Get the Ungula home directory, defaulting to ~/.ungula."""
    return Path(os.environ.get("UNGULA_HOME", Path.home() / ".ungula"))


def get_workspace_dir() -> Path:
    """Get the workspace directory."""
    return get_ungula_home() / "workspace"


def get_data_dir() -> Path:
    """Get the data directory for database and embeddings."""
    return get_ungula_home() / "data"


def get_logs_dir() -> Path:
    """Get the logs directory."""
    return get_ungula_home() / "logs"


# Configuration Models


class DatabaseConfig(BaseModel):
    """Database configuration."""

    type: str = Field(default="sqlite", description="Database type (sqlite)")
    path: str = Field(default="ungula.db", description="Database file path relative to data dir")


class RedisConfig(BaseModel):
    """Redis configuration for message queues."""

    host: str = Field(default="localhost", description="Redis host")
    port: int = Field(default=6379, description="Redis port")
    db: int = Field(default=0, description="Redis database number")
    password: str | None = Field(default=None, description="Redis password")


class EmbeddingsConfig(BaseModel):
    """Embeddings configuration for memory system."""

    provider: str = Field(
        default="local", description="Embeddings provider (local, openai)"
    )
    model: str = Field(
        default="all-MiniLM-L6-v2",
        description="Model name for embeddings",
    )
    openai_api_key: str | None = Field(
        default=None, description="OpenAI API key for embeddings"
    )


class LLMProviderConfig(BaseModel):
    """Configuration for a single LLM provider."""

    enabled: bool = Field(default=True, description="Whether provider is enabled")
    api_key: str | None = Field(default=None, description="API key for provider")
    base_url: str | None = Field(default=None, description="Base URL override")
    default_model: str | None = Field(default=None, description="Default model for provider")


class CustomProviderConfig(BaseModel):
    """Configuration for a custom OpenAI-compatible provider."""

    name: str = Field(description="Unique provider identifier")
    display_name: str = Field(description="Human-readable name")
    enabled: bool = Field(default=True, description="Whether provider is enabled")
    api_key: str = Field(description="API key for provider")
    base_url: str = Field(description="Base URL for OpenAI-compatible API")
    default_model: str | None = Field(default=None, description="Default model")


class LLMConfig(BaseModel):
    """LLM providers configuration."""

    default_provider: str = Field(
        default="openrouter", description="Default LLM provider"
    )
    failover_order: list[str] = Field(
        default_factory=list,
        description="User-defined provider failover order (empty = auto)",
    )
    openrouter: LLMProviderConfig = Field(default_factory=LLMProviderConfig)
    anthropic: LLMProviderConfig = Field(default_factory=LLMProviderConfig)
    openai: LLMProviderConfig = Field(default_factory=LLMProviderConfig)
    google: LLMProviderConfig = Field(default_factory=LLMProviderConfig)
    xai: LLMProviderConfig = Field(default_factory=LLMProviderConfig)
    nvidia: LLMProviderConfig = Field(default_factory=LLMProviderConfig)
    ollama: LLMProviderConfig = Field(
        default_factory=lambda: LLMProviderConfig(
            base_url="http://localhost:11434", api_key=None
        )
    )
    custom_providers: list[CustomProviderConfig] = Field(
        default_factory=list, description="Custom OpenAI-compatible providers"
    )


class AgentConfig(BaseModel):
    """Configuration for an agent."""

    id: str = Field(description="Unique agent identifier")
    name: str = Field(description="Display name")
    type: str = Field(description="Agent type (orchestrator, coder, researcher, etc.)")
    enabled: bool = Field(default=True, description="Whether agent is enabled")
    model: str | None = Field(default=None, description="Model override for agent")
    provider: str | None = Field(default=None, description="Provider override")
    persona: str | None = Field(default=None, description="Persona name")
    system_prompt: str | None = Field(default=None, description="System prompt override")
    temperature: float | None = Field(default=None, description="Temperature override (0-2)")
    max_tokens: int | None = Field(default=None, description="Max tokens override")
    max_tool_iterations: int | None = Field(default=None, description="Max tool loop iterations")
    default_provider_params: dict[str, Any] = Field(
        default_factory=dict, description="Default provider-specific parameters"
    )


class PersonaConfig(BaseModel):
    """Configuration for a persona."""

    name: str = Field(description="Persona name")
    description: str = Field(description="Short description")
    instruction: str = Field(description="System instruction for persona")


class NodeConfig(BaseModel):
    """Configuration for a LAN node (legacy, kept for backwards compat)."""

    id: str = Field(description="Unique node identifier")
    name: str = Field(description="Display name")
    host: str = Field(description="Node hostname or IP")
    port: int = Field(default=8000, description="Node API port")
    capabilities: list[str] = Field(
        default_factory=list, description="Node capabilities (gpu, memory, general)"
    )
    enabled: bool = Field(default=True, description="Whether node is enabled")


class NodeSystemConfig(BaseModel):
    """Node system (companion devices) configuration."""

    enabled: bool = Field(default=True, description="Enable node system")
    max_nodes: int = Field(default=10, description="Maximum number of connected nodes")
    pairing_ttl: int = Field(default=300, description="Pairing request TTL in seconds")
    heartbeat_interval: int = Field(default=30, description="Heartbeat interval in seconds")
    heartbeat_timeout: int = Field(default=90, description="Heartbeat timeout before node marked stale")
    command_timeout: int = Field(default=60, description="Command execution timeout in seconds")
    allow_commands: list[str] = Field(default_factory=list, description="Additional allowed node commands")
    deny_commands: list[str] = Field(default_factory=list, description="Denied node commands (overrides platform defaults)")


class FileToolsConfig(BaseModel):
    """File tools configuration."""

    enabled: bool = Field(default=True, description="Enable file tools")
    max_file_size: int = Field(default=1_000_000, description="Max file size in bytes")
    denied_extensions: list[str] = Field(
        default_factory=lambda: [".env", ".key", ".pem"],
        description="File extensions that cannot be read/written",
    )


class ProcessToolConfig(BaseModel):
    """Process management tool configuration."""

    enabled: bool = Field(default=True, description="Enable process tools")
    max_background: int = Field(default=5, description="Max concurrent background processes")
    max_output_size: int = Field(default=50_000, description="Max output buffer size per process")


class WebhookConfig(BaseModel):
    """Webhook system configuration."""

    enabled: bool = Field(default=True, description="Enable webhook system")
    max_webhooks: int = Field(default=50, description="Maximum number of webhooks")
    max_payload_size: int = Field(default=1_000_000, description="Max payload size in bytes")
    event_retention_days: int = Field(default=7, description="Days to retain webhook events")


class BrowserConfig(BaseModel):
    """Browser automation configuration."""

    enabled: bool = Field(default=False, description="Enable browser automation (off by default)")
    headless: bool = Field(default=True, description="Run browser in headless mode")
    timeout: int = Field(default=30, description="Default page timeout in seconds")
    max_tabs: int = Field(default=5, description="Maximum number of open tabs")


class PluginConfig(BaseModel):
    """Plugin system configuration."""

    enabled: bool = Field(default=True, description="Enable plugin system")
    plugin_dirs: list[str] = Field(
        default_factory=list, description="Additional plugin directories"
    )


class AgentRuntimeConfig(BaseModel):
    """Agent runtime configuration for context management."""

    max_context_tokens: int = Field(default=200_000, description="Maximum context window size in tokens")
    max_history_share: float = Field(default=0.5, description="Max fraction of context for history")
    reserve_tokens_floor: int = Field(default=20_000, description="Always reserve this many tokens for new content")
    pruning_enabled: bool = Field(default=True, description="Enable tool result pruning")
    soft_trim_ratio: float = Field(default=0.3, description="Trigger soft trim at this fraction of context")
    hard_clear_ratio: float = Field(default=0.5, description="Trigger hard clear at this fraction of context")


class ServerConfig(BaseModel):
    """Server configuration."""

    host: str = Field(default="0.0.0.0", description="Server bind host")
    port: int = Field(default=8001, description="Server port")
    reload: bool = Field(default=False, description="Enable auto-reload")
    workers: int = Field(default=1, description="Number of workers")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3001", "http://localhost:3000"],
        description="Allowed CORS origins",
    )


class DiscordChannelConfig(BaseModel):
    """Discord channel configuration."""

    enabled: bool = Field(default=False, description="Enable Discord integration")
    token: str | None = Field(default=None, description="Discord bot token")
    dm_enabled: bool = Field(default=True, description="Enable DM handling")
    dm_policy: str = Field(default="pairing", description="DM policy: open, pairing, allowlist")
    dm_allowlist: list[str] = Field(default_factory=list, description="Allowed user IDs for DMs")
    guild_policy: str = Field(default="allowlist", description="Guild policy: open, allowlist, disabled")
    guild_allowlist: dict[str, Any] = Field(default_factory=dict, description="Guild configs by ID")
    mention_required: bool = Field(default=True, description="Require @mention in guilds")
    max_response_length: int = Field(default=2000, description="Max message length")


class IMessageChannelConfig(BaseModel):
    """iMessage channel configuration."""

    enabled: bool = Field(default=False, description="Enable iMessage integration")
    cli_path: str = Field(default="imsg", description="Path to imsg CLI tool")
    db_path: str | None = Field(default=None, description="Path to iMessage database")
    dm_policy: str = Field(default="pairing", description="DM policy: open, pairing, allowlist")
    dm_allowlist: list[str] = Field(default_factory=list, description="Allowed phone numbers/emails")
    group_policy: str = Field(default="allowlist", description="Group policy: open, allowlist, disabled")
    group_allowlist: list[str] = Field(default_factory=list, description="Allowed group chat IDs")


class TelegramChannelConfig(BaseModel):
    """Telegram channel configuration."""

    enabled: bool = Field(default=False, description="Enable Telegram integration")
    token: str | None = Field(default=None, description="Telegram bot token from @BotFather")
    allowed_users: list[str] = Field(default_factory=list, description="Allowed user IDs (empty = all)")
    allowed_chats: list[str] = Field(default_factory=list, description="Allowed chat IDs (empty = all)")


class SlackChannelConfig(BaseModel):
    """Slack channel configuration."""

    enabled: bool = Field(default=False, description="Enable Slack integration")
    bot_token: str | None = Field(default=None, description="Slack bot token (xoxb-...)")
    app_token: str | None = Field(default=None, description="Slack app-level token (xapp-...)")


class SignalChannelConfig(BaseModel):
    """Signal channel configuration."""

    enabled: bool = Field(default=False, description="Enable Signal integration")
    account: str | None = Field(default=None, description="Signal account phone number (+1234567890)")
    cli_path: str = Field(default="signal-cli", description="Path to signal-cli binary")
    allowed_users: list[str] = Field(default_factory=list, description="Allowed user phone numbers (empty = all)")
    allowed_groups: list[str] = Field(default_factory=list, description="Allowed group IDs (empty = all)")


class MessagingConfig(BaseModel):
    """Messaging integration configuration."""

    # Legacy fields (for backwards compatibility)
    imessage_enabled: bool = Field(default=False, description="Enable iMessage integration (legacy)")
    discord_enabled: bool = Field(default=False, description="Enable Discord integration (legacy)")
    discord_token: str | None = Field(default=None, description="Discord bot token (legacy)")
    discord_channel_id: str | None = Field(default=None, description="Discord channel to monitor (legacy)")

    # New channel configs
    discord: DiscordChannelConfig = Field(default_factory=DiscordChannelConfig)
    imessage: IMessageChannelConfig = Field(default_factory=IMessageChannelConfig)
    telegram: TelegramChannelConfig = Field(default_factory=TelegramChannelConfig)
    slack: SlackChannelConfig = Field(default_factory=SlackChannelConfig)
    signal: SignalChannelConfig = Field(default_factory=SignalChannelConfig)


class BraveSearchToolConfig(BaseModel):
    """Brave Search tool configuration."""

    enabled: bool = Field(default=False, description="Enable Brave Search tool")
    api_key: str | None = Field(default=None, description="Brave Search API key")
    max_results: int = Field(default=5, description="Maximum search results")


class TavilySearchToolConfig(BaseModel):
    """Tavily Search tool configuration (fallback provider)."""

    enabled: bool = Field(default=False, description="Enable Tavily Search as fallback")
    api_key: str | None = Field(default=None, description="Tavily Search API key")
    max_results: int = Field(default=5, description="Maximum search results")


class ToolPolicyConfig(BaseModel):
    """Tool policy configuration."""

    profile: str = Field(default="full", description="Policy profile: minimal, coding, messaging, full")
    allowed: list[str] = Field(default_factory=list, description="Additional allowed tool names")
    denied: list[str] = Field(default_factory=list, description="Denied tool names (overrides allowed)")


class ToolsConfig(BaseModel):
    """Tools configuration."""

    brave_search: BraveSearchToolConfig = Field(default_factory=BraveSearchToolConfig)
    tavily_search: TavilySearchToolConfig = Field(default_factory=TavilySearchToolConfig)
    policy: ToolPolicyConfig = Field(default_factory=ToolPolicyConfig)


class ShellToolConfig(BaseModel):
    """Shell execution tool configuration."""

    enabled: bool = Field(default=True, description="Enable shell execution tool")
    allowed_commands: list[str] = Field(
        default_factory=list, description="Allowed command prefixes (empty = all allowed)"
    )
    blocked_commands: list[str] = Field(
        default_factory=lambda: ["rm -rf /", "sudo rm", "mkfs", "dd if=", "> /dev/"],
        description="Blocked command patterns",
    )
    max_timeout: int = Field(default=30, description="Maximum execution timeout in seconds")
    working_dir: str | None = Field(default=None, description="Working directory for commands")


class SkillsConfig(BaseModel):
    """Skills framework configuration."""

    enabled: bool = Field(default=True, description="Enable skills system")
    extra_dirs: list[str] = Field(
        default_factory=list, description="Additional skill directories to scan"
    )
    entries: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="Per-skill configuration overrides"
    )
    shell: ShellToolConfig = Field(default_factory=ShellToolConfig)


class MemoryConfig(BaseModel):
    """Vector memory system configuration."""

    enabled: bool = Field(default=True, description="Enable the vector memory system")
    auto_index_workspace: bool = Field(
        default=False, description="Auto-index workspace files on change"
    )
    embeddings_provider: str = Field(
        default="local", description="Embeddings provider: local, openai"
    )
    embeddings_model: str | None = Field(
        default=None, description="Override default embedding model"
    )
    embedding_cache_size: int = Field(
        default=10000, description="Max entries in embedding cache (0 = disabled)"
    )


class AuthConfig(BaseModel):
    """Authentication configuration."""

    secret_key: str = Field(
        default="CHANGE-ME-IN-PRODUCTION",
        description="JWT signing secret key",
    )
    algorithm: str = Field(default="HS256", description="JWT algorithm")
    token_expire_minutes: int = Field(default=1440, description="Token expiration in minutes (default 24h)")


class UngulaConfig(BaseModel):
    """Main Ungula configuration."""

    auth: AuthConfig = Field(default_factory=AuthConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    messaging: MessagingConfig = Field(default_factory=MessagingConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    agents: list[AgentConfig] = Field(default_factory=list)
    personas: list[PersonaConfig] = Field(default_factory=list)
    nodes: list[NodeConfig] = Field(default_factory=list)
    node_system: NodeSystemConfig = Field(default_factory=NodeSystemConfig)
    file_tools: FileToolsConfig = Field(default_factory=FileToolsConfig)
    process_tools: ProcessToolConfig = Field(default_factory=ProcessToolConfig)
    webhooks: WebhookConfig = Field(default_factory=WebhookConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    plugins: PluginConfig = Field(default_factory=PluginConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    agent_runtime: AgentRuntimeConfig = Field(default_factory=AgentRuntimeConfig)


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    These override values in config.yaml.
    """

    model_config = SettingsConfigDict(
        env_prefix="UNGULA_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    # Core paths
    home: Path = Field(default_factory=get_ungula_home)

    # Server settings (can be overridden via env)
    server_host: str = "0.0.0.0"
    server_port: int = 8000

    # Redis (can be overridden via env)
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str | None = None

    # LLM API keys (commonly set via env)
    openrouter_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    google_api_key: str | None = None
    xai_api_key: str | None = None
    nvidia_api_key: str | None = None

    # Auth
    auth_secret_key: str | None = None

    # Discord
    discord_token: str | None = None
    discord_channel_id: str | None = None



def load_yaml_config(config_path: Path) -> dict[str, Any]:
    """Load configuration from a YAML file."""
    if not config_path.exists():
        return {}
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def merge_configs(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two configuration dictionaries."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: Path | None = None) -> UngulaConfig:
    """
    Load Ungula configuration.

    Priority (highest to lowest):
    1. Environment variables (via Settings)
    2. Config file (config.yaml)
    3. Defaults
    """
    settings = Settings()

    # Determine config path
    if config_path is None:
        config_path = settings.home / "config.yaml"

    # Load YAML config
    yaml_config = load_yaml_config(config_path)

    # Apply environment variable overrides (only if explicitly set)
    env_overrides: dict[str, Any] = {}

    # Server overrides - only apply if env var is explicitly set
    server_overrides: dict[str, Any] = {}
    if os.environ.get("UNGULA_SERVER_HOST"):
        server_overrides["host"] = settings.server_host
    if os.environ.get("UNGULA_SERVER_PORT"):
        server_overrides["port"] = settings.server_port
    if server_overrides:
        env_overrides["server"] = server_overrides

    # Redis overrides - only apply if env var is explicitly set
    redis_overrides: dict[str, Any] = {}
    if os.environ.get("UNGULA_REDIS_HOST"):
        redis_overrides["host"] = settings.redis_host
    if os.environ.get("UNGULA_REDIS_PORT"):
        redis_overrides["port"] = settings.redis_port
    if settings.redis_password:
        redis_overrides["password"] = settings.redis_password
    if redis_overrides:
        env_overrides["redis"] = redis_overrides

    # LLM API key overrides
    llm_overrides: dict[str, Any] = {}
    if settings.openrouter_api_key:
        llm_overrides["openrouter"] = {"api_key": settings.openrouter_api_key}
    if settings.anthropic_api_key:
        llm_overrides["anthropic"] = {"api_key": settings.anthropic_api_key}
    if settings.openai_api_key:
        llm_overrides["openai"] = {"api_key": settings.openai_api_key}
    if settings.google_api_key:
        llm_overrides["google"] = {"api_key": settings.google_api_key}
    if settings.xai_api_key:
        llm_overrides["xai"] = {"api_key": settings.xai_api_key}
    if settings.nvidia_api_key:
        llm_overrides["nvidia"] = {"api_key": settings.nvidia_api_key}
    if llm_overrides:
        env_overrides["llm"] = llm_overrides

    # Auth overrides
    if settings.auth_secret_key:
        env_overrides["auth"] = {"secret_key": settings.auth_secret_key}

    # Messaging overrides
    messaging_overrides: dict[str, Any] = {}
    if settings.discord_token:
        messaging_overrides["discord_token"] = settings.discord_token
        messaging_overrides["discord_enabled"] = True
    if settings.discord_channel_id:
        messaging_overrides["discord_channel_id"] = settings.discord_channel_id
    if messaging_overrides:
        env_overrides["messaging"] = messaging_overrides

    # Merge configs
    merged = merge_configs(yaml_config, env_overrides)

    # Parse into config model
    return UngulaConfig(**merged)


def save_config(config: UngulaConfig, config_path: Path | None = None) -> None:
    """Save configuration to YAML file with restricted permissions."""
    settings = Settings()
    if config_path is None:
        config_path = settings.home / "config.yaml"

    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w") as f:
        yaml.dump(config.model_dump(exclude_none=True), f, default_flow_style=False)

    # Restrict config file to owner-only read/write (contains secrets)
    try:
        config_path.chmod(0o600)
    except OSError:
        pass  # May fail on some filesystems


def init_ungula_dirs() -> None:
    """Initialize Ungula directory structure with restricted permissions."""
    home = get_ungula_home()

    # Create directories
    dirs = [
        home,
        home / "workspace",
        home / "workspace" / "memory",
        home / "skills",
        home / "data",
        home / "data" / "embeddings",
        home / "nodes",
        home / "plugins",
        home / "logs",
    ]

    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    # Restrict home directory to owner-only (contains secrets)
    try:
        home.chmod(0o700)
    except OSError:
        pass


def get_workspace_file(filename: str) -> Path:
    """Get path to a workspace file."""
    return get_workspace_dir() / filename


def load_workspace_file(filename: str) -> str | None:
    """Load content from a workspace file."""
    path = get_workspace_file(filename)
    if path.exists():
        return path.read_text()
    return None


def save_workspace_file(filename: str, content: str) -> None:
    """Save content to a workspace file."""
    path = get_workspace_file(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
