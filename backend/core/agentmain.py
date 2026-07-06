import os, sys, threading, queue, time, json, re, random, locale, uuid
from contextlib import nullcontext
from pathlib import Path

os.environ.setdefault('GA_LANG', 'zh' if any(k in (locale.getlocale()[0] or '').lower() for k in ('zh', 'chinese')) else 'en')
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
elif hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(errors='replace')
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
elif hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(errors='replace')

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(PROJECT_ROOT)

from .llmcore import LLMSession, ToolClient, ClaudeSession, MixinSession, NativeToolClient, NativeClaudeSession, NativeOAISession
from .agent_loop import agent_runner_loop
from .ga import GenericAgentHandler, consume_file, file_read, format_error, get_global_memory, smart_format
from .runtime import (
    RuntimeProfiler,
    build_profile_path,
    detect_read_shortcut,
    direct_answer_enabled,
    early_stop_enabled,
    format_profile_summary,
    profiling_enabled,
    read_shortcut_enabled,
    try_direct_answer_from_tool_result,
)
from .tools import ToolSchemaSelector, load_runtime_tool_schema, slim_tools_enabled
from .prompts import build_agent_behavior_kernel
from core.protocol.agent import AgentBackend
from core.protocol.input import AgentInput
from frontends.file_processor import strip_attachment_prompt


script_dir = PROJECT_ROOT


def load_tool_schema(suffix='', llm_name=None):
    global TOOLS_SCHEMA, TOOL_SCHEMA_REPORT
    preferred_lang = None
    if suffix == '_cn':
        preferred_lang = 'zh'
    elif suffix == '_en':
        preferred_lang = 'en'
    TOOLS_SCHEMA, TOOL_SCHEMA_REPORT = load_runtime_tool_schema(
        preferred_lang=preferred_lang,
        llm_name=llm_name,
    )
    if TOOL_SCHEMA_REPORT.get('fallback_to_english'):
        print(
            "[tool-schema] localized schema required English fallback: "
            f"locale={TOOL_SCHEMA_REPORT.get('locale')} "
            f"missing_tools={len(TOOL_SCHEMA_REPORT.get('missing_tools', []))} "
            f"missing_tool_descriptions={len(TOOL_SCHEMA_REPORT.get('missing_tool_descriptions', []))} "
            f"missing_param_descriptions={len(TOOL_SCHEMA_REPORT.get('missing_param_descriptions', []))}"
        )


load_tool_schema()

lang_suffix = '_en' if os.environ.get('GA_LANG', '') == 'en' else ''
mem_dir = os.path.join(script_dir, 'memory')
if not os.path.exists(mem_dir):
    os.makedirs(mem_dir)
mem_txt = os.path.join(mem_dir, 'global_mem.txt')
if not os.path.exists(mem_txt):
    open(mem_txt, 'w', encoding='utf-8').write('# [Global Memory - L2]\n')
mem_insight = os.path.join(mem_dir, 'global_mem_insight.txt')
if not os.path.exists(mem_insight):
    t = os.path.join(script_dir, f'assets/global_mem_insight_template{lang_suffix}.txt')
    open(mem_insight, 'w', encoding='utf-8').write(open(t, encoding='utf-8').read() if os.path.exists(t) else '')
cdp_cfg = os.path.join(script_dir, 'assets/tmwd_cdp_bridge/config.js')
if not os.path.exists(cdp_cfg):
    try:
        os.makedirs(os.path.dirname(cdp_cfg), exist_ok=True)
        open(cdp_cfg, 'w', encoding='utf-8').write(f"const TID = '__ljq_{hex(random.randint(0, 99999999))[2:8]}';")
    except Exception as e:
        print(f'[WARN] CDP config init failed: {e} 鈥?advanced web features (tmwebdriver) will be unavailable.')


# Cached system prompt to avoid disk I/O every turn. TTL = 60s.
_sys_prompt_cache: str | None = None
_sys_prompt_cache_time: float = 0.0


def get_system_prompt():
    global _sys_prompt_cache, _sys_prompt_cache_time
    now = time.time()
    if _sys_prompt_cache is not None and (now - _sys_prompt_cache_time) < 60:
        return _sys_prompt_cache
    with open(os.path.join(script_dir, f'assets/sys_prompt{lang_suffix}.txt'), 'r', encoding='utf-8') as f:
        prompt = f.read()
    prompt += f"\nToday: {time.strftime('%Y-%m-%d %a')}\n"
    prompt += build_agent_behavior_kernel()
    prompt += get_global_memory()
    _sys_prompt_cache = prompt
    _sys_prompt_cache_time = now
    return prompt


def _profile_status_label(status):
    return status if status in {'success', 'error', 'aborted'} else 'success'


def _tool_name(tool):
    fn = tool.get("function", {}) if isinstance(tool, dict) else {}
    return str(fn.get("name") or tool.get("name") or "").strip() if isinstance(tool, dict) else ""


def _tool_schema_chars(tools):
    return len(json.dumps(tools or [], ensure_ascii=False, separators=(",", ":")))


