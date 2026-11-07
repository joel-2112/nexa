"""Telegram bot service and update processor with interactive action approval."""

from __future__ import annotations

import asyncio
import html
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import IntegrationError, IntegrationNotConfiguredError
from app.core.logging import get_logger
from app.db.models import Conversation, Task, TaskStatus, User
from app.integrations.telegram.views import (
    get_remove_keyboard,
    get_unified_nav_keyboard,
    render_calendar_view,
    render_dashboard_view,
    render_help_view,
    render_integrations_view,
    render_plans_view,
    render_tasks_view,
)

logger = get_logger(__name__)


def format_to_telegram_html(text: str) -> str:
    """Convert Markdown elements into Telegram-supported HTML tags."""
    if not text:
        return ""

    # Check if text already contains valid Telegram HTML tags
    has_html_tags = bool(re.search(r"</?(?:b|i|u|s|code|pre|a|blockquote)>", text, re.IGNORECASE))
    s = text if has_html_tags else html.escape(text, quote=False)

    # 1. Code blocks: ```language\ncode``` -> <pre>code</pre>
    s = re.sub(r"```[a-zA-Z0-9_]*\n?(.*?)```", r"<pre>\1</pre>", s, flags=re.DOTALL)
    # 2. Inline code: `code` -> <code>code</code>
    s = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", s)
    # 3. Bold: **text** or __text__ -> <b>text</b>
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"__(.+?)__", r"<b>\1</b>", s)
    # 4. Italic: *text* or _text_ -> <i>text</i>
    s = re.sub(r"(?<!\w)\*([^*\n]+?)\*(?!\w)", r"<i>\1</i>", s)
    s = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"<i>\1</i>", s)
    # 5. Bullet list items: lines starting with "- " or "* " -> "• "
    s = re.sub(r"^\s*[-*]\s+", "• ", s, flags=re.MULTILINE)
    # 6. Markdown links: [text](url) -> <a href="url">text</a>
    s = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", r'<a href="\2">\1</a>', s)

    return s


