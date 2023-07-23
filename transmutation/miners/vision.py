#!/bin/python3
"""
Find social profiles from the image profile using Google Vision (Lens) API

Google Vision API Limits:
- 1800 requests/minute
- 8000 simultaneous requests
"""
__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__license__ = "AGPL"

import asyncio
import re
import urllib
from random import choice
from typing import Optional

from ..api.config import settings

from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from google.cloud import vision
from loguru import logger as log
from thefuzz import fuzz

from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from curl_cffi import requests

    CURL_REQUESTS = True
    IMPERSONATE_BROWSER = "chrome110"
except ImportError:
    log.warning("Using native requests instead of curl_cffi: no impersonate")
    import requests

    CURL_REQUESTS = False

from .utils import TOKEN_RATIO, match_name


# generic social profile matcher
# Hypothesis: TLD is max 10 characters
# Hypothesis: subdomain is www or a 2-char country code (linkedin) or nothing
# Hypothesis: some social profiles have specific URI for users profiles like
# - in: linkedin
# - person: crunchbase
# - @: tiktok (without trailing /)
# - add: snapchat
generic_socialprofile_regexp = re.compile(
    r"^https:\/\/((?P<subdomain>www|mobile|\w{2})\.)?(?P<socialnetwork>\w+)\.(?P<tld>\w{2,10})(\/(in|people|add))?\/@?(?P<identifier>\w+)$"
)

MAX_RETRY = 3
MAX_VISION_RESULTS = 20
MAX_PARRALEL_REQUESTS = 10


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


# a private life is a happy life
REQUESTS_PARAM = {
    "headers": ua_headers(),
    "timeout": 3,
    "impersonate": IMPERSONATE_BROWSER,
}


def find_pages_with_matching_images(
    image_url: str,
    max_results: Optional[int] = MAX_VISION_RESULTS,
) -> set[str]:
    """Find pages with matching images

    Args:
        image_url (str): image url

    Raises:
        Exception: Google Vision Error

    Returns:
        list[str]: list of urls
    """
    # search using google vision
    client = vision.ImageAnnotatorClient.from_service_account_file(
        settings.google_vision_credentials
    )

    response = client.annotate_image(
        {
            "image": {"source": {"image_uri": image_url}},
            "features": [
                {
                    "type_": vision.Feature.Type.WEB_DETECTION,
                    "max_results": max_results,
                }
            ],
        }
    )
    response = response.web_detection

    if hasattr(response, "error"):
        log.error(f"Image: {image_url}. Error: {response.error.message}")
        raise Exception(
            "{}\nFor more info on error messages, check: "
            "https://cloud.google.com/apis/design/errors".format(
                response.error.message)
        )

    matching = [
        r for r in response.pages_with_matching_images if "full_matching_images" in r
    ]
    log.debug(f"Matching images found for {image_url}: {matching}")

    return matching


# TODO: make it async
def get_socialprofile(
    url,
    sn,
    name=None,
    params=REQUESTS_PARAM,
    session=None,
    retry=0,
    max_retry=MAX_RETRY,
):
    if retry > max_retry:
        return None, sn

    name = name or self._person["name"]

    # linkedin is giving us an hard time
    # if retry>0:
    #    params["proxies"] = rotating_proxy()
    #    params['proxies'] = {'http' : "https://localhost:8080"}
    #    log.info(f"Retry with proxy. Proxy: {params['proxies']}, URL: {url}")

    if CURL_REQUESTS:
        # if not session:
        #    session = requests.AsyncSession()
        try:
            # r = await session.get(url, **params)
            r = requests.get(url, **params)
        except requests.RequestsError as e:
            log.error(
                f"Failed trying to reach Social Network. URL {url}, Error {e}")
            return None, sn
    else:
        try:
            r = requests.get(url, **params)
        except requests.exceptions.ProxyError as e:
            log.error(f"Proxy error. Params: {params}. Error {e}")
        except requests.exceptions.ConnectTimeout:
            log.error(f"Timeout error. Params: {params}")
            return None, sn
        except requests.RequestException as e:
            log.error(
                f"Failed trying to reach Social Network. URL: {url}, Error: {e}")
            return None, sn

    if not r.ok:
        log.debug(
            f"Social Network profile not found. URL: {url}, Error: {r.status_code}"
        )
        return False, sn

    soup = BeautifulSoup(r.text, "html.parser")

    # the title from the profile must contains the person's name itself
    title = soup.title

    # something went wrong with scrapping?
    if not title:
        log.error(
            f"No title, possible antibot tactic. URL: {url}, Headers: {params}, Content: {r.text}"
        )
        return False, sn

    og_title = soup.find("meta", attrs={"property": "og:title"})
    og_title = og_title["content"] if og_title else None

    # 96 seems a good ratio for difference between ascii and latin characters
    # should do fine tuning here trained on a huge international dataset
    ratio_title = fuzz.partial_token_sort_ratio(name, title.string)
    ratio_ogtitle = fuzz.partial_token_sort_ratio(name, og_title)
    title = title.string or og_title or ""
    if ratio_title < TOKEN_RATIO and ratio_ogtitle < TOKEN_RATIO and name not in title:
        log.debug(
            f"Name doesn't match with page title. Name: {name}, URL: {url}, Page title: {title.string} - {ratio_title}, OG Title {og_title} - {ratio_ogtitle}"
        )
        return False, sn

    return soup, sn


