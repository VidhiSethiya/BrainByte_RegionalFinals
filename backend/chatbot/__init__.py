"""Chatbot conversation layer — sessions, memory, context, orchestration.

Do not import conversation_manager at package import time: that pulls ai.agents
while agents is still loading (agents → context_manager → chatbot → … → agents).
"""

from __future__ import annotations

from typing import Any

__all__ = ["handle_message"]


def __getattr__(name: str) -> Any:
    if name == "handle_message":
        from chatbot.conversation_manager import handle_message

        return handle_message
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
