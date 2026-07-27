#!/bin/env python
"""
Find social profiles from the image profile using Google Vision (Lens) API

Google Vision API Limits:
- 1800 requests/minute
- 8000 simultaneous requests
"""

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from json import loads
from typing import ClassVar, Optional

from bs4 import BeautifulSoup
from curl_cffi import requests
from google.cloud import vision
from loguru import logger as log
from pydantic import FilePath, HttpUrl
from rapidfuzz import fuzz

from ..api.person import Person, dict_to_person
from .linkedin import parse_linkedin_title
from .utils import TOKEN_RATIO, match_name, ua_headers

# generic social profile matcher
# Hypothesis: TLD is max 10 characters
# Hypothesis: subdomain is www or a 2-char country code (linkedin) or nothing
# Hypothesis: some social profiles have specific URI for users profiles like
# - in: linkedin
# - person: crunchbase
# - @: tiktok (without trailing /)
# - add: snapchat
RE_SOCIALPROFILE = re.compile(
    r"^https?:\/\/((?P<subdomain>www|mobile|\w{2})\.)?(?P<socialnetwork>\w+)\.(?P<tld>\w{2,10})(?:\/(?:public\-profile\/in|in|people|add))?\/@?(?P<identifier>\w+(?:(?:\.|\-)\w+)?(?:(?:\-)\w+)?)/?$"
)

MAX_RETRY = 3
MAX_VISION_RESULTS = 20
MAX_PARRALEL_REQUESTS = 10
OUTPUT_TAG = "#OptOut"

DESCRIPTION_DEFAULTS = {
    "has discovered on Pinterest, the world's biggest collection of ideas.",
    "Facebook gives people the power to share and makes the world more open and connected.",
    "is on Snapchat!",
    "See Instagram photos and videos from",
    "I use about.me to show people what matters most to me.",
    "Follow their code on GitHub",
    "See the complete profile on LinkedIn and discover",
    "GitHub is where",
    " on TikTok | ",
}

SOCIALNETWORKS = {
    # 'crunchbase': "https://crunchbase.com/person/{identifier}",
    "about": "https://about.me/{identifier}",
    "facebook": "https://www.facebook.com/{identifier}",
    "github": "https://github.com/{identifier}",
    "instagram": "https://instagram.com/{identifier}",
    # linkedin don't let you scrap at all :(
    # "linkedin": None,
    "pinterest": "https://pinterest.com/{identifier}",
    "snapchat": "https://snapchat.com/add/{identifier}",
    # no telegram, false positive
    "tiktok": "https://tiktok.com/@{identifier}",
    # twitter is full javascript, needs a headless browser
    "twitter": "https://twitter.com/{identifier}",
    # that's why we're using nitter as a proxy
    "twitter#alt": "{nitter_instance_server}/{identifier}",
    "youtube": "https://youtube.com/{identifier}",
    "dribble": "https://dribble.com/{identifier}",
}

# a private life is a happy life
REQUESTS_PARAM = {
    "headers": ua_headers(),
    "timeout": 10,
}


async def find_pages_with_matching_images(
    image_url: str,
    google_credentials: FilePath,
    max_results: Optional[int] = MAX_VISION_RESULTS,
) -> list[str]:
    """Find pages with matching images

    Args:
        image_url (str): image url

    Raises:
        Exception: Google Vision Error

    Returns:
        list[str]: list of urls
    """
    # search using google vision
    client = vision.ImageAnnotatorClient.from_service_account_file(google_credentials)
    matching = []
    try:
        response = await asyncio.to_thread(
            client.annotate_image,
            vision.AnnotateImageRequest(
                {
                    "image": {"source": {"image_uri": image_url}},
                    "features": [
                        {
                            "type_": vision.Feature.Type.WEB_DETECTION,
                            "max_results": max_results,
                        }
                    ],
                }
            ),
        )
        response = response.web_detection
    except Exception as e:
        log.error(f"Google Vision reverse image search failed: {e}")
        return []

    if hasattr(response, "error"):
        log.error(f"Image: {image_url}. Error: {response.error.message}")
        google_cloud_error = "{response}\nFor more info on error messages, check: \
        https://cloud.google.com/apis/design/errors".format(response=response.error.message)
        raise Exception(google_cloud_error)

    matching = [r for r in response.pages_with_matching_images if "full_matching_images" in r]
    log.debug(f"Matching images found for {image_url}: {matching}")

    return matching


