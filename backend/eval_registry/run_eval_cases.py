#!/usr/bin/env python
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any


BACKEND = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from core import ga  # noqa: E402
from core.agent_loop import BaseHandler, StepOutcome, agent_runner_loop, exhaust  # noqa: E402
from eval_registry.registry import EvalCase, load_eval_cases  # noqa: E402
from eval_registry.score_final_answer import make_default_final_answer, score_final_answer  # noqa: E402
from eval_registry.score_eval_result import score_case_result  # noqa: E402
from runtime_ledger import LedgerEvent, read_run_events, summarize_run, write_event  # noqa: E402


RESULTS_DIR = ROOT / "backend" / "eval_registry" / "results"


class _DummyParent:
    verbose = False


class _FakeDriver:
    def __init__(self) -> None:
        self.default_session_id = "tab-1"
        self.urls = {
            "tab-1": "https://example.com/current",
            "tab-2": "https://openai.com/docs",
        }

    def get_all_sessions(self) -> list[dict[str, str]]:
        return [
            {"id": key, "url": value, "connected_at": "now", "type": "page"}
            for key, value in self.urls.items()
        ]

    def get_session_dict(self) -> dict[str, str]:
        return dict(self.urls)

    def execute_js(self, script: str) -> dict[str, Any]:
        if "location" in str(script):
            self.urls[self.default_session_id] = "https://example.com/after-nav"
        return {"status": "success", "js_return": None}


class _FakeFunction:
    def __init__(self, name: str, arguments: dict[str, Any]) -> None:
        self.name = name
        self.arguments = json.dumps(arguments, ensure_ascii=False)


class _FakeToolCall:
    def __init__(self, name: str, arguments: dict[str, Any], call_id: str) -> None:
        self.function = _FakeFunction(name, arguments)
        self.id = call_id


class _FakeResponse:
    def __init__(self, content: str, tool_calls: list[_FakeToolCall] | None = None) -> None:
        self.thinking = ""
        self.content = content
        self.tool_calls = tool_calls or []
        self.raw = content


class _FakeAgentLoopClient:
    name = "eval_fake_agent_loop_client"

    class _Backend:
        name = "eval_fake_backend"

    def __init__(self, args: dict[str, Any]) -> None:
        self.args = args
        self.backend = self._Backend()
        self.last_tools = ""
        self.turn = 0

    def chat(self, messages, tools=None):
        if False:
            yield ""
        self.turn += 1
        if self.turn == 1:
            return _FakeResponse(
                "I will call web_search.",
                [_FakeToolCall("web_search", dict(self.args), "eval_call_1")],
            )
        return _FakeResponse("web_search succeeded. Source: https://openai.com/docs")


class _AgentLoopEvalHandler(BaseHandler):
    def do_web_search(self, args, response):
        yield "[eval] web_search stub\n"
        return StepOutcome(
            {
                "status": "success",
                "results": [
                    {
                        "title": "OpenAI API docs",
                        "url": "https://openai.com/docs",
                    }
                ],
            },
            next_prompt="Write the final answer from the web_search result.",
        )

    def do_no_tool(self, args, response):
        return StepOutcome(
            {"status": "success", "answer": getattr(response, "content", "")},
            next_prompt=None,
        )


