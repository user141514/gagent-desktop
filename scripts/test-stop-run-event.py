import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from core.api.app import ReactApiRuntime, RunCreateRequest
from core.protocol.agent import AgentBackend
from core.protocol.channel import AgentOutputChannel, QueueOutputChannel
from core.protocol.input import AgentInput


class FakeAgent(AgentBackend):
    def __init__(self) -> None:
        self.channel = QueueOutputChannel()
        self.aborted = False

    def submit(self, task: AgentInput) -> AgentOutputChannel:
        return self.channel

    def abort(self) -> None:
        self.aborted = True

    @property
    def is_running(self) -> bool:
        return not self.channel.closed

    def get_llm_name(self) -> str:
        return "fake"

    def get_key_labels(self) -> list[str]:
        return []

    def switch_to_key(self, index: int) -> str:
        return "fake"


def parse_sse(payload: str) -> dict:
    data_line = next(line for line in payload.splitlines() if line.startswith("data: "))
    return json.loads(data_line[6:])


async def main() -> None:
    agent = FakeAgent()
    runtime = ReactApiRuntime(agent, project_root=str(ROOT))
    run = runtime.create_run(RunCreateRequest(query="hello"))
    response = runtime.stop_run(run.run_id)
    assert response.status == "stopped"
    assert agent.aborted

    events = []
    async for payload in runtime.stream_events(run.run_id):
        events.append(parse_sse(payload))

    assert any(event["kind"] == "stopped" and event["task_id"] == run.run_id for event in events), events
    assert runtime.active_run is not None and runtime.active_run.terminal
    print("stop run event test passed")


if __name__ == "__main__":
    asyncio.run(main())
