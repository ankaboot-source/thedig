"""
Various utilities
"""
__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__license__ = "AGPL"

from thefuzz import fuzz
from fake_useragent import UserAgent

TOKEN_RATIO = 82


def ua_headers(random: bool = False) -> dict:
    """
    generate a random user-agent
    basic techniques against bot blockers
    """
    ua = UserAgent()
    if random:
        user_agent = ua.random
    else:
        user_agent = ua.chrome
    return {"user-agent": user_agent}


def match_name(name: str, text: str) -> bool:
    if not name:
        return True
    return fuzz.partial_token_sort_ratio(name, text) >= TOKEN_RATIO


def normalize(name: str) -> str:
    return name.encode("ASCII", "ignore").strip().lower().decode().replace(" ", "")
