"""
Named materials — Crimson Furnace Province / Core Formation (content expansion brief
section 9.3, plus two original entries in the same style — the brief only names 5 for this
region's 7 hunt monsters that need one, same "brief underspecifies, extend consistently"
precedent as Hundred Beast Mountains' own secret realms/dream realms). Same inert
Materials-category convention as every other region's materials module.
"""

from ..items import Item

CRIMSON_FURNACE_MATERIALS: dict[str, Item] = {
    "Magma Scale": Item(
        name="Magma Scale", category="Materials", subcategory="Beast Trophy",
        description="A scale from a Magma-Scale Salamander, still faintly warm long after the kill.",
    ),
    "Living Furnace Heart": Item(
        name="Living Furnace Heart", category="Materials", subcategory="Beast Trophy",
        description="A furnace hound's own heart, somehow still radiating forge-heat.",
    ),
    "Ashwing Feather": Item(
        name="Ashwing Feather", category="Materials", subcategory="Beast Trophy",
        description="A feather from an Ashwing Crow, edged in fine grey ash that never quite falls off.",
    ),
    "Molten Shell Fragment": Item(
        name="Molten Shell Fragment", category="Materials", subcategory="Beast Trophy",
        description="A fragment of a Molten Shell Scorpion's carapace, cooled hard but still faintly glowing at the core.",
    ),
    "Ember Vein Venom Gland": Item(
        name="Ember Vein Venom Gland", category="Materials", subcategory="Beast Trophy",
        description="A venom gland from an Ember Vein Python, hot enough to cauterize its own bite.",
    ),
    "Crimson Lion Core": Item(
        name="Crimson Lion Core", category="Materials", subcategory="Beast Trophy",
        description="A condensed core of battle-qi taken from a Crimson Furnace Lion.",
    ),
    "Star-Iron Digestive Crystal": Item(
        name="Star-Iron Digestive Crystal", category="Materials", subcategory="Beast Trophy",
        description="A crystal formed in a Star-Iron Devouring Worm's gut from decades of digested ore.",
    ),
    "Living Pill Core": Item(
        name="Living Pill Core", category="Materials", subcategory="Alchemy Root",
        description="The still-faintly-aware core of a Runaway Living Pill — a rare, unsettling alchemy component.",
    ),
}
