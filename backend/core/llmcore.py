import os, json, re, time, requests, sys, threading, urllib3, base64, mimetypes, uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .runtime import LLMCallCache

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
_RESP_CACHE_KEY = str(uuid.uuid4()) 
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_LLM_AUDIT_CACHE = LLMCallCache(Path(PROJECT_ROOT) / "temp" / "llm_cache")
_MYKEYS_CACHE_LOCK = threading.Lock()
_MYKEYS_CACHE: tuple[dict[str, Any], dict[str, str] | None] | None = None

# Load .env file for API key configuration (preferred over mykey.py)
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
except ImportError:
    pass


def _audit_response_text(content_blocks):
    texts = []
    for block in content_blocks or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and block.get("text"):
            texts.append(str(block.get("text")))
        elif block.get("type") == "thinking" and block.get("thinking"):
            texts.append(str(block.get("thinking")))
    return "\n".join(t for t in texts if t).strip()


def _clean_audit_metadata(metadata):
    return {k: v for k, v in (metadata or {}).items() if v is not None}


def _build_audit_metadata(session, *, call_site, streaming, extra=None):
    metadata = dict(getattr(session, "_audit_context", {}) or {})
    metadata.update(extra or {})
    metadata["call_site"] = call_site
    metadata["streaming"] = bool(streaming)
    metadata["cache_type"] = "streaming_response" if streaming else "user_chat_response"
    metadata.setdefault("backend_name", getattr(session, "name", ""))
    metadata.setdefault("api_base", getattr(session, "api_base", ""))
    metadata.setdefault("api_mode", getattr(session, "api_mode", ""))
    metadata["temperature"] = getattr(session, "temperature", metadata.get("temperature"))
    return _clean_audit_metadata(metadata)


def _safe_audit_llm_call(*, session, call_site, messages, response, duration_ms, tools=None, streaming):
    metadata = _build_audit_metadata(session, call_site=call_site, streaming=streaming)
    try:
        _LLM_AUDIT_CACHE.audit(
            model=getattr(session, "model", "") or getattr(session, "name", ""),
            messages=messages,
            response=response,
            duration_ms=duration_ms,
            tools=tools,
            metadata=metadata,
        )
    except Exception as exc:
        print(f"[LLM AUDIT] {call_site} failed: {exc}")


# ── Error classification — turn HTTP responses into semantic categories ─────
# Category    → user-facing action
# AUTH_ERROR  → check API key
# MODEL_NOT_FOUND → check key/group/model match
# PROTOCOL_ERROR  → report + protocol snapshot, DO NOT auto-fallback
# RATE_LIMITED / SERVER_ERROR / CONNECTION_ERROR → retry with backoff

from enum import Enum, auto


class ErrorCategory(Enum):
    AUTH_ERROR = auto()
    MODEL_NOT_FOUND = auto()
    PROTOCOL_ERROR = auto()
    RATE_LIMITED = auto()
    SERVER_ERROR = auto()
    CONNECTION_ERROR = auto()
    UNKNOWN = auto()


class ErrorAction(Enum):
    SUGGEST_KEY_CHECK = auto()
    SUGGEST_MATCH = auto()
    REPORT_WITH_SNAPSHOT = auto()
    RETRY_BACKOFF = auto()
    NO_RETRY = auto()


def classify_http_error(status_code, body=""):
    """Classify an HTTP error into a semantic category and recommended action.

    Returns ``(ErrorCategory, ErrorAction)``.  The caller decides whether to
    retry, report, or escalate based on the action.
    """
    lowered = (body or "").lower()

    if status_code in (401, 403):
        return ErrorCategory.AUTH_ERROR, ErrorAction.SUGGEST_KEY_CHECK

    if status_code == 404:
        return ErrorCategory.MODEL_NOT_FOUND, ErrorAction.SUGGEST_MATCH

    if status_code == 429:
        return ErrorCategory.RATE_LIMITED, ErrorAction.RETRY_BACKOFF

    if status_code in (500, 502, 503, 504):
        return ErrorCategory.SERVER_ERROR, ErrorAction.RETRY_BACKOFF

    if status_code == 400:
        protocol_markers = (
            "unknown variant", "failed to deserialize",
            "invalid content block", "unexpected content",
            "thinking blocks are not supported",
        )
        if any(m in lowered for m in protocol_markers):
            return ErrorCategory.PROTOCOL_ERROR, ErrorAction.REPORT_WITH_SNAPSHOT

    # Model-not-found markers in body (even without 404)
    model_markers = (
        "model_not_found", "no available channel",
        "model not found", "channel not found",
    )
    if any(m in lowered for m in model_markers):
        return ErrorCategory.MODEL_NOT_FOUND, ErrorAction.SUGGEST_MATCH

    # Auth markers in body (even without 401/403)
    auth_markers = (
        "invalid_api_key", "authentication_error",
        "permission denied", "credential",
    )
    if any(m in lowered for m in auth_markers):
        return ErrorCategory.AUTH_ERROR, ErrorAction.SUGGEST_KEY_CHECK

    return ErrorCategory.UNKNOWN, ErrorAction.NO_RETRY


# ── Provider protocol snapshot (diagnostic, gated by GA_PROTOCOL_SNAPSHOT=1) ──

def _protocol_snapshot(*, model: str = "", api_base: str = "", api_key: str = "",
                        session: Any = None, messages: list | None = None,
                        tools: list | None = None, label: str = "") -> None:
    """Print the active provider profile once when ``GA_PROTOCOL_SNAPSHOT=1``.

    Shows key/mode/base_url/thinking/stream/history at every API call gateway
    so mismatches between key, model, and protocol are visible immediately.
    """
    if os.environ.get("GA_PROTOCOL_SNAPSHOT", "0") != "1":
        return
    key_prefix = (api_key or "")[:8] + "..." if len(api_key or "") > 8 else "(empty)"
    backend_name = getattr(session, "name", "") or ""
    thinking_type = getattr(session, "thinking_type", "not_set")
    thinking_budget = getattr(session, "thinking_budget_tokens", "not_set")
    stream_mode = getattr(session, "stream", True)
    api_mode = getattr(session, "api_mode", "chat_completions")
    history_count = len(getattr(session, "history", []))
    tool_count = len(tools or [])
    label_str = f"[{label}] " if label else ""
    print(
        f"\n[PROTOCOL SNAPSHOT] {label_str}"
        f"provider={backend_name or 'unknown'} "
        f"model={model} "
        f"base_url={api_base} "
        f"key={key_prefix} "
        f"session_cls={type(session).__name__ if session else 'N/A'} "
        f"thinking={thinking_type}/{thinking_budget} "
        f"stream={stream_mode} "
        f"api_mode={api_mode} "
        f"history_msgs={history_count} "
        f"tools={tool_count}\n"
    )

def _load_mykeys_from_env():
    """Build a mykeys-compatible config dict from GA_* / GA_KEY1_* / GA_KEY2_* env vars."""
    result = {}
    # ── Key1 (primary model) ──
    key1_api = os.environ.get("GA_KEY1_API_KEY", "").strip() or os.environ.get("GA_API_KEY", "").strip()
    if key1_api:
        result["key1_native_oai_config"] = {
            "name": os.environ.get("GA_KEY1_NAME", os.environ.get("GA_BACKEND_NAME", "key1")),
            "apikey": key1_api,
            "apibase": os.environ.get("GA_KEY1_API_BASE", os.environ.get("GA_API_BASE_URL", "https://api.deepseek.com")).rstrip("/"),
            "model": os.environ.get("GA_KEY1_MODEL", os.environ.get("GA_MODEL", "deepseek-v4-pro")),
            "stream": os.environ.get("GA_KEY1_STREAM", os.environ.get("GA_STREAM", "true")).lower() != "false",
            "max_retries": int(os.environ.get("GA_KEY1_MAX_RETRIES", os.environ.get("GA_MAX_RETRIES", "3"))),
            "connect_timeout": int(os.environ.get("GA_KEY1_CONNECT_TIMEOUT", os.environ.get("GA_CONNECT_TIMEOUT", "10"))),
            "read_timeout": int(os.environ.get("GA_KEY1_READ_TIMEOUT", os.environ.get("GA_READ_TIMEOUT", "120"))),
        }
    # ── Key2 (secondary model) ──
    key2_api = os.environ.get("GA_KEY2_API_KEY", "").strip()
    if key2_api:
        result["key2_native_oai_config"] = {
            "name": os.environ.get("GA_KEY2_NAME", "key2"),
            "apikey": key2_api,
            "apibase": os.environ.get("GA_KEY2_API_BASE", "https://api.deepseek.com").rstrip("/"),
            "model": os.environ.get("GA_KEY2_MODEL", "deepseek-v4-pro"),
            "stream": os.environ.get("GA_KEY2_STREAM", "true").lower() != "false",
            "max_retries": int(os.environ.get("GA_KEY2_MAX_RETRIES", "3")),
            "connect_timeout": int(os.environ.get("GA_KEY2_CONNECT_TIMEOUT", "10")),
            "read_timeout": int(os.environ.get("GA_KEY2_READ_TIMEOUT", "120")),
        }
    return result

