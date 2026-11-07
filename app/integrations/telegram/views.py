"""Telegram interactive UI views and dashboard builders for NEXA."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    ActionPlan,
    ActionPlanStatus,
    CalendarEvent,
    CalendarEventStatus,
    ConnectedAccount,
    IntegrationProvider,
    Task,
    TaskPriority,
    TaskStatus,
    User,
)


def get_remove_keyboard() -> dict[str, Any]:
    """Dismiss and remove any persistent bottom sheet keyboard in Telegram."""
    return {"remove_keyboard": True}


def get_persistent_reply_keyboard() -> dict[str, Any]:
    """Deprecated: Alias to get_remove_keyboard to ensure no persistent keyboard remains."""
    return get_remove_keyboard()


def get_unified_nav_keyboard(
    active_tab: str = "dashboard",
    action_rows: list[list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Generate a clean, professional inline keyboard with active tab indicators and actions."""
    tabs = [
        ("dashboard", "📊 Dashboard"),
        ("calendar", "📅 Calendar"),
        ("tasks", "📝 Tasks"),
        ("plans", "📋 Plans"),
        ("integrations", "🔗 Services"),
        ("help", "❓ Guide"),
    ]

    tab_buttons: list[dict[str, Any]] = []
    for tab_id, label in tabs:
        if tab_id == active_tab:
            tab_buttons.append({"text": f"• {label} •", "callback_data": f"nav:{tab_id}"})
        else:
            tab_buttons.append({"text": label, "callback_data": f"nav:{tab_id}"})

    keyboard: list[list[dict[str, Any]]] = []

    # 1. View-specific action rows (e.g. Join Meet, Complete Task, Approve Plan, Refresh)
    if action_rows:
        keyboard.extend(action_rows)

    # 2. Main interactive navigation tabs
    keyboard.append([tab_buttons[0], tab_buttons[1], tab_buttons[2]])  # Dashboard, Calendar, Tasks
    keyboard.append([tab_buttons[3], tab_buttons[4], tab_buttons[5]])  # Plans, Services, Guide

    return {"inline_keyboard": keyboard}


def _format_dt(dt: datetime | None, user_tz: str | None = None) -> str:
    if not dt:
        return "Not set"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    tz_str = user_tz or "Africa/Addis_Ababa"
    try:
        from zoneinfo import ZoneInfo
        dt = dt.astimezone(ZoneInfo(tz_str))
    except Exception:
        pass
    return dt.strftime("%b %d, %Y at %I:%M %p %Z").strip().replace(" 0", " ")


def categorize_task(t: Task, now: datetime) -> str:
    """Classify task into professional lifecycle categories:
    - 'completed': Explicitly marked done
    - 'scheduled': due_at is in the future
    - 'active': due_at has arrived and is within active window (or no due date set)
    - 'expired': due_at was in the past and > 2 hours overdue without completion
    """
    if t.status == TaskStatus.completed:
        return "completed"
    if t.status == TaskStatus.cancelled:
        return "cancelled"

    if not t.due_at:
        return "active"

    due = t.due_at if t.due_at.tzinfo else t.due_at.replace(tzinfo=UTC)
    now_utc = now if now.tzinfo else now.replace(tzinfo=UTC)

    if due > now_utc:
        return "scheduled"
    elif now_utc - due <= timedelta(hours=2):
        return "active"
    else:
        return "expired"


