"""Unified CLI entry point for the GenericAgent Workbench.

Usage::

    ga run [--input PROMPT] [--task DIR] [--llm N] [--verbose]
    ga serve [--llm N] [--verbose]
    ga reflect SCRIPT [--llm N] [--verbose]

This replaces the separate ``if __name__ == '__main__'`` blocks in
``core/agentmain.py`` and ``core/openai_agentmain.py``.
"""

from __future__ import annotations

import argparse
import os
import queue
import random
import sys
import threading
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _load_classic_agent(llm_no: int = 0, verbose: bool = False):
    """Create and start a GeneraticAgent (classic backend)."""
    from core.agentmain import GeneraticAgent

    agent = GeneraticAgent()
    agent.next_llm(llm_no)
    agent.verbose = verbose
    threading.Thread(target=agent.run, daemon=True).start()
    return agent


def _load_openai_agent(llm_no: int = 0, verbose: bool = False):
    """Create and start an OpenAIOrchestratedAgent (multi-agent backend)."""
    from core.openai_agentmain import OpenAIOrchestratedAgent

    agent = OpenAIOrchestratedAgent()
    agent.next_llm(llm_no)
    agent.verbose = verbose
    threading.Thread(target=agent.run, daemon=True).start()
    return agent


def cmd_run(args: argparse.Namespace) -> None:
    """Run a single task and print streaming output."""
    agent = _load_classic_agent(args.llm_no, args.verbose)

    if args.task:
        _run_task_mode(agent, args)
    else:
        _run_interactive(agent, args)


def cmd_serve(args: argparse.Namespace) -> None:
    """Start an interactive REPL session."""
    agent = _load_classic_agent(args.llm_no, args.verbose)
    _run_interactive(agent, args)


