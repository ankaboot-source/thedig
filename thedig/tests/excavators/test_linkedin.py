"""Regression tests for the LinkedIn search engines / profile parsing.

These tests never touch the network: engines are built with ``__new__`` (or
with a no-op ``raw_search``) and handcrafted payloads are injected directly.
"""

# Import the API module first to avoid the known circular-import path
# (thedig.api.person -> thedig.api.dig -> thedig.excavators.linkedin).
import pytest

from thedig.api import dig
from thedig.excavators.linkedin import (
    Bing,
    Brave,
    GoogleVertexAI,
    Search,
    SearchChain,
)

TARGET_URL = "https://fr.linkedin.com/in/jane-doe-0b119742"
TARGET_TITLE = "Jane Doe - Senior Manager Consulting Business Operationnel - Acme France | LinkedIn"
TARGET_DESCRIPTION = (
    "Consultante · Expérience : Acme France · Formation : Université de Paris · "
    "Lieu : Paris, Île-de-France, France · 500+ relations sur LinkedIn. "
    "Consultez le profil de Jane Doe sur LinkedIn, une communauté professionnelle d’un milliard de membres"  # noqa: RUF001
)


class _StubSearch(Search):
    """Minimal Search implementation: injects results without any HTTP call."""

    def __init__(self, results):
        self._results = results
        super().__init__(endpoint="https://example.test", method="GET")

    def search_query(self, _query: str = None) -> dict:  # noqa: RUF013
        return {}

    def extract(self):
        self.results = self._results

    def authenticate(self):
        return self.headers

    def raw_search(self, _query: str):
        self.raw_results = {}


class _StubEngine:
    """Fake engine for SearchChain tests."""

    def __init__(self, profiles, results=None):
        self.profiles = profiles
        self.results = results if results is not None else [{"url": TARGET_URL}]

    def search(self, query: str, name: str):  # noqa: ARG002
        return self.profiles


def test_search_ignores_none_values_from_bing_shaped_results():
    """A None value (Bing sets image=None) must not abort the whole engine."""
    results = [
        {
            "title": "Jane Doe - Acme France",
            "url": TARGET_URL,
            "description": TARGET_DESCRIPTION,
            "image": None,
        },
        {
            "title": TARGET_TITLE,
            "url": TARGET_URL,
            "description": TARGET_DESCRIPTION,
            "image": None,
        },
        {
            "title": "Jane Doe - Autre poste - Autre société | LinkedIn",
            "url": "https://fr.linkedin.com/in/jane-doe-0b119742",
            "description": None,
            "image": None,
        },
    ]

    profiles = _StubSearch(results).search(query="Jane Doe", name="Jane Doe")

    assert len(profiles) >= 1
    assert str(profiles[0].url).startswith(TARGET_URL)


def test_search_preserves_french_accents_with_nfkc():
    profile = _StubSearch(
        [
            {
                "title": TARGET_TITLE,
                "url": TARGET_URL,
                "description": TARGET_DESCRIPTION,
                "image": None,
            }
        ]
    ).search(query="Jane Doe", name="Jane Doe")[0]

    assert profile.jobTitle == "Senior Manager Consulting Business Operationnel"
    assert profile.worksFor == "Acme France"
    assert profile.workLocation == "Paris, Île-de-France, France"
    assert "Île-de-France" in profile.workLocation


def test_two_part_title_takes_company_from_description():
    """A 2-part title only gives the name, so worksFor/workLocation must be
    parsed from the description."""
    profile = _StubSearch(
        [
            {
                "title": "Jane Doe - Consultante | LinkedIn",
                "url": TARGET_URL,
                "description": TARGET_DESCRIPTION,
                "image": None,
            }
        ]
    ).search(query="Jane Doe", name="Jane Doe")[0]

    assert profile.worksFor == "Acme France"
    assert profile.workLocation == "Paris, Île-de-France, France"
    # The current title parser does not derive a jobTitle from 2-part titles
    # and the description parser only extracts worksFor/workLocation, so this
    # field stays unset rather than being guessed.
    assert profile.jobTitle is None


def test_search_chain_falls_through_when_no_valid_profile():
    first = _StubEngine(profiles=[], results=[{"url": TARGET_URL}])
    second = _StubEngine(profiles=[object()])

    chain = SearchChain.__new__(SearchChain)
    chain.engines = [first, second]

    assert chain.search(name="Jane Doe", query="Jane Doe") is second


