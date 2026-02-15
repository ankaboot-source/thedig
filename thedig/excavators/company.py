#!/bin/python3
"""
Grab informations about a company from its domain
"""

import json
import os
import re
import shutil
import string
import tempfile
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Required

import pydantic
import rapidfuzz
import whoisdomain as whois
from bs4 import BeautifulSoup
from curl_cffi import requests
from loguru import logger as log
from pydantic import EmailStr, HttpUrl, StringConstraints, TypeAdapter
from typing_extensions import TypedDict

from .utils import absolutize, domain_to_urls, match_name, normalize

QUERY_TIMEOUT = 10
BROWSER_WAIT_AFTER_LOAD_MS = 1500
CRUNCHBASE_CHALLENGE_MARKERS = (
    "one moment, please",
    "just a moment...",
    "attention required! | cloudflare",
    "challenges.cloudflare.com",
    "cf-chl",
)


@dataclass
class WebResponse:
    url: str
    status_code: int
    reason: str
    text: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400


def _proxy_server(proxy) -> str | None:
    if isinstance(proxy, dict):
        return proxy.get("https") or proxy.get("http")
    return proxy


def _detect_patchright_chrome_path() -> str | None:
    override_path = os.getenv("THEDIG_PATCHRIGHT_CHROME_PATH")
    if override_path:
        return override_path

    cache_root = Path.home() / ".cache" / "ms-playwright"
    if not cache_root.exists():
        return None

    for pattern in ("chromium-*/chrome-linux64/chrome", "chromium-*/chrome-linux/chrome"):
        for candidate in sorted(cache_root.glob(pattern), reverse=True):
            if candidate.exists() and os.access(candidate, os.X_OK):
                return str(candidate)

    return None


def _http_fetch(url: str, proxy=None) -> WebResponse | None:
    request_kwargs: dict[str, object] = {
        "timeout": QUERY_TIMEOUT,
        "impersonate": os.getenv("THEDIG_CURL_IMPERSONATE", "chrome"),
    }
    proxy_server = _proxy_server(proxy)
    if proxy_server:
        request_kwargs["proxy"] = proxy_server

    try:
        response = requests.get(url, **request_kwargs)
    except requests.RequestsError as e:
        log.error(f"HTTP request failed for {url}: {e}")
        return None

    return WebResponse(
        url=str(response.url),
        status_code=response.status_code,
        reason=response.reason or "",
        text=response.text,
    )


async def _browser_fetch(url: str, proxy=None) -> WebResponse | None:
    try:
        from patchright.async_api import async_playwright
    except Exception as e:
        log.error(f"Patchright is unavailable: {e}")
        return None

    browser_timeout = int(float(QUERY_TIMEOUT) * 1000)
    user_data_dir = tempfile.mkdtemp(prefix="thedig-patchright-")

    launch_kwargs: dict[str, object] = {
        "user_data_dir": user_data_dir,
        "headless": os.getenv("THEDIG_PATCHRIGHT_HEADLESS", "false").lower() in {"1", "true", "yes"},
        "no_viewport": True,
    }
    proxy_server = _proxy_server(proxy)
    if proxy_server:
        launch_kwargs["proxy"] = {"server": proxy_server}

    executable_path = _detect_patchright_chrome_path()
    if executable_path:
        launch_kwargs["executable_path"] = executable_path
    else:
        launch_kwargs["channel"] = os.getenv("THEDIG_PATCHRIGHT_CHANNEL", "chrome")

    try:
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(**launch_kwargs)
            page = await context.new_page()
            response = await page.goto(url, wait_until="domcontentloaded", timeout=browser_timeout)
            await page.wait_for_timeout(BROWSER_WAIT_AFTER_LOAD_MS)

            status_code = response.status if response else 0
            reason = "OK" if status_code and status_code < 400 else "HTTP Error"
            page_response = WebResponse(
                url=page.url,
                status_code=status_code,
                reason=reason,
                text=await page.content(),
            )

            await context.close()
    except Exception as e:
        log.error(
            f"Patchright request failed for {url}: {e}. "
            "Install Chrome with `patchright install chrome` or set THEDIG_PATCHRIGHT_CHROME_PATH."
        )
        return None
    finally:
        shutil.rmtree(user_data_dir, ignore_errors=True)

    return page_response


