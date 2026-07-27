#!/bin/env python3
"""
Split fullname into givenName and familyName
"""

import logging
import re

from thedig.excavators.utils import normalize

log = logging.getLogger(__name__)

RE_WHITESPACE = re.compile(r"\s+")
RE_ALPHA = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)?", re.UNICODE)

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
    "communication",
    "events",
    "forum",
    "meeting",
    "secretariat",
    "secretario",
    "service",
    "service client",
    "support",
    "wordpress",
}

JOBTITLES_ABBRV = {
    "Dr": "Doctor",
    "Ing": "Engineer",
    "Eng": "Engineer",
    "Engr": "Engineer",
    "PhD": "Doctor",
    "Phd": "Doctor",
    "Pr": "Professor",
    "Prof": "Professor",
}

BUSINESS_SEPARATOR = {
    "from",
    "van",
    "von",
    "de",
    "d",  # only works if ' are removed
}

BLOCKED_NAMES = {name.casefold() for name in CIVILITY | ROLE_NAMES}


def order(givenname: str, familyname: str) -> dict:
    # FAMILY NAME First Name (reversed)
    if givenname.isupper() and not familyname.isupper():
        return {
            "familyName": givenname,
            "givenName": familyname,
        }
    return {
        "familyName": familyname,
        "givenName": givenname,
    }


def is_company(name: str, domain: str) -> bool:
    normalized_name = normalize(name)
    for sep in BUSINESS_SEPARATOR:
        normalized_sep = normalize(sep)
        if normalized_name.startswith(normalized_sep):
            normalized_name = normalized_name.removeprefix(normalized_sep)
            break

    domain_parts = domain.split(".")
    domain_root = normalize(domain_parts[-2] if len(domain_parts) > 1 else domain)
    normalized_domain = normalize(domain)
    normalized_registrable_domain = normalize(".".join(domain_parts[-2:]))

    return (
        normalized_name in (domain_root, normalized_domain, normalized_registrable_domain)
        or domain_root in normalized_name
    )


def _split_fullname(fullname: str) -> dict:
    fullname = RE_WHITESPACE.sub(" ", fullname).strip()
    if not fullname or not re.match(RE_ALPHA, fullname):
        return None

    if not any(char.isalpha() for char in fullname):
        return None

    # one token can still be a valid given name
    if " " not in fullname:
        if len(fullname) < 2:
            return None
        return {
            "givenName": fullname,
        }

    # e.g Familyname, First Name
    comma_format = [part.strip() for part in fullname.split(",")]
    if len(comma_format) == 2 and all(comma_format):
        return {
            "familyName": comma_format[0],
            "givenName": comma_format[1],
        }

    words = fullname.split(" ")

    # civility prefixes are not part of the name itself
    while words and words[0].removesuffix(".") in CIVILITY:
        words.pop(0)
    if not words:
        return None

    # suffixes such as PhD are not part of family name
    while len(words) > 2:
        trailing = words[-1].removesuffix(".")
        trailing_norm = trailing[:1].upper() + trailing[1:].lower() if trailing else trailing
        if trailing_norm in JOBTITLES_ABBRV:
            words.pop()
            continue
        break

    # eg. Dr. First Name FamilyName
    jobtitle = None
    if words and 1 < len(words[0]) < 5:
        # if last caracter end with a '.' we remove it for test purpose
        _jobtitle = words[0] if words[0][-1] != "." else words[0][:-1]
        normalized_jobtitle = _jobtitle[:1].upper() + _jobtitle[1:].lower() if _jobtitle else _jobtitle
        if normalized_jobtitle in JOBTITLES_ABBRV:
            jobtitle = normalized_jobtitle
            words.pop(0)

    if not words:
        return None

    if len(words) == 1:
        result = {
            "givenName": words[0],
        }
        if jobtitle:
            result["jobTitle"] = jobtitle
        return result

    # e.g givenName FamilyName
    if len(words) == 2:
        ordered = order(words[0], words[1])
        result = {
            "givenName": ordered["givenName"],
            "familyName": ordered["familyName"],
        }
        if jobtitle:
            result["jobTitle"] = jobtitle
        return result

    # eg. First name FAMILY NAME (or the opposite)
    givenname = words[0]
    familyname = words[-1]

    last_word_upper = words[-1].isupper()
    first_word_upper = words[0].isupper()

    if first_word_upper ^ last_word_upper:
        # trick to reverse FAMILY NAME Given Name
        isfamily = str.isupper if last_word_upper else lambda f: not str.isupper(f)
        split_index = next((index for index, word in enumerate(words) if isfamily(word)), 1)
        givenname = " ".join(words[:split_index])
        familyname = " ".join(words[split_index:])
        if first_word_upper:
            givenname, familyname = familyname, givenname
    else:
        # eg. First Name Van Family Name
        for i in range(1, len(words) - 1):
            if words[i].lower() in FAMILYNAME_SEPARATOR:
                givenname = " ".join(words[:i])
                familyname = " ".join(words[i:])
                break
        else:
            givenname = " ".join(words[:-1])
            familyname = words[-1]

    if givenname:
        return {
            "givenName": givenname,
            "familyName": familyname,
            "jobTitle": jobtitle,
        }


def split_fullname(fullname: str, domain: str = None) -> dict:
    if not fullname or not fullname.strip() or fullname.strip().casefold() in ROLE_NAMES:
        return None

    if domain and is_company(fullname, domain):
        return None

    splitted = _split_fullname(fullname)
    if not splitted:
        return None

    for k, v in splitted.copy().items():
        if not v:
            splitted.pop(k)
        # needs to look like a word somehow
        elif not re.match(RE_ALPHA, v):
            splitted.pop(k)
        elif domain and is_company(v, domain):
            splitted.pop(k)
        elif v.casefold() in BLOCKED_NAMES:
            splitted.pop(k)

    return splitted if splitted.get("givenName") else None


if __name__ == "__main__":
    import argparse
    import csv

    parser = argparse.ArgumentParser(
        prog="Fullname Splitter",
        description="Split a fullname in a givenname and familyname",
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
            reader = csv.DictReader(csvfile, delimiter=",", quotechar='"', quoting=csv.QUOTE_ALL)
            for row in reader:
                if row.get("Name"):
                    s = split_fullname(row["Name"], row["Email"].split("@")[-1])
                    if s:
                        print(f"{row['Name']}: {s} from {row['Email']}")
                    else:
                        print(f"{row['Name']}: None")
    elif args.name and args.email:
        print(split_fullname(args.name, args.email.split("@")[1]))
    else:
        print(split_fullname(args.name))