# DEPRECATED: phase=M6, replaced_by=core.context.recent_turns.is_ambiguous_followup()
_AMBIGUOUS_PATTERNS = [
    "...", "。。。", "…", "继续", "接着", "然后呢", "然后",
    "上一个", "刚才那个", "你刚才说的", "按你说的做", "照做",
    "怎么改回去", "怎么撤销", "如何回滚", "undo", "rollback",
    "继续执行", "继续做", "还有呢", "接着说",
]


def _is_ambiguous_followup(user_query: str) -> bool:
    """Detect queries that need recent context to be understood.

    M6: Delegates to the canonical is_ambiguous_followup() in
    core.context.recent_turns when available. Falls back to legacy
    pattern matching on import failure.
    """
    try:
        from core.context.recent_turns import is_ambiguous_followup as _canonical
        return _canonical(user_query)
    except Exception:
        pass
    # Legacy fallback
    if not user_query or not user_query.strip():
        return True
    s = user_query.strip().lower()
    return any(s == p or s.startswith(p) for p in _AMBIGUOUS_PATTERNS)


def _build_recent_context(history: list[str], current_query: str, max_lines: int = 12, max_chars: int = 3000) -> str:
    """Build a [RECENT CONTEXT] block from self.history.

    M6: Uses the canonical build_recent_conversation_block() from
    core.context.recent_turns when history is available. Falls back
    to legacy format on import failure or when history is empty.
    """
    ambiguous = _is_ambiguous_followup(current_query)

    # ── Empty history: use canonical clarification note ──
    if not history:
        if ambiguous:
            try:
                from core.context.recent_turns import build_clarification_request as _canonical_clarify
                return _canonical_clarify()
            except Exception:
                pass
            return (
                "### [RECENT CONTEXT]\n"
                "No recent conversation history is available. "
                "The user's message is ambiguous (e.g. a continuation like '...'). "
                "Do NOT ask the user to clarify. Instead, make minimal, reversible "
                "assumptions based on common context (project state, recent edits, "
                "git status) and proceed. State your assumptions briefly, then act.\n"
                "[/RECENT CONTEXT]"
            )
        return ""

    # ── Convert Classic history format to input_items ──
    input_items = _history_to_input_items(history, max_lines=max_lines)

    # ── Use canonical format when available ──
    try:
        from core.context.recent_turns import build_recent_conversation_block as _canonical_block
        block = _canonical_block(input_items, max_turns=max(min(max_lines, 5), 1), max_chars=max_chars)
        if block:
            prefix = ""
            if ambiguous:
                prefix = (
                    "The user's current message is ambiguous (e.g. '...', '继续', '怎么改回去'). "
                    "Use the context below to understand what the user is referring to. "
                    "If context is insufficient, make minimal assumptions and proceed — "
                    "do NOT ask the user to repeat themselves.\n\n"
                )
            return prefix + block
    except Exception:
        pass

    # ── Legacy fallback ──
    recent_lines = history[-max_lines:]
    parts = ["### [RECENT CONTEXT]"]
    if ambiguous:
        parts.append(
            "The user's current message is ambiguous (e.g. '...', '继续', '怎么改回去'). "
            "Use the context below to understand what the user is referring to. "
            "If context is insufficient, make minimal assumptions and proceed — "
            "do NOT ask the user to repeat themselves."
        )
    parts.append("")

    budget = max_chars - len("\n".join(parts))
    included = []
    for line in reversed(recent_lines):
        if budget - len(line) < 100 and included:
            break
        included.append(line)
        budget -= len(line) + 1
    included.reverse()

    for line in included:
        parts.append(line)

    parts.append("[/RECENT CONTEXT]")
    return "\n".join(parts)


def _history_to_input_items(history: list[str], max_lines: int = 12) -> list[dict[str, str]]:
    """Convert Classic history format to OpenAI input_items format.

    Classic format:
        [USER]: query text
        [Agent] summary text

    OpenAI format:
        {"role": "user", "content": "query text"}
        {"role": "assistant", "content": "summary text"}
    """
    items: list[dict[str, str]] = []
    for line in history[-max_lines:]:
        line = str(line or "").strip()
        if line.startswith("[USER]:"):
            items.append({"role": "user", "content": line[len("[USER]:"):].strip()})
        elif line.startswith("[Agent]"):
            items.append({"role": "assistant", "content": line[len("[Agent]"):].strip()})
        elif line.startswith("[USER]:") or line.startswith("[Agent]"):
            # Already in correct format, skip unrecognized prefixes
            pass
        else:
            # Unrecognized format — treat as system info
            if line:
                items.append({"role": "user", "content": line})
    return items


def _strip_attachment_context_from_content(content):
    if isinstance(content, str):
        return strip_attachment_prompt(content)
    if isinstance(content, list):
        cleaned = []
        for block in content:
            if isinstance(block, dict):
                block = dict(block)
                if isinstance(block.get("text"), str):
                    block["text"] = strip_attachment_prompt(block["text"])
                if isinstance(block.get("content"), str):
                    block["content"] = strip_attachment_prompt(block["content"])
            cleaned.append(block)
        return cleaned
    return content


