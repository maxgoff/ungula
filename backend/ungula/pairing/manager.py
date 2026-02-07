"""
Pairing Manager.

Handles generation and verification of pairing codes for
authenticating channel contacts (DM users, etc.).
"""

import logging
import secrets
import string

from .store import PairingRequest, PairingStore

logger = logging.getLogger(__name__)

# Characters for pairing codes (no ambiguous chars: 0/O, 1/I/l)
CODE_CHARS = string.ascii_uppercase.replace("O", "").replace("I", "") + string.digits.replace("0", "").replace("1", "")
CODE_LENGTH = 8


class PairingManager:
    """
    Manages the pairing flow for channel contacts.

    Flow:
    1. Contact sends a message via channel (Discord DM, etc.)
    2. If dm_policy == "pairing" and contact not yet paired:
       a. Generate a pairing code
       b. Send code to the contact
       c. User enters code in the web UI to verify
    3. Once verified, the contact is allowed to chat
    """

    def __init__(
        self,
        ttl_seconds: int = 3600,
        max_pending: int = 3,
    ):
        self.store = PairingStore(
            ttl_seconds=ttl_seconds,
            max_pending_per_contact=max_pending,
        )
        # Contacts that have been verified (channel:contact_id -> True)
        self._verified: set[str] = set()

    def _make_key(self, channel: str, contact_id: str) -> str:
        return f"{channel}:{contact_id}"

    def is_paired(self, channel: str, contact_id: str) -> bool:
        """Check if a contact is already paired."""
        return self._make_key(channel, contact_id) in self._verified

    async def generate_code(
        self,
        channel: str,
        contact_id: str,
        contact_name: str | None = None,
    ) -> str | None:
        """
        Generate a pairing code for a contact.

        Returns the code, or None if max pending limit reached.
        """
        code = "".join(secrets.choice(CODE_CHARS) for _ in range(CODE_LENGTH))

        request = PairingRequest(
            code=code,
            channel=channel,
            contact_id=contact_id,
            contact_name=contact_name,
        )

        added = await self.store.add(request)
        if not added:
            logger.warning(
                "Max pending pairing requests for %s:%s",
                channel, contact_id,
            )
            return None

        logger.info(
            "Generated pairing code for %s:%s (%s)",
            channel, contact_id, contact_name,
        )
        return code

    async def verify_code(self, code: str) -> PairingRequest | None:
        """
        Verify a pairing code.

        If valid, marks the contact as paired.
        Returns the request if successful, None if invalid.
        """
        code = code.upper().strip()
        request = await self.store.verify(code)

        if request:
            key = self._make_key(request.channel, request.contact_id)
            self._verified.add(key)
            logger.info(
                "Paired %s:%s (%s)",
                request.channel, request.contact_id, request.contact_name,
            )

        return request

    async def list_pending(self) -> list[PairingRequest]:
        """List all pending pairing requests."""
        return await self.store.get_pending()

    async def revoke_code(self, code: str) -> bool:
        """Revoke a pending pairing code."""
        return await self.store.revoke(code)

    def unpair(self, channel: str, contact_id: str) -> bool:
        """Remove a paired contact."""
        key = self._make_key(channel, contact_id)
        if key in self._verified:
            self._verified.discard(key)
            return True
        return False
