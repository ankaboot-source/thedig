#!/bin/python3
"""
Find the logo related to a domain
"""
__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__license__ = "AGPL"

import re
from bs4 import BeautifulSoup
import urllib.parse

import logging
import requests

log = logging.getLogger(__name__)

FAVICON_RE = re.compile("^(shortcut icon|icon)$", re.I)


def domain_to_urls(domain: str) -> list[str]:
    """Build hypothetical websites URL from a domain
    Gives priority to https then to www

    Args:
        domain (str): domain name

    Returns:
        list of urls
    """
    return [
        f"https://www.{domain}",
        f"https://{domain}",
        f"http://www.{domain}",
        f"http://{domain}",
    ]


def get_favicon(url: str) -> bool:
    """check for favicon at a specific URL

    Args:
        favicon_url (str): favicon url to check

    Returns:
        True if found
        False if not found but host answer
        None if the host does answer with a HTTP or Network error
    """
    favicon_url = f"{url}/favicon.ico"
    try:
        r = requests.get(favicon_url)
    except requests.RequestException:
        log.debug("No reachable host for this url: %s" % favicon_url)
        return None

    if r.ok and r.headers["Content-Type"] == "image/x-icon":
        log.debug("favicon found at this URL %s" % favicon_url)
        return True
    else:  # yet, this is probably the right website to scan
        log.debug("No favicon at this URL: %s" % favicon_url)
        return False


def scrap_favicon(url: str) -> str:
    """Scrap for favicon on a website
    fallback to og:image if found

    Args:
        url (str): website url

    Returns:
        str: favicon url found
    """
    try:
        r = requests.get(url)
    except requests.RequestException:
        return None

    if r.status_code == 200:
        soup = BeautifulSoup(r.text, features="lxml")
        log.debug("That page's url seems Ok: %s " % url)

        favicon_link = soup.find("link", attrs={"rel": FAVICON_RE})
        if favicon_link:
            log.debug("We did find the favicon link in the HTML: %s" %
                      favicon_link)
            favicon_href = favicon_link.get("href")
            favicon_url = urllib.parse.urljoin(url, favicon_href)
        else:
            og_image_tag = soup.find("meta", attrs={"property": "og:image"})
            if og_image_tag:
                log.debug("og:image found for this url: %s" % url)
                og_image = og_image_tag.get("content")
                favicon_url = urllib.parse.urljoin(url, og_image)
            else:
                log.debug("Nothing found sorry for this url: %s" % url)
                return None

    return favicon_url


def find_favicon(domain: str) -> str:
    """_summary_

    Args:
        domain (str): _description_

    Returns:
        str: _description_
    """
    urls = domain_to_urls(domain)
    for url in urls:
        favicon_url = get_favicon(url)
        if favicon_url:
            return favicon_url
        elif favicon_url is None:  # not a valid website
            continue  # next URL
        elif not favicon_url:
            favicon_url = scrap_favicon(url)
            if favicon_url:
                return favicon_url


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        format="%(asctime)-15s [%(levelname)s] %(funcName)s: %(message)s",
        level=logging.DEBUG,
    )

    log.info(find_favicon(domain=sys.argv[1]))
