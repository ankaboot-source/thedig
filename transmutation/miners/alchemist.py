# Copyright 2022 Badreddine LEJMI.
# SPDX-License-Identifier: 	AGPL-3.0-or-later

"""Base Alchemist"""
__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__copyright__ = "Ankaboot"
__license__ = "AGPL"

from collections import OrderedDict
from functools import wraps
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

            for miner in self.miners[el]:
                log.debug(f"mining {el} with miner {miner}")
                p_mined = await miner["func"](person)
                if p_mined:
                    log.debug(f"miner {miner['func']} on {el} gave {p_mined}")

                    if not modified:
                        modified = True

                    for k, v in p_mined.items():
                        # eligibility to update
                        if k in miner["output"]:
                            person[k] = v
                            # eligibility to mine
                            if k in self.elements:
                                elements.append(k)

        return modified, person

    async def bulk(self, persons: list[dict]):
        """Bulk transmute

        Args:
            persons (list[dict]): list of persons to transmute

        Yields:
            Iterator[AsyncIterator]: iterator over transmuted person
        """
        for person in persons:
            yield self.person(person)

    def register(self, element: str, output: tuple | str):
        """register a function as a miner for an element field

        Args:
            element (str): schema.org element to mine
            output (set): elements added by the miner

        Returns:
            function: miner
        """

        def decorator(miner_func):
            if element in self._ordered_elements:
                log.debug(f"add {miner_func} to miners for {element}")
                self.miners[element].append(
                    {
                        "func": miner_func,
                        "output": output if type(output) is tuple else (output,),
                    }
                )
                self.elements.add(element)
            return miner_func

        return decorator