def cmd_reflect(args: argparse.Namespace) -> None:
    """Watch a script and re-run when it changes."""
    import importlib.util

    agent = _load_classic_agent(args.llm_no, args.verbose)
    spec = importlib.util.spec_from_file_location("reflect_script", args.script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mtime = os.path.getmtime(args.script)
    print(f"[Reflect] loaded {args.script}")

    while True:
        if os.path.getmtime(args.script) != mtime:
            try:
                spec.loader.exec_module(mod)
                mtime = os.path.getmtime(args.script)
            except Exception as e:
                print(f"[Reflect] reload error: {e}")
        if hasattr(mod, "check") and mod.check():
            dq = agent.put_task(mod.check(), source="reflect")
            _drain_to_stdout(dq)
        time.sleep(1.0)


def cmd_run_openai(args: argparse.Namespace) -> None:
    """Run a task using the OpenAI multi-agent backend."""
    agent = _load_openai_agent(args.llm_no, args.verbose)

    if args.task:
        _run_task_mode_openai(agent, args)
    else:
        _run_interactive_openai(agent, args)


def cmd_serve_openai(args: argparse.Namespace) -> None:
    """Start an interactive REPL with the OpenAI multi-agent backend."""
    agent = _load_openai_agent(args.llm_no, args.verbose)
    _run_interactive_openai(agent, args)


# ── shared helpers ──────────────────────────────────────────────────────────


def _drain_to_stdout(dq: queue.Queue) -> str:
    """Drain a legacy display queue, printing streaming output to stdout."""
    full = ""
    while True:
        try:
            item = dq.get(timeout=120)
        except queue.Empty:
            break
        if "next" in item:
            delta = item["next"]
            if delta and delta != full:
                sys.stdout.write(delta[len(full) :] if delta.startswith(full) else delta)
                sys.stdout.flush()
            full = delta
        if "done" in item:
            done = item["done"]
            if done != full:
                sys.stdout.write("\n")
            print()
            return done
        if item.get("event") == "stopped":
            print("\n[stopped]")
            return item.get("next", "")
        if item.get("event") == "error":
            print(f"\n[error] {item.get('error', 'unknown')}")
            return item.get("done", item.get("next", ""))
    return full


def _run_task_mode(agent, args: argparse.Namespace) -> None:
    """Continuous file I/O task loop (classic backend)."""
    from core.ga import consume_file

    d = os.path.join(PROJECT_ROOT, "temp", args.task)
    nround: object = ""
    infile = os.path.join(d, "input.txt")
    if args.input:
        os.makedirs(d, exist_ok=True)
        import glob

        for f in glob.glob(os.path.join(d, "output*.txt")):
            os.remove(f)
        with open(infile, "w", encoding="utf-8") as f:
            f.write(args.input)

    with open(infile, encoding="utf-8") as f:
        raw = f.read()

    while True:
        dq = agent.put_task(raw, source="task")
        full = _drain_to_stdout(dq)
        outfile = os.path.join(d, f"output{nround}.txt")
        with open(outfile, "w", encoding="utf-8") as f:
            f.write(full + "\n\n[ROUND END]\n")
        consume_file(d, "_stop")
        for _ in range(300):
            time.sleep(2)
            reply = consume_file(d, "reply.txt")
            if reply:
                raw = reply
                break
        else:
            break
        nround = nround + 1 if isinstance(nround, int) else 1


def _run_interactive(agent, args: argparse.Namespace) -> None:
    """Interactive REPL (classic backend)."""
    print("GenericAgent CLI — type /help for commands, /quit to exit")
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue
        if raw == "/quit" or raw == "/exit":
            break
        dq = agent.put_task(raw, source="user")
        _drain_to_stdout(dq)


def _run_task_mode_openai(agent, args: argparse.Namespace) -> None:
    """Continuous file I/O task loop (OpenAI backend)."""
    d = os.path.join(PROJECT_ROOT, "temp", args.task)
    infile = os.path.join(d, "input.txt")
    if args.input:
        os.makedirs(d, exist_ok=True)
        with open(infile, "w", encoding="utf-8") as f:
            f.write(args.input)
    with open(infile, encoding="utf-8") as f:
        raw = f.read()
    dq = agent.put_task(raw, source="task")
    full = _drain_to_stdout(dq)
    outfile = os.path.join(d, "output.txt")
    with open(outfile, "w", encoding="utf-8") as f:
        f.write(full)
    print(f"[saved] {outfile}")


def _run_interactive_openai(agent, args: argparse.Namespace) -> None:
    """Interactive REPL (OpenAI backend)."""
    print("GenericAgent CLI (openai-agents) — type /quit to exit")
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue
        if raw == "/quit" or raw == "/exit":
            break
        dq = agent.put_task(raw, source="user")
        _drain_to_stdout(dq)


# ── main entry point ────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="ga",
        description="GenericAgent Workbench CLI",
    )
    sub = parser.add_subparsers(dest="command", title="commands")

    # ga run
    p_run = sub.add_parser("run", help="Run a single task")
    p_run.add_argument("--input", help="Prompt text (interactive if omitted)")
    p_run.add_argument("--task", metavar="DIR", help="File-based task I/O directory")
    p_run.add_argument("--llm", type=int, default=0, dest="llm_no", help="LLM key index (default 0)")
    p_run.add_argument("--verbose", action="store_true", help="Verbose output")

    # ga serve
    p_serve = sub.add_parser("serve", help="Interactive REPL")
    p_serve.add_argument("--llm", type=int, default=0, dest="llm_no", help="LLM key index")
    p_serve.add_argument("--verbose", action="store_true")

    # ga reflect
    p_refl = sub.add_parser("reflect", help="Watch a script for change-triggered tasks")
    p_refl.add_argument("script", help="Python script with check() function")
    p_refl.add_argument("--llm", type=int, default=0, dest="llm_no", help="LLM key index")
    p_refl.add_argument("--verbose", action="store_true")

    # ga run-openai
    p_ro = sub.add_parser("run-openai", help="Run task with OpenAI multi-agent backend")
    p_ro.add_argument("--input", help="Prompt text")
    p_ro.add_argument("--task", metavar="DIR", help="File-based task I/O directory")
    p_ro.add_argument("--llm", type=int, default=0, dest="llm_no", help="LLM key index")
    p_ro.add_argument("--verbose", action="store_true")

    # ga serve-openai
    p_so = sub.add_parser("serve-openai", help="REPL with OpenAI multi-agent backend")
    p_so.add_argument("--llm", type=int, default=0, dest="llm_no", help="LLM key index")
    p_so.add_argument("--verbose", action="store_true")

    ns = parser.parse_args(argv)

    if ns.command == "run":
        cmd_run(ns)
    elif ns.command == "serve":
        cmd_serve(ns)
    elif ns.command == "reflect":
        cmd_reflect(ns)
    elif ns.command == "run-openai":
        cmd_run_openai(ns)
    elif ns.command == "serve-openai":
        cmd_serve_openai(ns)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
