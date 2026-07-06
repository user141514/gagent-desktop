import ast, asyncio, glob, json, os, queue as Q, re, socket, sys, time

HELP_TEXT = "📖 命令列表:\n/help - 显示帮助\n/status - 查看状态\n/stop - 停止当前任务\n/new - 清空当前上下文\n/restore - 恢复上次对话历史\n/llm [n] - 查看或切换模型"
FILE_HINT = "If you need to show files to user, use [FILE:filepath] in your response."
INTERNAL_TAGS = (
    "thinking",
    "summary",
    "tool_use",
    "file_content",
    "bash",
    "shell",
    "powershell",
    "tool_call",
)
TAG_PATS = [
    r"<\s*" + t + r"\b[^>]*>.*?<\s*/\s*" + t + r"\s*>"
    for t in INTERNAL_TAGS
]
OPEN_INTERNAL_TAG_RE = re.compile(
    r"<\s*(?:" + "|".join(re.escape(t) for t in INTERNAL_TAGS) + r")\b[^>]*>.*\Z",
    re.DOTALL | re.IGNORECASE,
)
EXECUTION_HONESTY_GATE_RE = re.compile(
    r"\[EXECUTION HONESTY GATE\][\s\S]*?(?:explicitly\.|\Z)",
    re.IGNORECASE,
)
EXECUTION_HONESTY_USER_NOTICE = (
    "\u6267\u884c\u8bda\u5b9e\u68c0\u67e5\u62e6\u622a\u4e86"
    "\u4e00\u6bb5\u7f3a\u5c11\u5de5\u5177\u8bc1\u636e\u7684"
    "\u72b6\u6001\u58f0\u660e\u3002\u672c\u8f6e\u4e0d\u80fd"
    "\u58f0\u79f0\u5df2\u4fdd\u5b58\u3001\u5df2\u66f4\u65b0"
    "\u6216\u5df2\u9a8c\u8bc1\uff1b\u9700\u8981\u5148\u6267\u884c"
    "\u5bf9\u5e94\u5de5\u5177\u5e76\u62ff\u5230\u6210\u529f\u7ed3\u679c\u3002"
)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEMORY_INBOX_PATH = os.path.join(PROJECT_ROOT, "memory", "history_memory_inbox.md")
RESTORE_GLOBS_DEFAULT = (
    os.path.join(PROJECT_ROOT, "temp", "model_responses", "model_responses_*.txt"),
    os.path.join(PROJECT_ROOT, "temp", "model_responses_*.txt"),
)
RESTORE_GLOBS_OPENAI = (
    os.path.join(PROJECT_ROOT, "temp", "model_responses_openai", "model_responses_*.txt"),
)
RESTORE_BLOCK_RE = re.compile(
    r"^=== (Prompt|Response) ===.*?\n(.*?)(?=^=== (?:Prompt|Response) ===|\Z)",
    re.DOTALL | re.MULTILINE,
)
HISTORY_RE = re.compile(r"<history>\s*(.*?)\s*</history>", re.DOTALL)
SUMMARY_RE = re.compile(r"<summary>\s*(.*?)\s*</summary>", re.DOTALL)
RECENT_CONVERSATION_RE = re.compile(
    r"\[RECENT CONVERSATION[^\]]*\]\s*(.*?)(?:\[/RECENT CONVERSATION\]|\Z)",
    re.DOTALL,
)
RECENT_TURN_RE = re.compile(r"^## Turn\s+(\d+)\s*$", re.MULTILINE)


def clean_reply(text):
    text = EXECUTION_HONESTY_GATE_RE.sub(
        EXECUTION_HONESTY_USER_NOTICE,
        text or "",
    )
    for pat in TAG_PATS:
        text = re.sub(pat, "", text or "", flags=re.DOTALL | re.IGNORECASE)
    text = OPEN_INTERNAL_TAG_RE.sub("", text or "")
    return re.sub(r"\n{3,}", "\n\n", text).strip() or "..."


def extract_files(text):
    return re.findall(r"\[FILE:([^\]]+)\]", text or "")


def strip_files(text):
    return re.sub(r"\[FILE:[^\]]+\]", "", text or "").strip()


def split_text(text, limit):
    text, parts = (text or "").strip() or "...", []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit * 0.6:
            cut = limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return parts + ([text] if text else []) or ["..."]