def _parse_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _is_crunchbase_challenge(html: str) -> bool:
    lower_html = html.casefold()
    return any(marker in lower_html for marker in CRUNCHBASE_CHALLENGE_MARKERS)


def _extract_linkedin_ld_json(html: BeautifulSoup) -> dict | None:
    ld_json_node = html.select_one("script[type='application/ld+json']")
    if not ld_json_node:
        return None

    try:
        payload = json.loads(ld_json_node.get_text(strip=True))
    except json.JSONDecodeError as e:
        log.warning(f"Failed to decode LinkedIn JSON-LD: {e}")
        return None

    def _node_type(candidate: object) -> str:
        if not isinstance(candidate, dict):
            return ""
        return str(candidate.get("@type", "")).title()

    if isinstance(payload, dict):
        if "@graph" in payload and isinstance(payload["@graph"], list):
            graph = payload["@graph"]
            org_node = next((item for item in graph if _node_type(item) in {"Corporation", "Organization"}), None)
            if org_node:
                return org_node
            return next((item for item in graph if _node_type(item) in {"Website", "Webpage"}), None)

        if _node_type(payload) in {"Corporation", "Organization", "Website", "Webpage"}:
            return payload
        return payload

    if isinstance(payload, list):
        org_node = next((item for item in payload if _node_type(item) in {"Corporation", "Organization"}), None)
        if org_node:
            return org_node
        return next((item for item in payload if _node_type(item) in {"Website", "Webpage"}), None)

    return None


TO_IGNORE = (
    "Ano Nymous",
    "<data not disclosed>",
    "Contact Privacy Inc. Customer",
    "Data Protected",
    "DATA REDACTED",
    "Domain Privacy Trustee SA",
    "Domains By Proxy, LLC",
    "Data Privacy Protected",
    "Domain Privacy Service FBO Registrant",
    "Domain Privacy Service FBO Registrant.",
    "Domain Privacy Trustee",
    "Domain Protection Services",
    "GDPR Masked",
    "hidden",
    "Identity Protect Limited",
    "Identity Protection Service",
    "Jewella Privacy LLC Privacy ID#",
    "MyPrivacy.net",
    "NameBrightPrivacy.com",
    "NO FORMAT!",
    "None",
    "Not Disclosed",
    "Not shown, please visit www.dnsbelgium.be for webbased whois.",
    "[PRIVATE]",
    "Privacy Protection",
    "PrivacyGuardian.org llc",
    "Privacy service provided by Withheld for Privacy ehf",
    "REDACTED FOR PRIVACY",
    "Redacted for GDPR privacy",
    "Redacted for Privacy",
    "Redacted for Privacy Purposes",
    "Statutory Masking Enabled",
    "See PrivacyGuardian.org",
    "Super domains privacy",
    "Whois Privacy",
    "Whois Privacy Protection Foundation",
    "Whois Privacy Protection Service",
    "Whois Privacy Protection Service by VALUE-DOMAIN",
    "Whois Privacy Protection Service by onamae.com",
    "Whois Privacy Service",
    "Whoisprotection.cc",
    "Withheld for Privacy Purposes",
)

COMPANY_TYPE_ABBR = {
    "AG",
    "Co",
    "Corp",
    "Corporation",
    "EURL",
    "Inc",
    "LLC",
    "Ltd",
    "SA",
    "SARL",
    "SAS",
    "SASU",
}

DomainName = Annotated[
    str, StringConstraints(pattern=r"^([\w-]+\.)*(\w[\w-]{0,66})\.(?P<tld>[a-z]{2,18})$", strict=True)
]


