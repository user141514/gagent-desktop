import os
import sys
import http.server
import json
import socketserver
import threading

sys.path.insert(0, "backend")

from core import ga
from core.agent_loop import exhaust


class DummyParent:
    verbose = False


def test_default_search_uses_http_fallback():
    original = ga._generic_http_search
    calls = []
    try:
        def fake_search(query, engine="bing", max_results=8, timeout=18, deadline=None):
            calls.append(engine)
            if engine == "bing":
                return {"status": "error", "engine": engine, "msg": "timeout"}
            return {
                "status": "success",
                "engine": engine,
                "result_count": 1,
                "results": [{"rank": 1, "title": "agent framework", "url": "https://example.com/a"}],
            }

        ga._generic_http_search = fake_search
        result = ga.web_search("agent framework")
        assert result["status"] == "success", result
        assert calls[:2] == ["bing", "google"], calls
        assert result["fallback_order"][0] == "bing", result
    finally:
        ga._generic_http_search = original


def test_powershell_transport_can_be_first():
    original_env = os.environ.get("GENERIC_AGENT_WEB_SEARCH_TRANSPORT")
    original_ps = ga._powershell_web_request_text
    original_requests = ga._requests_web_request_text
    calls = []
    try:
        os.environ["GENERIC_AGENT_WEB_SEARCH_TRANSPORT"] = "powershell,python"

        def fake_ps(url, timeout):
            calls.append("powershell")
            return '<a href="https://example.com/agent-framework">agent framework</a>'

        def fake_requests(url, timeout):
            calls.append("python")
            raise AssertionError("python requests should not run when PowerShell succeeds")

        ga._powershell_web_request_text = fake_ps
        ga._requests_web_request_text = fake_requests
        result = ga._generic_http_search("agent framework", engine="bing")
        assert result["status"] == "success", result
        assert result["transport"] == "powershell", result
        assert calls == ["powershell"], calls
    finally:
        if original_env is None:
            os.environ.pop("GENERIC_AGENT_WEB_SEARCH_TRANSPORT", None)
        else:
            os.environ["GENERIC_AGENT_WEB_SEARCH_TRANSPORT"] = original_env
        ga._powershell_web_request_text = original_ps
        ga._requests_web_request_text = original_requests


def test_empty_powershell_response_is_retried_before_python_fallback():
    original_env = os.environ.get("GENERIC_AGENT_WEB_SEARCH_TRANSPORT")
    original_ps = ga._powershell_web_request_text
    original_requests = ga._requests_web_request_text
    calls = []
    try:
        os.environ["GENERIC_AGENT_WEB_SEARCH_TRANSPORT"] = "powershell,python"

        def fake_ps(url, timeout):
            calls.append("powershell")
            if calls.count("powershell") == 1:
                return ""
            return "recovered response"

        def fake_requests(url, timeout):
            calls.append("python")
            return "python response"

        ga._powershell_web_request_text = fake_ps
        ga._requests_web_request_text = fake_requests
        text, transport = ga._fetch_web_search_text("https://example.com/search", 5)
        assert text == "recovered response", text
        assert transport == "powershell", transport
        assert calls == ["powershell", "powershell"], calls
    finally:
        if original_env is None:
            os.environ.pop("GENERIC_AGENT_WEB_SEARCH_TRANSPORT", None)
        else:
            os.environ["GENERIC_AGENT_WEB_SEARCH_TRANSPORT"] = original_env
        ga._powershell_web_request_text = original_ps
        ga._requests_web_request_text = original_requests


def test_bing_html_parse_failure_uses_rss_fallback():
    original_fetch = ga._fetch_web_search_text
    calls = []
    try:
        def fake_fetch(url, timeout, headers=None, deadline=None):
            calls.append(url)
            if "format=rss" not in url:
                return "<html><body>challenge page</body></html>", "powershell"
            return (
                "<?xml version='1.0' encoding='utf-8'?>"
                "<rss><channel><item>"
                "<title>OpenAI API documentation</title>"
                "<link>https://platform.openai.com/docs/api-reference</link>"
                "<description>Official API reference.</description>"
                "</item></channel></rss>",
                "powershell",
            )

        ga._fetch_web_search_text = fake_fetch
        result = ga._generic_http_search("OpenAI API docs", engine="bing", max_results=2, timeout=5)
        assert result["status"] == "success", result
        assert result["result_format"] == "rss", result
        assert result["results"][0]["url"] == "https://platform.openai.com/docs/api-reference", result
        assert len(calls) == 2 and "format=rss" in calls[1], calls
    finally:
        ga._fetch_web_search_text = original_fetch


