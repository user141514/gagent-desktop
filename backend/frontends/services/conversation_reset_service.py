"""Agent conversation state reset helper.

Clears agent backend history, tool cache, and aborts the current task.
Does NOT touch ``st.session_state`` or Streamlit UI — callers remain
responsible for ``st.session_state.messages``, ``st.rerun()``, etc.
"""

from __future__ import annotations


def reset_agent_conversation_state(agent: object) -> None:
    """Abort current task and clear agent conversation history.

    Safely handles missing ``history``, ``llmclient``, or ``backend``
    attributes — no-op when they don't exist (same behaviour as the
    original inline guards in stapp.py).
    """
    agent.abort()

    if hasattr(agent, "history"):
        agent.history = []

    if (
        hasattr(agent, "llmclient")
        and agent.llmclient is not None
        and hasattr(agent.llmclient, "backend")
        and agent.llmclient.backend is not None
    ):
        agent.llmclient.backend.history = []
        agent.llmclient.last_tools = ""
