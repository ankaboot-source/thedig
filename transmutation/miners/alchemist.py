# Copyright 2022 Badreddine LEJMI.
# SPDX-License-Identifier: 	AGPL-3.0-or-later

"""Base Alchemist"""
__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__copyright__ = "Ankaboot"
__license__ = "AGPL"

from functools import wraps
from loguru import logger as log


class Alchemist:
    """Enrich iteratively persons using miners"""

    _ordered_elements = {
        "url",
        "sameAs",
        "email",
        "image",
        "description",
        "name",
    }

    def __init__(self):
        self.elements = set()
        self.miners = {k: [] for k in self._ordered_elements}

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
                if not p_mined or p_mined == person:
                    continue
                if "OptOut" in p_mined:
                    return False, {"OptOut": True}

                log.debug(f"miner {miner['func']} on {el} gave {p_mined}")

                if not modified:
                    modified = True

                for k, v in p_mined.items():
                    if not v:
                        continue
                    # eligibility to update
                    if (
                        not miner["catchall"]
                        and k not in miner["update"]
                        and k not in miner["insert"]
                    ):
                        continue

                    # real update
                    if k not in person:
                        person[k] = v
                        log.debug(f"{miner['func']} add {k} : {v}")
                    elif k in miner["update"] or miner["catchall"]:
                        # gymnastic to update/add set
                        if type(person[k]) is not set:
                            person[k] = {
                                person[k],
                            }
                        if type(v) is not set:
                            v = {
                                v,
                            }
                        person[k] |= v
                        log.debug(f"{miner['func']} update {k} : {v}")
                    else:
                        log.debug(
                            f"{miner['func']} does nothing - already exists or insert mode {k} : {v}"
                        )

                    # eligibility to mine
                    if k in self.elements:
                        elements.append(k)
                        log.debug(f"new element to mine: {k}")

        return modified, person if modified else None

    async def bulk(self, persons: list[dict]):
        """Bulk transmute

        Args:
            persons (list[dict]): list of persons to transmute

        Yields:
            Iterator[AsyncIterator]: iterator over transmuted person
        """
        for person in persons:
            yield self.person(person)

    def register(self, **kw):
        """register a function as a miner for an element field

        Args:
            element (str): schema.org element to mine
            output (set): elements added by the miner

        Returns:
            function: miner
        """

        def decorator(miner_func):
            if kw["element"] in self._ordered_elements:
                log.debug(f"add {miner_func} to miners with parameters: {kw}")
                self.miners[kw["element"]].append(
                    {
                        "func": miner_func,
                        "update": kw.get("update") or [],
                        "insert": kw.get("insert") or [],
                        "catchall": not kw.get("insert") and not kw.get("update"),
                    }
                )
                self.elements.add(kw["element"])
            return miner_func

        return decorator
