"""Tests for the Archeologist excavation ordering."""

from inspect import signature

import pytest

import thedig.api  # noqa: F401  # imported first to avoid a circular import with archaeology
from thedig.excavators.archaeology import Archeologist


def fake_excavator(field: str, calls: list):
    """Build an excavator registration dict that records the excavated field."""

    async def excavator():
        calls.append(field)
        return {}

    return {
        "field": field,
        "update": [],
        "insert": [],
        "enrich": True,
        "endpoint": excavator,
        "parameters": signature(excavator).parameters,
        "catchall": True,
        "person_param": False,
    }


@pytest.mark.asyncio
async def test_person_excavates_email_before_name():
    ar = Archeologist()
    calls: list = []

    ar.excavators["email"].append(fake_excavator("email", calls))
    ar.excavators["name"].append(fake_excavator("name", calls))
    ar.fields = {"name", "email"}

    modified, enriched, person = await ar.person({"email": "a@b.com", "name": "A B"})

    assert calls == ["email", "name"]
    assert modified is False
    assert enriched is False
    assert person == {}


@pytest.mark.asyncio
async def test_person_ignores_fields_not_excavated():
    ar = Archeologist()
    calls: list = []

    ar.excavators["email"].append(fake_excavator("email", calls))
    ar.excavators["name"].append(fake_excavator("name", calls))
    ar.fields = {"name", "email"}

    modified, enriched, person = await ar.person({"email": "a@b.com", "name": "A B", "telephone": "+33123456789"})

    assert calls == ["email", "name"]
    assert modified is False
    assert enriched is False
    assert person == {}
