from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any

EXECUTION_HONESTY_ENV_VAR = "GENERIC_AGENT_EXECUTION_HONESTY"
EXECUTION_HONESTY_REPAIR_ENV_VAR = "GENERIC_AGENT_EXECUTION_HONESTY_REPAIR"
TRUSTED_EVIDENCE_STATUSES = {"verified", "tool_verified", "direct", "indirect", "user_provided"}
TRUSTED_ACTION_STATUSES = {"success", "ok", "completed", "done"}

STATE_TRANSITION_PHRASES = (
    "我记下了",
    "已记下",
    "已保存",
    "已写入",
    "已更新",
    "已验证",
    "我检查了",
    "我统计了",
    "已确认",
    "saved",
    "updated",
    "verified",
    "checked",
    "recorded",
)

PERSISTENCE_TRANSITION_PHRASES = (
    "我记下了",
    "已记下",
    "已保存",
    "已写入",
    "已更新",
    "saved",
    "updated",
    "recorded",
)

CAUSAL_MARKERS = (
    "说明",
    "表明",
    "证明",
    "导致",
    "因此",
    "所以",
    "这意味着",
    "because",
    "therefore",
    "this shows",
    "this proves",
)

NEGATION_MARKERS = ("未", "没有", "尚未", "不曾", "当前未", "not ", "no ")
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])(?:~|约)?\d+(?:\.\d+)?%?")


def execution_honesty_enabled() -> bool:
    return os.environ.get(EXECUTION_HONESTY_ENV_VAR, "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def execution_honesty_repair_enabled() -> bool:
    return os.environ.get(EXECUTION_HONESTY_REPAIR_ENV_VAR, "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass(frozen=True)
class RequestedAction:
    type: str = ""
    requires_tool: bool = False
    required_tool_name: str = ""
    expected_state_delta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionAction:
    tool: str
    input_summary: str = ""
    output_summary: str = ""
    status: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StateDelta:
    memory_written: bool = False
    files_changed: tuple[str, ...] = ()
    checkpoints_updated: bool = False
    metrics_verified: bool = False
    claims_added: tuple[str, ...] = ()
    candidates_added: tuple[str, ...] = ()
    archive_updated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResponseClaim:
    claim: str
    claim_type: str
    evidence_status: str = "unsupported"
    source: str = ""
    evidence_type: str = "none"
    confidence: float = 0.0
    verified: bool | None = None
    tolerance: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionState:
    requested_action: RequestedAction | None = None
    actual_actions: list[ExecutionAction] = field(default_factory=list)
    state_delta: StateDelta = field(default_factory=StateDelta)
    unexecuted_commitments: list[dict[str, Any]] = field(default_factory=list)
    response_claims: list[ResponseClaim] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_action": (
                self.requested_action.to_dict() if self.requested_action is not None else None
            ),
            "actual_actions": [action.to_dict() for action in self.actual_actions],
            "state_delta": self.state_delta.to_dict(),
            "unexecuted_commitments": list(self.unexecuted_commitments),
            "response_claims": [claim.to_dict() for claim in self.response_claims],
        }


@dataclass(frozen=True)
class HonestyFinding:
    rule: str
    claim: str
    severity: str
    message: str
    evidence_status: str = "unsupported"
    suggested_rewrite: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HonestyGateResult:
    allowed: bool
    action: str
    findings: list[HonestyFinding] = field(default_factory=list)
    response_claims: list[ResponseClaim] = field(default_factory=list)
    unexecuted_commitments: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "action": self.action,
            "findings": [finding.to_dict() for finding in self.findings],
            "response_claims": [claim.to_dict() for claim in self.response_claims],
            "unexecuted_commitments": list(self.unexecuted_commitments),
        }


def _normalize(text: str) -> str:
    return " ".join(str(text or "").strip().split())


def _has_recent_negation(text: str, start: int) -> bool:
    prefix = text[max(0, start - 10) : start].lower()
    return any(marker in prefix for marker in NEGATION_MARKERS)


def detect_state_transition_claims(response_text: str) -> list[str]:
    text = _normalize(response_text)
    lowered = text.lower()
    claims: list[str] = []
    for phrase in STATE_TRANSITION_PHRASES:
        search_text = lowered if phrase.isascii() else text
        needle = phrase.lower() if phrase.isascii() else phrase
        start = 0
        while True:
            index = search_text.find(needle, start)
            if index < 0:
                break
            if not _has_recent_negation(text, index):
                claims.append(phrase)
            start = index + len(needle)
    return claims


