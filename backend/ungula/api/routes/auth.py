"""
Authentication API routes.

Provides endpoints for user registration, login, and profile access.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from ...auth import create_access_token, get_current_user, verify_password
from ...storage.base import StorageBackend, User, UserCreate

logger = logging.getLogger(__name__)

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


# --- Request / Response Models ---


class RegisterRequest(BaseModel):
    """Request to register a new user."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str | None = Field(default=None, max_length=255)


class LoginRequest(BaseModel):
    """Request to log in."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """JWT token response."""

    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """Public user info."""

    id: str
    email: str
    name: str | None
    is_active: bool
    created_at: str


# --- Endpoints ---


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(request: Request, data: RegisterRequest) -> TokenResponse:
    """Register a new user and return a JWT token."""
    storage: StorageBackend = request.app.state.storage

    # Check if email already taken
    existing = await storage.get_user_by_email(data.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = await storage.create_user(
        UserCreate(email=data.email, password=data.password, name=data.name)
    )

    token = create_access_token(str(user.id))
    logger.info("User registered: %s", user.email)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, data: LoginRequest) -> TokenResponse:
    """Authenticate and return a JWT token."""
    storage: StorageBackend = request.app.state.storage

    user_in_db = await storage.get_user_by_email(data.email)
    if user_in_db is None or not verify_password(data.password, user_in_db.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user_in_db.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    token = create_access_token(str(user_in_db.id))
    logger.info("User logged in: %s", user_in_db.email)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Get the current authenticated user's profile."""
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        name=current_user.name,
        is_active=current_user.is_active,
        created_at=current_user.created_at.isoformat(),
    )
