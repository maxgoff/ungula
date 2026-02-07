"""
Comprehensive tests for the Ungula JWT authentication module.

Tests cover password hashing/verification, token creation and decoding,
the get_current_user dependency, and various edge cases around token
expiration and malformed payloads.
"""

import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import bcrypt
import pytest
from fastapi import HTTPException
from jose import jwt

from ungula.auth import (
    _resolve_user,
    configure_auth,
    create_access_token,
    get_current_user,
    get_current_user_optional,
    verify_password,
)
from ungula.storage.base import User

# ---------------------------------------------------------------------------
# Constants used across multiple test classes
# ---------------------------------------------------------------------------

TEST_SECRET = "test-secret-key-for-unit-tests-only"
TEST_ALGORITHM = "HS256"
TEST_EXPIRE_MINUTES = 30
TEST_PASSWORD = "correct-horse-battery-staple"
TEST_USER_ID = uuid4()


def _make_user(
    user_id: UUID | None = None,
    email: str = "tester@ungula.dev",
    is_active: bool = True,
) -> User:
    """Helper to build a User model for assertions."""
    now = datetime.now(UTC)
    return User(
        id=user_id or TEST_USER_ID,
        email=email,
        name="Test User",
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )


def _hash_password(plain: str) -> str:
    """Hash a password with bcrypt (real crypto, no mocking)."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _configure_auth_module():
    """
    Ensure the auth module globals are in a known state before each test
    and reset them afterward so tests are fully isolated.
    """
    configure_auth(
        secret_key=TEST_SECRET,
        algorithm=TEST_ALGORITHM,
        token_expire_minutes=TEST_EXPIRE_MINUTES,
        storage=None,
    )
    yield
    # Reset to blank state
    configure_auth(secret_key="", algorithm="HS256", token_expire_minutes=1440, storage=None)


@pytest.fixture
def mock_storage() -> AsyncMock:
    """Return an AsyncMock that behaves like a StorageBackend."""
    return AsyncMock()


@pytest.fixture
def active_user() -> User:
    """A standard active user for tests."""
    return _make_user()


@pytest.fixture
def inactive_user() -> User:
    """An inactive user for tests."""
    return _make_user(is_active=False)


# ===========================================================================
# Password hashing and verification
# ===========================================================================


class TestPasswordHashing:
    """Tests for verify_password and the underlying bcrypt round-trip."""

    def test_correct_password_verifies(self):
        """A password should verify against its own bcrypt hash."""
        hashed = _hash_password(TEST_PASSWORD)
        assert verify_password(TEST_PASSWORD, hashed) is True

    def test_wrong_password_fails(self):
        """An incorrect password should not verify."""
        hashed = _hash_password(TEST_PASSWORD)
        assert verify_password("wrong-password", hashed) is False

    def test_empty_password_fails(self):
        """An empty string should not verify against a real hash."""
        hashed = _hash_password(TEST_PASSWORD)
        assert verify_password("", hashed) is False

    def test_empty_password_hashes_and_verifies(self):
        """Even an empty password should hash and round-trip correctly."""
        hashed = _hash_password("")
        assert verify_password("", hashed) is True

    def test_unicode_password(self):
        """Unicode passwords should hash and verify correctly."""
        unicode_pw = "p\u00e4ssw\u00f6rd-\u2603-\U0001f512"
        hashed = _hash_password(unicode_pw)
        assert verify_password(unicode_pw, hashed) is True
        assert verify_password("passw0rd", hashed) is False

    def test_long_password_rejected(self):
        """bcrypt rejects passwords longer than 72 bytes."""
        long_pw = "a" * 100
        with pytest.raises(ValueError, match="72 bytes"):
            _hash_password(long_pw)

    def test_max_length_password(self):
        """A 72-byte password (the bcrypt maximum) should hash and verify."""
        max_pw = "a" * 72
        hashed = _hash_password(max_pw)
        assert verify_password(max_pw, hashed) is True
        assert verify_password("a" * 71, hashed) is False

    def test_different_hashes_for_same_password(self):
        """Two hashes of the same password should differ (different salts)."""
        hash1 = _hash_password(TEST_PASSWORD)
        hash2 = _hash_password(TEST_PASSWORD)
        assert hash1 != hash2
        # Both should still verify
        assert verify_password(TEST_PASSWORD, hash1) is True
        assert verify_password(TEST_PASSWORD, hash2) is True

    def test_invalid_hash_raises(self):
        """Passing a non-bcrypt string as hash should raise ValueError."""
        with pytest.raises((ValueError, Exception)):
            verify_password(TEST_PASSWORD, "not-a-bcrypt-hash")


# ===========================================================================
# Token creation
# ===========================================================================


class TestCreateAccessToken:
    """Tests for create_access_token."""

    def test_returns_string(self):
        """Token should be a non-empty string."""
        token = create_access_token(str(TEST_USER_ID))
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_contains_sub_claim(self):
        """Decoded token should have a 'sub' matching the supplied user_id."""
        user_id = str(TEST_USER_ID)
        token = create_access_token(user_id)
        payload = jwt.decode(token, TEST_SECRET, algorithms=[TEST_ALGORITHM])
        assert payload["sub"] == user_id

    def test_token_contains_exp_claim(self):
        """Token should contain an expiration timestamp."""
        token = create_access_token(str(TEST_USER_ID))
        payload = jwt.decode(token, TEST_SECRET, algorithms=[TEST_ALGORITHM])
        assert "exp" in payload

    def test_token_contains_iat_claim(self):
        """Token should contain an issued-at timestamp."""
        token = create_access_token(str(TEST_USER_ID))
        payload = jwt.decode(token, TEST_SECRET, algorithms=[TEST_ALGORITHM])
        assert "iat" in payload

    def test_default_expiry_uses_module_setting(self):
        """Without expires_delta the module default (TEST_EXPIRE_MINUTES) is used."""
        before = datetime.now(UTC)
        token = create_access_token(str(TEST_USER_ID))
        after = datetime.now(UTC)

        payload = jwt.decode(token, TEST_SECRET, algorithms=[TEST_ALGORITHM])
        exp = datetime.fromtimestamp(payload["exp"], tz=UTC)

        # Expiry should be roughly TEST_EXPIRE_MINUTES from now
        expected_min = before + timedelta(minutes=TEST_EXPIRE_MINUTES) - timedelta(seconds=5)
        expected_max = after + timedelta(minutes=TEST_EXPIRE_MINUTES) + timedelta(seconds=5)
        assert expected_min <= exp <= expected_max

    def test_custom_expiry_delta(self):
        """A custom expires_delta should override the default."""
        delta = timedelta(hours=2)
        before = datetime.now(UTC)
        token = create_access_token(str(TEST_USER_ID), expires_delta=delta)
        after = datetime.now(UTC)

        payload = jwt.decode(token, TEST_SECRET, algorithms=[TEST_ALGORITHM])
        exp = datetime.fromtimestamp(payload["exp"], tz=UTC)

        expected_min = before + delta - timedelta(seconds=5)
        expected_max = after + delta + timedelta(seconds=5)
        assert expected_min <= exp <= expected_max

    def test_very_short_expiry(self):
        """A token with a 1-second expiry should be decodable immediately."""
        token = create_access_token(
            str(TEST_USER_ID),
            expires_delta=timedelta(seconds=1),
        )
        payload = jwt.decode(token, TEST_SECRET, algorithms=[TEST_ALGORITHM])
        assert payload["sub"] == str(TEST_USER_ID)

    def test_token_signed_with_configured_secret(self):
        """Token should fail to decode with a different secret."""
        token = create_access_token(str(TEST_USER_ID))
        with pytest.raises(Exception):
            jwt.decode(token, "wrong-secret", algorithms=[TEST_ALGORITHM])

    def test_token_uses_configured_algorithm(self):
        """Token header should declare the configured algorithm."""
        token = create_access_token(str(TEST_USER_ID))
        header = jwt.get_unverified_header(token)
        assert header["alg"] == TEST_ALGORITHM

    def test_different_user_ids_produce_different_tokens(self):
        """Tokens for different users should differ."""
        t1 = create_access_token(str(uuid4()))
        t2 = create_access_token(str(uuid4()))
        assert t1 != t2

    def test_zero_expiry_delta(self):
        """A zero timedelta should produce a token that expires immediately."""
        token = create_access_token(
            str(TEST_USER_ID),
            expires_delta=timedelta(seconds=0),
        )
        # The token was created at ~now with exp ~now.
        # Depending on timing it may or may not be expired yet,
        # but we can at least decode without verification to check the claim.
        payload = jwt.decode(
            token, TEST_SECRET, algorithms=[TEST_ALGORITHM],
            options={"verify_exp": False},
        )
        assert payload["sub"] == str(TEST_USER_ID)


# ===========================================================================
# Token decode edge cases
# ===========================================================================


class TestTokenDecodeEdgeCases:
    """Edge cases around JWT decoding (outside the FastAPI dependency)."""

    def test_expired_token_rejected(self):
        """A token whose exp is in the past should fail jose decode."""
        token = create_access_token(
            str(TEST_USER_ID),
            expires_delta=timedelta(seconds=-1),
        )
        with pytest.raises(Exception):
            jwt.decode(token, TEST_SECRET, algorithms=[TEST_ALGORITHM])

    def test_tampered_payload_rejected(self):
        """Altering the payload portion of the JWT should fail verification."""
        token = create_access_token(str(TEST_USER_ID))
        parts = token.split(".")
        assert len(parts) == 3
        # Flip a character in the payload
        mangled = list(parts[1])
        mangled[0] = "A" if mangled[0] != "A" else "B"
        parts[1] = "".join(mangled)
        bad_token = ".".join(parts)
        with pytest.raises(Exception):
            jwt.decode(bad_token, TEST_SECRET, algorithms=[TEST_ALGORITHM])

    def test_none_algorithm_rejected(self):
        """Tokens signed with 'none' should not verify with HS256."""
        payload = {"sub": str(TEST_USER_ID), "exp": datetime.now(UTC) + timedelta(hours=1)}
        unsigned = jwt.encode(payload, "", algorithm="HS256")
        # Attempt to forge by removing signature
        parts = unsigned.split(".")
        forged = parts[0] + "." + parts[1] + "."
        with pytest.raises(Exception):
            jwt.decode(forged, TEST_SECRET, algorithms=[TEST_ALGORITHM])

    def test_completely_garbage_token(self):
        """A completely invalid string should raise on decode."""
        with pytest.raises(Exception):
            jwt.decode("not.a.jwt", TEST_SECRET, algorithms=[TEST_ALGORITHM])

    def test_empty_string_token(self):
        """An empty string should raise on decode."""
        with pytest.raises(Exception):
            jwt.decode("", TEST_SECRET, algorithms=[TEST_ALGORITHM])

    def test_missing_sub_claim(self):
        """A token without 'sub' should decode but have no sub."""
        payload = {"exp": datetime.now(UTC) + timedelta(hours=1), "foo": "bar"}
        token = jwt.encode(payload, TEST_SECRET, algorithm=TEST_ALGORITHM)
        decoded = jwt.decode(token, TEST_SECRET, algorithms=[TEST_ALGORITHM])
        assert decoded.get("sub") is None


# ===========================================================================
# _resolve_user (internal helper)
# ===========================================================================


class TestResolveUser:
    """Tests for the internal _resolve_user coroutine."""

    async def test_none_token_returns_none(self):
        """Passing None token should immediately return None."""
        result = await _resolve_user(None)
        assert result is None

    async def test_storage_not_configured_raises_503(self):
        """If _storage is None and a real token is given, raise 503."""
        configure_auth(secret_key=TEST_SECRET, storage=None)
        token = create_access_token(str(TEST_USER_ID))
        with pytest.raises(HTTPException) as exc_info:
            await _resolve_user(token)
        assert exc_info.value.status_code == 503

    async def test_invalid_token_returns_none(self, mock_storage):
        """An unparseable token should return None (JWTError caught)."""
        configure_auth(secret_key=TEST_SECRET, storage=mock_storage)
        result = await _resolve_user("garbage-token")
        assert result is None
        mock_storage.get_user.assert_not_called()

    async def test_expired_token_returns_none(self, mock_storage):
        """An expired token should return None."""
        configure_auth(secret_key=TEST_SECRET, storage=mock_storage)
        token = create_access_token(
            str(TEST_USER_ID), expires_delta=timedelta(seconds=-1)
        )
        result = await _resolve_user(token)
        assert result is None

    async def test_token_missing_sub_returns_none(self, mock_storage):
        """A token with no 'sub' claim should return None."""
        configure_auth(secret_key=TEST_SECRET, storage=mock_storage)
        payload = {"exp": datetime.now(UTC) + timedelta(hours=1)}
        token = jwt.encode(payload, TEST_SECRET, algorithm=TEST_ALGORITHM)
        result = await _resolve_user(token)
        assert result is None
        mock_storage.get_user.assert_not_called()

    async def test_user_not_found_returns_none(self, mock_storage):
        """If storage returns None for the user_id, result is None."""
        configure_auth(secret_key=TEST_SECRET, storage=mock_storage)
        mock_storage.get_user.return_value = None

        token = create_access_token(str(TEST_USER_ID))
        result = await _resolve_user(token)
        assert result is None
        mock_storage.get_user.assert_awaited_once_with(TEST_USER_ID)

    async def test_inactive_user_returns_none(self, mock_storage, inactive_user):
        """An inactive user should be treated as non-existent."""
        configure_auth(secret_key=TEST_SECRET, storage=mock_storage)
        mock_storage.get_user.return_value = inactive_user

        token = create_access_token(str(inactive_user.id))
        result = await _resolve_user(token)
        assert result is None

    async def test_valid_token_active_user_returns_user(self, mock_storage, active_user):
        """A valid token for an active user should return the User."""
        configure_auth(secret_key=TEST_SECRET, storage=mock_storage)
        mock_storage.get_user.return_value = active_user

        token = create_access_token(str(active_user.id))
        result = await _resolve_user(token)
        assert result is not None
        assert result.id == active_user.id
        assert result.email == active_user.email

    async def test_wrong_secret_returns_none(self, mock_storage):
        """A token signed with a different secret should return None."""
        configure_auth(secret_key="different-secret", storage=mock_storage)
        # Token was created with TEST_SECRET via the autouse fixture,
        # but the module is now configured with a different secret.
        token = jwt.encode(
            {"sub": str(TEST_USER_ID), "exp": datetime.now(UTC) + timedelta(hours=1)},
            TEST_SECRET,
            algorithm=TEST_ALGORITHM,
        )
        result = await _resolve_user(token)
        assert result is None


# ===========================================================================
# get_current_user (FastAPI dependency)
# ===========================================================================


class TestGetCurrentUser:
    """Tests for the get_current_user FastAPI dependency."""

    async def test_valid_token_returns_user(self, mock_storage, active_user):
        """A valid token should yield the corresponding User."""
        configure_auth(secret_key=TEST_SECRET, storage=mock_storage)
        mock_storage.get_user.return_value = active_user

        token = create_access_token(str(active_user.id))
        user = await get_current_user(token=token)
        assert user.id == active_user.id

    async def test_invalid_token_raises_401(self, mock_storage):
        """An invalid token should raise HTTP 401."""
        configure_auth(secret_key=TEST_SECRET, storage=mock_storage)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token="bad-token")
        assert exc_info.value.status_code == 401
        assert "Invalid or expired token" in exc_info.value.detail

    async def test_401_includes_www_authenticate_header(self, mock_storage):
        """The 401 response should include WWW-Authenticate: Bearer."""
        configure_auth(secret_key=TEST_SECRET, storage=mock_storage)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token="bad-token")
        assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}

    async def test_expired_token_raises_401(self, mock_storage):
        """An expired token should raise HTTP 401."""
        configure_auth(secret_key=TEST_SECRET, storage=mock_storage)
        token = create_access_token(
            str(TEST_USER_ID), expires_delta=timedelta(seconds=-1)
        )
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token=token)
        assert exc_info.value.status_code == 401

    async def test_user_not_found_raises_401(self, mock_storage):
        """If the user_id in the token has no matching record, raise 401."""
        configure_auth(secret_key=TEST_SECRET, storage=mock_storage)
        mock_storage.get_user.return_value = None

        token = create_access_token(str(TEST_USER_ID))
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token=token)
        assert exc_info.value.status_code == 401

    async def test_inactive_user_raises_401(self, mock_storage, inactive_user):
        """An inactive user's token should raise 401."""
        configure_auth(secret_key=TEST_SECRET, storage=mock_storage)
        mock_storage.get_user.return_value = inactive_user

        token = create_access_token(str(inactive_user.id))
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token=token)
        assert exc_info.value.status_code == 401

    async def test_storage_unavailable_raises_503(self):
        """If storage is not configured, raise 503."""
        configure_auth(secret_key=TEST_SECRET, storage=None)
        token = create_access_token(str(TEST_USER_ID))
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token=token)
        assert exc_info.value.status_code == 503


