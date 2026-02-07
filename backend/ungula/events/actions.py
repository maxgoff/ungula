"""
Action Executor for event-triggered rules.

Executes the action defined in an EventRule when an event matches.
"""

import logging
from typing import Any

from .types import ActionType, Event, EventRule

logger = logging.getLogger(__name__)


class ActionExecutor:
    """
    Executes actions for matched event rules.

    Holds references to agent_runner, tool_registry, and channel_registry
    for dispatching the various action types.
    """

    def __init__(
        self,
        agent_runner: Any = None,
        tool_registry: Any = None,
        channel_registry: Any = None,
    ):
        self.agent_runner = agent_runner
        self.tool_registry = tool_registry
        self.channel_registry = channel_registry

    async def execute(self, rule: EventRule, event: Event) -> None:
        """Execute the action defined in a rule."""
        action = rule.action
        config = rule.action_config

        if action == ActionType.RUN_AGENT:
            await self._run_agent(config, event)
        elif action == ActionType.EXECUTE_TOOL:
            await self._execute_tool(config, event)
        elif action == ActionType.SEND_MESSAGE:
            await self._send_message(config, event)
        elif action == ActionType.CALL_WEBHOOK:
            await self._call_webhook(config, event)
        elif action == ActionType.LOG:
            await self._log(config, event)
        else:
            logger.warning("Unknown action type: %s", action)

    async def _run_agent(self, config: dict[str, Any], event: Event) -> None:
        """Run an agent with a message derived from the event."""
        if not self.agent_runner:
            logger.warning("No agent_runner available for run_agent action")
            return

        conversation_id = config.get("conversation_id")
        message = config.get("message", f"Event triggered: {event.type}")

        # Template simple variable substitution
        for key, value in event.data.items():
            message = message.replace(f"{{{key}}}", str(value))

        if conversation_id:
            await self.agent_runner.run(
                conversation_id=conversation_id,
                user_message=message,
            )

    async def _execute_tool(self, config: dict[str, Any], event: Event) -> None:
        """Execute a tool."""
        if not self.tool_registry:
            logger.warning("No tool_registry available for execute_tool action")
            return

        tool_name = config.get("tool_name")
        tool_args = config.get("args", {})

        if tool_name:
            result = await self.tool_registry.execute(tool_name, **tool_args)
            logger.info(
                "Tool %s executed via event rule: success=%s",
                tool_name, result.success,
            )

    async def _send_message(self, config: dict[str, Any], event: Event) -> None:
        """Send a message via a channel."""
        if not self.channel_registry:
            logger.warning("No channel_registry available for send_message action")
            return

        from ..messaging.base import OutboundMessage

        channel = config.get("channel")
        target = config.get("target")
        content = config.get("content", f"Event: {event.type}")

        # Template substitution
        for key, value in event.data.items():
            content = content.replace(f"{{{key}}}", str(value))

        if channel and target:
            outbound = OutboundMessage(
                channel=channel,
                target=target,
                content=content,
            )
            await self.channel_registry.send(outbound)

    async def _call_webhook(self, config: dict[str, Any], event: Event) -> None:
        """Call an external webhook URL."""
        import httpx

        url = config.get("url")
        if not url:
            return

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(url, json={
                    "event_type": event.type,
                    "event_id": event.id,
                    "data": event.data,
                    "timestamp": event.timestamp.isoformat(),
                })
        except Exception as e:
            logger.error("Webhook call failed for %s: %s", url, e)

    async def _log(self, config: dict[str, Any], event: Event) -> None:
        """Log the event."""
        level = config.get("level", "info").lower()
        message = config.get("message", f"Event: {event.type} data={event.data}")

        # Template substitution
        for key, value in event.data.items():
            message = message.replace(f"{{{key}}}", str(value))

        log_func = getattr(logger, level, logger.info)
        log_func("EventRule log: %s", message)
