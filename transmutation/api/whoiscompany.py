"""Whois Company Miner API"""
import redis

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
from .config import redis_parameters as redis_param

# log
from loguru import logger as log

# set-up router
router = APIRouter()

# redis for cache

redis_param["db"] = settings.cache_redis_db
redis_param["decode_responses"] = True
cache = redis.Redis(**redis_param)
log.info("Set-up Redis cache for whoiscompany")


@router.get("/whoiscompany/{domain}")
def whois_unique(domain: str) -> str:
    """Give company name based on the domain's owner

    Args:
        domain (str): domain

    Returns:
        str: company name
    """
    if domain in settings.public_email_providers:
        return None

    company = cache.get(domain)
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

    cache.set(domain, company, ex=settings.cache_expiration)

    return company or None


@router.post("/whoiscompany")
def whois_bulk(body: Dict[str, List[str]]) -> dict:
    companies = {}
    for domain in body["domains"]:
        if domain in settings.public_email_providers:
            company = None
        else:
            company = cache.get(domain)
        if company is None:
            log.debug("The following domain is not cached: %s" % domain)
            company = whoiscompany.get_company(domain)
            if company is None:
                log.debug("No valid data for this domain: %s" % domain)
                company = ""
            cache.set(domain, company, ex=settings.cache_expiration)
        log.info(f"Domain:company - {domain}:{company}")
        companies[domain] = company or None
    return companies


@router.delete("/whoiscompany/cache")
def _whois_flushcache():
    """Flush cache"""
    return cache.flushdb()
