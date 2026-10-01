import os
import json

import pytest

from thedig.excavators.company import (
    WebResponse,
    _detect_patchright_chrome_path,
    _extract_linkedin_ld_json,
    _parse_html,
    _company_from_linkedin,
    company_from_societecom,
    find_company_societecom,
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


@pytest.mark.asyncio
async def test_find_company_societecom_prefers_exact_label(monkeypatch):
    payload = {
        "hits": [
            {"label": "TF1 PRODUCTION", "alt": "TF1", "code": "c", "url": "/societe/352614663-352614663.html"},
            {"label": "TF1", "alt": "SIREAU", "code": "c", "url": "/societe/tf1-398257691.html"},
        ]
    }

    monkeypatch.setattr(
        "thedig.excavators.company._http_fetch",
        lambda *_args, **_kwargs: WebResponse(
            url="https://www.societe.com/cgi-bin/finder-api?q=tf1",
            status_code=200,
            reason="OK",
            text=json.dumps(payload),
        ),
    )

    result = await find_company_societecom("tf1")

    assert result == "https://www.societe.com/societe/tf1-398257691.html"


@pytest.mark.asyncio
async def test_find_company_societecom_avoids_alt_only_acronym_collisions(monkeypatch):
    payload = {
        "hits": [
            {"label": "S2FM", "alt": "SFR", "code": "c", "url": "/societe/790741953-790741953.html"},
            {"label": "SFR", "alt": "", "code": "c", "url": "/societe/sfr-343059564.html"},
        ]
    }

    monkeypatch.setattr(
        "thedig.excavators.company._http_fetch",
        lambda *_args, **_kwargs: WebResponse(
            url="https://www.societe.com/cgi-bin/finder-api?q=sfr",
            status_code=200,
            reason="OK",
            text=json.dumps(payload),
        ),
    )

    result = await find_company_societecom("sfr", domain="sfr.fr")

    assert result == "https://www.societe.com/societe/sfr-343059564.html"


@pytest.mark.asyncio
async def test_company_from_societecom_parses_core_fields(monkeypatch):
    payload = {
        "hits": [
            {"label": "AUTOMATTIC", "alt": "", "code": "c", "url": "/societe/automattic-123.html"},
        ]
    }

    profile_html = """
    <html>
      <span class="TableTextGenerique">01-01-2000</span>
      <div id="trancheeff-histo-description">1 à 3 salariés</div>
      <div class="CompanyIdentity__adress__around">
        12 rue Example
        75001 Paris
        FRANCE
      </div>
    </html>
    """

    def fake_http_fetch(url: str, *args, **kwargs):
        if "finder-api" in url:
            return WebResponse(url=url, status_code=200, reason="OK", text=json.dumps(payload))
        return WebResponse(url=url, status_code=200, reason="OK", text=profile_html)

    monkeypatch.setattr("thedig.excavators.company._http_fetch", fake_http_fetch)

    company = await company_from_societecom("Automattic")

    assert company is not None
    assert company["name"] == "Automattic"
    assert company.get("foundingDate") == "01-01-2000"
    assert company.get("numberOfEmployees") == "1-3"
    assert company.get("location")


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


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("THEDIG_RUN_INTEGRATION") != "1", reason="Set THEDIG_RUN_INTEGRATION=1 to run live tests")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("domain", "expected_name_token"),
    [
        ("sfr.fr", "sfr"),
        ("orange.fr", "orange"),
        ("bouyguestelecom.fr", "bouygues"),
    ],
)
async def test_company_by_domain_french_telcos_live_integration(domain: str, expected_name_token: str):
    company = await company_by_domain(domain)

    assert company is not None
    combined_name = f"{company.get('name', '')} {company.get('legalName', '')}".casefold()
    assert expected_name_token in combined_name
    assert company.get("sameAs") or company.get("url")


def test_detect_patchright_chrome_path_prefers_env_override(monkeypatch, tmp_path):
    fake = tmp_path / "chrome"
    fake.touch()
    monkeypatch.setenv("THEDIG_PATCHRIGHT_CHROME_PATH", str(fake))

    assert _detect_patchright_chrome_path() == str(fake)


def test_detect_patchright_chrome_path_finds_cached_chromium(monkeypatch, tmp_path):
    binary = tmp_path / ".cache" / "ms-playwright" / "chromium-1243" / "chrome-linux" / "chrome"
    binary.parent.mkdir(parents=True)
    binary.touch()
    binary.chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("THEDIG_PATCHRIGHT_CHROME_PATH", raising=False)

    assert _detect_patchright_chrome_path() == str(binary)


def test_detect_patchright_chrome_path_returns_none_when_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("THEDIG_PATCHRIGHT_CHROME_PATH", raising=False)

    assert _detect_patchright_chrome_path() is None
