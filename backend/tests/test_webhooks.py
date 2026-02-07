"""
Tests for the webhook system: verification, templates, presets.

Covers HMAC signature verification for GitHub, Stripe, Slack, and generic webhooks,
Jinja2 template rendering, preset configuration, and edge cases.
"""

import hashlib
import hmac
import json

import pytest

from ungula.webhooks.presets import PRESETS, WebhookPreset, get_preset
from ungula.webhooks.templates import render_template
from ungula.webhooks.verification import (
    verify_generic_hmac,
    verify_github_signature,
    verify_slack_signature,
    verify_stripe_signature,
)


# ===========================================================================
# verify_generic_hmac
# ===========================================================================


class TestVerifyGenericHMAC:
    """Tests for generic HMAC signature verification."""

    def _sign(self, payload: bytes, secret: str, algo: str = "sha256") -> str:
        hash_func = getattr(hashlib, algo)
        return hmac.new(secret.encode(), payload, hash_func).hexdigest()

    def test_valid_signature(self):
        payload = b'{"event": "test"}'
        secret = "test_secret_123"
        sig = self._sign(payload, secret)
        assert verify_generic_hmac(payload, secret, sig) is True

    def test_valid_with_prefix(self):
        payload = b'{"event": "test"}'
        secret = "test_secret_123"
        sig = "sha256=" + self._sign(payload, secret)
        assert verify_generic_hmac(payload, secret, sig) is True

    def test_invalid_signature(self):
        payload = b'{"event": "test"}'
        assert verify_generic_hmac(payload, "secret", "deadbeef") is False

    def test_empty_secret(self):
        assert verify_generic_hmac(b"data", "", "sig") is False

    def test_empty_signature(self):
        assert verify_generic_hmac(b"data", "secret", "") is False

    def test_unknown_algorithm(self):
        assert verify_generic_hmac(b"data", "secret", "sig", "fakealgo") is False

    def test_sha512(self):
        payload = b"sha512 test"
        secret = "secret_512"
        sig = self._sign(payload, secret, "sha512")
        assert verify_generic_hmac(payload, secret, sig, "sha512") is True

    def test_case_insensitive_comparison(self):
        payload = b"case test"
        secret = "case_secret"
        sig = self._sign(payload, secret).upper()
        assert verify_generic_hmac(payload, secret, sig) is True

    def test_tampered_payload(self):
        payload = b'{"event": "original"}'
        secret = "secret"
        sig = self._sign(payload, secret)
        tampered = b'{"event": "tampered"}'
        assert verify_generic_hmac(tampered, secret, sig) is False

    def test_wrong_secret(self):
        payload = b"data"
        sig = self._sign(payload, "correct_secret")
        assert verify_generic_hmac(payload, "wrong_secret", sig) is False


# ===========================================================================
# verify_github_signature
# ===========================================================================


class TestVerifyGitHubSignature:
    """Tests for GitHub webhook signature (X-Hub-Signature-256)."""

    def _github_sign(self, payload: bytes, secret: str) -> str:
        return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    def test_valid_github_signature(self):
        payload = b'{"action":"opened"}'
        secret = "github_secret"
        sig = self._github_sign(payload, secret)
        assert verify_github_signature(payload, secret, sig) is True

    def test_invalid_github_signature(self):
        assert verify_github_signature(b"data", "secret", "sha256=invalid") is False

    def test_empty_inputs(self):
        assert verify_github_signature(b"", "", "") is False
        assert verify_github_signature(b"data", "", "sig") is False
        assert verify_github_signature(b"data", "secret", "") is False


# ===========================================================================
# verify_stripe_signature
# ===========================================================================


