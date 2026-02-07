"""
In-memory pairing request store.

Stores pending pairing codes with TTL and per-user limits.
Uses asyncio locks for thread safety.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class PairingRequest:
    """A pending pairing request."""

    code: str
    channel: str
    contact_id: str
    contact_name: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC) + timedelta(hours=1))
    verified: bool = False
    verified_at: datetime | None = None


class PairingStore:
    """
    In-memory store for pairing requests with TTL.

    Stores pending codes and handles expiration.
    """

    def __init__(
        self,
        ttl_seconds: int = 3600,  # 1 hour
        max_pending_per_contact: int = 3,
    ):
        self.ttl_seconds = ttl_seconds
        self.max_pending_per_contact = max_pending_per_contact
        self._by_code: dict[str, PairingRequest] = {}
        self._by_contact: dict[str, list[str]] = {}  # contact_id -> [codes]
        self._lock = asyncio.Lock()

    async def add(self, request: PairingRequest) -> bool:
        """
        Add a pairing request.

        Returns False if the contact has too many pending requests.
        """
        async with self._lock:
            self._cleanup_expired()

            # Check per-contact limit
            contact_codes = self._by_contact.get(request.contact_id, [])
            active = [c for c in contact_codes if c in self._by_code]
            if len(active) >= self.max_pending_per_contact:
                return False

            # Set expiration
            request.expires_at = datetime.now(UTC) + timedelta(seconds=self.ttl_seconds)

            self._by_code[request.code] = request
            if request.contact_id not in self._by_contact:
                self._by_contact[request.contact_id] = []
            self._by_contact[request.contact_id].append(request.code)

            return True

    async def verify(self, code: str) -> PairingRequest | None:
        """
        Verify a pairing code.

        Returns the request if valid, None if not found or expired.
        Marks the request as verified.
        """
        async with self._lock:
            self._cleanup_expired()

            request = self._by_code.get(code)
            if request is None:
                return None
            if request.verified:
                return None  # Already used

            request.verified = True
            request.verified_at = datetime.now(UTC)
            return request

    async def get_pending(self, contact_id: str | None = None) -> list[PairingRequest]:
        """List pending (unverified, unexpired) pairing requests."""
        async with self._lock:
            self._cleanup_expired()

            results = []
            for request in self._by_code.values():
                if request.verified:
                    continue
                if contact_id and request.contact_id != contact_id:
                    continue
                results.append(request)

            return sorted(results, key=lambda r: r.created_at, reverse=True)

    async def revoke(self, code: str) -> bool:
        """Revoke a pairing code."""
        async with self._lock:
            request = self._by_code.pop(code, None)
            if request:
                codes = self._by_contact.get(request.contact_id, [])
                if code in codes:
                    codes.remove(code)
                return True
            return False

    def _cleanup_expired(self) -> None:
        """Remove expired requests (must be called under lock)."""
        now = datetime.now(UTC)
        expired = [code for code, req in self._by_code.items() if req.expires_at < now]
        for code in expired:
            req = self._by_code.pop(code, None)
            if req:
                codes = self._by_contact.get(req.contact_id, [])
                if code in codes:
                    codes.remove(code)