def _restore_log_files(backend_kind=None):
    """获取历史文件列表，backend_kind='openai-agents'时使用独立目录"""
    globs = RESTORE_GLOBS_OPENAI if backend_kind == "openai-agents" else RESTORE_GLOBS_DEFAULT
    files = []
    for pattern in globs:
        files.extend(glob.glob(pattern))
    return sorted(set(files))


def _restore_text_pairs(content):
    users = re.findall(
        r"^=== USER ===\n(.*?)(?=^=== (?:Prompt|Response|USER|INPUT_ITEMS) ===|\Z)",
        content,
        re.DOTALL | re.MULTILINE,
    )
    resps = re.findall(
        r"^=== Response ===.*?\n(.*?)(?=^=== (?:Prompt|Response|USER|INPUT_ITEMS) ===|\Z)",
        content,
        re.DOTALL | re.MULTILINE,
    )
    restored = []
    for u, r in zip(users, resps):
        u, r = u.strip(), r.strip()
        if u and r:
            restored.extend([f"[USER]: {u}", f"[Agent] {r}"])
    return restored


def _parse_input_items_from_content(content):
    """从历史文件中解析INPUT_ITEMS块，返回完整的input_items列表"""
    import json
    # 定位最后一个 INPUT_ITEMS 标记，再从该位置做 JSON 解码。
    # 这样即使输出文本里包含 "=== " 也不会截断 JSON。
    matches = list(re.finditer(r"^=== INPUT_ITEMS ===\n", content, re.MULTILINE))
    if not matches:
        return None
    tail = content[matches[-1].end():]
    start = tail.find("[")
    if start < 0:
        return None
    try:
        parsed, _ = json.JSONDecoder().raw_decode(tail[start:])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


def _content_to_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                if block:
                    parts.append(block)
                continue
            if not isinstance(block, dict):
                parts.append(str(block))
                continue
            block_type = block.get("type")
            if block_type in ("text", "input_text", "output_text"):
                text = block.get("text", "")
                if text:
                    parts.append(str(text))
            elif block_type == "tool_result":
                tool_content = block.get("content", "")
                if tool_content:
                    parts.append(_content_to_text(tool_content))
            elif block_type == "refusal":
                refusal = block.get("refusal", "")
                if refusal:
                    parts.append(str(refusal))
        return "\n".join(part for part in parts if str(part).strip())
    if isinstance(content, dict):
        return str(content.get("text", "") or content.get("content", "") or content.get("output", "") or "")
    return str(content or "")


def input_items_to_messages(input_items):
    messages = []
    for item in input_items or []:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role not in ("user", "assistant"):
            continue
        text = _content_to_text(item.get("content", ""))
        if not text and "output" in item:
            text = _content_to_text(item.get("output", ""))
        text = text.strip()
        if not text:
            continue
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += "\n\n" + text
        else:
            messages.append({"role": role, "content": text})
    return messages


def input_items_to_lines(input_items):
    lines = []
    for msg in input_items_to_messages(input_items):
        prefix = "[USER]: " if msg["role"] == "user" else "[Agent] "
        lines.append(prefix + msg["content"])
    return lines


def input_items_to_backend_history(input_items):
    history = []
    for msg in input_items_to_messages(input_items):
        history.append({
            "role": msg["role"],
            "content": [{"type": "text", "text": msg["content"]}],
        })
    return history


def _native_prompt_obj(prompt_body):
    try:
        prompt = json.loads(prompt_body)
    except Exception:
        return None
    if not isinstance(prompt, dict) or prompt.get("role") != "user":
        return None
    if not isinstance(prompt.get("content"), list):
        return None
    return prompt


def _native_prompt_text(prompt):
    texts = []
    for block in prompt.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            if isinstance(text, str) and text.strip():
                texts.append(text)
    return "\n".join(texts).strip()


def _native_history_lines(prompt_text):
    match = HISTORY_RE.search(prompt_text or "")
    if not match:
        return []
    restored = []
    for line in match.group(1).splitlines():
        line = line.strip()
        if line.startswith("[USER]: ") or line.startswith("[Agent] "):
            restored.append(line)
    return restored


