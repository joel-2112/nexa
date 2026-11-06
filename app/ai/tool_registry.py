"""Tool registry for explicit, secure application capabilities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    requires_approval: bool = False
    handler: Callable[..., Any] | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        requires_approval: bool = False,
        handler: Callable[..., Any] | None = None,
    ) -> None:
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            requires_approval=requires_approval,
            handler=handler,
        )

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def is_approval_required(self, name: str) -> bool:
        tool = self._tools.get(name)
        return tool.requires_approval if tool else True

    def get_openai_tools(self) -> list[dict[str, Any]]:
        """Return the function definitions in OpenAI tool schema format."""
        openai_tools = []
        for tool in self._tools.values():
            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
            )
        return openai_tools


tool_registry = ToolRegistry()

# Register core application tools

tool_registry.register(
    name="check_calendar_availability",
    description="Check whether the user is free or busy during a specific time range.",
    parameters={
        "type": "object",
        "properties": {
            "start_time": {
                "type": "string",
                "description": "ISO 8601 start time (e.g. 2026-11-07T14:00:00Z)",
            },
            "end_time": {
                "type": "string",
                "description": "ISO 8601 end time (e.g. 2026-11-07T15:00:00Z)",
            },
        },
        "required": ["start_time", "end_time"],
    },
    requires_approval=False,
)

tool_registry.register(
    name="create_calendar_event",
    description="Create a calendar event with an optional Google Meet link and attendees. Requires user approval.",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Title or subject of the meeting"},
            "start_time": {"type": "string", "description": "ISO 8601 meeting start time"},
            "end_time": {"type": "string", "description": "ISO 8601 meeting end time"},
            "description": {"type": "string", "description": "Meeting agenda or description"},
            "location": {"type": "string", "description": "Physical location or virtual notes"},
            "attendee_emails": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of participant email addresses to invite",
            },
            "add_google_meet": {
                "type": "boolean",
                "description": "Whether to generate a Google Meet conference link",
                "default": True,
            },
        },
        "required": ["title", "start_time", "end_time"],
    },
    requires_approval=True,
)

tool_registry.register(
    name="create_task",
    description="Create a new task or preparation item in the user's task list. Requires user approval.",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Task summary or title"},
            "description": {"type": "string", "description": "Details or notes for the task"},
            "due_date": {"type": "string", "description": "ISO 8601 due date or timestamp"},
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high", "urgent"],
                "default": "medium",
            },
        },
        "required": ["title"],
    },
    requires_approval=True,
)

tool_registry.register(
    name="list_tasks",
    description="List active or pending tasks for the user.",
    parameters={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed", "cancelled"],
                "description": "Filter by task status",
            },
            "limit": {"type": "integer", "default": 10},
        },
    },
    requires_approval=False,
)

tool_registry.register(
    name="search_contacts",
    description="Search user's saved contacts by name, email, or company.",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Name, email, or company to search for"}},
        "required": ["query"],
    },
    requires_approval=False,
)

tool_registry.register(
    name="send_email_invitation",
    description="Send an email or meeting briefing to an external recipient. Requires user approval.",
    parameters={
        "type": "object",
        "properties": {
            "to_email": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string", "description": "Email subject line"},
            "body": {"type": "string", "description": "Email message body"},
        },
        "required": ["to_email", "subject", "body"],
    },
    requires_approval=True,
)

tool_registry.register(
    name="schedule_reminder",
    description="Schedule a reminder notification for a meeting or task. Requires user approval.",
    parameters={
        "type": "object",
        "properties": {
            "event_title": {"type": "string", "description": "Name of the event or task"},
            "remind_at": {"type": "string", "description": "ISO 8601 timestamp when reminder should fire"},
            "channel": {
                "type": "string",
                "enum": ["telegram", "email"],
                "default": "telegram",
            },
        },
        "required": ["event_title", "remind_at"],
    },
    requires_approval=True,
)
