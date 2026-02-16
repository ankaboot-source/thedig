#!/bin/env python
"""
Mine public data from LinkedIn with an email address using Google Search API
Return format is JSON-LD simplified
"""

import json
import re
import time
import unicodedata
from abc import ABC, abstractmethod
from html import unescape
from typing import ClassVar, Literal

import jwt

# from curl_cffi import requests
import requests
from loguru import logger as log
from pydantic import BaseModel, Field, HttpUrl, model_validator

# needed for memory sharing between threads
from ..api.person import dict_to_person
from .ISO3166 import ISO3166
from .utils import match_name

HttpMethod = Literal["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "TRACE", "PATCH"]

# linkedin profile url with an ISO3166 country code regular expression
RE_LINKEDIN_URL = re.compile(
    r"^https?:\/\/((?P<countrycode>\w{2})|(:?www))\.linkedin\.com\/(?:public\-profile\/in|in|people)\/(?P<identifier>([%\w-]+))/?",
    re.U,
)
RE_LINKEDIN_NAME_DESCRIPTION = re.compile(r"<strong>([^<]+)</strong>.*<strong>([^<]+)</strong>", re.U)

RE_LINKEDIN_INFOS_DESCRIPTION = re.compile(
    (
        r"^(?P<description>.*?)(?: · Experience: (?P<worksFor>.+?)(?: · Education: (.+?))?"
        r" · Location: (?P<workLocation>.*?) · (?: · \d+\+ connections on LinkedIn)?)"
    ),
    re.U,
)

LINKEDIN_DESCRIPTION = {
    "en": {
        "begin": "View ",
        "end": "’s profile on LinkedIn, a professional community of 1 billion members",
        "re": RE_LINKEDIN_INFOS_DESCRIPTION,
    },
    "fr": {
        "begin": "Consultez le profil de ",
        "end": " sur LinkedIn, une communauté professionnelle d’un milliard de membres",
        "re": re.compile(
            (
                r"^(?P<description>.*?)(?: · Expérience : (?P<worksFor>.+?)(?: · Formation : (.+?))?"
                r" · Lieu : (?P<workLocation>.*?) · (?: · \d+\+ relations sur LinkedIn)?)"
            ),
            re.U,
        ),
    },
    "de": {
        "begin": "Sehen Sie sich das Profil von ",
        "end": " auf LinkedIn, einer professionellen Community mit mehr als 1 Milliarde Mitgliedern, an",
        "re": re.compile(
            (
                r"^(?P<description>.*?)(?: · Berufserfahrung: (?P<worksFor>.+?)(?: · Ausbildung: (.+?))?"
                r" · Standort: (?P<workLocation>.*?) · (?: · \d+\+ Kontakte auf LinkedIn)?)"
            ),
            re.U,
        ),
    },
    "ch": {
        "begin": "Sehen Sie sich das Profil von ",
        "end": " auf LinkedIn, einer professionellen Community mit mehr als 1 Milliarde Mitgliedern, an",
        "re": re.compile(
            (
                r"^(?P<description>.*?)(?: · Berufserfahrung: (?P<worksFor>.+?)(?: · Ausbildung: (.+?))?"
                r" · Standort: (?P<workLocation>.*?) · (?: · \d+\+ Kontakte auf LinkedIn)?)"
            ),
            re.U,
        ),
    },
}

LINKEDIN_TRAILING_DESCRIPTION = (" ...", ".")

REQUESTS_TIMEOUT = 3
PROXYCURL_PICTURE_ENDPOINT = "https://nubela.co/proxycurl/api/linkedin/person/profile-picture"


def linkedin_profile_picture(url: HttpUrl, api_key: str, proxy=None) -> HttpUrl:
    match = RE_LINKEDIN_URL.match(str(url))
    if not match:
        log.debug(f"Not a valid LinkedIn profile URL: {url}")
        return
    linkedin_url = f"https://www.linkedin.com/in/{match.group('identifier')}"
    try:
        r = requests.get(
            PROXYCURL_PICTURE_ENDPOINT,
            params={"linkedin_person_profile_url": linkedin_url},
            timeout=REQUESTS_TIMEOUT,
            headers={"Authorization": f"Bearer {api_key}"},
            proxies={"https": proxy} if proxy else None,
        )
        log.debug(r.text)
    except requests.RequestException as e:
        log.debug(e)
        return

    if not r.ok:
        return

    return r.json().get("tmp_profile_pic_url")


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


def parse_linkedin_title(title: str, name: str | None = None) -> dict:
    """parse LinkedIn Title that has this form
        Full Name - Title - Company | LinkedIn
        and sometimes (Google only):
        Full Name - Title - Company... | LinkedIn
        or even:
        Full Name - Company | LinkedIn
        Full Name - Title | LinkedIn
        it should always ends with '| LinkedIn'
    Args:
        title (str): title from LinkedIn page
        name (str): name of the person
    """
    result = {}

    if not title.endswith("LinkedIn") and not title.endswith("..."):
        log.debug("This is not a LinkedIn profile title: wrong ending")
        return result

    title_ = title.split(" | ")
    # actually, LinkedIn separator is not - but –
    full_title = title_[0].replace(" – ", " - ").split(" - ")
    if len(full_title) < 2:
        log.debug("This is not a LinkedIn profile title: wrong separator or too short")
        return result

    if name and full_title[0].casefold() != name.casefold():
        log.debug("This may not its LinkedIn profile")
        return result

    result = {"name": full_title[0]}

    # when it's long, LinkedIn add a '...' suffix
    if len(full_title) == 3:
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

    return result


def parse_linkedin_description(description, country="en") -> dict:
    person = {}

    if not description:
        return person

    html_matches = re.match(RE_LINKEDIN_NAME_DESCRIPTION, description)
    if html_matches:
        given_name, family_name = html_matches.groups()
        if given_name and family_name:
            person["givenName"] = given_name
            person["familyName"] = family_name
            person["alternateName"] = f"{given_name} {family_name}"

    # fallback to english
    if country not in LINKEDIN_DESCRIPTION:
        country = "en"

    for trailing in LINKEDIN_TRAILING_DESCRIPTION:
        if description.endswith(trailing):
            description = description.removesuffix(trailing)
            break

    if description.endswith(LINKEDIN_DESCRIPTION[country]["end"]):
        # clean description suffix
        description = description.removesuffix(LINKEDIN_DESCRIPTION[country]["end"])

        person["description"] = description
        # add alternateName found in description
        if "alternateName" not in person:
            description = description.replace("<strong>", "").replace("</strong>", "")
            person["alternateName"] = description[
                description.find(LINKEDIN_DESCRIPTION[country]["begin"]) + len(LINKEDIN_DESCRIPTION[country]["begin"]) :
            ]
        person["description"] = description.replace(LINKEDIN_DESCRIPTION[country]["begin"], "")
        person["description"] = person["description"].removesuffix(person["alternateName"])

        # add other infos
        matched_infos = re.match(LINKEDIN_DESCRIPTION[country]["re"], description)
        if matched_infos:
            infos = matched_infos.groupdict()
            person.update({key: value.strip() for key, value in infos.items() if value})

    return person


def _load_face_recognition_module():
    try:
        import face_recognition
    except ImportError as e:
        msg = "face-recognition is required for face matching"
        raise RuntimeError(msg) from e
    return face_recognition


def _remote_image_array(url: str):
    face_recognition = _load_face_recognition_module()
    try:
        image_f = requests.get(
            url,
            stream=True,
            timeout=REQUESTS_TIMEOUT,
        )
    except requests.RequestException as e:
        raise ValueError(f"Failed to get image from {url}") from e
    if not image_f.ok:
        failed_request = f"Failed to get image from {url}: {image_f.status_code}"
        raise ValueError(failed_request)
    image_f.raw.decode_content = True
    return face_recognition.load_image_file(image_f.raw)


class LinkedInProfile(BaseModel):
    url: HttpUrl
    title: str
    name: str

    # not every search engine got them correctly
    description: str | None = None
    image: HttpUrl | None = None
    givenName: str | None = None
    familyName: str | None = None
    workLocation: str | None = None
    alternateName: str | None = None

    # usually computed from the URL
    jobTitle: str | None = None
    worksFor: str | None = None
    country: str | None = None
    identifier: str | None = None

    # private attribute for regexp purposes
    match: dict | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def parse(self):
        self.match_url()
        self.parse_title()
        self.parse_description()
        self.parse_url()
        self.clean_image()
        return self

    def match_url(self):
        self.match = RE_LINKEDIN_URL.match(str(self.url))
        if not self.match:
            invalid_linkedin_url = "Invalid LinkedIn profile URL"
            raise ValueError(invalid_linkedin_url)

    def parse_url(self):
        if not self.country and self.match["countrycode"]:
            self.country = ISO3166[self.match["countrycode"].upper()]
            # we upsert self.workLocation if None
            # or given by the search engine if it's not the same as the country
            # Country names like USA, UAE need to be checked as an acronym too
            country_acronym = "".join(filter(str.isupper, self.country))
            if not self.workLocation or (
                self.country not in self.workLocation and country_acronym not in self.workLocation
            ):
                self.workLocation = self.country

        # we don't need generated linkedin identifier
        # generated linkedin identifier looks like firstname-lastname-a1b2c3d4
        # 3 words separated by a "-", last word has at least 2 digits and 8 char
        splitted_id = self.match["identifier"].split("-")
        if len(splitted_id) >= 3 and len(splitted_id[-1]) >= 8 and sum(c.isdigit() for c in splitted_id[-1]) >= 2:
            return
        self.identifier = self.match["identifier"]

    def parse_description(self):
        if not self.description:
            return
        infos = parse_linkedin_description(description=self.description, country=self.match["countrycode"])
        if infos:
            if infos.get("alternateName") == self.name:
                del infos["alternateName"]
            self.__dict__.update(infos)

    def parse_title(self):
        r = parse_linkedin_title(
            title=self.title,
            name=self.name,
        )
        if not r:
            raise ValueError("Not a valid LinkedIn Profile title")
        if not match_name(self.name, r["name"], fuzzy=False, condensed=False):
            raise ValueError("This LinkedIn profile name doesn't match")
        if "worksFor" in r:
            self.worksFor = r["worksFor"]
        if "jobTitle" in r:
            self.jobTitle = r["jobTitle"]

    def clean_image(self):
        if not self.image:
            return

        if str(self.image).startswith("https://static.licdn.com/aero-v1/sc/h/"):
            self.image = None


class Search(ABC):
    RICH_FIELDS = ["worksFor", "jobTitle"]
    RESULTS_COUNT = 10

    def __init__(
        self,
        endpoint: HttpUrl,
        method: HttpMethod,
        headers: dict = {},
        query_params: dict = {},
        body: dict | None = None,
        proxy: str | None = None,
    ):
        self.endpoint = endpoint
        self.headers = headers
        self.query_params = query_params
        self.body = body
        self.method = method
        self.proxy = proxy
        self.session = requests.Session()
        self.authenticate()

    @abstractmethod
    def search_query(self, query: str = None) -> dict:
        pass

    @abstractmethod
    def extract(self):
        pass

    @abstractmethod
    def authenticate(self):
        pass

    def raw_search(self, query: str):
        self.authenticate()
        search_q = self.search_query(query)
        if self.method == "GET":
            self.query_params.update(search_q)
        elif self.method == "POST":
            self.body.update(search_q)
        else:
            raise ValueError(f"Not a supported HTTP method: {self.method}")

        prepped_req = requests.Request(
            method=self.method, url=self.endpoint, params=self.query_params, headers=self.headers, json=self.body
        ).prepare()

        r = self.session.send(prepped_req)
        r.raise_for_status()

        self.raw_results = r.json()

    def search(self, query: str, name: str):
        self.raw_search(query)
        self.extract()

        # returns the first or the most complete
        self.profiles = []
        for r in self.results:
            normalized_r = {k: unicodedata.normalize("NFKD", v) for k, v in r.items()}
            try:
                self.profiles.append(LinkedInProfile(**normalized_r, **{"name": name}))
            except ValueError as e:
                log.debug(f"Not a valid {name} {normalized_r} LinkedInprofile: {e}")

        return self.profiles

    def to_persons(self, worksFor: str = None):
        self.persons = []
        for profile in self.profiles:
            person = dict_to_person(
                dict(
                    name=profile.name,
                    url=profile.url,
                    sameAs={profile.url},
                    description=profile.description,
                    alternateName={profile.alternateName},
                    workLocation={profile.workLocation},
                    givenName=profile.givenName,
                    familyName=profile.familyName,
                    identifier={profile.identifier},
                    image=profile.image,
                    jobTitle=profile.jobTitle,
                    worksFor=profile.worksFor,
                ),
                unsetvoid=True,
            )

            if worksFor and profile.worksFor and match_name(worksFor, profile.worksFor, acronym=True):
                self.persons.insert(0, person)
            else:
                self.persons.append(person)
        return self.persons

    def face_match(self, image: HttpUrl, deepface_fallback=True):  # noqa: FBT002
        try:
            face_recognition = _load_face_recognition_module()
        except RuntimeError as e:
            log.warning(e)
            return []

        matches = []

        original_face_img = _remote_image_array(str(image))
        original_face = face_recognition.face_encodings(original_face_img)[0]

        for person in self.persons:
            if "image" not in person:
                continue
            profile_face = face_recognition.face_encodings(_remote_image_array(str(person["image"])))
            if True in face_recognition.compare_faces([original_face], profile_face)[0]:
                matches.append(person)

        if matches or not deepface_fallback:
            return matches

        try:
            from deepface import DeepFace
        except Exception as e:
            log.warning(f"DeepFace fallback is unavailable: {e}")
            return matches

        # ok let's try deepface now
        for person in self.persons:
            if "image" not in person:
                continue
            if DeepFace.verify(
                img1_path=original_face_img,
                img2_path=_remote_image_array(str(person["image"])),
            )["verified"]:
                matches.append(person)
                break

        return matches


class GoogleVertexAI(Search):
    TOKEN_URI = "https://oauth2.googleapis.com/token"
    TOKEN_LIFEDURATION = 3600
    SCOPE = "https://www.googleapis.com/auth/cloud-platform"
    ENDPOINT = "https://discoveryengine.googleapis.com/v1alpha/projects/{project_id}/locations/{region}/collections/default_collection/engines/{datastore_id}/servingConfigs/default_search:search"

    def __init__(
        self,
        service_account_info: dict,
        project_id: str,
        datastore_id: str,
        region: str = "global",
    ):
        self.service_account_info = service_account_info
        self.access_token = None
        self.token_expiry = 0  # Timestamp when the token will expire

        super().__init__(
            endpoint=self.ENDPOINT.format(project_id=project_id, region=region, datastore_id=datastore_id),
            method="POST",
            body={"pageSize": self.RESULTS_COUNT, "contentSearchSpec": {"snippetSpec": {"returnSnippet": False}}},
            headers={
                "Content-Type": "application/json",
            },
        )

    def authenticate(self):
        # Check if the token is still valid and not about to expire
        if self.access_token and time.time() < self.token_expiry - 60 * 5:
            return

        # Generate a JWT for the service account
        now = int(time.time())
        payload = {
            "iss": self.service_account_info["client_email"],
            "sub": self.service_account_info["client_email"],
            "aud": self.TOKEN_URI,
            "iat": now,
            "exp": now + 3600,  # Token valid for 1 hour
            "scope": self.SCOPE,
        }

        # Sign the JWT with the service account's private key
        signed_jwt = jwt.encode(payload, self.service_account_info["private_key"], algorithm="RS256")

        # Request an access token
        token_response = requests.post(
            self.TOKEN_URI,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": signed_jwt,
            },
            timeout=REQUESTS_TIMEOUT,
        )

        token_response.raise_for_status()
        token_json = token_response.json()
        self.access_token = token_json["access_token"]
        self.token_expiry = now + token_json.get("expires_in", self.TOKEN_LIFEDURATION)

        # Update headers with the new access token
        self.headers["Authorization"] = f"Bearer {self.access_token}"

    def raw_search(self, name: str):
        self.authenticate()
        return super().raw_search(name)

    def search_query(self, query: str) -> dict:
        return {**self.body, "query": query}

    def extract(self):
        self.results = [
            {
                "title": p.get("og:title"),
                "url": p.get("og:url"),
                "description": unescape(p.get("og:description")).replace("<br>", "\n"),
                "givenName": p.get("profile:first_name"),
                "familyName": p.get("profile:last_name"),
                "image": p.get("og:image"),
                "country": ISO3166.get(p.get("locale").split("_")[-1]),
            }
            for p in map(
                lambda r: r.get("document", {})
                .get("derivedStructData", {})
                .get("pagemap", {})
                .get("metatags", [{}])[0],
                self.raw_results.get("results", []),
            )
        ]


