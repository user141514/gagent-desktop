import os
import sys

sys.path.insert(0, "backend")

from core import ga
from core.agent_loop import exhaust


class DummyParent:
    verbose = False


def main():
    old_mode = os.environ.get("GA_OPENAI_DISTILLATION")
    os.environ["GA_OPENAI_DISTILLATION"] = "preview"
    try:
        handler = ga.GenericAgentHandler(DummyParent(), cwd=os.path.join(os.getcwd(), "backend", "temp"))
        assert hasattr(handler, "do_capture_experience")
        outcome = exhaust(handler.do_capture_experience({
            "summary": "PowerShell Invoke-WebRequest succeeded for web search when Python HTTP paths failed.",
            "task": "Prefer PowerShell web transport on Windows.",
            "questions": ["How should web_search recover from Python HTTP failures?"],
        }, ""))
        assert outcome.data["status"] == "success", outcome.data
        assert outcome.data["mode"] == "preview", outcome.data
        assert outcome.data["path"], outcome.data
        assert os.path.exists(outcome.data["path"]), outcome.data
        os.remove(outcome.data["path"])
    finally:
        if old_mode is None:
            os.environ.pop("GA_OPENAI_DISTILLATION", None)
        else:
            os.environ["GA_OPENAI_DISTILLATION"] = old_mode


if __name__ == "__main__":
    main()
    print("[test-capture-experience] ok")
