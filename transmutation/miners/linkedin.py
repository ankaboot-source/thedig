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
import threading

# needed for memory sharing between threads
from multiprocessing.sharedctypes import Value

import requests

# log
from loguru import logger as log
from pydantic_schemaorg.Organization import Organization

# JSON Schema.org types
from pydantic_schemaorg.Person import Person
from pydantic_schemaorg.PostalAddress import PostalAddress

# Fuzzy string match for person name identification
from thefuzz import fuzz

# linkedin profile url with an ISO3166 country code regular expression
LINKEDIN_URL_RE = re.compile(
    r"https:\/\/(?P<countrycode>\w{2})\.?linkedin.com\/in\/(?P<nickname>w)*"
)


def country_from_url(linkedin_url: str) -> str:
    """Country name based on the xx.linkedin.com profile url
    where xx is the ISO3166 country code else return None

    Args:
        linkedin_url (str): linkedin profile URL

    Returns:
        str: country name
    """
    match = LINKEDIN_URL_RE.match(linkedin_url)

    if match:
        return ISO3166[match["countrycode"].upper()]


def parse_linkedin_title(title):
    """parse LinkedIn Title that has this form
        Full Name - Title - Company | LinkedIn
        and sometimes (Google only):
        Full Name - Title - Company... | LinkedIn
    Args:
        title (str): title from LinkedIn page
    """
    result = {}
    full_title = title.split("|")[0].split(" - ")
    result["name"] = full_title[0]

    if len(full_title) > 1:
        # when it's long, LinkedIn add a '...' suffix
        result["title"] = full_title[1].removesuffix("...").strip()
        if len(full_title) > 2:
            result["company"] = full_title[2].removesuffix("...").strip()
    return result