def _successful_actions(state: ExecutionState) -> list[ExecutionAction]:
    return [
        action
        for action in state.actual_actions
        if str(action.status or "").strip().lower() in TRUSTED_ACTION_STATUSES
    ]


def _state_delta_satisfies_expected(state: ExecutionState) -> bool:
    requested = state.requested_action
    if requested is None or not requested.expected_state_delta:
        return True
    delta = state.state_delta.to_dict()
    for key, expected in requested.expected_state_delta.items():
        if bool(delta.get(key)) != bool(expected):
            return False
    return True


def _has_successful_trace(state: ExecutionState) -> bool:
    successful = _successful_actions(state)
    if not successful:
        return False
    requested = state.requested_action
    if requested and requested.required_tool_name:
        if not any(action.tool == requested.required_tool_name for action in successful):
            return False
    return _state_delta_satisfies_expected(state)


def _has_material_state_delta(state: ExecutionState) -> bool:
    delta = state.state_delta
    return bool(
        delta.memory_written
        or delta.files_changed
        or delta.checkpoints_updated
        or delta.claims_added
        or delta.candidates_added
        or delta.archive_updated
    )


def _transition_claim_has_required_trace(claims: list[str], state: ExecutionState) -> bool:
    if not _has_successful_trace(state):
        return False
    normalized_claims = {str(claim or "").strip().lower() for claim in claims}
    if any(
        (phrase.lower() if phrase.isascii() else phrase) in normalized_claims
        for phrase in PERSISTENCE_TRANSITION_PHRASES
    ):
        return _has_material_state_delta(state)
    return True


def _required_next_step(state: ExecutionState) -> str:
    requested = state.requested_action
    if requested and requested.required_tool_name:
        return f"call {requested.required_tool_name}"
    return "run the required tool and capture a success trace"


def _human_next_step(step: str) -> str:
    normalized = str(step or "").strip()
    if normalized.startswith("call "):
        return normalized
    return "call the appropriate tool and confirm a successful result"


def detect_causal_claims(response_text: str) -> list[str]:
    text = _normalize(response_text)
    lowered = text.lower()
    claims: list[str] = []
    for marker in CAUSAL_MARKERS:
        search_text = lowered if marker.isascii() else text
        needle = marker.lower() if marker.isascii() else marker
        if needle in search_text:
            claims.append(text)
            break
    return claims


def detect_quant_claims(response_text: str) -> list[str]:
    text = _normalize(response_text)
    if not text:
        return []
    matches = NUMBER_RE.findall(text)
    if not matches:
        return []
    return [match for match in matches if match]


def _claims_by_type(state: ExecutionState, claim_type: str) -> list[ResponseClaim]:
    return [claim for claim in state.response_claims if claim.claim_type == claim_type]


def _has_acceptable_evidence(claims: list[ResponseClaim]) -> bool:
    for claim in claims:
        status = str(claim.evidence_status or "").strip().lower()
        evidence_type = str(claim.evidence_type or "").strip().lower()
        if status in TRUSTED_EVIDENCE_STATUSES or evidence_type in TRUSTED_EVIDENCE_STATUSES:
            return True
    return False


def _quant_claim_labeled(response_text: str, claims: list[ResponseClaim]) -> bool:
    if _has_acceptable_evidence(claims):
        return True
    text = _normalize(response_text).lower()
    return any(
        marker in text
        for marker in (
            "基于你提供的数字",
            "暂不独立验证",
            "user provided",
            "not independently verified",
            "tool verified",
            "calculated",
        )
    )


