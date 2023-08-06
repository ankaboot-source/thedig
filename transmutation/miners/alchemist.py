# Copyright 2022 Badreddine LEJMI.
# SPDX-License-Identifier: 	AGPL-3.0-or-later

"""Base Alchemist"""
__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__copyright__ = "Ankaboot"
__license__ = "AGPL"

from loguru import logger as log
from inspect import signature
from fastapi import APIRouter
from ..api.person import Person, person_ta


def person_set_field(person: Person, field: str, value: str | set) -> Person:
    """Set while transform field into set when the value or the dest is not set
    WARNING: only works with set/str

    Args:
        person (Person): person's dict
        field (str): field name to set
        value (str | set): value

    Returns:
        Person: person's dict
    """
    dest_set = Person.__annotations__[
        field] == set or Person.__annotations__[field] == set | str
    if dest_set:
        if field not in person:
            person[field] = set()
        elif not type(person[field]) is set:
            person[field] = {
                person[field],
            }
        if type(value) is set:
            person[field] |= value
        else:
            person[field] = {
                value,
            }
    else:
        person[field] = value

    return person


class Alchemist:
    """Enrich iteratively persons using miners"""

    _ordered_elements: list = [
        "url",
        "sameAs",
        "email",
        "image",
        "description",
        "name",
    ]

    default_path: str = "/{operation}/{func_name}/{{{element}}}"

    def __init__(self, router: APIRouter = None):
        self.elements: set = set()
        self.miners: dict = {k: [] for k in self._ordered_elements}
        self.router = router

        # we don't mine again with the same miner, the same element/value
        # so we keep an history of what element/value was used for what miner
        self._mined: dict = {}

    async def person(self, person: dict) -> tuple[bool, dict]:
        """Transmute one person

        Args:
            person (dict): person to transmute

        Returns:
            bool, dict: succeed or not, enriched person
        """
        elements = list(person.keys() & self.elements)

        log.debug(f"mining {elements} for {person}")

        modified = False
        # sync because we want to control the order of mining elements
        for el in elements:
            log.debug(f"mining {el}: {person.get(el)}")

            if el not in self.miners:
                log.debug(f"no miner for {el}")
                continue

            if el not in self._mined:
                self._mined[el] = {}

            upgraded = set()
            for miner in self.miners[el]:
                upgraded.update(await self.mine_element(el, miner, person))

            modified = True if upgraded else modified

            # eligibility to mine
            to_mine = upgraded & self.elements
            if upgraded and to_mine:
                elements.extend(to_mine)
                log.debug(f"new elements to mine: {to_mine}")

        return modified, person if modified else None

    async def mine_element(self, el, miner, person):
        upgraded = set()

        # do not mine twice the same elemnt/value with the same miner
        if miner["endpoint"] not in self._mined[el]:
            self._mined[el] = {miner["endpoint"]: []}
        elif person[el] in self._mined[el][miner["endpoint"]]:
            return upgraded
        self._mined[el][miner["endpoint"]].append(person[el])

        log.debug(f"mining {el} with miner {miner}")

        if miner['person_param']:
            p_mined: Person = await miner["endpoint"](person)
        else:
            person_eligible = {k: v for k, v in person.items(
            ) if k in miner['parameters'] & person.keys()}
            p_mined: Person = await miner["endpoint"](**person_eligible)

        if not p_mined:
            return upgraded

        person_ta.validate_python(p_mined)

        if "OptOut" in p_mined:
            upgraded.add("Optout")
            return upgraded

        log.debug(f"miner {miner['endpoint']} on {el} gave {p_mined}")

        p_eligible = {
            k: v
            for k, v in p_mined.items()
            if (v and (miner['catchall'] or k in miner['update'] or k in miner['insert']))
        }

        upgraded = {k for k, v in p_eligible.items(
        ) if self.upgrade_person(miner, person, k, v)}

        return upgraded

    def upgrade_person(self, miner, person, k, v):
        modified = False

        # skip alternateName if same as name
        if k == "alternateName" and v == person.get("name"):
            log.debug(
                f"miner['endpoint'] does nothing - alternateName == name: {v}")
        # real update
        elif k not in person:
            modified = True
            person_set_field(person, k, v)
            log.debug(f"{miner['endpoint']} add {k} : {v}")
        elif person[k] == v:
            log.debug(
                f"{miner['endpoint']} does nothing - existing value {k} : {v}")
            return None
        elif k in miner["update"] or miner["catchall"]:
            modified = True
            person_set_field(person, k, v)
            log.debug(f"{miner['endpoint']} update {k} : {v}")
        else:
            log.debug(
                f"{miner['endpoint']} does nothing - already exists or insert mode {k} : {v}")
        return modified

    def register(self, **kw):
        """register a function as a miner

        Args:
            element (str): schema.org element to mine
            update (set): elements updated or added by the miner
            insert (set): elements inserted only by the miner
            transmute (bool): if miner is part of transmute, default to True

        Returns:
            function: miner
        """

        def decorator(miner_func):
            if kw['element'] in self._ordered_elements:
                # Check if this is dict/person
                parameters = signature(miner_func).parameters
                route_param = {}

                # Register as miner
                miner_param = {
                    'element': kw.pop('element'),
                    'update': kw.pop('update', []),
                    'insert': kw.pop('insert', []),
                    'transmute': kw.pop('transmute', False),
                    'endpoint': miner_func,
                    'parameters': parameters,
                }
                miner_param['catchall'] = not miner_param['insert'] and not miner_param['update']

                if any(param.annotation is dict for param in parameters.values()):
                    route_param['methods'] = [
                        'POST',
                    ]
                    miner_param['person_param'] = True
                else:
                    route_param['methods'] = [
                        'GET',
                    ]
                    miner_param['person_param'] = False

                # add to FastAPI Router
                if self.router:
                    route_param.update(kw)
                    route_param['path'] = self.default_path.format(
                        operation="transmute" if miner_param['transmute'] else "enrich",
                        element=miner_param['element'],
                        func_name=miner_func.__name__,
                    )
                    route_param['endpoint'] = miner_func
                    self.router.add_api_route(**route_param)

                log.debug(
                    f"add {miner_func.__name__} to miners with parameters: {miner_param}")
                self.miners[miner_param['element']].append(miner_param)
                self.elements.add(miner_param['element'])

            return miner_func

        return decorator
