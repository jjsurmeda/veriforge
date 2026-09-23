from cryptography.fernet import Fernet, InvalidToken

from config import get_settings
from errors import AppError


def _cipher() -> Fernet:
    key = get_settings().provider_encryption_key
    if not key:
        raise AppError(
            "provider_encryption_not_configured",
            "PROVIDER_ENCRYPTION_KEY is not configured",
            status_code=503,
        )
    try:
        return Fernet(key.encode())
    except (TypeError, ValueError) as exc:
        raise AppError("provider_encryption_invalid", "PROVIDER_ENCRYPTION_KEY is invalid") from exc


def encrypt_provider_key(value: str) -> str:
    return _cipher().encrypt(value.encode()).decode()


def decrypt_provider_key(value: str) -> str:
    try:
        return _cipher().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise AppError("provider_key_invalid", "Stored provider key cannot be decrypted") from exc