async def render_dashboard_view(user: User, db: AsyncSession) -> tuple[str, dict[str, Any] | None]:
    """Render the primary executive dashboard for Telegram."""
    now = datetime.now(UTC)

    # 1. Auto-complete past calendar events whose end_at has passed
    past_event_stmt = (
        select(CalendarEvent)
        .where(
            CalendarEvent.owner_id == user.id,
            CalendarEvent.status == CalendarEventStatus.scheduled,
            CalendarEvent.end_at < now,
        )
    )
    past_events = (await db.execute(past_event_stmt)).scalars().all()
    for pe in past_events:
        pe.status = CalendarEventStatus.completed
    if past_events:
        await db.flush()

    # 2. Fetch upcoming or ongoing events (where end_at >= now)
    event_stmt = (
        select(CalendarEvent)
        .where(
            CalendarEvent.owner_id == user.id,
            CalendarEvent.status == CalendarEventStatus.scheduled,
            CalendarEvent.end_at >= now,
            CalendarEvent.start_at <= now + timedelta(days=2),
        )
        .order_by(CalendarEvent.start_at.asc())
        .limit(3)
    )
    events = (await db.execute(event_stmt)).scalars().all()

    # 3. Fetch all pending and in-progress tasks
    task_stmt = (
        select(Task)
        .where(
            Task.owner_id == user.id,
            Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]),
        )
        .order_by(Task.due_at.asc().nullslast(), Task.created_at.desc())
    )
    all_uncompleted_tasks = (await db.execute(task_stmt)).scalars().all()

    active_tasks: list[Task] = []
    scheduled_tasks: list[Task] = []
    expired_tasks: list[Task] = []

    for t in all_uncompleted_tasks:
        cat = categorize_task(t, now)
        if cat == "scheduled":
            scheduled_tasks.append(t)
        elif cat == "expired":
            expired_tasks.append(t)
        else:
            active_tasks.append(t)

    # 4. Count tasks completed today
    completed_today_stmt = select(func.count(Task.id)).where(
        Task.owner_id == user.id,
        Task.status == TaskStatus.completed,
        Task.completed_at >= now - timedelta(days=1),
    )
    completed_today_count = (await db.execute(completed_today_stmt)).scalar() or 0

    # 5. Fetch pending action plans
    plan_stmt = (
        select(ActionPlan)
        .where(
            ActionPlan.user_id == user.id,
            ActionPlan.status == ActionPlanStatus.pending_approval,
        )
        .order_by(ActionPlan.created_at.desc())
        .limit(2)
    )
    pending_plans = (await db.execute(plan_stmt)).scalars().all()

    # 6. Check connected Google account
    google_stmt = select(ConnectedAccount).where(
        ConnectedAccount.user_id == user.id,
        ConnectedAccount.provider == IntegrationProvider.google,
        ConnectedAccount.is_active == True,  # noqa: E712
    )
    google_acc = (await db.execute(google_stmt)).scalar_one_or_none()

    # Build Dashboard Text in User's Local Timezone
    tz_name = user.timezone or "Africa/Addis_Ababa"
    try:
        from zoneinfo import ZoneInfo
        now_local = now.astimezone(ZoneInfo(tz_name))
    except Exception:
        now_local = now

    lines = [
        "📊 <b>NEXA Executive Dashboard</b>",
        f"👤 <b>User:</b> {user.full_name} | 🌍 <code>{tz_name}</code>",
        f"⏰ <i>{now_local.strftime('%A, %b %d • %I:%M %p %Z').replace(' 0', ' ')}</i>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    # Calendar Section
    lines.append("\n📅 <b>Upcoming Schedule:</b>")
    if events:
        for ev in events:
            time_str = _format_dt(ev.start_at, tz_name)
            meet_badge = f" [🔗 <a href='{ev.meet_link}'>Join Meet</a>]" if ev.meet_link else ""
            if ev.start_at <= now <= ev.end_at:
                lines.append(f"• 🔴 <b>[Happening Now] {ev.title}</b>{meet_badge}\n  🕒 Ends: {_format_dt(ev.end_at, tz_name)}")
            else:
                lines.append(f"• <b>{ev.title}</b>{meet_badge}\n  🕒 {time_str}")
    else:
        lines.append("• <i>No meetings scheduled in the next 48h. Clear skies!</i>")

    # Tasks Section
    total_uncompleted = len(active_tasks) + len(scheduled_tasks) + len(expired_tasks)
    stats_str = f"{total_uncompleted} pending"
    if completed_today_count > 0:
        stats_str += f", {completed_today_count} completed today"
    lines.append(f"\n📝 <b>Tasks Overview ({stats_str}):</b>")

    if not total_uncompleted:
        lines.append("• <i>All tasks complete! Outstanding work.</i>")
    else:
        if active_tasks:
            for t in active_tasks[:3]:
                due_info = f" • <i>Due: {_format_dt(t.due_at, tz_name)}</i>" if t.due_at else ""
                lines.append(f"• ⚡ [Active] <b>{t.title}</b>{due_info}")
        if scheduled_tasks:
            for t in scheduled_tasks[:2]:
                lines.append(f"• ⏳ [Scheduled] <b>{t.title}</b> <i>(At {_format_dt(t.due_at, tz_name)})</i>")
        if expired_tasks:
            for t in expired_tasks[:2]:
                lines.append(f"• ⚠️ [Expired] <b>{t.title}</b> <i>(Was due {_format_dt(t.due_at, tz_name)})</i>")

    # Pending Plans Section
    if pending_plans:
        lines.append("\n⚠️ <b>Action Plans Awaiting Approval:</b>")
        for p in pending_plans:
            lines.append(f"📋 <b>{p.title}</b>\n   <i>Use the buttons below to approve or reject.</i>")

    # Integrations line
    lines.append("\n━━━━━━━━━━━━━━━━━━━━")
    g_status = f"✅ Connected ({google_acc.email})" if google_acc else "❌ Disconnected"
    lines.append(f"🔗 <b>Google:</b> {g_status} | <b>Telegram:</b> ✅ Active")

    # Build Interactive Action Buttons
    action_rows: list[list[dict[str, Any]]] = []

    # If there are pending plans, put approval buttons first
    for p in pending_plans:
        action_rows.append([
            {"text": f"✅ Approve: {p.title[:20]}", "callback_data": f"approve:{p.id}"},
            {"text": "❌ Reject", "callback_data": f"reject:{p.id}"},
        ])

    # If there are upcoming events with meet links, provide instant one-click join buttons
    meet_buttons: list[dict[str, Any]] = []
    for ev in events:
        if ev.meet_link:
            meet_buttons.append({"text": f"🔗 Join: {ev.title[:18]}", "url": ev.meet_link})
    if meet_buttons:
        for i in range(0, len(meet_buttons), 2):
            action_rows.append(meet_buttons[i : i + 2])

    action_rows.append([{"text": "🔄 Refresh Dashboard", "callback_data": "nav:dashboard"}])

    return "\n".join(lines), get_unified_nav_keyboard("dashboard", action_rows)


async def render_calendar_view(user: User, db: AsyncSession) -> tuple[str, dict[str, Any] | None]:
    """Render the 7-day calendar schedule, auto-completing concluded events."""
    now = datetime.now(UTC)
    end_window = now + timedelta(days=7)

    # 1. Automatically mark past events whose end_at has passed as completed
    past_stmt = (
        select(CalendarEvent)
        .where(
            CalendarEvent.owner_id == user.id,
            CalendarEvent.status == CalendarEventStatus.scheduled,
            CalendarEvent.end_at < now,
        )
    )
    past_events = (await db.execute(past_stmt)).scalars().all()
    for pe in past_events:
        pe.status = CalendarEventStatus.completed
    if past_events:
        await db.flush()

    # 2. Query only scheduled events that have not ended yet
    stmt = (
        select(CalendarEvent)
        .where(
            CalendarEvent.owner_id == user.id,
            CalendarEvent.status == CalendarEventStatus.scheduled,
            CalendarEvent.end_at >= now,
            CalendarEvent.start_at <= end_window,
        )
        .order_by(CalendarEvent.start_at.asc())
    )
    events = (await db.execute(stmt)).scalars().all()

    tz_name = user.timezone or "Africa/Addis_Ababa"
    lines = [
        "📅 <b>Your 7-Day Calendar & Schedule</b>",
        f"<i>Showing upcoming events between {now.strftime('%b %d')} and {end_window.strftime('%b %d')}</i>\n",
    ]

    if not events:
        lines.append("🌴 <i>No upcoming events in the next 7 days. You have open availability!</i>")
    else:
        for idx, ev in enumerate(events, 1):
            start_str = _format_dt(ev.start_at, tz_name)
            end_str = ev.end_at.strftime("%I:%M %p") if ev.end_at else ""
            if ev.start_at <= now <= ev.end_at:
                lines.append(f"<b>{idx}. 🔴 [Happening Now] {ev.title}</b>")
            else:
                lines.append(f"<b>{idx}. {ev.title}</b>")
            lines.append(f"   🕒 {start_str} – {end_str}")
            if ev.meet_link:
                lines.append(f"   🔗 <a href='{ev.meet_link}'>Join Google Meet</a>")
            if ev.location:
                lines.append(f"   📍 {ev.location}")
            lines.append("")

    action_rows: list[list[dict[str, Any]]] = []
    meet_buttons: list[dict[str, Any]] = []
    for ev in events:
        if ev.meet_link:
            meet_buttons.append({"text": f"🔗 Join: {ev.title[:18]}", "url": ev.meet_link})
    if meet_buttons:
        for i in range(0, len(meet_buttons), 2):
            action_rows.append(meet_buttons[i : i + 2])

    action_rows.append([{"text": "🔄 Refresh Schedule", "callback_data": "nav:calendar"}])

    return "\n".join(lines), get_unified_nav_keyboard("calendar", action_rows)


async def render_tasks_view(user: User, db: AsyncSession) -> tuple[str, dict[str, Any] | None]:
    """Render interactive task manager with professional lifecycle categorization:
    Active, Scheduled, Expired, and Completed.
    """
    now = datetime.now(UTC)
    tz_name = user.timezone or "Africa/Addis_Ababa"

    # 1. Fetch all pending / in-progress tasks
    pending_stmt = (
        select(Task)
        .where(
            Task.owner_id == user.id,
            Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]),
        )
        .order_by(Task.due_at.asc().nullslast(), Task.created_at.desc())
    )
    pending_tasks = (await db.execute(pending_stmt)).scalars().all()

    # 2. Fetch recently completed tasks
    completed_stmt = (
        select(Task)
        .where(
            Task.owner_id == user.id,
            Task.status == TaskStatus.completed,
        )
        .order_by(Task.completed_at.desc().nullslast(), Task.updated_at.desc())
        .limit(5)
    )
    completed_tasks = (await db.execute(completed_stmt)).scalars().all()

    active_tasks: list[Task] = []
    scheduled_tasks: list[Task] = []
    expired_tasks: list[Task] = []

    for t in pending_tasks:
        cat = categorize_task(t, now)
        if cat == "scheduled":
            scheduled_tasks.append(t)
        elif cat == "expired":
            expired_tasks.append(t)
        else:
            active_tasks.append(t)

    lines = [
        "📝 <b>NEXA Task Manager</b>",
        f"👤 <code>{user.full_name}</code> | 🌍 <code>{tz_name}</code>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    priority_icons = {
        TaskPriority.urgent: "🚨 Urgent",
        TaskPriority.high: "⚠️ High",
        TaskPriority.medium: "📌 Medium",
        TaskPriority.low: "☕ Low",
    }

    action_rows: list[list[dict[str, Any]]] = []

    # 1. Active Tasks Section
    lines.append(f"\n⚡ <b>Active Tasks ({len(active_tasks)}):</b>")
    if active_tasks:
        for idx, t in enumerate(active_tasks, 1):
            prio = priority_icons.get(t.priority, "📌 Medium")
            due_str = f" • 🕒 Due: {_format_dt(t.due_at, tz_name)}" if t.due_at else ""
            lines.append(f"<b>{idx}. {t.title}</b> [{prio}]{due_str}")
            if t.description:
                lines.append(f"   <i>{t.description[:80]}</i>")
            action_rows.append([
                {"text": f"✅ Complete: {t.title[:24]}", "callback_data": f"done_task:{t.id}"}
            ])
    else:
        lines.append("• <i>No active tasks right now.</i>")

    # 2. Scheduled Tasks Section
    lines.append(f"\n⏳ <b>Scheduled Tasks ({len(scheduled_tasks)}):</b>")
    if scheduled_tasks:
        for idx, t in enumerate(scheduled_tasks, 1):
            prio = priority_icons.get(t.priority, "📌 Medium")
            lines.append(f"<b>{idx}. {t.title}</b> [{prio}]\n   🕒 <i>Scheduled for: {_format_dt(t.due_at, tz_name)}</i>")
            action_rows.append([
                {"text": f"✅ Complete Early: {t.title[:20]}", "callback_data": f"done_task:{t.id}"}
            ])
    else:
        lines.append("• <i>No scheduled tasks queued.</i>")

    # 3. Expired / Overdue Tasks Section
    if expired_tasks:
        lines.append(f"\n⚠️ <b>Expired / Overdue Tasks ({len(expired_tasks)}):</b>")
        for idx, t in enumerate(expired_tasks, 1):
            prio = priority_icons.get(t.priority, "📌 Medium")
            lines.append(f"<b>{idx}. {t.title}</b> [{prio}]\n   ⚠️ <i>Was due: {_format_dt(t.due_at, tz_name)}</i>")
            action_rows.append([
                {"text": f"✅ Done (Expired): {t.title[:20]}", "callback_data": f"done_task:{t.id}"}
            ])

    # 4. Completed Tasks Section
    lines.append(f"\n✅ <b>Recently Completed ({len(completed_tasks)}):</b>")
    if completed_tasks:
        for _idx, t in enumerate(completed_tasks, 1):
            done_time = _format_dt(t.completed_at, tz_name) if t.completed_at else "Recently"
            lines.append(f"• <s>{t.title}</s> <i>({done_time})</i>")
    else:
        lines.append("• <i>No completed tasks yet.</i>")

    action_rows.append([{"text": "🔄 Refresh Tasks", "callback_data": "nav:tasks"}])

    return "\n".join(lines), get_unified_nav_keyboard("tasks", action_rows)