def _load_mykeys():
    # 1. Try importing mykey.py (legacy, gitignored)
    try:
        import mykey
        return {k: v for k, v in vars(mykey).items() if not k.startswith("_")}
    except ImportError:
        pass
    # 2. Try mykey.json (legacy)
    p = os.path.join(PROJECT_ROOT, "mykey.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    # 3. Fall back to environment variables (preferred new approach)
    keys = _load_mykeys_from_env()
    if keys:
        return keys
    raise Exception(
        "[ERROR] No API key configuration found. "
        "Set GA_API_KEY environment variable, or create mykey.py from mykey_template.py."
    )

def _load_mykeys_cached():
    global _MYKEYS_CACHE
    if _MYKEYS_CACHE is None:
        with _MYKEYS_CACHE_LOCK:
            if _MYKEYS_CACHE is None:
                mk = _load_mykeys()
                proxy = mk.get("proxy", 'http://127.0.0.1:2082')
                px = {"http": proxy, "https": proxy} if proxy else None
                _MYKEYS_CACHE = (mk, px)
                globals()["mykeys"] = mk
                globals()["proxies"] = px
    return _MYKEYS_CACHE


def __getattr__(name):
    if name in ('mykeys', 'proxies'):
        mk, px = _load_mykeys_cached()
        return mk if name == 'mykeys' else px
    raise AttributeError(f"module 'llmcore' has no attribute {name}")

# Compiled once at module load — reused across all compress_history_tags calls.
_COMPRESS_TAG_PATS = {
    tag: re.compile(rf'(<{tag}>)([\s\S]*?)(</{tag}>)')
    for tag in ('thinking', 'think', 'tool_use', 'tool_result')
}
_COMPRESS_HIST_PAT = re.compile(r'<(history|key_info)>[\s\S]*?</\1>')
_COMPRESS_HISTORY_LOCK = threading.Lock()
_COMPRESS_HISTORY_COUNTS: dict[int, int] = {}
_COMPRESS_HISTORY_MAX_TRACKED = 4096


def _should_compress_history(messages, force=False):
    key = id(messages)
    with _COMPRESS_HISTORY_LOCK:
        if force:
            _COMPRESS_HISTORY_COUNTS[key] = 0
            return True
        count = _COMPRESS_HISTORY_COUNTS.get(key, 0) + 1
        _COMPRESS_HISTORY_COUNTS[key] = count
        if len(_COMPRESS_HISTORY_COUNTS) > _COMPRESS_HISTORY_MAX_TRACKED:
            for stale_key in list(_COMPRESS_HISTORY_COUNTS)[:512]:
                if stale_key != key:
                    _COMPRESS_HISTORY_COUNTS.pop(stale_key, None)
        return count % 5 == 0


def compress_history_tags(messages, keep_recent=10, max_len=800, force=False):
    """Compress <thinking>/<tool_use>/<tool_result> tags in older messages to save tokens."""
    if not _should_compress_history(messages, force=force): return messages
    _before = sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)
    def _trunc_str(s): return s[:max_len//2] + '\n...[Truncated]...\n' + s[-max_len//2:] if isinstance(s, str) and len(s) > max_len else s
    def _trunc(text):
        text = _COMPRESS_HIST_PAT.sub(lambda m: f'<{m.group(1)}>[...]</{m.group(1)}>', text)
        for pat in _COMPRESS_TAG_PATS.values(): text = pat.sub(lambda m: m.group(1) + _trunc_str(m.group(2)) + m.group(3), text)
        return text
    for i, msg in enumerate(messages):
        if i >= len(messages) - keep_recent: break
        c = msg['content']
        if isinstance(c, str): msg['content'] = _trunc(c)
        elif isinstance(c, list):
            for b in c:
                if not isinstance(b, dict): continue
                t = b.get('type')
                if t == 'text' and isinstance(b.get('text'), str): b['text'] = _trunc(b['text'])
                elif t == 'tool_result':
                    tc = b.get('content')
                    if isinstance(tc, str): b['content'] = _trunc_str(tc)
                    elif isinstance(tc, list):
                        for sub in tc:
                            if isinstance(sub, dict) and sub.get('type') == 'text': sub['text'] = _trunc_str(sub.get('text'))
                elif t == 'tool_use' and isinstance(b.get('input'), dict):
                    for k, v in b['input'].items(): b['input'][k] = _trunc_str(v)
    print(f"[Cut] {_before} -> {sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)}")
    return messages

def _sanitize_leading_user_msg(msg):
    """把 user 消息里的 tool_result 块改写成纯文本，避免孤立引用。
    history 统一使用 Claude content-block 格式：content 是 list of blocks。"""
    msg = dict(msg)  # 浅拷贝外层 dict
    content = msg.get('content')
    if not isinstance(content, list): return msg
    texts = []
    for block in content:
        if not isinstance(block, dict): continue
        if block.get('type') == 'tool_result':
            c = block.get('content', '')
            if isinstance(c, list):  # content 本身也可能是 list[{type:text,text:...}]
                texts.extend(b.get('text', '') for b in c if isinstance(b, dict))
            else: texts.append(str(c))
        elif block.get('type') == 'text': texts.append(block.get('text', ''))
    msg['content'] = [{"type": "text", "text": '\n'.join(t for t in texts if t)}]
    return msg

def _normalize_content_blocks(content):
    """Normalize message content into Claude content-block list."""
    if isinstance(content, list):
        blocks = []
        for block in content:
            if isinstance(block, dict):
                blocks.append(block)
            elif isinstance(block, str):
                blocks.append({"type": "text", "text": block})
            else:
                blocks.append({"type": "text", "text": str(block)})
        return blocks or [{"type": "text", "text": ""}]
    if isinstance(content, dict):
        return [content]
    return [{"type": "text", "text": "" if content is None else str(content)}]

def _with_ephemeral_last_block(content):
    blocks = _normalize_content_blocks(content)
    blocks[-1] = dict(blocks[-1], cache_control={"type": "ephemeral"})
    return blocks

def trim_messages_history(history, context_win):
    compress_history_tags(history)
    cost = sum(len(json.dumps(m, ensure_ascii=False)) for m in history) 
    print(f'[Debug] Current context: {cost} chars, {len(history)} messages.')
    if cost > context_win * 3: 
        compress_history_tags(history, keep_recent=4, force=True)   # trim breaks cache, so compress more btw
        target = context_win * 3 * 0.6
        while len(history) > 5 and cost > target:
            history.pop(0)
            while history and history[0].get('role') != 'user': history.pop(0)
            if history and history[0].get('role') == 'user': history[0] = _sanitize_leading_user_msg(history[0])
            cost = sum(len(json.dumps(m, ensure_ascii=False)) for m in history)
        print(f'[Debug] Trimmed context, current: {cost} chars, {len(history)} messages.')

def auto_make_url(base, path):
    b, p = base.rstrip('/'), path.strip('/')
    if b.endswith('$'): return b[:-1].rstrip('/')
    if b.endswith(p): return b
    return f"{b}/{p}" if re.search(r'/v\d+(/|$)', b) else f"{b}/v1/{p}"


def _log_sse_json_error(exc, data_str):
    print(f"[SSE] JSON parse error: {exc}, line: {str(data_str)[:200]}")

def _parse_claude_sse(resp_lines):
    """Parse Anthropic SSE stream. Yields text chunks, returns list[content_block]."""
    content_blocks = []; current_block = None; tool_json_buf = ""
    stop_reason = None; got_message_stop = False; warn = None
    for line in resp_lines:
        if not line: continue
        line = line.decode('utf-8') if isinstance(line, bytes) else line
        if not line.startswith("data:"): continue
        data_str = line[5:].lstrip()
        if data_str == "[DONE]": break
        try: evt = json.loads(data_str)
        except Exception as e:
            _log_sse_json_error(e, data_str)
            continue
        evt_type = evt.get("type", "")
        if evt_type == "message_start":
            usage = evt.get("message", {}).get("usage", {})
            ci, cr, inp = usage.get("cache_creation_input_tokens", 0), usage.get("cache_read_input_tokens", 0), usage.get("input_tokens", 0)
            print(f"[Cache] input={inp} creation={ci} read={cr}")
        elif evt_type == "content_block_start":
            block = evt.get("content_block", {})
            if block.get("type") == "text": current_block = {"type": "text", "text": ""}
            elif block.get("type") == "thinking": current_block = {"type": "thinking", "thinking": ""}
            elif block.get("type") == "tool_use":
                current_block = {"type": "tool_use", "id": block.get("id", ""), "name": block.get("name", ""), "input": {}}
                tool_json_buf = ""
        elif evt_type == "content_block_delta":
            delta = evt.get("delta", {})
            if delta.get("type") == "text_delta":
                text = delta.get("text", "")
                if current_block and current_block.get("type") == "text": current_block["text"] += text
                if text: yield text
            elif delta.get("type") == "thinking_delta":
                if current_block and current_block.get("type") == "thinking": current_block["thinking"] += delta.get("thinking", "")
            elif delta.get("type") == "input_json_delta": tool_json_buf += delta.get("partial_json", "")
        elif evt_type == "content_block_stop":
            if current_block:
                if current_block["type"] == "tool_use":
                    try:
                        current_block["input"] = json.loads(tool_json_buf) if tool_json_buf else {}
                    except (json.JSONDecodeError, TypeError):
                        current_block["input"] = {"_raw": tool_json_buf}
                content_blocks.append(current_block)
                current_block = None
        elif evt_type == "message_delta":
            delta = evt.get("delta", {})
            stop_reason = delta.get("stop_reason", stop_reason)
            out_usage = evt.get("usage", {})
            out_tokens = out_usage.get("output_tokens", 0)
            if out_tokens: print(f"[Output] tokens={out_tokens} stop_reason={stop_reason}")
        elif evt_type == "message_stop": got_message_stop = True
        elif evt_type == "error":
            err = evt.get("error", {})
            emsg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            warn = f"\n\n[SSE Error: {emsg}]"; break
    if not warn:
        if not got_message_stop and not stop_reason: warn = "\n\n[!!! 流异常中断，未收到完整响应 !!!]"
        elif stop_reason == "max_tokens": warn = "\n\n[!!! Response truncated: max_tokens !!!]"
    if warn:
        print(f"[WARN] {warn.strip()}")
        content_blocks.append({"type": "text", "text": warn}); yield warn
    return content_blocks

def _parse_openai_sse(resp_lines, api_mode="chat_completions"):
    """Parse OpenAI SSE stream (chat_completions or responses API).
    Yields text chunks, returns list[content_block].
    content_block: {type:'text', text:str} | {type:'tool_use', id:str, name:str, input:dict}
    """
    content_text = ""
    if api_mode == "responses":
        seen_delta = False; fc_buf = {}; current_fc_idx = None
        for line in resp_lines:
            if not line: continue
            line = line.decode('utf-8', errors='replace') if isinstance(line, bytes) else line
            if not line.startswith("data:"): continue
            data_str = line[5:].lstrip()
            if data_str == "[DONE]": break
            try: evt = json.loads(data_str)
            except Exception as e:
                _log_sse_json_error(e, data_str)
                continue
            etype = evt.get("type", "")
            if etype == "response.output_text.delta":
                delta = evt.get("delta", "")
                if delta: seen_delta = True; content_text += delta; yield delta
            elif etype == "response.output_text.done" and not seen_delta:
                text = evt.get("text", "")
                if text: content_text += text; yield text
            elif etype == "response.output_item.added":
                item = evt.get("item", {})
                if item.get("type") == "function_call":
                    idx = evt.get("output_index", 0)
                    fc_buf[idx] = {"id": item.get("call_id", item.get("id", "")), "name": item.get("name", ""), "args": ""}
                    current_fc_idx = idx
            elif etype == "response.function_call_arguments.delta":
                idx = evt.get("output_index", current_fc_idx or 0)
                if idx in fc_buf: fc_buf[idx]["args"] += evt.get("delta", "")
            elif etype == "response.function_call_arguments.done":
                idx = evt.get("output_index", current_fc_idx or 0)
                if idx in fc_buf: fc_buf[idx]["args"] = evt.get("arguments", fc_buf[idx]["args"])
            elif etype == "error":
                err = evt.get("error", {})
                emsg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                if emsg: content_text += f"Error: {emsg}"; yield f"Error: {emsg}"
                break
            elif etype == "response.completed":
                usage = evt.get("response", {}).get("usage", {})
                cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
                inp = usage.get("input_tokens", 0)
                if inp: print(f"[Cache] input={inp} cached={cached}")
                break
        blocks = []
        if content_text: blocks.append({"type": "text", "text": content_text})
        for idx in sorted(fc_buf):
            fc = fc_buf[idx]
            try:
                inp = json.loads(fc["args"]) if fc["args"] else {}
            except (json.JSONDecodeError, TypeError):
                inp = {"_raw": fc["args"]}
            blocks.append({"type": "tool_use", "id": fc["id"], "name": fc["name"], "input": inp})
        return blocks
    else:
        tc_buf = {}  # index -> {id, name, args}
        reasoning_text = ""
        for line in resp_lines:
            if not line: continue
            line = line.decode('utf-8', errors='replace') if isinstance(line, bytes) else line
            if not line.startswith("data:"): continue
            data_str = line[5:].lstrip()
            if data_str == "[DONE]": break
            try: evt = json.loads(data_str)
            except Exception as e:
                _log_sse_json_error(e, data_str)
                continue
            ch = (evt.get("choices") or [{}])[0]
            delta = ch.get("delta") or {}
            if delta.get("reasoning_content"):
                reasoning_text += delta["reasoning_content"]
                yield {"_thinking_delta": delta["reasoning_content"]}
            if delta.get("content"):
                text = delta["content"]; content_text += text; yield text
            for tc in (delta.get("tool_calls") or []):
                idx = tc.get("index", 0)
                if idx not in tc_buf: tc_buf[idx] = {"id": tc.get("id", ""), "name": "", "args": ""}
                if tc.get("function", {}).get("name"): tc_buf[idx]["name"] = tc["function"]["name"]
                if tc.get("function", {}).get("arguments"): tc_buf[idx]["args"] += tc["function"]["arguments"]
            usage = evt.get("usage")
            if usage:
                cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
                print(f"[Cache] input={usage.get('prompt_tokens',0)} cached={cached}")
        blocks = []
        if reasoning_text: blocks.append({"type": "thinking", "thinking": reasoning_text})
        if content_text: blocks.append({"type": "text", "text": content_text})
        for idx in sorted(tc_buf):
            tc = tc_buf[idx]
            try:
                inp = json.loads(tc["args"]) if tc["args"] else {}
            except (json.JSONDecodeError, TypeError):
                inp = {"_raw": tc["args"]}
            blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": inp})
        return blocks

def _parse_openai_json(data, api_mode="chat_completions"):
    """Parse non-stream OpenAI-compatible JSON into content blocks."""
    if api_mode == "responses":
        usage = data.get("usage", {})
        cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
        inp = usage.get("input_tokens", 0)
        if inp: print(f"[Cache] input={inp} cached={cached}")
        blocks = []
        for item in (data.get("output") or []):
            if item.get("type") == "message":
                text = ""
                for part in (item.get("content") or []):
                    if part.get("type") in ("output_text", "text") and part.get("text"):
                        text += part["text"]
                if text: blocks.append({"type": "text", "text": text})
            elif item.get("type") == "function_call":
                args = item.get("arguments", "")
                try:
                    inp = json.loads(args) if args else {}
                except (json.JSONDecodeError, TypeError):
                    inp = {"_raw": args}
                blocks.append({"type": "tool_use", "id": item.get("call_id", item.get("id", "")), "name": item.get("name", ""), "input": inp})
        return blocks
    usage = data.get("usage") or {}
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    if usage: print(f"[Cache] input={usage.get('prompt_tokens',0)} cached={cached}")
    msg = ((data.get("choices") or [{}])[0]).get("message") or {}
    reasoning_content = msg.get("reasoning_content", "")
    content = msg.get("content", "")
    text = ""
    if isinstance(content, str): text = content
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") in ("text", "output_text") and part.get("text"):
                text += part["text"]
    blocks = []
    if reasoning_content: blocks.append({"type": "thinking", "thinking": reasoning_content})
    if text: blocks.append({"type": "text", "text": text})
    for tc in (msg.get("tool_calls") or []):
        fn = tc.get("function", {})
        args = fn.get("arguments", "")
        try:
            inp = json.loads(args) if args else {}
        except (json.JSONDecodeError, TypeError):
            inp = {"_raw": args}
        blocks.append({"type": "tool_use", "id": tc.get("id", ""), "name": fn.get("name", ""), "input": inp})
    return blocks

def _stamp_oai_cache_markers(messages, model):
    """Add cache_control to last 2 user messages for Anthropic models via OAI-compatible relay."""
    ml = model.lower()
    if not any(k in ml for k in ('claude', 'anthropic')): return
    user_idxs = [i for i, m in enumerate(messages) if m.get('role') == 'user']
    for idx in user_idxs[-2:]:
        c = messages[idx].get('content')
        if isinstance(c, str):
            messages[idx] = {**messages[idx], 'content': [{'type': 'text', 'text': c, 'cache_control': {'type': 'ephemeral'}}]}
        elif isinstance(c, list) and c:
            c = list(c); c[-1] = dict(c[-1], cache_control={'type': 'ephemeral'})
            messages[idx] = {**messages[idx], 'content': c}

def _normalize_thinking_blocks(messages):
    """Strip ``{"type":"thinking"}`` blocks from content arrays and move them to
    ``reasoning_content`` on assistant messages.  OpenAI-compatible endpoints
    (DeepSeek, etc.) reject ``thinking`` content-block variants in requests."""
    cleaned: list[dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            cleaned.append(msg)
            continue
        thinking_texts: list[str] = []
        clean_blocks: list[dict[str, Any]] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "thinking":
                t = str(block.get("thinking", "") or "")
                if t.strip():
                    thinking_texts.append(t)
            else:
                clean_blocks.append(block)
        if not thinking_texts:
            cleaned.append(msg)
            continue
        msg = dict(msg)
        msg["content"] = clean_blocks or ""
        if msg.get("role") == "assistant":
            new_reasoning = "\n".join(thinking_texts)
            existing = str(msg.get("reasoning_content", "") or "")
            msg["reasoning_content"] = (existing + "\n" + new_reasoning) if existing else new_reasoning
        cleaned.append(msg)
    return cleaned


# ── Provider switch sanitization: canonicalize + rebuild ──────────────────

def _canonicalize_history(history):
    """Convert any provider's ``session.history`` to canonical text-only messages.

    Strips provider-specific fields: ``{"type": "thinking"}`` blocks,
    ``reasoning_content``, ``cache_control``, and other metadata.
    Keeps: role, plain-text content, tool_calls, tool_results.
    """
    canonical = []
    for msg in history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        result = {"role": role}

        # Extract plain text from any content format
        if isinstance(content, str):
            text = content
            tool_results = []
        elif isinstance(content, list):
            text_parts = []
            tool_results = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type", "")
                if btype == "text":
                    text_parts.append(str(block.get("text", "") or ""))
                elif btype == "thinking":
                    pass  # DROP: provider-specific
                elif btype == "tool_result":
                    tr_content = block.get("content", "")
                    if isinstance(tr_content, list):
                        tr_text = "\n".join(
                            b.get("text", "") for b in tr_content
                            if isinstance(b, dict) and b.get("type") == "text"
                        )
                    else:
                        tr_text = str(tr_content)
                    tool_results.append({
                        "tool_use_id": str(block.get("tool_use_id", "") or ""),
                        "content": tr_text,
                    })
            text = "\n".join(p for p in text_parts if p)
        else:
            text = str(content)
            tool_results = []

        result["content"] = text

        if tool_results:
            result["tool_results"] = tool_results

        # Preserve tool_calls from assistant messages
        if role == "assistant" and msg.get("tool_calls"):
            result["tool_calls"] = msg["tool_calls"]

        # Preserve tool_call_id for tool messages
        if role == "tool" and msg.get("tool_call_id"):
            result["tool_call_id"] = msg["tool_call_id"]

        # DROP: reasoning_content (provider-specific reasoning format)

        canonical.append(result)
    return canonical


def rebuild_history_for_session(canonical, session):
    """Rebuild canonical messages into the native format for ``session``.

    The result is a list of message dicts ready to assign to
    ``session.history``.
    """
    rebuilt = []
    for msg in canonical:
        role = msg["role"]
        content = msg["content"]
        tool_results = msg.get("tool_results", [])

        if role == "user":
            blocks = [{"type": "text", "text": content}]
            for tr in tool_results:
                blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tr["tool_use_id"],
                    "content": tr["content"],
                })
            rebuilt.append({"role": "user", "content": blocks})

        elif role == "assistant":
            blocks = []
            if content:
                blocks.append({"type": "text", "text": content})
            for tc in (msg.get("tool_calls") or []):
                tc_name = tc.get("function", {}).get("name", tc.get("name", ""))
                tc_args = tc.get("function", {}).get("arguments", {})
                if isinstance(tc_args, str):
                    try:
                        tc_args = json.loads(tc_args)
                    except Exception:
                        tc_args = {"_raw": tc_args}
                blocks.append({
                    "type": "tool_use",
                    "id": str(tc.get("id", "") or ""),
                    "name": str(tc_name),
                    "input": tc_args,
                })
            if not blocks:
                blocks = [{"type": "text", "text": ""}]
            rebuilt.append({"role": "assistant", "content": blocks})

        elif role == "tool":
            rebuilt.append({
                "role": "tool",
                "tool_call_id": msg.get("tool_call_id", ""),
                "content": content,
            })

        else:
            rebuilt.append(msg)

    return rebuilt