def extract_socialprofile(soup, url, name):
    og_image_tag = soup.find("meta", attrs={"property": "og:image"})
    if og_image_tag:
        og_image = og_image_tag.content
        og_image_url = urllib.parse.urljoin(url, og_image)
        log.debug(
            f"og:image found. Name: {name}, URL: {url}, Image URL: {og_image_url}"
        )

    twitter_image_tag = soup.find("meta", attrs={"property": "twitter:image"})
    if twitter_image_tag:
        twitter_image = twitter_image_tag.content
        twitter_image_url = urllib.parse.urljoin(url, twitter_image)
        log.debug(
            f"twitter:image found. Name: {name}, URL: {url}, Image URL: {twitter_image_url}"
        )

    og_description = soup.find("meta", attrs={"property": "og:description"})
    if og_description:
        og_description = og_description.content
        log.debug(
            f"og_description found. Name: {name}, URL: {url}, Image URL: {og_description}"
        )

    schemaorg_name = soup.find("meta", attrs={"property": "name"})
    if schemaorg_name:
        schemaorg_name = schemaorg_name.get("content")
        log.debug(
            f"Schema.org Name found. Name: {name}, URL: {url}, Schema.org Name: {schemaorg_name}"
        )

    location = soup.find("div", class_="profile-location")
    if location:
        location = location.contents[3].text
        log.debug(f"Location {location}")


