import sys, os, re, json, time, threading, importlib, base64, html
from datetime import datetime
from pathlib import Path
import tempfile, traceback, subprocess, itertools, collections, difflib, hashlib, shutil
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
import requests
if sys.stdout is None: sys.stdout = open(os.devnull, "w")
if sys.stderr is None: sys.stderr = open(os.devnull, "w")
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(PROJECT_ROOT)

from .agent_loop import BaseHandler, StepOutcome, json_default
from .quality.execution_honesty import (
    ExecutionAction,
    ExecutionState,
    ResponseClaim,
    StateDelta,
    evaluate_execution_honesty,
    execution_honesty_enabled,
    execution_honesty_repair_enabled,
    format_honesty_gate_feedback,
    format_honesty_user_notice,
)
from .runtime.clarification_gate import (
    clarification_gate_enabled,
    should_allow_clarification,
    emit_clarification_requested,
    emit_clarification_allowed,
    emit_clarification_denied,
)
from .runtime.code_preflight import (
    CACHE_VERSION,
    CodePreflightResult,
    SmokeCache,
    SmokeCacheEntry,
    evaluate_code_run_preflight,
    get_smoke_cache,
)
from .runtime.path_safety import ToolPathResult, resolve_tool_path
from .runtime.web_tool_errors import enrich_web_tool_result, web_tool_failure_prompt

def code_run(code, code_type="python", timeout=60, cwd=None, code_cwd=None, stop_signal=[]):
    """代码执行器
    python: 运行复杂的 .py 脚本（文件模式）
    powershell/bash: 运行单行指令（命令模式）
    优先使用python，仅在必要系统操作时使用powershell"""
    preview = (code[:60].replace('\n', ' ') + '...') if len(code) > 60 else code.strip()
    yield f"[Action] Running {code_type} in {os.path.basename(cwd)}: {preview}\n"
    script_dir = PROJECT_ROOT
    cwd = cwd or os.path.join(script_dir, 'temp'); tmp_path = None
    if code_type == "python":
        tmp_file = tempfile.NamedTemporaryFile(suffix=".ai.py", delete=False, mode='w', encoding='utf-8', dir=code_cwd)
        cr_header = os.path.join(script_dir, 'assets', 'code_run_header.py')
        if os.path.exists(cr_header): tmp_file.write(open(cr_header, encoding='utf-8').read())
        tmp_file.write(code)
        tmp_path = tmp_file.name
        tmp_file.close()
        cmd = [sys.executable, "-X", "utf8", "-u", tmp_path]   
    elif code_type in ["powershell", "bash"]:
        if os.name == 'nt': cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", code]
        else: cmd = ["bash", "-c", code]
    else:
        return {"status": "error", "msg": f"不支持的类型: {code_type}"}
    print("code run output:") 
    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0 # SW_HIDE
    full_stdout = []

    def stream_reader(proc, logs):
        try:
            for line_bytes in iter(proc.stdout.readline, b''):
                try:
                    line = line_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    line = line_bytes.decode('utf-8', errors='replace')
                logs.append(line)
                try:
                    print(line, end="")
                except OSError:
                    pass
        except (OSError, ValueError):
            pass

    try:
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=0, cwd=cwd, startupinfo=startupinfo
        )
        start_t = time.time()
        t = threading.Thread(target=stream_reader, args=(process, full_stdout), daemon=True)
        t.start()

        while t.is_alive():
            istimeout = time.time() - start_t > timeout
            if istimeout or len(stop_signal) > 0:
                process.kill()
                print("[Debug] Process killed due to timeout or stop signal.")
                if istimeout: full_stdout.append("\n[Timeout Error] 超时强制终止")
                else: full_stdout.append("\n[Stopped] 用户强制终止")
                break
            time.sleep(1)

        t.join(timeout=1)
        exit_code = process.poll()

        stdout_str = "".join(full_stdout)
        status = "success" if exit_code == 0 else "error"
        status_icon = "✅" if exit_code == 0 else "❌"
        if exit_code is None: status_icon = "⏳" 
        output_snippet = smart_format(stdout_str, max_str_len=600, omit_str='\n\n[omitted long output]\n\n')
        yield f"[Status] {status_icon} Exit Code: {exit_code}\n[Stdout]\n{output_snippet}\n"
        if process.stdout: threading.Thread(target=process.stdout.close, daemon=True).start()
        return {
            "status": status,
            "stdout": smart_format(stdout_str, max_str_len=10000, omit_str='\n\n[omitted long output]\n\n'),
            "exit_code": exit_code
        }
    except Exception as e:
        if 'process' in locals(): process.kill()
        return {"status": "error", "msg": str(e)}
    finally:
        if code_type == "python" and tmp_path and os.path.exists(tmp_path): os.remove(tmp_path)


def ask_user(question, candidates=None):
    """question: 向用户提出的问题。candidates: 可选的候选项列表"""
    return {"status": "INTERRUPT", "intent": "HUMAN_INTERVENTION",
        "data": {"question": question, "candidates": candidates or []}}

from . import simphtml
driver = None
_tmwd_browser_proc = None
_DEFAULT_TMWD_START_URL = "https://www.bing.com"
_GITHUB_SEARCH_API = "https://api.github.com/search/repositories"


def _env_enabled(name, default="1"):
    return os.environ.get(name, default).strip().lower() not in {"0", "false", "no", "off"}


