"""Chatbot conversation layer — sessions, memory, context, orchestration.

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
