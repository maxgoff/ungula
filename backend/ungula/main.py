"""
Ungula FastAPI Application

Main entry point for the Ungula backend server.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request as FastAPIRequest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from . import __version__
from .agents import AgentRunner
from .api.routes import auth as auth_routes
from .api.routes import channels as channel_routes
from .api.routes import chat as chat_routes
from .api.routes import config as config_routes
from .api.routes import cron as cron_routes
from .api.routes import conversations as conversation_routes
from .api.routes import memory as memory_routes
from .api.routes import pairing as pairing_routes
from .api.routes import security as security_routes
from .api.routes import skills as skills_routes
from .api.routes import subagents as subagent_routes
from .api.routes import ws as ws_routes
from .api.routes import nodes as node_routes
from .api.routes import ws_node as ws_node_routes
from .api.routes import webhooks as webhook_routes
from .api.routes import plugins as plugin_routes
from .api.routes import usage as usage_routes
from .api.routes import agents_config as agents_config_routes
from .api.routes import runtime as runtime_routes
from .api.routes import events as events_routes
from .api.routes import queue as queue_routes
from .api.ws_manager import ConnectionManager
from .auth import configure_auth
from .messaging import ChannelRegistry
from .messaging.router import MessageRouter, create_message_callback
from .messaging.session import SessionManager
from .config import get_data_dir, get_ungula_home, get_workspace_dir, init_ungula_dirs, load_config, save_config
from .llm import create_registry_from_config
from .skills.loader import SkillLoader, SkillRegistry
from .storage import SQLiteStorage
from .tools import BraveSearchConfig, TavilySearchConfig, ToolRegistry, ToolResultCache, WebSearchTool
from .tools.policy import PolicyEngine, PolicyProfile, ToolPolicy

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Rate limiter (global default: 60 requests/minute per IP)
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

# Global state
_storage: SQLiteStorage | None = None


def get_storage() -> SQLiteStorage:
    """Get the storage instance."""
    if _storage is None:
        raise RuntimeError("Storage not initialized")
    return _storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    global _storage

    logger.info("Starting Ungula v%s", __version__)

    # Initialize directories
    init_ungula_dirs()
    logger.info("Initialized Ungula directories")

    # Auto-initialize workspace templates if workspace is empty
    workspace_dir = get_workspace_dir()
    if not any(workspace_dir.glob("*.md")):
        templates_dir = Path(__file__).parent.parent.parent / "docs" / "templates"
        if not templates_dir.is_dir():
            templates_dir = Path("/app/docs/templates")
        if templates_dir.is_dir():
            from .config import save_workspace_file

            for tmpl in templates_dir.glob("*.md"):
                save_workspace_file(tmpl.name, tmpl.read_text())
            logger.info("Initialized workspace from templates (%s)", templates_dir)

    # Load configuration
    config = load_config()
    app.state.config = config
    logger.info("Loaded configuration")

    # Initialize storage
    db_path = get_data_dir() / config.database.path
    _storage = SQLiteStorage(db_path)
    await _storage.initialize()
    app.state.storage = _storage
    logger.info("Initialized storage at %s", db_path)

    # Configure authentication
    configure_auth(
        secret_key=config.auth.secret_key,
        algorithm=config.auth.algorithm,
        token_expire_minutes=config.auth.token_expire_minutes,
        storage=_storage,
    )
    if config.auth.secret_key == "CHANGE-ME-IN-PRODUCTION":
        logger.warning("AUTH: Using default secret key -- set UNGULA_AUTH_SECRET_KEY for production!")
    logger.info("Configured JWT authentication")

    # Initialize LLM registry
    registry = create_registry_from_config(config.llm)
    app.state.registry = registry
    logger.info("Initialized LLM registry with providers: %s", registry.list_providers())

    # Initialize tool result cache
    tool_cache = ToolResultCache()
    app.state.tool_cache = tool_cache

    # Initialize tool registry
    tool_registry = ToolRegistry(cache=tool_cache)
    app.state.tool_registry = tool_registry

    # Initialize skill registry
    skill_registry = SkillRegistry()
    if config.skills.enabled:
        loader = SkillLoader(config)
        bundled_dir = Path(__file__).parent / "skills" / "builtin"
        user_dir = get_ungula_home() / "skills"
        extra_dirs = [Path(d) for d in config.skills.extra_dirs]

        skills = loader.scan_directories([bundled_dir, user_dir] + extra_dirs)
        for skill in skills:
            skill_registry.register(skill)
            # Register skill tools in the tool registry
            for tool in skill.tools:
                tool_registry.register(tool)

        logger.info(
            "Loaded %d skills with %d tools",
            len(skills),
            len(skill_registry.get_all_tools()),
        )
    else:
        # Fallback: register web search directly if skills disabled
        if config.tools.brave_search.enabled and config.tools.brave_search.api_key:
            brave_config = BraveSearchConfig(
                api_key=config.tools.brave_search.api_key,
                max_results=config.tools.brave_search.max_results,
            )
            # Build Tavily fallback config if available
            tavily_fallback = None
            if config.tools.tavily_search.enabled and config.tools.tavily_search.api_key:
                tavily_fallback = TavilySearchConfig(
                    api_key=config.tools.tavily_search.api_key,
                    max_results=config.tools.tavily_search.max_results,
                )
                logger.info("Tavily Search configured as fallback provider")
            tool_registry.register(WebSearchTool(brave_config, tavily_config=tavily_fallback))
            logger.info("Registered web_search tool (Brave Search) -- skills disabled")

    app.state.skill_registry = skill_registry
    logger.info("Initialized tool registry with tools: %s", tool_registry.list_tools())

    # Initialize policy engine from config
    try:
        policy_profile = PolicyProfile(config.tools.policy.profile)
    except ValueError:
        logger.warning("Unknown tool policy profile '%s', using 'full'", config.tools.policy.profile)
        policy_profile = PolicyProfile.FULL

    tool_policy = ToolPolicy(
        profile=policy_profile,
        allowed=set(config.tools.policy.allowed),
        denied=set(config.tools.policy.denied),
    )
    policy_engine = PolicyEngine(default_policy=tool_policy)
    app.state.policy_engine = policy_engine
    logger.info("Initialized tool policy (profile=%s)", policy_profile.value)

    # Build agent runtime configs
    from .agents.compaction import CompactionConfig
    from .agents.context_pruning import PruningConfig

    rt = config.agent_runtime
    compaction_config = CompactionConfig(
        max_context_tokens=rt.max_context_tokens,
        max_history_share=rt.max_history_share,
        reserve_tokens_floor=rt.reserve_tokens_floor,
    )
    pruning_config = PruningConfig(
        enabled=rt.pruning_enabled,
        soft_trim_ratio=rt.soft_trim_ratio,
        hard_clear_ratio=rt.hard_clear_ratio,
    )

    # Initialize agent runner
    app.state.agent_runner = AgentRunner(
        storage=_storage,
        registry=registry,
        workspace_dir=get_workspace_dir(),
        default_provider=config.llm.default_provider,
        tool_registry=tool_registry,
        skill_registry=skill_registry,
        policy_engine=policy_engine,
        compaction_config=compaction_config,
        pruning_config=pruning_config,
    )
    logger.info("Initialized agent runner")

    # Initialize agent factory for per-agent configuration
    from .agents.factory import AgentRunnerFactory

    agent_factory = AgentRunnerFactory(
        storage=_storage,
        registry=registry,
        workspace_dir=get_workspace_dir(),
        tool_registry=tool_registry,
        skill_registry=skill_registry,
        policy_engine=policy_engine,
        compaction_config=compaction_config,
        pruning_config=pruning_config,
        defaults={
            "default_provider": config.llm.default_provider,
            "default_model": None,
            "default_temperature": 0.7,
            "max_tool_iterations": 10,
        },
    )
    app.state.agent_factory = agent_factory
    logger.info("Initialized agent runner factory")

    # Run boot tasks from BOOT.md (fire-and-forget)
    try:
        from .hooks.boot import run_boot_tasks

        async def _boot():
            try:
                result = await run_boot_tasks(get_workspace_dir(), app.state.agent_runner)
                logger.info("Boot tasks result: %s", result.get("status", "unknown"))
            except Exception as e:
                logger.warning("Boot tasks failed: %s", e)

        import asyncio
        asyncio.create_task(_boot())
    except Exception as e:
        logger.warning("Could not schedule boot tasks: %s", e)

    # Initialize vector memory system
    app.state.memory_manager = None
    if config.memory.enabled:
        try:
            from .memory import MemoryManager, create_embedding_provider
            from .memory.embeddings import CachedEmbeddingProvider

            embedding_provider = create_embedding_provider(
                provider=config.memory.embeddings_provider,
                model=config.memory.embeddings_model,
                api_key=config.embeddings.openai_api_key,
            )
            # Wrap with caching if configured
            if config.memory.embedding_cache_size > 0:
                embedding_provider = CachedEmbeddingProvider(
                    provider=embedding_provider,
                    max_cache_size=config.memory.embedding_cache_size,
                )
                logger.info("Embedding cache enabled (max_size=%d)", config.memory.embedding_cache_size)
            memory_manager = MemoryManager(
                storage=_storage,
                embedding_provider=embedding_provider,
                persist_dir=get_data_dir() / "embeddings",
            )
            await memory_manager.initialize()
            app.state.memory_manager = memory_manager
            logger.info("Initialized vector memory system")

            # Start file watcher if auto-indexing enabled
            if config.memory.auto_index_workspace:
                from .memory.watcher import FileWatcher

                watcher = FileWatcher(
                    watch_dir=get_workspace_dir(),
                    memory_manager=memory_manager,
                )
                await watcher.start()
                app.state.file_watcher = watcher
                logger.info("Started workspace file watcher")
        except Exception as e:
            logger.warning("Failed to initialize memory system: %s", e)

    # Initialize subagent manager
    from .agents.subagent import SubagentManager

    subagent_manager = SubagentManager(max_concurrent=5)
    app.state.subagent_manager = subagent_manager
    logger.info("Initialized subagent manager")

    # Initialize cron scheduler
    from .cron import CronScheduler

    cron_scheduler = CronScheduler()
    await cron_scheduler.start()
    app.state.cron_scheduler = cron_scheduler
    logger.info("Initialized cron scheduler")

    # Initialize event bus
    from .events import ActionExecutor, EventBus, EventRuleStore

    event_rule_store = EventRuleStore()
    action_executor = ActionExecutor(
        agent_runner=app.state.agent_runner,
        tool_registry=tool_registry,
    )
    event_bus = EventBus(store=event_rule_store, action_executor=action_executor)
    app.state.event_bus = event_bus
    tool_registry._event_bus = event_bus
    logger.info("Initialized event bus")

    # Initialize task queue
    from .queue import QueueManager

    queue_manager = QueueManager(redis_config=config.redis)
    await queue_manager.initialize()

    # Register agent_run handler
    async def _agent_run_handler(job):
        conversation_id = job.payload.get("conversation_id")
        message = job.payload.get("message", "")
        if conversation_id:
            result = await app.state.agent_runner.run(
                conversation_id=conversation_id,
                user_message=message,
            )
            return {"content": result.content}
        return {"error": "No conversation_id in payload"}

    queue_manager.register_handler("agent_run", _agent_run_handler)
    await queue_manager.start_worker()
    app.state.queue_manager = queue_manager
    logger.info("Initialized task queue (backend=%s)", queue_manager._backend_type)

    # Initialize pairing manager
    from .pairing import PairingManager

    pairing_manager = PairingManager()
    app.state.pairing_manager = pairing_manager
    logger.info("Initialized pairing manager")

    # Initialize security auditor
    from .security.audit import SecurityAuditor

    config_path = get_ungula_home() / "config.yaml"
    security_auditor = SecurityAuditor(
        config=config,
        config_path=config_path,
        home_dir=get_ungula_home(),
    )
    app.state.security_auditor = security_auditor
    logger.info("Initialized security auditor")

    # Initialize node system
    app.state.node_manager = None
    if config.node_system.enabled:
        try:
            from .nodes import ExecApprovalManager, NodeManager, NodePairingStore, NodeCommandPolicy, NodeRegistry

            node_registry = NodeRegistry(max_nodes=config.node_system.max_nodes)
            pairing_store = NodePairingStore(ttl=config.node_system.pairing_ttl)
            node_policy = NodeCommandPolicy(
                allow_commands=config.node_system.allow_commands or None,
                deny_commands=config.node_system.deny_commands or None,
            )
            exec_approval = ExecApprovalManager()
            node_manager = NodeManager(
                registry=node_registry,
                pairing_store=pairing_store,
                policy=node_policy,
                storage=_storage,
                command_timeout=config.node_system.command_timeout,
                exec_approval=exec_approval,
            )
            # Start heartbeat monitor
            node_manager.start_heartbeat_monitor(
                interval=config.node_system.heartbeat_interval,
                timeout=config.node_system.heartbeat_timeout,
            )
            app.state.node_manager = node_manager
            logger.info("Initialized node system (max_nodes=%d)", config.node_system.max_nodes)

            # Register node_invoke tool now that we have NodeManager
            from .skills.builtin.node_invoke.tool import NodeInvokeTool
            node_invoke_tool = NodeInvokeTool(node_manager)
            tool_registry.register(node_invoke_tool)
            logger.info("Registered node_invoke tool")
        except Exception as e:
            logger.warning("Failed to initialize node system: %s", e)

    # Initialize webhook system
    app.state.webhook_manager = None
    if config.webhooks.enabled:
        try:
            from .webhooks import WebhookManager

            webhook_manager = WebhookManager(
                storage=_storage,
                agent_runner=app.state.agent_runner,
                event_bus=event_bus,
            )
            app.state.webhook_manager = webhook_manager
            logger.info("Initialized webhook system")
        except Exception as e:
            logger.warning("Failed to initialize webhook system: %s", e)

    # Initialize browser manager (lazy — starts on first use)
    app.state.browser_manager = None
    if config.browser.enabled:
        try:
            from .browser.manager import BrowserManager

            browser_manager = BrowserManager(
                headless=config.browser.headless,
                timeout=config.browser.timeout,
                max_tabs=config.browser.max_tabs,
            )
            app.state.browser_manager = browser_manager
            logger.info("Initialized browser manager (headless=%s)", config.browser.headless)
        except Exception as e:
            logger.warning("Failed to initialize browser manager: %s", e)

    # Initialize plugin system
    app.state.plugin_manager = None
    if config.plugins.enabled:
        try:
            from pathlib import Path as PathlibPath
            from .plugins import PluginManager
            from .plugins.registry import PluginRegistry

            plugin_dirs = [get_ungula_home() / "plugins"]
            plugin_dirs.extend(PathlibPath(d) for d in config.plugins.plugin_dirs)

            plugin_registry = PluginRegistry(
                tool_registry=tool_registry,
                channel_registry=None,  # Set after channel registry init
            )
            plugin_manager = PluginManager(
                plugin_dirs=plugin_dirs,
                plugin_registry=plugin_registry,
            )
            await plugin_manager.discover()
            app.state.plugin_manager = plugin_manager
            logger.info("Initialized plugin system")
        except Exception as e:
            logger.warning("Failed to initialize plugin system: %s", e)

    # Initialize Docker sandbox if enabled
    app.state.docker_sandbox = None
    if config.sandbox.enabled:
        try:
            from .sandbox import DockerSandbox

            docker_sandbox = DockerSandbox(
                config=config.sandbox,
                workspace_path=get_workspace_dir(),
            )
            if await docker_sandbox.initialize():
                app.state.docker_sandbox = docker_sandbox
                logger.info("Initialized Docker sandbox (image=%s)", config.sandbox.image)
            else:
                logger.warning("Docker sandbox enabled but Docker not available")
        except Exception as e:
            logger.warning("Failed to initialize Docker sandbox: %s", e)

    # Initialize WebSocket manager
    ws_manager = ConnectionManager(max_connections=50)
    app.state.ws_manager = ws_manager
    logger.info("Initialized WebSocket manager")

    # Initialize session manager
    app.state.session_manager = SessionManager(storage=_storage)
    logger.info("Initialized session manager")

    # Initialize channel registry
    app.state.channel_registry = ChannelRegistry()
    logger.info("Initialized channel registry")

    # Initialize message router
    app.state.message_router = MessageRouter(
        storage=_storage,
        agent_runner=app.state.agent_runner,
        session_manager=app.state.session_manager,
        channel_registry=app.state.channel_registry,
        ws_manager=ws_manager,
        event_bus=event_bus,
    )
    logger.info("Initialized message router")

    # Create message callback for channels
    on_message = await create_message_callback(app.state.message_router)
    app.state.channel_registry._on_message = on_message

    # Wire channel_registry into action executor now that it exists
    action_executor.channel_registry = app.state.channel_registry

    # Register and start Discord if enabled
    if config.messaging.discord.enabled and config.messaging.discord.token:
        try:
            from .messaging.discord import DiscordProvider

            discord_provider = DiscordProvider()
            app.state.channel_registry.register(discord_provider)

            # Start Discord with config
            discord_config = {
                "token": config.messaging.discord.token,
                "dm_enabled": config.messaging.discord.dm_enabled,
                "dm_policy": config.messaging.discord.dm_policy,
                "dm_allowlist": config.messaging.discord.dm_allowlist,
                "guild_policy": config.messaging.discord.guild_policy,
                "guild_allowlist": config.messaging.discord.guild_allowlist,
                "mention_required": config.messaging.discord.mention_required,
            }
            await discord_provider.start(discord_config, on_message)
            app.state.channel_registry.status["discord"].running = True
            logger.info("Started Discord channel")
        except ImportError as e:
            logger.warning("Discord provider not available: %s", e)
        except Exception as e:
            logger.error("Failed to start Discord: %s", e, exc_info=True)

    # Register and start Telegram if enabled
    if config.messaging.telegram.enabled and config.messaging.telegram.token:
        try:
            from .messaging.telegram import TelegramProvider

            telegram_provider = TelegramProvider()
            app.state.channel_registry.register(telegram_provider)

            # Start Telegram with config
            telegram_config = {
                "token": config.messaging.telegram.token,
                "allowed_users": config.messaging.telegram.allowed_users,
                "allowed_chats": config.messaging.telegram.allowed_chats,
            }
            await telegram_provider.start(telegram_config, on_message, app_state=app.state)
            app.state.channel_registry.status["telegram"].running = True
            logger.info("Started Telegram channel")
        except ImportError as e:
            logger.warning("Telegram provider not available: %s", e)
        except Exception as e:
            logger.error("Failed to start Telegram: %s", e, exc_info=True)

    # Register and start iMessage if enabled (macOS only)
    if config.messaging.imessage.enabled:
        try:
            import sys

            if sys.platform == "darwin":
                from .messaging.imessage import IMessageProvider

                imessage_provider = IMessageProvider()
                app.state.channel_registry.register(imessage_provider)

                imessage_config = {
                    "cli_path": config.messaging.imessage.cli_path,
                    "dm_policy": config.messaging.imessage.dm_policy,
                    "dm_allowlist": config.messaging.imessage.dm_allowlist,
                }
                await imessage_provider.start(imessage_config, on_message)
                app.state.channel_registry.status["imessage"].running = True
                logger.info("Started iMessage channel")
            else:
                logger.warning("iMessage enabled but not running on macOS")
        except Exception as e:
            logger.error("Failed to start iMessage: %s", e, exc_info=True)

    # Register and start Slack if enabled
    if config.messaging.slack.enabled and config.messaging.slack.bot_token:
        try:
            from .messaging.slack import SlackProvider

            slack_provider = SlackProvider()
            app.state.channel_registry.register(slack_provider)

            slack_config = {
                "bot_token": config.messaging.slack.bot_token,
                "app_token": config.messaging.slack.app_token,
            }
            await slack_provider.start(slack_config, on_message)
            app.state.channel_registry.status["slack"].running = True
            logger.info("Started Slack channel")
        except ImportError as e:
            logger.warning("Slack provider not available: %s", e)
        except Exception as e:
            logger.error("Failed to start Slack: %s", e, exc_info=True)

    # Register and start Signal if enabled
    if config.messaging.signal.enabled and config.messaging.signal.account:
        try:
            from .messaging.signal import SignalProvider

            signal_provider = SignalProvider()
            app.state.channel_registry.register(signal_provider)

            signal_config = {
                "account": config.messaging.signal.account,
                "cli_path": config.messaging.signal.cli_path,
                "allowed_users": config.messaging.signal.allowed_users,
                "allowed_groups": config.messaging.signal.allowed_groups,
            }
            await signal_provider.start(signal_config, on_message)
            app.state.channel_registry.status["signal"].running = True
            logger.info("Started Signal channel")
        except Exception as e:
            logger.error("Failed to start Signal: %s", e, exc_info=True)

    yield

    # Cleanup Docker sandbox
    docker_sbx = getattr(app.state, "docker_sandbox", None)
    if docker_sbx:
        await docker_sbx.cleanup()
        logger.info("Cleaned up Docker sandbox")

    # Cleanup node heartbeat monitor
    node_mgr = getattr(app.state, "node_manager", None)
    if node_mgr:
        await node_mgr.stop_heartbeat_monitor()
        logger.info("Stopped node heartbeat monitor")

    # Cleanup browser
    browser_mgr = getattr(app.state, "browser_manager", None)
    if browser_mgr and browser_mgr.is_running:
        await browser_mgr.stop()
        logger.info("Stopped browser manager")

    # Cleanup queue worker
    qm = getattr(app.state, "queue_manager", None)
    if qm:
        await qm.stop_worker()
        logger.info("Stopped queue worker")

    # Cleanup cron scheduler
    scheduler = getattr(app.state, "cron_scheduler", None)
    if scheduler:
        await scheduler.stop()
        logger.info("Stopped cron scheduler")

    # Cleanup file watcher
    watcher = getattr(app.state, "file_watcher", None)
    if watcher:
        await watcher.stop()
        logger.info("Stopped file watcher")

    # Cleanup channels
    if app.state.channel_registry:
        await app.state.channel_registry.close()
        logger.info("Closed channel registry")

    # Cleanup
    if _storage:
        await _storage.close()
        logger.info("Closed storage")

    logger.info("Ungula shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Ungula",
    description="Autonomous AI Agent System",
    version=__version__,
    lifespan=lifespan,
)

# Configure rate limiter
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: FastAPIRequest, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Try again later."},
    )


# Configure CORS -- origins from config, explicit methods/headers
_cors_origins = ["http://localhost:3001", "http://localhost:3000", "http://localhost:5173"]
try:
    _boot_config = load_config()
    if _boot_config.server.cors_origins:
        _cors_origins = _boot_config.server.cors_origins
except Exception:
    pass

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)


# Health check endpoint
@app.get("/api/health")
async def health_check() -> dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": __version__,
    }


# API info endpoint
@app.get("/")
async def root() -> dict[str, Any]:
    """Root endpoint with API information."""
    return {
        "name": "Ungula",
        "version": __version__,
        "description": "Autonomous AI Agent System",
        "docs_url": "/docs",
    }


# Include routers
app.include_router(auth_routes.router, prefix="/api/auth", tags=["auth"])
app.include_router(config_routes.router, prefix="/api/config", tags=["config"])
app.include_router(conversation_routes.router, prefix="/api/conversations", tags=["conversations"])
app.include_router(chat_routes.router, prefix="/api/chat", tags=["chat"])
app.include_router(channel_routes.router, prefix="/api/channels", tags=["channels"])
app.include_router(skills_routes.router, prefix="/api/skills", tags=["skills"])
app.include_router(cron_routes.router, prefix="/api/cron", tags=["cron"])
app.include_router(memory_routes.router, prefix="/api/memory", tags=["memory"])
app.include_router(pairing_routes.router, prefix="/api/pairing", tags=["pairing"])
app.include_router(security_routes.router, prefix="/api/security", tags=["security"])
app.include_router(subagent_routes.router, prefix="/api/subagents", tags=["subagents"])
app.include_router(node_routes.router, prefix="/api/nodes", tags=["nodes"])
app.include_router(webhook_routes.router, prefix="/api/webhooks", tags=["webhooks"])
app.include_router(plugin_routes.router, prefix="/api/plugins", tags=["plugins"])
app.include_router(usage_routes.router, prefix="/api/usage", tags=["usage"])
app.include_router(agents_config_routes.router, prefix="/api/agents", tags=["agents"])
app.include_router(runtime_routes.router, prefix="/api/runtime", tags=["runtime"])
app.include_router(events_routes.router, prefix="/api/events", tags=["events"])
app.include_router(queue_routes.router, prefix="/api/queue", tags=["queue"])
app.include_router(ws_routes.router, tags=["websocket"])
app.include_router(ws_node_routes.router, tags=["websocket"])

# Serve frontend static files if dist directory exists (Docker/production)
_frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if not _frontend_dist.is_dir():
    _frontend_dist = Path("/app/frontend/dist")
if _frontend_dist.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")


async def rebuild_registry(app_instance: FastAPI) -> None:
    """Rebuild the LLM registry from current config, closing old providers."""
    old_registry = app_instance.state.registry
    for provider in old_registry.providers.values():
        try:
            await provider.close()
        except Exception:
            pass
    new_registry = create_registry_from_config(app_instance.state.config.llm)
    app_instance.state.registry = new_registry
    # Update agent runner's registry reference
    app_instance.state.agent_runner.registry = new_registry
    # Update factory's registry and invalidate cached runners
    factory = getattr(app_instance.state, "agent_factory", None)
    if factory:
        factory.update_registry(new_registry)
        factory.invalidate()
    logger.info("Rebuilt LLM registry with providers: %s", new_registry.list_providers())


def run(
    host: str | None = None,
    port: int | None = None,
    ssl_certfile: str | None = None,
    ssl_keyfile: str | None = None,
):
    """Run the server using uvicorn."""
    import uvicorn

    config = load_config()
    kwargs: dict = {
        "host": host or config.server.host,
        "port": port or config.server.port,
        "reload": config.server.reload,
        "workers": config.server.workers,
    }

    # TLS: CLI args take precedence, then config file
    cert = ssl_certfile or getattr(config.server, "tls_cert_path", None)
    key = ssl_keyfile or getattr(config.server, "tls_key_path", None)
    if cert and key:
        from pathlib import Path

        if Path(cert).is_file() and Path(key).is_file():
            kwargs["ssl_certfile"] = cert
            kwargs["ssl_keyfile"] = key
        else:
            logger.warning("TLS cert/key files not found, running without TLS")

    uvicorn.run("ungula.main:app", **kwargs)


if __name__ == "__main__":
    run()
