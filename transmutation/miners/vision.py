#!/bin/python3
"""
Find social profiles from the image profile using Google Vision (Lens) API

Google Vision API Limits:
- 1800 requests/minute
- 8000 simultaneous requests
"""

import re
import urllib
from random import choice
from typing import Optional

from ..api.config import settings

import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from google.cloud import vision
from loguru import logger as log
from thefuzz import fuzz

# JSON Schema.org types
from pydantic_schemaorg.Person import Person

# generic social profile matcher
# Hypothesis: TLD is max 10 characters
# Hypothesis: subdomain is www or a 2-char country code (linkedin) or nothing
# Hypothesis: some social profiles have specific URI for users profiles like
# - in: linkedin
# - person: crunchbase
# - @: tiktok (without trailing /)
# - add: snapchat
generic_socialprofile_regexp = r"^https:\/\/(?P<subdomain>www|\w{2})?\.?(?P<socialnetwork>\w+)\.(?P<TLD>\w{2,10})(\/(in|people|add))?\/@?(?P<identifier>\w+)"
generic_socialprofile_regexp = re.compile(generic_socialprofile_regexp)

MAX_RETRY = 3
MAX_VISION_RESULTS = 20
TOKEN_RATIO = 96


def match_name(name: str, text: str) -> bool:
    if not name:
        return True
    return fuzz.partial_token_sort_ratio(name, text) >= TOKEN_RATIO


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

    log.debug(response.pages_with_matching_images)
    return response.pages_with_matching_images


def random_ua_headers():
    """
    generate a random user-agent
    basic techniques against bot blockers
    """
    ua = UserAgent(num_newest_uas=1)
    return {"user-agent": ua.random}