def _append_recent_role(sections, role, lines):
    text = "\n".join(lines).strip()
    if text:
        sections.append((role, text))


def _recent_turn_sections(segment):
    sections = []
    role = None
    lines = []
    skip_tool_events = False
    for raw_line in (segment or "").splitlines():
        line = raw_line.rstrip()
        if line.startswith("USER:"):
            _append_recent_role(sections, role, lines)
            role = "user"
            lines = [line.split(":", 1)[1].strip()]
            skip_tool_events = False
            continue
        if line.startswith("ASSISTANT:"):
            _append_recent_role(sections, role, lines)
            role = "assistant"
            lines = [line.split(":", 1)[1].strip()]
            skip_tool_events = False
            continue
        if line.startswith("TOOL_EVENTS:"):
            _append_recent_role(sections, role, lines)
            role = None
            lines = []
            skip_tool_events = True
            continue
        if skip_tool_events:
            continue
        if role:
            lines.append(line)
    _append_recent_role(sections, role, lines)
    return sections


def _recent_conversation_lines(prompt_text):
    restored = []
    for block in RECENT_CONVERSATION_RE.findall(prompt_text or ""):
        matches = list(RECENT_TURN_RE.finditer(block))
        turns = []
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(block)
            try:
                turn = int(match.group(1))
            except (TypeError, ValueError):
                turn = index
            turns.append((turn, index, block[start:end]))
        if not turns and block.strip():
            turns.append((0, 0, block))
        for _, _, segment in sorted(turns, key=lambda item: (item[0], item[1])):
            for role, text in _recent_turn_sections(segment):
                prefix = "[USER]: " if role == "user" else "[Agent] "
                _append_restored_line(restored, prefix + text)
    return restored


def _remove_uploaded_file_context(text):
    return re.sub(
        r"<uploaded_file_context>.*?</uploaded_file_context>",
        "",
        text or "",
        flags=re.DOTALL | re.IGNORECASE,
    )


def _looks_like_internal_prompt(text):
    stripped = (text or "").lstrip()
    return stripped.startswith((
        "[DANGER]",
        "[REFLECT]",
        "[System]",
        "[ROUTER_HINT]",
        "[LEGACY PROJECT MEMORY",
        "[RECENT CONVERSATION",
        "[WEB TOOL FAILURE]",
        "### [WORKING MEMORY]",
        "### Research and Code Priority Guard",
        "### Answer Quality",
        "### Problem Framing",
        "TOOL_EVENTS:",
        "cwd =",
    ))


def _native_first_user_line(prompt_text):
    text = (prompt_text or "").strip()
    if text.startswith(FILE_HINT):
        text = text[len(FILE_HINT):].lstrip()
    if RECENT_CONVERSATION_RE.search(text):
        matches = list(RECENT_CONVERSATION_RE.finditer(text))
        if matches:
            text = text[matches[-1].end():].strip()
        text = _remove_uploaded_file_context(text).strip()
    for marker in ("### 用户当前消息", "### Current User Message"):
        if marker in text:
            return text.split(marker, 1)[-1].strip()
    if not text or "<history>" in text or _looks_like_internal_prompt(text):
        return ""
    return text


def _native_response_text(response_body):
    raw = (response_body or "").strip()
    if not raw:
        return ""
    try:
        blocks = ast.literal_eval(raw)
    except Exception:
        text = clean_reply(raw)
        if text and text != "...":
            return text
        match = SUMMARY_RE.search(raw)
        return match.group(1).strip() if match else ""
    if not isinstance(blocks, list):
        return ""
    text_parts = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") in ("text", "output_text"):
            text = block.get("text", "")
            if isinstance(text, str) and text:
                text_parts.append(text)
    joined = "\n".join(text_parts).strip()
    if not joined:
        return ""
    text = clean_reply(joined)
    if text and text != "...":
        return text
    match = SUMMARY_RE.search(joined)
    text = match.group(1).strip() if match else ""
    return text


def _native_response_summary(response_body, max_chars=None):
    text = _native_response_text(response_body)
    return text[:max_chars] if max_chars else text


def _append_restored_line(restored, line):
    line = (line or "").strip()
    if not line:
        return
    if restored and restored[-1] == line:
        return
    restored.append(line)