def is_socialprofile(url):
    m = re.match(RE_SOCIALPROFILE, str(url))
    if not m or m["socialnetwork"] not in SOCIALNETWORKS:
        return None
    sp = m.groupdict()
    _url = SocialNetworkMiner.socialnetworks_urls[sp["socialnetwork"]]
    url = _url.format(identifier=sp["identifier"]) if _url else m[0]

    return sp | {
        "url": url,
    }


def get_socialprofile(url, sn, name, params=REQUESTS_PARAM, session=None, retry=0, max_retry=MAX_RETRY):
    if retry > max_retry:
        return None, sn

    # linkedin is giving us an hard time
    # if retry>0:
    #    params["proxies"] = rotating_proxy()
    #    params['proxies'] = {'http' : "https://localhost:8080"}
    #    log.info(f"Retry with proxy. Proxy: {params['proxies']}, URL: {url}")

    # if not session:
    #    session = requests.AsyncSession()
    try:
        # r = await session.get(url, **params)
        r = requests.get(url, **params)
    except requests.RequestsError as e:
        log.error(f"Failed trying to reach Social Network. URL {url}, Error {e}")
        return None, sn

    if not r.ok:
        log.debug(f"Social Network profile not found. URL: {url}, Error: {r.status_code}")
        return False, sn

    soup = BeautifulSoup(r.text, "html.parser")

    # the title from the profile must contains the person's name itself
    title = soup.title

    # something went wrong with scrapping?
    if not title:
        log.error(f"No title, possible antibot tactic. URL: {url}, Headers: {params}, Content: {r.text}")
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
            f"Name doesn't match with page title. \
                Name: {name}, URL: {url}, \
                    Page title: {title} - {ratio_title}, \
                        OG Title {og_title} - {ratio_ogtitle}"
        )
        return False, sn

    return soup, sn


def right_to_optout(text):
    return OUTPUT_TAG in text


def extract_socialprofile(soup, url, name):
    person = {}

    og_image = soup.find("meta", attrs={"property": "og:image"})
    # snapchat gives by default a fake avatar called square.jpeg
    # pinterest gives by default this URL: https://s.pinimg.com/images/default_open_graph_1200.png
    if og_image:
        person["image"] = og_image["content"]
        log.debug(f"og:image found. Name: {name}, URL: {url}, Image URL: {og_image['content']}")
    else:  # twitter or pinterest
        twitter_image = soup.find("meta", attrs={"property": "twitter:image"})
        twitter_image_src = soup.find("meta", attrs={"property": "twitter:image:src"})
        twitter_image = twitter_image or twitter_image_src
        if twitter_image and not twitter_image["content"].endswith("square.jpeg"):
            person["image"] = twitter_image["content"]
            log.debug(f"twitter:image found. Name: {name}, URL: {url} , Image URL: {twitter_image['content']}")

    if any(person["image"].endswith(f) for f in ("square.jpeg", "default_open_graph_1200.png")):
        del person["image"]

    # OpenGraph protocol
    og_description = soup.find("meta", attrs={"property": "og:description"})
    if og_description and all(desc not in og_description["content"] for desc in DESCRIPTION_DEFAULTS):
        person["description"] = og_description["content"]
        log.debug(f"og_description found. Name: {name}, URL: {url} , Description: {og_description}")

        if right_to_optout(person["description"]):
            log.warning(f"{name} asked for #OptOut")
            log.debug(f"#OptOut asked on {url}")
            person["OptOut"] = True

    # JSON-LD in script tag (eg. instagram)
    jsonld = soup.find("script", attrs={"type": "application/ld+json", "id": "Person"}) or soup.find(
        "script", attrs={"type": "application/ld+json"}
    )
    if jsonld:
        jsonld = loads(jsonld.text)
        try:
            jsonld = jsonld.get("author") or jsonld
            if jsonld.get("name") and jsonld["name"].casefold() != name.casefold():
                person["alternateName"] = jsonld["name"]
            if jsonld.get("nationality"):
                person["nationality"] = jsonld["nationality"]
            if jsonld.get("knowsLanguage"):
                person["knowsLanguage"] = jsonld["knowsLanguage"]
            if type(jsonld.get("image")) is str:
                person["image"] = jsonld["image"]
            elif jsonld.get("image", {}).get("contentUrl"):
                person["image"] = jsonld["image"]["contentUrl"]
            log.debug(f"JSON-LD found: {jsonld}")
        except KeyError:
            log.warning(f"Unknown JSON-LD format: {jsonld}")

    # Social links
    links = soup.find_all(
        "a",
        class_=("social-link", "Link--primary"),
        attrs={"rel": re.compile("^(me nofollow noopener noreferrer|nofollow me)$")},
    )
    if links:
        person["sameAs"] = set()
        for link in links:
            sp = is_socialprofile(link["href"])
            person["sameAs"].add(sp["url"] if sp else link["href"])

    schemaorg_name = soup.find("meta", attrs={"property": "name"})
    if schemaorg_name:
        schemaorg_name = schemaorg_name.get("content")
        person["alternateName"] = schemaorg_name
        log.debug(f"Schema.org Name found. Name: {name}, URL: {url} : {schemaorg_name}")

    # location from nitter or github or about.me
    location = (
        soup.find("div", class_="profile-location")
        or soup.find("span", class_="p-label")
        or soup.find("span", class_="location")
    )
    if location:
        person["homeLocation"] = location.text.strip()
        log.debug(f"Location found. Name: {name}, URL: {url} : {location}")

    return person