class TestVerifyStripeSignature:
    """Tests for Stripe webhook signature (Stripe-Signature header)."""

    def _stripe_sign(self, payload: bytes, secret: str, timestamp: str) -> str:
        signed = f"{timestamp}.".encode() + payload
        sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        return f"t={timestamp},v1={sig}"

    def test_valid_stripe_signature(self):
        payload = b'{"type":"charge.succeeded"}'
        secret = "whsec_test"
        ts = "1234567890"
        sig_header = self._stripe_sign(payload, secret, ts)
        assert verify_stripe_signature(payload, secret, sig_header) is True

    def test_invalid_stripe_signature(self):
        assert verify_stripe_signature(b"data", "secret", "t=123,v1=invalid") is False

    def test_missing_timestamp(self):
        assert verify_stripe_signature(b"data", "secret", "v1=sig") is False

    def test_missing_v1(self):
        assert verify_stripe_signature(b"data", "secret", "t=123") is False

    def test_empty_header(self):
        assert verify_stripe_signature(b"data", "secret", "") is False

    def test_empty_secret(self):
        assert verify_stripe_signature(b"data", "", "t=123,v1=sig") is False

    def test_tampered_payload(self):
        payload = b'{"type":"original"}'
        secret = "whsec_test"
        ts = "1234567890"
        sig_header = self._stripe_sign(payload, secret, ts)
        assert verify_stripe_signature(b'{"type":"tampered"}', secret, sig_header) is False

    def test_stripe_format_with_extra_fields(self):
        """Stripe headers can include extra v1 values — only first matters."""
        payload = b"data"
        secret = "secret"
        ts = "123"
        signed = f"{ts}.".encode() + payload
        sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        # Extra fields after the first v1
        header = f"t={ts},v1={sig},v0=ignoreme"
        assert verify_stripe_signature(payload, secret, header) is True


# ===========================================================================
# verify_slack_signature
# ===========================================================================


class TestVerifySlackSignature:
    """Tests for Slack webhook signature (X-Slack-Signature)."""

    def _slack_sign(self, payload: bytes, secret: str, timestamp: str) -> str:
        base = f"v0:{timestamp}:".encode() + payload
        sig = hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
        return f"v0={sig}"

    def test_valid_slack_signature(self):
        payload = b'{"event":{"type":"message"}}'
        secret = "slack_signing_secret"
        ts = "1234567890"
        sig = self._slack_sign(payload, secret, ts)
        assert verify_slack_signature(payload, secret, sig, ts) is True

    def test_invalid_slack_signature(self):
        assert verify_slack_signature(b"data", "secret", "v0=invalid", "123") is False

    def test_empty_timestamp(self):
        assert verify_slack_signature(b"data", "secret", "v0=sig", "") is False

    def test_empty_secret(self):
        assert verify_slack_signature(b"data", "", "v0=sig", "123") is False

    def test_empty_signature(self):
        assert verify_slack_signature(b"data", "secret", "", "123") is False

    def test_tampered_payload(self):
        payload = b"original"
        secret = "slack_secret"
        ts = "999"
        sig = self._slack_sign(payload, secret, ts)
        assert verify_slack_signature(b"tampered", secret, sig, ts) is False


# ===========================================================================
# render_template
# ===========================================================================


class TestRenderTemplate:
    """Tests for Jinja2 template rendering."""

    def test_empty_template_returns_json(self):
        payload = {"key": "value"}
        result = render_template("", payload, {})
        assert json.loads(result) == payload

    def test_simple_template(self):
        result = render_template("Event: {{ payload.event }}", {"event": "push"}, {})
        assert result == "Event: push"

    def test_template_with_headers(self):
        result = render_template(
            "Source: {{ headers.get('x-source', 'unknown') }}",
            {},
            {"x-source": "github"},
        )
        assert result == "Source: github"

    def test_tojson_filter(self):
        result = render_template(
            "{{ payload | tojson(indent=2) }}",
            {"a": 1, "b": "two"},
            {},
        )
        parsed = json.loads(result)
        assert parsed == {"a": 1, "b": "two"}

    def test_complex_template(self):
        template = (
            "**{{ payload.get('action', 'event') }}** on {{ payload.get('repo', 'unknown') }}\n"
            "{% if payload.get('user') %}By: {{ payload.user }}{% endif %}"
        )
        payload = {"action": "push", "repo": "myrepo", "user": "alice"}
        result = render_template(template, payload, {})
        assert "push" in result
        assert "myrepo" in result
        assert "alice" in result

    def test_template_error_falls_back_to_json(self):
        # Invalid Jinja2 syntax should fall back gracefully
        result = render_template("{{ bad_syntax|", {"key": "val"}, {})
        # Should return JSON fallback
        parsed = json.loads(result)
        assert parsed == {"key": "val"}

    def test_nested_payload(self):
        result = render_template(
            "{{ payload.data.object.id }}",
            {"data": {"object": {"id": "obj_123"}}},
            {},
        )
        assert result == "obj_123"