def test_powershell_transport_fetches_local_http():
    if os.name != "nt":
        return

    class Handler(http.server.BaseHTTPRequestHandler):
        accept_header = ""

        def do_GET(self):
            Handler.accept_header = self.headers.get("Accept", "")
            body = b"<html><body>powershell transport ok</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/?q=agent&hl=en"
            text = ga._powershell_web_request_text(url, 5, headers={"Accept": "application/json"})
            assert "powershell transport ok" in text, text
            assert Handler.accept_header == "application/json", Handler.accept_header
        finally:
            server.shutdown()
            thread.join(timeout=5)


def test_windows_user_proxy_is_available_to_python_fallback():
    expected = {
        "http": "http://127.0.0.1:7897",
        "https": "http://127.0.0.1:7897",
    }
    assert ga._parse_windows_proxy_server("127.0.0.1:7897") == expected

    original_proxy = ga._windows_user_proxy_config
    original_get = ga.requests.get
    seen = {}

    class FakeResponse:
        text = "proxy transport ok"

        def raise_for_status(self):
            return None

    try:
        ga._windows_user_proxy_config = lambda: expected

        def fake_get(url, **kwargs):
            seen.update(kwargs)
            return FakeResponse()

        ga.requests.get = fake_get
        text = ga._requests_web_request_text("https://example.com/search?q=agent", 5)
        assert text == "proxy transport ok", text
        assert seen.get("proxies") == expected, seen
    finally:
        ga._windows_user_proxy_config = original_proxy
        ga.requests.get = original_get


def test_partial_proxy_environment_keeps_missing_windows_scheme():
    windows_proxy = {
        "http": "http://127.0.0.1:7897",
        "https": "http://127.0.0.1:7897",
    }
    merged = ga._windows_proxy_fallbacks(
        windows_proxy,
        environ={"HTTP_PROXY": "http://proxy.example:8080"},
    )
    assert merged == {"https": "http://127.0.0.1:7897"}, merged


def test_transport_and_engine_fallbacks_share_deadline():
    original_env = os.environ.get("GENERIC_AGENT_WEB_SEARCH_TRANSPORT")
    original_clock = ga.time.monotonic
    original_ps = ga._powershell_web_request_text
    original_requests = ga._requests_web_request_text
    original_search = ga._generic_http_search
    clock = [0.0]
    transport_calls = []
    engine_calls = []
    try:
        os.environ["GENERIC_AGENT_WEB_SEARCH_TRANSPORT"] = "powershell,python"
        ga.time.monotonic = lambda: clock[0]

        def fake_ps(url, timeout):
            transport_calls.append(("powershell", timeout))
            clock[0] += timeout
            raise TimeoutError("simulated timeout")

        def fake_requests(url, timeout):
            transport_calls.append(("python", timeout))
            clock[0] += timeout
            raise TimeoutError("simulated timeout")

        ga._powershell_web_request_text = fake_ps
        ga._requests_web_request_text = fake_requests
        try:
            ga._fetch_web_search_text("https://example.com/search", 18, deadline=10.0)
        except Exception:
            pass
        assert transport_calls == [("powershell", 10)], transport_calls

        clock[0] = 0.0

        def fake_search(query, engine="bing", max_results=8, timeout=18, deadline=None):
            engine_calls.append((engine, timeout, deadline))
            clock[0] += timeout
            return {"status": "error", "engine": engine, "msg": "simulated timeout"}

        ga._generic_http_search = fake_search
        ga._http_search_with_fallback("agent framework", timeout=5, deadline=8.0)
        assert [item[0] for item in engine_calls] == ["bing", "google"], engine_calls
        assert [item[1] for item in engine_calls] == [5, 3], engine_calls
    finally:
        if original_env is None:
            os.environ.pop("GENERIC_AGENT_WEB_SEARCH_TRANSPORT", None)
        else:
            os.environ["GENERIC_AGENT_WEB_SEARCH_TRANSPORT"] = original_env
        ga.time.monotonic = original_clock
        ga._powershell_web_request_text = original_ps
        ga._requests_web_request_text = original_requests
        ga._generic_http_search = original_search


