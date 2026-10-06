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
    # Required only when `signup_mode=invite`. Optional in the schema rather
    # than conditionally required so one model serves all three modes: a
    # deployment flipping to `invite` must not turn every existing client's
    # signup into a 422 at the validation layer, and `require_code` already
    # refuses a missing one with the same error an invalid one gets.
    invite_code: str | None = Field(default=None, max_length=128)


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
