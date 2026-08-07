"""
Named materials — Verdant Borderlands / Qi Condensation (content expansion brief, section
9.1). Inert Materials-category items (use=None), the same status items.py's existing
Tier N Beast Core/Material have — held, traded, and available for future Blacksmith/
Alchemy recipes once one actually calls for them (none do yet). Merged into items.ITEMS
by items.py itself (see the import near the bottom of that file) rather than imported
directly by callers.
"""

from ..items import Item

VERDANT_MATERIALS: dict[str, Item] = {
    "Ironhide Bristle": Item(
        name="Ironhide Bristle", category="Materials", subcategory="Beast Trophy",
        description="A stiff, iron-grey bristle shed by an Ironhide Boar.",
    ),
    "Spirit Snake Fang": Item(
        name="Spirit Snake Fang", category="Materials", subcategory="Beast Trophy",
        description="A curved fang drawn from a Bamboo Shadow Snake, still faintly venomous.",
    ),
    "Moonlit Fur": Item(
        name="Moonlit Fur", category="Materials", subcategory="Beast Trophy",
        description="Fur shed by a Moon-Eared Rabbit that seems to hold a trace of moonlight.",
    ),
    "Crimson Flight Feather": Item(
        name="Crimson Flight Feather", category="Materials", subcategory="Beast Trophy",
        description="A spear-sharp flight feather molted by a Red-Crest Crane.",
    ),
    "Grave Moss": Item(
        name="Grave Moss", category="Materials", subcategory="Beast Trophy",
        description="Moss thick with residual qi, scraped from a Grave-Moss Corpse Beetle's shell.",
    ),
    "Wolf Heart Blood": Item(
        name="Wolf Heart Blood", category="Materials", subcategory="Beast Trophy",
        description="Blood drawn from a Blood Fang Wolf's heart, still warm with battle-qi.",
    ),
    "Jade Poison Pearl": Item(
        name="Jade Poison Pearl", category="Materials", subcategory="Beast Trophy",
        description="A jade-green pearl distilled in a Jade Shell Toad's throat sac.",
    ),
    "Hundred-Year Ginseng Root": Item(
        name="Hundred-Year Ginseng Root", category="Materials", subcategory="Alchemy Root",
        description="A century-old spirit ginseng root, dense with cultivation resource potential.",
    ),
    "Spirit Ginseng Seed": Item(
        name="Spirit Ginseng Seed", category="Materials", subcategory="Alchemy Root",
        description="A single viable seed from a hundred-year spirit ginseng — could grow another, given enough time.",
    ),
}
