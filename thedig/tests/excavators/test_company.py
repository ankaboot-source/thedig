import os

import pytest

from thedig.excavators.company import (
    WebResponse,
    _extract_linkedin_ld_json,
    _parse_html,
    _company_from_linkedin,
    company_by_domain,
    company_from_linkedin,
)


def test_extract_linkedin_ld_json_from_graph_payload():
    html = _parse_html(
        """
        <html><head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@graph": [
            {"@type": "WebPage", "name": "Company page"},
            {
              "@type": "Corporation",
              "name": "Automattic",
              "url": "https://www.linkedin.com/company/automattic",
              "sameAs": "https://automattic.com"
            }
          ]
        }
        </script>
        </head></html>
        """
    )

    payload = _extract_linkedin_ld_json(html)

    assert payload is not None
    assert payload["name"] == "Automattic"
    assert payload["url"] == "https://www.linkedin.com/company/automattic"
    assert payload["sameAs"] == "https://automattic.com"


@pytest.mark.asyncio
async def test_company_from_linkedin_parses_automattic_payload(monkeypatch):
    html = """
    <html>
      <h1>Automattic</h1>
      <script type="application/ld+json">
      {
        "@type": "Corporation",
        "name": "Automattic",
        "url": "https://www.linkedin.com/company/automattic",
        "sameAs": "https://automattic.com",
        "description": "Automattic builds products for the web"
      }
      </script>
    </html>
    """

    monkeypatch.setattr(
        "thedig.excavators.company._http_fetch",
        lambda *_args, **_kwargs: WebResponse(
            url="https://www.linkedin.com/company/automattic",
            status_code=200,
            reason="OK",
            text=html,
        ),
    )

    company = await _company_from_linkedin("Automattic", "automattic.com")

    assert company is not None
    assert company["name"] == "Automattic"
    assert company.get("url") == "https://automattic.com"
    assert "https://automattic.com" in company.get("sameAs", set())


@pytest.mark.asyncio
async def test_company_from_linkedin_accepts_google_fr_with_google_name(monkeypatch):
    html = """
    <html>
      <h1>Google</h1>
      <script type="application/ld+json">
      {
        "@type": "Corporation",
        "name": "Google",
        "url": "https://www.linkedin.com/company/google",
        "sameAs": "https://goo.gle/3DLEokh",
        "description": "Google company profile"
      }
      </script>
    </html>
    """

    monkeypatch.setattr(
        "thedig.excavators.company._http_fetch",
        lambda *_args, **_kwargs: WebResponse(
            url="https://www.linkedin.com/company/google",
            status_code=200,
            reason="OK",
            text=html,
        ),
    )

    company = await _company_from_linkedin("Google", "google.fr", use_domain=False)

    assert company is not None
    assert company["name"] == "Google"
    assert company.get("url") == "https://goo.gle/3DLEokh"
    assert "https://www.linkedin.com/company/google" in company.get("sameAs", set())


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("THEDIG_RUN_INTEGRATION") != "1", reason="Set THEDIG_RUN_INTEGRATION=1 to run live tests")
@pytest.mark.asyncio
async def test_company_from_linkedin_automattic_live_integration():
    company = await company_from_linkedin("Automattic", "automattic.com")

    assert company is not None
    assert company["name"] == "Automattic"
    assert company.get("url") == "https://automattic.com"

    same_as = {str(item) for item in company.get("sameAs", set())}
    assert any("linkedin.com/company/automattic" in item for item in same_as)
    assert "https://automattic.com" in same_as

    description = company.get("description", set())
    assert description


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("THEDIG_RUN_INTEGRATION") != "1", reason="Set THEDIG_RUN_INTEGRATION=1 to run live tests")
@pytest.mark.asyncio
async def test_company_by_domain_automattic_com_live_integration():
    company = await company_by_domain("automattic.com")

    assert company is not None
    assert "automattic" in company["name"].casefold()
    assert "sameAs" in company and company["sameAs"]


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("THEDIG_RUN_INTEGRATION") != "1", reason="Set THEDIG_RUN_INTEGRATION=1 to run live tests")
@pytest.mark.asyncio
async def test_company_by_domain_google_fr_live_integration():
    company = await company_by_domain("google.fr")

    assert company is not None
    assert "google" in company["name"].casefold()
    assert "sameAs" in company and company["sameAs"]
