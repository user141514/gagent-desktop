"""Compatibility wrapper for the classic GenericAgent runtime."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("core.agentmain", run_name="__main__")
else:
    from core.agentmain import *  # noqa: F401,F403
