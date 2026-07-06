import os
import sys
import http.server
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
        def fake_search(query, engine="bing", max_results=8, timeout=18):
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


def test_powershell_transport_fetches_local_http():
    if os.name != "nt":
        return

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
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
            url = f"http://127.0.0.1:{server.server_address[1]}/"
            text = ga._powershell_web_request_text(url, 5)
            assert "powershell transport ok" in text, text
        finally:
            server.shutdown()
            thread.join(timeout=5)


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
    test_powershell_transport_fetches_local_http()
    test_inline_js_is_not_treated_as_a_file_path()
    print("[test-web-tool-routing] ok")
