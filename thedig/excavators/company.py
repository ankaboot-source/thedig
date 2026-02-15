#!/bin/python3
"""
Grab informations about a company from its domain
"""

import json
import random
import re
import string
import urllib.parse
from typing import Annotated, Required

import hrequests
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
    r = hrequests.get(
        f"https://www.societe.com/cgi-bin/liste?ori=avance&nom={urllib.parse.quote(name)}&exa=on",
        timeout=QUERY_TIMEOUT,
        proxy=proxy,
    )
    if not r.ok:
        log.error(f"Couldn't get results for {r.url}: {r.status_code} : {r.reason}")
        return None

    links = r.html.find_all("a.ResultBloc__link__content")
    if not links:
        log.warning(f"No results for that name: {name}")
        return None
    # there is at least 6 links when only one result
    if len(links) > 6:
        log.warning(f"More than one company found with that name: {name}")
        return None

    return f"https://www.societe.com{links[0].attrs['href']}"


async def company_from_societecom(name: str, proxy=None) -> Company | None:
    url = await find_company_societecom(name)

    if not url:
        return None

    r = hrequests.get(url, timeout=QUERY_TIMEOUT, proxy=proxy)
    if not r.ok:
        log.error(f"{r.url} : {r.reason}")
        return None

    cmp: Company = Company(
        name=name,
        foundingDate=r.html.find("span.TableTextGenerique").text.strip(),
        sameAs={
            url,
        },
    )

    # eg "1 à 3 salariés"
    number_of_employees = r.html.find("div#trancheeff-histo-description") or r.html.find("#effmoy-histo-description")
    if number_of_employees:
        try:
            num_employees = number_of_employees.text.split()
            if len(num_employees) > 1:
                cmp["numberOfEmployees"] = f"{num_employees[0]}-{num_employees[2]}"
            elif num_employees:
                cmp["numberOfEmployees"] = num_employees[0]
            else:
                log.debug(f"Number of employees is void: {number_of_employees.text}")
        except (UnicodeDecodeError, SystemError):  # Why SystemError?!
            log.error(f"Couldn't get number of employees because of encoding error from {url}")

    address = r.html.find("div.CompanyIdentity__adress__around").text.splitlines()
    cmp["address"] = {
        ", ".join(address),
    }
    cmp["location"] = {
        ", ".join(address[-2:])[6:],
    }

    return cmp


async def company_from_indeed(name: str, domain: DomainName = "", proxy=None) -> Company | None:
    url = f"https://www.indeed.com/cmp/{name}"

    try:
        r = hrequests.get(url, timeout=QUERY_TIMEOUT, proxy=proxy)
    except Exception as e:
        log.error(e)
        return

    if not r.ok:
        log.error(f"Couldn't get results for {r.url}: {r.reason}")
        return None
    try:
        name_found = r.html.find("div[itemprop=name]")
    except Exception as e:
        log.error(e)
        return
    if not name_found:
        log.debug("No company name found")
        return

    if name_found.text.lower() != name.lower() and name_found.text.lower() != domain.lower():
        log.debug(f"Company name found {name_found.text} doesn't match name given {name}")
        return None

    cmp: Company = Company(
        name=name_found.text,
        sameAs={
            r.url,
        },
    )

    link = r.html.find("a[data-testid='companyLink[]']")
    if not link:
        return {}
    cmp["url"] = link.attrs["href"]

    # that's not the right company
    if domain not in cmp["url"] and cmp["url"] != url:
        log.debug("No URL found for {cmp}")
        return {}

    cmp["sameAs"].add(cmp["url"])

    logo = r.html.find("img[itemprop=image]")
    if logo and "placeholder" not in logo.attrs["src"]:
        cmp["logo"] = urllib.parse.urljoin(url, logo.attrs["src"])
        cmp["image"] = {
            cmp["logo"],
        }

    location = r.html.find("a[data-tn-element='cmp-LocationsSectionlocation'] span")
    if location:
        cmp["location"] = {
            location.text.removesuffix(" ..."),
        }

    numberOfEmployees = r.html.find("li[data-testid='companyInfo-employee'] div:last-child")
    if numberOfEmployees:
        cmp["numberOfEmployees"] = "-".join(numberOfEmployees.text.split(" to ")).replace(",", "").replace("\n", "")

    industry = r.html.find("a[data-testid='industryInterLink']")
    if industry:
        cmp["industry"] = {
            industry.text,
        }

    foundingDate = r.html.find("li[data-testid='companyInfo-founded'] div:last-child")
    if foundingDate:
        cmp["foundingDate"] = foundingDate.text

    revenue = r.html.find("li[data-testid='companyInfo-revenue'] span")
    if revenue:
        cmp["revenue"] = revenue.text.replace("\n", "")

    description = r.html.find("div[data-testid='more-text'] p") or r.html.find(
        "div[data-testid='less-text'] p:first-child"
    )
    if description:
        cmp["description"] = {
            description.text.removesuffix("...Show less"),
        }

    return cmp


async def company_from_linkedin(name: str, domain: DomainName = "", proxy=None) -> Company | None:
    cmp = await _company_from_linkedin(name, domain, proxy) or await _company_from_linkedin(
        name, domain, use_domain=True, proxy=proxy
    )
    return cmp