def _scrub_uploaded_file_context_from_backend(backend) -> None:
    """Remove uploaded attachment bodies from provider history after a run."""
    history = getattr(backend, "history", None)
    if not isinstance(history, list):
        return
    for idx, item in enumerate(list(history)):
        if isinstance(item, dict):
            item["content"] = _strip_attachment_context_from_content(item.get("content"))
        elif isinstance(item, str):
            history[idx] = strip_attachment_prompt(item)


class GeneraticAgent(AgentBackend):
    def __init__(self):
        script_dir = PROJECT_ROOT
        os.makedirs(os.path.join(script_dir, 'temp'), exist_ok=True)
        from .llmcore import mykeys

        llm_sessions = []
        for k, cfg in mykeys.items():
            if not isinstance(cfg, dict):
                continue
            # Skip known non-key entries (proxy, templates, metadata)
            if k in ('proxy', 'proxies', 'template', 'TEMPLATE', 'mykey_template'):
                continue
            try:
                if 'native' in k and 'claude' in k:
                    llm_sessions += [NativeToolClient(NativeClaudeSession(cfg=cfg))]
                elif 'native' in k and 'oai' in k:
                    llm_sessions += [NativeToolClient(NativeOAISession(cfg=cfg))]
                elif 'claude' in k:
                    llm_sessions += [ToolClient(ClaudeSession(cfg=cfg))]
                elif 'oai' in k:
                    llm_sessions += [ToolClient(LLMSession(cfg=cfg))]
                elif 'mixin' in k:
                    llm_sessions += [{'mixin_cfg': cfg}]
            except Exception:
                pass
        for i, s in enumerate(llm_sessions):
            if isinstance(s, dict) and 'mixin_cfg' in s:
                try:
                    mixin = MixinSession(llm_sessions, s['mixin_cfg'])
                    if isinstance(mixin._sessions[0], (NativeClaudeSession, NativeOAISession)):
                        llm_sessions[i] = NativeToolClient(mixin)
                    else:
                        llm_sessions[i] = ToolClient(mixin)
                except Exception as e:
                    print(f'[WARN] Failed to init MixinSession with cfg {s["mixin_cfg"]}: {e}')
        self.llmclients = llm_sessions
        self.lock = threading.Lock()
        self.task_dir = None
        self.history = []
        self.task_queue = queue.Queue()
        self._running = False
        self.stop_sig = False
        self._stop_event = None
        self.llm_no = 0
        self.inc_out = False
        self.handler = None
        self.verbose = True
        self.llmclient = self.llmclients[self.llm_no]
        self.active_profiler = None
        self._profile_run_id = None
        self._profile_status = 'success'
        self._current_user_input = ""
        self._last_read_shortcut = None
        self._last_direct_answer = None
        self._last_early_stop = None
        self._tool_selector = ToolSchemaSelector()
        self._available_tool_count = len(TOOLS_SCHEMA)
        self._selected_tool_names = [_tool_name(tool) for tool in TOOLS_SCHEMA]
        self._selected_tools_schema_chars = _tool_schema_chars(TOOLS_SCHEMA)
        self._active_display_queue = None
        self._active_source = None

    def switch_to_key(self, n: int) -> str:
        """Switch directly to a specific LLM key index. Returns the new model name."""
        if not self.llmclients or n < 0 or n >= len(self.llmclients):
            return self.get_llm_name()
        lastc = self.llmclient
        self.llm_no = n
        self.llmclient = self.llmclients[self.llm_no]
        # ── Provider switch: canonicalize + rebuild to avoid format pollution ──
        try:
            from .llmcore import _canonicalize_history, rebuild_history_for_session
            old_backend = getattr(lastc, 'backend', None)
            new_backend = getattr(self.llmclient, 'backend', None)
            same_cls = (type(old_backend) is type(new_backend)) if (old_backend and new_backend) else False
            if same_cls:
                new_backend.history = list(getattr(old_backend, 'history', []))
            elif old_backend and new_backend:
                canonical = _canonicalize_history(getattr(old_backend, 'history', []))
                new_backend.history = rebuild_history_for_session(canonical, new_backend)
        except Exception as e:
            print(f"[SWITCH] Canonical rebuild failed ({e}), falling back to raw copy")
            self.llmclient.backend.history = getattr(lastc.backend, 'history', [])
        self.llmclient.last_tools = ''
        name = self.get_llm_name()
        load_tool_schema(llm_name=name)
        return self.get_llm_name()

    def next_llm(self, n=-1):
        self.switch_to_key(((self.llm_no + 1) if n < 0 else n) % len(self.llmclients))

    def list_llms(self):
        return [(i, self.get_llm_name(b), i == self.llm_no) for i, b in enumerate(self.llmclients)]

    def get_llm_name(self, b=None):
        b = self.llmclient if b is None else b
        return f"{type(b.backend).__name__}/{b.backend.name}" if not isinstance(b, dict) else "BADCONFIG_MIXIN"

    def get_key_labels(self) -> list[str]:
        """Return display labels for all configured LLMs (for UI model switcher)."""
        labels = []
        for i, b in enumerate(self.llmclients):
            name = self.get_llm_name(b)
            prefix = "Key1" if i == 0 else f"Key{i + 1}"
            active = " *" if i == self.llm_no else ""
            labels.append(f"{prefix}: {name}{active}")
        return labels

    def _select_tools_for_task(self, query):
        available_tools = list(TOOLS_SCHEMA)
        self._available_tool_count = len(available_tools)
        if slim_tools_enabled():
            selected = self._tool_selector.select_tools_for_task(query, available_tools, mode="classic")
            if selected:
                available_tools = selected
        self._selected_tool_names = [_tool_name(tool) for tool in available_tools if _tool_name(tool)]
        self._selected_tools_schema_chars = _tool_schema_chars(available_tools)
        return available_tools

    def _extract_shortcut_user_query(self, raw_query):
        match = re.search(
            r"Original user request:\s*\n(.*?)\n\s*Execution plan or corrective follow-up:\s*\n",
            str(raw_query or ""),
            flags=re.DOTALL | re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
        return str(raw_query or "").strip()

    def _build_shortcut_file_result(self, target_file, extraction_type):
        extraction = str(extraction_type or "")
        if extraction.startswith("readme"):
            count = 50
        elif extraction.startswith("explicit_file_view"):
            count = 80
            _count_match = re.search(r":(\d+)$", extraction)
            if _count_match:
                try:
                    count = max(1, min(int(_count_match.group(1)), 200))
                except (TypeError, ValueError):
                    count = 80
        else:
            count = 5
        result = file_read(str(target_file), start=1, keyword=None, count=count, show_linenos=True)
        if not str(result).startswith("Error:"):
            result = "由于设置了show_linenos，以下返回信息为：(行号|)内容 。\n" + str(result)
        if " ... [TRUNCATED]" in str(result):
            result += "\n\n（某些行被截断，如需完整内容可改用 code_run 读取）"
        return smart_format(str(result), max_str_len=20000, omit_str="\n\n[omitted long content]\n\n")

    def _try_read_shortcut(self, raw_query):
        if not read_shortcut_enabled():
            return None
        shortcut_query = self._extract_shortcut_user_query(raw_query)
        decision = detect_read_shortcut(shortcut_query, project_root=PROJECT_ROOT)
        if not decision.should_shortcut or not decision.target_file:
            return None
        profiler = self.active_profiler
        try:
            io_span = profiler.span(
                "read_shortcut_file_read",
                kind="io",
                metadata={"target_file": decision.target_file, "extraction_type": decision.extraction_type},
            ) if profiler is not None else nullcontext()
            with io_span:
                read_result = self._build_shortcut_file_result(decision.target_file, decision.extraction_type)
            answer_decision = try_direct_answer_from_tool_result(
                shortcut_query,
                [{"content": read_result}],
                metadata={
                    "tool_names": ["file_read"],
                    "extraction_type": decision.extraction_type,
                    "line_count": decision.line_count,
                    "target_label": os.path.relpath(str(decision.target_file), PROJECT_ROOT).replace("\\", "/"),
                },
            )
        except Exception as exc:
            print(f"[READ_SHORTCUT] failed: {type(exc).__name__}: {exc}")
            return None
        if not answer_decision.should_answer or not answer_decision.answer:
            return None

        event_payload = {
            "target_file": decision.target_file,
            "extraction_type": decision.extraction_type,
            "reason": decision.reason,
            "confidence": decision.confidence,
            "signals": decision.signals,
            "direct_answer_reason": answer_decision.reason,
            "direct_answer_confidence": answer_decision.confidence,
        }
        if profiler is not None:
            try:
                profiler.record_event("classic_executor_read_shortcut", kind="agent", metadata=event_payload)
            except Exception:
                pass
        self._last_read_shortcut = dict(event_payload)
        print(
            f"[READ_SHORTCUT] target={decision.target_file} "
            f"extraction={decision.extraction_type} confidence={decision.confidence}"
        )
        rel_target = os.path.relpath(str(decision.target_file), PROJECT_ROOT)
        output = f"[Info] Read shortcut matched: {rel_target}\n{answer_decision.answer.rstrip()}\n"
        history_summary = smart_format(answer_decision.answer.replace("\n", " "), max_str_len=100)
        return {
            "output": output,
            "history_summary": history_summary,
            "final_answer_ready": True,
            "final_answer_text": answer_decision.answer.rstrip(),
            "shortcut_type": "read_shortcut",
            "skip_planner_followup": True,
            "shortcut_reason": decision.reason,
            "shortcut_confidence": decision.confidence,
            "tool_error": False,
        }

    # ── AgentBackend protocol (Phase 5) ─────────────────────────────────

    @property
    def is_running(self) -> bool:
        """Whether a task is currently being processed (AgentBackend protocol)."""
        return self._running

    def submit(self, task):
        """Submit a task via the AgentBackend protocol.

        Returns an AgentOutputChannel for consuming streaming output.
        This path wraps the raw output queue with a bridge for typed consumers.
        """
        from core.protocol.channel import QueueOutputChannel

        display_queue = queue.Queue()
        stop_event = threading.Event()
        self.task_queue.put({
            "query": task.query, "source": task.source,
            "images": task.images or [], "output": display_queue,
            "run_id": task.run_id, "stop_event": stop_event,
        })
        return QueueOutputChannel.from_legacy_queue(display_queue)

    def put_task(self, query, source="user", images=None, run_id=None):
        """Submit a task (legacy API).

        Returns a raw ``queue.Queue`` for backward compatibility.
        Prefer ``submit(AgentInput(...))`` for new code.
        """
        display_queue = queue.Queue()
        self.task_queue.put({
            "query": query, "source": source,
            "images": images or [], "output": display_queue,
            "run_id": run_id, "stop_event": None,
        })
        return display_queue

    def abort(self):
        if not self._running:
            return
        print('Abort current task...')
        self.stop_sig = True
        if self._stop_event is not None:
            self._stop_event.set()
        if self.handler is not None:
            self.handler.code_stop_signal.append(1)

    def _emit_status_event(self, payload):
        q = self._active_display_queue
        if q is None or not isinstance(payload, dict):
            return
        item = dict(payload)
        item.setdefault("source", self._active_source or "user")
        item.setdefault("task_id", self._profile_run_id)
        try:
            q.put(item)
        except Exception:
            pass

    # i know it is dangerous, but raw_query is dangerous enough it doesn't enlarge
    def _handle_slash_cmd(self, raw_query, display_queue):
        if not raw_query.startswith('/'):
            return raw_query
        _sm = re.match(r'/session\.(\w+)=(.*)', raw_query.strip())
        if _sm:
            k, v = _sm.group(1), _sm.group(2)
            vfile = os.path.join(script_dir, 'temp', v)
            if os.path.isfile(vfile):
                v = open(vfile, encoding='utf-8').read().strip()
            try:
                v = json.loads(v)
            except (json.JSONDecodeError, ValueError):
                pass
            setattr(self.llmclient.backend, k, v)
            display_queue.put({'done': smart_format(f"鉁?session.{k} = {repr(v)}", max_str_len=500), 'source': 'system'})
            return None
        if raw_query.strip() == '/resume':
            return '绠€鍗曠湅鐪媘odel_responses涓殑鏈€杩戝嚑娆″璇濈粨灏鹃儴鍒?闄や簡鏈)锛屽垎鍒畝鍗曟€荤粨涓€涓嬭鎴戦€夋嫨锛岀劧鍚庝綘绠€鍗曢槄璇讳簡瑙ｆ儏鍐靛悗浣滀负鎴戜滑鎺ヤ笅鏉ヨ亰澶╃殑鍩虹'
        return raw_query

    def run(self):
        while True:
            task = self.task_queue.get()
            raw_query = task["query"]
            source = task["source"]
            display_queue = task["output"]
            run_id = task.get("run_id") or uuid.uuid4().hex
            stop_event = task.get("stop_event")
            self._stop_event = stop_event
            raw_query = self._handle_slash_cmd(raw_query, display_queue)
            if raw_query is None:
                self.task_queue.task_done()
                continue

            self._running = True
            self._profile_status = 'success'
            self._profile_run_id = run_id
            self._active_display_queue = display_queue
            self._active_source = source
            self._current_user_input = raw_query
            self._last_read_shortcut = None
            self._last_direct_answer = None
            self._last_early_stop = None
            self.active_profiler = RuntimeProfiler() if profiling_enabled() else None
            if self.active_profiler is not None:
                self.active_profiler.start_run(
                    run_id=run_id,
                    name='classic_agent_request',
                    metadata={'backend': 'classic', 'source': source},
                )

            history_query = strip_attachment_prompt(raw_query)
            rquery = smart_format(history_query.replace('\n', ' '), max_str_len=200)
            self.history.append(f"[USER]: {rquery}")

            handler = None
            full_resp = ""
            turn_value = 1
            # ── RuntimeHost: session recording (Phase 3) ──
            _runtime_host = None
            _runtime_mapper = None
            try:
                from core.runtime.host import RuntimeHost
                from core.runtime.protocol_bridge import RuntimeEventMapper
                _runtime_host = RuntimeHost(
                    project_root=PROJECT_ROOT,
                    agent_name="classic_agent",
                )
                _runtime_host.start_session(user_intent=raw_query, source=source)
                _runtime_mapper = RuntimeEventMapper(_runtime_host)
            except Exception:
                pass  # runtime unavailable — continue without session recording
            try:
                shortcut_check_span = self.active_profiler.span('read_shortcut_check', kind='agent', metadata={'source': source}) if self.active_profiler is not None else nullcontext()
                with shortcut_check_span:
                    shortcut_payload = self._try_read_shortcut(raw_query)
                if shortcut_payload is not None:
                    full_resp = shortcut_payload["output"]
                    turn_value = 1
                    self.history.append(f"[Agent] {shortcut_payload['history_summary']}")
                    display_queue.put(
                        {
                            'done': full_resp,
                            'source': source,
                            'turn': turn_value,
                            'task_id': run_id,
                            'final_answer_ready': bool(shortcut_payload.get('final_answer_ready')),
                            'final_answer_text': shortcut_payload.get('final_answer_text') or full_resp,
                            'shortcut_type': shortcut_payload.get('shortcut_type'),
                            'skip_planner_followup': bool(shortcut_payload.get('skip_planner_followup')),
                            'shortcut_reason': shortcut_payload.get('shortcut_reason'),
                            'shortcut_confidence': shortcut_payload.get('shortcut_confidence'),
                            'tool_error': bool(shortcut_payload.get('tool_error')),
                        }
                    )
                    continue

                memory_span = self.active_profiler.span('memory_injection', kind='memory', metadata={'source': source}) if self.active_profiler is not None else nullcontext()
                with memory_span:
                    sys_prompt = get_system_prompt() + getattr(self.llmclient.backend, 'extra_sys_prompt', '')

                script_dir = PROJECT_ROOT
                setup_span = self.active_profiler.span('agent_setup', kind='agent', metadata={'source': source}) if self.active_profiler is not None else nullcontext()
                with setup_span:
                    selected_tools = self._select_tools_for_task(raw_query)
                    print(
                        f"[ToolSchema] slim={int(slim_tools_enabled())} "
                        f"read_shortcut={int(read_shortcut_enabled())} "
                        f"direct_answer={int(direct_answer_enabled())} "
                        f"early_stop={int(early_stop_enabled())} "
                        f"selected={len(selected_tools)}/{self._available_tool_count} "
                        f"chars={self._selected_tools_schema_chars} "
                        f"names={','.join(self._selected_tool_names)}"
                    )
                    handler = GenericAgentHandler(self, self.history, os.path.join(script_dir, 'temp'))
                    if self.handler and 'key_info' in self.handler.working:
                        ki = re.sub(r'\n\[SYSTEM\] 这是第.*?工作记忆[。\n]*', '', self.handler.working['key_info'])
                        handler.working['key_info'] = ki
                        handler.working['passed_sessions'] = ps = self.handler.working.get('passed_sessions', 0) + 1
                        if ps > 0:
                            handler.working['key_info'] += f'\n[SYSTEM] 姝や负 {ps} 涓璇濆墠璁剧疆鐨刱ey_info锛岃嫢宸插湪鏂颁换鍔★紝鍏堟洿鏂版垨娓呴櫎宸ヤ綔璁板繂銆俓n'
                            handler.working['key_info'] = ki + f'\n[SYSTEM] 这是第 {ps} 个对话前设置的 key_info；如果已经进入新任务，先更新或清除工作记忆。\n'
                    self.handler = handler
                    user_input = raw_query
                    # ── Inject recent conversation history for ALL sources ──
                    if os.environ.get("GENERIC_AGENT_RECENT_TURNS", "1") == "1":
                        recent = _build_recent_context(self.history, history_query)
                        if recent:
                            user_input = recent + "\n\n" + user_input
                    try:
                        from core.quality import (
                            build_research_code_priority_context,
                            build_state_driven_thinking_context,
                            research_code_priority_enabled,
                        )
                        state_context = build_state_driven_thinking_context(
                            history_query,
                            route_target=None,
                            max_chars=2600,
                        )
                        state_block = str(state_context.get("block") or "").strip()
                        if state_block:
                            user_input = state_block + "\n\n" + user_input
                        if research_code_priority_enabled():
                            priority_context = build_research_code_priority_context(
                                history_query,
                                route_target=None,
                                max_chars=1000,
                            )
                            priority_block = str(priority_context.get("block") or "").strip()
                            if priority_block:
                                user_input = priority_block + "\n\n" + user_input
                    except Exception:
                        pass
                    if source == 'feishu' and len(self.history) > 1:
                        user_input = handler._get_anchor_prompt() + f"\n\n### 鐢ㄦ埛褰撳墠娑堟伅\n{raw_query}"
                    initial_user_content = None
                    # Compute turn gap from env (moved here from agent_loop.py)
                    _turn_gap = 0.0
                    _gap_raw = os.environ.get("GENERIC_AGENT_FRONTEND_TURN_GAP_MS", "").strip()
                    if _gap_raw:
                        try:
                            _gap_ms = float(_gap_raw)
                            if _gap_ms > 0:
                                _turn_gap = _gap_ms / 1000.0
                        except (ValueError, TypeError):
                            pass
                    gen = agent_runner_loop(
                        self.llmclient,
                        sys_prompt,
                        user_input,
                        handler,
                        selected_tools,
                        max_turns=80,
                        verbose=self.verbose,
                        initial_user_content=initial_user_content,
                        stop_event=stop_event,
                        runtime_mapper=_runtime_mapper,
                        turn_gap=_turn_gap,
                    )

                stream_span = self.active_profiler.span('stream_output', kind='frontend', metadata={'source': source}) if self.active_profiler is not None else nullcontext()
                with stream_span:
                    last_pos = 0
                    prev_turn = 0
                    for chunk in gen:
                        if consume_file(self.task_dir, '_stop'):
                            self.abort()
                        if self.stop_sig or (stop_event and stop_event.is_set()):
                            break
                        full_resp += chunk
                        turn_value = max(1, int(getattr(handler, 'current_turn', 0) or 0))
                        # emit turn_start/turn_end events when turn changes
                        if turn_value != prev_turn:
                            if prev_turn > 0:
                                display_queue.put({'event': 'turn_end', 'turn': prev_turn, 'source': source, 'task_id': run_id})
                            display_queue.put({'event': 'turn_start', 'turn': turn_value, 'source': source, 'task_id': run_id})
                            prev_turn = turn_value
                        if len(full_resp) - last_pos > 50 or 'LLM Running' in chunk:
                            delta_text = full_resp[last_pos:] if self.inc_out else full_resp
                            display_queue.put({'event': 'turn_delta', 'next': delta_text, 'source': source, 'turn': turn_value, 'task_id': run_id})
                            display_queue.put({'next': delta_text, 'source': source, 'turn': turn_value, 'task_id': run_id})
                            last_pos = len(full_resp)
                    turn_value = max(1, int(getattr(handler, 'current_turn', 0) or 0))
                    # Put stopped marker if aborted
                    if self.stop_sig or (stop_event and stop_event.is_set()):
                        full_resp += '\n\n[已停止输出]\n'
                        display_queue.put({'event': 'stopped', 'next': full_resp, 'source': source, 'turn': turn_value, 'task_id': run_id})
                    if prev_turn > 0 and turn_value == prev_turn:
                        display_queue.put({'event': 'turn_end', 'turn': turn_value, 'source': source, 'task_id': run_id})
                    if self.inc_out and last_pos < len(full_resp):
                        remaining = full_resp[last_pos:]
                        display_queue.put({'event': 'turn_delta', 'next': remaining, 'source': source, 'turn': turn_value, 'task_id': run_id})
                        display_queue.put({'next': remaining, 'source': source, 'turn': turn_value, 'task_id': run_id})

                if '</summary>' in full_resp:
                    full_resp = full_resp.replace('</summary>', '</summary>\n\n')
                if '</file_content>' in full_resp:
                    full_resp = re.sub(r'<file_content>\s*(.*?)\s*</file_content>', r'\n````\n<file_content>\n\1\n</file_content>\n````', full_resp, flags=re.DOTALL)
                execution_state = {}
                export_execution_state = getattr(handler, '_export_execution_state', None)
                if callable(export_execution_state):
                    try:
                        execution_state = export_execution_state()
                    except Exception:
                        execution_state = {}
                display_queue.put({'event': 'final', 'done': full_resp, 'source': source, 'turn': turn_value, 'task_id': run_id, 'execution_state': execution_state})
                display_queue.put({'done': full_resp, 'source': source, 'turn': turn_value, 'task_id': run_id, 'execution_state': execution_state})
                self.history = handler.history_info
            except Exception as e:
                print(f"Backend Error: {format_error(e)}")
                self._profile_status = 'error'
                turn_value = max(1, int(getattr(handler, 'current_turn', 0) or 0)) if handler is not None else 1
                error_msg = full_resp + f'\n```\n{format_error(e)}\n```' if full_resp else f'```\n{format_error(e)}\n```'
                display_queue.put({'event': 'error', 'error': str(e), 'source': source, 'turn': turn_value, 'task_id': run_id})
                display_queue.put({'done': error_msg, 'source': source, 'turn': turn_value, 'task_id': run_id})
                # ── Runtime: record error ──
                if _runtime_mapper is not None:
                    try:
                        _runtime_mapper.on_error(str(e))
                    except Exception:
                        pass
            finally:
                if self.stop_sig:
                    print('User aborted the task.')
                    self._profile_status = 'aborted'
                    if _runtime_mapper is not None:
                        try:
                            _runtime_mapper.on_stop_requested()
                        except Exception:
                            pass
                elif _runtime_mapper is not None:
                    try:
                        _runtime_mapper.on_done(full_resp[:200] if full_resp else "")
                    except Exception:
                        pass
                if self.active_profiler is not None:
                    try:
                        summary = self.active_profiler.end_run(status=_profile_status_label(self._profile_status))
                        profile_path = build_profile_path(os.path.join(PROJECT_ROOT, 'temp', 'profiles'), self._profile_run_id or run_id)
                        self.active_profiler.export_json(profile_path)
                        print(format_profile_summary(summary, top_n=10))
                        print(f"[PROFILE] saved={profile_path}")
                    except Exception as profile_error:
                        print(f"[PROFILE] export failed: {profile_error}")
                    finally:
                        self.active_profiler = None
                        self._profile_run_id = None
                try:
                    _scrub_uploaded_file_context_from_backend(getattr(self.llmclient, 'backend', None))
                except Exception:
                    pass
                self._current_user_input = ""
                self._last_read_shortcut = None
                self._last_direct_answer = None
                self._last_early_stop = None
                self._active_display_queue = None
                self._active_source = None
                self._running = False
                self.stop_sig = False
                self._stop_event = None
                self.task_queue.task_done()
                if self.handler is not None:
                    self.handler.code_stop_signal.append(1)


# ══ DEPRECATED: use `ga run/serve/reflect` CLI instead (core/cli.py). ══
# This block is kept for backward compatibility with launch.pyw --sched
# and the root agentmain.py wrapper.  Do NOT add new features here.
if __name__ == '__main__':
    import argparse
    from datetime import datetime

    parser = argparse.ArgumentParser()
    parser.add_argument('--task', metavar='IODIR', help='涓€娆℃€т换鍔℃ā寮?鏂囦欢IO)')
    parser.add_argument('--reflect', metavar='SCRIPT', help='鍙嶅皠妯″紡锛氬姞杞界洃鎺ц剼鏈紝check()瑙﹀彂鏃跺彂浠诲姟')
    parser.add_argument('--input', help='prompt')
    parser.add_argument('--llm_no', type=int, default=0)
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--bg', action='store_true', help='popen, print PID, exit')
    args = parser.parse_args()

    if args.bg:
        import subprocess, platform

        cmd = [sys.executable, "-m", "core.agentmain"] + [a for a in sys.argv[1:] if a != '--bg']
        d = os.path.join(script_dir, f'temp/{args.task}')
        os.makedirs(d, exist_ok=True)
        p = subprocess.Popen(
            cmd,
            cwd=script_dir,
            creationflags=0x08000000 if platform.system() == 'Windows' else 0,
            stdout=open(os.path.join(d, 'stdout.log'), 'w', encoding='utf-8'),
            stderr=open(os.path.join(d, 'stderr.log'), 'w', encoding='utf-8'),
        )
        print(p.pid)
        sys.exit(0)

    agent = GeneraticAgent()
    agent.next_llm(args.llm_no)
    agent.verbose = args.verbose
    threading.Thread(target=agent.run, daemon=True).start()

    if args.task:
        agent.task_dir = d = os.path.join(script_dir, f'temp/{args.task}')
        nround = ''
        infile = os.path.join(d, 'input.txt')
        if args.input:
            os.makedirs(d, exist_ok=True)
            import glob

            [os.remove(f) for f in glob.glob(os.path.join(d, 'output*.txt'))]
            with open(infile, 'w', encoding='utf-8') as f:
                f.write(args.input)
        with open(infile, encoding='utf-8') as f:
            raw = f.read()
        while True:
            dq = agent.put_task(raw, source='task')
            item = dq.get(timeout=120)
            while 'done' not in item:
                if 'next' in item and random.random() < 0.95:
                    with open(f'{d}/output{nround}.txt', 'w', encoding='utf-8') as f:
                        f.write(item.get('next', ''))
                item = dq.get(timeout=120)
            with open(f'{d}/output{nround}.txt', 'w', encoding='utf-8') as f:
                f.write(item['done'] + '\n\n[ROUND END]\n')
            consume_file(d, '_stop')
            for _ in range(300):
                time.sleep(2)
                raw = consume_file(d, 'reply.txt')
                if raw:
                    break
            else:
                break
            nround = nround + 1 if isinstance(nround, int) else 1
    elif args.reflect:
        import importlib.util

        spec = importlib.util.spec_from_file_location('reflect_script', args.reflect)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _mt = os.path.getmtime(args.reflect)
        print(f'[Reflect] loaded {args.reflect}')
        while True:
            if os.path.getmtime(args.reflect) != _mt:
                try:
                    spec.loader.exec_module(mod)
                    _mt = os.path.getmtime(args.reflect)
                    print('[Reflect] reloaded')
                except Exception as e:
                    print(f'[Reflect] reload error: {e}')
            time.sleep(getattr(mod, 'INTERVAL', 5))
            try:
                task = mod.check()
            except Exception as e:
                print(f'[Reflect] check() error: {e}')
                continue
            if task is None:
                continue
            print(f'[Reflect] triggered: {task[:80]}')
            dq = agent.put_task(task, source='reflect')
            try:
                item = dq.get(timeout=120)
                while 'done' not in item:
                    item = dq.get(timeout=120)
                    pass
                result = item['done']
                print(result)
            except Exception as e:
                if getattr(mod, 'ONCE', False):
                    raise
                print(f'[Reflect] drain error: {e}')
                result = f'[ERROR] {e}'
            log_dir = os.path.join(script_dir, 'temp/reflect_logs')
            os.makedirs(log_dir, exist_ok=True)
            script_name = os.path.splitext(os.path.basename(args.reflect))[0]
            open(os.path.join(log_dir, f'{script_name}_{datetime.now():%Y-%m-%d}.log'), 'a', encoding='utf-8').write(f'[{datetime.now():%m-%d %H:%M}]\n{result}\n\n')
            on_done = getattr(mod, 'on_done', None)
            if on_done:
                try:
                    on_done(result)
                except Exception as e:
                    print(f'[Reflect] on_done error: {e}')
            if getattr(mod, 'ONCE', False):
                print('[Reflect] ONCE=True, exiting.')
                break
    else:
        agent.inc_out = True
        while True:
            q = input('> ').strip()
            if not q:
                continue
            try:
                dq = agent.put_task(q, source='user')
                while True:
                    item = dq.get()
                    if 'next' in item:
                        print(item['next'], end='', flush=True)
                    if 'done' in item:
                        print()
                        break
            except KeyboardInterrupt:
                agent.abort()
                print('\n[Interrupted]')
