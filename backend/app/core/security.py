"""
AURA Security Utilities
JWT token creation/validation and bcrypt password hashing.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db

settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against its bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.access_token_expire_minutes
        )
    to_encode["exp"] = expire
    to_encode["iat"] = datetime.now(timezone.utc)
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT token. Returns payload or None if invalid."""
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        return payload
    except JWTError:
        return None


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> "User":  # type: ignore
    """FastAPI dependency: validates JWT and returns the current active user."""
    from app.models.user import User

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_token(token)
    if payload is None:
        raise credentials_exception

    user_id: str | None = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == uid, User.is_active == True))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception

    return user


async def get_current_supervisor(
    current_user: Annotated["User", Depends(get_current_user)],  # type: ignore
) -> "User":  # type: ignore
    """FastAPI dependency: requires Supervisor role."""
    if current_user.role != "supervisor":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Supervisor role required for this operation",
        )
    return current_user
