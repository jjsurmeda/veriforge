from pydantic import BaseModel, EmailStr, Field


class PlanPublic(BaseModel):
    name: str
    credits_5h: int
    credits_month: int


class UserPublic(BaseModel):
    id: str
    email: EmailStr
    role: str
    plan: PlanPublic


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=1024)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    user: UserPublic


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=1024)
