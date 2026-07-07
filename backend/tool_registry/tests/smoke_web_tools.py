#!/usr/bin/env python
"""Smoke checks for Layer 1 web tool boundaries."""

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[3]
if sys.version_info < (3, 11):
    embedded = ROOT / "python-runtime" / ("python.exe" if os.name == "nt" else "bin/python")
    if embedded.exists() and Path(sys.executable).resolve() != embedded.resolve():
        raise SystemExit(subprocess.call([str(embedded)] + sys.argv))

sys.path.insert(0, str(ROOT / "backend"))

from core import ga  # noqa: E402


SEARCH_HOSTS = {
    "baidu.com",
    "www.baidu.com",
    "bing.com",
    "www.bing.com",
    "google.com",
    "www.google.com",
    "duckduckgo.com",
    "www.duckduckgo.com",
}

NETWORK_HINTS = (
    "timeout",
    "timed out",
    "proxy",
    "dns",
    "name resolution",
    "connection",
    "network",
    "ssl",
    "tls",
    "all http transports failed",
    "invoke-webrequest failed",
)


class LogicFailure(Exception):
    pass


class FakeDriver:
    def __init__(self):
        self.default_session_id = "tab-1"
        self.urls = {
            "tab-1": "https://example.com/current",
            "tab-2": "https://openai.com/docs",
        }

    def get_all_sessions(self):
        return [
            {"id": key, "url": value, "connected_at": "now", "type": "page"}
            for key, value in self.urls.items()
        ]

    def get_session_dict(self):
        return dict(self.urls)

    def execute_js(self, script):
        if "location" in script:
            self.urls[self.default_session_id] = "https://example.com/after-nav"
        return {"status": "success", "js_return": None}


def host(url):
    return urlparse(str(url)).netloc.lower()


def is_search_homepage(url):
    parsed = urlparse(str(url))
    return parsed.netloc.lower() in SEARCH_HOSTS and parsed.path in ("", "/")


def classify_failure(result):
    category = str((result or {}).get("error_category") or "")
    if category in {"network_error", "search_backend_unavailable", "rate_limited"}:
        return category
    text = json.dumps(result, ensure_ascii=False).lower()
    if any(hint in text for hint in NETWORK_HINTS):
        return "network_failure"
    if "tmwebdriver" in text or "browser" in text or "session" in text:
        return "browser_bridge_failure"
    return "logic_failure"


def assert_no_baidu_success(result):
    for item in result.get("results") or []:
        if "baidu.com" in str(item.get("url", "")).lower():
            raise LogicFailure("Baidu URL returned as success: %s" % item.get("url"))


def smoke_web_search_openai_docs():
    result = ga.web_search("OpenAI API docs", engine="auto", max_results=6, timeout=10)
    if result.get("status") != "success":
        return {"status": classify_failure(result), "result": result}

    assert_no_baidu_success(result)
    urls = [item.get("url", "") for item in result.get("results") or []]
    if any(is_search_homepage(url) for url in urls):
        raise LogicFailure("search engine homepage returned as source result: %s" % urls)
    if not any(host(url) not in SEARCH_HOSTS for url in urls):
        raise LogicFailure("no non-search-engine source URL returned: %s" % urls)
    return {"status": "passed", "result_count": len(urls)}


def smoke_web_search_yobot():
    result = ga.web_search("yobot GitHub code", engine="auto", max_results=6, timeout=10)
    if result.get("status") == "success":
        assert_no_baidu_success(result)
        return {"status": "passed", "result_count": len(result.get("results") or [])}
    if result.get("status") == "error" and result.get("msg"):
        return {"status": "structured_failure", "failure_class": classify_failure(result), "result": result}
    raise LogicFailure("web_search failure is not structured: %s" % result)


def smoke_web_scan_current_tab_only():
    original_driver = ga.driver
    try:
        ga.driver = FakeDriver()
        result = ga.web_scan(tabs_only=True)
    finally:
        ga.driver = original_driver

    if result.get("status") != "success":
        return {"status": classify_failure(result), "result": result}
    if "query" in result or "search_url" in result or "results" in result:
        raise LogicFailure("web_scan returned search-shaped data: %s" % result)
    if "content" in result:
        raise LogicFailure("tabs_only web_scan returned page content")
    return {"status": "passed", "tabs_count": result.get("metadata", {}).get("tabs_count")}


def smoke_web_execute_js_navigation():
    original_driver = ga.driver
    original_sleep = ga.time.sleep
    try:
        ga.driver = FakeDriver()
        ga.time.sleep = lambda _seconds: None
        result = ga.web_execute_js("window.location.href = 'https://example.com/after-nav';")
    finally:
        ga.driver = original_driver
        ga.time.sleep = original_sleep

    if result.get("status") != "success" or not result.get("navigated"):
        raise LogicFailure("navigation JS did not return navigation success: %s" % result)
    return {"status": "passed", "new_url": result.get("new_url")}


def smoke_browser_agent_contract():
    contract = (ROOT / "backend" / "tool_registry" / "tools" / "browser_agent.yml").read_text(encoding="utf-8").lower()
    required = ["complex", "rendered", "ordinary web_search fallback"]
    missing = [text for text in required if text not in contract]
    if missing:
        raise LogicFailure("browser_agent contract missing: %s" % ", ".join(missing))
    return {"status": "passed"}


def main():
    checks = {
        "web_search_openai_docs": smoke_web_search_openai_docs,
        "web_search_yobot": smoke_web_search_yobot,
        "web_scan_current_tab_only": smoke_web_scan_current_tab_only,
        "web_execute_js_navigation": smoke_web_execute_js_navigation,
        "browser_agent_contract": smoke_browser_agent_contract,
    }
    results = {}
    failed = False
    for name, check in checks.items():
        try:
            results[name] = check()
            if results[name].get("status") == "logic_failure":
                failed = True
        except LogicFailure as error:
            results[name] = {"status": "logic_failure", "error": str(error)}
            failed = True
        except Exception as error:
            results[name] = {"status": "logic_failure", "error": repr(error)}
            failed = True

    print(json.dumps(results, indent=2, ensure_ascii=False))
    if failed:
        print("[smoke_web_tools] failed", file=sys.stderr)
        return 1
    print("[smoke_web_tools] ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