def run_eval_cases(write_report: bool = True) -> dict[str, Any]:
    cases = load_eval_cases()
    results = []
    for case in cases:
        if case.type == "agent_loop_eval":
            results.append(_run_agent_loop_case(case))
        elif case.target_tool == "web_search":
            results.append(_run_web_search_case(case))
        elif case.target_tool in {"web_scan", "web_execute_js"}:
            results.append(_run_browser_bridge_case(case))
        elif case.target_tool == "browser_agent" and case.type == "tool_contract_eval":
            results.append(_run_contract_case(case))
        elif case.target_tool == "browser_agent":
            results.append(_run_browser_agent_handler_case(case))
        else:
            results.append({
                "case_id": case.id,
                "verdict": "skip",
                "reason": f"target_tool {case.target_tool} is not supported in eval_registry",
            })

    failed = [item for item in results if item.get("verdict") == "fail"]
    summary = {
        "status": "ok" if not failed else "failed",
        "case_count": len(cases),
        "passed": len([item for item in results if item.get("verdict") == "pass"]),
        "failed": len(failed),
        "skipped": len([item for item in results if item.get("verdict") == "skip"]),
        "results": results,
    }
    if write_report:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (RESULTS_DIR / "latest_eval_report.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    return summary


def _run_agent_loop_case(case: EvalCase) -> dict[str, Any]:
    run_id = f"eval_{case.id}_{time.time_ns()}"
    args = dict(case.input)
    write_event(LedgerEvent(
        run_id=run_id,
        event_type="run_started",
        task=case.task,
        owner_layer=case.owner_layer,
        metadata={"integration_scope": "agent_loop_runtime_mapper"},
    ))
    write_event(LedgerEvent(
        run_id=run_id,
        event_type="tool_call",
        task=case.task,
        owner_layer=case.owner_layer,
        tool=case.target_tool,
        args=args,
    ))
    tool_result = _exercise_agent_loop_runtime_mapper(case, run_id, args)
    write_event(LedgerEvent(
        run_id=run_id,
        event_type="tool_result",
        task=case.task,
        owner_layer=case.owner_layer,
        tool=case.target_tool,
        args=args,
        result=tool_result,
    ))
    result_status = str(tool_result.get("status") or "unknown").lower()
    if result_status in {"error", "failed", "blocked", "timeout"}:
        write_event(LedgerEvent(
            run_id=run_id,
            event_type="decision",
            task=case.task,
            owner_layer=case.owner_layer,
            decision={
                "action": "report_runtime_mapper_blocker",
                "forbidden_actions": case.expected_ledger.get("required_decision_forbidden_actions") or [],
                "next_tool": "",
            },
        ))
    write_event(LedgerEvent(
        run_id=run_id,
        event_type="run_finished",
        task=case.task,
        owner_layer=case.owner_layer,
        tool=case.target_tool,
        final_status="success" if result_status == "success" else "structured_failure",
        metadata={"result_status": result_status},
    ))
    ledger_events = read_run_events(run_id)
    ledger_summary = summarize_run(run_id)
    score = score_case_result(case, tool_result, ledger_events, ledger_summary)
    forbidden = set(str(x) for x in case.expected_tools.get("forbidden") or [])
    forbidden_used = sorted({str(event.get("tool") or "") for event in ledger_events} & forbidden)
    score.update({
        "run_id": run_id,
        "target_tool": case.target_tool,
        "tool_status": str(tool_result.get("status") or ""),
        "runtime_event_types": tool_result.get("runtime_event_types") or [],
        "runtime_started_turns": tool_result.get("runtime_started_turns"),
        "runtime_completed_turns": tool_result.get("runtime_completed_turns"),
        "ledger_event_count": len(ledger_events),
        "final_status": ledger_summary.get("final_status"),
        "forbidden_tools_used": forbidden_used,
    })
    return _attach_final_answer_score(case, tool_result, score)


def _exercise_agent_loop_runtime_mapper(case: EvalCase, run_id: str, args: dict[str, Any]) -> dict[str, Any]:
    from core.protocol.formatter import NullFormatter
    from core.runtime.host import RuntimeHost
    from core.runtime.protocol_bridge import RuntimeEventMapper

    logs_root = RESULTS_DIR / "runtime_host_logs"
    host = RuntimeHost(
        project_root=str(ROOT),
        logs_root=str(logs_root),
        session_db_path=str(RESULTS_DIR / "runtime_host_sessions.sqlite"),
        agent_name="eval_agent_loop",
    )
    host.start_session(user_intent=case.task, source="eval", session_id=run_id)
    mapper = RuntimeEventMapper(host)
    client = _FakeAgentLoopClient(args)
    handler = _AgentLoopEvalHandler()
    exit_reason = exhaust(agent_runner_loop(
        client,
        "You are an eval fake agent.",
        case.task,
        handler,
        tools_schema=[],
        max_turns=3,
        verbose=False,
        runtime_mapper=mapper,
        formatter=NullFormatter(),
        turn_gap=0.0,
    ))
    mapper.on_done(str(exit_reason))
    runtime_events = _read_runtime_host_events(host)
    event_types = [str(event.get("event_type") or "") for event in runtime_events]
    required = [str(x) for x in case.expected_result.get("require_runtime_events") or []]
    missing = [event for event in required if event not in event_types]
    started_turns = _runtime_turns(event_types, runtime_events, "llm_call_started")
    completed_turns = _runtime_turns(event_types, runtime_events, "llm_call_completed")
    unbalanced = case.expected_result.get("require_balanced_turn_events") and started_turns != completed_turns
    if missing or unbalanced:
        return {
            "status": "error",
            "msg": "runtime mapper events missing or unbalanced",
            "error_category": "runtime_mapper_event_mismatch",
            "runtime_event_types": event_types,
            "runtime_started_turns": started_turns,
            "runtime_completed_turns": completed_turns,
            "missing_runtime_events": missing,
        }
    return {
        "status": "success",
        "runtime_event_types": event_types,
        "runtime_started_turns": started_turns,
        "runtime_completed_turns": completed_turns,
        "exit_result": exit_reason,
    }


def _read_runtime_host_events(host) -> list[dict[str, Any]]:
    path = Path(host.event_log.events_path) if host.event_log is not None else None
    if path is None or not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _runtime_turns(event_types: list[str], events: list[dict[str, Any]], event_type: str) -> list[int]:
    turns: list[int] = []
    for item_type, event in zip(event_types, events):
        if item_type != event_type:
            continue
        payload = event.get("payload") or {}
        turn = payload.get("turn")
        if turn is not None:
            turns.append(int(turn))
    return turns


def _run_web_search_case(case: EvalCase) -> dict[str, Any]:
    run_id = f"eval_{case.id}_{time.time_ns()}"
    args = dict(case.input)
    args["ledger_run_id"] = run_id
    handler = ga.GenericAgentHandler(_DummyParent(), cwd=str(ROOT / "backend" / "temp"))
    outcome = _call_handler(handler.do_web_search(args, ""))
    tool_result = outcome.data if isinstance(outcome, StepOutcome) else outcome
    if not isinstance(tool_result, dict):
        tool_result = {"status": "error", "msg": str(tool_result)}
    ledger_events = read_run_events(run_id)
    ledger_summary = summarize_run(run_id)
    score = score_case_result(case, tool_result, ledger_events, ledger_summary)
    forbidden = set(str(x) for x in case.expected_tools.get("forbidden") or [])
    forbidden_used = sorted({str(event.get("tool") or "") for event in ledger_events} & forbidden)
    score.update({
        "run_id": run_id,
        "target_tool": case.target_tool,
        "tool_status": str(tool_result.get("status") or ""),
        "error_category": str(tool_result.get("error_category") or ""),
        "attempt_engines": [
            str(item.get("engine") or "")
            for item in tool_result.get("attempts") or []
            if isinstance(item, dict) and item.get("engine")
        ],
        "ledger_event_count": len(ledger_events),
        "final_status": ledger_summary.get("final_status"),
        "forbidden_tools_used": forbidden_used,
    })
    return _attach_final_answer_score(case, tool_result, score)


def _run_contract_case(case: EvalCase) -> dict[str, Any]:
    run_id = f"eval_{case.id}_{time.time_ns()}"
    args = dict(case.input)
    write_event(LedgerEvent(
        run_id=run_id,
        event_type="run_started",
        task=case.task,
        owner_layer=case.owner_layer,
        metadata={"integration_scope": "eval_harness_contract"},
    ))
    write_event(LedgerEvent(
        run_id=run_id,
        event_type="tool_call",
        task=case.task,
        owner_layer=case.owner_layer,
        tool=case.target_tool,
        args=args,
    ))
    tool_result = _check_registry_contract(case)
    write_event(LedgerEvent(
        run_id=run_id,
        event_type="tool_result",
        task=case.task,
        owner_layer=case.owner_layer,
        tool=case.target_tool,
        args=args,
        result=tool_result,
    ))
    result_status = str(tool_result.get("status") or "unknown").lower()
    write_event(LedgerEvent(
        run_id=run_id,
        event_type="run_finished",
        task=case.task,
        owner_layer=case.owner_layer,
        tool=case.target_tool,
        final_status="success" if result_status == "success" else "structured_failure",
        metadata={"result_status": result_status},
    ))
    ledger_events = read_run_events(run_id)
    ledger_summary = summarize_run(run_id)
    score = score_case_result(case, tool_result, ledger_events, ledger_summary)
    forbidden = set(str(x) for x in case.expected_tools.get("forbidden") or [])
    forbidden_used = sorted({str(event.get("tool") or "") for event in ledger_events} & forbidden)
    score.update({
        "run_id": run_id,
        "target_tool": case.target_tool,
        "tool_status": str(tool_result.get("status") or ""),
        "contract_valid": bool(tool_result.get("contract_valid")),
        "ledger_event_count": len(ledger_events),
        "final_status": ledger_summary.get("final_status"),
        "forbidden_tools_used": forbidden_used,
    })
    return _attach_final_answer_score(case, tool_result, score)


def _check_registry_contract(case: EvalCase) -> dict[str, Any]:
    registry_file = ROOT / str(case.input.get("registry_file") or "")
    try:
        text = registry_file.read_text(encoding="utf-8").lower()
    except OSError as exc:
        return {"status": "error", "msg": f"cannot read registry contract: {exc}"}
    terms = [str(item).lower() for item in case.expected_result.get("require_contract_terms") or []]
    missing = [term for term in terms if term not in text]
    forbidden_texts = ["ordinary web_search fallback", "simple current-tab inspection", "single-shot dom scripting"]
    forbidden_present = [term for term in forbidden_texts if term in text]
    valid = not missing and len(forbidden_present) == len(forbidden_texts)
    if not valid:
        return {
            "status": "error",
            "msg": "browser_agent registry contract is incomplete",
            "contract_valid": False,
            "missing_terms": missing,
            "checked_forbidden_behaviors": forbidden_present,
        }
    return {
        "status": "success",
        "contract_valid": True,
        "checked_terms": terms,
        "checked_forbidden_behaviors": forbidden_present,
    }


def _run_browser_bridge_case(case: EvalCase) -> dict[str, Any]:
    run_id = f"eval_{case.id}_{time.time_ns()}"
    args = dict(case.input)
    args["ledger_run_id"] = run_id
    tool_result = _call_browser_bridge_tool(case.target_tool, args)
    if not isinstance(tool_result, dict):
        tool_result = {"status": "error", "msg": str(tool_result)}
    ledger_events = read_run_events(run_id)
    ledger_summary = summarize_run(run_id)
    score = score_case_result(case, tool_result, ledger_events, ledger_summary)
    forbidden = set(str(x) for x in case.expected_tools.get("forbidden") or [])
    forbidden_used = sorted({str(event.get("tool") or "") for event in ledger_events} & forbidden)
    score.update({
        "run_id": run_id,
        "target_tool": case.target_tool,
        "tool_status": str(tool_result.get("status") or ""),
        "ledger_event_count": len(ledger_events),
        "final_status": ledger_summary.get("final_status"),
        "forbidden_tools_used": forbidden_used,
    })
    return _attach_final_answer_score(case, tool_result, score)


def _run_browser_agent_handler_case(case: EvalCase) -> dict[str, Any]:
    run_id = f"eval_{case.id}_{time.time_ns()}"
    args = dict(case.input)
    args["ledger_run_id"] = run_id
    tool_result = _call_browser_agent_stub(args)
    if not isinstance(tool_result, dict):
        tool_result = {"status": "error", "msg": str(tool_result)}
    ledger_events = read_run_events(run_id)
    ledger_summary = summarize_run(run_id)
    score = score_case_result(case, tool_result, ledger_events, ledger_summary)
    forbidden = set(str(x) for x in case.expected_tools.get("forbidden") or [])
    forbidden_used = sorted({str(event.get("tool") or "") for event in ledger_events} & forbidden)
    status = str(tool_result.get("status") or "").strip().lower()
    if not status and tool_result.get("success") is True:
        status = "success"
    elif not status and tool_result.get("success") is False:
        status = "error"
    score.update({
        "run_id": run_id,
        "target_tool": case.target_tool,
        "tool_status": status,
        "steps_taken": tool_result.get("steps_taken"),
        "ledger_event_count": len(ledger_events),
        "final_status": ledger_summary.get("final_status"),
        "forbidden_tools_used": forbidden_used,
    })
    return _attach_final_answer_score(case, tool_result, score)


def _attach_final_answer_score(case: EvalCase, tool_result: dict, score: dict[str, Any]) -> dict[str, Any]:
    answer_text = make_default_final_answer(case, tool_result)
    answer_score = score_final_answer(case, answer_text, tool_result)
    score["final_answer"] = {
        "text": answer_text,
        "total": answer_score["total"],
        "verdict": answer_score["verdict"],
        "reasons": answer_score["reasons"],
        "penalties": answer_score["penalties"],
    }
    if answer_score["verdict"] == "fail":
        score["verdict"] = "fail"
        score.setdefault("penalties", []).append("final answer score failed")
    return score


def _call_browser_agent_stub(args: dict[str, Any]) -> dict[str, Any]:
    from core import browser_agent as browser_agent_module

    original_run = browser_agent_module.run_browser_agent

    def fake_run_browser_agent(task, llm_config, max_steps=20, headless=True, progress_cb=None):
        return {
            "success": True,
            "result": f"stubbed browser_agent completed: {task}",
            "steps_taken": min(int(max_steps or 1), 2),
        }

    try:
        browser_agent_module.run_browser_agent = fake_run_browser_agent
        handler = ga.GenericAgentHandler(_DummyParent(), cwd=str(ROOT / "backend" / "temp"))
        return _coerce_handler_result(_call_handler(handler.do_browser_agent(args, "")))
    finally:
        browser_agent_module.run_browser_agent = original_run


def _call_browser_bridge_tool(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    original_driver = ga.driver
    original_sleep = ga.time.sleep
    try:
        ga.driver = _FakeDriver()
        handler = ga.GenericAgentHandler(_DummyParent(), cwd=str(ROOT / "backend" / "temp"))
        if tool_name == "web_scan":
            return _coerce_handler_result(_call_handler(handler.do_web_scan(args, "")))
        if tool_name == "web_execute_js":
            ga.time.sleep = lambda _seconds: None
            return _coerce_handler_result(_call_handler(handler.do_web_execute_js(args, "")))
        return {"status": "error", "msg": f"unsupported browser bridge eval tool: {tool_name}"}
    finally:
        ga.driver = original_driver
        ga.time.sleep = original_sleep


def _coerce_handler_result(outcome: Any) -> dict[str, Any]:
    value = outcome.data if isinstance(outcome, StepOutcome) else outcome
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {"status": "error", "msg": str(value)}


def _call_handler(value: Any) -> Any:
    if hasattr(value, "__iter__") and not isinstance(value, (str, bytes, dict, list, tuple)):
        return exhaust(value)
    return value


def main() -> int:
    summary = run_eval_cases(write_report=True)
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    return 0 if summary.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
