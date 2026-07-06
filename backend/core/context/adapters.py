"""
Context Injection Adapters — thin wrappers that convert ContextPacket
into backend-specific injection formats.

M5: OpenAIContextAdapter for the OpenAI orchestration path.

Design rules:
  1. Adapters only format/reorder — they never read files or compute context.
  2. Every injected block carries a structural marker (not bare role: user).
  3. The raw user query is always the LAST entry in the inputs list.
"""

from __future__ import annotations

import os
import time
from typing import Any


# ═══ Structural markers ═════════════════════════════════════════════════════

_MARKER_WORKING_MEMORY = "[WORKING MEMORY]"
_MARKER_PROJECT_MEMORY = "[PROJECT MEMORY]"
_MARKER_RECENT_CONTEXT = "[RECENT CONTEXT]"
_MARKER_CONTEXT_PACKET = "[CONTEXT PACKET]"
_MARKER_ROUTE_HINT = "[ROUTER HINT]"
_MARKER_ANSWER_QUALITY = "[ANSWER QUALITY]"
_MARKER_RESEARCH_WORKFLOW = "[RESEARCH WORKFLOW]"
_MARKER_STATE_DRIVEN_THINKING = "[STATE-DRIVEN THINKING]"
_MARKER_SKILLS = "[ACTIVE SKILLS]"
_MARKER_PREFETCH = "[PREFETCH CONTENT]"
_MARKER_CLARIFICATION = "[CONTEXT NOTE]"

# Marker applied to all injected context blocks to distinguish them from user input
_CONTEXT_ROLE_MARKER = "### [SYSTEM CONTEXT — not user input]"


class OpenAIContextAdapter:
    """Build the inputs list for Runner.run_streamed() from canonical sources.

    Replaces the 11 hand-rolled inputs.append() calls in _run_task_async()
    with a single auditable assembly point.

    Usage:
        adapter = OpenAIContextAdapter(policy_mode="preview")
        inputs = adapter.build_inputs(
            input_items=existing_inputs,
            working_memory=working_memory_text,
            context_packet=context_packet_text,
            recent_block=recent_conversation_text,
            legacy_memory=legacy_l1l2_text,
            route_hint=hint_text,
            answer_quality=aq_text,
            sop_context=sop_text,
            prefetch_block=prefetch_text,
            clarification=clarify_text,
            raw_query=user_query,
        )
    """

    def __init__(self, *, policy_mode: str = "preview"):
        self._policy_mode = policy_mode

    def build_inputs(
        self,
        *,
        input_items: list[dict[str, Any]],
        working_memory: str = "",
        context_packet: str = "",
        recent_block: str = "",
        legacy_memory: str = "",
        route_hint: str = "",
        answer_quality: str = "",
        research_workflow: str = "",
        state_driven_thinking: str = "",
        sop_context: str = "",
        prefetch_block: str = "",
        clarification: str = "",
        raw_query: str = "",
    ) -> list[dict[str, Any]]:
        """Build the ordered inputs list from all source blocks.

        Order:
          1. input_items (conversation history, as-is)
          2. working_memory   [WORKING MEMORY]
          3. context_packet   [CONTEXT PACKET]
          4. recent_block     [RECENT CONTEXT]
          5. legacy_memory    [PROJECT MEMORY]
          6. route_hint       [ROUTER HINT]
          7. answer_quality   [ANSWER QUALITY]
          8. sop_context      [ACTIVE SKILLS]
          9. prefetch_block   [PREFETCH CONTENT]
          10. clarification   [CONTEXT NOTE]
          11. raw_query       (unmarked — this IS the user input)

        Every context block (#2-#10) is wrapped with a structural marker
        to distinguish it from actual user input.
        """
        inputs: list[dict[str, Any]] = list(input_items)

        # Each context block is wrapped with a marker prefix
        _add_marked(inputs, working_memory, _MARKER_WORKING_MEMORY)
        _add_marked(inputs, context_packet, _MARKER_CONTEXT_PACKET)
        _add_marked(inputs, recent_block, _MARKER_RECENT_CONTEXT)
        _add_marked(inputs, legacy_memory, _MARKER_PROJECT_MEMORY)

        # Route hint — only injected when set and agent is root
        if route_hint:
            inputs.append({"role": "user", "content": f"[{_MARKER_ROUTE_HINT}]\n{route_hint}"})

        _add_marked(inputs, answer_quality, _MARKER_ANSWER_QUALITY)
        _add_marked(inputs, research_workflow, _MARKER_RESEARCH_WORKFLOW)
        _add_marked(inputs, state_driven_thinking, _MARKER_STATE_DRIVEN_THINKING)
        _add_marked(inputs, sop_context, _MARKER_SKILLS)
        _add_marked(inputs, prefetch_block, _MARKER_PREFETCH)
        _add_marked(inputs, clarification, _MARKER_CLARIFICATION)

        # Raw user query — always LAST, no marker
        inputs.append({"role": "user", "content": raw_query})

        return inputs

    def build_inputs_from_packet(
        self,
        *,
        input_items: list[dict[str, Any]],
        packet: Any,  # ContextPacket (avoid circular import)
        route_hint: str = "",
        answer_quality: str = "",
        research_workflow: str = "",
        state_driven_thinking: str = "",
        sop_context: str = "",
        prefetch_block: str = "",
        clarification: str = "",
        raw_query: str = "",
    ) -> list[dict[str, Any]]:
        """Build inputs from a pre-assembled ContextPacket plus route-specific blocks.

        This is the canonical path — ContextPacket carries workspace, project,
        memory, recent_turns, and working_memory. The adapter adds route-specific
        blocks (answer quality, SOP, prefetch, clarification) and the raw query.
        """
        # Serialize the ContextPacket to get the core blocks
        packet_text = ""
        if packet is not None:
            try:
                # Use serialize() if available, otherwise build manually
                packet_text = _serialize_packet(packet)
            except Exception:
                packet_text = ""

        # Build inputs with the packet text as the combined core context
        return self.build_inputs(
            input_items=input_items,
            working_memory="",  # already in packet
            context_packet=packet_text,
            recent_block="",    # already in packet
            legacy_memory="",   # already in packet (via memory_bundle)
            route_hint=route_hint,
            answer_quality=answer_quality,
            research_workflow=research_workflow,
            state_driven_thinking=state_driven_thinking,
            sop_context=sop_context,
            prefetch_block=prefetch_block,
            clarification=clarification,
            raw_query=raw_query,
        )


