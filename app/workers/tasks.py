"""Celery background tasks with retry policies and database tracking."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.models import (
    ActionPlan,
    ActionPlanStatus,
    ActionStepStatus,
    JobStatus,
    NotificationChannel,
    NotificationDelivery,
    NotificationStatus,
    RefreshToken,
    ScheduledJob,
    User,
)
from app.db.session import AsyncSessionLocal
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name="app.workers.tasks.send_scheduled_reminder_task",
)
def send_scheduled_reminder_task(self, job_id_str: str) -> dict[str, str]:
    """Execute a scheduled reminder job and deliver notifications."""

    async def _run() -> dict[str, str]:
        job_id = uuid.UUID(job_id_str)
        async with AsyncSessionLocal() as db:
            stmt = select(ScheduledJob).where(ScheduledJob.id == job_id)
            res = await db.execute(stmt)
            job = res.scalar_one_or_none()

            if not job:
                return {"status": "not_found"}

            if job.status == JobStatus.completed:
                return {"status": "already_completed"}

            job.status = JobStatus.running
            await db.flush()

            # Fetch user
            user_stmt = select(User).where(User.id == job.user_id)
            user = (await db.execute(user_stmt)).scalar_one_or_none()

            data = job.job_data or {}
            title = data.get("title", "Meeting")
            channel_str = data.get("channel", "telegram")

            try:
                if channel_str == "telegram" and user and user.telegram_id:
                    from app.integrations.telegram.bot import TelegramBotService

                    bot = TelegramBotService()
                    if data.get("type") == "task":
                        await bot.send_task_reminder(
                            chat_id=user.telegram_id,
                            title=title,
                            due_date=job.scheduled_at.strftime("%b %d, %Y at %I:%M %p UTC"),
                            priority=data.get("priority", "medium"),
                        )
                        body_msg = f"Task reminder: {title}"
                    else:
                        await bot.send_meeting_reminder(
                            chat_id=user.telegram_id,
                            title=title,
                            start_time=job.scheduled_at.strftime("%b %d, %Y at %I:%M %p UTC"),
                        )
                        body_msg = f"Meeting reminder: {title}"

                    # Record delivery
                    delivery = NotificationDelivery(
                        user_id=user.id,
                        job_id=job.id,
                        channel=NotificationChannel.telegram,
                        status=NotificationStatus.sent,
                        body=body_msg,
                        sent_at=datetime.now(UTC),
                    )
                    db.add(delivery)

                job.status = JobStatus.completed
                job.completed_at = datetime.now(UTC)
                await db.commit()
                return {"status": "completed"}
            except Exception as exc:
                job.retry_count += 1
                job.last_error = str(exc)
                await db.commit()
                logger.error("reminder_task_failed", job_id=job_id_str, error=str(exc))
                raise exc

    try:
        return asyncio.run(_run())
    except Exception as exc:
        raise self.retry(exc=exc)


async def execute_plan_async(plan_id_str: str, user_id_str: str) -> dict[str, str]:
    """Execute action steps for an approved ActionPlan directly in asyncio."""
    plan_id = uuid.UUID(plan_id_str)
    user_id = uuid.UUID(user_id_str)

    async with AsyncSessionLocal() as db:
        from sqlalchemy.orm import selectinload

        stmt = (
            select(ActionPlan)
            .where(ActionPlan.id == plan_id, ActionPlan.user_id == user_id)
            .options(selectinload(ActionPlan.steps))
        )
        res = await db.execute(stmt)
        plan = res.scalar_one_or_none()

        if not plan:
            return {"status": "plan_not_found"}

        if plan.status != ActionPlanStatus.approved:
            return {"status": f"invalid_state_{plan.status.value}"}

        plan.status = ActionPlanStatus.executing
        await db.flush()

        user_stmt = select(User).where(User.id == user_id)
        user = (await db.execute(user_stmt)).scalar_one_or_none()
        if not user:
            return {"status": "user_not_found"}

        from app.ai.tool_executor import ToolExecutor

        executor = ToolExecutor(db)

        all_succeeded = True
        error_details = None

        for step in sorted(plan.steps, key=lambda s: s.step_order):
            step.status = ActionStepStatus.running
            step.started_at = datetime.now(UTC)
            await db.flush()

            try:
                res = await executor.execute(
                    tool_name=step.tool_name,
                    arguments=step.arguments,
                    user=user,
                    plan_id=plan.id,
                    bypass_approval_check=True,  # Plan has been explicitly approved
                )
                step.status = ActionStepStatus.completed
                step.result = res
                step.completed_at = datetime.now(UTC)
                await db.flush()
            except Exception as exc:
                step.status = ActionStepStatus.failed
                step.error_message = str(exc)
                step.completed_at = datetime.now(UTC)
                all_succeeded = False
                error_details = str(exc)
                await db.flush()
                break

        if all_succeeded:
            plan.status = ActionPlanStatus.completed
            plan.completed_at = datetime.now(UTC)
        else:
            plan.status = ActionPlanStatus.failed
            plan.result_data = {"error": error_details}

        await db.commit()
        return {"status": plan.status.value}


@celery_app.task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    name="app.workers.tasks.execute_approved_plan",
)
def execute_approved_plan(self, plan_id_str: str, user_id_str: str) -> dict[str, str]:
    """Execute action steps for an approved ActionPlan via Celery."""
    try:
        return asyncio.run(execute_plan_async(plan_id_str, user_id_str))
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(name="app.workers.tasks.cleanup_expired_tokens_task")
def cleanup_expired_tokens_task() -> dict[str, int]:
    """Periodic task to purge expired refresh tokens from database."""

    async def _run() -> dict[str, int]:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import delete

            stmt = delete(RefreshToken).where(RefreshToken.expires_at < datetime.now(UTC))
            result = await db.execute(stmt)
            await db.commit()
            deleted_count = result.rowcount or 0
            logger.info("cleaned_expired_refresh_tokens", count=deleted_count)
            return {"deleted": deleted_count}

    return asyncio.run(_run())
