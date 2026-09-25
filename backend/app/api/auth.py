"""
AURA Authentication Endpoints
POST /auth/login, POST /auth/logout, GET /auth/me
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    get_current_user,
    verify_password,
)
from app.database import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, UserResponse

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """
    Authenticate with email and password.
    Returns a JWT access token valid for 24 hours.
    """
    # Fetch user by email
    result = await db.execute(
        select(User).where(User.email == credentials.email, User.is_active == True)
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": str(user.id), "role": user.role})

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=str(user.id),
        email=user.email,
        role=user.role,
    )


@router.post("/logout")
async def logout() -> dict:
    """
    Logout endpoint. Stateless JWT — the client must discard the token.
    """
    return {"message": "Logged out successfully. Please discard your token."}


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    """
    Return the currently authenticated user's profile.
    """
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        role=current_user.role,
        is_active=current_user.is_active,
    )
