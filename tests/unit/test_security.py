"""Unit tests for security utilities."""

from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import AuthenticationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    verify_password,
)


def test_password_hashing_and_verification():
    raw_pass = "MySecretPassw0rd!"
    hashed = hash_password(raw_pass)

    assert hashed != raw_pass
    assert hashed.startswith("$argon2")
    assert verify_password(raw_pass, hashed) is True
    assert verify_password("WrongPassw0rd!", hashed) is False


def test_jwt_access_token_creation_and_decoding():
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    payload = decode_access_token(token)

    assert payload["sub"] == str(user_id)
    assert payload["type"] == "access"
    assert "exp" in payload


def test_jwt_refresh_token_creation_and_decoding():
    user_id = uuid.uuid4()
    jti = "unique-jti-12345"
    token = create_refresh_token(user_id, jti)
    payload = decode_refresh_token(token)

    assert payload["sub"] == str(user_id)
    assert payload["type"] == "refresh"
    assert payload["jti"] == jti


def test_jwt_token_type_mismatch_raises_error():
    user_id = uuid.uuid4()
    # Create refresh token and try to decode as access token
    token = create_refresh_token(user_id, "jti-1")
    with pytest.raises(AuthenticationError):
        decode_access_token(token)


def test_fernet_secret_encryption_and_decryption():
    secret_text = "ya29.a0ARrdaM8-very-sensitive-oauth-refresh-token"
    encrypted = encrypt_secret(secret_text)

    assert encrypted != secret_text
    decrypted = decrypt_secret(encrypted)
    assert decrypted == secret_text


def test_decrypt_with_tampered_secret_raises_error():
    secret_text = "sample-secret"
    encrypted = encrypt_secret(secret_text)
    tampered = encrypted[:-4] + "AAAA"

    with pytest.raises(ValueError):
        decrypt_secret(tampered)