def _openai_stream(api_base, api_key, messages, model, api_mode='chat_completions', *,
                   temperature=0.5, max_tokens=None, tools=None, reasoning_effort=None,
                   max_retries=0, connect_timeout=10, read_timeout=300, proxies=None, stream=True,
                   audit_session=None, call_site="llmcore._openai_stream"):
    """Shared OpenAI-compatible request with retry. Yields text chunks, returns list[content_block]."""
    start_perf = time.perf_counter()
    response_parts = []
    ml = model.lower()
    # ── Defense-in-depth: strip leaked thinking blocks ──
    messages = _normalize_thinking_blocks(messages)
    _protocol_snapshot(
        model=model, api_base=api_base, api_key=api_key,
        session=audit_session, messages=messages, tools=tools,
        label="_openai_stream",
    )
    if 'kimi' in ml or 'moonshot' in ml: temperature = 1
    elif 'minimax' in ml: temperature = max(0.01, min(temperature, 1.0))  # MiniMax requires temp in (0, 1]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if stream: headers["Accept"] = "text/event-stream"
    if api_mode == "responses":
        url = auto_make_url(api_base, "responses")
        payload = {"model": model, "input": _to_responses_input(messages), "stream": stream, "prompt_cache_key": _RESP_CACHE_KEY}
        if reasoning_effort: payload["reasoning"] = {"effort": reasoning_effort}
    else:
        url = auto_make_url(api_base, "chat/completions")
        _stamp_oai_cache_markers(messages, model)
        payload = {"model": model, "messages": messages, "stream": stream}
        if stream: payload["stream_options"] = {"include_usage": True}
        if temperature != 1: payload["temperature"] = temperature
        if max_tokens: payload["max_tokens"] = max_tokens
        if reasoning_effort: payload["reasoning_effort"] = reasoning_effort
    if tools:
        if api_mode == "responses":
            # Responses API: flatten {type, function: {name, ...}} -> {type, name, ...}
            resp_tools = []
            for t in tools:
                if t.get("type") == "function" and "function" in t:
                    rt = {"type": "function"}
                    rt.update(t["function"])
                    resp_tools.append(rt)
                else: resp_tools.append(t)
            payload["tools"] = resp_tools
        else: payload["tools"] = tools
    RETRYABLE_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504, 529}
    def _should_retry(status, body, attempt, max_retries, streamed):
        """Decide retry using semantic classification + legacy retryable set."""
        if attempt >= max_retries or streamed:
            return False
        if status is not None and status in RETRYABLE_STATUSES:
            return True
        if status is None:
            return True  # connection-level errors are always retryable
        return False

    def _delay(resp, attempt):
        try:
            ra = float((resp.headers or {}).get("retry-after"))
        except (ValueError, TypeError):
            ra = None
        return max(0.5, ra if ra is not None else min(30.0, 1.5 * (2 ** attempt)))
    _sess = requests.Session()
    _sess.trust_env = False
    try:
     for attempt in range(max_retries + 1):
        streamed = False
        try:
            with _sess.post(url, headers=headers, json=payload, stream=stream, proxies=proxies,
                       timeout=(connect_timeout, read_timeout)) as r:
                if r.status_code >= 400:
                    err_body = ""
                    try: err_body = r.text.strip()[:1200]
                    except AttributeError: pass
                    cat, act = classify_http_error(r.status_code, err_body)
                    if _should_retry(r.status_code, err_body, attempt, max_retries, False):
                        d = _delay(r, attempt)
                        print(f"[LLM Retry] {cat.name} HTTP {r.status_code}, retry in {d:.1f}s ({attempt+1}/{max_retries+1})")
                        time.sleep(d); continue
                    # Build semantic error message
                    if act is ErrorAction.SUGGEST_KEY_CHECK:
                        hint = "Check that the API key is valid and not expired."
                    elif act is ErrorAction.SUGGEST_MATCH:
                        hint = "Check that the model matches the key's authorized models/channels."
                    elif act is ErrorAction.REPORT_WITH_SNAPSHOT:
                        hint = "Protocol mismatch — message format is incompatible with this provider."
                    else:
                        hint = ""
                    try: r.raise_for_status()
                    except requests.HTTPError as e:
                        e._err_body = err_body
                        e._err_category = cat.name
                        e._err_hint = hint
                        raise
                if stream:
                    gen = _parse_openai_sse(r.iter_lines(), api_mode)
                    try:
                        while True:
                            chunk = next(gen)
                            streamed = True
                            if chunk:
                                response_parts.append(str(chunk))
                            yield chunk
                    except StopIteration as e:
                        blocks = e.value or []
                        if audit_session is not None:
                            _safe_audit_llm_call(
                                session=audit_session,
                                call_site=call_site,
                                messages=messages,
                                response="".join(response_parts) or blocks,
                                duration_ms=(time.perf_counter() - start_perf) * 1000.0,
                                tools=tools,
                                streaming=stream,
                            )
                        return blocks
                else:
                    blocks = _parse_openai_json(r.json(), api_mode)
                    for b in blocks:
                        if b.get("type") == "text" and b.get("text"):
                            response_parts.append(str(b["text"]))
                            yield b["text"]
                    if audit_session is not None:
                        _safe_audit_llm_call(
                            session=audit_session,
                            call_site=call_site,
                            messages=messages,
                            response="".join(response_parts) or blocks,
                            duration_ms=(time.perf_counter() - start_perf) * 1000.0,
                            tools=tools,
                            streaming=stream,
                        )
                    return blocks
        except requests.HTTPError as e:
            resp = getattr(e, "response", None); status = getattr(resp, "status_code", None)
            body = ""; rid = ""; ra = ""; ct = ""
            try:
                body = getattr(e, '_err_body', '') or (resp.text or "").strip()[:1200]
            except (AttributeError, ValueError):
                pass
            try:
                h = resp.headers or {}
                rid = h.get("x-request-id","") or h.get("request-id","")
                ra = h.get("retry-after","")
                ct = h.get("content-type","")
            except AttributeError:
                pass
            cat, act = classify_http_error(status, body)
            if _should_retry(status, body, attempt, max_retries, streamed):
                d = _delay(resp, attempt)
                print(f"[LLM Retry] {cat.name} HTTP {status}, retry in {d:.1f}s ({attempt+1}/{max_retries+1})")
                time.sleep(d); continue
            hint = getattr(e, '_err_hint', '')
            if not hint:
                if act is ErrorAction.SUGGEST_KEY_CHECK:
                    hint = "Check that the API key is valid and not expired."
                elif act is ErrorAction.SUGGEST_MATCH:
                    hint = "Check that the model matches the key's authorized models/channels."
                elif act is ErrorAction.REPORT_WITH_SNAPSHOT:
                    hint = "Protocol mismatch — message format is incompatible with this provider."
            err = f"Error: HTTP {status} ({cat.name}) {e}; content_type: {ct or '<empty>'}; retry_after: {ra or '<empty>'}; request_id: {rid or '<empty>'}; body: {body or '<empty>'}"
            if hint:
                err += f" -- {hint}"
            yield err
            if audit_session is not None:
                _safe_audit_llm_call(
                    session=audit_session,
                    call_site=call_site,
                    messages=messages,
                    response=err,
                    duration_ms=(time.perf_counter() - start_perf) * 1000.0,
                    tools=tools,
                    streaming=stream,
                )
            return [{"type": "text", "text": err}]
        except (requests.Timeout, requests.ConnectionError) as e:
            if _should_retry(None, "", attempt, max_retries, streamed):
                d = _delay(None, attempt)
                print(f"[LLM Retry] CONNECTION_ERROR {type(e).__name__}, retry in {d:.1f}s ({attempt+1}/{max_retries+1})")
                time.sleep(d); continue
            err = f"Error: CONNECTION_ERROR {type(e).__name__}: {e}"
            yield err
            if audit_session is not None:
                _safe_audit_llm_call(
                    session=audit_session,
                    call_site=call_site,
                    messages=messages,
                    response=err,
                    duration_ms=(time.perf_counter() - start_perf) * 1000.0,
                    tools=tools,
                    streaming=stream,
                )
            return [{"type": "text", "text": err}]
        except Exception as e:
            err = f"Error: {e}"
            yield err
            if audit_session is not None:
                _safe_audit_llm_call(
                    session=audit_session,
                    call_site=call_site,
                    messages=messages,
                    response=err,
                    duration_ms=(time.perf_counter() - start_perf) * 1000.0,
                    tools=tools,
                    streaming=stream,
                )
            return [{"type": "text", "text": err}]
    finally:
        _sess.close()


