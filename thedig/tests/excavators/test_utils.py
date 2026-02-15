from thedig.excavators.utils import (
    absolutize,
    domain_to_urls,
    get_tld,
    guess_country,
    match_name,
    normalize,
    ua_headers,
)


def test_absolutize():
    assert absolutize("https://example.com", "http://test.com") == "https://example.com"
    assert absolutize("/path", "http://test.com") == "http://test.com/path"
    assert absolutize("invalid", "http://test.com") == ""


def test_get_tld():
    assert get_tld("example.com") == "com"
    assert get_tld("sub.example.co.uk") == "uk"
    assert get_tld("example") == "example"


def test_guess_country():
    assert guess_country("example.com") is None
    assert guess_country("example.fr") == "France"
    assert guess_country("example.com.tn") == "Tunisia"


def test_domain_to_urls():
    assert domain_to_urls("example.com") == [
        "https://www.example.com",
        "https://example.com",
    ]


def test_ua_headers():
    headers = ua_headers()
    assert "user-agent" in headers
    assert headers["user-agent"] != ""


def test_match_name():
    assert match_name("John Doe", "John Doe") is True
    assert match_name("John Doe", "Doe, John") is True
    assert match_name("John Doe", "Jane Doe") is False
    assert match_name("John Doe", "John Smith") is False
    assert match_name("John H. Doe", "John Doe") is False
    assert match_name("The Big Company", "TBC", acronym=True) is True
    assert match_name("The Big Company", "TBD", acronym=True) is False
    assert match_name("John Doe", "johndoe", condensed=True) is True


def test_normalize():
    assert normalize("John Doe") == "johndoe"
    assert normalize("John Doe", {" ": "-"}) == "john-doe"
    assert normalize("J. Doe") == "jdoe"
