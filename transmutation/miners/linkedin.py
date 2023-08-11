#!/bin/python3
"""
Mine public data from LinkedIn with an email address using Google Search API
Return format is JSON-LD simplified
"""
__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__license__ = "AGPL"

# make it work as a command line tool
try:
    from .ISO3166 import ISO3166
except ImportError:
    from ISO3166 import ISO3166

import re

# needed for memory sharing between threads

from pydantic import HttpUrl

from curl_cffi import requests
from urllib.parse import quote

# log
from loguru import logger as log

# Fuzzy string match for person name identification
from thefuzz import fuzz

# linkedin profile url with an ISO3166 country code regular expression
RE_LINKEDIN_URL = re.compile(
    r"^https?:\/\/((?P<countrycode>\w{2})|(:?www))\.linkedin\.com\/(?:public\-profile\/in|in|people)\/(?P<identifier>\w+(?:(?:\.|\-)\w+)?(?:(?:\-)\w+)?)/?$"
)


def country_from_url(linkedin_url: str) -> str:
    """Country name based on the xx.linkedin.com profile url
    where xx is the ISO3166 country code else return None

    Args:
        linkedin_url (str): linkedin profile URL

    Returns:
        str: country name
    """
    match = RE_LINKEDIN_URL.match(linkedin_url)

    if match and match["countrycode"]:
        return ISO3166[match["countrycode"].upper()]


def parse_linkedin_title(title, name: str = None):
    """parse LinkedIn Title that has this form
        Full Name - Title - Company | LinkedIn
        and sometimes (Google only):
        Full Name - Title - Company... | LinkedIn
    Args:
        title (str): title from LinkedIn page
    """
    full_title = title.split("|")[0].split(" - ")

    if name and full_title[0] != name:
        return None

    result = {"name": full_title[0]}

    # when it's long, LinkedIn add a '...' suffix
    if len(full_title) > 2:
        secondpart = full_title[2].removesuffix("...").strip()
        firstpart = full_title[1].removesuffix("...").strip()
        # if last word got LinkedIn in it, it's not his company
        # except if this person does work for LinkedIn
        # this last case won't work
        if "LinkedIn" not in secondpart:
            result["jobTitle"] = firstpart
            result["worksFor"] = secondpart
        else:
            result["worksFor"] = firstpart
    elif len(full_title) > 1:
        result["jobTitle"] = full_title[1].removesuffix("...").strip()
    else:
        return None

    return result