def test_brave_extract_skips_malformed_rows():
    engine = Brave.__new__(Brave)
    engine.raw_results = {
        "web": {
            "results": [
                {"title": None, "url": TARGET_URL, "description": "x"},
                {"url": TARGET_URL, "description": "missing title"},
                {"title": TARGET_TITLE, "description": "missing url"},
                {"title": TARGET_TITLE, "url": TARGET_URL},
                {"title": TARGET_TITLE, "url": TARGET_URL, "description": "valid"},
            ]
        }
    }

    engine.extract()

    # rows without title or url are skipped; a missing description is allowed
    assert len(engine.results) == 2
    assert all(row["url"] == TARGET_URL for row in engine.results)
    assert engine.results[0]["description"] is None


def test_bing_extract_skips_malformed_rows_and_rich_facts():
    engine = Bing.__new__(Bing)
    engine.raw_results = {
        "webPages": {
            "value": [
                {"snippet": "no name", "url": TARGET_URL},
                {"name": "No snippet", "url": TARGET_URL},
                {"name": "No url", "snippet": "x"},
                {
                    "name": "Jane Doe - Acme France | LinkedIn",
                    "snippet": TARGET_DESCRIPTION,
                    "url": TARGET_URL,
                    "openGraphImage": None,
                    "richFacts": [
                        {"hint": "not-a-dict"},
                        {"hint": {"text": "ADDRESS:LOCATIONGENERAL"}},
                        {"hint": {"text": "ADDRESS:LOCATIONGENERAL"}, "items": []},
                        {
                            "hint": {"text": "ADDRESS:LOCATIONGENERAL"},
                            "items": [{"text": "Paris, Île-de-France, France"}],
                        },
                    ],
                },
            ]
        }
    }

    engine.extract()

    assert len(engine.results) == 1
    assert engine.results[0]["url"] == TARGET_URL
    assert engine.results[0]["workLocation"] == "Paris, Île-de-France, France"


def test_google_vertexai_extract_skips_malformed_rows():
    engine = GoogleVertexAI.__new__(GoogleVertexAI)
    engine.raw_results = {
        "results": [
            {},
            {"document": {"derivedStructData": {"pagemap": {}}}},
            {"document": {"derivedStructData": {"pagemap": {"metatags": ["not-a-dict"]}}}},
            {
                "document": {
                    "derivedStructData": {
                        "pagemap": {
                            "metatags": [
                                {
                                    "og:title": TARGET_TITLE,
                                    "og:url": TARGET_URL,
                                    "og:description": "Sans accent &amp; sans locale",
                                    "locale": None,
                                }
                            ]
                        }
                    }
                }
            },
        ]
    }

    engine.extract()

    assert len(engine.results) == 1
    assert engine.results[0]["url"] == TARGET_URL
    assert engine.results[0]["country"] is None
    assert engine.results[0]["description"] == "Sans accent & sans locale"


@pytest.mark.asyncio
async def test_dig_linkedin_returns_url_and_worksfor(monkeypatch):
    expected_person = {
        "name": "Jane Doe",
        "url": TARGET_URL,
        "worksFor": ["Acme France"],
    }

    class _FakeEngine:
        def __init__(self):
            self.persons = []

        def to_persons(self, worksFor=None):  # noqa: N803, ARG002
            self.persons = [expected_person]
            return self.persons

    engine = _FakeEngine()

    class _FakeChain:
        def __init__(self, _settings):
            self.engine = engine

        def search(self, name, query):  # noqa: ARG002
            return self.engine

    monkeypatch.setattr(dig, "SearchChain", _FakeChain)

    person = await dig.linkedin("Jane Doe")

    assert person["url"] == TARGET_URL
    assert person["worksFor"] == ["Acme France"]


@pytest.mark.asyncio
async def test_dig_linkedin_handles_empty_worksfor_set(monkeypatch):
    received = {}

    class _FakeEngine:
        def __init__(self):
            self.persons = []

        def to_persons(self, worksFor=None):  # noqa: N803
            received["worksFor"] = worksFor
            self.persons = [{"name": "Jane Doe", "url": TARGET_URL}]
            return self.persons

    engine = _FakeEngine()

    class _FakeChain:
        def __init__(self, _settings):
            self.engine = engine

        def search(self, name, query):  # noqa: ARG002
            return self.engine

    monkeypatch.setattr(dig, "SearchChain", _FakeChain)

    person = await dig.linkedin("Jane Doe", worksFor=set())

    assert received["worksFor"] is None
    assert person["url"] == TARGET_URL
