"""Pytest configuration, fixtures, and database setup."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set test environment variables before importing app
os.environ["APP_ENV"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key-at-least-64-characters-long-for-testing-purposes-12345"
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-at-least-64-characters-long-for-testing-purposes-12345"
os.environ["ENCRYPTION_KEY"] = "8Z1j-gU5yP6r4oW3xV7zL8mK1nP4qR9tY2uA5cE7wQ8="
os.environ["GOOGLE_CLIENT_ID"] = ""
os.environ["GOOGLE_CLIENT_SECRET"] = ""
os.environ["N8N_API_KEY"] = ""
os.environ["TELEGRAM_BOT_TOKEN"] = ""  # Valid 32-byte Fernet key

from app.core.dependencies import get_current_user_id
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.models import User, UserStatus
from app.db.session import get_db
from app.main import app

# In-memory SQLite async engine for lightning fast and isolated testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
)

TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@pytest_asyncio.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def setup_test_db() -> AsyncGenerator[None, None]:
    """Create fresh database schema before each test."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestingSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Creates a standard test user."""
    user = User(
        email="testuser@example.com",
        hashed_password=hash_password("SecurePassword123!"),
        full_name="Test Executive",
        timezone="Africa/Addis_Ababa",
        status=UserStatus.active,
        telegram_id=123456789,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def other_user(db_session: AsyncSession) -> User:
    """Creates a second test user to test data isolation."""
    user = User(
        email="otheruser@example.com",
        hashed_password=hash_password("AnotherPassword456!"),
        full_name="Other User",
        timezone="UTC",
        status=UserStatus.active,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def user_token(test_user: User) -> str:
    return create_access_token(test_user.id)


@pytest_asyncio.fixture
async def auth_client(test_user: User, db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """FastAPI Test Client authenticated with test_user."""

    async def override_get_db():
        yield db_session

    async def override_get_current_user_id():
        return test_user.id

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user_id] = override_get_current_user_id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = create_access_token(test_user.id)
        client.headers.update({"Authorization": f"Bearer {token}"})
        yield client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def unauth_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """FastAPI Test Client without authentication."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
