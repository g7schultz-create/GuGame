"""
Named materials — Hundred Beast Mountains / Foundation Establishment (content expansion
brief section 9.2). Same inert Materials-category convention as
game/content/materials.py's own Verdant Borderlands set — split into its own module
(rather than appended to that one) simply to keep each region's content independently
reviewable, matching game/content/monsters/ and gu_families's own per-region file split.
"""

from ..items import Item

HUNDRED_BEAST_MOUNTAINS_MATERIALS: dict[str, Item] = {
    "Granite Ape Marrow": Item(
        name="Granite Ape Marrow", category="Materials", subcategory="Beast Trophy",
        description="Marrow from a Granite-Back Ape, dense enough to feel more like stone than bone.",
    ),
    "Cloudstep Lynx Pelt": Item(
        name="Cloudstep Lynx Pelt", category="Materials", subcategory="Beast Trophy",
        description="A pelt from a Cloudstep Lynx, unnaturally light for its size.",
    ),
    "Ironbeak Feather": Item(
        name="Ironbeak Feather", category="Materials", subcategory="Beast Trophy",
        description="A flight feather from an Ironbeak Vulture, dark and hard along its whole spine.",
    ),
    "Venom Mist Silk": Item(
        name="Venom Mist Silk", category="Materials", subcategory="Beast Trophy",
        description="Silk drawn from a Venom Mist Spider's web, still faintly toxic to the touch.",
    ),
    "Thunderhorn": Item(
        name="Thunderhorn", category="Materials", subcategory="Beast Trophy",
        description="A horn taken from a Thunderhorn Yak, warm and faintly charged even long after the kill.",
    ),
    "White Tiger Soul Eye": Item(
        name="White Tiger Soul Eye", category="Materials", subcategory="Beast Trophy",
        description="A milky, unsettling eye taken from a Ghost-Eyed White Tiger — still seems to be looking at something.",
    ),
}
