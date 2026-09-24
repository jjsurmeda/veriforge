from typing import Annotated

from email_validator import EmailNotValidError, validate_email
from pydantic import AfterValidator, BaseModel, Field


def _validate_email(value: str) -> str:
    try:
        return validate_email(
            value,
            test_environment=True,
            check_deliverability=False,
        ).normalized
    except EmailNotValidError as exc:
        raise ValueError(str(exc)) from exc


Email = Annotated[str, AfterValidator(_validate_email)]


class PlanPublic(BaseModel):
    name: str
    credits_5h: int
    credits_month: int


class UserPublic(BaseModel):
    id: str
    email: Email
    role: str
    plan: PlanPublic


class SignupRequest(BaseModel):
    email: Email
    password: str = Field(min_length=8, max_length=1024)


class LoginRequest(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    user: UserPublic


class ForgotPasswordRequest(BaseModel):
    email: Email


class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=1024)