class Organization(TypedDict, total=False):
    name: Required[str]
    description: set[str]
    address: set[str]
    description: set[str]
    founder: set[str]
    logo: HttpUrl
    image: set[HttpUrl]
    legalName: str
    location: set[str]
    # often a range x-y
    numberOfEmployees: str
    image: set[HttpUrl]
    sameAs: set[HttpUrl]
    url: HttpUrl
    email: EmailStr
    telephone: str
    foundingDate: str


class Corporation(Organization, total=False):
    tickerSymbol: str


class Company(Corporation, total=False):
    industry: set[str]
    revenue: str


def get_domain(email: EmailStr) -> str:
    return email.split("@")[1]


def get_name(domain: DomainName) -> str | None:
    d = domain.split(".")
    if len(d) > 2:
        return None
    return d[-2].replace("-", " ").lower()


def extract_name(text: str, domain: DomainName) -> str:
    return rapidfuzz.process.extractOne(
        domain,
        map(str.strip, re.split(":|-|\\|", text)),
        scorer=rapidfuzz.fuzz.QRatio,
    )[0]


def remove_shorter_duplicates(data: set):
    for d in data.copy():
        # it has been removed, so continue
        if d not in data:
            continue
        data_c = data.copy() - {
            d,
        }
        for d_c in data_c:
            if str(d_c).strip(string.whitespace + ".") in str(d).strip(string.whitespace + "."):
                data.remove(d_c)
    return data


def remove_company_type_abbrv(company: str) -> str:
    last_word = company.split(", ")[-1].split(" ")[-1].removesuffix(".")
    if last_word in COMPANY_TYPE_ABBR:
        company = company.removesuffix(".").removesuffix(last_word).removesuffix(", ").strip()
    return company


def company_from_whois(domain: DomainName) -> Company | None:
    try:
        result = whois.query(domain, ignore_returncode=True, timeout=float(QUERY_TIMEOUT))
    except whois.WhoisPrivateRegistry as e:
        log.error(f"Whois failed: {e}")
        return None
    except (whois.WhoisCommandFailed, whois.FailedParsingWhoisOutput, whois.UnknownTld, whois.WhoisCommandTimeout) as e:
        log.error(f"Whois failed: {e}")
        return None

    if not result:
        return None

    # the company name is the registrant in *this* whois implementation
    company = result.registrant

    if not company or company == result.registrar:
        log.debug("No result or the registrar is the registrant")
        return None

    # there is some domains who hide their real registrant name
    if any(ignore in company for ignore in TO_IGNORE):
        log.debug(f"Registrant in ignore list: {company}")
        return None

    cmp: Company = Company(name=remove_company_type_abbrv(company), legalName=company)

    return cmp


async def company_by_domain(domain: DomainName, proxy=None) -> Company | None:
    """Will get company using its domain whois

    Args:
        domain (str): domain of the company

    Returns:
        Company: company object
    """
    cmp: Company = company_from_whois(domain) or {}
    web_cmp: Company = await company_from_web(domain, proxy)
    if web_cmp:
        for field, value in web_cmp.items():
            if type(value) is set and len(value) > 1:
                cmp[field] = cmp.get(field, set()) | remove_shorter_duplicates(value)
            elif field in cmp:
                continue
            else:
                cmp[field] = value

    return cmp


async def company_from_web(domain: DomainName, proxy=None) -> Company | None:
    company = await company_from_website(domain, proxy)
    name = company.get("name", get_name(domain))
    if not name:
        return None

    cmps = []
    cmps.extend(
        (
            await company_from_crunchbase(name, domain, proxy),
            await company_from_indeed(name, domain, proxy),
            await company_from_linkedin(name, domain, proxy),
        )
    )
    if domain[-3:].lower() == ".fr":
        cmps.append(await company_from_societecom(name))

    for cmp in cmps:
        if not cmp:
            continue
        if not name and domain not in cmp["url"]:
            continue
        if not match_name(name, cmp["name"], acronym=True):
            continue
        for k, v in cmp.items():
            if type(v) is set and k in company:
                company[k].update(v)
            else:
                company[k] = v
    return company


