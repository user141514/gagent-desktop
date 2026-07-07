"""
browser-use Sub-Agent synchronous wrapper.
Runs in an isolated thread + event loop to avoid polluting ga.py's sync generator chain.
"""

import asyncio
import logging
import os
import queue
import threading

logger = logging.getLogger(__name__)


def run_browser_agent(
    task: str,
    llm_config: dict,
    max_steps: int = 20,
    headless: bool = True,
    progress_cb=None,
) -> dict:
    """Synchronous entry point. Runs browser-use Agent inside an isolated thread.

    Returns: {"success": bool, "result": str, "steps_taken": int}
    """
    result_q: queue.Queue = queue.Queue()

    def _thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            data = loop.run_until_complete(
                _async_run(task, llm_config, max_steps, headless, progress_cb)
            )
            result_q.put({"ok": True, "data": data})
        except Exception as e:
            logger.exception("browser_agent error")
            result_q.put({"ok": False, "error": str(e)})
        finally:
            loop.close()

    t = threading.Thread(target=_thread, daemon=True)
    t.start()
    t.join(timeout=300)  # 5-minute hard timeout

    if t.is_alive():
        return {"success": False, "result": "Timeout (>5 min)", "steps_taken": 0}

    r = result_q.get_nowait()
    if r["ok"]:
        result_text = r["data"].get("result")
        if not result_text:
            return {
                "success": False,
                "result": "browser_agent completed without a final result",
                "steps_taken": r["data"].get("steps_taken", 0),
            }
        return {"success": True, "result": result_text, "steps_taken": r["data"]["steps_taken"]}
    return {"success": False, "result": r["error"], "steps_taken": 0}


async def _async_run(task, llm_config, max_steps, headless, progress_cb):
    # Soft import: won't crash when browser-use is not installed
    try:
        from browser_use import Agent
        from browser_use.browser import BrowserSession, BrowserProfile
    except ImportError as e:
        raise RuntimeError(
            f"browser-use is not installed: {e}. "
            f"Run: pip install browser-use && playwright install chromium"
        ) from e

    llm = _build_llm(llm_config)
    profile = BrowserProfile(headless=headless)
    browser = BrowserSession(browser_profile=profile)

    agent = Agent(task=task, llm=llm, browser=browser, max_steps=max_steps)

    # Progress callback (optional)
    if progress_cb and hasattr(agent, "on"):
        @agent.on("step")
        def _on_step(step_info):
            progress_cb(f"Step {step_info.step_number}: {step_info.action}")

    history = await agent.run()

    # final_result() exists in 0.12.x; fall back to str(history)
    result_text = (
        history.final_result()
        if hasattr(history, "final_result") and callable(history.final_result)
        else str(history)
    )
    steps_taken = (
        len(history.action_results())
        if hasattr(history, "action_results")
        else 0
    )
    return {"result": result_text, "steps_taken": steps_taken}


def _build_llm(cfg: dict):
    """Build a browser-use-compatible LLM object from llm_config."""
    provider = cfg.get("provider", "openai")
    model = _clean_model_name(cfg.get("model", "gpt-4o"))
    base_url = cfg.get("base_url") or None
    api_key = cfg.get("api_key") or None  # None → let browser-use read env var

    if provider == "deepseek" or "deepseek" in str(model).lower() or "deepseek" in str(base_url).lower():
        api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is required for browser_agent DeepSeek provider")
        from browser_use.llm.deepseek.chat import ChatDeepSeek

        return ChatDeepSeek(
            model=_deepseek_browser_model(model),
            api_key=api_key,
            base_url=_deepseek_base_url(base_url),
        )

    if provider == "anthropic":
        if not api_key and not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is required for browser_agent Anthropic provider")
        from browser_use.llm.anthropic.chat import ChatAnthropic

        return ChatAnthropic(model=model, api_key=api_key, base_url=base_url)
    # Default: openai (compatible with gpt-4o, gpt-4.1, etc.)
    if not api_key and not (os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_ADMIN_KEY")):
        raise RuntimeError("OPENAI_API_KEY or OPENAI_ADMIN_KEY is required for browser_agent OpenAI provider")
    from browser_use.llm.openai.chat import ChatOpenAI

    return ChatOpenAI(model=model, api_key=api_key, base_url=base_url)


def _clean_model_name(model: str | None) -> str:
    text = str(model or "").strip()
    return text.split("[", 1)[0] if "[" in text else text


def _deepseek_base_url(base_url: str | None) -> str | None:
    if not base_url:
        return None
    text = str(base_url).rstrip("/")
    if text.endswith("/anthropic"):
        return text[: -len("/anthropic")] + "/v1"
    return text


def _deepseek_browser_model(model: str) -> str:
    text = str(model or "").strip()
    if not text or "v4-pro" in text.lower():
        return "deepseek-chat"
    return text