class Brave(Search):
    ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
    HEADERS = {
        "X-Subscription-Token": None,
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }
    QUERY_PARAMS = {
        "resultfilter": "web",
        # "goggles_id": "https://raw.githubusercontent.com/carlopezzuto/google-linkedin/main/googgleLI",
        "count": Search.RESULTS_COUNT,
        "country": "us",
        "search_lang": "en",
    }

    def __init__(
        self,
        token: str,
    ):
        self.token = token
        super().__init__(endpoint=self.ENDPOINT, method="GET", headers=self.HEADERS, query_params=self.QUERY_PARAMS)

    def authenticate(self):
        self.headers["X-Subscription-Token"] = self.token

    def search_query(self, query: str):
        return {"q": f"site:linkedin.com/in {query}"}

    def extract(self):
        self.results = [
            {"title": p["title"], "url": p["url"], "description": p["description"]}
            for p in self.raw_results.get("web", {}).get("results", {})
            if p
        ]


class Bing(Search):
    ENDPOINT = "https://api.bing.microsoft.com/v7.0/custom/search"
    QUERY_PARAMS = {
        "count": Search.RESULTS_COUNT,
    }

    def __init__(
        self,
        token: str,
        customconfig: str,
    ):
        self.token = token
        super().__init__(
            endpoint=self.ENDPOINT,
            method="GET",
            query_params=self.QUERY_PARAMS,
        )
        self.query_params["customconfig"] = customconfig

    def authenticate(self):
        self.headers["Ocp-Apim-Subscription-Key"] = self.token

    def search_query(self, query: str) -> dict:
        return {"q": query}

    def extract(self):
        self.results = []
        if "webPages" not in self.raw_results or not self.raw_results["webPages"].get("value"):
            return

        for result in self.raw_results["webPages"]["value"]:
            self.results.append(
                {
                    "title": result["name"],
                    "description": result["snippet"],
                    "url": result["url"],
                    "image": result.get("openGraphImage", {}).get("contentUrl"),
                }
            )

            # Bing also gives you sometimes location
            for item in result.get("richFacts", ()):
                if item["hint"]["text"] != "ADDRESS:LOCATIONGENERAL":
                    continue
                address = item["items"][0]["text"].split(", ")
                # however sometimes the address isn't correctly identified by Bing
                if len(address) >= 3:
                    self.results[-1]["workLocation"] = ", ".join(address)


