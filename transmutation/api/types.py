"""
Person Types
"""
__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__license__ = "AGPL"

from pydantic import TypeAdapter
from pydantic import EmailStr, HttpUrl
from typing_extensions import TypedDict


class Person(TypedDict, total=False):
    name: str
    email: EmailStr | set[EmailStr]
    homeLocation: str | set[str]
    alternateName: str | set[str]
    description: str | set[str]
    identifier: str | set[str]
    image: HttpUrl | set[HttpUrl]
    jobTitle: str | set[str]
    OptOut: bool
    sameAs: set[HttpUrl]
    url: HttpUrl | set[HttpUrl]
    workLocation: str | set[str]
    worksFor: str | set[str]


class PersonRequest(TypedDict):
    uid: str
    person: Person


class PersonResponse(TypedDict):
    status: bool
    person: Person | None


person_ta = TypeAdapter(Person)
person_request_ta = TypeAdapter(PersonRequest)
person_response_ta = TypeAdapter(PersonResponse)
