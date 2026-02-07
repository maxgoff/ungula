"""
Capability decorator and registry for node command handlers.

Usage:
    from ungula_node.capabilities import capability, get_registry

    @capability("notify.send")
    async def send_notification(args):
        # handle command
        return {"success": True, "output": "Notification sent"}

    registry = get_registry()
    handler = registry.get("notify.send")
"""

import logging
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

# Global handler registry
_handlers: dict[str, Callable] = {}


def capability(command: str):
    """Decorator to register a function as a handler for a node command."""

    def decorator(func: Callable[..., Coroutine[Any, Any, dict[str, Any]]]):
        _handlers[command] = func
        logger.debug("Registered capability handler: %s", command)
        return func

    return decorator


def get_registry() -> dict[str, Callable]:
    """Get the current handler registry."""
    return dict(_handlers)


def get_capabilities() -> list[str]:
    """Get list of registered capability names."""
    return list(_handlers.keys())


async def dispatch(command: str, args: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a command to the registered handler.

    Returns:
        Dict with 'success', 'output', and optionally 'data'.
    """
    handler = _handlers.get(command)
    if not handler:
        return {
            "success": False,
            "output": "",
            "error": f"No handler for command: {command}",
        }

    try:
        result = await handler(args)
        return result
    except Exception as e:
        logger.error("Handler error for %s: %s", command, e)
        return {
            "success": False,
            "output": "",
            "error": str(e),
        }