# ═══ Helpers ════════════════════════════════════════════════════════════════

def _add_marked(inputs: list[dict[str, Any]], content: str, marker: str) -> None:
    """Append a marked context block if non-empty."""
    if not content or not content.strip():
        return
    # If content already starts with a known marker, don't double-wrap
    stripped = content.strip()
    for known in (_MARKER_WORKING_MEMORY, _MARKER_PROJECT_MEMORY,
                  _MARKER_RECENT_CONTEXT, _MARKER_CONTEXT_PACKET,
                  _MARKER_ANSWER_QUALITY, _MARKER_RESEARCH_WORKFLOW, _MARKER_SKILLS,
                  _MARKER_STATE_DRIVEN_THINKING, _MARKER_PREFETCH,
                  _MARKER_CLARIFICATION, _MARKER_ROUTE_HINT):
        if stripped.startswith(known) or stripped.startswith("[" + known + "]"):
            inputs.append({"role": "user", "content": content})
            return
    inputs.append({"role": "user", "content": f"[{marker}]\n{content}"})


def _serialize_packet(packet: Any) -> str:
    """Serialize a ContextPacket to text, handling import gracefully."""
    if packet is None:
        return ""
    if hasattr(packet, "serialize"):
        # ContextBuilder.serialize() if we have the builder
        return packet.serialize()
    # Fallback: use to_dict and format manually
    try:
        d = packet.to_dict()
        lines = [
            f"[CONTEXT PACKET — preview mode, {d.get('total_chars', 0)} chars, "
            f"route={d.get('target_route', 'unknown')}]",
        ]
        breakdown = d.get("source_breakdown", {})
        if breakdown:
            lines.append(f"sources: {breakdown}")
        lines.append("[/CONTEXT PACKET]")
        return "\n".join(lines)
    except Exception:
        return ""
