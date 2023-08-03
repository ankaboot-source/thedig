"""Whois Company Miner API"""
__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__copyright__ = "Ankaboot"
__license__ = "AGPL"

# service
from ..miners import whoiscompany

# fast api
from fastapi import APIRouter
from typing import List
from typing import Dict

# config
from .config import settings
from .config import setup_cache

# log
from loguru import logger as log

import asyncio

# set-up router
router = APIRouter()


cache = asyncio.get_event_loop().run_until_complete(
    setup_cache(settings, settings.cache_redis_db)
)


@router.get("/whoiscompany/{domain}")
async def whois_unique(domain: str) -> str:
    """Give company name based on the domain's owner

    Args:
        domain (str): domain

    Returns:
        str: company name
    """
    if domain in settings.public_email_providers:
        return None

    company = await cache.get(domain)
    if company:
        log.debug("Cache found for domain: %s" % domain)
        return company

    # no cache for this domain
    log.debug("The following domain is not cached: %s" % domain)
    company = whoiscompany.get_company(domain)

    # invalid data for this domain
    if company is None:
        log.debug("No valid data for this domain: %s" % domain)
        # redis refuse to store None so we'll use a void string instead
        # we won't check for this domain again for some time
        company = ""

    await cache.set(domain, company, ex=settings.cache_expiration)

    return company or None


@router.post("/whoiscompany")
async def whois_bulk(body: Dict[str, List[str]]) -> dict:
    companies = {}
    for domain in body["domains"]:
        if domain in settings.public_email_providers:
            company = None
        else:
            company = await cache.get(domain)
        if company is None:
            log.debug("The following domain is not cached: %s" % domain)
            company = whoiscompany.get_company(domain)
            if company is None:
                log.debug("No valid data for this domain: %s" % domain)
                company = ""
            await cache.set(domain, company, ex=settings.cache_expiration)
        log.info(f"Domain:company - {domain}:{company}")
        companies[domain] = company or None
    return companies


@router.delete("/whoiscompany/cache")
async def _whois_flushcache():
    """Flush cache"""
    return await cache.flushdb()
