"""Encrypt/decrypt sensitive tokens at rest using Fernet."""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _get_fernet() -> Fernet:
    key_material = settings.GOOGLE_TOKEN_ENCRYPTION_KEY or settings.JWT_SECRET
    digest = hashlib.sha256(key_material.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(digest)
    return Fernet(fernet_key)


def encrypt_token(plain_text: str) -> str:
    return _get_fernet().encrypt(plain_text.encode()).decode()


def decrypt_token(cipher_text: str) -> str:
    try:
        return _get_fernet().decrypt(cipher_text.encode()).decode()
    except InvalidToken:
        raise ValueError("Invalid encrypted token")