def _trim_leading_agent_context(restored):
    for index, line in enumerate(restored or []):
        if not isinstance(line, str) or not line.startswith("[USER]: "):
            continue
        user_text = line[8:].strip()
        if _looks_like_internal_prompt(user_text):
            continue
        return list(restored[index:])
    return restored


def _restore_native_prompt(prompt_body, response_body=""):
    prompt = _native_prompt_obj(prompt_body)
    if prompt is None:
        return []
    prompt_text = _native_prompt_text(prompt)
    restored = list(_recent_conversation_lines(prompt_text) or _native_history_lines(prompt_text))
    user_text = _native_first_user_line(prompt_text)
    if user_text:
        _append_restored_line(restored, f"[USER]: {user_text}")
    summary = _native_response_summary(response_body)
    if summary:
        _append_restored_line(restored, f"[Agent] {summary}")
    return _trim_leading_agent_context(restored)


def _restore_native_history(content):
    """从历史文件恢复对话，包括仅有 Prompt 的中断日志。"""
    blocks = RESTORE_BLOCK_RE.findall(content or "")
    if not blocks:
        return []
    pairs = []
    pending_prompt = None
    for label, body in blocks:
        if label == "Prompt":
            pending_prompt = body
        elif pending_prompt is not None:
            pairs.append((pending_prompt, body))
            pending_prompt = None
    pending_fallback = []
    if pending_prompt is not None:
        restored = _restore_native_prompt(pending_prompt)
        if restored:
            pending_fallback = restored
    turns = []
    current_idx = -1

    def ensure_user(user_text, reuse_last=False):
        nonlocal current_idx
        user_text = (user_text or "").strip()
        if not user_text or _looks_like_internal_prompt(user_text):
            return current_idx
        if turns and turns[-1]["user"] == user_text and (reuse_last or not turns[-1].get("agent")):
            current_idx = len(turns) - 1
            return current_idx
        turns.append({"user": user_text, "agent": ""})
        current_idx = len(turns) - 1
        return current_idx

    def turns_from_history_lines(lines):
        parsed = []
        index = -1
        for line in lines or []:
            if not isinstance(line, str):
                continue
            if line.startswith("[USER]: "):
                user_text = line[8:].strip()
                if user_text and not _looks_like_internal_prompt(user_text):
                    if parsed and parsed[-1]["user"] == user_text and not parsed[-1].get("agent"):
                        index = len(parsed) - 1
                    else:
                        parsed.append({"user": user_text, "agent": ""})
                        index = len(parsed) - 1
            elif line.startswith("[Agent] ") and index >= 0:
                text = line[8:].strip()
                if text:
                    existing = parsed[index].get("agent") or ""
                    parsed[index]["agent"] = (existing + "\n" + text).strip() if existing else text
        return parsed

    def merge_history_turns(incoming):
        nonlocal turns, current_idx
        if not incoming:
            return
        if not turns:
            turns = [dict(turn) for turn in incoming]
            current_idx = len(turns) - 1
            return
        limit = min(len(turns), len(incoming))
        matched = 0
        while matched < limit and turns[matched]["user"] == incoming[matched]["user"]:
            if incoming[matched].get("agent") and not turns[matched].get("agent"):
                turns[matched]["agent"] = incoming[matched]["agent"]
            matched += 1
        if matched == len(turns):
            turns.extend(dict(turn) for turn in incoming[matched:])
        current_idx = len(turns) - 1

    for prompt_body, response_body in pairs:
        prompt = _native_prompt_obj(prompt_body)
        if prompt is None:
            continue
        prompt_text = _native_prompt_text(prompt)
        history_lines = _recent_conversation_lines(prompt_text) or _native_history_lines(prompt_text)
        merge_history_turns(turns_from_history_lines(history_lines))
        user_text = _native_first_user_line(prompt_text)
        if user_text:
            ensure_user(user_text)
        response_text = _native_response_text(response_body)
        if response_text and current_idx >= 0 and (user_text or history_lines or not _looks_like_internal_prompt(prompt_text)):
            turns[current_idx]["agent"] = response_text

    restored = []
    for turn in turns:
        _append_restored_line(restored, f"[USER]: {turn['user']}")
        if turn.get("agent"):
            _append_restored_line(restored, f"[Agent] {turn['agent']}")
    restored = _trim_leading_agent_context(restored)
    has_user = any(line.startswith("[USER]: ") for line in restored)
    has_agent = any(line.startswith("[Agent] ") for line in restored)
    if restored and has_user and has_agent:
        return restored
    if restored and has_user:
        return restored
    return pending_fallback or restored