class SocialNetworkMiner:
    """Mine for social network profiles related to a person"""

    # supported social networks and theirs urls
    socialnetworks_urls = SOCIALNETWORKS
    handlers: ClassVar = {
        "github": {
            "name": "span.p-name.vcard-fullname.d-block.overflow-hidden",
            "image": "/html/body/div[5]/main/div[2]/div/div[1]/div/div[2]/div[1]/div[1]/a/img",
            "url_eligible": False,
        },
        "linkedin": {
            "url_eligible": True,
        },
    }

    def __init__(
        self,
        person: dict,
        nitter_instance_server: HttpUrl,
        google_credentials: FilePath = None,
        socialnetworks: list | None = None,
        proxy: dict | None = None,
    ):
        # specific for this miner, name is mandatory
        # TBD: find a better way to require for name
        if google_credentials:
            self.google_credentials = google_credentials
        self.socialnetworks_urls["twitter#alt"] = self.socialnetworks_urls["twitter#alt"].replace(
            "{nitter_instance_server}", nitter_instance_server
        )

        if "name" not in person:
            name_mandatory = "Name is mandatory"
            raise ValueError(name_mandatory)

        self.proxy = proxy

        # person init
        self._original_person = person
        self._person: Person = dict_to_person(person.copy(), setdefault=True)

        # ok let's pretend is always void
        self._person["description"] = set()

        if "image" in self._person:
            self._person["image"] = (
                {
                    self._person["image"],
                }
                if type(self._person["image"]) is not set
                else self._person["image"]
            )
        else:
            self._person["image"] = set()

        # one could choose to opt out some social networks
        if socialnetworks:
            self.socialnetworks_urls = {
                sn: url for sn, url in self.socialnetworks_urls.items() if sn.split("#alt")[0] in socialnetworks
            }
            self.socialnetworks = socialnetworks
        else:
            self.socialnetworks = self.socialnetworks_urls.keys()

        # now we populate profiles
        self.profiles = {}
        self._populate_profiles()

    @property
    def person(self):
        return {k: v for k, v in self._person.items() if v != self._original_person.get(k) and v}

    async def image(self, match_check: bool = True) -> dict:
        """Look for social profiles using profile picture

        Returns:
            dict: dict of profiles urls by social network
        """

        pages = []
        for img in self._person["image"]:
            pages.extend(await find_pages_with_matching_images(str(img), self.google_credentials))

        for page in pages:
            m = is_socialprofile(page.url)
            # valid_sp = is_valid_socialprofile(url_matched.group(0), self._person['name'])
            if not m or m["socialnetwork"] not in self.socialnetworks_urls:
                log.debug(f"Invalid/existing social network profile: {page.url}")
                continue
            page_title = BeautifulSoup(page.page_title, "html.parser").contents[0].text
            if not match_name(self._person["name"], parse_linkedin_title(page_title).get("name", page_title)):
                log.debug(f"Social Profile: {page_title} doesn't match name {self._person['name']}")
                continue

            log.debug(f"Social Network profile found by image: {m}")

            self.add_profile(**m)

        return self.profiles

    def add_profile(
        self,
        url,
        socialnetwork,
        identifier,
        tld,
        _url=None,
        alternateName=None,
        sameAs=None,
        image=None,
        homeLocation=None,
        description=None,
        subdomain=None,
        knowsLanguage=None,
        nationality=None,
    ):
        # no duplicates
        # we only add new social networks URLs
        if socialnetwork in self.profiles and any(sp["url"] == url for sp in self.profiles[socialnetwork]):
            return None

        if socialnetwork not in self.profiles:
            self.profiles[socialnetwork] = []

        self.profiles[socialnetwork].append(
            {
                "url": url,
                "identifier": identifier,
                "tld": tld,
                "subdomain": subdomain,
            }
        )
        self._person["identifier"].add(identifier)
        self._person["sameAs"].add(url)
        if socialnetwork in self.handlers and self.handlers[socialnetwork]["url_eligible"]:
            self._person["url"] = url
            if url in self._person["sameAs"]:
                self._person["sameAs"].remove(url)
        if image:
            self._person["image"].add(image)
        if homeLocation:
            self._person["homeLocation"].add(homeLocation)
        if description:
            self._person["description"].add(description)
        if alternateName:
            self._person["alternateName"] = alternateName
        if sameAs:
            self._person["sameAs"].update(sameAs)
        if nationality:
            self._person["nationality"].add(nationality)
        if knowsLanguage:
            self._person["knowsLanguage"].add(knowsLanguage)

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

        getters = {}
        # TODO: make it async instead of threads
        with ThreadPoolExecutor(max_workers=MAX_PARRALEL_REQUESTS) as executor:
            for sn, url in social.items():
                getters[
                    executor.submit(
                        get_socialprofile,
                        url,
                        sn,
                        self._person["name"],
                        params={"proxies": {"https": self.proxy, "http": self.proxy}} | REQUESTS_PARAM,
                    )
                ] = (sn, url)

            for future in as_completed(getters):
                try:
                    sp, sn = future.result()
                except Exception as exc:
                    log.error(f"{getters[future][0]},{getters[future][1]} : {exc}")
                    continue

                if not sp:
                    continue

                # replace alternative mirror URL with the original one
                if sn.endswith("#alt"):
                    sn = sn.removesuffix("#alt")
                url = self.socialnetworks_urls[sn].format(identifier=identifier)
                m = is_socialprofile(url)

                log.debug(f"Social Profile found by identifier: {m}")
                extr = extract_socialprofile(sp, m["url"], self._person["name"])
                if extr:
                    log.debug(f"More data extracted from Social Profile: {extr}")
                    m.update(extr)

                self.add_profile(**m)

    def sameAs(self) -> dict:
        for url in tuple(self._person["sameAs"]):
            sp = is_socialprofile(url)
            if sp:
                self.add_profile(**sp)
        return self.profiles

    async def identifier(self) -> dict:
        """Look for social profiles using identifiers

        Returns:
            dict: dict of profiles urls by social network
        """
        # if we don't have any identifier we'll use temporary ones
        identifiers = self._person["identifier"] or self._generate_identifiers()

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
            m = is_socialprofile(url)
            if m and m["socialnetwork"] not in self.profiles and m["socialnetwork"] in self.socialnetworks:
                self.add_profile(**m)

    def _generate_identifiers(self) -> set[str]:
        idr: set = (
            self._generate_identifier_from_email()
            # | self._generate_identifier_from_name()
            # disabled temporary because give too much false positive
        )
        return idr

    def _generate_identifier_from_name(self) -> set[str]:
        idr = self._person["name"].encode("ASCII", "ignore").strip().lower().decode().replace(" ", "")
        return {idr, idr.replace(".", "")}

    def _generate_identifier_from_email(self) -> set[str]:
        local_part, domain = self._person["email"].split("@", 1)
        local_id = "".join(filter(str.isalnum, local_part.split("+")[0]))

        candidates = {
            local_id,
            local_id.replace(".", ""),
        }

        domain_root = "".join(filter(str.isalnum, domain.split(".")[0]))
        if local_id and domain_root and local_id in domain_root and domain_root != local_id:
            candidates.add(domain_root)

        return {
            identifier
            for identifier in candidates
            if len(identifier) >= 3 and fuzz.partial_token_sort_ratio(identifier, self._person["name"]) <= 81
        }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(prog="Vision Miner", description="Find someone using his profile picture")
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
