#!/bin/python3
"""
Return company name based on domain's email address whois
"""
import logging
import whoisdomain as whois

__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__license__ = "AGPL"

TO_IGNORE = {
    "Statutory Masking Enabled",
    "Privacy service provided by Withheld for Privacy ehf",
    "Data Protected",
    "Whois Privacy Service",
    "Redacted for Privacy Purposes",
    "REDACTED FOR PRIVACY",
}

log = logging.getLogger(__name__)


def get_domain(email: str) -> str:
    return email.split("@")[1]


def get_company(domain: str) -> str:
    try:
        result = whois.query(domain, ignore_returncode=True)
    except whois.WhoisPrivateRegistry as e:
        log.error(f"Whois failed: {e}")
        return None
    except whois.WhoisCommandFailed as e:
        log.error(f"Whois failed: {e}")
        return None

    # if the whois request does answer a proper string
    if not result:
        return None

    # the company name is the registrant in *this* whois implementation
    company = result.registrant

    # there is some domains who hide their real registrant name
    if company in TO_IGNORE:
        log.debug(f"Registrant in ignore list: {company}")
        return None

    return company


def get_company_from_email(email: str) -> str:
    """return company name from an email address

    Args:
        email (str): email address

    Returns:
        str: company name
    """
    domain = get_domain(email)
    return get_company(domain)


def get_company_from_person(person: dict) -> dict:
    domain = get_domain(person["email"])
    company = get_company(domain)
    person["worksFor"] = {"legalName": company, "name": company}
    return person


def bulk_companies_from_domains(domains: list) -> dict:
    return {domain: get_company(domain) for domain in domains}


def bulk_companies_from_emails(emails: list) -> dict:
    domains = {}

    # build directory of domains
    for email in emails:
        domain = get_domain(email)
        if domain not in domains:
            domains[domain] = [email]
        else:
            domains[domain].append(email)

    # map emails to companies based on their domain
    companies = {}
    for domain in domains:
        company = get_company(domain)
        for email in domains[domain]:
            companies[email] = company

    return companies


def bulk_company_from_person(persons: list) -> list:
    return None


if __name__ == "__main__":
    import sys

    # print({domain:get_company(domain) for domain in sys.argv[1:]})
    print(bulk_companies_from_emails(sys.argv[1:]))
