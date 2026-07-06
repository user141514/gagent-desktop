from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.protocol.events import AgentOutputEvent
from core.quality.frontier_state import build_frontier_state_snapshot, frontier_state_should_activate


@dataclass
class FrontierRunState:
    """Session-local frontier state for one API run.

    This object is deliberately kept out of the main runtime. The API layer owns
    transport concerns, while core.quality owns scoring and snapshot content.
    Keeping the bridge here makes the future Rust boundary explicit: emit an
    AgentOutputEvent plus metadata, do not reach into Python UI state.
    """

    user_input: str
    route_target: str
    enabled: bool
    latest_snapshot: dict[str, Any] | None = None


def create_frontier_run_state(user_input: str, route_target: str) -> FrontierRunState:
    return FrontierRunState(
        user_input=user_input,
        route_target=route_target,
        enabled=frontier_state_should_activate(user_input, route_target),
    )


def build_frontier_state_event(
    run_id: str,
    frontier: FrontierRunState,
    event: AgentOutputEvent | None = None,
) -> AgentOutputEvent | None:
    """Build the SSE side-channel event for the latest frontier snapshot.

    The returned event is not user-visible assistant text. React consumes it to
    update an expandable state panel, so it must stay structurally separate from
    chunk/done events.
    """

    if not frontier.enabled or (event is not None and event.kind == "frontier_state"):
        return None

    metadata = dict(event.metadata if event is not None else {})
    snapshot = build_frontier_state_snapshot(
        user_input=frontier.user_input,
        route_target=frontier.route_target,
        response_text=(event.text or event.error) if event is not None else "",
        execution_state=metadata.get("execution_state"),
        run_id=run_id,
        metadata=metadata,
    )
    frontier.latest_snapshot = snapshot.to_dict()
    return AgentOutputEvent(
        kind="frontier_state",
        task_id=run_id,
        turn=event.turn if event is not None else 0,
        metadata={"frontier_state": frontier.latest_snapshot},
    )


__all__ = [
    "FrontierRunState",
    "build_frontier_state_event",
    "create_frontier_run_state",
]
