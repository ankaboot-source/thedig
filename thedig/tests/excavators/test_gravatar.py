import pytest
from curl_cffi.requests import RequestsError

from thedig.excavators.gravatar import email_hash, gravatar


@pytest.mark.parametrize(
    "email, expected_hash",
    [
        ("myemailaddress@example.com", "0bc83cb571cd1c50ba6f3e8a78ef1346"),
        ("UPPERCASE@EXAMPLE.COM", "75d9e1b22db0d5981a0d7dd91ff01982"),
        ("user.name+tag@example.com", "0c74dcad1a1a306543e1d3d59f17dfcf"),
    ],
)
def test_email_hash(email, expected_hash):
    assert email_hash(email) == expected_hash


class FakeAsyncSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, *_args, **_kwargs):
        if self.error:
            raise self.error
        return self.response


@pytest.mark.asyncio
async def test_gravatar_no_check():
    email = "test@example.com"
    expected_url = f"https://www.gravatar.com/avatar/{email_hash(email)}?d=404&s=400"
    result = await gravatar(email, check=False)
    assert result == expected_url


@pytest.mark.asyncio
async def test_gravatar_with_check_success(mocker):
    email = "test@example.com"
    expected_url = f"https://www.gravatar.com/avatar/{email_hash(email)}?d=404&s=400"

    mock_response = mocker.Mock()
    mock_response.ok = True

    mocker.patch("thedig.excavators.gravatar.AsyncSession", return_value=FakeAsyncSession(response=mock_response))

    result = await gravatar(email, check=True)
    assert result == expected_url


@pytest.mark.asyncio
async def test_gravatar_with_check_failure(mocker):
    email = "test@example.com"

    mock_response = mocker.Mock()
    mock_response.ok = False

    mocker.patch("thedig.excavators.gravatar.AsyncSession", return_value=FakeAsyncSession(response=mock_response))

    result = await gravatar(email, check=True)
    assert result is None


@pytest.mark.asyncio
async def test_gravatar_with_request_error(mocker):
    email = "test@example.com"

    mocker.patch(
        "thedig.excavators.gravatar.AsyncSession",
        return_value=FakeAsyncSession(error=RequestsError("Test error")),
    )
    mocker.patch("thedig.excavators.gravatar.log.error")

    result = await gravatar(email, check=True)
    assert result is None
