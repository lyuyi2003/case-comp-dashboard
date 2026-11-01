"""Tests for the page checker. None of these touch the internet."""

from fetch_pages import (
    collect_pages,
    fingerprint,
    html_to_text,
    is_blocked,
    page_state,
    read_page,
    relevant_lines,
    skip_reason,
)

SKIP_RULES = [{"prefix": "https://nus.edu.sg/cfg/", "reason": "Refuses automated visitors"}]


def test_html_keeps_words_and_drops_code():
    page = "<html><style>p{}</style><script>alert(1)</script><p>Hello</p><div>World</div></html>"
    assert html_to_text(page) == "Hello\nWorld"


def test_line_breaks_stay_separate_lines():
    assert html_to_text("one<br>two<br/>three") == "one\ntwo\nthree"


def test_fingerprint_ignores_spacing_but_not_words():
    assert fingerprint("register   by  5 December") == fingerprint("register by 5 December")
    assert fingerprint("register by 5 December") != fingerprint("register by 6 December")


def test_fingerprint_ignores_random_codes():
    page = "Registration closes soon for this year's competition\n"
    assert fingerprint(page + "c8594d688b98425abfbc9bff208625b2") == fingerprint(page + "3adad763d6024d1598a8b1b761be434f")


def test_fingerprint_ignores_shuffled_menus():
    page = "The competition is open to all undergraduate students\n"
    assert fingerprint(page + "Home\nAbout\nEvents") == fingerprint(page + "Events\nCareers")


def test_fingerprint_notices_a_short_date_change():
    assert fingerprint("Deadline: 5 Dec") != fingerprint("Deadline: 6 Dec")


def test_fingerprint_notices_a_changed_eligibility_rule():
    before = "Open to all undergraduate students in Singapore"
    after = "Open only to penultimate year students in Singapore"
    assert fingerprint(before) != fingerprint(after)


def test_block_pages_are_recognised():
    assert is_blocked('<iframe src="/_Incapsula_Resource?x=1">Request unsuccessful.</iframe>')
    assert not is_blocked("An ordinary page about a case competition")


def test_only_lines_near_a_competition_are_kept():
    text = "\n".join(f"line {n}" for n in range(20)) + "\nNew Case Competition 2027\n" + "\n".join(
        f"after {n}" for n in range(20)
    )
    kept = relevant_lines(text)
    assert "New Case Competition 2027" in kept
    assert "line 19" in kept
    assert "after 2" in kept
    assert "line 0" not in kept
    assert "after 10" not in kept


def test_listing_with_no_competitions_is_empty():
    assert relevant_lines("Open day\nCareer fair\nLibrary hours") == ""


def test_changed_and_unchanged_pages():
    assert page_state("abc", "abc", False) == "unchanged"
    assert page_state("abc", "xyz", False) == "changed"
    assert page_state(None, "xyz", False) == "changed"


def test_empty_listing_seen_for_the_first_time_is_not_news():
    assert page_state(None, fingerprint(""), True) == "unchanged"


def test_skip_rules_match_by_address():
    assert skip_reason("https://nus.edu.sg/cfg/events/details/1", SKIP_RULES)
    assert skip_reason("https://sgfin.nus.edu.sg/page", SKIP_RULES) is None


def test_skipped_pages_are_never_visited(monkeypatch):
    def fail_if_called(url):
        raise AssertionError("a skipped page must not be visited")

    monkeypatch.setattr("fetch_pages.download", fail_if_called)
    page = {"url": "https://nus.edu.sg/cfg/events", "kind": "official", "ids": []}
    assert read_page(page, {}, SKIP_RULES)["state"] == "blocked"


def test_a_failed_page_does_not_stop_the_run(monkeypatch):
    def broken(url):
        raise TimeoutError("too slow")

    monkeypatch.setattr("fetch_pages.download", broken)
    page = {"url": "https://example.com", "kind": "source", "ids": ["a"]}
    result = read_page(page, {}, [])
    assert result["state"] == "failed"
    assert "too slow" in result["error"]


def test_a_block_page_in_a_response_counts_as_blocked(monkeypatch):
    body = b"<html><iframe>Request unsuccessful. Incapsula incident</iframe>" + b" " * 300 + b"</html>"
    monkeypatch.setattr("fetch_pages.download", lambda url: (body, "text/html"))
    page = {"url": "https://example.com", "kind": "source", "ids": []}
    assert read_page(page, {}, [])["state"] == "blocked"


def test_a_page_with_no_readable_text_fails(monkeypatch):
    monkeypatch.setattr("fetch_pages.download", lambda url: (b"<html><body></body></html>", "text/html"))
    page = {"url": "https://example.com", "kind": "source", "ids": []}
    assert read_page(page, {}, [])["state"] == "failed"


def test_a_changed_source_page_is_detected(monkeypatch):
    html = "<p>" + "The competition closes on 5 December. " * 10 + "</p>"
    monkeypatch.setattr("fetch_pages.download", lambda url: (html.encode(), "text/html"))
    page = {"url": "https://example.com", "kind": "source", "ids": []}
    first = read_page(page, {}, [])
    assert first["state"] == "changed"
    second = read_page(page, {"https://example.com": first["hash"]}, [])
    assert second["state"] == "unchanged"


def test_collect_pages_lists_each_address_once():
    records = [
        {"id": "a", "official_url": "https://x.com/1", "source_urls": [{"url": "https://x.com/1"}]},
        {"id": "b", "official_url": None, "source_urls": [{"url": "https://x.com/1"}, {"url": "https://x.com/2"}]},
    ]
    sources = {"listings": [{"name": "List", "url": "https://x.com/list", "type": "lead"}]}
    pages = {page["url"]: page for page in collect_pages(records, sources)}
    assert len(pages) == 3
    assert pages["https://x.com/1"]["ids"] == ["a", "b"]
    assert pages["https://x.com/list"]["kind"] == "lead"
