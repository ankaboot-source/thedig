#!/bin/env python3
"""
Enrichment related to a domain
- favicon
- country (exclusion list for country tld misused like .io)
"""
__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__license__ = "AGPL"

import re
import logging
from contextlib import suppress

try:
    from .utils import match_name, normalize
except ImportError:
    from utils import match_name, normalize
# import spacy
# import xx_ent_wiki_sm

log = logging.getLogger(__name__)
# nlp = xx_ent_wiki_sm.load()

FAMILYNAME_SEPARATOR = {
    "إبن",
    "بن",
    "a",
    "ab",
    "af",
    "ap",
    "abu",
    "aït",
    "al",
    "ālam",
    "at",
    "ath",
    "aust",
    "bar",
    "bath",
    "ben",
    "bin",
    "bint",
    "d'",
    "da",
    "de",
    "degli",
    "del",
    "dele",
    "della",
    "der",
    "di",
    "dos",
    "du",
    "e",
    "el",
    "ferch",
    "fitz",
    "i",
    "ibn",
    "ka",
    "kil",
    "la",
    "le",
    "lil",
    "lille",
    "lu",
    "m'",
    "mac",
    "mc",
    "mck",
    "mhic",
    "mic",
    "mala",
    "mellom",
    "na",
    "ned",
    "neder",
    "ngā",
    "nic",
    "nin",
    "nord",
    "ny",
    "o",
    "o'",
    "opp",
    "ost",
    "över",
    "øvste",
    "ó",
    "öz",
    "pour",
    "'s",
    "setia",
    "setya",
    "stor",
    "söder",
    "'t",
    "te",
    "ter",
    "tre",
    "ua",
    "ui",
    "van",
    "väst",
    "verch",
    "vest",
    "vesle",
    "von",
    "war",
    "zu",
}

CIVILITY = {
    "M",
    "Mme",
    "Mlle",
    "Mr",
    "Mrs",
    "Ms",
}

ROLE_NAMES = {
    "contact",
    "forum",
    "secretariat",
    "secretario",
    "service",
    "service client",
    "support",
    "wordpress",
}

JOBTITLES = {
    "Dr": "Doctor",
    "Ing": "Engineer",
    "Eng": "Engineer",
    "Engr": "Engineer",
    "Phd": "Doctor",
    "Pr": "Professor",
    "Prof": "Professor",
}

RE_WHITESPACE = re.compile(r"\s+")
RE_ALPHA = re.compile(r"\b[^\W\d_]+\b")

BUSINESS_SEPARATOR = {
    "from",
    "van",
    "von",
    "de",
    "d",
}


def order(firstname: str, familyname: str) -> dict:
    # FAMILY NAME First Name (reversed)
    if firstname.isupper() and not familyname.isupper():
        return {
            "familyname": firstname,
            "firstname": familyname,
        }
    return {
        "familyname": familyname,
        "firstname": firstname,
    }


def is_company(name: str, domain: str) -> bool:
    for sep in BUSINESS_SEPARATOR:
        if name.startswith(sep):
            name = name.removeprefix(sep)
            break

    _name = normalize(name)

    return _name in (domain.split(".")[-2], domain, ".".join(domain.split(".")[-2:]))


# def is_organization(familyname: str) -> bool:
#    return any(
#        map(lambda e: e.label_ == "ORG",
#        nlp(familyname).ents
#        ))


