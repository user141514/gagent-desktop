"""Agent capability profiles — define what an agent CAN DO, not who it is.

Key philosophy: GenericAgent is a tool-use kernel, not a role-playing chatbot.
CapabilityProfiles declare mechanical constraints (tools, budget, skills), not
personas.  The ``build_agent_instructions()`` method is hardcoded to use only
capability language — it never generates "you are a senior developer" text.
"""

from .capability_profile import (
    CapabilityProfile,
    ProfileManager,
    build_agent_instructions,
    load_profile_from_md,
    profile_dir,
)

__all__ = [
    "CapabilityProfile",
    "ProfileManager",
    "build_agent_instructions",
    "load_profile_from_md",
    "profile_dir",
]
