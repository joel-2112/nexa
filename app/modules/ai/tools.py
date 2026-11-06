"""AI tool definitions for the OpenAI function-calling interface."""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Tool schemas for OpenAI function calling
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": (
                "Create a new calendar event for the user. "
                "Use when the user wants to schedule a meeting, appointment, or event."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Event title"},
                    "description": {"type": "string", "description": "Event description"},
                    "location": {"type": "string", "description": "Physical or virtual location"},
                    "start_at": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Start datetime in ISO 8601 format with timezone",
                    },
                    "end_at": {
                        "type": "string",
                        "format": "date-time",
                        "description": "End datetime in ISO 8601 format with timezone",
                    },
                    "participants": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "email": {"type": "string"},
                                "full_name": {"type": "string"},
                            },
                            "required": ["email"],
                        },
                        "description": "List of participant email addresses",
                    },
                },
                "required": ["title", "start_at", "end_at"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_calendar_events",
            "description": "Retrieve upcoming calendar events for the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_from": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Filter events starting from this datetime",
                    },
                    "start_to": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Filter events until this datetime",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of events to return",
                        "default": 10,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Create a new task or to-do item for the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Task title"},
                    "description": {"type": "string", "description": "Task description"},
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "urgent"],
                        "description": "Task priority level",
                    },
                    "due_at": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Due date/time in ISO 8601 format",
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_tasks",
            "description": "Retrieve the user's tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "cancelled"],
                        "description": "Filter tasks by status",
                    },
                    "limit": {"type": "integer", "default": 10},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an email on behalf of the user via Gmail.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body in plain text or HTML"},
                    "cc": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "CC recipients",
                    },
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_contacts",
            "description": "Search the user's contacts by name or email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_telegram_message",
            "description": "Send a Telegram message to the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Message text to send"},
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task_status",
            "description": "Update the status of an existing task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task UUID"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "cancelled"],
                    },
                },
                "required": ["task_id", "status"],
            },
        },
    },
]

# Tool names that require user approval before execution
APPROVAL_REQUIRED_TOOLS: set[str] = {
    "create_calendar_event",
    "send_email",
    "send_telegram_message",
}

# Tool names that are read-only (no approval needed)
READ_ONLY_TOOLS: set[str] = {
    "get_calendar_events",
    "get_tasks",
    "search_contacts",
}