class TelegramBotService:
    def __init__(self) -> None:
        self.bot_token = settings.TELEGRAM_BOT_TOKEN
        self.webhook_secret = settings.TELEGRAM_WEBHOOK_SECRET
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"

    def _ensure_configured(self) -> None:
        if not settings.telegram_configured:
            raise IntegrationNotConfiguredError("Telegram bot token is not configured.", provider="telegram")

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._ensure_configured()
        url = f"{self.base_url}/sendMessage"

        formatted_text = format_to_telegram_html(text) if parse_mode == "HTML" else text
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": formatted_text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": False,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                # If Telegram rejected the HTML entities, fallback to sending plain unformatted text
                if "parse entities" in resp.text.lower() or "bad request" in resp.text.lower():
                    logger.warning("telegram_html_parse_failed_falling_back_plain", error=resp.text)
                    payload["text"] = text
                    del payload["parse_mode"]
                    retry_resp = await client.post(url, json=payload)
                    if retry_resp.status_code == 200:
                        return retry_resp.json()

                logger.error("telegram_send_failed", status=resp.status_code, body=resp.text)
                raise IntegrationError(f"Telegram error: {resp.text}", provider="telegram")
            return resp.json()

    async def answer_callback_query(
        self, callback_query_id: str, text: str | None = None, show_alert: bool = False
    ) -> dict[str, Any]:
        self._ensure_configured()
        url = f"{self.base_url}/answerCallbackQuery"
        payload: dict[str, Any] = {"callback_query_id": callback_query_id, "show_alert": show_alert}
        if text:
            payload["text"] = text
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            return resp.json() if resp.status_code == 200 else {}

    async def edit_message_text(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._ensure_configured()
        url = f"{self.base_url}/editMessageText"

        formatted_text = format_to_telegram_html(text) if parse_mode == "HTML" else text
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": formatted_text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": False,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                if "parse entities" in resp.text.lower() or "bad request" in resp.text.lower():
                    payload["text"] = text
                    del payload["parse_mode"]
                    retry_resp = await client.post(url, json=payload)
                    if retry_resp.status_code == 200:
                        return retry_resp.json()
                logger.warning("telegram_edit_message_failed", error=resp.text)
            return resp.json() if resp.status_code == 200 else {}

    async def set_bot_commands(self) -> dict[str, Any]:
        """Register the official bot commands in Telegram's native menu."""
        if not settings.telegram_configured:
            return {}
        url = f"{self.base_url}/setMyCommands"
        commands = [
            {"command": "dashboard", "description": "📊 Executive Dashboard & Schedule"},
            {"command": "calendar", "description": "📅 7-Day Calendar & Meet links"},
            {"command": "tasks", "description": "📝 Interactive Task Manager"},
            {"command": "plans", "description": "📋 Review Action Plans & Approvals"},
            {"command": "integrations", "description": "🔗 Google Workspace & Service Status"},
            {"command": "reset", "description": "🔄 Clear Conversation & Reset Context"},
            {"command": "help", "description": "❓ Quick Guide, Tips & Commands"},
        ]
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={"commands": commands})
            return resp.json() if resp.status_code == 200 else {}

    async def send_meeting_reminder(
        self,
        chat_id: int | str,
        title: str,
        start_time: str,
        meet_link: str | None = None,
        duration_minutes: int | None = None,
    ) -> None:
        lines = [
            "🔔 <b>Upcoming Meeting in 10 Minutes</b>",
            f"📌 <b>Title:</b> {title}",
            f"⏰ <b>Start Time:</b> {start_time}",
        ]
        if duration_minutes:
            lines.append(f"⏱️ <b>Duration:</b> {duration_minutes} minutes")
        if meet_link:
            lines.append(f"🔗 <b>Google Meet:</b> {meet_link}")
        lines.append("\n<i>Good luck with your meeting!</i>")
        await self.send_message(chat_id, "\n".join(lines))

    async def send_task_reminder(
        self,
        chat_id: int | str,
        title: str,
        due_date: str | None = None,
        priority: str = "medium",
    ) -> None:
        priority_emoji = {"urgent": "🚨", "high": "⚠️", "medium": "📝", "low": "☕"}.get(priority.lower(), "📝")
        lines = [
            f"{priority_emoji} <b>Task Reminder</b>",
            f"📌 <b>Task:</b> {title}",
        ]
        if due_date:
            lines.append(f"⏰ <b>Due:</b> {due_date}")
        await self.send_message(chat_id, "\n".join(lines))

    async def handle_update(self, update: dict[str, Any], db: AsyncSession) -> None:
        """Process an incoming Telegram webhook update (messages & callback queries)."""
        # 1. Handle interactive inline keyboard callback queries
        callback_query = update.get("callback_query")
        if callback_query:
            await self._handle_callback_query(callback_query, db)
            return

        # 2. Handle normal user messages
        message = update.get("message")
        if not message:
            return

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        from_user = message.get("from", {})
        telegram_user_id = from_user.get("id")
        text = message.get("text", "").strip()

        if not chat_id or not telegram_user_id or not text:
            return

        # Handle Account Linking via /start <token>
        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            if len(parts) > 1:
                token = parts[1].strip()
                await self._process_account_linking(token, telegram_user_id, chat_id, db)
                return
            else:
                await self.send_message(
                    chat_id,
                    "👋 Welcome to <b>NEXA AI Assistant</b>!\n\n"
                    "To link your Telegram account, please get your link command from the NEXA Web App "
                    "(under Integrations) and send <code>/start &lt;token&gt;</code>.",
                )
                return

        # Verify linked account
        user = await self._get_linked_user(telegram_user_id, db)
        if not user:
            await self.send_message(
                chat_id,
                "⚠️ <b>Account not linked</b>.\n\n"
                "Please connect your Telegram account in the NEXA Settings or run <code>/start &lt;token&gt;</code>.",
            )
            return

        # Check for menu button clicks or slash commands
        clean_text = text.lower().strip()
        is_legacy_button = any(icon in text for icon in ["📊", "📅", "📝", "📋", "🔗", "❓"])

        async def _respond_with_view(render_fn: Any, title_msg: str) -> None:
            if asyncio.iscoroutinefunction(render_fn):
                content, markup = await render_fn(user, db)
            else:
                content, markup = render_fn(user)
            if is_legacy_button:
                # Clear the persistent reply keyboard immediately
                rm = await self.send_message(chat_id, f"<i>{title_msg}</i>", reply_markup=get_remove_keyboard())
                msg_id = rm.get("result", {}).get("message_id")
                if msg_id:
                    await self.edit_message_text(chat_id, msg_id, content, reply_markup=markup)
                    return
            await self.send_message(chat_id, content, reply_markup=markup)

        if clean_text in ["/dashboard", "/menu", "📊 dashboard", "dashboard"]:
            await _respond_with_view(render_dashboard_view, "📊 Loading Executive Dashboard...")
            return
        elif clean_text in ["/calendar", "📅 calendar", "calendar"]:
            await _respond_with_view(render_calendar_view, "📅 Loading 7-Day Schedule...")
            return
        elif clean_text in ["/tasks", "📝 tasks", "tasks"]:
            await _respond_with_view(render_tasks_view, "📝 Loading Task Manager...")
            return
        elif clean_text in ["/plans", "📋 plans", "plans"]:
            await _respond_with_view(render_plans_view, "📋 Loading Action Plans...")
            return
        elif clean_text in ["/integrations", "/status", "🔗 integrations", "integrations", "status"]:
            await _respond_with_view(render_integrations_view, "🔗 Loading Services & Integrations...")
            return
        elif clean_text in ["/help", "❓ help", "help"]:
            await _respond_with_view(render_help_view, "❓ Loading Quick Guide...")
            return
        elif clean_text in ["/reset", "reset", "clear", "cancel"]:
            # Clear any active multi-turn context
            stmt = select(Conversation).where(Conversation.user_id == user.id, Conversation.title == "Telegram Chat")
            conv = (await db.execute(stmt)).scalar_one_or_none()
            if conv:
                conv.current_intent = None
                conv.collected_data = {}
                conv.pending_questions = []
                await db.flush()
            await self.send_message(
                chat_id,
                "🔄 <b>Conversation Context Cleared.</b>\n\n"
                "I am ready for your next instruction. What would you like to schedule or accomplish?",
                reply_markup=get_remove_keyboard(),
            )
            return
        elif clean_text in ["approve", "approved", "yes", "confirm", "approve plan"]:
            from app.db.models import ActionPlan, ActionPlanStatus
            from app.modules.action_plans.service import ActionPlanService

            plan_stmt = (
                select(ActionPlan)
                .where(ActionPlan.user_id == user.id, ActionPlan.status == ActionPlanStatus.pending_approval)
                .order_by(ActionPlan.created_at.desc())
                .limit(1)
            )
            latest_plan = (await db.execute(plan_stmt)).scalar_one_or_none()
            if latest_plan:
                svc = ActionPlanService(db)
                await svc.approve_plan(latest_plan.id, user.id)
                dash_markup = get_unified_nav_keyboard("dashboard", [
                    [
                        {"text": "📊 View Dashboard", "callback_data": "nav:dashboard"},
                        {"text": "📅 View Calendar", "callback_data": "nav:calendar"},
                    ]
                ])
                await self.send_message(
                    chat_id,
                    f"✅ <b>Action Plan '{latest_plan.title}' Approved!</b>\n\n"
                    "NEXA has executed your scheduled steps. Review your schedule or tasks below:",
                    reply_markup=dash_markup,
                )
                return
            else:
                await self.send_message(
                    chat_id,
                    "ℹ️ No action plans are currently awaiting your approval.",
                    reply_markup=get_remove_keyboard(),
                )
                return
        elif clean_text in ["reject", "no", "cancel plan", "reject plan"]:
            from app.db.models import ActionPlan, ActionPlanStatus
            from app.modules.action_plans.service import ActionPlanService

            plan_stmt = (
                select(ActionPlan)
                .where(ActionPlan.user_id == user.id, ActionPlan.status == ActionPlanStatus.pending_approval)
                .order_by(ActionPlan.created_at.desc())
                .limit(1)
            )
            latest_plan = (await db.execute(plan_stmt)).scalar_one_or_none()
            if latest_plan:
                svc = ActionPlanService(db)
                await svc.reject_plan(latest_plan.id, user.id, reason="Rejected via chat")
                dash_markup = get_unified_nav_keyboard("plans", [
                    [{"text": "📊 Return to Dashboard", "callback_data": "nav:dashboard"}]
                ])
                await self.send_message(
                    chat_id,
                    f"❌ <b>Action Plan '{latest_plan.title}' Cancelled.</b> No external changes were made.",
                    reply_markup=dash_markup,
                )
                return
        elif any(
            phrase in clean_text
            for phrase in [
                "mark task done", "complete task", "task done", "task completed",
                "mark task as done", "i finished the task", "task finished",
                "mark done", "mark as completed", "completed task", "i did the task",
            ]
        ):
            now = datetime.now(UTC)
            task_stmt = (
                select(Task)
                .where(
                    Task.owner_id == user.id,
                    Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]),
                )
                .order_by(Task.due_at.asc().nullslast(), Task.created_at.desc())
                .limit(1)
            )
            target_task = (await db.execute(task_stmt)).scalar_one_or_none()
            if target_task:
                target_task.status = TaskStatus.completed
                target_task.completed_at = now
                await db.flush()
                content, markup = await render_tasks_view(user, db)
                await self.send_message(
                    chat_id,
                    f"🎉 <b>Task Marked Completed!</b>\n\n"
                    f"✓ <s>{target_task.title}</s> has been moved to Completed Tasks.\n"
                    f"It will no longer appear on your active schedule.",
                    reply_markup=markup,
                )
                return
            else:
                await self.send_message(
                    chat_id,
                    "🎉 <b>All caught up!</b> You have no pending tasks to complete.",
                    reply_markup=get_remove_keyboard(),
                )
                return

        # Route message into the AI conversation engine
        await self._process_user_message(user, text, chat_id, db)

    async def _handle_callback_query(self, callback_query: dict[str, Any], db: AsyncSession) -> None:
        query_id = callback_query.get("id")
        data = callback_query.get("data", "")
        from_user = callback_query.get("from", {})
        telegram_user_id = from_user.get("id")
        message = callback_query.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")

        user = await self._get_linked_user(telegram_user_id, db)
        if not user or not chat_id or not query_id:
            return

        from app.modules.action_plans.service import ActionPlanService

        svc = ActionPlanService(db)

        if data.startswith("approve:"):
            plan_id_str = data.split("approve:", 1)[1]
            try:
                plan_id = UUID(plan_id_str)
                await self.answer_callback_query(query_id, text="🚀 Executing action plan...")
                if message_id:
                    await self.edit_message_text(
                        chat_id,
                        message_id,
                        "⚙️ <b>Executing Action Plan...</b>\n\n"
                        "NEXA is setting up your calendar event, generating Google Meet links, "
                        "and scheduling your tasks right now.",
                    )
                await svc.approve_plan(plan_id, user.id)
                success_text = (
                    "🎉 <b>Action Plan Executed Successfully!</b>\n\n"
                    "• Calendar event created with Google Meet link\n"
                    "• Reminder notifications queued\n"
                    "• Associated tasks recorded\n\n"
                    "Explore your updated schedule or dashboard below:"
                )
                dash_markup = get_unified_nav_keyboard("dashboard", [
                    [
                        {"text": "📊 View Dashboard", "callback_data": "nav:dashboard"},
                        {"text": "📅 View Calendar", "callback_data": "nav:calendar"},
                    ]
                ])
                if message_id:
                    await self.edit_message_text(chat_id, message_id, success_text, reply_markup=dash_markup)
                else:
                    await self.send_message(chat_id, success_text, reply_markup=dash_markup)
            except Exception as e:
                logger.error("telegram_plan_approval_failed", error=str(e))
                await self.answer_callback_query(query_id, text=f"Error: {e}", show_alert=True)

        elif data.startswith("reject:"):
            plan_id_str = data.split("reject:", 1)[1]
            try:
                plan_id = UUID(plan_id_str)
                await svc.reject_plan(plan_id, user.id, reason="Rejected via Telegram")
                await self.answer_callback_query(query_id, text="Plan rejected.")
                reject_text = "❌ <b>Action Plan Cancelled.</b>\n\nNo external changes were made."
                dash_markup = get_unified_nav_keyboard("plans", [
                    [{"text": "📊 Return to Dashboard", "callback_data": "nav:dashboard"}]
                ])
                if message_id:
                    await self.edit_message_text(chat_id, message_id, reject_text, reply_markup=dash_markup)
                else:
                    await self.send_message(chat_id, reject_text, reply_markup=dash_markup)
            except Exception as e:
                await self.answer_callback_query(query_id, text=f"Error: {e}", show_alert=True)

        elif data.startswith("done_task:"):
            task_id_str = data.split("done_task:", 1)[1]
            try:
                task_id = UUID(task_id_str)
                stmt = select(Task).where(Task.id == task_id, Task.owner_id == user.id)
                task = (await db.execute(stmt)).scalar_one_or_none()
                if task:
                    task.status = TaskStatus.completed
                    task.completed_at = datetime.now(UTC)
                    await db.flush()
                    await self.answer_callback_query(query_id, text=f"'{task.title[:20]}' completed! 🎉")
                else:
                    await self.answer_callback_query(query_id, text="Task not found.", show_alert=True)

                # Re-render tasks view in place
                content, markup = await render_tasks_view(user, db)
                if message_id:
                    await self.edit_message_text(chat_id, message_id, content, reply_markup=markup)
                else:
                    await self.send_message(chat_id, content, reply_markup=markup)
            except Exception as e:
                logger.error("telegram_task_completion_failed", error=str(e))
                await self.answer_callback_query(query_id, text=f"Error: {e}", show_alert=True)

        elif data.startswith("nav:"):
            view_name = data.split("nav:", 1)[1]
            content: str = ""
            markup: dict[str, Any] | None = None

            if view_name == "dashboard":
                await self.answer_callback_query(query_id)
                content, markup = await render_dashboard_view(user, db)
            elif view_name == "calendar":
                await self.answer_callback_query(query_id)
                content, markup = await render_calendar_view(user, db)
            elif view_name == "tasks":
                await self.answer_callback_query(query_id)
                content, markup = await render_tasks_view(user, db)
            elif view_name == "plans":
                await self.answer_callback_query(query_id)
                content, markup = await render_plans_view(user, db)
            elif view_name == "integrations":
                await self.answer_callback_query(query_id)
                content, markup = await render_integrations_view(user, db)
            elif view_name == "help":
                await self.answer_callback_query(query_id)
                content, markup = render_help_view(user)
            else:
                return

            if message_id:
                await self.edit_message_text(chat_id, message_id, content, reply_markup=markup)
            else:
                await self.send_message(chat_id, content, reply_markup=markup)

    async def _process_account_linking(
        self, token: str, telegram_user_id: int, chat_id: int, db: AsyncSession
    ) -> None:
        stmt = select(User).where(User.telegram_link_token == token)
        res = await db.execute(stmt)
        user = res.scalar_one_or_none()

        if not user:
            await self.send_message(
                chat_id,
                "❌ <b>Invalid or expired link token.</b> Please generate a new one from the NEXA dashboard.",
            )
            return

        user.telegram_id = telegram_user_id
        user.telegram_link_token = None  # Invalidate token immediately after use
        await db.flush()

        await self.send_message(
            chat_id,
            f"✅ <b>Successfully connected!</b>\n\n"
            f"Welcome, <b>{user.full_name}</b>. I am NEXA, your AI personal executive assistant.\n\n"
            f"Speak to me naturally anytime or navigate using the interactive tabs below.",
            reply_markup=get_remove_keyboard(),
        )

        # Send dashboard
        dash_content, dash_markup = await render_dashboard_view(user, db)
        await self.send_message(chat_id, dash_content, reply_markup=dash_markup)

    async def _get_linked_user(self, telegram_user_id: int, db: AsyncSession) -> User | None:
        stmt = select(User).where(User.telegram_id == telegram_user_id)
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    async def _process_user_message(self, user: User, message_text: str, chat_id: int, db: AsyncSession) -> None:
        """Route message through Orchestrator."""
        try:
            # Find active telegram conversation or create one
            stmt = (
                select(Conversation)
                .where(Conversation.user_id == user.id, Conversation.title == "Telegram Chat")
                .order_by(Conversation.updated_at.desc())
                .limit(1)
            )
            res = await db.execute(stmt)
            conv = res.scalar_one_or_none()
            if not conv:
                conv = Conversation(user_id=user.id, title="Telegram Chat")
                db.add(conv)
                await db.flush()

            from app.ai.orchestrator import NexaOrchestrator

            orchestrator = NexaOrchestrator(db)
            reply = await orchestrator.process_message(
                user=user,
                conversation=conv,
                user_message=message_text,
            )

            # If the reply proposed an Action Plan, attach interactive Telegram Inline Buttons!
            reply_markup = None
            if reply.action_plan_id:
                reply_markup = {
                    "inline_keyboard": [
                        [
                            {
                                "text": "✅ Approve Plan",
                                "callback_data": f"approve:{reply.action_plan_id}",
                            },
                            {
                                "text": "❌ Reject Plan",
                                "callback_data": f"reject:{reply.action_plan_id}",
                            },
                        ]
                    ]
                }
            else:
                reply_markup = get_remove_keyboard()

            await self.send_message(chat_id, reply.response_text, reply_markup=reply_markup)
        except Exception as exc:
            logger.error("telegram_orchestrator_error", error=str(exc))
            await self.send_message(
                chat_id,
                "Sorry, I encountered an error processing your request. Please try again in a moment.",
                reply_markup=get_remove_keyboard(),
            )
