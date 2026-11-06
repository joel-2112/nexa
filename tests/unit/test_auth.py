"""Tests for authentication and user management APIs."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_user_success(unauth_client: AsyncClient):
    payload = {
        "email": "newexecutive@nexa.ai",
        "password": "StrongPassword123!",
        "full_name": "Executive Officer",
        "timezone": "Africa/Addis_Ababa",
    }
    response = await unauth_client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newexecutive@nexa.ai"
    assert data["full_name"] == "Executive Officer"
    assert "id" in data


@pytest.mark.asyncio
async def test_register_duplicate_email_fails(unauth_client: AsyncClient, test_user):
    payload = {
        "email": test_user.email,
        "password": "StrongPassword123!",
        "full_name": "Duplicate Person",
    }
    response = await unauth_client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_success(unauth_client: AsyncClient, test_user):
    payload = {
        "email": test_user.email,
        "password": "SecurePassword123!",
    }
    response = await unauth_client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password_fails(unauth_client: AsyncClient, test_user):
    payload = {
        "email": test_user.email,
        "password": "IncorrectPassword999!",
    }
    response = await unauth_client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_rotation(unauth_client: AsyncClient, test_user):
    # 1. Login to obtain tokens
    login_res = await unauth_client.post(
        "/api/v1/auth/login",
        json={"email": test_user.email, "password": "SecurePassword123!"},
    )
    tokens = login_res.json()
    old_refresh = tokens["refresh_token"]

    # 2. Use refresh token to obtain a new pair
    refresh_res = await unauth_client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert refresh_res.status_code == 200
    new_tokens = refresh_res.json()
    assert "access_token" in new_tokens
    assert new_tokens["refresh_token"] != old_refresh

    # 3. Old refresh token should now be revoked (replay protection)
    reused_res = await unauth_client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert reused_res.status_code == 401


@pytest.mark.asyncio
async def test_get_me_profile(auth_client: AsyncClient, test_user):
    response = await auth_client.get("/api/v1/auth/me")
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == test_user.email
    assert data["full_name"] == test_user.full_name
