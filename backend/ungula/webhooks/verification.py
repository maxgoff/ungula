"""
Webhook signature verification for various services.
"""

import hashlib
import hmac
import logging

logger = logging.getLogger(__name__)


def verify_generic_hmac(payload: bytes, secret: str, signature: str, algorithm: str = "sha256") -> bool:
    """Verify a generic HMAC signature."""
    if not secret or not signature:
        return False

    # Strip prefix like "sha256=" if present
    if "=" in signature:
        _, _, sig_value = signature.partition("=")
    else:
        sig_value = signature

    hash_func = getattr(hashlib, algorithm, None)
    if not hash_func:
        logger.warning("Unknown hash algorithm: %s", algorithm)
        return False

    expected = hmac.new(
        secret.encode("utf-8"), payload, hash_func
    ).hexdigest()

    return hmac.compare_digest(expected.lower(), sig_value.lower())


def verify_github_signature(payload: bytes, secret: str, signature: str) -> bool:
    """Verify GitHub webhook signature (X-Hub-Signature-256)."""
    return verify_generic_hmac(payload, secret, signature, "sha256")


def verify_stripe_signature(payload: bytes, secret: str, sig_header: str) -> bool:
    """Verify Stripe webhook signature (Stripe-Signature header).

    Stripe signature format: t=timestamp,v1=signature
    """
    if not sig_header or not secret:
        return False

    parts = {}
    for item in sig_header.split(","):
        key, _, value = item.partition("=")
        parts[key.strip()] = value.strip()

    timestamp = parts.get("t", "")
    sig_value = parts.get("v1", "")
    if not timestamp or not sig_value:
        return False

    signed_payload = f"{timestamp}.".encode("utf-8") + payload
    expected = hmac.new(
        secret.encode("utf-8"), signed_payload, hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, sig_value)


def verify_slack_signature(payload: bytes, secret: str, signature: str, timestamp: str) -> bool:
    """Verify Slack webhook signature (X-Slack-Signature).

    Slack uses: v0=HMAC-SHA256(secret, "v0:{timestamp}:{body}")
    """
    if not secret or not signature or not timestamp:
        return False

    base_string = f"v0:{timestamp}:".encode("utf-8") + payload
    expected = "v0=" + hmac.new(
        secret.encode("utf-8"), base_string, hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature)
