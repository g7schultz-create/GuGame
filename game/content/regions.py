"""
Region definitions — pure content-organization metadata (content expansion brief, section
5.1). A Region does NOT change hunt/raid/search mechanics by itself; it's a label tying a
cluster of monster/material content together, and (later) a filter for a region picker.
No player-location/travel system exists yet, and none is implied by this module.

Only Verdant Borderlands (Qi Condensation) is populated so far — later regions get added
the same way, one at a time, per the brief's own "work in batches" instruction.
"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class Region:
    region_id: str
    name: str
    great_realm_index: int
    description: str
    theme_tags: List[str] = field(default_factory=list)
    hunt_monster_ids: List[str] = field(default_factory=list)
    material_ids: List[str] = field(default_factory=list)


VERDANT_BORDERLANDS = Region(
    region_id="verdant_borderlands",
    name="Verdant Borderlands",
    great_realm_index=0,
    description=(
        "Villages, bamboo forests, and mortal ruins at the edge of the cultivation world — "
        "where Qi Condensation cultivators take their first steps."
    ),
    theme_tags=["beast", "wood", "moon", "blood", "earth"],
    hunt_monster_ids=[
        "Ironhide Boar", "Bamboo Shadow Snake", "Moon-Eared Rabbit", "Red-Crest Crane",
        "Grave-Moss Corpse Beetle", "Blood Fang Wolf", "Jade Shell Toad", "Hundred-Year Spirit Ginseng",
    ],
    material_ids=[
        "Ironhide Bristle", "Spirit Snake Fang", "Moonlit Fur", "Crimson Flight Feather",
        "Grave Moss", "Wolf Heart Blood", "Jade Poison Pearl", "Hundred-Year Ginseng Root",
        "Spirit Ginseng Seed",
    ],
)

REGIONS: Dict[str, Region] = {VERDANT_BORDERLANDS.region_id: VERDANT_BORDERLANDS}