async def render_plans_view(user: User, db: AsyncSession) -> tuple[str, dict[str, Any] | None]:
    """Render recent action plans and their execution status."""
    stmt = (
        select(ActionPlan)
        .where(ActionPlan.user_id == user.id)
        .order_by(ActionPlan.created_at.desc())
        .limit(5)
    )
    plans = (await db.execute(stmt)).scalars().all()

    lines = [
        "📋 <b>Action Plans & Execution History</b>\n",
    ]

    status_badges = {
        ActionPlanStatus.pending_approval: "⏳ Awaiting Approval",
        ActionPlanStatus.approved: "✅ Approved",
        ActionPlanStatus.executing: "⚙️ Executing...",
        ActionPlanStatus.completed: "🎉 Completed",
        ActionPlanStatus.rejected: "❌ Rejected",
        ActionPlanStatus.failed: "⚠️ Execution Failed",
    }

    action_rows: list[list[dict[str, Any]]] = []

    if not plans:
        lines.append("<i>No action plans recorded yet. Ask NEXA to schedule something!</i>")
    else:
        for idx, p in enumerate(plans, 1):
            badge = status_badges.get(p.status, p.status.value)
            date_str = _format_dt(p.created_at, user.timezone or "Africa/Addis_Ababa")
            lines.append(f"<b>{idx}. {p.title}</b>")
            lines.append(f"   Status: <b>{badge}</b> • {date_str}")
            if p.rejection_reason:
                lines.append(f"   Reason: <i>{p.rejection_reason}</i>")
            lines.append("")

            # If awaiting approval, offer instant inline buttons
            if p.status == ActionPlanStatus.pending_approval:
                action_rows.append([
                    {"text": f"✅ Approve: {p.title[:20]}", "callback_data": f"approve:{p.id}"},
                    {"text": "❌ Reject", "callback_data": f"reject:{p.id}"},
                ])

    action_rows.append([{"text": "🔄 Refresh Plans", "callback_data": "nav:plans"}])

    return "\n".join(lines), get_unified_nav_keyboard("plans", action_rows)