def _to_responses_input(messages):
    result = []
    for msg in messages:
        role = str(msg.get("role", "user")).lower()
        if role == "tool":
            result.append({"type": "function_call_output", "call_id": msg.get("tool_call_id", ""), "output": msg.get("content", "")})
            continue
        if role not in ["user", "assistant", "system", "developer"]: role = "user"
        if role == "system": role = "developer"  # Responses API uses 'developer' instead of 'system'
        content = msg.get("content", "")
        text_type = "output_text" if role == "assistant" else "input_text"
        parts = []
        if isinstance(content, str):
            if content: parts.append({"type": text_type, "text": content})
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict): continue
                ptype = part.get("type")
                if ptype == "text":
                    text = part.get("text", "")
                    if text: parts.append({"type": text_type, "text": text})
                elif ptype == "image_url":
                    url = (part.get("image_url") or {}).get("url", "")
                    if url and role != "assistant": parts.append({"type": "input_image", "image_url": url})
        if len(parts) == 0: parts = [{"type": text_type, "text": str(content)}]
        result.append({"role": role, "content": parts})
        for tc in (msg.get("tool_calls") or []):
            f = tc.get("function", {})
            result.append({"type": "function_call", "call_id": tc.get("id", ""), "name": f.get("name", ""), "arguments": f.get("arguments", "")})
    return result


