# Copyright 2022 Badreddine LEJMI.
# SPDX-License-Identifier: 	AGPL-3.0-or-later

"""Base Alchemist"""
__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__copyright__ = "Ankaboot"
__license__ = "AGPL"

from collections import OrderedDict
from pydantic_schemaorg.Person import Person
from loguru import logger as log


class Alchemist:
    """Enrich iteratively persons using miners"""

    _ordered_elements = {
        "url",
        "sameAs",
        "email",
        "image",
    }

    def __init__(self):
        self.elements = set()
        self.miners = OrderedDict({k: [] for k in self._ordered_elements})

    async def transmute_person(self, person: Person) -> tuple[bool, Person]:
        """Transmute one person

        Args:
            person (Person): person to transmute

        Returns:
            bool, Person: succeed or not, enriched person
        """
        elements = list(self.elements & person.__fields_set__)

        p_new = person.dict(exclude_unset=True, exclude_none=True)
        log.debug(f"mining {elements} for {person}")

        modified = False
        # sync because we want to control the order of mining elements
        for el in elements:
            log.debug(f"mining {el}: {p_new.get(el)}")

            if el not in self.miners:
                log.debug(f"no miner for {el}")
                continue

            for miner in self.miners[el]:
                log.debug(f"mining {el} with miner {miner}")
                p_status, p_mined = await miner(Person(**p_new))
                if p_status:
                    log.debug(f"miner {miner} on {el} gave {p_mined}")
                    p_new.update(p_mined)

                    if not modified:
                        modified = True

                    # add new elements with miners registered
                    new_keys = set(p_mined.keys()) & self.elements
                    if new_keys:
                        elements.extend(list(new_keys))

        return modified, Person(**p_new)

    async def transmute_bulk(self, persons: list[Person]):
        """Bulk transmute

        Args:
            persons (list[Person]): list of persons to transmute

        Yields:
            Iterator[AsyncIterator]: iterator over transmuted person
        """
        async for person in persons:
            yield self.transmute_person(person)

    async def transmute(self, person: Person = None, persons: list[Person] = None):
        if person:
            return await self.transmute_person(person)
        elif persons:
            return self.transmute_bulk(persons)

    def register(self, element: str):
        def decorator(miner_func):
            if element in self._ordered_elements:
                log.debug(f"add {miner_func} to miners for {element}")
                self.miners[element].append(miner_func)
                self.elements.add(element)
            return miner_func

        return decorator