class LinkedInSearch:
    """
    Mine public data from LinkedIn with an email address
    using Google Search API and/or Microsoft Bing API
    """

    NUM_RESULTS = 10

    # either q or exactTerms (don't work for emails)
    QUERY_TYPE = "q"
    GOOGLE_FIELDS = "items(title,link,pagemap/cse_thumbnail,pagemap/metatags/profile:first_name,pagemap/metatags/profile:last_name,pagemap/metatags/og:image)"
    GOOGLE_SEARCH_URL_BASE = "https://www.googleapis.com/customsearch/v1/siterestrict?key={google_api_key}&cx={google_cx}&num={num_results}&fields={google_fields}&{query_type}"
    BING_SEARCH_URL_BASE = (
        "https://api.bing.microsoft.com/v7.0/custom/search?customconfig={bing_custom_config}&count={num_results}"
    )

    def __init__(
        self,
        search_api_params: dict,
        google: bool = True,
        bing: bool = False,
        bulk: bool = False,
    ):
        """LinkedInSearch constructor

        Args:
            search_api_params (dict): parameters for the search API including credentials
            google (bool, optional): search with Google. Defaults to True.
            bing (bool, optional): search with Bing. Defaults to False.

        Raises:
            ValueError: at least bing or google search engine must be True
        """

        self.google = False
        self.bing = False

        # there is default values for this params, the others are mandatory
        if "query_type" not in search_api_params:
            search_api_params["query_type"] = LinkedInSearch.QUERY_TYPE
        if "num_result" not in search_api_params:
            search_api_params["num_results"] = LinkedInSearch.NUM_RESULTS
        if "google_fields" not in search_api_params:
            search_api_params["google_fields"] = LinkedInSearch.GOOGLE_FIELDS

        if google:
            self.google = True
            self.google_search_url = self.GOOGLE_SEARCH_URL_BASE.format(**search_api_params)
            log.debug("Build Google search URL : " + self.google_search_url)

        if bing:
            self.bing = True
            self.bing_search_url = self.BING_SEARCH_URL_BASE.format(**search_api_params)
            log.debug("Build Bing search URL : " + self.bing_search_url)

        if not bing and not google:
            raise ValueError("Must choose at least one search engine: bing or google")

        if bulk:
            self.persons = []
        self.person = None

    async def _search_google(self, query: str):
        """Search a query on Google and return the first result

        Args:
            query (string): query string

        Returns:
            dict: first result
        """
        search_url_complete = f"{self.google_search_url}={query}"
        async with requests.AsyncSession() as s:
            try:
                r = await s.get(search_url_complete)
                # import requests as req
                # r = req.get(search_url_complete)
            except requests.RequestsError as e:
                # except req.RequestException as e:
                log.error(f"{search_url_complete}: {e}")
                return None
            if not r.ok:
                log.error(f"{r.status_code} : {r.reason}")

            result_raw = r.json()

            # if a data is missing, that means probably that there is no results
            if "items" in result_raw and len(result_raw["items"]) > 0:
                return result_raw["items"]

        log.debug(f"No results found for query: {query}")

    def _search_bing(self, query: str):
        """Search a query on Bing and return the first result

        Args:
            query (str): query string

        Returns:
            dict: first result
        """
        search_url_complete = self.bing_search_url + "&q=" + query
        r = requests.get(
            search_url_complete,
            headers={"Ocp-Apim-Subscription-Key": self.bing_api_key},
        )
        if not r.ok:
            r.raise_for_status()

        result_raw = r.json()

        log.info("bing result %s" % result_raw)
        # if a data is missing, that means probably that there is no results
        if "webPages" in result_raw and "value" in result_raw["webPages"] and len(result_raw["webPages"]["value"]) > 0:
            return result_raw["webPages"]["value"][0]

        log.debug("No results found for query %s " % query)

    def _add_country(self):
        """add country name to the dict JSON-LD based on the linkedin profile url"""
        if "url" in self.person:
            country = country_from_url(self.person["url"])
            if country:
                self.person["workLocation"] = country

    def _extract_bing_specific(self, result):
        # sometimes it's an useless thumbnail : 404 Error
        self.person["image"] = result["openGraphImage"]["contentUrl"]
        self.person["url"] = result["url"]

        # Bing also gives you sometimes location
        address = result["richFacts"][0]["items"][0]["text"].split(", ")
        # however sometimes the address isn't correctly identified by Bing
        if len(address) >= 3:
            self.person["workLocation"] = ", ".join(address)

    def _extract_google_specific(self, result):
        self.person["givenName"] = result["pagemap"]["metatags"][0]["profile:first_name"]
        self.person["familyName"] = result["pagemap"]["metatags"][0]["profile:last_name"]

        # we do not use cse_thumbnail (Google's image)
        if len(result["pagemap"]["metatags"]) >= 1:
            self.person["image"] = result["pagemap"]["metatags"][0]["og:image"]
        self.person["url"] = result["link"]

    def _result_to_dict(self, result) -> dict:
        # build initial dict
        person_d = {
            "givenName": result["pagemap"]["metatags"][0]["profile:first_name"],
            "familyName": result["pagemap"]["metatags"][0]["profile:last_name"],
            "url": result["link"],
            "identifier": re.match(RE_LINKEDIN_URL, result["link"])["identifier"],
        }

        person_d["name"] = f"{person_d['givenName']} {person_d['familyName']}"
        # enrich with parsed from linkedin title
        full_title = parse_linkedin_title(result["title"], person_d["name"])
        # the parsing worked only if name parsed is the same
        if full_title:
            person_d.update(full_title)

        # add the image, yet
        # we do not use cse_thumbnail (Google's image)
        if len(result["pagemap"]["metatags"]) >= 1:
            person_d["image"] = result["pagemap"]["metatags"][0]["og:image"]

        return person_d

    async def extract(
        self,
        name: str,
        email: str = None,
        company: str = None,
        linkedin_url: HttpUrl = None,
        google: bool = True,
    ) -> dict:
        """
        Search engine then update and return the personal data accordingly
        Google gives you the givenName/familyName but not the location
        Bings gives you the location sometimes but not the givenName/familyName
        Args:
            name (str): name
            email (str): email
            company (str): company's name
            url (HttpUrl): URL's of LinkedIn
            google (bool): extract with Google, if false Bing

        Returns:
            person (str) : person JSON-LD filled with the infos mined
        """
        query_string = quote(email or linkedin_url or (f"{name} {company}" if company else name))
        if not query_string:
            log.error("No query string could be built")
            raise ValueError

        results = await self._search_google(query_string) if google else self._search_bing(query_string)

        if not results:
            log.debug("LinkedIn: No result found")
            # self.person = None
            return None

        # if there are homonymous, KO
        # if the name found isn't the one given, KO
        # else that's good!
        persons_d = {}
        for r in results:
            # must be a valid profile link
            if not re.match(RE_LINKEDIN_URL, r["link"]):
                log.debug(f"This url isn't a valid Linkedin Profile {r['link']}")
                continue

            person_d = self._result_to_dict(r)

            # the full name from the result must be the same that the name itself
            # 96 seems a good ratio for difference between ascii and latin characters
            # should do fine tuning here trained on a huge international dataset
            if fuzz.token_set_ratio(person_d["name"], name) < 96:
                log.debug(f"The name mined doesn't match the name given: {person_d['name']}, {name}")
                continue

            # check homonymous
            if name in persons_d:
                return None

            persons_d[name] = person_d
            break

        # not found, bye
        if name not in persons_d:
            return None

        persons_d[name].update(self.person)
        self.person = persons_d[name]

        return self.person

    async def search(self, name, email: str = None, company: str = None, linkedin_url: HttpUrl = None) -> dict:
        """
        search and return the public data for an email and/or company
        """
        self.person = {"name": name}
        await self.extract(name, email, company, linkedin_url)

        # answer only if we found something
        if "url" in self.person:
            self._add_country()
            return self.person


if __name__ == "__main__":
    import os
    import sys

    log.level("DEBUG")

    search_api_params = {
        "google_api_key": os.getenv("GOOGLE_API_KEY"),
        "google_cx": os.getenv("GOOGLE_CX"),
        "bing_api_key": os.getenv("BING_API_KEY"),
        "query_type": "exactTerms",
        "bing_customconfig": os.getenv("BING_CUSTOMCONFIG"),
    }
    miner = LinkedInSearch(search_api_params)
    print(miner.search(name=" ".join(sys.argv[3:]), email=sys.argv[1], company=sys.argv[2]))