def _msgs_claude2oai(messages):
    result = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": str(content)}]
        if role == "assistant":
            text_parts, tool_calls = [], []
            reasoning_parts = []
            for b in blocks:
                if not isinstance(b, dict): continue
                if b.get("type") == "text": text_parts.append({"type": "text", "text": b.get("text", "")})
                elif b.get("type") == "thinking":
                    reasoning_parts.append(b.get("thinking", ""))
                elif b.get("type") == "tool_use":
                    tool_calls.append({
                        "id": b.get("id", ""), "type": "function",
                        "function": {"name": b.get("name", ""), "arguments": json.dumps(b.get("input", {}), ensure_ascii=False)}
                    })
            m = {"role": "assistant"}
            if text_parts: m["content"] = text_parts
            else: m["content"] = ""
            if tool_calls: m["tool_calls"] = tool_calls
            if reasoning_parts: m["reasoning_content"] = "\n".join(reasoning_parts)
            result.append(m)
        elif role == "user":
            text_parts = []
            for b in blocks:
                if not isinstance(b, dict): continue
                if b.get("type") == "tool_result":
                    if text_parts:
                        result.append({"role": "user", "content": text_parts})
                        text_parts = []
                    tr = b.get("content", "")
                    if isinstance(tr, list):
                        tr = "\n".join(x.get("text", "") for x in tr if isinstance(x, dict) and x.get("type") == "text")
                    result.append({"role": "tool", "tool_call_id": b.get("tool_use_id", ""), "content": tr if isinstance(tr, str) else str(tr)})
                elif b.get("type") == "image":
                    src = b.get("source") or {}
                    if src.get("type") == "base64" and src.get("data"):
                        text_parts.append({"type": "image_url", "image_url": {"url": f"data:{src.get('media_type', 'image/png')};base64,{src.get('data', '')}"}})
                elif b.get("type") == "image_url": text_parts.append(b)
                elif b.get("type") == "text": text_parts.append({"type": "text", "text": b.get("text", "")})
            if text_parts: result.append({"role": "user", "content": text_parts})
        else: result.append(msg)
    return result


class BaseSession:
    def __init__(self, cfg):
        self.api_key = cfg['apikey']
        self.api_base = cfg['apibase'].rstrip('/')
        self.model = cfg.get('model', '')
        self.context_win = cfg.get('context_win', 24000)
        self.history = []
        self.lock = threading.Lock()
        self.system = ""
        self.name = cfg.get('name', self.model)
        proxy = cfg.get('proxy')
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        self.max_retries = max(0, int(cfg.get('max_retries', 1)))
        self.stream = cfg.get('stream', True)
        default_ct, default_rt = (5, 30) if self.stream else (10, 240)
        self.connect_timeout = max(1, int(cfg.get('connect_timeout', cfg.get('timeout', default_ct))))
        self.read_timeout = max(5, int(cfg.get('read_timeout', default_rt)))
        def _enum(key, valid):
            v = cfg.get(key); v = None if v is None else str(v).strip().lower()
            return v if not v or v in valid else print(f"[WARN] Invalid {key} {v!r}, ignored.")
        self.reasoning_effort = _enum('reasoning_effort', {'none', 'minimal', 'low', 'medium', 'high', 'xhigh'})
        self.thinking_type = _enum('thinking_type', {'adaptive', 'enabled', 'disabled'})
        self.thinking_budget_tokens = cfg.get('thinking_budget_tokens')
        mode = str(cfg.get('api_mode', 'chat_completions')).strip().lower().replace('-', '_')
        self.api_mode = 'responses' if mode in ('responses', 'response') else 'chat_completions'
        self.temperature = cfg.get('temperature', 1)
        self.max_tokens = cfg.get('max_tokens', 8192)
        self._audit_context = {}
    def _apply_claude_thinking(self, payload):
        if self.thinking_type:
            thinking = {"type": self.thinking_type}
            if self.thinking_type == 'enabled':
                if self.thinking_budget_tokens is None: print("[WARN] thinking_type='enabled' requires thinking_budget_tokens, ignored.")
                else:
                    thinking["budget_tokens"] = self.thinking_budget_tokens; payload["thinking"] = thinking
            else: payload["thinking"] = thinking
        if self.reasoning_effort:
            effort = {'low': 'low', 'medium': 'medium', 'high': 'high', 'xhigh': 'max'}.get(self.reasoning_effort)
            if effort: payload["output_config"] = {"effort": effort}
            else: print(f"[WARN] reasoning_effort {self.reasoning_effort!r} is unsupported for Claude output_config.effort, ignored.")
    def ask(self, prompt, stream=False):
        def _ask_gen():
            with self.lock:
                self.history.append({"role": "user", "content": [{"type": "text", "text": prompt}]})
                trim_messages_history(self.history, self.context_win)
                messages = self.make_messages(self.history)
            content_blocks = None; content = ''
            gen = self.raw_ask(messages)
            try:
                while True: chunk = next(gen); content += chunk; yield chunk
            except StopIteration as e: content_blocks = e.value or []
            if len(content_blocks) > 1: print(f"[DEBUG BaseSession.ask] content_blocks: {content_blocks}")
            for block in (content_blocks or []):
                if block.get('type', '') == 'tool_use':
                    tu = {'name': block.get('name', ''), 'arguments': block.get('input', {})}
                    yield f'<tool_use>{json.dumps(tu, ensure_ascii=False)}</tool_use>'
            if not content.startswith("Error:"): self.history.append({"role": "assistant", "content": [{"type": "text", "text": content}]})
        return _ask_gen() if stream else ''.join(list(_ask_gen()))

class ClaudeSession(BaseSession):
    def raw_ask(self, messages):
        start_perf = time.perf_counter()
        _protocol_snapshot(
            model=self.model, api_base=self.api_base, api_key=self.api_key,
            session=self, messages=messages, label="ClaudeSession.raw_ask",
        )
        headers = {"x-api-key": self.api_key, "Content-Type": "application/json", "anthropic-version": "2023-06-01", "anthropic-beta": "prompt-caching-2024-07-31"}
        payload = {"model": self.model, "messages": messages, "max_tokens": self.max_tokens, "stream": True}
        if self.temperature != 1: payload["temperature"] = self.temperature
        self._apply_claude_thinking(payload)
        if self.system: payload["system"] = [{"type": "text", "text": self.system, "cache_control": {"type": "persistent"}}]
        try:
            with requests.Session() as sess:
                sess.trust_env = False
                with sess.post(auto_make_url(self.api_base, "messages"), headers=headers, json=payload, stream=True,
                               timeout=(self.connect_timeout, self.read_timeout), proxies=self.proxies) as r:
                    if r.status_code != 200: raise Exception(f"HTTP {r.status_code} {r.content.decode('utf-8', errors='replace')[:500]}")
                    blocks = (yield from _parse_claude_sse(r.iter_lines())) or []
                    _safe_audit_llm_call(
                        session=self,
                        call_site="llmcore.ClaudeSession.raw_ask",
                        messages=messages,
                        response=_audit_response_text(blocks) or blocks,
                        duration_ms=(time.perf_counter() - start_perf) * 1000.0,
                        tools=None,
                        streaming=True,
                    )
                    return blocks
        except Exception as e:
            yield (err := f"Error: {e}")
            _safe_audit_llm_call(
                session=self,
                call_site="llmcore.ClaudeSession.raw_ask",
                messages=messages,
                response=err,
                duration_ms=(time.perf_counter() - start_perf) * 1000.0,
                tools=None,
                streaming=True,
            )
            return [{"type": "text", "text": err}]
    def make_messages(self, raw_list):
        msgs = [{"role": m['role'], "content": _normalize_content_blocks(m.get('content'))} for m in raw_list]
        user_idxs = [i for i, m in enumerate(msgs) if m['role'] == 'user']
        for idx in user_idxs[-2:]:
            msgs[idx]["content"] = _with_ephemeral_last_block(msgs[idx]["content"])
        return msgs

class LLMSession(BaseSession):
    def raw_ask(self, messages):
        msgs = _msgs_claude2oai(messages)
        return (yield from _openai_stream(self.api_base, self.api_key, msgs, self.model, self.api_mode,
                                  temperature=self.temperature, reasoning_effort=self.reasoning_effort,
                                  max_tokens=self.max_tokens, max_retries=self.max_retries,
                                  connect_timeout=self.connect_timeout, read_timeout=self.read_timeout,
                                  proxies=self.proxies, stream=self.stream,
                                  audit_session=self, call_site="llmcore.LLMSession.raw_ask"))
    def make_messages(self, raw_list): return _msgs_claude2oai(raw_list)

def _fix_messages(messages):
    """修复 messages 符合 Claude API：交替、tool_use/tool_result 配对"""
    if not messages: return messages
    _wrap = lambda c: c if isinstance(c, list) else [{"type": "text", "text": str(c)}]
    fixed = []
    for m in messages:
        if fixed and m['role'] == fixed[-1]['role']:
            fixed[-1] = {**fixed[-1], 'content': _wrap(fixed[-1]['content']) + [{"type": "text", "text": "\n"}] + _wrap(m['content'])}; continue
        if fixed and fixed[-1]['role'] == 'assistant' and m['role'] == 'user':
            uses = [b.get('id') for b in fixed[-1].get('content', []) if isinstance(b, dict) and b.get('type') == 'tool_use' and b.get('id')]
            has = {b.get('tool_use_id') for b in _wrap(m['content']) if isinstance(b, dict) and b.get('type') == 'tool_result'}
            miss = [uid for uid in uses if uid not in has]
            if miss: m = {**m, 'content': [{"type": "tool_result", "tool_use_id": uid, "content": "(error)"} for uid in miss] + _wrap(m['content'])}
        fixed.append(m)
    while fixed and fixed[0]['role'] != 'user': fixed.pop(0)
    return fixed

