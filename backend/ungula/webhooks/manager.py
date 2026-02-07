"""
Webhook manager.

Handles CRUD operations, payload processing, signature verification,
template rendering, and agent dispatch for incoming webhooks.
"""

import logging
import secrets
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select, update

from ..storage.models import WebhookEventModel, WebhookModel
from .presets import PRESETS, get_preset
from .templates import render_template
from .verification import (
    verify_generic_hmac,
    verify_github_signature,
    verify_slack_signature,
    verify_stripe_signature,
)

logger = logging.getLogger(__name__)


class WebhookManager:
    """Manages webhooks: CRUD, receive, verify, process, dispatch."""

    def __init__(self, storage: Any, agent_runner: Any = None):
        self.storage = storage
        self.agent_runner = agent_runner

    # --- CRUD ---

    async def create(
        self,
        name: str,
        preset: str = "generic",
        template: str | None = None,
        target_conversation_id: str | None = None,
        trigger_agent: bool = True,
    ) -> dict[str, Any]:
        """Create a new webhook."""
        webhook_id = str(uuid.uuid4())
        slug = secrets.token_urlsafe(16)
        secret = secrets.token_urlsafe(32)

        # Use preset's default template if none provided
        if template is None:
            preset_obj = get_preset(preset)
            if preset_obj:
                template = preset_obj.default_template

        async with self.storage.session() as session:
            webhook = WebhookModel(
                id=webhook_id,
                name=name,
                slug=slug,
                secret=secret,
                preset=preset,
                template=template,
                target_conversation_id=target_conversation_id,
                trigger_agent=trigger_agent,
            )
            session.add(webhook)
            await session.commit()

        return {
            "id": webhook_id,
            "name": name,
            "slug": slug,
            "secret": secret,
            "preset": preset,
            "receive_url": f"/api/webhooks/receive/{slug}",
        }

    async def list_all(self) -> list[dict[str, Any]]:
        """List all webhooks."""
        async with self.storage.session() as session:
            result = await session.execute(select(WebhookModel))
            webhooks = result.scalars().all()
            return [
                {
                    "id": w.id,
                    "name": w.name,
                    "slug": w.slug,
                    "enabled": w.enabled,
                    "preset": w.preset,
                    "trigger_agent": w.trigger_agent,
                    "receive_url": f"/api/webhooks/receive/{w.slug}",
                    "created_at": w.created_at.isoformat() if w.created_at else None,
                }
                for w in webhooks
            ]

    async def get(self, webhook_id: str) -> dict[str, Any] | None:
        """Get webhook details."""
        async with self.storage.session() as session:
            result = await session.execute(
                select(WebhookModel).where(WebhookModel.id == webhook_id)
            )
            w = result.scalar_one_or_none()
            if not w:
                return None
            return {
                "id": w.id,
                "name": w.name,
                "slug": w.slug,
                "enabled": w.enabled,
                "secret": w.secret,
                "preset": w.preset,
                "template": w.template,
                "target_conversation_id": w.target_conversation_id,
                "trigger_agent": w.trigger_agent,
                "receive_url": f"/api/webhooks/receive/{w.slug}",
                "created_at": w.created_at.isoformat() if w.created_at else None,
            }

    async def update(self, webhook_id: str, **kwargs) -> bool:
        """Update webhook fields."""
        allowed = {"name", "enabled", "template", "target_conversation_id", "trigger_agent", "preset"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return False

        async with self.storage.session() as session:
            result = await session.execute(
                update(WebhookModel).where(WebhookModel.id == webhook_id).values(**updates)
            )
            await session.commit()
            return result.rowcount > 0

    async def delete(self, webhook_id: str) -> bool:
        """Delete a webhook and its events."""
        async with self.storage.session() as session:
            result = await session.execute(
                delete(WebhookModel).where(WebhookModel.id == webhook_id)
            )
            await session.commit()
            return result.rowcount > 0

    # --- Event Processing ---

    async def receive(
        self,
        slug: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        raw_body: bytes,
    ) -> dict[str, Any]:
        """Receive and process an incoming webhook event."""
        # Look up webhook by slug
        async with self.storage.session() as session:
            result = await session.execute(
                select(WebhookModel).where(WebhookModel.slug == slug)
            )
            webhook = result.scalar_one_or_none()

        if not webhook:
            return {"error": "Webhook not found", "status": 404}

        if not webhook.enabled:
            return {"error": "Webhook disabled", "status": 403}

        # Verify signature
        if webhook.secret:
            verified = self._verify_signature(
                webhook.preset, webhook.secret, raw_body, headers
            )
            if not verified:
                # Log the failed event
                await self._save_event(webhook.id, payload, headers, status="failed", error="Signature verification failed")
                return {"error": "Invalid signature", "status": 401}

        # Render template
        template = webhook.template or ""
        processed = render_template(template, payload, headers)

        # Save event
        event_id = await self._save_event(
            webhook.id, payload, headers,
            processed_content=processed, status="processed"
        )

        # Dispatch to agent if configured
        if webhook.trigger_agent and self.agent_runner and webhook.target_conversation_id:
            try:
                await self.agent_runner.run(
                    conversation_id=webhook.target_conversation_id,
                    user_message=f"[Webhook: {webhook.name}]\n{processed}",
                )
            except Exception as e:
                logger.error("Failed to dispatch webhook to agent: %s", e)

        return {"status": "ok", "event_id": event_id}

    async def get_events(self, webhook_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent events for a webhook."""
        async with self.storage.session() as session:
            result = await session.execute(
                select(WebhookEventModel)
                .where(WebhookEventModel.webhook_id == webhook_id)
                .order_by(WebhookEventModel.created_at.desc())
                .limit(limit)
            )
            events = result.scalars().all()
            return [
                {
                    "id": e.id,
                    "status": e.status,
                    "processed_content": e.processed_content,
                    "error": e.error,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in events
            ]

    # --- Helpers ---

    def _verify_signature(
        self, preset: str, secret: str, raw_body: bytes, headers: dict[str, str]
    ) -> bool:
        """Verify webhook signature based on preset type."""
        if preset == "github":
            sig = headers.get("x-hub-signature-256", "")
            return verify_github_signature(raw_body, secret, sig)
        elif preset == "stripe":
            sig = headers.get("stripe-signature", "")
            return verify_stripe_signature(raw_body, secret, sig)
        elif preset == "slack":
            sig = headers.get("x-slack-signature", "")
            ts = headers.get("x-slack-request-timestamp", "")
            return verify_slack_signature(raw_body, secret, sig, ts)
        else:
            # Generic HMAC
            preset_obj = get_preset(preset) or get_preset("generic")
            sig_header = preset_obj.signature_header.lower() if preset_obj else "x-webhook-signature"
            sig = headers.get(sig_header, headers.get("x-webhook-signature", ""))
            return verify_generic_hmac(raw_body, secret, sig)

    async def _save_event(
        self,
        webhook_id: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        processed_content: str | None = None,
        status: str = "pending",
        error: str | None = None,
    ) -> str:
        """Save a webhook event to the database."""
        event_id = str(uuid.uuid4())
        async with self.storage.session() as session:
            event = WebhookEventModel(
                id=event_id,
                webhook_id=webhook_id,
                payload=payload,
                headers=dict(headers),
                processed_content=processed_content,
                status=status,
                error=error,
            )
            session.add(event)
            await session.commit()
        return event_id
