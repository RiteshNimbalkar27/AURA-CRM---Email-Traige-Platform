"""
AURA Authentication Schemas
Pydantic models for auth request/response validation.
"""
from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    role: str


class UserResponse(BaseModel):
    id: str
    email: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}