def format_restore(filepath=None, backend_kind=None):
    """恢复历史对话。filepath为None时恢复最新文件。backend_kind='openai-agents'时使用独立目录"""
    if filepath:
        # 指定了文件路径
        if not os.path.exists(filepath):
            return None, "❌ 指定的历史文件不存在"
        target = filepath
    else:
        # 恢复最新文件
        files = _restore_log_files(backend_kind)
        if not files:
            return None, "❌ 没有找到历史记录"
        target = max(files, key=os.path.getmtime)
    with open(target, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    # 优先尝试解析完整的input_items (openai-agents新格式)
    input_items = _parse_input_items_from_content(content)
    if input_items:
        count = sum(1 for item in input_items if item.get("role") == "user")
        return (input_items, os.path.basename(target), count, "input_items"), None
    # 回退到旧格式
    restored = _restore_text_pairs(content) or _restore_native_history(content)
    if not restored:
        return None, "❌ 历史记录里没有可恢复内容"
    count = sum(1 for line in restored if line.startswith("[USER]: "))
    return (restored, os.path.basename(target), count, "lines"), None


def unpack_restore_result(restored_info):
    if not restored_info:
        return None, None, 0, "lines"
    if len(restored_info) >= 4:
        restored, fname, count, fmt_type = restored_info[:4]
        return restored, fname, count, fmt_type
    restored, fname, count = restored_info
    return restored, fname, count, "lines"


def restored_lines_to_messages(restored):
    messages = []
    for line in restored or []:
        if line.startswith("[USER]: "):
            messages.append({"role": "user", "content": line[8:]})
        elif line.startswith("[Agent] "):
            messages.append({"role": "assistant", "content": line[8:]})
    return messages


def restored_lines_to_backend_history(restored):
    history = []
    for msg in restored_lines_to_messages(restored):
        history.append({
            "role": msg["role"],
            "content": [{"type": "text", "text": msg["content"]}],
        })
    return history


def build_done_text(raw_text):
    files = [p for p in extract_files(raw_text) if os.path.exists(p)]
    body = strip_files(clean_reply(raw_text))
    if files:
        body = (body + "\n\n" if body else "") + "\n".join(f"生成文件: {p}" for p in files)
    return body or "..."


def public_access(allowed):
    return not allowed or "*" in allowed


def to_allowed_set(value):
    if value is None:
        return set()
    if isinstance(value, str):
        value = [value]
    return {str(x).strip() for x in value if str(x).strip()}


def allowed_label(allowed):
    return "public" if public_access(allowed) else sorted(allowed)


def ensure_single_instance(port, label):
    try:
        lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lock_sock.bind(("127.0.0.1", port))
        return lock_sock
    except OSError:
        print(f"[{label}] Another instance is already running, skipping...")
        sys.exit(1)


def require_runtime(agent, label, **required):
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"[{label}] ERROR: please set {', '.join(missing)} in mykey.py or mykey.json")
        sys.exit(1)
    if agent.llmclient is None:
        print(f"[{label}] ERROR: no usable LLM backend found in mykey.py or mykey.json")
        sys.exit(1)