async def find_company_societecom(name: str, proxy=None) -> HttpUrl | None:
    r = _http_fetch(
        f"https://www.societe.com/cgi-bin/liste?ori=avance&nom={urllib.parse.quote(name)}&exa=on",
        proxy=proxy,
    )
    if not r:
        return None

    if not r.ok:
        log.error(f"Couldn't get results for {r.url}: {r.status_code} : {r.reason}")
        return None

    html = _parse_html(r.text)
    links = html.select("a.ResultBloc__link__content")
    if not links:
        log.warning(f"No results for that name: {name}")
        return None
    # there is at least 6 links when only one result
    if len(links) > 6:
        log.warning(f"More than one company found with that name: {name}")
        return None

    href = links[0].get("href")
    if not href:
        return None

    return f"https://www.societe.com{href}"


async def company_from_societecom(name: str, proxy=None) -> Company | None:
    url = await find_company_societecom(name)

    if not url:
        return None

    r = _http_fetch(str(url), proxy=proxy)
    if not r:
        return None

    if not r.ok:
        log.error(f"{r.url} : {r.reason}")
        return None

    html = _parse_html(r.text)
    founding_date = html.select_one("span.TableTextGenerique")
    if not founding_date:
        return None

    cmp: Company = Company(
        name=name,
        foundingDate=founding_date.get_text(strip=True),
        sameAs={
            url,
        },
    )

    # eg "1 à 3 salariés"
    number_of_employees = html.select_one("div#trancheeff-histo-description") or html.select_one(
        "#effmoy-histo-description"
    )
    if number_of_employees:
        try:
            num_employees = number_of_employees.get_text(strip=True).split()
            if len(num_employees) > 1:
                cmp["numberOfEmployees"] = f"{num_employees[0]}-{num_employees[2]}"
            elif num_employees:
                cmp["numberOfEmployees"] = num_employees[0]
            else:
                log.debug(f"Number of employees is void: {number_of_employees.get_text(strip=True)}")
        except (UnicodeDecodeError, SystemError):  # Why SystemError?!
            log.error(f"Couldn't get number of employees because of encoding error from {url}")

    address_html = html.select_one("div.CompanyIdentity__adress__around")
    if not address_html:
        return cmp

    address = address_html.get_text("\n").splitlines()
    cmp["address"] = {
        ", ".join(address),
    }
    cmp["location"] = {
        ", ".join(address[-2:])[6:],
    }

    return cmp


async def company_from_indeed(name: str, domain: DomainName = "", proxy=None) -> Company | None:
    url = f"https://www.indeed.com/cmp/{name}"

    r = _http_fetch(url, proxy=proxy)
    if not r:
        return None

    if not r.ok:
        log.error(f"Couldn't get results for {r.url}: {r.reason}")
        return None

    html = _parse_html(r.text)
    name_found = html.select_one("div[itemprop=name]")
    if not name_found:
        log.debug("No company name found")
        return None

    found_name = name_found.get_text(strip=True)
    if found_name.lower() != name.lower() and found_name.lower() != domain.lower():
        log.debug(f"Company name found {found_name} doesn't match name given {name}")
        return None

    cmp: Company = Company(
        name=found_name,
        sameAs={
            r.url,
        },
    )

    link = html.select_one("a[data-testid='companyLink[]']")
    if not link:
        return None

    href = link.get("href")
    if not href:
        return None

    cmp["url"] = href

    # that's not the right company
    if domain not in cmp["url"] and cmp["url"] != url:
        log.debug("No URL found for {cmp}")
        return None

    cmp["sameAs"].add(cmp["url"])

    logo = html.select_one("img[itemprop=image]")
    logo_src = logo.get("src") if logo else None
    if logo_src and "placeholder" not in logo_src:
        cmp["logo"] = urllib.parse.urljoin(url, logo_src)
        cmp["image"] = {
            cmp["logo"],
        }

    location = html.select_one("a[data-tn-element='cmp-LocationsSectionlocation'] span")
    if location:
        cmp["location"] = {
            location.get_text(strip=True).removesuffix(" ..."),
        }

    numberOfEmployees = html.select_one("li[data-testid='companyInfo-employee'] div:last-child")
    if numberOfEmployees:
        cmp["numberOfEmployees"] = (
            "-".join(numberOfEmployees.get_text(strip=True).split(" to ")).replace(",", "").replace("\n", "")
        )

    industry = html.select_one("a[data-testid='industryInterLink']")
    if industry:
        cmp["industry"] = {
            industry.get_text(strip=True),
        }

    foundingDate = html.select_one("li[data-testid='companyInfo-founded'] div:last-child")
    if foundingDate:
        cmp["foundingDate"] = foundingDate.get_text(strip=True)

    revenue = html.select_one("li[data-testid='companyInfo-revenue'] span")
    if revenue:
        cmp["revenue"] = revenue.get_text(strip=True).replace("\n", "")

    description = html.select_one("div[data-testid='more-text'] p") or html.select_one(
        "div[data-testid='less-text'] p:first-child"
    )
    if description:
        cmp["description"] = {
            description.get_text(strip=True).removesuffix("...Show less"),
        }

    return cmp


