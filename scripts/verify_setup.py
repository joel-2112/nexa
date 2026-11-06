"""Environment and service readiness verification script.

Run this script to diagnose and verify your local setup before running the application:
    python scripts/verify_setup.py
"""

from __future__ import annotations

import asyncio
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    END = "\033[0m"


def check_mark(status: bool) -> str:
    return f"{Colors.GREEN}✓ READY{Colors.END}" if status else f"{Colors.RED}✗ MISSING{Colors.END}"


def warn_mark(status: bool) -> str:
    return f"{Colors.GREEN}✓ CONFIGURED{Colors.END}" if status else f"{Colors.YELLOW}○ NOT CONFIGURED (Optional){Colors.END}"


async def main() -> None:
    print(f"\n{Colors.BOLD}{Colors.BLUE}==============================================={Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}       NEXA BACKEND ENVIRONMENT DIAGNOSTICS    {Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}==============================================={Colors.END}\n")

    # 1. Check Python version
    py_ver = sys.version.split()[0]
    print(f"Python Version: {py_ver} ... {Colors.GREEN}✓ OK{Colors.END}")

    # 2. Check configuration loading
    try:
        from app.core.config import settings
    except Exception as e:
        print(f"{Colors.RED}ERROR loading app.core.config: {e}{Colors.END}")
        return

    print(f"App Name:       {settings.APP_NAME}")
    print(f"Environment:    {settings.APP_ENV}")
    print(f"Timezone:       {settings.DEFAULT_TIMEZONE}\n")

    # 3. Check Core Security Keys
    print(f"{Colors.BOLD}[1] Security & Cryptography Keys:{Colors.END}")
    has_secret = bool(settings.SECRET_KEY and len(settings.SECRET_KEY) >= 32)
    has_jwt = bool(settings.JWT_SECRET_KEY and len(settings.JWT_SECRET_KEY) >= 32)
    print(f"  - SECRET_KEY:       {check_mark(has_secret)}")
    print(f"  - JWT_SECRET_KEY:   {check_mark(has_jwt)}")

    # Fernet encryption key validation
    fernet_ok = False
    try:
        from cryptography.fernet import Fernet

        if settings.ENCRYPTION_KEY:
            Fernet(settings.ENCRYPTION_KEY.encode())
            fernet_ok = True
    except Exception:
        fernet_ok = False
    print(f"  - ENCRYPTION_KEY:   {check_mark(fernet_ok)}")

    # 4. Check Database Connection
    print(f"\n{Colors.BOLD}[2] PostgreSQL Database:{Colors.END}")
    db_ok = False
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(settings.DATABASE_URL, connect_args={"timeout": 3})
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
        print(f"  - Connection to {settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}: {check_mark(True)}")
        await engine.dispose()
    except Exception as e:
        print(f"  - Connection failed: {Colors.RED}{e}{Colors.END}")
        print(f"    {Colors.YELLOW}Hint: Start PostgreSQL via 'docker compose up -d postgres'{Colors.END}")

    # 5. Check Redis Broker
    print(f"\n{Colors.BOLD}[3] Redis & Celery Message Broker:{Colors.END}")
    redis_ok = False
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL, socket_timeout=3)
        await r.ping()
        redis_ok = True
        print(f"  - Connection to {settings.REDIS_HOST}:{settings.REDIS_PORT}: {check_mark(True)}")
        await r.close()
    except Exception as e:
        print(f"  - Connection failed: {Colors.RED}{e}{Colors.END}")
        print(f"    {Colors.YELLOW}Hint: Start Redis via 'docker compose up -d redis'{Colors.END}")

    # 6. Check Integrations
    print(f"\n{Colors.BOLD}[4] External Integrations:{Colors.END}")
    has_openai = bool(settings.OPENAI_API_KEY and settings.OPENAI_API_KEY.startswith("sk-"))
    print(f"  - OpenAI (GPT-4o):         {warn_mark(has_openai)}")
    print(f"  - Google Workspace:        {warn_mark(settings.google_configured)}")
    print(f"  - Telegram Bot API:        {warn_mark(settings.telegram_configured)}")
    print(f"  - n8n Automation Engine:   {warn_mark(settings.n8n_configured)}")

    # Summary
    print(f"\n{Colors.BOLD}==============================================={Colors.END}")
    if fernet_ok and has_secret and has_jwt:
        print(f"{Colors.GREEN}{Colors.BOLD}CORE CONFIGURATION IS READY!{Colors.END}")
        if not db_ok or not redis_ok:
            print(f"{Colors.YELLOW}Next step: Start local infrastructure with:{Colors.END}")
            print("  docker compose up -d postgres redis")
            print("  alembic upgrade head")
    else:
        print(f"{Colors.RED}{Colors.BOLD}ACTION REQUIRED: Complete the missing required keys in .env{Colors.END}")
    print(f"{Colors.BOLD}==============================================={Colors.END}\n")


if __name__ == "__main__":
    asyncio.run(main())