class Singleton(type):
    _instances: ClassVar = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class SearchChain(metaclass=Singleton):
    def __init__(self, settings):
        self.engines = []
        if settings.google_credentials and settings.google_vertexai_datastore and settings.google_vertexai_projectid:
            self.engines.append(
                GoogleVertexAI(
                    service_account_info=json.loads(open(settings.google_credentials).read()),
                    project_id=settings.google_vertexai_projectid,
                    datastore_id=settings.google_vertexai_datastore,
                )
            )
        if settings.bing_customconfig and settings.bing_api_key:
            self.engines.append(Bing(customconfig=settings.bing_customconfig, token=settings.bing_api_key))
        if settings.brave_api_key:
            self.engines.append(Brave(token=settings.brave_api_key))

    def search(self, name: str, query: str):
        if not self.engines:
            log.warning("No LinkedIn search engine configured; skipping LinkedIn lookup")
            return None

        success = False
        for engine in self.engines:
            try:
                log.debug(f"Trying {engine.__class__.__name__}...")
                engine.search(query=query, name=name)
                if not engine.results:
                    success = True
                    continue
                log.debug(f"Search successful with {engine.__class__.__name__}")
                return engine
            except Exception as e:
                log.error(f"{engine.__class__.__name__} failed with error: {e}")

        if not success:
            log.warning("All configured search engines have failed; skipping LinkedIn lookup")

        return None
