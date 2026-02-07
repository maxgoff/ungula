"""
JWT Authentication for Ungula.

Provides password verification, token creation, and FastAPI dependencies
for protecting endpoints.
"""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from .storage.base import StorageBackend, User, UserInDB

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=True)
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# Defaults -- overridden at startup from config
_secret_key: str = ""
_algorithm: str = "HS256"
_token_expire_minutes: int = 1440  # 24 hours
_storage: StorageBackend | None = None


def configure_auth(
    secret_key: str,
    algorithm: str = "HS256",
    token_expire_minutes: int = 1440,
    storage: StorageBackend | None = None,
) -> None:
    """Configure the auth module at startup. Called from main.py lifespan."""
    global _secret_key, _algorithm, _token_expire_minutes, _storage
    _secret_key = secret_key
    _algorithm = algorithm
    _token_expire_minutes = token_expire_minutes
    _storage = storage


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def create_access_token(
    user_id: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token."""
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=_token_expire_minutes))
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, _secret_key, algorithm=_algorithm)


async def _resolve_user(token: str | None) -> User | None:
    """Decode a JWT token and return the user, or None."""
    if token is None:
        return None

    if _storage is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth not configured",
        )

    try:
        payload = jwt.decode(token, _secret_key, algorithms=[_algorithm])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            return None
    except JWTError:
        return None

    user = await _storage.get_user(UUID(user_id))
    if user is None or not user.is_active:
        return None
    return user


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """FastAPI dependency -- requires valid JWT. Returns the authenticated user."""
    user = await _resolve_user(token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_user_optional(
    token: str | None = Depends(oauth2_scheme_optional),
) -> User | None:
    """FastAPI dependency -- returns User if token valid, None otherwise."""
    return await _resolve_user(token)