async def render_integrations_view(user: User, db: AsyncSession) -> tuple[str, dict[str, Any] | None]:
    """Render connected workspace services and authentication status."""
    google_stmt = select(ConnectedAccount).where(
        ConnectedAccount.user_id == user.id,
        ConnectedAccount.provider == IntegrationProvider.google,
        ConnectedAccount.is_active == True,  # noqa: E712
    )
    google_acc = (await db.execute(google_stmt)).scalar_one_or_none()

    lines = [
        "🔗 <b>Connected Integrations & Services</b>\n",
        "<b>1. Google Workspace (Calendar, Meet, Gmail, Tasks):</b>",
    ]

    action_rows: list[list[dict[str, Any]]] = []

    # Get service URL (Render URL)
    base_url = "https://nexa-1jwm.onrender.com"
    connect_url = f"{base_url}/api/v1/integrations/google/connect-browser?token={user.id}"

    if google_acc:
        lines.append(f"   • Status: ✅ <b>Connected</b> ({google_acc.email})")
        lines.append(f"   • Linked at: <i>{_format_dt(google_acc.created_at)}</i>")
    else:
        lines.append("   • Status: ❌ <b>Not Connected</b>")
        lines.append("   • <i>Connect to allow NEXA to create Calendar events and send Gmail invites.</i>")
        action_rows.append([
            {"text": "🔗 Connect Google Workspace", "url": connect_url}
        ])

    lines.append("\n<b>2. Telegram Bot Assistant:</b>")
    lines.append(f"   • Status: ✅ <b>Active</b> (Chat ID: <code>{user.telegram_id}</code>)")

    lines.append("\n<b>3. n8n Automation Engine:</b>")
    n8n_status = "✅ Configured" if settings.n8n_configured else "⚙️ Optional Webhook"
    lines.append(f"   • Status: <i>{n8n_status}</i>")

    action_rows.append([{"text": "🔄 Refresh Services", "callback_data": "nav:integrations"}])

    return "\n".join(lines), get_unified_nav_keyboard("integrations", action_rows)


