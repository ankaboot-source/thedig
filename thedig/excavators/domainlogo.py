#!/bin/env python3
"""
Enrichment related to a domain
- favicon
- country (exclusion list for country tld misused like .io)
"""

import re
import urllib.parse

from bs4 import BeautifulSoup
from curl_cffi import requests
from loguru import logger as log

from .utils import domain_to_urls

FAVICON_RE = re.compile("^(shortcut icon|icon)$", re.I)


def get_favicon(url: str, proxy=None):
    """check for favicon at a specific URL

    Args:
        favicon_url (str): favicon url to check

    Returns:
        URL if found
        False if not found but host answer
        None if the host does answer with a HTTP or Network error
    """
    favicon_url = f"{url}/favicon.ico"
    try:
        r = requests.get(favicon_url, proxies={"https": proxy, "http": proxy}, timeout=1)
    except requests.RequestsError:
        log.debug("No reachable host for this url: %s" % favicon_url)
        return None

    if r.ok and r.headers["Content-Type"] == "image/x-icon":
        log.debug("favicon found at this URL %s" % favicon_url)
        return favicon_url
    else:  # yet, this is probably the right website to scan
        log.debug("No favicon at this URL: %s" % favicon_url)
        return False


def get_ogimage(html, url) -> str | None:
    og_image_url = None
    og_image_tag = html.find("meta", attrs={"property": "og:image"})
    if og_image_tag:
        og_image = og_image_tag.get("content")
        og_image_url = urllib.parse.urljoin(url, og_image)

    return og_image_url


def scrap_favicon(url: str, proxy=None) -> str | None:
    """Scrap for favicon on a website
    fallback to og:image if found

    Args:
        url (str): website url
        proxy (str): https/socks5 proxy (optional)

    Returns:
        str: favicon url found
    """
    try:
        r = requests.get(url, proxies={"https": proxy, "http": proxy})
    except requests.RequestsError:
        return None

    if not r.ok:
        return None

    soup = BeautifulSoup(r.text, features="lxml")
    log.debug(f"That page's url seems Ok: {url}")

    favicon_link = soup.find("link", attrs={"rel": FAVICON_RE})
    if favicon_link:
        log.debug(f"We did find the favicon link in the HTML: {favicon_link}")
        favicon_href = favicon_link.get("href")
        favicon_url = urllib.parse.urljoin(url, favicon_href)
    else:
        favicon_url = get_ogimage(soup, url)

    return favicon_url


def find_favicon(domain: str, proxy=None) -> str:
    """Find a favicon from a domain

    Args:
        domain (str): domain
        proxy (str): https/socks5 proxy (optional)

    Returns:
        str: favicon URL
    """
    urls = domain_to_urls(domain)
    for url in urls:
        favicon_url = get_favicon(url, proxy=proxy)
        if favicon_url:
            return favicon_url
        elif favicon_url is None:  # not a valid website
            continue  # next URL
        elif not favicon_url:
            favicon_url = scrap_favicon(url, proxy=proxy)
            if favicon_url:
                return favicon_url


if __name__ == "__main__":
    import sys

    log.info(find_favicon(domain=sys.argv[1]))