def evaluate_execution_honesty(
    response_text: str,
    execution_state: ExecutionState | None = None,
) -> HonestyGateResult:
    state = execution_state or ExecutionState()
    findings: list[HonestyFinding] = []
    unexecuted_commitments = list(state.unexecuted_commitments)

    transition_claims = detect_state_transition_claims(response_text)
    if transition_claims and not _transition_claim_has_required_trace(transition_claims, state):
        commitment = {
            "commitment": ", ".join(transition_claims),
            "reason_not_executed": "no successful execution trace or material state delta",
            "required_next_step": _required_next_step(state),
        }
        unexecuted_commitments.append(commitment)
        findings.append(
            HonestyFinding(
                rule="state_transition_claim_requires_trace",
                claim=commitment["commitment"],
                severity="critical",
                message="Response claims a system state transition without successful tool evidence.",
                evidence_status="unsupported",
                suggested_rewrite=(
                    "我理解了，但当前未写入 checkpoint。下一步应调用 "
                    f"{commitment['required_next_step']} 写入事实快照。"
                ),
            )
        )

    causal_claims = detect_causal_claims(response_text)
    causal_evidence = _claims_by_type(state, "causality")
    if causal_claims and not _has_acceptable_evidence(causal_evidence):
        findings.append(
            HonestyFinding(
                rule="causal_claim_requires_evidence_level",
                claim=causal_claims[0],
                severity="high",
                message="Causal or timeline inference lacks an evidence level.",
                evidence_status="unsupported",
                suggested_rewrite=(
                    "这可能有两种解释：报告本身就有误，或者项目后来发生了变化。"
                    "当前没有时间线证据，不能判断是哪一种。"
                ),
            )
        )

    quant_claims = detect_quant_claims(response_text)
    quant_evidence = _claims_by_type(state, "quant")
    if quant_claims and not _quant_claim_labeled(response_text, quant_evidence):
        findings.append(
            HonestyFinding(
                rule="quant_claim_requires_verification_status",
                claim=", ".join(quant_claims[:5]),
                severity="medium",
                message="Numeric analysis must state whether values are user-provided, verified, calculated, or inferred.",
                evidence_status="unlabeled",
                suggested_rewrite="基于你提供的数字，暂不独立验证。",
            )
        )

    allowed = not findings
    return HonestyGateResult(
        allowed=allowed,
        action="allow" if allowed else "block_or_rewrite",
        findings=findings,
        response_claims=list(state.response_claims),
        unexecuted_commitments=unexecuted_commitments,
    )


def format_honesty_gate_feedback(result: HonestyGateResult) -> str:
    lines = [
        "[EXECUTION HONESTY GATE]",
        "The final response was blocked because it made claims that require execution evidence.",
    ]
    for finding in result.findings:
        lines.append(f"- {finding.rule}: {finding.message} claim={finding.claim!r}")
        if finding.suggested_rewrite:
            lines.append(f"  suggested_rewrite: {finding.suggested_rewrite}")
    if result.unexecuted_commitments:
        lines.append("Unexecuted commitments:")
        for item in result.unexecuted_commitments:
            lines.append(
                f"- {item.get('commitment')}: next={item.get('required_next_step')}"
            )
    lines.append(
        "Rewrite the answer so executed facts are backed by tool traces, and label assumptions/user-provided numbers explicitly."
    )
    return "\n".join(lines)


def format_honesty_user_notice(result: HonestyGateResult) -> str:
    """Format a blocked honesty result for user display.

    ``format_honesty_gate_feedback`` is an internal repair prompt for the model.
    This function is deliberately plain and does not expose repair directives.
    """
    transition_claims = [
        str(finding.claim or "").strip()
        for finding in result.findings
        if finding.rule == "state_transition_claim_requires_trace"
        and str(finding.claim or "").strip()
    ]
    if transition_claims:
        claim_text = (
            "上一版回答使用了需要执行证据的状态表述"
            f"（{'、'.join(transition_claims[:2])}），但本轮没有成功的工具证据支撑它。"
        )
    else:
        claim_text = "上一版回答包含需要执行证据的状态表述，但本轮没有成功的工具证据支撑它。"

    next_steps = [
        str(item.get("required_next_step") or "").strip()
        for item in result.unexecuted_commitments
        if str(item.get("required_next_step") or "").strip()
    ]
    next_step = _human_next_step(next_steps[0]) if next_steps else "call the appropriate tool and confirm a successful result"
    return (
        "执行诚实检查拦下了这次最终回复。\n\n"
        f"{claim_text}\n\n"
        "当前能确定的是：我理解了这个请求，但还不能声称已经完成保存、更新、验证或记忆写入。"
        f"如果需要真的落盘或更新状态，下一步应 {next_step}。"
    )


__all__ = [
    "ExecutionAction",
    "EXECUTION_HONESTY_ENV_VAR",
    "ExecutionState",
    "HonestyFinding",
    "HonestyGateResult",
    "RequestedAction",
    "ResponseClaim",
    "StateDelta",
    "detect_causal_claims",
    "detect_quant_claims",
    "detect_state_transition_claims",
    "execution_honesty_enabled",
    "execution_honesty_repair_enabled",
    "format_honesty_gate_feedback",
    "format_honesty_user_notice",
    "evaluate_execution_honesty",
]
