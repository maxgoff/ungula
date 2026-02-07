"""
Webhook presets for common services.
"""

from dataclasses import dataclass


@dataclass
class WebhookPreset:
    """Configuration preset for a webhook service."""

    name: str
    signature_header: str
    scheme: str  # hmac-sha256, stripe, slack
    default_template: str

    def __str__(self) -> str:
        return self.name


PRESETS: dict[str, WebhookPreset] = {
    "github": WebhookPreset(
        name="GitHub",
        signature_header="X-Hub-Signature-256",
        scheme="hmac-sha256",
        default_template=(
            "**GitHub {{ headers.get('X-GitHub-Event', 'event') }}** "
            "on `{{ payload.get('repository', {}).get('full_name', 'unknown') }}`\n"
            "{% if payload.get('action') %}Action: {{ payload.action }}{% endif %}\n"
            "{% if payload.get('sender') %}By: {{ payload.sender.login }}{% endif %}"
        ),
    ),
    "stripe": WebhookPreset(
        name="Stripe",
        signature_header="Stripe-Signature",
        scheme="stripe",
        default_template=(
            "**Stripe {{ payload.get('type', 'event') }}**\n"
            "{% if payload.get('data', {}).get('object') %}"
            "Object: {{ payload.data.object.get('id', 'unknown') }}"
            "{% endif %}"
        ),
    ),
    "slack": WebhookPreset(
        name="Slack",
        signature_header="X-Slack-Signature",
        scheme="slack",
        default_template=(
            "**Slack event**: {{ payload.get('event', {}).get('type', 'unknown') }}\n"
            "{% if payload.get('event', {}).get('text') %}"
            "{{ payload.event.text }}"
            "{% endif %}"
        ),
    ),
    "generic": WebhookPreset(
        name="Generic",
        signature_header="X-Webhook-Signature",
        scheme="hmac-sha256",
        default_template="Webhook received:\n```json\n{{ payload | tojson(indent=2) }}\n```",
    ),
}


def get_preset(name: str) -> WebhookPreset | None:
    """Get a webhook preset by name."""
    return PRESETS.get(name)
