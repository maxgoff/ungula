"""
REST API routes for webhook management and event reception.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


class CreateWebhookRequest(BaseModel):
    name: str
    preset: str = "generic"
    template: str | None = None
    target_conversation_id: str | None = None
    trigger_agent: bool = True


class UpdateWebhookRequest(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    template: str | None = None
    target_conversation_id: str | None = None
    trigger_agent: bool | None = None
    preset: str | None = None


class TestWebhookRequest(BaseModel):
    payload: dict[str, Any] | None = None


# --- CRUD ---

@router.post("/")
async def create_webhook(body: CreateWebhookRequest, request: Request):
    """Create a new webhook."""
    manager = request.app.state.webhook_manager
    result = await manager.create(
        name=body.name,
        preset=body.preset,
        template=body.template,
        target_conversation_id=body.target_conversation_id,
        trigger_agent=body.trigger_agent,
    )
    return result


@router.get("/")
async def list_webhooks(request: Request):
    """List all webhooks."""
    manager = request.app.state.webhook_manager
    webhooks = await manager.list_all()
    return {"webhooks": webhooks}


@router.get("/{webhook_id}")
async def get_webhook(webhook_id: str, request: Request):
    """Get webhook details."""
    manager = request.app.state.webhook_manager
    webhook = await manager.get(webhook_id)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return webhook


@router.put("/{webhook_id}")
async def update_webhook(webhook_id: str, body: UpdateWebhookRequest, request: Request):
    """Update a webhook."""
    manager = request.app.state.webhook_manager
    updated = await manager.update(webhook_id, **body.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Webhook not found or no changes")
    return {"status": "updated"}


@router.delete("/{webhook_id}")
async def delete_webhook(webhook_id: str, request: Request):
    """Delete a webhook."""
    manager = request.app.state.webhook_manager
    deleted = await manager.delete(webhook_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return {"status": "deleted"}


@router.get("/{webhook_id}/events")
async def get_webhook_events(webhook_id: str, request: Request, limit: int = 20):
    """Get recent events for a webhook."""
    manager = request.app.state.webhook_manager
    events = await manager.get_events(webhook_id, limit=limit)
    return {"events": events}


# --- Receive (public, HMAC-protected) ---

@router.post("/receive/{slug}")
async def receive_webhook(slug: str, request: Request):
    """Receive an external webhook event. Verified by HMAC signature."""
    manager = request.app.state.webhook_manager

    # Read raw body for signature verification
    raw_body = await request.body()

    # Parse payload
    try:
        payload = json.loads(raw_body) if raw_body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {"raw": raw_body.decode("utf-8", errors="replace")}

    # Collect headers (lowercase keys)
    headers = {k.lower(): v for k, v in request.headers.items()}

    result = await manager.receive(slug, payload, headers, raw_body)

    status_code = result.pop("status", 200) if isinstance(result.get("status"), int) else 200
    if result.get("error"):
        raise HTTPException(status_code=status_code, detail=result["error"])

    return result


# --- Test ---

@router.post("/{webhook_id}/test")
async def test_webhook(webhook_id: str, body: TestWebhookRequest, request: Request):
    """Send a test event to a webhook."""
    manager = request.app.state.webhook_manager
    webhook = await manager.get(webhook_id)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    test_payload = body.payload or {
        "event": "test",
        "message": "This is a test webhook event",
        "webhook_id": webhook_id,
    }

    # Process without signature verification
    from ...webhooks.templates import render_template

    template = webhook.get("template", "")
    processed = render_template(template, test_payload, {"x-test": "true"})

    event_id = await manager._save_event(
        webhook_id, test_payload, {"x-test": "true"},
        processed_content=processed, status="processed"
    )

    return {"status": "ok", "event_id": event_id, "processed": processed}