def is_valid_socialprofile(url, name, retry=0, max_retry=MAX_RETRY):
    if retry > max_retry:
        return None

    # a private life is a happy life
    params = {
        "headers": random_ua_headers(),
        "timeout": 1,
    }

    # linkedin is giving us an hard time
    # if retry>0:
    #    params["proxies"] = rotating_proxy()
    #    params['proxies'] = {'http' : "https://localhost:8080"}
    #    log.info(f"Retry with proxy. Proxy: {params['proxies']}, URL: {url}")

    try:
        r = requests.get(url, **params)
    except requests.exceptions.ProxyError as e:
        log.warning(f"Proxy error, let's retry. Params: {params}. Error {e}")
        return is_valid_socialprofile(url, name, retry=retry + 1)
        # log.error(f"Too much proxy retry. Proxy: {param['proxies']['http']}")
    except requests.exceptions.ConnectTimeout:
        log.warning(f"Timeout error, let's retry. Params: {params}")
        if params.get("proxies"):
            return is_valid_socialprofile(url, name, retry=retry + 1)
        return None
    except requests.RequestException as e:
        log.error(
            f"Failed trying to reach Social Network. URL: {url}, Error: {e}")
        return None

    if not r.ok:
        log.debug(
            f"Social Network profile not found. URL: {url}, Error: {r.status_code}"
        )
        return False

    # soup = BeautifulSoup(r.text, "html.parser", parse_only=parse_only_title)
    soup = BeautifulSoup(r.text, "html.parser")

    # the title from the profile must contains the person's name itself
    title = soup.title

    # something went wrong with scrapping?
    if not title:
        log.warning(
            f"No title, possible antibot tactic. URL: {url}, Headers: {params}, Content: {r.text}"
        )
        return is_valid_socialprofile(url, name, retry=retry + 1)

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
        return False

    return soup


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
        # 'linkedin': "https://linkedin.com/in/{identifier}",
        "pinterest": "https://pinterest.com/{identifier}",
        "snapchat": "https://snapchat.com/add/{identifier}",
        "telegram": "https://telegram.me/{identifier}",
        "tiktok": "https://tiktok.com/@{identifier}",
        # twitter is full javascript, needs a headless browser
        "twitter": "https://twitter.com/{identifier}",
        # "twitter#alt": "https://instalker.org/{identifier}",
        "twitter#alt": "https://nitter.it/{identifier}",
        "youtube": "https://youtube.com/{identifier}",
    }

    socialnetwork_extractors = {
        "github": {
            "name": "span.p-name.vcard-fullname.d-block.overflow-hidden",
            "image": "/html/body/div[5]/main/div[2]/div/div[1]/div/div[2]/div[1]/div[1]/a/img",
        }
    }

    def __init__(self, person: Person, socialnetworks: Optional[list] = None):

        # person init
        self.person = person
        if not self.person.identifier:
            self.person.identifier = set()
        elif type(self.person.identifier) == str:
            self.person.identifer = {self.person.identifier}
        elif type(self.person.identifier) == list:
            self.person.identifier = set(self.person.identifier)

        self.profiles = {}

        # generate identifiers from provided social profiles in sameAs
        if not self.person.sameAs:
            self.person.sameAs = set()
        else:
            self._generate_identifiers()

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

    def image(self, match_name: bool = True) -> dict:
        """Look for social profiles using profile picture

        Returns:
            dict: dict of profiles urls by social network
        """
        pages = find_pages_with_matching_images(self.person.image)
        for page in pages:
            url_matched = re.match(generic_socialprofile_regexp, page.url)
            # valid_sp = is_valid_socialprofile(url_matched.group(0), self.person.name)
            if url_matched and url_matched["socialnetwork"] in self.socialnetworks_urls:
                log.debug(
                    f"Social Network Profile found: {url_matched.group(0)}")
                m = url_matched.groupdict()
                # we only add new social networks URLs
                if m["socialnetwork"] not in self.profiles:
                    self.profiles[m.pop("socialnetwork")] = m | {
                        "url": url_matched.group(0)
                    }
                    self.person.identifier.add(m["identifier"])
                    self.person.sameAs.add(url_matched.group(0))

        log.debug(f"Profiles found by image: {self.profiles}")
        return self.profiles

    def identifier(self, generate_id: bool = True) -> dict:
        """Look for social profiles using identifier

        Returns:
            dict: dict of profiles urls by social network
        """
        if generate_id:
            self._generate_identifiers()

        for idr in self.person.identifier:
            for sn, url in self.socialnetworks_urls.items():
                # pass existing social networks profiles
                if sn in self.profiles:
                    continue

                url = url.format(identifier=idr)
                # priority for the alternative mirror if it exists
                if f"{sn}#alt" in self.socialnetworks_urls:
                    continue
                # check if there is this person profile for this social network
                soup = is_valid_socialprofile(url, self.person.name)
                if soup:
                    # replace alternative mirror URL with the original one
                    if sn.endswith("#alt"):
                        sn = sn.removesuffix("#alt")
                        url = self.socialnetworks_urls[sn].format(
                            identifier=idr)
                    m = re.match(generic_socialprofile_regexp, url).groupdict()
                    self.profiles[sn] = m | {"url": url}
                    self.person.identifier.add(m["identifier"])
                    self.person.sameAs.add(url)
                    # extract_socialprofile(soup, url, self.person.name)

        return self.profiles

    def _generate_identifiers(self, email: bool = True):
        # add typical identifier from email
        if email and self.person.email:
            id_email = self._generate_identifier_from_email()
            if id_email:
                self.person.identifier.add(id_email)

        # generate *potential* identifier from name
        # useless alone: too many false positives
        # if self.person.name:
        #    self.person.identifier.add(
        #        self._generate_identifier_from_name()
        #    )

        # extract identifier from social profiles
        urls = []
        if self.person.url:
            urls.append(self.person.url)
        if self.person.sameAs:
            urls.extend(self.person.sameAs)

        for url in urls:
            url_matched = re.match(generic_socialprofile_regexp, url)
            if url_matched and url_matched["identifier"]:
                m = url_matched.groupdict()
                if m["socialnetwork"] not in self.profiles:
                    self.profiles[m.pop("socialnetwork")] = m | {"url": url}
                self.person.identifier.add(url_matched["identifier"])

    def _generate_identifier_from_name(self):
        return (
            self.person.name.encode("ASCII", "ignore")
            .strip()
            .lower()
            .decode()
            .replace(" ", "")
        )

    def _generate_identifier_from_email(self):
        id_email = "".join(
            filter(str.isalnum, self.person.email.split("@")[0].split("+")[0])
        )
        # useful only if really different from name
        # otherwise, it gives too much false positive
        if fuzz.partial_token_sort_ratio(id_email, self.person.name) > 81:
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

    p = Person(
        name=args.name,
        identifier=args.identifier,
        image=args.image,
        email=args.email,
        sameAs=[],
    )

    s = SocialNetworkMiner(p, socialnetworks=args.socialnetwork)
    print(s.identifier())
