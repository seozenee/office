"""Browser / Computer agent: JS rendering, extraction, download → KB, form submission behind approval."""
import http.server
import os
import threading
from pathlib import Path

import pytest

pytest.importorskip("playwright")
if Path("/opt/pw-browsers").exists():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")

PAGES = {
    "/js": b"""<html><body><div id=app></div><script>
      document.getElementById('app').innerHTML = '<h1>JS Report</h1><p>' + 'The AI tutoring market reached 3 billion dollars in 2024 according to the ministry. '.repeat(3) + '</p><table><tr><td>2024</td><td>3</td></tr></table>';
    </script></body></html>""",
    "/form": b"""<html><body><form action="/done" method="get"><input name="q"><button type="submit">Go</button></form></body></html>""",
    "/pay": b"""<html><body><form action="/done"><input name="card_number"><button>Pay</button></form></body></html>""",
    "/done": b"<html><head><title>Done</title></head><body>submitted</body></html>",
    "/file.txt": "업로드용 텍스트 문서입니다. 매출은 120억원이었다.".encode(),
}


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        body = PAGES.get(path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8" if path.endswith(".txt") else "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def site():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture()
def allow_local(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "fetch_allow_private_network", True)


def test_private_network_blocked_by_default(client, site):
    from app.tools.browser import BrowserError, open_page

    with pytest.raises(BrowserError):
        open_page(site + "/js")


def test_open_renders_javascript_and_lists_forms(allow_local, site):
    from app.tools.browser import open_page, render_html

    page = open_page(site + "/js")
    assert "3 billion dollars" in page["text"] and page["untrusted"]
    _, html = render_html(site + "/js")
    assert "<table>" in html
    assert open_page(site + "/form")["forms"][0]["fields"][0]["name"] == "q"


def test_allow_list(allow_local, site, monkeypatch):
    from app.core.config import get_settings
    from app.tools.browser import BrowserError, open_page

    monkeypatch.setattr(get_settings(), "browser_allowed_domains", "example.org")
    with pytest.raises(BrowserError):
        open_page(site + "/js")


def test_download_is_medium_and_ingested(allow_local, site, client):
    r = client.post("/api/tools/browser.download/execute", json={"args": {"url": site + "/file.txt"}}).json()
    assert r["result"]["kb_document_id"] and Path(r["result"]["path"]).exists()


def test_form_submit_requires_ceo_approval_then_runs(allow_local, site, client):
    r = client.post("/api/tools/browser.submit_form/execute", json={"args": {"url": site + "/form", "fields": {"q": "hello"}}}).json()
    assert r["approval_required"] and r["approval"]["risk_level"] == "HIGH"
    res = client.post(f"/api/approvals/{r['approval']['id']}/decide", json={"approve": True, "note": "ok"}).json()
    assert res["status"] == "approved" and "q=hello" in res["tool_result"]["url"]
    assert Path(res["tool_result"]["after"]).exists()


def test_payment_form_refused(allow_local, site):
    from app.tools.browser import BrowserError, form_risk, submit_form

    assert form_risk({"card_number": "1"}) == "CRITICAL"
    with pytest.raises(BrowserError):
        submit_form(site + "/pay", {"card_number": "4111"})


def test_research_falls_back_to_browser_for_js_pages(allow_local, site, db):
    from app.agents.research import DocumentAnalystAgent
    from app.tools.web import SearchResult

    out = DocumentAnalystAgent(db).fetch_and_ingest([SearchResult("JS Report", site + "/js", "", None, "t", "q")],
                                                    project_id=None, project_slug=None, max_sources=3)
    assert out.accessed == 1 and "브라우저 렌더링" in out.sources[0].snippet
