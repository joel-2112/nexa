"""Telegram bot service and update processor with interactive action approval."""

from __future__ import annotations

import html
import re
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import IntegrationError, IntegrationNotConfiguredError
from app.core.logging import get_logger
from app.db.models import Conversation, User

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

        # Route message into the AI conversation engine
        await self._process_user_message(user, text, chat_id, db)

    async def _handle_callback_query(self, callback_query: dict[str, Any], db: AsyncSession) -> None:
        query_id = callback_query.get("id")
        data = callback_query.get("data", "")
        from_user = callback_query.get("from", {})
        telegram_user_id = from_user.get("id")
        message = callback_query.get("message", {})
        chat_id = message.get("chat", {}).get("id")

        user = await self._get_linked_user(telegram_user_id, db)
        if not user or not chat_id or not query_id:
            return

        from app.modules.action_plans.service import ActionPlanService

        svc = ActionPlanService(db)

        if data.startswith("approve:"):
            plan_id_str = data.split("approve:", 1)[1]
            try:
                plan_id = UUID(plan_id_str)
                await svc.approve_plan(plan_id, user.id)
                await self.answer_callback_query(query_id, text="Action plan approved and queued for execution!")
                await self.send_message(
                    chat_id,
                    "✅ <b>Action Plan Approved!</b>\n\n"
                    "NEXA is now executing your scheduled steps in the background. "
                    "You will be notified once execution completes.",
                )
            except Exception as e:
                logger.error("telegram_plan_approval_failed", error=str(e))
                await self.answer_callback_query(query_id, text=f"Error: {e}", show_alert=True)

        elif data.startswith("reject:"):
            plan_id_str = data.split("reject:", 1)[1]
            try:
                plan_id = UUID(plan_id_str)
                await svc.reject_plan(plan_id, user.id, reason="Rejected via Telegram")
                await self.answer_callback_query(query_id, text="Action plan cancelled.")
                await self.send_message(chat_id, "❌ <b>Action Plan Rejected.</b> No external actions were taken.")
            except Exception as e:
                await self.answer_callback_query(query_id, text=f"Error: {e}", show_alert=True)

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
            f"Welcome back, <b>{user.full_name}</b>. You can now chat with NEXA directly right here.",
        )

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

            await self.send_message(chat_id, reply.response_text, reply_markup=reply_markup)
        except Exception as exc:
            logger.error("telegram_orchestrator_error", error=str(exc))
            await self.send_message(
                chat_id,
                "Sorry, I encountered an error processing your request. Please try again in a moment.",
            )
