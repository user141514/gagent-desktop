"""Shared prompt capsules for agent runtimes."""

from .agent_behavior_kernel import (
    agent_behavior_kernel_enabled,
    build_agent_behavior_kernel,
)

__all__ = [
    "agent_behavior_kernel_enabled",
    "build_agent_behavior_kernel",
]