def _split_fullname(fullname: str) -> dict:
    # needs to look like a word somehow
    if not re.match(RE_ALPHA, fullname):
        return None

    # minimum to guess length is 4
    # needs a space somewhere in between
    if len(fullname) < 4 or " " not in fullname.strip():
        log.debug("Too short or only one word")
        return {
            "firstname": fullname,
            "familyname": None,
        }

    # e.g FAMILY NAME, First Name
    comma_format = fullname.split(",")
    if len(comma_format) == 2 and comma_format[0].isupper():
        log.debug("Comma format detected")
        return {
            "familyname": comma_format[0],
            "firstname": comma_format[1],
        }

    # normalize white spaces then split into words
    fullname = RE_WHITESPACE.sub(" ", fullname).strip()
    words = fullname.split(" ")

    # eg. Dr. First Name FamilyName
    jobtitle = None
    if len(words[0]) > 1 and len(words[0]) < 5:
        # if last caracter end with a '.' we remove it for test purpose
        _jobtitle = words[0] if words[0][-1] != "." else words[0][:-1]
        if _jobtitle in JOBTITLES:
            log.debug(f"Jobtitle detected {_jobtitle}")
            jobtitle = _jobtitle
            words.pop(0)

    # e.g FirstName FamilyName
    if len(words) == 2:
        log.debug("Only two words")
        return {**order(words[0], words[1]), **{"jobtitle": jobtitle}}

    # eg. First name FAMILY NAME (or the opposite)
    firstname = words[0]
    familyname = None

    last_word_upper = words[-1].isupper()
    first_word_upper = words[0].isupper()

    if first_word_upper ^ last_word_upper:
        log.debug("One of words is uppercase")
        # trick to reverse test
        isfamily = str.isupper if last_word_upper else lambda f: not str.isupper(
            f)
        for i in range(len(words)):
            if isfamily(words[i]):
                break
        firstname = " ".join(words[:i])
        familyname = " ".join(words[i:])
        if first_word_upper:
            firstname, familyname = familyname, firstname
    else:
        # eg. First Name Van Family Name
        for i in range(1, len(words) - 1):
            if words[i].lower() in FAMILYNAME_SEPARATOR:
                log.debug(f"Familyname separator found: {words[i]}")
                firstname = " ".join(words[:i])
                familyname = " ".join(words[i:])
                break

    if firstname:
        return {
            "firstname": firstname,
            "familyname": familyname,
            #               'familyname': familyname if is_organization(familyname) else None,
            "jobtitle": jobtitle,
        }


def split_fullname(fullname: str, domain: str = None) -> dict:
    if is_company(fullname, domain):
        return None

    splitted = _split_fullname(fullname)
    if not splitted:
        return None

    for k, v in splitted.copy().items():
        if not v:
            splitted.pop(k)
        # needs to look like a word somehow
        elif not re.match(RE_ALPHA, v):
            log.debug(f"Not a word {k}: {v}")
            splitted.pop(k)
        elif domain and is_company(v, domain):
            splitted.pop(k)
            log.debug(f"Company detected {v}:{domain}")
        elif v.lower() in CIVILITY | ROLE_NAMES:
            splitted.pop(k)
            log.debug(f"Civility or Role detected {v}")

    return splitted if splitted.get("firstname") else None


if __name__ == "__main__":
    import csv
    import argparse

    parser = argparse.ArgumentParser(
        prog="Fullname Splitter",
        description="Split a fullname in a firstname and familyname",
    )
    parser.add_argument("-f", "--file")
    parser.add_argument("-n", "--name")
    parser.add_argument("-e", "--email")
    parser.add_argument("--debug", action="store_true")

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(
            format="%(asctime)-15s [%(levelname)s] %(funcName)s: %(message)s",
            level=logging.DEBUG,
        )

    if args.file:
        with open(args.file, newline="", encoding="utf-8-sig") as csvfile:
            reader = csv.DictReader(
                csvfile, delimiter=",", quotechar='"', quoting=csv.QUOTE_ALL
            )
            for row in reader:
                if row.get("Name"):
                    s = split_fullname(
                        row["Name"], row["Email"].split("@")[-1])
                    if s:
                        print(f"{row['Name']}: {s} from {row['Email']}")
                    else:
                        print(f"{row['Name']}: None")
    elif args.name and args.email:
        print(split_fullname(args.name, args.email.split("@")[1]))
    else:
        print(split_fullname(args.name))