# ===========================================================================
# get_current_user_optional (FastAPI dependency)
# ===========================================================================


class TestGetCurrentUserOptional:
    """Tests for the get_current_user_optional FastAPI dependency."""

    async def test_valid_token_returns_user(self, mock_storage, active_user):
        """A valid token should yield the corresponding User."""
        configure_auth(secret_key=TEST_SECRET, storage=mock_storage)
        mock_storage.get_user.return_value = active_user

        token = create_access_token(str(active_user.id))
        user = await get_current_user_optional(token=token)
        assert user is not None
        assert user.id == active_user.id

    async def test_none_token_returns_none(self, mock_storage):
        """None token should return None (no error)."""
        configure_auth(secret_key=TEST_SECRET, storage=mock_storage)
        user = await get_current_user_optional(token=None)
        assert user is None

    async def test_invalid_token_returns_none(self, mock_storage):
        """An invalid token should return None, not raise."""
        configure_auth(secret_key=TEST_SECRET, storage=mock_storage)
        user = await get_current_user_optional(token="garbage")
        assert user is None

    async def test_expired_token_returns_none(self, mock_storage):
        """An expired token should return None."""
        configure_auth(secret_key=TEST_SECRET, storage=mock_storage)
        token = create_access_token(
            str(TEST_USER_ID), expires_delta=timedelta(seconds=-1)
        )
        user = await get_current_user_optional(token=token)
        assert user is None

    async def test_inactive_user_returns_none(self, mock_storage, inactive_user):
        """An inactive user should produce None."""
        configure_auth(secret_key=TEST_SECRET, storage=mock_storage)
        mock_storage.get_user.return_value = inactive_user

        token = create_access_token(str(inactive_user.id))
        user = await get_current_user_optional(token=token)
        assert user is None


