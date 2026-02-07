"""
Semantic slug generation for memory files.

Calls the LLM to generate a 1-2 word semantic slug from conversation
content. Falls back to timestamp if LLM call fails or times out.
"""

import asyncio
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)


async def generate_slug(content: str, registry) -> str | None:
    """Generate a 1-2 word semantic slug from conversation content.

    Calls the LLM with a 10-second timeout. Returns a slug like
    "vendor-pitch" or "bug-fix", or None if it fails.

    Args:
        content: Formatted conversation text.
        registry: ProviderRegistry for LLM calls.

    Returns:
        Slug string or None on failure.
    """
    from ..llm.base import CompletionRequest, Message, MessageRole

    prompt = (
        "Generate a 1-2 word slug (lowercase, hyphen-separated) that "
        "summarizes the topic of this conversation. Reply with ONLY the slug, "
        "nothing else. Examples: 'vendor-pitch', 'bug-fix', 'api-design', "
        "'weekly-review'.\n\n"
        f"{content[:2000]}"
    )

    request = CompletionRequest(
        messages=[Message(role=MessageRole.USER, content=prompt)],
        max_tokens=20,
        temperature=0.0,
        stream=False,
    )

    try:
        response = await asyncio.wait_for(
            registry.complete(request),
            timeout=10.0,
        )
        raw = (response.content or "").strip().lower()
        # Sanitize: only allow lowercase letters, digits, hyphens
        slug = re.sub(r"[^a-z0-9-]", "", raw)
        slug = slug.strip("-")
        if slug and len(slug) <= 40:
            return slug
        return None
    except asyncio.TimeoutError:
        logger.warning("Slug generation timed out")
        return None
    except Exception as e:
        logger.warning("Slug generation failed: %s", e)
        return None