async def company_from_linkedin(name: str, domain: DomainName = "", proxy=None) -> Company | None:
    cmp = await _company_from_linkedin(name, domain, proxy=proxy) or await _company_from_linkedin(
        name, domain, use_domain=True, proxy=proxy
    )
    return cmp


async def _company_from_linkedin(
    name: str, domain: DomainName = "", use_domain: bool = False, proxy=None
) -> Company | None:
    normalized_name = normalize(domain if use_domain else name, replace={" ": "", ".": "-"})
    url = f"https://www.linkedin.com/company/{normalized_name}"

    r = _http_fetch(url, proxy=proxy)
    if not r:
        return None

    if not r.ok:
        log.error(f"Couldn't get results for {r.url}: {r.reason}")
        return None

    html = _parse_html(r.text)
    name_found_ = html.select_one("h1")
    if not name_found_:
        log.error(f"No name found at {r.url}")
        return None

    name_found = name_found_.get_text(strip=True)

    if not match_name(name, name_found, fuzzy=False, acronym=True) and not match_name(domain, name_found, acronym=True):
        log.debug(f"Company name found {name_found} doesn't match name given {name}")
        return None

    ld_json = _extract_linkedin_ld_json(html)
    if not ld_json:
        return None

    linkedin_profile_url = ld_json.get("url")
    if not linkedin_profile_url:
        linkedin_profile_url = str(r.url)

    company_name = ld_json.get("name") or name_found
    if not company_name:
        return None

    cmp: Company = Company(name=company_name, sameAs={linkedin_profile_url})

    # if we don't have the Website's company, we can't be sure
    company_site = ld_json.get("sameAs")
    if not company_site:
        log.debug(f"No company's website for {cmp['name']}")
        return None

    if isinstance(company_site, str):
        cmp["url"] = company_site
        cmp["sameAs"].add(company_site)
    elif isinstance(company_site, list):
        urls = {candidate for candidate in company_site if isinstance(candidate, str)}
        if not urls:
            return None
        cmp["url"] = sorted(urls)[0]
        cmp["sameAs"].update(urls)
    else:
        return None

    # that's not the right company
    if use_domain and domain and domain not in cmp["url"] and cmp["url"] != url:
        log.debug(f"domain {domain} not found in the URL {cmp['url']}")
        return None

    if "numberOfEmployees" in ld_json:
        number_of_employees = ld_json["numberOfEmployees"]
        if isinstance(number_of_employees, dict):
            cmp["numberOfEmployees"] = str(number_of_employees.get("value", ""))
        elif isinstance(number_of_employees, str):
            cmp["numberOfEmployees"] = number_of_employees

    if "logo" in ld_json:
        logo = ld_json["logo"]
        if isinstance(logo, dict) and logo.get("contentUrl"):
            cmp["logo"] = logo["contentUrl"]
            cmp["image"] = {logo["contentUrl"]}
        elif isinstance(logo, str):
            cmp["logo"] = logo
            cmp["image"] = {logo}

    slogan = ld_json.get("slogan")
    if slogan:
        cmp["description"] = {
            slogan,
        }

    if "address" in ld_json:
        address = ld_json["address"]
        if isinstance(address, dict):
            location = (
                address.get("addressLocality", None),
                address.get("addressRegion", None),
                address.get("addressCountry", None),
            )
            location = {", ".join(loc for loc in location if loc)}
            if location and any(location):
                cmp["location"] = location

            address_values = [value for value in address.values() if value != "PostalAddress"]
            if address_values:
                cmp["address"] = {", ".join(address_values)}

    if "description" in ld_json:
        if "description" not in cmp:
            cmp["description"] = set()
        cmp["description"].add(ld_json["description"])

    return cmp