# ===========================================================================
# configure_auth
# ===========================================================================


class TestConfigureAuth:
    """Tests for the configure_auth setup function."""

    def test_configure_changes_secret(self):
        """Tokens should use the newly configured secret."""
        new_secret = "brand-new-secret"
        configure_auth(secret_key=new_secret)
        token = create_access_token(str(TEST_USER_ID))
        payload = jwt.decode(token, new_secret, algorithms=[TEST_ALGORITHM])
        assert payload["sub"] == str(TEST_USER_ID)

    def test_configure_changes_algorithm(self):
        """Changing algorithm should be reflected in created tokens."""
        configure_auth(secret_key=TEST_SECRET, algorithm="HS384")
        token = create_access_token(str(TEST_USER_ID))
        header = jwt.get_unverified_header(token)
        assert header["alg"] == "HS384"
        # Verify it decodes with HS384
        payload = jwt.decode(token, TEST_SECRET, algorithms=["HS384"])
        assert payload["sub"] == str(TEST_USER_ID)

    def test_configure_changes_expiry(self):
        """The default expiry should follow the configured minutes."""
        configure_auth(secret_key=TEST_SECRET, token_expire_minutes=5)
        before = datetime.now(UTC)
        token = create_access_token(str(TEST_USER_ID))
        payload = jwt.decode(token, TEST_SECRET, algorithms=[TEST_ALGORITHM])
        exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
        # Should be ~5 minutes from now, not the default 30
        assert exp < before + timedelta(minutes=6)
        assert exp > before + timedelta(minutes=4)

    async def test_configure_sets_storage(self, mock_storage, active_user):
        """After configuring with storage, _resolve_user should use it."""
        mock_storage.get_user.return_value = active_user
        configure_auth(secret_key=TEST_SECRET, storage=mock_storage)

        token = create_access_token(str(active_user.id))
        user = await get_current_user(token=token)
        assert user.id == active_user.id
        mock_storage.get_user.assert_awaited_once()