class NativeClaudeSession(BaseSession):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.context_win = cfg.get("context_win", 28000)
        self.fake_cc_system_prompt = cfg.get("fake_cc_system_prompt", False)
        self._session_id = str(uuid.uuid4())
        self._account_uuid = str(uuid.uuid4())
        self._device_id = uuid.uuid4().hex + uuid.uuid4().hex[:32]
        self.tools = None
    def raw_ask(self, messages):
        start_perf = time.perf_counter()
        messages = _fix_messages(messages)
        _protocol_snapshot(
            model=self.model, api_base=self.api_base, api_key=self.api_key,
            session=self, messages=messages, tools=self.tools,
            label="NativeClaudeSession.raw_ask",
        )
        model = self.model
        beta_parts = ["claude-code-20250219", "interleaved-thinking-2025-05-14", "redact-thinking-2026-02-12", "prompt-caching-scope-2026-01-05"]
        if "[1m]" in model.lower():
            beta_parts.insert(1, "context-1m-2025-08-07"); model = model.replace("[1m]", "").replace("[1M]", "")
        headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01",
            "anthropic-beta": ",".join(beta_parts), "anthropic-dangerous-direct-browser-access": "true",
            "user-agent": "claude-cli/2.1.114 (external, cli)", "x-app": "cli"}
        if self.api_key.startswith("sk-ant-"): headers["x-api-key"] = self.api_key
        else: headers["authorization"] = f"Bearer {self.api_key}"
        payload = {"model": model, "messages": messages, "max_tokens": self.max_tokens, "stream": self.stream}
        if self.temperature != 1: payload["temperature"] = self.temperature
        self._apply_claude_thinking(payload)
        payload["metadata"] = {"user_id": json.dumps({"device_id": self._device_id, "account_uuid": self._account_uuid, "session_id": self._session_id}, separators=(',', ':'))}
        if self.tools:
            claude_tools = openai_tools_to_claude(self.tools)
            tools = [dict(t) for t in claude_tools]; tools[-1]["cache_control"] = {"type": "ephemeral"}
            payload["tools"] = tools
        payload['system'] = [{"type": "text", "text": "You are Claude Code, Anthropic's official CLI for Claude.", "cache_control": {"type": "ephemeral"}}]
        if self.system:
            if self.fake_cc_system_prompt:
                messages[0]["content"] = _normalize_content_blocks(messages[0].get("content"))
                messages[0]["content"].insert(0, {"type": "text", "text": self.system})
            else: payload["system"] = [{"type": "text", "text": self.system}]
        user_idxs = [i for i, m in enumerate(messages) if m['role'] == 'user']
        for idx in user_idxs[-2:]:
            messages[idx] = {**messages[idx], "content": _with_ephemeral_last_block(messages[idx].get("content"))}
        try:
            with requests.Session() as sess:
                sess.trust_env = False
                with sess.post(auto_make_url(self.api_base, "messages")+'?beta=true', headers=headers, json=payload,
                               stream=self.stream, timeout=(self.connect_timeout, self.read_timeout), proxies=self.proxies) as resp:
                    if resp.status_code != 200: raise Exception(f"HTTP {resp.status_code} {resp.content.decode('utf-8', errors='replace')[:500]}")
                    if self.stream:
                        blocks = (yield from _parse_claude_sse(resp.iter_lines())) or []
                        _safe_audit_llm_call(
                            session=self,
                            call_site="llmcore.NativeClaudeSession.raw_ask",
                            messages=messages,
                            response=_audit_response_text(blocks) or blocks,
                            duration_ms=(time.perf_counter() - start_perf) * 1000.0,
                            tools=self.tools,
                            streaming=True,
                        )
                        return blocks
                    else:
                        data = resp.json(); content_blocks = data.get("content", [])
                        usage = data.get("usage", {})
                        print(f"[Cache] input={usage.get('input_tokens',0)} creation={usage.get('cache_creation_input_tokens',0)} read={usage.get('cache_read_input_tokens',0)}")
                        for b in content_blocks:
                            if b.get("type") == "text": yield b.get("text", "")
                            elif b.get("type") == "thinking": yield ""
                        _safe_audit_llm_call(
                            session=self,
                            call_site="llmcore.NativeClaudeSession.raw_ask",
                            messages=messages,
                            response=_audit_response_text(content_blocks) or content_blocks,
                            duration_ms=(time.perf_counter() - start_perf) * 1000.0,
                            tools=self.tools,
                            streaming=False,
                        )
                        return content_blocks
        except Exception as e:
            yield (err := f"Error: {e}")
            _safe_audit_llm_call(
                session=self,
                call_site="llmcore.NativeClaudeSession.raw_ask",
                messages=messages,
                response=err,
                duration_ms=(time.perf_counter() - start_perf) * 1000.0,
                tools=self.tools,
                streaming=self.stream,
            )
            return [{"type": "text", "text": err}]

    def ask(self, msg):
        assert type(msg) is dict
        with self.lock:
            self.history.append(msg)
            trim_messages_history(self.history, self.context_win)
            messages = [{"role": m["role"], "content": _normalize_content_blocks(m.get("content"))} for m in self.history]
        content_blocks = None
        gen = self.raw_ask(messages)
        try:
            while True: yield next(gen)
        except StopIteration as e: content_blocks = e.value or []
        if content_blocks and not (len(content_blocks) == 1 and content_blocks[0].get("text", "").startswith("Error:")):
            self.history.append({"role": "assistant", "content": content_blocks})
        text_parts = [b["text"] for b in content_blocks if b.get("type") == "text"]
        content = "\n".join(text_parts).strip()
        tool_calls = [MockToolCall(b["name"], b.get("input", {}), id=b.get("id", "")) for b in content_blocks if b.get("type") == "tool_use"]
        if not tool_calls: tool_calls, content = _parse_text_tool_calls(content)
        thinking_parts = [b["thinking"] for b in content_blocks if b.get("type") == "thinking"]
        thinking = "\n".join(thinking_parts).strip()
        if not thinking:
            think_pattern = r"<think(?:ing)?>(.*?)</think(?:ing)?>"
            think_match = re.search(think_pattern, content, re.DOTALL)
            if think_match:
                thinking = think_match.group(1).strip()
                content = re.sub(think_pattern, "", content, flags=re.DOTALL)
        return MockResponse(thinking, content, tool_calls, str(content_blocks))

