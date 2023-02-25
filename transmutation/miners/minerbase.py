# Copyright 2022 Badreddine LEJMI.
# SPDX-License-Identifier: 	AGPL-3.0-or-later

"""Base miner"""
__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__copyright__ = "Ankaboot"
__license__ = "AGPL"

from collections import OrderedDict
from pydantic_schemaorg.Person import Person


class BaseAlchemist:
    _ordered_mining_fields = (
        "url",
        "sameAs",
        "email",
        "image",
        "sameAs",
    )

    @classmethod
    def from_keys(cls, **fields):
        return cls(Person(**fields))

    def __init__(self, person):
        self.person = person
        self._init_miners()

    def _init_miners(self):
        self.fields_miner = OrderedDict(
            {k: [] for k in self._ordered_mining_fields})

    def mine(self):
        for field in self._ordered_mining_fields:
            for miner in self.fields_miner[field]:
                miner(self)

    def dict(self):
        ...


if __name__ == "__main__":
    from loguru import logger as log

    p = Person(name="Khalil LEJMI")
    b = BaseMiner.from_keys(name="Khalil LEJMI")
    b.mine()
    log.debug(b.__dict__)
    log.debug(b.fields_miner)