async def _company_from_linkedin(
    name: str, domain: DomainName = "", use_domain: bool = False, proxy=None
) -> Company | None:
    normalized_name = normalize(domain if use_domain else name, replace={" ": "", ".": "-"})
    url = f"https://www.linkedin.com/company/{normalized_name}"
    try:
        r = hrequests.get(
            url,
            timeout=QUERY_TIMEOUT,
            # verify=False,
            proxy=proxy,
        )
    except Exception as e:
        log.error(f"{e}")
        return None

    if not r.ok:
        log.error(f"Couldn't get results for {r.url}: {r.reason}")
        return None

    name_found_ = r.html.find("h1")
    if not name_found_:
        log.error(f"No name found at {r.url}")
        return
    name_found = name_found_.text.strip()

    if not match_name(name, name_found, fuzzy=False, acronym=True) and not match_name(domain, name_found, acronym=True):
        log.debug(f"Company name found {name_found} doesn't match name given {name}")
        return None

    ld_json = json.loads(r.html.find("script[type='application/ld+json']").text)

    try:
        cmp: Company = Company(
            name=ld_json["name"],
            sameAs={
                ld_json["url"],
            },
        )
    except TypeError as e:
        log.warning(e)
        return None

    # if we don't have the Website's company, we can't be sure
    if "sameAs" not in ld_json:
        log.debug(f"No company's website for {cmp['name']}")
        return {}

    cmp["url"] = ld_json["sameAs"]

    # that's not the right company
    if domain not in cmp["url"] and cmp["url"] != url:
        log.debug(f"domain {domain} not found in the URL {cmp['url']}")
        return {}

    if "numberOfEmployees" in ld_json:
        cmp["numberOfEmployees"] = str(ld_json["numberOfEmployees"]["value"])

    if "logo" in ld_json:
        cmp["logo"] = ld_json["logo"]["contentUrl"]
        cmp["image"] = {
            ld_json["logo"]["contentUrl"],
        }

    slogan = ld_json.get("slogan")
    if slogan:
        cmp["description"] = {
            slogan,
        }

    if "address" in ld_json:
        location = (
            ld_json["address"].get("addressLocality", None),
            ld_json["address"].get("addressRegion", None),
            ld_json["address"].get("addressCountry", None),
        )
        location = {", ".join(loc for loc in location if loc)}
        if location:
            cmp["location"] = location
        address_l = list(ld_json["address"].values())
        address_l.remove("PostalAddress")
        cmp["address"] = {
            ", ".join(address_l),
        }

    if "description" in ld_json:
        if "description" not in cmp:
            cmp["description"] = set()
        cmp["description"].add(ld_json["description"])

    return cmp


async def company_from_crunchbase(name: str, domain: DomainName = "", proxy=None) -> Company | None:
    url = f"https://www.crunchbase.com/organization/{normalize(name)}"
    try:
        r = hrequests.get(
            url,
            timeout=QUERY_TIMEOUT,
            proxy=proxy,
            browser=random.choice(("firefox", "chrome")),
            os=random.choice(("win", "lin", "mac")),
        )
    except Exception as e:
        log.error(f"Crunchbase: {e}")
        return None

    if not r.ok:
        log.error(f"Couldn't get results for {r.url}: {r.status_code} - {r.reason}")
        return None

    name_found = r.html.find("h1.profile-name").text.lower()
    if not name_found or all([name_found != n.lower() for n in (name, domain)]):
        log.debug(f"Company name found {name_found} doesn't match name given {name}")
        return None

    cmp: Company = Company(
        name=name,
        description={
            r.html.find("span.description").text,
        },
    )

    cmp["sameAs"] = {
        r.url,
    }

    summary = r.html.find_all("ul.icon_and_value > li.ng-star-inserted")
    if len(summary) >= 2:
        cmp["url"] = summary[-2].find("a").attrs["href"]

        # that's not the right company
        if domain not in cmp["url"] and cmp["url"] != url:
            return {}

        cmp["location"] = {
            summary[0].text,
        }
        cmp["numberOfEmployees"] = summary[1].text
        cmp["sameAs"].add(summary[-2].find("a").attrs["href"])

    details_html = r.html.find_all("profile-section.ng-star-inserted li.ng-star-inserted")
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
        if not detail.text:
            break
        field, value = detail.text.split("\n", 1)
        if field in details_fields.keys():
            cmp[details_fields[field]["field"]] = details_fields[field]["extract"](value)

    image = r.html.find(".image-holder img")
    if image:
        cmp["image"] = image.attrs["src"]

    sameAs = {e.attrs["href"] for e in r.html.find_all('a[title^="View on"]')}
    if sameAs:
        cmp["sameAs"] |= sameAs

    return cmp


async def company_from_website(domain: DomainName, proxy=None):
    cmp = {}
    urls = domain_to_urls(domain)
    for url in urls:
        try:
            r = requests.get(url, proxy=proxy, timeout=QUERY_TIMEOUT)
            if r.ok:
                break
        except requests.RequestsError:
            r = None
            continue
    if not r or not r.ok:
        return cmp

    html = BeautifulSoup(r.text, "lxml")

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

    cmp["url"] = url
    if "sameAs" in cmp:
        cmp["sameAs"] = {absolutize(sameAs, url) for sameAs in cmp["sameAs"]}
        cmp["sameAs"].add(url)
    else:
        cmp["sameAs"] = {
            url,
        }

    # name cleaning
    if "name" in cmp:
        cmp["name"] = extract_name(cmp["name"], domain)

    # sometimes URLs are relative URLs
    if "image" in cmp:
        cmp["image"] = {absolutize(image, url) for image in cmp["image"]}
    if "logo" in cmp:
        cmp["logo"] = absolutize(cmp["logo"], url)

    return cmp
