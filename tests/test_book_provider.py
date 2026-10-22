import pytest
from flask import Flask

from api.book_provider import BookProvider


@pytest.fixture
def provider():
    app = Flask(__name__)
    app.config.update(
        DATA_PROVIDER="primary",
        DATA_PROVIDER_FALLBACK="fallback",
    )
    with app.app_context():
        yield BookProvider()


def test_primary_search_result_does_not_call_fallback(provider, monkeypatch):
    calls = []
    primary = [{"isbn": "primary-isbn", "title": "Primary", "author": "Author"}]

    def fetch(provider_name, query):
        calls.append((provider_name, query))
        return primary

    monkeypatch.setattr(provider, "_fetch_search", fetch)

    assert provider.search("query") == primary
    assert calls == [("primary", "query")]


def test_empty_primary_search_uses_fallback_once(provider, monkeypatch):
    calls = []
    fallback = [{"isbn": "fallback-isbn", "title": "Fallback", "author": "Author"}]
    responses = iter([[], fallback])

    def fetch(provider_name, query):
        calls.append((provider_name, query))
        return next(responses)

    monkeypatch.setattr(provider, "_fetch_search", fetch)

    assert provider.search("query") == fallback
    assert calls == [("primary", "query"), ("fallback", "query")]


def test_missing_primary_get_uses_fallback_once(provider, monkeypatch):
    calls = []
    fallback = {"title": "Fallback", "subtitle": None, "author": "Author"}
    responses = iter([None, fallback])

    def fetch(provider_name, isbn):
        calls.append((provider_name, isbn))
        return next(responses)

    monkeypatch.setattr(provider, "_fetch_get", fetch)

    assert provider.get("isbn") == fallback
    assert calls == [("primary", "isbn"), ("fallback", "isbn")]


def test_primary_and_fallback_search_errors_return_none_without_sensitive_output(
    provider, monkeypatch, capsys
):
    calls = []

    def fail(provider_name, query):
        calls.append((provider_name, query))
        raise RuntimeError("secret-query https://private.example/token")

    monkeypatch.setattr(provider, "_fetch_search", fail)

    assert provider.search("secret-query") is None
    assert calls == [("primary", "secret-query"), ("fallback", "secret-query")]
    captured = capsys.readouterr()
    assert "secret-query" not in captured.out + captured.err
    assert "private.example" not in captured.out + captured.err


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class RecordingSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def test_existing_openlibrary_search_normalization_is_preserved(provider):
    session = RecordingSession(
        FakeResponse(
            {
                "docs": [
                    {
                        "isbn": ["9780000000001"],
                        "title": "Existing title",
                        "author_name": ["Existing author"],
                    }
                ]
            }
        )
    )
    provider.session = session

    assert provider._search_openlibrary("query") == [
        {"isbn": "9780000000001", "title": "Existing title", "author": "Existing author"}
    ]
    assert session.calls[0][0] == "https://openlibrary.org/search.json"
    assert session.calls[0][1]["timeout"] == 30


def test_existing_openlibrary_get_preserves_subtitle_and_normalization(provider):
    session = RecordingSession(
        FakeResponse(
            {
                "title": "Existing title",
                "subtitle": "Existing subtitle",
                "authors": [{"key": "/authors/existing"}],
                "description": {"value": "Existing description"},
                "number_of_pages": 321,
            }
        ),
        FakeResponse({"name": "Existing author"}),
    )
    provider.session = session

    assert provider._get_openlibrary("9780000000001") == {
        "title": "Existing title",
        "subtitle": "Existing subtitle",
        "author": "Existing author",
        "description": "Existing description",
        "total_pages": 321,
    }
    assert session.calls[0][0] == "https://openlibrary.org/isbn/9780000000001.json"
    assert session.calls[1][0] == "https://openlibrary.org/authors/existing.json"
