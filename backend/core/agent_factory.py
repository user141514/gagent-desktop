"""Agent factory — creates agent backends without frontends importing concrete classes.

Frontends should use ``load_agent()`` instead of directly importing
``GeneraticAgent`` or ``OpenAIOrchestratedAgent``. This enables:
- Swapping backends without changing frontend code
- Testing frontends with mock backends
- Future remote backends (the factory returns any AgentBackend)

Contract: Every return value passes ``isinstance(x, AgentBackend)``.

Adapters: ``ensure_agent_backend()`` wraps legacy agents (have ``put_task()``
but no ``submit()``) behind the ``AgentBackend`` interface so ALL frontend
code paths that pass a ``dispatch_agent`` are safe.
"""

from __future__ import annotations

from core.protocol.agent import AgentBackend
from core.protocol.input import AgentInput
from core.protocol.channel import AgentOutputChannel, QueueOutputChannel


def load_agent(backend: str = "classic", **kwargs: object) -> AgentBackend:
    """Create and start an agent backend.

    Args:
        backend: ``"classic"`` for GeneraticAgent.
                 ``"openai"`` is **blocked** until OpenAIOrchestratedAgent
                 implements ``AgentBackend`` (see Phase 5.5 debt).
        **kwargs: Passed to the agent constructor (e.g., ``llm_no``).

    Returns:
        An AgentBackend instance with its daemon thread already running.

    Raises:
        NotImplementedError: If *backend* is ``"openai"`` (not yet adapted).
        ValueError: If *backend* is unrecognized.
    """
    if backend == "classic":
        from core.agentmain import GeneraticAgent

        agent = GeneraticAgent(**kwargs)  # type: ignore[arg-type]
        import threading

        threading.Thread(target=agent.run, daemon=True).start()
        assert isinstance(agent, AgentBackend), (
            "GeneraticAgent must be an AgentBackend instance"
        )
        return agent

    if backend == "openai":
        from core.openai_agentmain import OpenAIOrchestratedAgent

        agent = OpenAIOrchestratedAgent(**kwargs)  # type: ignore[arg-type]
        import threading

        threading.Thread(target=agent.run, daemon=True).start()
        assert isinstance(agent, AgentBackend), (
            "OpenAIOrchestratedAgent must be an AgentBackend instance"
        )
        return agent

    raise ValueError(
        f"Unknown backend: {backend!r}. Expected 'classic'."
    )


# ── Adapter: wraps legacy agents behind AgentBackend ──────────────────────

class _LegacyAgentAdapter(AgentBackend):
    """Wraps an object that has ``put_task()`` / ``abort()`` / ``is_running``
    but does NOT implement ``AgentBackend`` (e.g. ``OpenAIOrchestratedAgent``).

    ``submit()`` is provided by calling the legacy ``put_task()`` and wrapping
    the returned raw ``queue.Queue`` via ``QueueOutputChannel.from_legacy_queue()``.
    """

    def __init__(self, agent: object) -> None:
        self._agent = agent

    def submit(self, task: AgentInput) -> AgentOutputChannel:
        raw_q = self._agent.put_task(  # type: ignore[attr-defined]
            task.query, task.source, task.images, task.run_id,
        )
        return QueueOutputChannel.from_legacy_queue(raw_q)

    def abort(self) -> None:
        self._agent.abort()  # type: ignore[attr-defined]

    @property
    def is_running(self) -> bool:
        return bool(self._agent.is_running)  # type: ignore[attr-defined]

    def get_llm_name(self) -> str:
        return str(getattr(self._agent, "get_llm_name", lambda: "legacy")())

    def get_key_labels(self) -> list[str]:
        fn = getattr(self._agent, "get_key_labels", None)
        return list(fn()) if callable(fn) else []

    def switch_to_key(self, index: int) -> str:
        fn = getattr(self._agent, "switch_to_key", None)
        if callable(fn):
            return str(fn(index))
        return ""


def ensure_agent_backend(obj: object) -> AgentBackend:
    """Return *obj* as an ``AgentBackend``, wrapping legacy agents if needed.

    - ``AgentBackend`` instances (e.g. ``GeneraticAgent``) → returned unchanged.
    - Objects with ``put_task()`` + ``abort()`` + ``is_running`` (e.g.
      ``OpenAIOrchestratedAgent``) → wrapped in ``_LegacyAgentAdapter``.
    - Otherwise → ``TypeError``.

    Frontends call this on every ``dispatch_agent`` before calling
    ``.submit(AgentInput(...))`` so all code paths are safe.
    """
    if isinstance(obj, AgentBackend):
        return obj

    # Duck-type check: has the legacy put_task/abort/is_running interface
    has_legacy = all(
        hasattr(obj, attr)
        for attr in ("put_task", "abort", "is_running")
    )
    if has_legacy:
        return _LegacyAgentAdapter(obj)

    raise TypeError(
        f"Cannot adapt {type(obj).__name__!r} to AgentBackend: "
        f"missing submit() (AgentBackend) or put_task() (legacy)."
    )