# ===========================================================================
# Presets
# ===========================================================================


class TestWebhookPresets:
    """Tests for webhook presets configuration."""

    def test_all_presets_exist(self):
        expected = {"github", "stripe", "slack", "generic"}
        assert set(PRESETS.keys()) == expected

    def test_get_preset_github(self):
        preset = get_preset("github")
        assert preset is not None
        assert preset.name == "GitHub"
        assert preset.signature_header == "X-Hub-Signature-256"
        assert preset.scheme == "hmac-sha256"

    def test_get_preset_stripe(self):
        preset = get_preset("stripe")
        assert preset is not None
        assert preset.name == "Stripe"
        assert preset.signature_header == "Stripe-Signature"
        assert preset.scheme == "stripe"

    def test_get_preset_slack(self):
        preset = get_preset("slack")
        assert preset is not None
        assert preset.name == "Slack"
        assert preset.signature_header == "X-Slack-Signature"
        assert preset.scheme == "slack"

    def test_get_preset_generic(self):
        preset = get_preset("generic")
        assert preset is not None
        assert preset.scheme == "hmac-sha256"

    def test_get_preset_unknown(self):
        assert get_preset("nonexistent") is None

    def test_preset_has_default_template(self):
        for name, preset in PRESETS.items():
            assert preset.default_template, f"Preset {name} has no default_template"

    def test_preset_str(self):
        preset = get_preset("github")
        assert str(preset) == "GitHub"

    def test_webhook_preset_dataclass(self):
        preset = WebhookPreset(
            name="Custom",
            signature_header="X-Custom-Sig",
            scheme="hmac-sha256",
            default_template="Custom: {{ payload }}",
        )
        assert preset.name == "Custom"
        assert preset.scheme == "hmac-sha256"


# ===========================================================================
# WebhookManager._verify_signature
# ===========================================================================


class TestWebhookManagerVerifySignature:
    """Tests for the manager's signature routing logic."""

    def _make_manager(self):
        from ungula.webhooks.manager import WebhookManager
        # Create with mock storage
        mock_storage = type("MockStorage", (), {"session": lambda self: None})()
        return WebhookManager(storage=mock_storage)

    def test_github_routing(self):
        manager = self._make_manager()
        payload = b'{"test": true}'
        secret = "gh_secret"
        sig = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert manager._verify_signature("github", secret, payload, {"x-hub-signature-256": sig}) is True

    def test_stripe_routing(self):
        manager = self._make_manager()
        payload = b"stripe_test"
        secret = "stripe_secret"
        ts = "123"
        signed = f"{ts}.".encode() + payload
        sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        headers = {"stripe-signature": f"t={ts},v1={sig}"}
        assert manager._verify_signature("stripe", secret, payload, headers) is True

    def test_slack_routing(self):
        manager = self._make_manager()
        payload = b"slack_test"
        secret = "slack_secret"
        ts = "456"
        base = f"v0:{ts}:".encode() + payload
        sig = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
        headers = {"x-slack-signature": sig, "x-slack-request-timestamp": ts}
        assert manager._verify_signature("slack", secret, payload, headers) is True

    def test_generic_routing(self):
        manager = self._make_manager()
        payload = b"generic_test"
        secret = "gen_secret"
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        headers = {"x-webhook-signature": sig}
        assert manager._verify_signature("generic", secret, payload, headers) is True

    def test_unknown_preset_uses_generic(self):
        manager = self._make_manager()
        payload = b"custom_test"
        secret = "custom_secret"
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        headers = {"x-webhook-signature": sig}
        assert manager._verify_signature("custom_thing", secret, payload, headers) is True