def render_help_view(user: User) -> tuple[str, dict[str, Any] | None]:
    """Render quick usage guide and voice/text commands."""
    lines = [
        "❓ <b>How to talk to NEXA</b>\n",
        "NEXA is your autonomous executive assistant. You can speak naturally or use quick commands:\n",
        "🗣️ <b>Natural Language Examples:</b>",
        "• <i>'Tomorrow at 10 AM, schedule a meeting with client Sarah (sarah@acme.com) about the merger'</i>",
        "• <i>'Do I have any conflicts on Friday between 2 PM and 4 PM?'</i>",
        "• <i>'Add task: Finalize audit report due Thursday, urgent priority'</i>",
        "• <i>'What are my highest priority tasks right now?'</i>",
        "• <i>'Cancel my 3 PM meeting today'</i>\n",
        "⚡ <b>Menu Tabs:</b>",
        "• <b>📊 Dashboard:</b> Executive summary of today's schedule & tasks",
        "• <b>📅 Calendar:</b> Next 7 days of meetings & Meet links",
        "• <b>📝 Tasks:</b> Task manager with one-click completion buttons",
        "• <b>📋 Plans:</b> Action plans awaiting your review & approval",
        "• <b>🔗 Services:</b> Google Workspace & service status",
    ]
    action_rows = [
        [{"text": "📊 Open Executive Dashboard", "callback_data": "nav:dashboard"}]
    ]
    return "\n".join(lines), get_unified_nav_keyboard("help", action_rows)
