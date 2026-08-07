"""Chatbot conversation layer — sessions, memory, context, orchestration.

<<<<<<< HEAD
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
=======
Deliberately no package-level re-exports here. `handle_message` used to be
re-exported from `chatbot.conversation_manager`, but every real caller already
imports it directly (`from chatbot.conversation_manager import handle_message`)
— the re-export was unused and created a genuine circular import:
chatbot/__init__ -> conversation_manager -> ai.agents -> (needs chatbot package
init to finish first, for chatbot.context_manager) -> chatbot/__init__, not yet
done. That's a real cycle in the dependency graph, not just a runtime ordering
quirk — it's what IDE import resolvers (and anything that imports `chatbot`
before `ai.agents`) will trip on. Keep this file import-free.
"""
>>>>>>> ea4fe4f2699f83c520f12d8f20cbfca17cec0b37
