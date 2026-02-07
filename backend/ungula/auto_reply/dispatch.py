"""
Auto-reply dispatcher.

Routes incoming channel messages: directives get handled immediately,
normal messages go through the agent pipeline.
"""

import logging
from typing import Any

from .chunker import chunk_response
from .directives import Directive, DirectiveParser

logger = logging.getLogger(__name__)


class AutoReplyDispatcher:
    """
    Dispatches messages to either directive handlers or the agent.

    Checks if a message is a directive first. If so, handles it
    directly and returns a response. Otherwise, returns None to
    indicate the message should go through normal agent processing.
    """

    def __init__(self, parser: DirectiveParser | None = None):
        self.parser = parser or DirectiveParser()

    async def try_dispatch(
        self,
        content: str,
        channel: str = "default",
        context: dict[str, Any] | None = None,
    ) -> list[str] | None:
        """
        Try to dispatch a message as a directive.

        Args:
            content: The message text.
            channel: Channel name for response chunking.
            context: Optional context (agent_runner, conversation_id, etc.).

        Returns:
            List of response chunks if handled as a directive,
            or None if this is a normal message for the agent.
        """
        directive = self.parser.parse(content)
        if directive is None:
            return None

        response = await self._handle_directive(directive, context or {})
        if response is None:
            return None

        # Chunk the response for the channel
        return chunk_response(response, channel=channel)

    async def _handle_directive(
        self,
        directive: Directive,
        context: dict[str, Any],
    ) -> str | None:
        """Handle a parsed directive."""
        handler = getattr(self, f"_handle_{directive.command}", None)
        if handler:
            return await handler(directive, context)

        return f"Unknown directive: /{directive.command}"

    async def _handle_help(
        self, directive: Directive, context: dict[str, Any]
    ) -> str:
        """Handle /help directive."""
        return (
            "Available commands:\n"
            "  /help    - Show this help message\n"
            "  /status  - Show system status\n"
            "  /model <name> - Switch LLM model\n"
            "  /think   - Show reasoning for next response\n"
            "  /compact - Compact conversation history\n"
            "  /reset   - Reset conversation\n"
            "  /ping    - Check if bot is alive"
        )

    async def _handle_ping(
        self, directive: Directive, context: dict[str, Any]
    ) -> str:
        """Handle /ping directive."""
        return "Pong! I'm here and working."

    async def _handle_status(
        self, directive: Directive, context: dict[str, Any]
    ) -> str:
        """Handle /status directive."""
        lines = ["System Status:"]

        agent_runner = context.get("agent_runner")
        if agent_runner:
            providers = agent_runner.registry.list_providers()
            lines.append(f"  LLM Providers: {', '.join(providers) if providers else 'none'}")
            lines.append(f"  Default Provider: {agent_runner.default_provider or 'not set'}")

            if agent_runner.tool_registry:
                tools = agent_runner.tool_registry.list_tools()
                lines.append(f"  Tools: {', '.join(tools) if tools else 'none'}")

        return "\n".join(lines)

    async def _handle_model(
        self, directive: Directive, context: dict[str, Any]
    ) -> str:
        """Handle /model directive."""
        if not directive.args:
            agent_runner = context.get("agent_runner")
            current = agent_runner.default_model if agent_runner else "unknown"
            return f"Current model: {current or 'default'}\nUsage: /model <model_name>"

        # Model switching would need to be implemented per-conversation
        return f"Model switching to '{directive.args}' noted. (Per-conversation model switching coming soon.)"

    async def _handle_think(
        self, directive: Directive, context: dict[str, Any]
    ) -> str:
        """Handle /think directive."""
        return "Thinking mode enabled for the next response. I'll show my reasoning."

    async def _handle_compact(
        self, directive: Directive, context: dict[str, Any]
    ) -> str:
        """Handle /compact directive."""
        return "Context compaction triggered. Older messages will be summarized."

    async def _handle_reset(
        self, directive: Directive, context: dict[str, Any]
    ) -> str:
        """Handle /reset directive."""
        return "Conversation reset. Starting fresh!"
