"""Interactive Terminal Console for NEXA Executive Assistant.

Run this script to interact with NEXA directly from your terminal:
    python scripts/nexa_cli.py
"""

from __future__ import annotations

import asyncio
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select

from app.ai.orchestrator import NexaOrchestrator
from app.core.config import settings
from app.core.security import hash_password
from app.db.models import Conversation, User, UserStatus
from app.db.session import AsyncSessionLocal
from app.modules.action_plans.service import ActionPlanService


class CLIColors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    BOLD = "\033[1m"
    END = "\033[0m"


async def get_or_create_cli_user(db) -> User:
    email = "executive@nexa.ai"
    stmt = select(User).where(User.email == email)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user:
        user = User(
            email=email,
            hashed_password=hash_password("ExecutivePass123!"),
            full_name="Executive User",
            timezone=settings.DEFAULT_TIMEZONE,
            status=UserStatus.active,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


async def get_or_create_conversation(user_id, db) -> Conversation:
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.title == "CLI Session")
        .order_by(Conversation.updated_at.desc())
        .limit(1)
    )
    conv = (await db.execute(stmt)).scalar_one_or_none()
    if not conv:
        conv = Conversation(user_id=user_id, title="CLI Session")
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
    return conv


async def run_cli() -> None:
    print(f"\n{CLIColors.BOLD}{CLIColors.CYAN}====================================================={CLIColors.END}")
    print(f"{CLIColors.BOLD}{CLIColors.CYAN}       NEXA AI PERSONAL ASSISTANT - CLI CONSOLE       {CLIColors.END}")
    print(f"{CLIColors.BOLD}{CLIColors.CYAN}====================================================={CLIColors.END}")
    print("Type your instructions naturally, e.g.:")
    print(f"  {CLIColors.WARNING}'Tomorrow at 12:00 PM, I have a meeting with a client about our fintech project'{CLIColors.END}")
    print(f"Type {CLIColors.BOLD}'exit'{CLIColors.END} or {CLIColors.BOLD}'quit'{CLIColors.END} to leave.\n")

    try:
        async with AsyncSessionLocal() as db:
            user = await get_or_create_cli_user(db)
            conv = await get_or_create_conversation(user.id, db)
            orchestrator = NexaOrchestrator(db)
            plan_svc = ActionPlanService(db)

            print(f"{CLIColors.GREEN}Logged in as: {user.full_name} ({user.email}){CLIColors.END}")
            print(f"{CLIColors.GREEN}Timezone: {user.timezone}{CLIColors.END}\n")

            while True:
                try:
                    user_input = input(f"{CLIColors.BOLD}You > {CLIColors.END}").strip()
                except (EOFError, KeyboardInterrupt):
                    break

                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit", "q"):
                    print(f"\n{CLIColors.CYAN}Goodbye!{CLIColors.END}")
                    break

                # Handle quick approval if user types 'approve' or 'yes'
                if user_input.lower() in ("approve", "yes", "confirm") and conv.messages:
                    last_plan_stmt = select(Conversation).where(Conversation.id == conv.id)
                    await db.execute(last_plan_stmt)
                    # Check recent action plans
                    user_plans = await plan_svc.list_user_plans(user.id, limit=1)
                    if user_plans and user_plans[0].status.value == "pending_approval":
                        pending = user_plans[0]
                        print(f"\n{CLIColors.YELLOW}Approving Action Plan: {pending.title}...{CLIColors.END}")
                        await plan_svc.approve_plan(pending.id, user.id)
                        await db.commit()
                        print(f"{CLIColors.GREEN}✓ Plan approved! Background worker will execute the scheduled steps.{CLIColors.END}\n")
                        continue

                # Process message through AI Orchestrator
                print(f"{CLIColors.CYAN}NEXA is thinking...{CLIColors.END}")
                try:
                    response = await orchestrator.process_message(user, conv, user_input)
                    await db.commit()

                    print(f"\n{CLIColors.BOLD}{CLIColors.BLUE}NEXA > {CLIColors.END}")
                    print(f"{response.response_text}\n")

                    if response.action_plan_id:
                        print(f"{CLIColors.WARNING}>> Reply 'Approve' to approve and execute this plan immediately.{CLIColors.END}\n")

                except Exception as exc:
                    print(f"\n{CLIColors.FAIL}Error: {exc}{CLIColors.END}\n")

    except Exception as e:
        print(f"\n{CLIColors.FAIL}Failed to connect to database: {e}{CLIColors.END}")
        print("Please ensure PostgreSQL is running (e.g. via 'docker compose up -d postgres').\n")


if __name__ == "__main__":
    asyncio.run(run_cli())

