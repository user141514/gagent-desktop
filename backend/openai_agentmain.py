"""Compatibility wrapper for the OpenAI Agents runtime."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("core.openai_agentmain", run_name="__main__")
else:
    from core.openai_agentmain import *  # noqa: F401,F403
