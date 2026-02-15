import pytest

from thedig.excavators.splitfullname import is_company, split_fullname


@pytest.mark.parametrize(
    "fullname, domain, expected",
    [
        ("John Doe", "example.com", {"givenName": "John", "familyName": "Doe"}),
        ("DOE John", "example.com", {"givenName": "John", "familyName": "DOE"}),
        ("Dr. Jane Smith", "example.com", {"givenName": "Jane", "familyName": "Smith", "jobTitle": "Dr"}),
        ("van der Waals", "example.com", {"givenName": "van", "familyName": "der Waals"}),
        ("John", "example.com", {"givenName": "John"}),
        ("Smith, John", "example.com", {"givenName": "John", "familyName": "Smith"}),
        ("Contact", "example.com", None),
        ("Example Company", "example.com", None),
        ("J", "example.com", None),
    ],
)
def test_split_fullname(fullname, domain, expected):
    assert split_fullname(fullname, domain) == expected


@pytest.mark.parametrize(
    "name, domain, expected",
    [
        ("Example Company", "example.com", True),
        ("John Doe", "example.com", False),
        ("Acme", "acme.com", True),
        ("Google", "google.com", True),
        ("Jane Smith", "google.com", False),
    ],
)
def test_is_company(name, domain, expected):
    assert is_company(name, domain) == expected


def test_split_fullname_no_domain():
    assert split_fullname("John Doe") == {"givenName": "John", "familyName": "Doe"}


def test_split_fullname_invalid_input():
    assert split_fullname("123") is None
    assert split_fullname("") is None
    assert split_fullname(" ") is None


@pytest.mark.parametrize(
    "fullname, domain, expected",
    [
        ("Mr John Doe", "example.com", {"givenName": "John", "familyName": "Doe"}),
        ("John Doe PhD", "example.com", {"givenName": "John", "familyName": "Doe"}),
        ("Service Client", "example.com", None),
    ],
)
def test_split_fullname_edge_cases(fullname, domain, expected):
    assert split_fullname(fullname, domain) == expected