class NativeOAISession(NativeClaudeSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    def raw_ask(self, messages):
        """OpenAI streaming. yields text chunks, generator return = list[content_block]"""
        msgs = ([{"role": "system", "content": self.system}] if self.system else []) + _msgs_claude2oai(messages)
        return (yield from _openai_stream(self.api_base, self.api_key, msgs, self.model, self.api_mode,
                                          temperature=self.temperature, max_tokens=self.max_tokens, 
                                          tools=self.tools, reasoning_effort=self.reasoning_effort,
                                          max_retries=self.max_retries, connect_timeout=self.connect_timeout,
                                          read_timeout=self.read_timeout, proxies=self.proxies, stream=self.stream,
                                          audit_session=self, call_site="llmcore.NativeOAISession.raw_ask"))

def openai_tools_to_claude(tools):
    """[{type:'function', function:{name,description,parameters}}] → [{name,description,input_schema}]."""
    result = []
    for t in tools:
        if 'input_schema' in t: result.append(t); continue  # 已是claude格式
        fn = t.get('function', t)
        result.append({'name': fn['name'], 'description': fn.get('description', ''),
            'input_schema': fn.get('parameters', {'type': 'object', 'properties': {}})})
    return result


class MockFunction:
    def __init__(self, name, arguments): self.name, self.arguments = name, arguments  
         
class MockToolCall:
    def __init__(self, name, args, id=''):
        arg_str = json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else args
        self.function = MockFunction(name, arg_str); self.id = id

class MockResponse:
    def __init__(self, thinking, content, tool_calls, raw, stop_reason='end_turn'):
        self.thinking = thinking; self.content = content          
        self.tool_calls = tool_calls; self.raw = raw
        self.stop_reason = 'tool_use' if tool_calls else stop_reason
    def __repr__(self):    
        return f"<MockResponse thinking={bool(self.thinking)}, content='{self.content}', tools={bool(self.tool_calls)}>"

class ToolClient:
    def __init__(self, backend, auto_save_tokens=True):
        self.backend = backend
        self.auto_save_tokens = auto_save_tokens
        self.last_tools = ''
        self.name = self.backend.name
        self.total_cd_tokens = 0

    def chat(self, messages, tools=None):
        full_prompt = self._build_protocol_prompt(messages, tools)
        # ── P2-cache: check exact + semantic hash before LLM call ──
        try:
            from .runtime.llm_cache_bridge import llm_cache_enabled, try_get_cached, store_cache
            if llm_cache_enabled():
                cached = try_get_cached(full_prompt, getattr(self.backend, 'model', 'unknown'), tools)
                if cached is not None:
                    cached_text = cached.get("response", "")
                    if cached_text:
                        for i in range(0, len(cached_text), 40):
                            yield cached_text[i:i+40]
                        return self._parse_mixed_response(cached_text)
        except Exception:
            pass
        print("Full prompt length:", len(full_prompt), 'chars')
        prompt_log = full_prompt
        gen = self.backend.ask(full_prompt, stream=True)
        _write_llm_log('Prompt', prompt_log)
        raw_text = ''; summarytag = '[NextWillSummary]'
        for chunk in gen:
            raw_text += chunk
            if chunk != summarytag: yield chunk
        if raw_text.endswith(summarytag):
            self.last_tools = ''; raw_text = raw_text[:-len(summarytag)]
        _write_llm_log('Response', raw_text)
        try:
            from .runtime.llm_cache_bridge import llm_cache_enabled, store_cache
            if llm_cache_enabled():
                store_cache(full_prompt, getattr(self.backend, 'model', 'unknown'), raw_text, tools)
        except Exception:
            pass
        return self._parse_mixed_response(raw_text)

    def _estimate_content_len(self, content):
        if isinstance(content, str): return len(content)
        if isinstance(content, list):
            total = 0
            for part in content:
                if not isinstance(part, dict): continue
                if part.get("type") == "text":
                    total += len(part.get("text", ""))
                elif part.get("type") == "image_url":
                    total += 1000
            return total
        return len(str(content))
    
    def _prepare_tool_instruction(self, tools):
        tool_instruction = ""
        if not tools: return tool_instruction
        tools_json = json.dumps(tools, ensure_ascii=False, separators=(',', ':'))
        _en = os.environ.get('GA_LANG') == 'en'
        critical_rules = """
Critical tool rules:
- code_run: NEVER call with empty arguments. Provide arguments.script, or put exactly one fenced code block immediately before the tool call.
- code_run defaults to runtime scratch cwd ./temp. For the repo root/current project folder, use cwd:'../'.
- If you only need to inspect existing file contents, prefer file_read over code_run.
"""
        format_instruction = '\nFormat: ```<tool_use>{{"name": "tool_name", "arguments": {{...}}}}</tool_use>```\n'
        if _en:
            tool_instruction = f"""
### Interaction Protocol (must follow strictly, always in effect)
Follow these steps to think and act:
1. **Think**: Analyze the current situation and strategy inside `<thinking>` tags.
2. **Summarize**: Output a minimal one-line (<30 words) physical snapshot in `<summary>`: new info from last tool result + current tool call intent. This goes into long-term working memory. Must contain real information, no filler.
3. **Act**: If you need to call tools, output one or more **<tool_use> blocks** after your reply, then stop.
"""
        else:
            tool_instruction = f"""
### 交互协议 (必须严格遵守，持续有效)
请按照以下步骤思考并行动：
1. **思考**: 在 `<thinking>` 标签中先进行思考，分析现状和策略。
2. **总结**: 在 `<summary>` 中输出*极为简短*的高度概括的单行（<30字）物理快照，包括上次工具调用结果产生的新信息+本次工具调用意图。此内容将进入长期工作记忆，记录关键信息，严禁输出无实际信息增量的描述。
3. **行动**: 如需调用工具，请在回复正文之后输出一个（或多个）**<tool_use>块**，然后结束。
"""
        tool_instruction += f'\nFormat: ```<tool_use>{{"name": "tool_name", "arguments": {{...}}}}</tool_use>```\n\n### Tools (mounted, always in effect):\n{tools_json}\n'
        if self.auto_save_tokens and self.last_tools == tools_json:
            tool_instruction = "\n### Tools: still active, **ready to call**. Protocol unchanged.\n" if _en else "\n### 工具库状态：持续有效（code_run/file_read等），**可正常调用**。调用协议沿用。\n"
        else: self.total_cd_tokens = 0
        self.last_tools = tools_json
        return tool_instruction

    def _compact_tool_glossary(self, tools):
        lines = []
        for tool in tools or []:
            fn = tool.get("function", tool) if isinstance(tool, dict) else {}
            if not isinstance(fn, dict):
                continue
            name = str(fn.get("name") or "").strip()
            if not name:
                continue
            desc = " ".join(str(fn.get("description") or "").split()).strip()
            if len(desc) > 140:
                desc = desc[:137].rstrip() + "..."
            if desc:
                lines.append(f"- {name}: {desc}")
            else:
                lines.append(f"- {name}")
        if not lines:
            return ""
        title = "### Mounted tools (still active):\n" if os.environ.get('GA_LANG') == 'en' else "### 当前可调用工具（持续生效）：\n"
        return title + "\n".join(lines) + "\n"

    def _prepare_tool_instruction_v2(self, tools):
        tool_instruction = ""
        if not tools:
            return tool_instruction
        tools_json = json.dumps(tools, ensure_ascii=False, separators=(',', ':'))
        _en = os.environ.get('GA_LANG') == 'en'
        format_instruction = '\nFormat: ```<tool_use>{{"name": "tool_name", "arguments": {{...}}}}</tool_use>```\n'
        if _en:
            critical_rules = (
                "\nCritical tool rules:\n"
                "- Prefer the smallest evidence-producing action. Do not assume tool results before seeing them.\n"
                "- Read before write: inspect the current file/context with file_read before editing.\n"
                "- Use file_patch for surgical edits; use file_write only for full-file or very large rewrites.\n"
                "- code_run: NEVER call with empty arguments. Provide arguments.script, or put exactly one fenced code block immediately before the tool call.\n"
                "- code_run defaults to runtime scratch cwd ./temp. For the repo root/current project folder, use cwd:'../'.\n"
                "- Prefer file_read over code_run when you only need to inspect existing files.\n"
                "- Use ask_user only for decisions, missing credentials, permissions, or true blockers you cannot resolve with tools.\n"
                "- After emitting one or more <tool_use> blocks, stop. Do not fabricate the tool result in the same turn.\n"
            )
            tool_instruction = (
                "\n### Interaction Protocol (must follow strictly, always in effect)\n"
                "Follow these steps on every turn:\n"
                "1. **Think** inside `<thinking>`: current objective, evidence gap, and best next step.\n"
                "2. **Summarize** inside `<summary>` using one factual line (usually <=30 words): last new fact or current grounded state + current intent. No filler like 'continue working'.\n"
                "3. **Act**: if tools are needed, choose the smallest high-information action, emit one or more **<tool_use> blocks**, then stop.\n"
                "4. **Answer directly** only when no tool is needed. Do not use tools just for ceremony.\n"
            )
            cached_prefix = (
                "\n### Tools: still active, ready to call.\n"
                "Protocol unchanged: factual summary, read before write, do not invent tool results.\n"
            )
        else:
            critical_rules = (
                "\n关键工具规则：\n"
                "- 优先做能产出客观证据的最小动作，不要在拿到结果前脑补结果。\n"
                "- 读先于写：改文件前先用 file_read 看最新上下文。\n"
                "- 小改优先 file_patch；只有整文件重写或超大块写入时才用 file_write。\n"
                "- code_run 绝不能空参调用；要么提供 arguments.script，要么在工具调用前紧贴一个代码块。\n"
                "- code_run 默认工作目录是 ./temp；需要项目根目录时显式传 cwd:'../'。\n"
                "- 只是查看已有文件时优先 file_read，不要滥用 code_run。\n"
                "- ask_user 只用于用户决策、缺失凭证/权限、不可逆操作确认或真实阻塞。\n"
                "- 输出一个或多个 <tool_use> 块后立即停止，不要在同一轮假装看到了工具结果。\n"
            )
            tool_instruction = (
                "\n### 交互协议（严格执行，持续有效）\n"
                "每一轮都按下面顺序执行：\n"
                "1. 在 <thinking> 中判断：当前目标、证据缺口、最优下一步。\n"
                "2. 在 <summary> 中写一行事实快照（通常 <=50 个中文字符）：上一轮得到的新事实或当前已知状态 + 本轮意图。禁止空话，例如“继续处理”“继续分析”。\n"
                "3. 如果需要工具，选择当前信息增量最大的最小动作，输出一个或多个 <tool_use> 块，然后停止等待结果。\n"
                "4. 如果不需要工具，直接回答用户；不要为了走流程而硬调工具。\n"
            )
            cached_prefix = (
                "\n### 工具库仍然生效，可直接调用。\n"
                "协议不变：summary 要写事实，先读后写，不要伪造工具结果。\n"
            )
        if self.auto_save_tokens and self.last_tools == tools_json:
            tool_instruction = cached_prefix + critical_rules + format_instruction + self._compact_tool_glossary(tools)
        else:
            self.total_cd_tokens = 0
            tool_instruction += critical_rules
            tool_instruction += f'{format_instruction}\n### Tools (mounted, always in effect):\n{tools_json}\n'
        self.last_tools = tools_json
        return tool_instruction

    def _build_protocol_prompt(self, messages, tools):
        system_content = next((m['content'] for m in messages if m['role'].lower() == 'system'), "")
        history_msgs = [m for m in messages if m['role'].lower() != 'system']
        tool_instruction = self._prepare_tool_instruction_v2(tools)
        system_parts = []
        if system_content:
            system_parts.append(f"{system_content}\n")
        system_parts.append(f"{tool_instruction}")
        system = "".join(system_parts)
        user_parts = []
        for m in history_msgs:
            role = "USER" if m['role'] == 'user' else "ASSISTANT"
            user_parts.append(f"=== {role} ===\n")
            for tr in m.get('tool_results', []):
                user_parts.append(f'<tool_result>{tr["content"]}</tool_result>\n')
            user_parts.append(str(m['content']) + "\n")
        user = "".join(user_parts)
        self.total_cd_tokens += self._estimate_content_len(user)
        if self.total_cd_tokens > 9000:
            self.last_tools = ''
            self.total_cd_tokens = 0
        user_parts.append("=== ASSISTANT ===\n")
        return system + "".join(user_parts)

    def _parse_mixed_response(self, text):
        remaining_text = text; thinking = ''
        think_pattern = r"<think(?:ing)?>(.*?)</think(?:ing)?>"
        think_match = re.search(think_pattern, text, re.DOTALL)
        
        if think_match:
            thinking = think_match.group(1).strip()
            remaining_text = re.sub(think_pattern, "", remaining_text, flags=re.DOTALL)
        
        tool_calls = []; json_strs = []; errors = []
        tool_pattern = r"<(?:tool_use|tool_call)>((?:(?!<(?:tool_use|tool_call)>).){15,}?)</(?:tool_use|tool_call)>"
        tool_all = re.findall(tool_pattern, remaining_text, re.DOTALL)
        
        if tool_all:
            tool_all = [s.strip() for s in tool_all]
            json_strs.extend([s for s in tool_all if s.startswith('{') and s.endswith('}')])
            remaining_text = re.sub(tool_pattern, "", remaining_text, flags=re.DOTALL)
        elif '<tool_use>' in remaining_text:
            weaktoolstr = remaining_text.split('<tool_use>')[-1].strip().strip('><')
            json_str = weaktoolstr if weaktoolstr.endswith('}') else ''
            if json_str == '' and '```' in weaktoolstr and weaktoolstr.split('```')[0].strip().endswith('}'):
                json_str = weaktoolstr.split('```')[0].strip()
            if json_str:
                json_strs.append(json_str)
            remaining_text = remaining_text.replace('<tool_use>'+weaktoolstr, "")
        elif '"name":' in remaining_text and '"arguments":' in remaining_text:
            json_match = re.search(r'\{.*"name":.*\}', remaining_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0).strip()
                json_strs.append(json_str)
                remaining_text = remaining_text.replace(json_str, "").strip()

        for json_str in json_strs:
            try:
                data = tryparse(json_str)
                func_name = data.get('name') or data.get('function') or data.get('tool')
                args = data.get('arguments') or data.get('args') or data.get('params') or data.get('parameters')
                if args is None: args = data
                if func_name: tool_calls.append(MockToolCall(func_name, args))
            except json.JSONDecodeError as e:
                errors.append({'err': f"[Warn] Failed to parse tool_use JSON: {json_str}", 'bad_json': f'Failed to parse tool_use JSON: {json_str[:200]}'})
                self.last_tools = ''   # llm肯定忘了tool schema了，再提供下
            except Exception as e:
                errors.append({'err': f'[Warn] Exception during tool_use parsing: {str(e)} {str(data)}'})
        if len(tool_calls) == 0:
            for e in errors:
                print(e['err'])
                if 'bad_json' in e: tool_calls.append(MockToolCall('bad_json', {'msg': e['bad_json']}))
        content = remaining_text.strip()
        return MockResponse(thinking, content, tool_calls, text)

def _parse_text_tool_calls(content):
    """Fallback: extract tool calls from text when model doesn't use native tool_use blocks."""
    tcs = []
    # try JSON array: [{"type":"tool_use", "name":..., "input":...}]
    _jp = next((p for p in ['[{"type":"tool_use"', '[{"type": "tool_use"'] if p in content), None)
    if _jp and content.endswith('}]'):
        try:
            idx = content.index(_jp); raw = json.loads(content[idx:])
            tcs = [MockToolCall(b["name"], b.get("input", {}), id=b.get("id", "")) for b in raw if b.get("type") == "tool_use"]
            return tcs, content[:idx].strip()
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    # try XML tags: <tool_call>{"name":..., "arguments":...}</tool_call>
    _xp = r"<(?:tool_use|tool_call)>((?:(?!<(?:tool_use|tool_call)>).){15,}?)</(?:tool_use|tool_call)>"
    for s in re.findall(_xp, content, re.DOTALL):
        try:
            d = tryparse(s.strip()); name = d.get('name')
            args = d.get('arguments') or d.get('args') or d.get('input') or {}
            if name: tcs.append(MockToolCall(name, args))
        except (AttributeError, ValueError, TypeError):
            pass
    if tcs: content = re.sub(_xp, "", content, flags=re.DOTALL).strip()
    return tcs, content

def _write_llm_log(label, content):
    log_dir = os.path.join(PROJECT_ROOT, 'temp/model_responses')
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f'model_responses_{os.getpid()}.txt')
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(log_path, 'a', encoding='utf-8', errors='replace') as f:
        f.write(f"=== {label} === {ts}\n{content}\n\n")

