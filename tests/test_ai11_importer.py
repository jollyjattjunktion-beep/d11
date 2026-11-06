import httpx
import pytest

from app.importers import ai11


def test_parse_ai11_player_table_maps_selection_and_role():
    html = """
    <html><head><title>NZ vs IND 2nd ODI | AI11</title></head>
    <body>
      <img alt="New Zealand"><img alt="India">
      <table>
        <tr><th>Name</th><th>T</th><th>R</th><th>S</th><th>M#</th><th>Bat</th><th>P</th><th>S%</th><th>C</th><th>VC</th></tr>
        <tr><td>Example Player</td><td>NZ</td><td>BAT</td><td>✓</td><td>10</td><td>RHB</td><td>50</td><td>44.5</td><td>5.2</td><td>3.1</td></tr>
      </table>
      <h2>Pitch Report: Hnry Stadium</h2>
      <p>Average first-innings score 252</p>
    </body></html>
    """
    data = ai11.parse_analysis(html)
    assert data["format"] == "ODI"
    assert data["team_a"] == "New Zealand"
    assert data["players"][0]["role"] == "BAT"
    assert data["players"][0]["status"] == "confirmed"
    assert data["players"][0]["selection_pct"] == 44.5
    assert data["profiles"][0]["ai11_captain_pct"] == 5.2


def test_parse_fantasy_does_not_guess_missing_credits():
    result = ai11.parse_fantasy("<html><body><div>Player list loading</div></body></html>")
    assert result["credits"] == {}
    assert result["dynamic_content_may_require_browser"] is True


@pytest.mark.parametrize("url", [
    "http://ai11.in/match",
    "https://example.com/match",
    "https://ai11.in:8443/match",
])
def test_reject_unsafe_import_urls(url):
    with pytest.raises(ValueError):
        ai11.validate_ai11_url(url)


def test_successful_page_is_cached(monkeypatch):
    ai11.clear_page_cache()
    calls = []
    monkeypatch.setattr(ai11, "_fetch_once", lambda url: calls.append(url) or "<html>ok</html>")
    url = "https://www.ai11.in/example"
    assert ai11.fetch_page(url) == "<html>ok</html>"
    assert ai11.fetch_page(url) == "<html>ok</html>"
    assert len(calls) == 1
    ai11.clear_page_cache()


def test_rate_limit_retries_then_raises(monkeypatch):
    ai11.clear_page_cache()
    calls = []

    def rate_limited(url):
        calls.append(url)
        request = httpx.Request("GET", url)
        response = httpx.Response(429, headers={"Retry-After": "2"}, request=request)
        raise httpx.HTTPStatusError("rate limited", request=request, response=response)

    waits = []
    monkeypatch.setattr(ai11, "_fetch_once", rate_limited)
    monkeypatch.setattr(ai11.time, "sleep", lambda seconds: waits.append(seconds))
    with pytest.raises(ai11.AI11RateLimitError) as error:
        ai11.fetch_page("https://www.ai11.in/rate-limited")
    assert len(calls) == ai11.MAX_RETRIES
    assert waits == [2, 2]
    assert error.value.retry_after == 2
    ai11.clear_page_cache()


def test_rate_limit_retry_after_is_bounded(monkeypatch):
    ai11.clear_page_cache()
    def rate_limited(url):
        request = httpx.Request("GET", url)
        response = httpx.Response(429, headers={"Retry-After": "120"}, request=request)
        raise httpx.HTTPStatusError("rate limited", request=request, response=response)

    waits = []
    monkeypatch.setattr(ai11, "_fetch_once", rate_limited)
    monkeypatch.setattr(ai11.time, "sleep", lambda seconds: waits.append(seconds))
    with pytest.raises(ai11.AI11RateLimitError) as error:
        ai11.fetch_page("https://www.ai11.in/long-wait")
    assert waits == [ai11.MAX_RETRY_WAIT_SECONDS] * (ai11.MAX_RETRIES - 1)
    assert error.value.retry_after == 120
    ai11.clear_page_cache()
