from unittest.mock import AsyncMock

import pytest

from thedig.api import dig


@pytest.mark.asyncio
async def test_worksfor_adds_company_name(monkeypatch):
    company_by_domain = AsyncMock(return_value={"name": "Ankaboot"})

    monkeypatch.setattr(dig.settings, "public_email_providers", {"gmail.com"})
    monkeypatch.setattr(dig, "company_by_domain", company_by_domain)

    assert await dig.worksfor("team@ankaboot.io") == {"worksFor": {"Ankaboot"}}
    company_by_domain.assert_awaited_once()


@pytest.mark.asyncio
async def test_worksfor_ignores_company_without_name(monkeypatch):
    """Regression: company_by_domain may return a truthy dict with no 'name'
    key (whois failed, website lookup contributed other fields only).
    worksfor must not raise KeyError (thedig#95)."""
    company_by_domain = AsyncMock(return_value={"url": "https://ankaboot.io", "description": {"Ankaboot"}})

    monkeypatch.setattr(dig.settings, "public_email_providers", {"gmail.com"})
    monkeypatch.setattr(dig, "company_by_domain", company_by_domain)

    assert await dig.worksfor("team@ankaboot.io") == {"worksFor": set()}
    company_by_domain.assert_awaited_once()
