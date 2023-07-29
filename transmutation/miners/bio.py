"""
Mine bio from social network profiles
"""
__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__license__ = "AGPL"

import re
from json import load
import importlib.resources as pkg_resources
from . import data

RE_WORDS = re.compile(r"\w{3,}|of|to")
JOBTITLES = set(
    load(open(pkg_resources.files(data) / "jobtitles.json"))["job-titles"])


def normalize(text: str) -> str:
    return text.encode("ASCII", "ignore").lower().decode()


def find_jobtitle(text: str) -> set[str]:
    # split text in words
    words = re.findall(RE_WORDS, text)
    if not words:
        return None

    # this algorithm founds jobtitles by desc length
    # in order to avoid duplicates
    # 3, 2 then 1 word
    # eg. Senior Software Engineer is found once
    jobtitles = []
    i = 0
    while i < len(words):
        if (i + 2) < len(words):
            three_w = " ".join(words[i: i + 3])
            if normalize(three_w) in JOBTITLES:
                jobtitles.append(three_w)
                i += 3
                continue
        if (i + 1) < len(words):
            two_w = " ".join(words[i: i + 2])
            if normalize(two_w) in JOBTITLES:
                jobtitles.append(two_w)
                i += 2
                continue
        if normalize(words[i]) in JOBTITLES:
            jobtitles.append(words[i])
        i += 1

    return set(jobtitles) if jobtitles else None