async def company_from_crunchbase(name: str, domain: DomainName = "", proxy=None) -> Company | None:
    url = f"https://www.crunchbase.com/organization/{normalize(name)}"

    r = await _browser_fetch(url, proxy=proxy)
    if not r:
        r = _http_fetch(url, proxy=proxy)
    if not r:
        log.error(f"Crunchbase lookup failed for {url}")
        return None

    if not r.ok:
        log.error(f"Couldn't get results for {r.url}: {r.status_code} - {r.reason}")
        return None

    if _is_crunchbase_challenge(r.text):
        log.debug(f"Crunchbase anti-bot challenge detected for {r.url}")
        return None

    html = _parse_html(r.text)
    name_found_html = html.select_one("h1.profile-name")
    if not name_found_html:
        return None

    name_found = name_found_html.get_text(strip=True).lower()
    if not name_found or all(name_found != n.lower() for n in (name, domain) if n):
        log.debug(f"Company name found {name_found} doesn't match name given {name}")
        return None

    cmp: Company = Company(name=name, sameAs={str(r.url)})
    description_html = html.select_one("span.description")
    if description_html:
        cmp["description"] = {description_html.get_text(strip=True)}

    summary = html.select("ul.icon_and_value > li.ng-star-inserted")
    if len(summary) >= 2:
        summary_link = summary[-2].select_one("a")
        if summary_link and summary_link.get("href"):
            cmp["url"] = summary_link.get("href")

            # that's not the right company
            if domain and domain not in cmp["url"] and cmp["url"] != url:
                return None

            cmp["sameAs"].add(cmp["url"])

        location = summary[0].get_text(strip=True)
        if location:
            cmp["location"] = {location}

        number_of_employees = summary[1].get_text(strip=True)
        if number_of_employees:
            cmp["numberOfEmployees"] = number_of_employees

    details_html = html.select("profile-section.ng-star-inserted li.ng-star-inserted")
    details_fields = {
        "Industries": {
            "field": "industry",
            "extract": lambda f: set(str.splitlines(f)),
        },
        "Founded Date": {
            "field": "foundingDate",
            "extract": str,
        },
        "Founders": {
            "field": "founder",
            "extract": lambda f: f.split(", "),
        },
        "Also Known As": {
            "field": "alternateName",
            "extract": lambda f: {
                f,
            },
        },
        "Legal Name": {
            "field": "legalName",
            "extract": str,
        },
        "Contact Email": {
            "field": "email",
            "extract": str,
        },
        "Phone Number": {
            "field": "telephone",
            "extract": str,
        },
    }
    for detail in details_html:
        detail_text = detail.get_text("\n", strip=True)
        if not detail_text or "\n" not in detail_text:
            break
        field, value = detail_text.split("\n", 1)
        if field in details_fields.keys():
            cmp[details_fields[field]["field"]] = details_fields[field]["extract"](value)

    image = html.select_one(".image-holder img")
    if image and image.get("src"):
        cmp["image"] = {image.get("src")}

    sameAs = {href for e in html.select('a[title^="View on"]') if (href := e.get("href"))}
    if sameAs:
        cmp["sameAs"] |= sameAs

    return cmp