def redirect_log(script_file, log_name, label, allowed):
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(script_file))), "temp")
    os.makedirs(log_dir, exist_ok=True)
    logf = open(os.path.join(log_dir, log_name), "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = logf
    print(f"[NEW] {label} process starting, the above are history infos ...")
    print(f"[{label}] allow list: {allowed_label(allowed)}")


class AgentChatMixin:
    label = "Chat"
    source = "chat"
    split_limit = 1500
    ping_interval = 20

    def __init__(self, agent, user_tasks):
        self.agent, self.user_tasks = agent, user_tasks

    async def send_text(self, chat_id, content, **ctx):
        raise NotImplementedError

    async def send_done(self, chat_id, raw_text, **ctx):
        await self.send_text(chat_id, build_done_text(raw_text), **ctx)

    async def handle_command(self, chat_id, cmd, **ctx):
        parts = (cmd or "").split()
        op = (parts[0] if parts else "").lower()
        if op == "/stop":
            state = self.user_tasks.get(chat_id)
            if state:
                state["running"] = False
            self.agent.abort()
            return await self.send_text(chat_id, "⏹️ 正在停止...", **ctx)
        if op == "/status":
            llm = self.agent.get_llm_name() if self.agent.llmclient else "未配置"
            return await self.send_text(chat_id, f"状态: {'🔴 运行中' if self.agent.is_running else '🟢 空闲'}\nLLM: [{self.agent.llm_no}] {llm}", **ctx)
        if op == "/llm":
            if not self.agent.llmclient:
                return await self.send_text(chat_id, "❌ 当前没有可用的 LLM 配置", **ctx)
            if len(parts) > 1:
                try:
                    self.agent.next_llm(int(parts[1]))
                    return await self.send_text(chat_id, f"✅ 已切换到 [{self.agent.llm_no}] {self.agent.get_llm_name()}", **ctx)
                except Exception:
                    return await self.send_text(chat_id, f"用法: /llm <0-{len(self.agent.list_llms()) - 1}>", **ctx)
            lines = [f"{'→' if cur else '  '} [{i}] {name}" for i, name, cur in self.agent.list_llms()]
            return await self.send_text(chat_id, "LLMs:\n" + "\n".join(lines), **ctx)
        if op == "/restore":
            try:
                restored_info, err = format_restore()
                if err:
                    return await self.send_text(chat_id, err, **ctx)
                restored, fname, count, fmt_type = unpack_restore_result(restored_info)
                self.agent.abort()
                if fmt_type == "input_items" and hasattr(self.agent, "restore_history"):
                    self.agent.restore_history(restored, is_input_items=True)
                elif fmt_type == "input_items":
                    self.agent.history = input_items_to_lines(restored)
                    if getattr(self.agent, "llmclient", None):
                        self.agent.llmclient.backend.history = input_items_to_backend_history(restored)
                        self.agent.llmclient.last_tools = ''
                else:
                    self.agent.history = list(restored)
                    if getattr(self.agent, "llmclient", None):
                        self.agent.llmclient.backend.history = restored_lines_to_backend_history(restored)
                        self.agent.llmclient.last_tools = ''
                return await self.send_text(chat_id, f"✅ 已恢复 {count} 轮对话\n来源: {fname}\n(将从这次对话的最后状态继续)", **ctx)
            except Exception as e:
                return await self.send_text(chat_id, f"❌ 恢复失败: {e}", **ctx)
        if op == "/new":
            self.agent.abort()
            self.agent.history = []
            return await self.send_text(chat_id, "🆕 已清空当前共享上下文", **ctx)
        return await self.send_text(chat_id, HELP_TEXT, **ctx)

    async def run_agent(self, chat_id, text, **ctx):
        state = {"running": True}
        self.user_tasks[chat_id] = state
        try:
            await self.send_text(chat_id, "思考中...", **ctx)
            dq = self.agent.put_task(f"{FILE_HINT}\n\n{text}", source=self.source)
            last_ping = time.time()
            while state["running"]:
                try:
                    item = await asyncio.to_thread(dq.get, True, 3)
                except Q.Empty:
                    if self.agent.is_running and time.time() - last_ping > self.ping_interval:
                        await self.send_text(chat_id, "⏳ 还在处理中，请稍等...", **ctx)
                        last_ping = time.time()
                    continue
                if "done" in item:
                    await self.send_done(chat_id, item.get("done", ""), **ctx)
                    break
            if not state["running"]:
                await self.send_text(chat_id, "⏹️ 已停止", **ctx)
        except Exception as e:
            import traceback
            print(f"[{self.label}] run_agent error: {e}")
            traceback.print_exc()
            await self.send_text(chat_id, f"❌ 错误: {e}", **ctx)
        finally:
            self.user_tasks.pop(chat_id, None)


# ========== 对话蒸馏功能 ==========

def distill_conversation(filepath):
    """
    蒸馏对话内容，提取有价值的信息摘要
    返回: (summary_dict, error)
    summary_dict 包含: title, key_points, decisions, files_modified
    """
    if not os.path.exists(filepath):
        return None, "文件不存在"
    
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # 提取对话历史
        result, err = format_restore(filepath)
        if err or not result:
            return None, f"无法解析对话内容: {err}"
        restored, fname, count, fmt_type = unpack_restore_result(result)
        restored_lines = input_items_to_lines(restored) if fmt_type == "input_items" else restored
        
        # 提取用户问题作为标题
        user_questions = [line[8:] for line in restored_lines if line.startswith("[USER]: ")]
        title = user_questions[0][:50] if user_questions else fname
        
        # 提取文件操作记录
        files_touched = set()
        for line in restored_lines:
            if line.startswith("[Agent]"):
                # 提取文件路径
                import re
                paths = re.findall(r"['\"]([^'\"]*\.(?:py|md|txt|json))['\"]", line)
                files_touched.update(paths)
        
        # 提取关键回复（包含"完成"、"修复"、"添加"等关键词的摘要）
        key_replies = []
        for line in restored_lines:
            if line.startswith("[Agent]"):
                text = line[8:]
                # 过滤掉工具调用行，保留有意义的摘要
                if not text.startswith("调用工具") and len(text) > 10:
                    key_replies.append(text[:200])
        
        summary = {
            "title": title,
            "rounds": count,
            "source_file": os.path.basename(filepath),
            "questions": user_questions,
            "files_touched": list(files_touched)[:10],  # 最多10个文件
            "key_replies": key_replies[-5:] if key_replies else [],  # 最后5条关键回复
        }
        
        return summary, None
        
    except Exception as e:
        return None, f"解析失败: {e}"


def delete_history_file(filepath):
    """删除历史文件，返回 (success, error)"""
    if not os.path.exists(filepath):
        return False, "文件不存在"
    
    try:
        os.remove(filepath)
        return True, None
    except Exception as e:
        return False, f"删除失败: {e}"


def _format_memory_inbox_entry(summary, source_path, saved_at=None):
    saved_at = saved_at or time.strftime("%Y-%m-%d %H:%M:%S")
    source_name = os.path.basename(source_path)
    title = (summary or {}).get("title") or source_name
    rounds = (summary or {}).get("rounds") or 0
    questions = list((summary or {}).get("questions") or [])
    files_touched = list((summary or {}).get("files_touched") or [])
    key_replies = list((summary or {}).get("key_replies") or [])

    lines = [
        f"## {title}",
        f"<!-- source: {source_name} -->",
        f"- Saved At: {saved_at}",
        f"- Source File: {source_name}",
        f"- Dialogue Rounds: {rounds}",
    ]
    if questions:
        lines.append("- User Questions:")
        lines.extend(f"  - {q}" for q in questions[:5])
    if files_touched:
        lines.append("- Files Touched:")
        lines.extend(f"  - {p}" for p in files_touched[:10])
    if key_replies:
        lines.append("- Key Replies:")
        lines.extend(f"  - {r}" for r in key_replies[:5])
    lines.append("")
    return "\n".join(lines)


def save_distilled_memory(summary, source_path, inbox_path=None):
    inbox_path = inbox_path or MEMORY_INBOX_PATH
    source_name = os.path.basename(source_path or "")
    marker = f"<!-- source: {source_name} -->"
    try:
        os.makedirs(os.path.dirname(inbox_path), exist_ok=True)
        existing = ""
        if os.path.exists(inbox_path):
            with open(inbox_path, "r", encoding="utf-8", errors="ignore") as f:
                existing = f.read()
        if marker in existing:
            return {
                "status": "exists",
                "path": inbox_path,
                "msg": f"{source_name} 已在记忆候选池中",
            }, None

        header = "# Distilled Conversation Memory Inbox\n\n"
        entry = _format_memory_inbox_entry(summary, source_path)
        mode = "a" if existing else "w"
        with open(inbox_path, mode, encoding="utf-8") as f:
            if not existing:
                f.write(header)
            elif not existing.endswith("\n\n"):
                f.write("\n")
            f.write(entry)
            if not entry.endswith("\n"):
                f.write("\n")
        return {
            "status": "saved",
            "path": inbox_path,
            "msg": f"{source_name} 已写入记忆候选池",
        }, None
    except Exception as e:
        return None, f"写入记忆候选池失败: {e}"