def test_github_api_uses_shared_http_transport():
    original_fetch = ga._fetch_web_search_text
    original_get = ga.requests.get
    original_github_token = os.environ.pop("GITHUB_TOKEN", None)
    original_gh_token = os.environ.pop("GH_TOKEN", None)
    seen = {}
    try:
        def fake_fetch(url, timeout, headers=None, deadline=None):
            seen.update({"url": url, "timeout": timeout, "headers": headers})
            payload = {
                "total_count": 1,
                "items": [{
                    "full_name": "owner/yobot",
                    "html_url": "https://github.com/owner/yobot",
                    "description": "yobot repository",
                    "stargazers_count": 10,
                    "language": "Python",
                    "updated_at": "2026-01-01T00:00:00Z",
                }],
            }
            return json.dumps(payload), "powershell"

        ga._fetch_web_search_text = fake_fetch
        ga.requests.get = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("direct requests path used"))
        result = ga._github_api_search("yobot GitHub code", max_results=2, timeout=4)
        assert result["status"] == "success", result
        assert result["transport"] == "powershell", result
        assert "q=yobot" in seen["url"]
        assert seen["headers"]["Accept"] == "application/vnd.github+json"
        assert "Authorization" not in seen["headers"]
    finally:
        ga._fetch_web_search_text = original_fetch
        ga.requests.get = original_get
        if original_github_token is not None:
            os.environ["GITHUB_TOKEN"] = original_github_token
        if original_gh_token is not None:
            os.environ["GH_TOKEN"] = original_gh_token


def test_duckduckgo_uses_shared_http_transport():
    original_fetch = ga._fetch_web_search_text
    original_get = ga.requests.get
    try:
        def fake_fetch(url, timeout, headers=None, deadline=None):
            html = '<a class="result__a" href="https://example.com/agent-framework">agent framework</a>'
            return html, "powershell"

        ga._fetch_web_search_text = fake_fetch
        ga.requests.get = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("direct requests path used"))
        result = ga._duckduckgo_html_search("agent framework", max_results=2, timeout=4)
        assert result["status"] == "success", result
        assert result["transport"] == "powershell", result
    finally:
        ga._fetch_web_search_text = original_fetch
        ga.requests.get = original_get


def test_baidu_subdomains_are_not_search_results():
    assert ga._is_forbidden_search_result_url("https://baidu.com/")
    assert ga._is_forbidden_search_result_url("https://baike.baidu.com/item/OpenAI/19758408")
    assert not ga._is_forbidden_search_result_url("https://openai.com/api/")


def test_inline_js_is_not_treated_as_a_file_path():
    original = ga.web_execute_js
    seen = []
    try:
        ga.web_execute_js = lambda script, switch_tab_id=None, no_monitor=False: seen.append(script) or {"status": "success"}
        handler = ga.GenericAgentHandler(DummyParent(), cwd=os.path.join(os.getcwd(), "backend", "temp"))
        outcome = exhaust(handler.do_web_execute_js({"script": "window.location.href = 'https://example.com';"}, ""))
        assert outcome.data == '{"status": "success"}', outcome.data
        assert seen == ["window.location.href = 'https://example.com';"], seen
    finally:
        ga.web_execute_js = original


if __name__ == "__main__":
    test_default_search_uses_http_fallback()
    test_powershell_transport_can_be_first()
    test_empty_powershell_response_is_retried_before_python_fallback()
    test_bing_html_parse_failure_uses_rss_fallback()
    test_powershell_transport_fetches_local_http()
    test_windows_user_proxy_is_available_to_python_fallback()
    test_partial_proxy_environment_keeps_missing_windows_scheme()
    test_transport_and_engine_fallbacks_share_deadline()
    test_github_api_uses_shared_http_transport()
    test_duckduckgo_uses_shared_http_transport()
    test_baidu_subdomains_are_not_search_results()
    test_inline_js_is_not_treated_as_a_file_path()
    print("[test-web-tool-routing] ok")