class SocialNetworkMiner:
    """Mine for social network profiles related to a person"""

    # supported social networks and theirs urls
    socialnetworks_urls = {
        # 'crunchbase': "https://crunchbase.com/person/{identifier}",
        "facebook": "https://www.facebook.com/{identifier}",
        "github": "https://github.com/{identifier}",
        "instagram": "https://instagram.com/{identifier}",
        # linkedin don't let you scrap at all :(
        "linkedin": None,
        "pinterest": "https://pinterest.com/{identifier}",
        "snapchat": "https://snapchat.com/add/{identifier}",
        # false positive
        # 'telegram': "https://telegram.me/{identifier}",
        "tiktok": "https://tiktok.com/@{identifier}",
        # twitter is full javascript, needs a headless browser
        "twitter": "https://twitter.com/{identifier}",
        # "twitter#alt": "https://instalker.org/{identifier}",
        "twitter#alt": "https://nitter.net/{identifier}",
        "youtube": "https://youtube.com/{identifier}",
    }

    socialnetwork_extractors = {
        "github": {
            "name": "span.p-name.vcard-fullname.d-block.overflow-hidden",
            "image": "/html/body/div[5]/main/div[2]/div/div[1]/div/div[2]/div[1]/div[1]/a/img",
        }
    }

    def __init__(self, person: dict, socialnetworks: Optional[list] = None):
        # person init
        self._original_person = person
        self._person = person.copy()
        if not "identifier" in self._person:
            self._person["identifier"] = set()
        elif type(self._person["identifier"]) == str:
            self._person["identifier"] = {self._person["identifier"]}
        elif type(self._person["identifier"]) == list:
            self._person["identifier"] = set(self._person["identifier"])
        if not "sameAs" in self._person:
            self._person["sameAs"] = set()

        # one could choose to opt out some social networks
        if socialnetworks:
            self.socialnetworks_urls = {
                sn: url
                for sn, url in self.socialnetworks_urls.items()
                if sn.split("#alt")[0] in socialnetworks
            }
            self.socialnetworks = socialnetworks
        else:
            self.socialnetworks = self.socialnetworks_urls.keys()

        # now we populate profiles
        self.profiles = {}
        self._populate_profiles()

    @property
    def person(self):
        return {k: v for k, v in self._person.items() if k not in self._original_person}

    async def image(self, match_check: bool = True) -> dict:
        """Look for social profiles using profile picture

        Returns:
            dict: dict of profiles urls by social network
        """
        pages = find_pages_with_matching_images(self._person["image"])
        for page in pages:
            url_matched = re.match(generic_socialprofile_regexp, page.url)
            # valid_sp = is_valid_socialprofile(url_matched.group(0), self._person['name'])
            if (
                not url_matched
                or url_matched["socialnetwork"] not in self.socialnetworks_urls
            ):
                log.debug(
                    f"Invalid/existing social network profile: {page.url}")
                continue
            page_title = BeautifulSoup(
                page.page_title, "html.parser").contents[0].text
            if match_check and not match_name(self._person["name"], page_title):
                log.debug(
                    f"Social Profile: {page_title} doesn't match name {self._person['name']}"
                )
                continue

            m = url_matched.groupdict()

            # we only add new social networks URLs
            if m["socialnetwork"] not in self.profiles:
                log.debug(f"Social Network profile found by image: {m}")
                self.add_profile(url_matched.group(0), **m)

        return self.profiles

    def add_profile(self, url, socialnetwork, identifier, tld, subdomain=None):
        self.profiles[socialnetwork] = {
            "url": url,
            "identifier": identifier,
            "tld": tld,
            "subdomain": subdomain,
        }
        self._person["identifier"].add(identifier)
        self._person["sameAs"].add(url)

    async def _identifier(self, identifier) -> dict:
        social = {}
        for sn, url in self.socialnetworks_urls.items():
            # pass existing social networks profiles
            if sn in self.profiles:
                continue

            # if not eligible to scrapping
            if not url:
                continue

            # priority for the alternative mirror if it exists
            if f"{sn}#alt" in self.socialnetworks_urls:
                continue

            # check if there is this person profile for this social network
            url = url.format(identifier=identifier)

            social[sn] = url

        socials = []
        # TODO: make it async instead of threads
        with ThreadPoolExecutor(max_workers=MAX_PARRALEL_REQUESTS) as executor:
            for sn, url in social.items():
                socials.append(executor.submit(get_socialprofile, url, sn))

            for future in as_completed(socials):
                try:
                    sp, sn = future.result()
                except Exception as exc:
                    log.warning(f"{url} generated an exception: {exc}")
                    continue

                if not sp:
                    continue

                # replace alternative mirror URL with the original one
                log.debug(f"{sn}")
                if sn.endswith("#alt"):
                    sn = sn.removesuffix("#alt")
                    url = self.socialnetworks_urls[sn].format(
                        identifier=identifier)
                m = re.match(generic_socialprofile_regexp, url).groupdict()

                log.debug(f"Social Profile found by identifier: {m}")
                self.add_profile(url, **m)
                # extract_socialprofile(sp, url, self._person['name'])

    async def identifier(self) -> dict:
        """Look for social profiles using identifiers

        Returns:
            dict: dict of profiles urls by social network
        """
        # if we don't have any identifier we'll use temporary ones
        identifiers = self._person["identifier"] or self._generate_identifiers(
        )

        for idr in identifiers:
            await self._identifier(idr)

        return self.profiles

    def _populate_profiles(self, email: bool = True):
        urls = []
        if "url" in self._person:
            urls.append(self._person["url"])
        if "sameAs" in self._person:
            urls.extend(self._person["sameAs"])

        for url in urls:
            url_matched = re.match(generic_socialprofile_regexp, url)
            if url_matched:
                m = url_matched.groupdict()
                if (
                    m["socialnetwork"] not in self.profiles
                    and m["socialnetwork"] in self.socialnetworks
                ):
                    self.add_profile(url, **m)

    def _generate_identifiers(self):
        id_email = self._generate_identifier_from_email()
        id_name = self._generate_identifier_from_name()
        return {id_email, id_name} if id_email else {id_name}

    def _generate_identifier_from_name(self):
        return (
            self._person["name"]
            .encode("ASCII", "ignore")
            .strip()
            .lower()
            .decode()
            .replace(" ", "")
        )

    def _generate_identifier_from_email(self):
        id_email = "".join(
            filter(str.isalnum, self._person["email"].split(
                "@")[0].split("+")[0])
        )
        # useful only if really different from name
        # otherwise, it gives too much false positive
        if fuzz.partial_token_sort_ratio(id_email, self._person["name"]) > 81:
            return None
        return id_email


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="Vision Miner", description="Find someone using his profile picture"
    )
    parser.add_argument("-n", "--name")
    parser.add_argument("-i", "--identifier")
    parser.add_argument("-g", "--image")
    parser.add_argument("-e", "--email")
    parser.add_argument("-u", "--url")
    parser.add_argument("-s", "--socialnetwork")
    args = parser.parse_args()

    p = dict(
        name=args.name,
        identifier=args.identifier,
        image=args.image,
        email=args.email,
        sameAs=[],
    )

    s = SocialNetworkMiner(p, socialnetworks=args.socialnetwork)
    print(s.identifier())