def tryparse(json_str):
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        pass
    json_str = json_str.strip().strip('`').replace('json\n', '', 1).strip()
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        pass
    try: return json.loads(json_str[:-1])
    except (json.JSONDecodeError, ValueError): pass
    if '}' in json_str: json_str = json_str[:json_str.rfind('}') + 1]
    return json.loads(json_str)

class MixinSession:
    """Multi-session fallback with spring-back to primary."""
    def __init__(self, all_sessions, cfg):
        self._retries, self._base_delay = cfg.get('max_retries', 3), cfg.get('base_delay', 1.5)
        self._spring_sec = cfg.get('spring_back', 300)
        self._sessions = [all_sessions[i].backend if isinstance(i, int) else 
                          next(s.backend for s in all_sessions if type(s) is not dict and s.backend.name == i) for i in cfg.get('llm_nos', [])]
        is_native = lambda s: 'Native' in s.__class__.__name__
        groups = {is_native(s) for s in self._sessions}
        assert len(groups) == 1, f"MixinSession: sessions must be in same group (Native or non-Native), got {[type(s).__name__ for s in self._sessions]}"
        self.name = '|'.join(s.name for s in self._sessions)
        import copy; self._sessions[0] = copy.copy(self._sessions[0])
        self._orig_raw_asks = [s.raw_ask for s in self._sessions]
        self._sessions[0].raw_ask = self._raw_ask
        self.model = getattr(self._sessions[0], 'model', None)
        self._cur_idx, self._switched_at = 0, 0.0
    def __getattr__(self, name): return getattr(self._sessions[0], name)
    _BROADCAST_ATTRS = frozenset({'system', 'tools', 'temperature', 'max_tokens', 'reasoning_effort', '_audit_context'})
    def __setattr__(self, name, value):
        if name in self._BROADCAST_ATTRS:
            for s in self._sessions:
                v = openai_tools_to_claude(value) if name == 'tools' and type(s) is NativeClaudeSession else value
                setattr(s, name, v)
        else: object.__setattr__(self, name, value)
    @property
    def primary(self): return self._sessions[0]
    def _pick(self):
        if self._cur_idx and time.time() - self._switched_at > self._spring_sec: self._cur_idx = 0
        return self._cur_idx
    def _raw_ask(self, *args, **kwargs):
        base, n = self._pick(), len(self._sessions)
        test_error = lambda x: isinstance(x, str) and (x.startswith('Error:') or x.startswith('[Error:'))
        for attempt in range(self._retries + 1):
            idx = (base + attempt) % n
            gen = self._orig_raw_asks[idx](*args, **kwargs)
            print(f'[MixinSession] Using session ({self._sessions[idx].name})')
            last_chunk, return_val, yielded = None, [], False
            try:
                while True:
                    chunk = next(gen); last_chunk = chunk
                    if not yielded and test_error(chunk): continue
                    yield chunk; yielded = True
            except StopIteration as e: return_val = e.value or []
            is_err = test_error(last_chunk)
            if not is_err:
                if attempt > 0: self._cur_idx = idx; self._switched_at = time.time()
                return return_val
            if attempt >= self._retries:
                yield last_chunk; return return_val
            nxt = (base + attempt + 1) % n
            if nxt == base:  # full round failed, delay before next
                rnd = (attempt + 1) // n
                delay = min(30, self._base_delay * (1.5 ** rnd))
                print(f'[MixinSession] {last_chunk[:80]}, round {rnd} exhausted, retry in {delay:.1f}s')
                time.sleep(delay)
            else: print(f'[MixinSession] {last_chunk[:80]}, retry {attempt+1}/{self._retries} (s{idx}→s{nxt})')

THINKING_PROMPT_ZH = """
### 行动规范（持续有效）
每次回复请遵循：
1. 在 <thinking></thinking> 中判断当前目标、证据缺口、下一步策略。
2. 在 <summary></summary> 中输出一行事实快照（通常 <=50 个中文字符）：上一轮新事实或当前已知状态 + 本轮意图，禁止空话。
3. 若需工具，只做当前信息增量最大的最小动作；输出工具调用后停止，等待结果。
4. 读先于写，小改优先 file_patch，需要真实输出/日志/测试时用 code_run，不要假装已经看到了工具结果。
""".strip()
THINKING_PROMPT_EN = """
### Action Protocol (always in effect)
For every reply, follow these steps:
1. Analyze the current objective, evidence gap, and next step inside <thinking></thinking>.
2. Output one factual line in <summary></summary> (usually <=30 words): last grounded fact or current state + current intent. No filler.
3. If tools are needed, take the smallest high-information action and stop after the tool call.
4. Read before write, prefer surgical edits, and never invent tool results before you see them.
""".strip()

class NativeToolClient:
    @staticmethod
    def _thinking_prompt(): return THINKING_PROMPT_EN if os.environ.get('GA_LANG') == 'en' else THINKING_PROMPT_ZH
    def __init__(self, backend):
        self.backend = backend
        self.backend.system = self._thinking_prompt()
        self.name = self.backend.name
        self._pending_tool_ids = []
    def set_system(self, extra_system):
        combined = f"{extra_system}\n\n{self._thinking_prompt()}" if extra_system else self._thinking_prompt()
        if combined != self.backend.system: print(f"[Debug] Updated system prompt, length {len(combined)} chars.")
        self.backend.system = combined
    def chat(self, messages, tools=None):
        if tools: self.backend.tools = tools
        combined_content = []; resp = None; tool_results = []
        for msg in messages:
            c = msg.get('content', '')
            if msg['role'] == 'system':
                self.set_system(c); continue
            if isinstance(c, str): combined_content.append({"type": "text", "text": c})
            elif isinstance(c, list): combined_content.extend(c)
            if msg['role'] == 'user' and msg.get('tool_results'): tool_results.extend(msg['tool_results'])
        tr_id_set = set();  tool_result_blocks = []
        for tr in tool_results:
            tool_use_id, content = tr.get("tool_use_id", ""), tr.get("content", "")
            tr_id_set.add(tool_use_id)
            if tool_use_id: tool_result_blocks.append({"type": "tool_result", "tool_use_id": tool_use_id, "content": tr.get("content", "")})
            else: combined_content = [{"type": "text", "text": f'<tool_result>{content}</tool_result>'}] + combined_content
        for tid in self._pending_tool_ids:
            if tid not in tr_id_set: tool_result_blocks.append({"type": "tool_result", "tool_use_id": tid, "content": ""})
        self._pending_tool_ids = []
        merged = {"role": "user", "content": tool_result_blocks + combined_content}
        # ── P2-cache: check exact + semantic hash before LLM call ──
        try:
            from .runtime.llm_cache_bridge import llm_cache_enabled, try_get_cached, store_cache
            if llm_cache_enabled():
                cached = try_get_cached(json.dumps(merged, ensure_ascii=False), getattr(self.backend, 'model', 'unknown'), tools)
                if cached is not None:
                    cached_text = cached.get("response", "")
                    if cached_text:
                        yield cached_text
                        return None
        except Exception:
            pass
        _write_llm_log('Prompt', json.dumps(merged, ensure_ascii=False, indent=2))
        gen = self.backend.ask(merged)
        try:
            while True:
                chunk = next(gen); yield chunk
        except StopIteration as e: resp = e.value
        if resp: _write_llm_log('Response', resp.raw)
        if resp and hasattr(resp, 'tool_calls') and resp.tool_calls: self._pending_tool_ids = [tc.id for tc in resp.tool_calls]
        try:
            from .runtime.llm_cache_bridge import llm_cache_enabled, store_cache
            if llm_cache_enabled() and resp:
                store_cache(json.dumps(merged, ensure_ascii=False), getattr(self.backend, 'model', 'unknown'), resp.raw, tools)
        except Exception:
            pass
        return resp
