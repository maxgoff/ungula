"""
Jinja2 template rendering for webhook payloads.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Lazy import jinja2 — it's part of FastAPI's deps via Starlette
_jinja_env = None


def _get_jinja_env():
    global _jinja_env
    if _jinja_env is None:
        try:
            from jinja2 import Environment, BaseLoader

            _jinja_env = Environment(
                loader=BaseLoader(),
                autoescape=False,
                keep_trailing_newline=True,
            )
            # Add tojson filter
            _jinja_env.filters["tojson"] = lambda v, **kw: json.dumps(v, **kw)
        except ImportError:
            logger.warning("jinja2 not available — webhook templates will return raw JSON")
            return None
    return _jinja_env


def render_template(template_str: str, payload: dict[str, Any], headers: dict[str, Any]) -> str:
    """Render a Jinja2 template with payload and headers context.

    Falls back to JSON dump if Jinja2 is not available or template fails.
    """
    if not template_str:
        return json.dumps(payload, indent=2)

    env = _get_jinja_env()
    if env is None:
        return json.dumps(payload, indent=2)

    try:
        tmpl = env.from_string(template_str)
        return tmpl.render(payload=payload, headers=headers)
    except Exception as e:
        logger.warning("Template render failed: %s", e)
        return json.dumps(payload, indent=2)