class LinkedInSearch:
    """
    Mine public data from LinkedIn with an email address
    using Google Search API and/or Microsoft Bing API
    """

    NUM_RESULTS = 1
    GOOGLE_FIELDS = "items(title,link,pagemap/cse_thumbnail,pagemap/metatags/profile:first_name,pagemap/metatags/profile:last_name,pagemap/metatags/og:image)"
    GOOGLE_SEARCH_URL_BASE = "https://www.googleapis.com/customsearch/v1/siterestrict?key={google_api_key}&cx={google_cx}&num={num_results}&fields={google_fields}"
    BING_SEARCH_URL_BASE = "https://api.bing.microsoft.com/v7.0/custom/search?customconfig={bing_custom_config}&count={num_results}"

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
        if "num_result" not in search_api_params:
            search_api_params["num_results"] = LinkedInSearch.NUM_RESULTS
        if "google_fields" not in search_api_params:
            search_api_params["google_fields"] = LinkedInSearch.GOOGLE_FIELDS

        if google:
            self.google = True
            self.google_search_url = self.GOOGLE_SEARCH_URL_BASE.format(
                **search_api_params
            )
            log.debug("Build Google search URL : " + self.google_search_url)

        if bing:
            self.bing = True
            self.bing_search_url = self.BING_SEARCH_URL_BASE.format(
                **search_api_params)
            log.debug("Build Bing search URL : " + self.bing_search_url)

        if not bing and not google:
            raise ValueError(
                "Must choose at least one search engine: bing or google")

        if bulk:
            self.persons = []
        self.person = None

    def _search_google(self, query: str):
        """Search a query on Google and return the first result

        Args:
            query (string): query string

        Returns:
            dict: first result
        """
        search_url_complete = self.google_search_url + "&q=" + query
        r = requests.get(search_url_complete)
        if not r.ok:
            r.raise_for_status()

        result_raw = r.json()

        # if a data is missing, that means probably that there is no results
        if "items" in result_raw and len(result_raw["items"]) > 0:
            return result_raw["items"][0]

        log.debug("No results found for query %s " % query)

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
        if (
            "webPages" in result_raw
            and "value" in result_raw["webPages"]
            and len(result_raw["webPages"]["value"]) > 0
        ):
            return result_raw["webPages"]["value"][0]

        log.debug("No results found for query %s " % query)

    def _add_country(self):
        """add country name to the Person JSON-LD based on the linkedin profile url"""
        if self.person.url:
            country = country_from_url(self.person.url)
            if country:
                self.person.address = country
                # TOFIX: do not work for unknown reason
                # self.person.address = PostalAddress(addressCountry=country)

    def _extract_bing_specific(self, result):
        # sometimes it's an useless thumbnail : 404 Error
        self.person.image = result["openGraphImage"]["contentUrl"]
        self.person.url = result["url"]

        # Bing also gives you sometimes location
        address = result["richFacts"][0]["items"][0]["text"].split(", ")
        # however sometimes the address isn't correctly identified by Bing
        if len(address) >= 3:
            self.person.address = PostalAddress(
                addressLocation=address[0],
                addressRegion=address[1],
                addressCountry=address[2],
            )

    def _extract_google_specific(self, result):
        self.person.givenName = result["pagemap"]["metatags"][0]["profile:first_name"]
        self.person.familyName = result["pagemap"]["metatags"][0]["profile:last_name"]

        # we do not use cse_thumbnail (Google's image)
        if len(result["pagemap"]["metatags"]) >= 1:
            self.person.image = result["pagemap"]["metatags"][0]["og:image"]
        self.person.url = result["link"]

    def extract(
        self, name: str, email: str = None, company: str = None, google: bool = True
    ) -> Person:
        """
        Search engine then update and return the personal data accordingly
        Google gives you the givenName/familyName but not the location
        Bings gives you the location sometimes but not the givenName/familyName
        Args:
            name (str): name
            email (str): email
            company (str): company's name
            google (bool): extract with Google, if false Bing

        Returns:
            person (str) : person JSON-LD filled with the infos mined
        """
        query_string = email or f"{name} {company}"
        result = (
            self._search_google(query_string)
            if google
            else self._search_bing(query_string)
        )

        if result:
            full_title = parse_linkedin_title(
                result["title" if google else "name"])

            # the full name from the result must be the same that the name itself
            # 96 seems a good ratio for difference between ascii and latin characters
            # should do fine tuning here trained on a huge international dataset
            if fuzz.token_set_ratio(full_title["name"], name.strip()) < 96:
                log.info(
                    f"The full name mined doesn't match the name given as a parameter: {full_title['name']}, {name}"
                )
                return None

            if "title" in full_title:
                self.person.jobTitle = full_title["title"]
            if "company" in full_title:
                self.person.worksFor = Organization(
                    name=full_title.get("company"))

            try:
                if google:
                    self._extract_google_specific(result)
                else:
                    self._extract_bing_specific(result)
            except KeyError:

                log.debug("No extractable data in this result : {result} ")
        else:
            log.debug("No result found")
            # self.person = None
            return None
        return self.person

    def search(self, name, email: str = None, company: str = None) -> dict:
        """
        search and return the public data for an email and/or company
        """
        self.person = Person(name=name)
        if email:
            log.debug("Searching by name %s and email %s" % (name, email))

            self.person.email = email
            if self.bing and self.google:
                # creating threads
                google = threading.Thread(
                    target=self.extract_google, args=(name, email)
                )
                bing = threading.Thread(
                    target=self.extract_bing, args=(name, email))

                # starting threads
                google.start()
                bing.start()

                # wait until all threads finish
                google.join()
                bing.join()  # usually add location
            elif self.google:
                self.extract(name, email)
            elif self.bing:
                self.extract(name, email, google=False)
        if company:
            self.person.worksFor = Organization(name=company)
            log.debug("Searching by name %s and company %s" % (name, company))
            self.extract(name, company=company)

        self._add_country()

        # answer only if we found something
        if self.person.url:
            return self.person

    def bulk(self, persons: list[Person]) -> list:
        """Bulk search

        Args:
            persons (list[Persons]): list of Persons

        Returns:
            list: list of Persons
        """
        for person in persons:
            p_enrich = self.search(person.name, person.email)
            if p_enrich:
                self.persons.append(p_enrich)

        return self.persons


if __name__ == "__main__":
    import os
    import sys

    log.level("DEBUG")

    search_api_params = {
        "google_api_key": os.getenv("GOOGLE_API_KEY"),
        "google_cx": os.getenv("GOOGLE_CX"),
        "bing_api_key": os.getenv("BING_API_KEY"),
        "bing_customconfig": os.getenv("BING_CUSTOMCONFIG"),
    }
    miner = LinkedInSearch(search_api_params)
    print(
        miner.search(
            name=" ".join(sys.argv[3:]), email=sys.argv[1], company=sys.argv[2]
        )
    )