def _find_tmwd_browser_exe():
    override = os.environ.get("GA_BROWSER_EXE", "").strip()
    candidates = [
        override,
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return ""


def _build_tmwd_browser_cmd(browser_exe, profile_dir, extension_dir, start_url):
    return [
        browser_exe,
        f"--user-data-dir={profile_dir}",
        f"--load-extension={extension_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        start_url,
    ]


def _is_valid_tmwd_extension_dir(extension_dir):
    manifest_path = os.path.join(extension_dir, "manifest.json")
    if not os.path.isdir(extension_dir) or not os.path.isfile(manifest_path):
        return False
    try:
        with open(manifest_path, "r", encoding="utf-8") as manifest_file:
            json.load(manifest_file)
    except (OSError, json.JSONDecodeError):
        return False
    return True


def _launch_tmwd_browser():
    global _tmwd_browser_proc
    if not _env_enabled("GENERIC_AGENT_WEB_AUTOLAUNCH", "1"):
        return False
    if _tmwd_browser_proc is not None and _tmwd_browser_proc.poll() is None:
        return True
    browser_exe = _find_tmwd_browser_exe()
    extension_dir = os.path.join(PROJECT_ROOT, "assets", "tmwd_cdp_bridge")
    if not browser_exe:
        return False
    if not _is_valid_tmwd_extension_dir(extension_dir):
        print(f"[TMWebDriver] browser autolaunch skipped; extension manifest is missing or invalid: {extension_dir}")
        return False
    profile_dir = os.environ.get("GENERIC_AGENT_TMWD_PROFILE_DIR") or os.path.join(
        PROJECT_ROOT, "temp", "tmwd_edge_profile"
    )
    start_url = os.environ.get("GENERIC_AGENT_WEB_AUTOLAUNCH_URL", _DEFAULT_TMWD_START_URL).strip()
    if not start_url:
        start_url = _DEFAULT_TMWD_START_URL
    os.makedirs(profile_dir, exist_ok=True)
    cmd = _build_tmwd_browser_cmd(browser_exe, profile_dir, extension_dir, start_url)
    creationflags = 0
    if os.name == "nt" and _env_enabled("GENERIC_AGENT_WEB_AUTOLAUNCH_HIDE", "0"):
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        _tmwd_browser_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        print(f"[TMWebDriver] launched browser with extension: {browser_exe}")
        return True
    except Exception as e:
        print(f"[TMWebDriver] browser autolaunch failed: {e}")
        return False


def _wait_for_tmwd_sessions(driver_obj, timeout=20):
    sessions = []
    deadline = time.time() + max(0, timeout)
    while time.time() < deadline:
        time.sleep(1)
        sessions = driver_obj.get_all_sessions()
        if sessions:
            break
    return sessions


def first_init_driver():
    global driver
    from .TMWebDriver import TMWebDriver
    driver = TMWebDriver()
    sess = _wait_for_tmwd_sessions(driver, timeout=20)
    if len(sess) == 0 and _launch_tmwd_browser():
        sess = _wait_for_tmwd_sessions(driver, timeout=20)
    if len(sess) == 0: return 
    if len(sess) == 1: 
        #driver.newtab()
        time.sleep(3)


_BING_HTML_SEARCH_URL = "https://www.bing.com/search"
_DUCKDUCKGO_HTML_SEARCH_URL = "https://duckduckgo.com/html/"
_GOOGLE_HTML_SEARCH_URL = "https://www.google.com/search"
_GOOGLE_SCHOLAR_SEARCH_URL = "https://scholar.google.com/scholar"
_HTTP_SEARCH_ALIASES = {"", "auto", "web", "http", "duckduckgo", "ddg", "bing", "google", "scholar"}
_HTTP_SEARCH_DEFAULT_ORDER = ("bing", "google", "duckduckgo")

_GITHUB_ENGINE_ALIASES = {
    "github",
    "github_api",
    "github-api",
    "github_repo",
    "github-repo",
    "github_repos",
    "github-repos",
    "github_repositories",
    "github-repositories",
}


def _clean_search_text(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _query_core_terms(query):
    stopwords = {"the", "and", "for", "with", "code", "github", "repo", "repository", "project", "official"}
    terms = []
    for term in re.split(r"[^0-9A-Za-z_\u4e00-\u9fff]+", str(query or "").lower()):
        if len(term) >= 3 and term not in stopwords:
            terms.append(term)
    return terms[:6]


def _search_result_matches_query(query, title, url, snippet=""):
    terms = _query_core_terms(query)
    if not terms:
        return True
    haystack = f"{title} {url} {snippet}".lower()
    return any(term in haystack for term in terms)


def _unwrap_duckduckgo_url(url):
    url = urljoin("https://duckduckgo.com/", str(url or ""))
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        for key in ("uddg", "url", "u"):
            if params.get(key):
                candidate = unquote(params[key][0])
                if candidate.startswith(("http://", "https://")):
                    return candidate
        if parsed.scheme in {"http", "https"} and "duckduckgo.com" not in parsed.netloc:
            return url
    except Exception:
        return ""
    return ""


def _unwrap_http_search_url(url, base_url=""):
    url = urljoin(base_url or "https://www.bing.com/", html.unescape(str(url or "")))
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        for key in ("uddg", "url", "q"):
            if params.get(key):
                candidate = unquote(params[key][0])
                if candidate.startswith(("http://", "https://")):
                    return candidate
        encoded = params.get("u", [""])[0]
        if encoded.startswith("a1"):
            b64 = encoded[2:].replace("-", "+").replace("_", "/")
            b64 += "=" * (-len(b64) % 4)
            try:
                candidate = base64.b64decode(b64).decode("utf-8", errors="ignore")
                if candidate.startswith(("http://", "https://")):
                    return candidate
            except Exception:
                pass
        if parsed.scheme in {"http", "https"}:
            return url
    except Exception:
        return ""
    return ""


class _GenericSearchResultParser(HTMLParser):
    def __init__(self, max_results=8, base_url=""):
        super().__init__(convert_charrefs=True)
        self.max_results = max(1, min(int(max_results or 8), 20))
        self.base_url = base_url
        self.results = []
        self._seen = set()
        self._current_href = ""
        self._current_text_parts = []
        self._in_link = False

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        attrs = dict(attrs or [])
        href = str(attrs.get("href") or "")
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            return
        self._in_link = True
        self._current_href = href
        self._current_text_parts = []

    def handle_data(self, data):
        if self._in_link:
            self._current_text_parts.append(data)

    def handle_endtag(self, tag):
        if tag != "a" or not self._in_link:
            return
        title = _clean_search_text("".join(self._current_text_parts))
        url = _unwrap_http_search_url(self._current_href, self.base_url)
        self._in_link = False
        if not self._is_usable(url, title):
            return
        key = url.split("#", 1)[0]
        if key in self._seen or len(self.results) >= self.max_results:
            return
        self._seen.add(key)
        self.results.append({
            "rank": len(self.results) + 1,
            "title": title,
            "url": url,
            "snippet": "",
        })

    @staticmethod
    def _is_usable(url, title):
        if not url.startswith(("http://", "https://")):
            return False
        if not title or len(title) < 3:
            return False
        try:
            parsed = urlparse(url)
            host = parsed.netloc.lower().replace("www.", "")
            if host in {"bing.com", "google.com", "duckduckgo.com", "scholar.google.com", "baidu.com", "support.google.com", "accounts.google.com", "policies.google.com"}:
                if parsed.path in {"", "/", "/search", "/s", "/html/", "/scholar"}:
                    return False
        except Exception:
            pass
        return True


class _DuckDuckGoResultParser(HTMLParser):
    def __init__(self, max_results=8):
        super().__init__(convert_charrefs=True)
        self.max_results = max(1, min(int(max_results or 8), 20))
        self.results = []
        self._seen = set()
        self._link_href = ""
        self._link_parts = []
        self._snippet_parts = []
        self._in_link = False
        self._in_snippet = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs or [])
        classes = str(attrs.get("class") or "")
        if tag == "a" and ("result__a" in classes or "uddg=" in str(attrs.get("href") or "")):
            self._in_link = True
            self._link_href = str(attrs.get("href") or "")
            self._link_parts = []
        elif "result__snippet" in classes:
            self._in_snippet = True
            self._snippet_parts = []

    def handle_data(self, data):
        if self._in_link:
            self._link_parts.append(data)
        elif self._in_snippet:
            self._snippet_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._in_link:
            title = _clean_search_text("".join(self._link_parts))
            url = _unwrap_duckduckgo_url(self._link_href)
            key = url.split("#", 1)[0]
            if title and url and key not in self._seen and len(self.results) < self.max_results:
                self._seen.add(key)
                self.results.append({"rank": len(self.results) + 1, "title": title, "url": url, "snippet": ""})
            self._in_link = False
        elif self._in_snippet:
            snippet = _clean_search_text("".join(self._snippet_parts))
            if snippet and self.results and not self.results[-1].get("snippet"):
                self.results[-1]["snippet"] = snippet
            self._in_snippet = False


def _duckduckgo_html_search(query, max_results=8, timeout=18):
    try:
        limit = max(1, min(int(max_results or 8), 20))
    except (TypeError, ValueError):
        limit = 8
    try:
        request_timeout = max(3, min(int(timeout or 18), 60))
    except (TypeError, ValueError):
        request_timeout = 18
    search_url = _DUCKDUCKGO_HTML_SEARCH_URL + "?q=" + quote_plus(str(query or "").strip())
    try:
        response = requests.get(
            _DUCKDUCKGO_HTML_SEARCH_URL,
            params={"q": query},
            headers={"User-Agent": "GenericAgent-Workbench/1.0"},
            timeout=request_timeout,
        )
        response.raise_for_status()
        parser = _DuckDuckGoResultParser(limit)
        parser.feed(response.text)
        results = parser.results[:limit]
        if not results:
            return {
                "status": "error",
                "query": query,
                "engine": "duckduckgo",
                "search_url": search_url,
                "msg": "No HTTP search results parsed.",
            }
        return {
            "status": "success",
            "query": query,
            "engine": "duckduckgo",
            "search_url": search_url,
            "result_count": len(results),
            "results": results,
        }
    except Exception as e:
        return {
            "status": "error",
            "query": query,
            "engine": "duckduckgo",
            "search_url": search_url,
            "msg": format_error(e),
        }


def _generic_http_search(query, engine="bing", max_results=8, timeout=18):
    engine_key = str(engine or "bing").strip().lower()
    endpoints = {
        "bing": (_BING_HTML_SEARCH_URL, {"q": query}),
        "google": (_GOOGLE_HTML_SEARCH_URL, {"q": query, "hl": "en"}),
        "scholar": (_GOOGLE_SCHOLAR_SEARCH_URL, {"q": query}),
    }
    if engine_key == "ddg":
        engine_key = "duckduckgo"
    if engine_key == "duckduckgo":
        return _duckduckgo_html_search(query, max_results=max_results, timeout=timeout)
    search_url, params = endpoints.get(engine_key, endpoints["bing"])
    engine_key = engine_key if engine_key in endpoints else "bing"
    rendered_url = search_url + "?" + "&".join(f"{quote_plus(str(k))}={quote_plus(str(v))}" for k, v in params.items())
    try:
        limit = max(1, min(int(max_results or 8), 20))
        request_timeout = max(3, min(int(timeout or 18), 60))
        response = requests.get(search_url, params=params, headers={"User-Agent": "Mozilla/5.0 GenericAgent-WebSearch/1.0"}, timeout=request_timeout)
        response.raise_for_status()
        results, seen = [], set()
        for href, raw_title in re.findall(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", response.text, re.I | re.S):
            title = _clean_search_text(re.sub(r"<[^>]+>", " ", raw_title))
            url = _unwrap_http_search_url(href, search_url)
            if not url.startswith(("http://", "https://")) or not title:
                continue
            if not _search_result_matches_query(query, title, url):
                continue
            host = urlparse(url).netloc.lower().replace("www.", "")
            if host in {"bing.com", "google.com", "duckduckgo.com", "baidu.com", "support.google.com", "accounts.google.com", "policies.google.com"} or title.strip().lower() in {"feedback", "privacy", "terms"}:
                continue
            key = url.split("#", 1)[0]
            if key in seen:
                continue
            seen.add(key)
            results.append({"rank": len(results) + 1, "title": title, "url": url, "snippet": ""})
            if len(results) >= limit:
                break
        if not results:
            return {"status": "error", "query": query, "engine": engine_key, "search_url": rendered_url, "msg": "No HTTP search results parsed."}
        return {"status": "success", "query": query, "engine": engine_key, "search_url": rendered_url, "result_count": len(results), "results": results}
    except Exception as e:
        return {"status": "error", "query": query, "engine": engine_key, "search_url": rendered_url, "msg": format_error(e)}


def _http_search_with_fallback(query, max_results=8, timeout=18):
    raw = os.environ.get("GENERIC_AGENT_WEB_SEARCH_ORDER", "")
    order = [p.strip().lower() for p in re.split(r"[,;\s]+", raw) if p.strip()] or list(_HTTP_SEARCH_DEFAULT_ORDER)
    attempts = []
    for engine in order:
        result = _generic_http_search(query, engine=engine, max_results=max_results, timeout=timeout)
        if isinstance(result, dict) and result.get("status") == "success" and result.get("results"):
            result["fallback_order"] = order
            return result
        attempts.append({"engine": engine, "msg": result.get("msg") if isinstance(result, dict) else str(result)})
    return {"status": "error", "query": query, "engine": "http_fallback", "msg": "All configured HTTP search engines failed.", "attempts": attempts, "fallback_order": order}


def _github_search_headers():
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "GenericAgent-Workbench",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _github_api_search(query, max_results=8, timeout=18):
    try:
        limit = int(max_results or 8)
    except (TypeError, ValueError):
        limit = 8
    limit = max(1, min(limit, 20))
    try:
        request_timeout = int(timeout or 18)
    except (TypeError, ValueError):
        request_timeout = 18
    request_timeout = max(3, min(request_timeout, 60))

    try:
        response = requests.get(
            _GITHUB_SEARCH_API,
            params={"q": query, "per_page": limit},
            headers=_github_search_headers(),
            timeout=request_timeout,
        )
        response.raise_for_status()
        payload = response.json()
        results = []
        for item in list(payload.get("items") or [])[:limit]:
            url = item.get("html_url") or ""
            title = item.get("full_name") or item.get("name") or url
            description = item.get("description") or ""
            results.append({
                "rank": len(results) + 1,
                "title": title,
                "url": url,
                "snippet": description,
                "stars": item.get("stargazers_count", 0),
                "language": item.get("language"),
                "updated_at": item.get("updated_at"),
            })
        return {
            "status": "success",
            "query": query,
            "engine": "github",
            "search_url": _GITHUB_SEARCH_API,
            "result_count": len(results),
            "total_count": int(payload.get("total_count") or len(results)),
            "results": results,
        }
    except Exception as e:
        return {
            "status": "error",
            "query": query,
            "engine": "github",
            "search_url": _GITHUB_SEARCH_API,
            "msg": format_error(e),
        }


def web_search(query, engine="bing", max_results=8, timeout=18):
    """Deterministic web search.

    General web search uses HTTP endpoints and never opens browser tabs.
    GitHub uses the public REST API.
    """
    query = str(query or "").strip()
    if not query:
        return {"status": "error", "msg": "query is empty"}
    try:
        engine_key = str(engine or "bing").strip().lower()
        if engine_key in _GITHUB_ENGINE_ALIASES:
            return _github_api_search(query, max_results=max_results, timeout=timeout)
        if engine_key in {"", "auto", "web", "http"}:
            return _http_search_with_fallback(query, max_results=max_results, timeout=timeout)
        if engine_key in {"duckduckgo", "ddg"}:
            return _duckduckgo_html_search(query, max_results=max_results, timeout=timeout)
        if engine_key in {"bing", "google", "scholar"}:
            return _generic_http_search(query, engine=engine_key, max_results=max_results, timeout=timeout)
        return {
            "status": "error",
            "query": query,
            "engine": engine_key,
            "msg": "Unsupported web_search engine. Use bing, google, duckduckgo, scholar, github, or auto.",
        }
    except Exception as e:
        return {"status": "error", "query": query, "msg": format_error(e)}


def web_scan(tabs_only=False, switch_tab_id=None, text_only=False):
    """
    获取当前页面的简化HTML内容和标签页列表。注意：简化过程会过滤边栏、浮动元素等非主体内容。
    tabs_only: 仅返回标签页列表，不获取HTML内容（节省token）。
    switch_tab_id: 可选参数，如果提供，则在扫描前切换到该标签页。
    应当多用execute_js，少全量观察html。
    """
    global driver
    try:
        if driver is None: first_init_driver()
        if len(driver.get_all_sessions()) == 0:
            return {"status": "error", "msg": "没有可用的浏览器标签页，查L3记忆分析原因。"}
        tabs = []
        for sess in driver.get_all_sessions(): 
            sess.pop('connected_at', None)
            sess.pop('type', None)
            sess['url'] = sess.get('url', '')[:50] + ("..." if len(sess.get('url', '')) > 50 else "")
            tabs.append(sess)
        if switch_tab_id: driver.default_session_id = switch_tab_id
        result = {
            "status": "success",
            "metadata": {
                "tabs_count": len(tabs), "tabs": tabs,
                "active_tab": driver.default_session_id
            }
        }
        if not tabs_only: 
            importlib.reload(simphtml); result["content"] = simphtml.get_html(driver, cutlist=True, maxchars=35000, text_only=text_only)
            if text_only: result['content'] = smart_format(result['content'], max_str_len=10000, omit_str='\n\n[omitted long content]\n\n')
        return result
    except Exception as e:
        return {"status": "error", "msg": format_error(e)}
    
def format_error(e):
    exc_type, exc_value, exc_traceback = sys.exc_info()
    tb = traceback.extract_tb(exc_traceback)
    if tb:
        f = tb[-1]
        fname = os.path.basename(f.filename)
        return f"{exc_type.__name__}: {str(e)} @ {fname}:{f.lineno}, {f.name} -> `{f.line}`"
    return f"{exc_type.__name__}: {str(e)}"

def log_memory_access(path):
    if 'memory' not in path: return
    script_dir = PROJECT_ROOT
    stats_file = os.path.join(script_dir, 'memory/file_access_stats.json')
    try:
        with open(stats_file, 'r', encoding='utf-8') as f: stats = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        stats = {}
    fname = os.path.basename(path)
    stats[fname] = {'count': stats.get(fname, {}).get('count', 0) + 1, 'last': datetime.now().strftime('%Y-%m-%d')}
    with open(stats_file, 'w', encoding='utf-8') as f: json.dump(stats, f, indent=2, ensure_ascii=False)

def _is_navigation_script(script):
    """Detect if a JS script is a page navigation (location change)."""
    import re as _re
    nav_pat = _re.compile(
        r'(?:window\.)?location\s*\.\s*(?:href\s*=|assign\s*\(|replace\s*\()|'
        r'(?:window\.)?location\s*=\s*[\'"]'
    )
    return bool(nav_pat.search(script))


def web_execute_js(script, switch_tab_id=None, no_monitor=False):
    """Execute JS in browser tab. Navigation scripts are handled with a
    short-circuit path: execute → wait for tab reconnect → return new URL."""
    global driver
    try:
        if driver is None:
            first_init_driver()
        if len(driver.get_all_sessions()) == 0:
            return {"status": "error", "msg": "没有可用的浏览器标签页，查L3记忆分析原因。"}
        if switch_tab_id:
            driver.default_session_id = switch_tab_id

        is_nav = _is_navigation_script(script)

        if is_nav:
            # Navigation path: don't wait for JS return (page will unload)
            before_sessions = driver.get_session_dict()
            before_sids = set(before_sessions.keys())
            try:
                driver.execute_js(script)
            except Exception:
                pass  # expected — connection drops during navigation

            # Wait for tab to reconnect with new URL (up to 20s)
            for _ in range(40):
                time.sleep(0.5)
                after = driver.get_session_dict()
                new_sids = {k: v for k, v in after.items() if k not in before_sids}
                if new_sids:
                    new_tab = list(new_sids.items())[0]
                    return {
                        "status": "success",
                        "navigated": True,
                        "new_url": new_tab[1],
                        "tab_id": new_tab[0],
                        "suggestion": f"已导航到 {new_tab[1]}",
                    }
                # Check if current tab reconnected with new URL
                sid = driver.default_session_id
                if sid and sid in after and after[sid] != before_sessions.get(sid, ""):
                    return {
                        "status": "success",
                        "navigated": True,
                        "new_url": after[sid],
                        "tab_id": sid,
                        "suggestion": f"已导航到 {after[sid]}",
                    }

            return {
                "status": "timeout",
                "suggestion": (
                    "导航超时（>20s），可能原因：浏览器扩展未响应、网络问题、"
                    "目标URL无效。检查浏览器是否开启，或尝试 browser_agent 工具。"
                ),
            }

        # Non-navigation path: normal JS execution
        result = simphtml.execute_js_rich(script, driver, no_monitor=no_monitor)
        return result
    except Exception as e:
        return {"status": "error", "msg": format_error(e)}

def expand_file_refs(text, base_dir=None):
    """展开文本中的 {{file:路径:起始行:结束行}} 引用为实际文件内容。
    可与普通文本混排。展开失败抛 ValueError。
    base_dir: 相对路径的基准目录，默认为进程 cwd"""
    pattern = r'\{\{file:(.+?):(\d+):(\d+)\}\}'
    def replacer(match):
        path, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        path = os.path.abspath(os.path.join(base_dir or '.', path))
        result = resolve_tool_path(path, base_dir=base_dir or '.', project_root=PROJECT_ROOT, mode="read")
        if not result.allowed:
            return f"[blocked: {path}]"
        if not os.path.isfile(path): raise ValueError(f"引用文件不存在: {path}")
        with open(path, 'r', encoding='utf-8') as f: lines = f.readlines()
        if start < 1 or end > len(lines) or start > end: raise ValueError(f"行号越界: {path} 共{len(lines)}行, 请求{start}-{end}")
        return ''.join(lines[start-1:end])
    return re.sub(pattern, replacer, text)
    
def file_patch(path: str, old_content: str, new_content: str):
    """在文件中寻找唯一的 old_content 块并替换为 new_content"""
    path = str(Path(path).resolve())
    try:
        if not os.path.exists(path): return {"status": "error", "msg": "文件不存在"}
        with open(path, 'r', encoding='utf-8') as f: full_text = f.read()
        if not old_content: return {"status": "error", "msg": "old_content 为空，请确认 arguments"}
        count = full_text.count(old_content)
        if count == 0: return {"status": "error", "msg": "未找到匹配的旧文本块，建议：先用 file_read 确认当前内容，再分小段进行 patch。若多次失败则询问用户，严禁自行使用 overwrite 或代码替换。"}
        if count > 1: return {"status": "error", "msg": f"找到 {count} 处匹配，无法确定唯一位置。请提供更长、更具体的旧文本块以确保唯一性。建议：包含上下文行来增强特征，或分小段逐个修改。"}
        updated_text = full_text.replace(old_content, new_content)
        with open(path, 'w', encoding='utf-8') as f: f.write(updated_text)
        return {"status": "success", "msg": "文件局部修改成功"}
    except Exception as e: return {"status": "error", "msg": str(e)}

_read_dirs = set()
def _scan_files(base, depth=2):
    try:
        for e in os.scandir(base):
            if e.is_file(): yield (e.name, e.path)
            elif depth > 0 and e.is_dir(follow_symlinks=False): yield from _scan_files(e.path, depth - 1)
    except (PermissionError, OSError): pass
def file_read(path, start=1, keyword=None, count=200, show_linenos=True):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            stream = ((i, l.rstrip('\r\n')) for i, l in enumerate(f, 1))
            stream = itertools.dropwhile(lambda x: x[0] < start, stream)
            if keyword:
                before = collections.deque(maxlen=count//3)
                for i, l in stream:
                    if keyword.lower() in l.lower():
                        res = list(before) + [(i, l)] + list(itertools.islice(stream, count - len(before) - 1))
                        break
                    before.append((i, l))
                else: return f"Keyword '{keyword}' not found after line {start}. Falling back to content from line {start}:\n\n" \
                               + file_read(path, start, None, count, show_linenos)
            else: res = list(itertools.islice(stream, count))
            realcnt = len(res); L_MAX = min(max(100, 256000//max(realcnt,1)), 8000); TAG = " ... [TRUNCATED]"
            remaining = sum(1 for _ in itertools.islice(stream, 5000))
            total_lines = (res[0][0] - 1 if res else start - 1) + realcnt + remaining
            total_tag = "[FILE] Total " + (f"{total_lines}+" if remaining >= 5000 else str(total_lines)) + ' lines\n'
            res = [(i, l if len(l) <= L_MAX else l[:L_MAX] + TAG) for i, l in res]
            result = "\n".join(f"{i}|{l}" if show_linenos else l for i, l in res)
            if show_linenos: result = total_tag + result
            _read_dirs.add(os.path.dirname(os.path.abspath(path)))
            return result
    except FileNotFoundError:
        msg = f"Error: File not found: {path}"
        try:
            tgt = os.path.basename(path); scan = os.path.dirname(os.path.dirname(os.path.abspath(path)))
            roots = [scan] + [d for d in _read_dirs if not d.startswith(scan)]
            cands = list(itertools.islice((c for base in roots for c in _scan_files(base)), 2000))
            top = sorted([(difflib.SequenceMatcher(None, tgt.lower(), c[0].lower()).ratio(), c) for c in cands[:2000]], key=lambda x: -x[0])[:5]
            top = [(s, c) for s, c in top if s > 0.3]
            if top: msg += "\n\nDid you mean:\n" + "\n".join(f"  {c[1]}  ({s:.0%})" for s, c in top)
        except Exception: pass
        return msg
    except Exception as e: return f"Error: {str(e)}"

def smart_format(data, max_str_len=100, omit_str=' ... '):
    if not isinstance(data, str): data = str(data)
    if len(data) < max_str_len + len(omit_str)*2: return data
    return f"{data[:max_str_len//2]}{omit_str}{data[-max_str_len//2:]}"

def consume_file(dr, file):
    if dr and os.path.exists(os.path.join(dr, file)): 
        with open(os.path.join(dr, file), encoding='utf-8', errors='replace') as f: content = f.read()
        os.remove(os.path.join(dr, file))
        return content

class GenericAgentHandler(BaseHandler):
    '''Generic Agent 工具库，包含多种工具的实现。工具函数自动加上了 do_ 前缀。实际工具名没有前缀。'''
    def __init__(self, parent, last_history=None, cwd='./temp'):
        self.parent = parent
        self.working = {}
        self.cwd = cwd;  self.current_turn = 0
        self.history_info = last_history if last_history else []
        self.code_stop_signal = []
        self._execution_actions = []
        self._execution_files_changed = []
        self._execution_checkpoints_updated = False
        self._execution_metrics_verified = False

    def status_callback(self, payload):
        try:
            emit = getattr(self.parent, "_emit_status_event", None)
            if emit is not None:
                emit(payload)
        except Exception:
            pass

    def _get_abs_path(self, path):
        if not path: return ""
        return os.path.abspath(os.path.join(self.cwd, path))   

    def _resolve_tool_path(self, path, mode="read") -> ToolPathResult:
        return resolve_tool_path(
            path,
            base_dir=self.cwd,
            project_root=PROJECT_ROOT,
            mode=mode,
        )

    def _path_blocked_outcome(self, path_result: ToolPathResult):
        return StepOutcome(path_result.to_error_dict(), next_prompt="\n")

    def _web_failure_prompt(self, tool_name, result):
        if isinstance(result, dict) and result.get("error_category"):
            return "\n" + web_tool_failure_prompt(tool_name, result)
        return "\n"

    def _sha256_file(self, path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def _backup_before_overwrite(self, path):
        backup_dir = os.path.join(PROJECT_ROOT, "temp", "file_backups")
        os.makedirs(backup_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_name = f"{stamp}_{os.path.basename(path)}"
        backup_path = os.path.join(backup_dir, backup_name)
        shutil.copy2(path, backup_path)
        return backup_path

    def _outcome_text(self, outcome):
        data = getattr(outcome, "data", outcome)
        if isinstance(data, (dict, list)):
            try:
                return json.dumps(data, ensure_ascii=False, default=json_default)
            except Exception:
                return str(data)
        return str(data or "")

    def _outcome_status(self, outcome):
        data = getattr(outcome, "data", outcome)
        if isinstance(data, dict):
            raw = str(data.get("status") or data.get("result") or "").strip().lower()
            if raw in {"success", "ok", "completed", "done"}:
                return "success"
            if raw in {"error", "failed", "blocked", "timeout"}:
                return "error"
        text = self._outcome_text(outcome).lower()
        if any(token in text for token in ("traceback", "error:", '"status": "error"', "blocked", "timeout")):
            return "error"
        return "success"

    def tool_after_callback(self, tool_name, args, response, ret):
        if tool_name == "no_tool":
            return None
        status = self._outcome_status(ret)
        input_summary = self._summary_path(
            args.get("path")
            or args.get("cwd")
            or args.get("save_to_file")
            or args.get("target_path")
            or tool_name
        )
        output_summary = smart_format(self._outcome_text(ret), max_str_len=240)
        self._execution_actions.append(
            ExecutionAction(
                tool=tool_name,
                input_summary=input_summary,
                output_summary=output_summary,
                status=status,
                timestamp=datetime.now().isoformat(timespec="seconds"),
            )
        )
        if status == "success":
            if tool_name in {"file_patch", "file_write"}:
                changed = self._summary_path(args.get("path") or args.get("target_path"))
                if changed:
                    self._execution_files_changed.append(changed)
            elif tool_name == "web_execute_js" and args.get("save_to_file"):
                changed = self._summary_path(args.get("save_to_file"))
                if changed:
                    self._execution_files_changed.append(changed)
            elif tool_name == "update_working_checkpoint":
                self._execution_checkpoints_updated = True
            elif tool_name == "code_run":
                self._execution_metrics_verified = True
        self._execution_actions = self._execution_actions[-50:]
        self._execution_files_changed = self._execution_files_changed[-50:]
        return None

    def _build_execution_state(self, response_text=""):
        successful_tools = {
            action.tool
            for action in self._execution_actions
            if str(action.status or "").lower() in {"success", "ok", "completed", "done"}
        }
        response_claims = []
        if "code_run" in successful_tools or self._execution_metrics_verified:
            response_claims.append(
                ResponseClaim(
                    claim="numeric claims may be backed by successful code_run output",
                    claim_type="quant",
                    evidence_status="tool_verified",
                    source="execution_actions",
                    evidence_type="direct",
                    confidence=0.8,
                    verified=True,
                )
            )
        if successful_tools & {"file_read", "code_run", "web_search", "web_scan", "web_execute_js"}:
            response_claims.append(
                ResponseClaim(
                    claim="causal claims have at least indirect tool evidence",
                    claim_type="causality",
                    evidence_status="indirect",
                    source="execution_actions",
                    evidence_type="indirect",
                    confidence=0.5,
                )
            )
        return ExecutionState(
            actual_actions=list(self._execution_actions),
            state_delta=StateDelta(
                files_changed=tuple(dict.fromkeys(self._execution_files_changed)),
                checkpoints_updated=self._execution_checkpoints_updated,
                metrics_verified=self._execution_metrics_verified,
            ),
            response_claims=response_claims,
        )

    def _export_execution_state(self):
        return self._build_execution_state().to_dict()

    def _extract_code_block(self, response, code_type=None):
        content = getattr(response, 'content', '') or ''
        candidates = []
        if code_type: candidates.append(str(code_type).lower())
        candidates.extend([t for t in ("python", "powershell", "bash") if t not in candidates])
        alias_map = {
            "python": ["py"],
            "powershell": ["ps1", "pwsh"],
            "bash": ["sh", "shell"],
            "javascript": ["js"],
        }
        for candidate in candidates:
            langs = [candidate] + alias_map.get(candidate, [])
            for lang in langs:
                matches = re.findall(rf"```{lang}\n(.*?)\n```", content, re.DOTALL | re.IGNORECASE)
                if matches: return candidate, matches[-1].strip()
        generic = re.findall(r"```\n(.*?)\n```", content, re.DOTALL)
        if generic: return (candidates[0] if candidates else "python"), generic[-1].strip()
        return None, None

    def _code_run_retry_hint(self):
        project_root = os.path.abspath(os.path.join(self.cwd, '..'))
        return (
            "[System] Invalid code_run call. Provide a non-empty arguments.script, or put exactly one fenced "
            "code block immediately before the tool call. Never call code_run with only type/cwd/inline_eval. "
            f"Runtime scratch cwd is {self.cwd}. Project root is {project_root}; use cwd:'../' for the current "
            "project folder/repo root. If you only need to inspect existing files, prefer file_read."
        )

    def do_code_run(self, args, response):
        '''执行代码片段，有长度限制，不允许代码中放大量数据，如有需要应当通过文件读取进行。'''
        explicit_type = args.get("type")
        code_type = str(explicit_type or "python").lower()
        code = args.get("code") or args.get("script")
        if not code:
            inferred_type, inferred_code = self._extract_code_block(response, code_type if explicit_type else None)
            code_type, code = inferred_type or code_type, inferred_code
            if not code:
                return StepOutcome(
                    "[Error] code_run requires a non-empty script. Use arguments.script or exactly one fenced code block immediately before the tool call.",
                    next_prompt=self._get_anchor_prompt(skip=args.get('_index', 0) > 0) + "\n" + self._code_run_retry_hint()
                )
        timeout = args.get("timeout", 60)
        raw_path = os.path.join(self.cwd, args.get("cwd", './'))
        cwd = os.path.normpath(os.path.abspath(raw_path))
        code_cwd = os.path.normpath(self.cwd)
        # ── L0: cache check before preflight ──────────────────────
        try:
            smoke_cache = get_smoke_cache()
            code_hash = SmokeCache.hash_code(code)
            cached = smoke_cache.get(code_hash) if code_hash else None
        except Exception:
            # Cache layer failure → fall back to full preflight
            smoke_cache = None
            code_hash = ""
            cached = None

        if cached is not None and cached.passed and cached.cache_version == CACHE_VERSION:
            # Smoke previously verified for this exact code — skip preflight.
            preflight = CodePreflightResult(
                allowed=True,
                checks={"enabled": True, "smoke_check": True, "cached": True},
                blocked_reasons=[],
                warnings=[],
            )
            smoke_fn_found = cached.smoke_function_found
            smoke_fn_name = cached.smoke_function_name
        else:
            preflight = evaluate_code_run_preflight(code, code_type, cwd, args)
            smoke_fn_found = (
                preflight.action is not None
                and preflight.action.get("type") == "run_smoke"
            )
            smoke_fn_name = preflight.action.get("function", "") if preflight.action else ""

        profiler = getattr(getattr(self, "parent", None), "active_profiler", None)
        if profiler is not None:
            try:
                profiler.record_event(
                    "code_preflight_gate",
                    kind="tool",
                    metadata={
                        "allowed": preflight.allowed,
                        "checks": preflight.checks,
                        "blocked_reasons": preflight.blocked_reasons,
                        "warnings": preflight.warnings,
                        "code_type": code_type,
                        "cwd": cwd,
                    },
                )
            except Exception:
                pass
        if preflight.allowed:
            result = yield from code_run(code, code_type, timeout, cwd, code_cwd=code_cwd, stop_signal=self.code_stop_signal)
            # ── L0: cache successful preflight + execution ────────
            # Cache every successful run so that adding SMOKE_CHECKED=True once
            # blesses the code for the rest of the session.  Only skip caching
            # when smoke was bypassed via WARN mode (unverified allowance).
            try:
                smoke_not_warned = not any("smoke_warning" in w for w in preflight.warnings)
                if smoke_cache is not None and smoke_not_warned and code_hash and preflight.checks.get("smoke_check", True):
                    smoke_cache.put(code_hash, SmokeCacheEntry(
                        passed=True,
                        smoke_function_found=smoke_fn_found,
                        smoke_function_name=smoke_fn_name,
                    ))
            except Exception:
                pass  # cache write failure must not break execution
        else:
            yield "[Code Preflight] blocked before execution.\n"
            result = preflight.to_tool_message()
        next_prompt = self._get_anchor_prompt(skip=args.get('_index', 0) > 0)
        if 'preflight' in locals() and not preflight.allowed:
            next_prompt += "\n[CODE PREFLIGHT]\n"
            if preflight.action:
                next_prompt += (
                    f"ACTION REQUIRED: {preflight.action.get('description', '')}\n"
                    f"Execute this action first, then retry the full script."
                )
            else:
                next_prompt += (
                    "The previous code_run was blocked before execution. Do not claim the code ran. "
                    "Fix the listed syntax, input file, CSV schema, or smoke-check issue first; then rerun a minimal check before any full experiment."
                )
        elif 'preflight' in locals() and preflight.warnings:
            # WARN mode: code was allowed to run, but preflight produced
            # recommendations the agent should see in its next instruction.
            next_prompt += "\n[CODE PREFLIGHT WARNINGS]\n"
            for w in preflight.warnings:
                next_prompt += f"  - {w}\n"
            if preflight.suggested_next_step:
                next_prompt += f"\nSuggestion: {preflight.suggested_next_step}\n"
        return StepOutcome(result, next_prompt=next_prompt)
    
    def do_ask_user(self, args, response):
        question = args.get("question", "请提供输入：")
        candidates = args.get("candidates", [])
        user_input = getattr(self, "_last_user_input", "") or ""

        # ── Clarification Gate ──────────────────────────────
        if clarification_gate_enabled():
            context: dict = {}
            if candidates:
                context["candidates"] = [
                    {"name": c if isinstance(c, str) else c.get("name", str(c)),
                     "score": c.get("score", 0.5) if isinstance(c, dict) else 0.5,
                     "action": c.get("action", "") if isinstance(c, dict) else ""}
                    for c in candidates
                ]
            # Check working state for target hints
            working = getattr(self, "working", {}) or {}
            if working.get("target_file"):
                context["target_file"] = working["target_file"]
            if working.get("target_object"):
                context["target_object"] = working["target_object"]
            if working.get("selected_candidate"):
                context["selected_candidate"] = working["selected_candidate"]

            profiler = getattr(getattr(self, "parent", None), "active_profiler", None)
            decision = should_allow_clarification(user_input, question, context)

            emit_clarification_requested(profiler, decision, user_input, question)

            if decision.allowed:
                emit_clarification_allowed(profiler, decision, user_input, question)
            else:
                emit_clarification_denied(profiler, decision, user_input, question)
                yield (
                    f"[Clarification Gate] ask_user blocked: {decision.reason}\n"
                )
                return StepOutcome(
                    {
                        "status": "BLOCKED",
                        "gate": "clarification",
                        "reason": decision.reason,
                        "fallback_instruction": decision.fallback_instruction,
                        "signals": decision.signals,
                    },
                    next_prompt=(
                        f"\n[System] ask_user was blocked by clarification gate: "
                        f"{decision.reason}\n{decision.fallback_instruction}\n"
                        f"继续执行，不要再次 ask_user 相同问题。"
                    ),
                    should_exit=False,
                )

        result = ask_user(question, candidates)
        yield f"Waiting for your answer ...\n"
        return StepOutcome(result, next_prompt="", should_exit=True)
    
    def do_web_scan(self, args, response):
        '''获取当前页面内容和标签页列表。也可用于切换标签页。
        注意：HTML经过简化，边栏/浮动元素等可能被过滤。如需查看被过滤的内容请用execute_js。
        tabs_only=true时仅返回标签页列表，不获取HTML（省token）。
        '''
        tabs_only = args.get("tabs_only", False)
        switch_tab_id = args.get("switch_tab_id", None)
        text_only = args.get("text_only", False)
        result = web_scan(tabs_only=tabs_only, switch_tab_id=switch_tab_id, text_only=text_only)
        result = enrich_web_tool_result("web_scan", result)
        content = result.pop("content", None)
        yield f'[Info] {str(result)}\n'
        if content: result = json.dumps(result, ensure_ascii=False, default=json_default) + f"\n```html\n{content}\n```"
        next_prompt = self._web_failure_prompt("web_scan", result)
        return StepOutcome(result, next_prompt=next_prompt)

    def do_web_search(self, args, response):
        """Run deterministic HTTP search without LLM/browser calls."""
        query = str(args.get("query") or "").strip()
        if not query:
            return StepOutcome({"status": "error", "msg": "query parameter cannot be empty"}, next_prompt="\n")
        engine = args.get("engine", "bing")
        try:
            max_results = int(args.get("max_results", 8) or 8)
        except (TypeError, ValueError):
            max_results = 8
        try:
            timeout = int(args.get("timeout", 18) or 18)
        except (TypeError, ValueError):
            timeout = 18
        result = web_search(
            query=query,
            engine=engine,
            max_results=max_results,
            timeout=timeout,
        )
        result = enrich_web_tool_result("web_search", result)
        show = smart_format(json.dumps(result, ensure_ascii=False, indent=2, default=json_default), max_str_len=800)
        yield f"[WebSearch] {show}\n"
        next_prompt = self._get_anchor_prompt(skip=args.get('_index', 0) > 0)
        if isinstance(result, dict) and result.get("error_category"):
            next_prompt += self._web_failure_prompt("web_search", result)
        return StepOutcome(result, next_prompt=next_prompt)
    
    def do_web_execute_js(self, args, response):
        '''web情况下的优先使用工具，执行任何js达成对浏览器的*完全*控制。支持将结果保存到文件供后续读取分析。'''
        script = args.get("script", "")
        if not script:
            _, script = self._extract_code_block(response, "javascript")
        if not script: return StepOutcome("[Error] Script missing. Use ```javascript block or 'script' arg.", next_prompt="\n")
        path_result = self._resolve_tool_path(script.strip(), mode="read")
        if not path_result.allowed:
            yield f"[Path Guard] {path_result.message}\n"
            return self._path_blocked_outcome(path_result)
        if os.path.isfile(path_result.path):
            with open(path_result.path, 'r', encoding='utf-8') as f: script = f.read()
        save_to_file = args.get("save_to_file", "")
        switch_tab_id = args.get("switch_tab_id") or args.get("tab_id")
        no_monitor = args.get("no_monitor", False)
        result = web_execute_js(script, switch_tab_id=switch_tab_id, no_monitor=no_monitor)
        result = enrich_web_tool_result("web_execute_js", result)
        if save_to_file and "js_return" in result:
            content = str(result["js_return"] or '')
            path_result = self._resolve_tool_path(save_to_file, mode="write")
            result["js_return"] = smart_format(content, max_str_len=170)
            if not path_result.allowed:
                result["js_return"] += f"\n\n[保存失败：{path_result.message}]"
            else:
                try:
                    with open(path_result.path, 'w', encoding='utf-8') as f: f.write(str(content))
                    result["js_return"] += f"\n\n[已保存完整内容到 {path_result.path}]"
                except OSError:
                    result['js_return'] += f"\n\n[保存失败，无法写入文件 {path_result.path}]"
        show = smart_format(json.dumps(result, ensure_ascii=False, indent=2, default=json_default), max_str_len=300)
        try: print("Web Execute JS Result:", show)
        except OSError: pass
        yield f"JS 执行结果:\n{show}\n"
        next_prompt = self._get_anchor_prompt(skip=args.get('_index', 0) > 0)
        if isinstance(result, dict) and result.get("error_category"):
            next_prompt += self._web_failure_prompt("web_execute_js", result)
        result = json.dumps(result, ensure_ascii=False, default=json_default)
        return StepOutcome(smart_format(result, max_str_len=8000), next_prompt=next_prompt)

    # ── browser-use sub-agent integration ──────────────────────────────

    def do_browser_agent(self, args, response):
        """Delegate complex multi-step browser tasks to a browser-use sub-Agent.

        The sub-Agent controls an independent Playwright browser,
        autonomously screenshot → analyze → act, until the task is done
        or max_steps is reached.

        Suitable for: form filling, post-login navigation, multi-page data collection.
        Not suitable for: simple JS injection (use web_execute_js), single-page scan (use web_scan).
        """
        task = args.get("task", "").strip()
        if not task:
            return StepOutcome({"error": "task parameter cannot be empty"}, next_prompt="\n")

        max_steps = int(args.get("max_steps", 20))
        headless = bool(args.get("headless", True))

        llm_config = self._get_browser_llm_config()
        yield f"[BrowserAgent] Starting sub-Agent, task: {task[:120]}\n"

        def _progress(msg):
            pass  # progress logged, not yielded (avoids breaking the generator chain)

        try:
            from .browser_agent import run_browser_agent
        except ImportError:
            return StepOutcome(
                {"error": "browser_agent module missing — check core/browser_agent.py"},
                next_prompt="\n",
            )

        result = run_browser_agent(
            task, llm_config,
            max_steps=max_steps,
            headless=headless,
            progress_cb=_progress,
        )
        result = enrich_web_tool_result("browser_agent", result)

        status = "OK" if result.get("success") else "FAILED"
        steps = result.get("steps_taken", "?")
        yield f"[BrowserAgent] {status}, executed {steps} steps\n"
        next_prompt = self._get_anchor_prompt()
        if isinstance(result, dict) and result.get("error_category"):
            next_prompt += self._web_failure_prompt("browser_agent", result)
        return StepOutcome(result, next_prompt=next_prompt)

    def _get_browser_llm_config(self) -> dict:
        """Extract LLM info from the current session for browser-use.
        Falls back to env vars if extraction fails.
        """
        try:
            backend = self.parent.llmclient.backend
            cfg = getattr(backend, "cfg", {}) or {}
            name = type(backend).__name__.lower()
            provider = "anthropic" if "claude" in name or "anthropic" in name else "openai"
            return {
                "provider": provider,
                "model": cfg.get("model", ""),
                "api_key": cfg.get("api_key", ""),
            }
        except Exception:
            return {"provider": "openai"}  # let browser-use read OPENAI_API_KEY

    def do_file_patch(self, args, response):
        path_result = self._resolve_tool_path(args.get("path", ""), mode="write")
        if not path_result.allowed:
            yield f"[Path Guard] {path_result.message}\n"
            return self._path_blocked_outcome(path_result)
        path = path_result.path
        yield f"[Action] Patching file: {path}\n"
        old_content = args.get("old_content", "")
        new_content = args.get("new_content", "")
        try: new_content = expand_file_refs(new_content, base_dir=self.cwd)
        except ValueError as e:
            yield f"[Status] ❌ 引用展开失败: {e}\n"
            return StepOutcome({"status": "error", "msg": str(e)}, next_prompt="\n")
        expected_sha256 = str(args.get("expected_sha256") or "").strip().lower()
        backup_path = ""
        current_sha256 = ""
        if os.path.exists(path):
            current_sha256 = self._sha256_file(path)
            if expected_sha256 and expected_sha256 != current_sha256:
                msg = (
                    "expected_sha256 mismatch; refusing file_patch. "
                    f"expected={expected_sha256} actual={current_sha256}"
                )
                yield f"[Status] ERROR: {msg}\n"
                return StepOutcome(
                    {
                        "status": "error",
                        "msg": msg,
                        "expected_sha256": expected_sha256,
                        "actual_sha256": current_sha256,
                    },
                    next_prompt="\n",
                )
            backup_path = self._backup_before_overwrite(path)
        result = file_patch(path, old_content, new_content)
        if isinstance(result, dict) and result.get("status") == "success":
            if backup_path:
                result["backup_path"] = backup_path
            if current_sha256:
                result["previous_sha256"] = current_sha256
        yield f"\n{str(result)}\n"
        next_prompt = self._get_anchor_prompt(skip=args.get('_index', 0) > 0)
        return StepOutcome(result, next_prompt=next_prompt)
    
    def do_file_write(self, args, response):
        '''用于对整个文件的大量处理，精细修改要用file_patch。
        需要将要写入的内容放在<file_content>标签内，或者放在代码块中'''
        path_result = self._resolve_tool_path(args.get("path", ""), mode="write")
        if not path_result.allowed:
            yield f"[Path Guard] {path_result.message}\n"
            return self._path_blocked_outcome(path_result)
        path = path_result.path
        mode = args.get("mode", "overwrite")  # overwrite/append/prepend
        action_str = {"prepend": "Prepending to", "append": "Appending to"}.get(mode, "Overwriting")
        yield f"[Action] {action_str} file: {os.path.basename(path)}\n"

        def extract_robust_content(text):
            tag = re.search(r"<file_content[^>]*>(.*)</file_content>", text, re.DOTALL)
            if tag: return tag.group(1).strip()
            s, e = text.find("```"), text.rfind("```")
            if -1 < s < e: return text[text.find("\n", s)+1 : e].strip()
            return None
        
        blocks = args.get("content") or args.get("file_content") or extract_robust_content(response.content)
        if not blocks:
            yield f"[Status] ❌ 失败: 未在回复中找到<file_content>代码块内容\n"
            return StepOutcome({"status": "error", "msg": "No content found. Put content inside <file_content>...</file_content> tags in your reply body before call file_write."}, next_prompt="\n")
        try:
            new_content = expand_file_refs(blocks, base_dir=self.cwd)
            expected_sha256 = str(args.get("expected_sha256") or "").strip().lower()
            backup_path = ""
            if mode in {"overwrite", "prepend"} and os.path.exists(path):
                current_sha256 = self._sha256_file(path)
                if expected_sha256 and expected_sha256 != current_sha256:
                    msg = (
                        "expected_sha256 mismatch; refusing file_write overwrite. "
                        f"expected={expected_sha256} actual={current_sha256}"
                    )
                    yield f"[Status] ERROR: {msg}\n"
                    return StepOutcome(
                        {
                            "status": "error",
                            "msg": msg,
                            "expected_sha256": expected_sha256,
                            "actual_sha256": current_sha256,
                        },
                        next_prompt="\n",
                    )
                backup_path = self._backup_before_overwrite(path)
            if mode == "prepend":
                old = open(path, 'r', encoding="utf-8").read() if os.path.exists(path) else ""
                open(path, 'w', encoding="utf-8").write(new_content + old)
            else:
                with open(path, 'a' if mode == "append" else 'w', encoding="utf-8") as f: f.write(new_content)
            yield f"[Status] ✅ {mode.capitalize()} 成功 ({len(new_content)} bytes)\n"
            next_prompt = self._get_anchor_prompt(skip=args.get('_index', 0) > 0)
            result = {"status": "success", 'writed_bytes': len(new_content)}
            if backup_path:
                result["backup_path"] = backup_path
            return StepOutcome(result, next_prompt=next_prompt)
        except Exception as e:
            yield f"[Status] ❌ 写入异常: {str(e)}\n"
            return StepOutcome({"status": "error", "msg": str(e)}, next_prompt="\n")
        
    def do_file_read(self, args, response):
        '''读取文件内容。从第start行开始读取。如有keyword则返回第一个keyword(忽略大小写)周边内容'''
        path_result = self._resolve_tool_path(args.get("path", ""), mode="read")
        if not path_result.allowed:
            yield f"[Path Guard] {path_result.message}\n"
            return self._path_blocked_outcome(path_result)
        path = path_result.path
        yield f"\n[Action] Reading file: {path}\n"
        start = args.get("start", 1)
        count = args.get("count", 200)
        keyword = args.get("keyword")
        show_linenos = args.get("show_linenos", True)
        result = file_read(path, start=start, keyword=keyword,
                           count=count, show_linenos=show_linenos)
        if show_linenos and not result.startswith("Error:"): result = '由于设置了show_linenos，以下返回信息为：(行号|)内容 。\n' + result 
        if ' ... [TRUNCATED]' in result: result += '\n\n（某些行被截断，如需完整内容可改用 code_run 读取）'
        result = smart_format(result, max_str_len=20000, omit_str='\n\n[omitted long content]\n\n')
        next_prompt = self._get_anchor_prompt(skip=args.get('_index', 0) > 0)
        log_memory_access(path)
        if 'memory' in path or 'sop' in path or '_sop' in path.lower():
            next_prompt += (
                "\n[SYSTEM TIPS] 正在读取记忆/SOP文件。"
                '⚠️ L1索引中的括号摘要（如「禁pyautogui」）仅为4-8字提示，'
                "不代表完整约束——必须逐条提取正文中的关键步骤/禁止项/前置条件。"
                "执行前用 update_working_checkpoint 保存要点以防遗忘。"
            )
        return StepOutcome(result, next_prompt=next_prompt)
    
    def _in_plan_mode(self): return self.working.get('in_plan_mode')
    def _exit_plan_mode(self): self.working.pop('in_plan_mode', None)
    def enter_plan_mode(self, plan_path): 
        self.working['in_plan_mode'] = plan_path; self.max_turns = 80
        print(f"[Info] Entered plan mode with plan file: {plan_path}"); return plan_path
    def _check_plan_completion(self):
        p = self._in_plan_mode() or ""
        if not os.path.isfile(p): return None
        try: return len(re.findall(r'\[ \]', open(p, encoding='utf-8', errors='replace').read()))
        except (FileNotFoundError, OSError): return None
    
    def do_update_working_checkpoint(self, args, response):
        '''为整个任务设定后续需要临时记忆的重点。'''
        key_info = args.get("key_info", "")
        related_sop = args.get("related_sop", "")
        if "key_info" in args: self.working['key_info'] = key_info
        if "related_sop" in args: self.working['related_sop'] = related_sop
        self.working['passed_sessions'] = 0
        yield f"[Info] Updated key_info and related_sop.\n"
        next_prompt = self._get_anchor_prompt(skip=args.get('_index', 0) > 0)
        #next_prompt += '\n[SYSTEM TIPS] 此函数一般在任务开始或中间时调用，如果任务已成功完成应该是start_long_term_update用于结算长期记忆。\n'
        return StepOutcome({"result": "working key_info updated"}, next_prompt=next_prompt)

    def do_no_tool(self, args, response):
        '''这是一个特殊工具，由引擎自主调用，不要包含在TOOLS_SCHEMA里。
        当模型在一轮中未显式调用任何工具时，由引擎自动触发。
        二次确认仅在回复几乎只包含<thinking>/<summary>和一段大代码块时触发。'''
        content = getattr(response, 'content', '') or ""
        if not response or not content.strip():
            yield "[Warn] LLM returned an empty response. Retrying...\n"
            return StepOutcome({}, next_prompt="[System] Blank response, regenerate and tooluse")
        if '未收到完整响应 !!!]' in content[-100:]:
            return StepOutcome({}, next_prompt="[System] Incomplete response. Regenerate and tooluse.")
        if 'max_tokens !!!]' in content[-100:]:
            return StepOutcome({}, next_prompt="[System] max_tokens limit reached. Use multi small steps to do it.")

        visible_content = re.sub(r"<thinking>[\s\S]*?</thinking>", "", content, flags=re.IGNORECASE)
        visible_content = re.sub(r"<summary>[\s\S]*?</summary>", "", visible_content, flags=re.IGNORECASE).strip()
        if not visible_content:
            yield "[Hard Gate] No user-visible final answer.\n"
            return StepOutcome({}, next_prompt="[System] Your last response contained no user-visible final answer after removing thinking/summary. Write a clear final answer for the user now.")

        raw_task = str(getattr(self, "_last_user_input", "") or "")
        recent_trace = "\n".join(str(x) for x in self.history_info[-20:]).lower()
        runtime_state = self._export_execution_state()
        state_blob = json.dumps(runtime_state, ensure_ascii=False, default=str).lower()
        constraint_trace = recent_trace + "\n" + state_blob
        state_delta = runtime_state.get("state_delta") or {}
        state_files_changed = tuple(state_delta.get("files_changed") or ())
        state_metrics_verified = bool(state_delta.get("metrics_verified"))
        state_actual_actions = tuple(runtime_state.get("actual_actions") or ())
        state_action_count = len(state_actual_actions)
        if "Original user request:" in raw_task and state_action_count == 0 and not any(t in content for t in ("无法执行", "无法操作", "缺少权限", "等待用户")):
            yield "[Hard Gate] Runtime state has no actual actions.\n"
            return StepOutcome({}, next_prompt="[System] Runtime state has zero actual_actions for this delegated execution task. Take at least one concrete tool action, or report a concrete blocker.")
        if "Original user request:" in raw_task and len(content.strip()) < 500:
            if not any(t in constraint_trace for t in ("file_read", "code_run", "reading file", "executed code", "已读取", "运行")):
                yield "[Hard Gate] Short executor answer blocked before any probe.\n"
                return StepOutcome({}, next_prompt="[System] This was delegated as an execution task, but no project/file/runtime probe is visible. Use file_read or code_run first, then continue.")
        write_pos = max(recent_trace.rfind(t) for t in ("file_patch", "file_write", "writed_bytes", "已修改", "写入"))
        verify_pos = max(recent_trace.rfind(t) for t in ("pytest", "npm test", "npm run build", "py_compile", "node --check", "exit code: 0", "已执行代码", "测试"))
        if write_pos >= 0 and verify_pos < write_pos and not any(t in content for t in ("未验证", "无法验证", "验证阻塞")):
            yield "[Hard Gate] Edit detected without later verification.\n"
            return StepOutcome({}, next_prompt="[System] A file edit is visible, but no later verification is visible. Run a minimal verification, or explicitly state why verification is blocked and what risk remains.")
        
        if state_files_changed and not state_metrics_verified and not any(t in content for t in ("未验证", "无法验证", "验证阻塞")):
            yield "[Hard Gate] Runtime state reports changed files without verification.\n"
            return StepOutcome({}, next_prompt="[System] Runtime state says files changed but verification is missing. Verify first, or report the blocker and remaining risk.")
        
        if self._in_plan_mode() and any(kw in content for kw in ['任务完成', '全部完成', '已完成所有', '🏁']):
            if 'VERDICT' not in content and '[VERIFY]' not in content and '验证subagent' not in content:
                yield "[Warn] Plan模式完成声明拦截。\n"
                return StepOutcome({}, next_prompt="⛔ [验证拦截] 检测到你在plan模式下声称完成，但未执行[VERIFY]验证步骤。请先按plan_sop §四启动验证subagent，获得VERDICT后才能声称完成。")
            
        # 2. 检测"包含较大代码块但未调用工具"的情况
        # 关键特征：恰好1个大代码块 + 代码块直接结尾（后面只有空白）
        code_block_pattern = r"```[a-zA-Z0-9_]*\n[\s\S]{50,}?```"
        blocks = re.findall(code_block_pattern, content)
        if len(blocks) == 1:
            m = re.search(code_block_pattern, content)
            after_block = content[m.end():]
            if not after_block.strip():
                residual = content.replace(m.group(0), "")
                residual = re.sub(r"<thinking>[\s\S]*?</thinking>", "", residual, flags=re.IGNORECASE)
                residual = re.sub(r"<summary>[\s\S]*?</summary>", "", residual, flags=re.IGNORECASE)
                clean_residual = re.sub(r"\s+", "", residual)
                if len(clean_residual) <= 30:
                    yield "[Info] Detected large code block without tool call and no extra natural language. Requesting clarification.\n"
                    next_prompt = (
                        "[System] 检测到你在上一轮回复中主要内容是较大代码块，且本轮未调用任何工具。\n"
                        "如果这些代码需要执行、写入文件或进一步分析，请重新组织回复并显式调用相应工具"
                        "（例如：code_run、file_write、file_patch 等）；\n"
                        "如果只是向用户展示或讲解代码片段，请在回复中补充自然语言说明，"
                        "并明确是否还需要额外的实际操作。"
                    )
                    return StepOutcome({}, next_prompt=next_prompt)
                
        if self._in_plan_mode():
            remaining = self._check_plan_completion()
            if remaining == 0:
                self._exit_plan_mode(); yield "[Info] Plan完成：plan.md中0个[ ]残留，退出plan模式。\n"
        
        if execution_honesty_enabled():
            honesty = evaluate_execution_honesty(content, self._build_execution_state(content))
            if not honesty.allowed:
                yield "[Execution Honesty Gate] Final response blocked before user delivery.\n"
                if execution_honesty_repair_enabled():
                    return StepOutcome({}, next_prompt=format_honesty_gate_feedback(honesty))
                notice = format_honesty_user_notice(honesty)
                yield notice + "\n"
                return StepOutcome(
                    {"result": "EXECUTION_HONESTY_BLOCKED", "data": notice},
                    next_prompt=None,
                    should_exit=True,
                )

        yield "[Info] Final response to user.\n"
        return StepOutcome(response, next_prompt=None)
    
    def do_start_long_term_update(self, args, response):
        '''Agent觉得当前任务完成后有重要信息需要记忆时调用此工具。'''
        prompt = '''### [总结提炼经验] 既然你觉得当前任务有重要信息需要记忆，请提取最近一次任务中【事实验证成功且长期有效】的环境事实、用户偏好、重要步骤，更新记忆。
本工具是标记开启结算过程，若已在更新记忆过程或没有值得记忆的点，忽略本次调用。
**提取行动验证成功的信息**：
- **环境事实**（路径/凭证/配置）→ `file_patch` 更新 L2，同步 L1
- **复杂任务经验**（关键坑点/前置条件/重要步骤）→ L3 精简 SOP（只记你被坑得多次重试的核心要点）
**禁止**：临时变量、具体推理过程、未验证信息、通用常识、你可以轻松复现的细节。
**操作**：严格遵循提供的L0的记忆更新SOP。先 `file_read` 看现有 → 判断类型 → 最小化更新 → 无新内容跳过，保证对记忆库最小局部修改。\n
''' + get_global_memory()
        yield "[Info] Start distilling good memory for long-term storage.\n"
        path = os.path.join(PROJECT_ROOT, 'memory', 'memory_management_sop.md')
        if os.path.exists(path): result = file_read(path, show_linenos=False)
        else: result = "Memory Management SOP not found. Do not update memory."
        return StepOutcome(result, next_prompt=prompt)

    def _get_anchor_prompt(self, skip=False):
        if skip: return "\n"
        h_str = "\n".join(self.history_info[-20:])
        prompt = f"\n### [WORKING MEMORY]\n<history>\n{h_str}\n</history>"
        prompt += f"\nCurrent turn: {self.current_turn}\n"
        if self.working.get('key_info'): prompt += f"\n<key_info>{self.working.get('key_info')}</key_info>"
        if self.working.get('related_sop'): prompt += f"\n有不清晰的地方请再次读取{self.working.get('related_sop')}"
        if getattr(self.parent, 'verbose', False):
            try: print(prompt)
            except OSError: pass
        return prompt

    @staticmethod
    def _summary_lang_en():
        return os.environ.get('GA_LANG') == 'en'

    @staticmethod
    def _summary_path(path):
        raw = str(path or "").strip().replace("\\", "/")
        if not raw:
            return ""
        try:
            if os.path.isabs(raw):
                rel = os.path.relpath(raw, PROJECT_ROOT).replace("\\", "/")
                if not rel.startswith(".."):
                    raw = rel
        except Exception:
            pass
        return raw if len(raw) <= 48 else os.path.basename(raw)

    @staticmethod
    def _summary_error_hint(text):
        content = str(text or "")
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        for line in lines:
            lowered = line.lower()
            if any(token in lowered for token in ("traceback", "error", "failed", "timeout", "http ", "exception", "not found")):
                return smart_format(line, max_str_len=90)
        return ""

    def _summary_is_low_signal(self, summary, tool_calls):
        cleaned = " ".join(str(summary or "").split()).strip()
        if not cleaned:
            return True
        lowered = cleaned.lower()
        if any(token in cleaned for token in ("<tool_use>", "</tool_use>", "{", "}", "```")):
            return True
        if len(cleaned) < 6:
            return True
        generic_markers = (
            "继续处理", "继续分析", "继续排查", "继续执行", "继续修改",
            "准备下一步", "准备继续", "处理中", "开始处理",
            "continue working", "continue analysis", "next step", "keep debugging",
        )
        factual_anchors = (
            "已", "发现", "定位", "读取", "修改", "运行", "测试", "报错", "错误",
            "文件", "日志", "页面", "文档", "路径", "结果", "验证", "搜索",
            "read", "patch", "write", "run", "test", "error", "file", "log",
        )
        has_anchor = any(anchor in cleaned for anchor in factual_anchors) or bool(re.search(r"[/\\._:-]|\d", cleaned))
        if any(marker in lowered for marker in generic_markers) and not has_anchor:
            return True
        if tool_calls and not has_anchor and len(cleaned) < 18:
            return True
        return False

    def _fallback_summary_from_tool(self, tool_calls, tool_results):
        lang_en = self._summary_lang_en()
        tool_idx = None
        tool_call = None
        for idx in range(len(tool_calls or []) - 1, -1, -1):
            tc = tool_calls[idx] or {}
            if tc.get("tool_name") and tc.get("tool_name") != "no_tool":
                tool_idx = idx
                tool_call = tc
                break
        if tool_call is None:
            return "Answered the user directly" if lang_en else "直接回答了用户问题"

        tool_name = str(tool_call.get("tool_name") or "")
        args = tool_call.get("args") or {}
        result_text = ""
        if isinstance(tool_results, list) and tool_idx is not None and tool_idx < len(tool_results):
            payload = tool_results[tool_idx]
            if isinstance(payload, dict):
                result_text = str(payload.get("content") or "")
            elif payload is not None:
                result_text = str(payload)
        lowered_result = result_text.lower()
        path = self._summary_path(
            args.get("path")
            or args.get("cwd")
            or args.get("save_to_file")
        )
        keyword = str(args.get("keyword") or "").strip()
        err_hint = self._summary_error_hint(result_text)

        if tool_name == "file_read":
            target = path or ("file" if lang_en else "文件")
            if keyword and "not found" in lowered_result:
                return (
                    f"Keyword {keyword} not found in {target}; next widen search"
                    if lang_en else
                    f"未在{target}找到{keyword}，准备扩大搜索"
                )
            if err_hint:
                return (
                    f"Read {target} failed: {err_hint}; next inspect path/context"
                    if lang_en else
                    f"读取{target}失败：{err_hint}，准备检查路径和上下文"
                )
            if keyword:
                return (
                    f"Located {keyword} in {target}; next inspect details"
                    if lang_en else
                    f"已在{target}定位{keyword}，准备继续分析"
                )
            return f"Read {target}; next use the content" if lang_en else f"已读取{target}，准备基于内容继续"

        if tool_name in ("file_patch", "file_write"):
            target = path or ("file" if lang_en else "文件")
            success = not err_hint and any(token in lowered_result for token in ('"success"', "✅", "status", "writed_bytes"))
            if success:
                return f"Updated {target}; next verify the change" if lang_en else f"已修改{target}，准备验证结果"
            if err_hint:
                return (
                    f"Edit on {target} failed: {err_hint}; next re-read context"
                    if lang_en else
                    f"修改{target}失败：{err_hint}，准备重新读取上下文"
                )
            return f"Edited {target}; next inspect result" if lang_en else f"已改动{target}，准备检查结果"

        if tool_name == "code_run":
            script = str(args.get("script") or "").strip()
            script_lower = script.lower()
            if "timeout" in lowered_result:
                return "Execution timed out; next inspect blocking point" if lang_en else "运行超时，准备排查阻塞点"
            if err_hint:
                return f"Execution failed: {err_hint}; next debug" if lang_en else f"运行报错：{err_hint}，准备排查原因"
            failed = re.search(r"(\d+)\s+failed", lowered_result)
            passed = re.search(r"(\d+)\s+passed", lowered_result)
            if "pytest" in script_lower or "pytest" in lowered_result or "test" in script_lower:
                if failed or passed:
                    fail_txt = failed.group(1) if failed else "0"
                    pass_txt = passed.group(1) if passed else "0"
                    return (
                        f"Ran tests: {pass_txt} passed, {fail_txt} failed; next fix failures"
                        if lang_en else
                        f"已运行测试：{pass_txt}通过，{fail_txt}失败，准备修复问题"
                    )
                return "Ran tests; next inspect failures" if lang_en else "已运行测试，准备分析结果"
            return "Executed code and got output; next inspect result" if lang_en else "已执行代码并拿到输出，准备分析结果"

        if tool_name == "web_scan":
            return "Scanned page structure; next locate the target element" if lang_en else "已扫描页面结构，准备定位目标元素"

        if tool_name == "web_search":
            if err_hint:
                return f"Web search failed: {err_hint}; next switch path or report blocker" if lang_en else f"网页搜索失败：{err_hint}，准备切换路径或报告阻塞"
            return "Ran browser-backed web search; next inspect sources" if lang_en else "已执行浏览器搜索，准备检查来源"

        if tool_name == "web_execute_js":
            if err_hint:
                return f"JS execution failed: {err_hint}; next inspect DOM/state" if lang_en else f"页面脚本执行失败：{err_hint}，准备检查DOM和页面状态"
            return "Executed page JS and captured result; next continue from page state" if lang_en else "已执行页面脚本并获得结果，准备继续页面操作"

        if tool_name == "browser_agent":
            if any(token in lowered_result for token in ("\"success\": true", "'success': true")):
                return "Browser workflow completed; next consolidate findings" if lang_en else "浏览器流程已完成，准备整理结论"
            return "Browser workflow ran; next inspect its findings" if lang_en else "浏览器流程已执行，准备分析结果"

        if tool_name == "update_working_checkpoint":
            return "Updated working checkpoint; next continue with saved constraints" if lang_en else "已更新工作记忆，准备按保存的约束继续"

        if tool_name == "ask_user":
            return "Asked the user for a decision/blocker resolution" if lang_en else "已向用户请求关键决策或补充信息"

        if tool_name == "start_long_term_update":
            return "Started long-term memory distillation" if lang_en else "已开始整理长期记忆"

        target = path or tool_name
        return f"Used {tool_name} on {target}; next inspect result" if lang_en else f"已调用{tool_name}处理{target}，准备继续分析"

    def _safe_summary(self, response, tool_calls, tool_results, turn):
        """Extract and validate summary before saving to history.

        Returns (summary_text, is_fallback).
        Hallucination-prone summaries on early turns are replaced with
        tool-based fallbacks to prevent context corruption.
        """
        _c = re.sub(r'```.*?```|<thinking>.*?</thinking>', '', response.content, flags=re.DOTALL)
        rsumm = re.search(r"<summary>(.*?)</summary>", _c, re.DOTALL)

        if rsumm:
            summary = " ".join(rsumm.group(1).split()).strip()
            user_input = getattr(self, "_last_user_input", "") or ""
            user_lower = str(user_input or "").lower()

            # Hallucination markers: claims about user statements that may be fabricated,
            # or explicit confusion signals on early turns.
            _hallucination_markers = [
                "用户澄清", "用户说", "用户提到", "用户表示", "用户已说明",
                "用户补充说明", "用户告诉我", "用户回复说",
                "我缺少前文", "我缺少上下文", "缺少前面的对话",
            ]
            has_marker = any(m in summary for m in _hallucination_markers)

            # Check if the summary references topics absent from the user input.
            # Extract potential topic keywords from summary (quoted phrases / project names).
            _topic_refs = re.findall(r'(?:在|关于|针对|对于|不是)\s*([\u4e00-\u9fffA-Za-z0-9_-]{3,20})', summary)
            _topic_mismatch = False
            for ref in _topic_refs:
                if ref.lower() not in user_lower:
                    _topic_mismatch = True
                    break

            if turn <= 2 and (has_marker or _topic_mismatch):
                # Suspicious summary on early turn — use tool-based fallback
                pass  # fall through to fallback
            elif summary and not self._summary_is_low_signal(summary, tool_calls):
                return summary, False

        return self._fallback_summary_from_tool(tool_calls, tool_results), True

    def turn_end_callback(self, response, tool_calls, tool_results, turn, next_prompt, exit_reason):
        summary, fallback_used = self._safe_summary(response, tool_calls, tool_results, turn)
        if fallback_used:
            next_prompt += "\n[DANGER] 上一轮的<summary>缺失、过空或不可信，已根据真实工具动作自动补全。下次必须写事实化<summary>。"
        summary = smart_format(summary, max_str_len=100)
        self.history_info.append(f'[Agent] {summary}')
        if turn % 70 == 0 and 'plan' not in str(self.working.get('related_sop')):
            next_prompt += f"\n\n[DANGER] 已连续执行第 {turn} 轮。你必须总结情况进行ask_user，不允许继续重试。"
        elif turn % 7 == 0:
            next_prompt += f"\n\n[DANGER] 已连续执行第 {turn} 轮。禁止无效重试。若无有效进展，必须切换策略：1. 探测物理边界 2. 请求用户协助。如有需要，可调用 update_working_checkpoint 保存关键上下文。"
        elif turn % 10 == 0: next_prompt += get_global_memory()

        _plan = self._in_plan_mode()
        if _plan and turn >= 10 and turn % 5 == 0:
            next_prompt = f"[Plan Hint] 你正在计划模式。必须 file_read({_plan}) 确认当前步骤，回复开头引用：📌 当前步骤：...\n\n" + next_prompt
        if _plan and turn >= 70: next_prompt += f"\n\n[DANGER] Plan模式已运行 {turn} 轮，已达上限。必须 ask_user 汇报进度并确认是否继续。"

        injkeyinfo = consume_file(self.parent.task_dir, '_keyinfo')
        injprompt = consume_file(self.parent.task_dir, '_intervene')
        if injkeyinfo: self.working['key_info'] = self.working.get('key_info', '') + f"\n[MASTER] {injkeyinfo}"
        if injprompt: next_prompt += f"\n\n[MASTER] {injprompt}\n"
        for hook in getattr(self.parent, '_turn_end_hooks', {}).values(): hook(locals())  # current readonly
        # ── Step-level reflection (LIVE-SWE-AGENT conditional trigger) ──
        _error_seen = False
        for tr in (tool_results or []):
            c = str(tr.get('content', '')).lower()
            if any(tok in c for tok in ('error:', 'traceback', 'exception', 'traceback (most recent call last)')):
                _error_seen = True
                break
        _repeat_seen = False
        if not _error_seen and tool_calls:
            _names = [tc.get('name', '') for tc in tool_calls]
            _last = getattr(self, '_reflect_last_names', None)
            if _last == _names:
                _repeat_seen = True
            self._reflect_last_names = _names
        if _error_seen:
            next_prompt += '\n[REFLECT] Tool returned an error. What capability gap caused this? Should you create a helper script via code_run or change approach?'
        elif _repeat_seen:
            next_prompt += '\n[REFLECT] Same tool sequence as last turn. Are you stuck? Is a reusable tool missing?'
        return next_prompt

def get_global_memory():
    from .memory.legacy_global import build_legacy_memory_block
    return build_legacy_memory_block(PROJECT_ROOT)
