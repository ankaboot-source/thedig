import pytest

from thedig.excavators.bio import find_gender, find_jobtitle, normalize


def test_normalize():
    assert normalize("Hello World!") == "hello world!"
    assert normalize("Café") == "caf"
    assert normalize("123 ABC") == "123 abc"


def test_find_gender():
    assert find_gender("She/Her pronouns") == "she/her"
    assert find_gender("He/Him") == "he/him"
    assert find_gender("They/Them") is None
    assert find_gender("No pronouns mentioned") is None


def test_find_jobtitle():
    assert find_jobtitle("I am a Software Engineer") == {"Software Engineer"}
    assert find_jobtitle("Senior Project Manager and Team Lead") == {"Senior Project Manager", "Team Lead"}
    assert find_jobtitle("No job title here") is None
    assert find_jobtitle("") is None

    # Test for longer job titles
    assert find_jobtitle("I am a Senior Software Engineer") == {"Senior Software Engineer"}

    # Test for case insensitivity
    assert find_jobtitle("i am a software ENGINEER") == {"software ENGINEER"}

    # Test for multiple occurrences
    assert find_jobtitle("Software Engineer and Project Manager") == {"Software Engineer", "Project Manager"}


@pytest.fixture
def mock_jobtitles(monkeypatch):
    mock_titles = {"software engineer", "project manager", "team lead", "senior software engineer"}
    monkeypatch.setattr("thedig.excavators.bio.JOBTITLES", mock_titles)


@pytest.mark.usefixtures("mock_jobtitles")
def test_find_jobtitle_with_mock():
    assert find_jobtitle("I am a Software Engineer") == {"Software Engineer"}
    assert find_jobtitle("Senior Software Engineer and Team Lead") == {"Senior Software Engineer", "Team Lead"}
    assert find_jobtitle("Data Scientist") is None