async def company_from_website(domain: DomainName, proxy=None):
    cmp = {}
    urls = domain_to_urls(domain)
    r = None
    selected_url = ""
    for url in urls:
        r = _http_fetch(url, proxy=proxy)
        if r and r.ok:
            selected_url = url
            break

    if not r or not r.ok:
        return cmp

    html = _parse_html(r.text)

    # schema.org organization has the priority

    # first, let's try with JSON
    org_js = html.find("script", attrs={"type": "application/ld+json"})
    if org_js:
        # <script content="" attribute or inside <script></script> element
        org_json_ = json.loads(org_js.attrs["content"] if "content" in org_js.attrs else org_js.text, strict=False)
        org_json = None

        def eligible_json(candidate: dict) -> bool:
            return candidate.get("@type", "").title() in ("Organization", "Corporation", "Website")

        # select only first eligible JSON
        if type(org_json_) is list:
            org_json = next(filter(eligible_json, org_json_), None)
        elif eligible_json(org_json_):
            org_json = org_json_

        if org_json:
            fields = Company.__annotations__.keys() & org_json.keys()
            for field in fields:
                # weirdly, sometimes fields are just empty
                if not org_json[field]:
                    continue
                if "set[" in str(Company.__annotations__[field]) and type(org_json[field]) is str:
                    org_json[field] = {
                        org_json[field],
                    }
                try:
                    cmp[field] = TypeAdapter(
                        Company.__annotations__[field], config=dict(arbitrary_types_allowed=True)
                    ).validate_python(org_json[field])
                except pydantic.ValidationError:
                    log.debug(f"{org_json[field]} not type valid for field: {field}")
                    continue

    # then with HTML
    if not cmp:
        org_html = html.find(attrs={"itemtype": "http://schema.org/Organization"}) or html.find(
            attrs={"itemtype": "http://schema.org/Corporation"}
        )
        if org_html:
            for field in Company.__annotations__.keys():
                f_html = org_html.find(attrs={"itemprop": f"{field}"})
                # takes the first value only when not empty
                if f_html and f_html.attrs.get("content", None):
                    cmp[field] = f_html.attrs["content"]

    meta = html.find_all("meta")
    og_html = [m for m in meta if "property" in m.attrs and m.attrs["property"].startswith("og:")]
    if og_html:
        og_map = {
            "og:site_name": [
                {
                    "field": "name",
                    "extract": str,
                }
            ],
            # too many websites put "Home - Brand Name"
            #'og:title': [{
            #    'field': 'name',
            #    'extract': str,
            #    }],
            "og:image": [
                {
                    "field": "image",
                    "extract": lambda x: {
                        x,
                    },
                },
                {
                    "field": "logo",
                    "extract": str,
                },
            ],
            "og:description": [
                {
                    "field": "description",
                    "extract": lambda x: {
                        x,
                    },
                }
            ],
            "og:url": [
                {
                    "field": "sameAs",
                    "extract": lambda x: {
                        x,
                    },
                }
            ],
        }
        for og_field in og_html:
            if og_field.attrs["property"] not in og_map:
                continue
            og_dest = og_map[og_field.attrs["property"]]
            for dest in og_dest:
                # only add data if isn't already found through JSON Schema.org
                if dest["field"] in cmp.keys():
                    continue
                if "content" not in og_field.attrs:
                    continue
                cmp[dest["field"]] = dest["extract"](og_field.attrs["content"])

    # no need to continue
    if not cmp:
        return cmp

    cmp["url"] = selected_url
    if "sameAs" in cmp:
        cmp["sameAs"] = {absolutize(sameAs, selected_url) for sameAs in cmp["sameAs"]}
        cmp["sameAs"].add(selected_url)
    else:
        cmp["sameAs"] = {
            selected_url,
        }

    # name cleaning
    if "name" in cmp:
        cmp["name"] = extract_name(cmp["name"], domain)

    # sometimes URLs are relative URLs
    if "image" in cmp:
        cmp["image"] = {absolutize(image, selected_url) for image in cmp["image"]}
    if "logo" in cmp:
        cmp["logo"] = absolutize(cmp["logo"], selected_url)

    return cmp
