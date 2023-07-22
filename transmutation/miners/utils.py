"""
Various utilities
"""
__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__license__ = "AGPL"

from thefuzz import fuzz

TOKEN_RATIO = 96


def match_name(name: str, text: str) -> bool:
    if not name:
        return True
    return fuzz.partial_token_sort_ratio(name, text) >= TOKEN_RATIO


def normalize(name: str) -> str:
    return name.encode("ASCII", "ignore").strip().lower().decode().replace(" ", "")
