"""
Named materials -- White Heaven (see game/white_heaven.py, content/monsters/white_heaven.py).
Same inert-Materials-category shape content/materials.py's VERDANT_MATERIALS already
established (use=None, held/traded, available for future recipes) -- reuses the existing
Beast Trophy/Alchemy Root/Essence subcategories rather than inventing a new one (see
items.MATERIAL_SUBCATEGORIES for the full recognized list). Merged into items.ITEMS by
items.py itself.
"""

from ..items import Item

WHITE_HEAVEN_MATERIALS: dict[str, Item] = {
    "White Heaven Floating Dust": Item(
        name="White Heaven Floating Dust", category="Materials", subcategory="Essence",
        description="Fine, faintly luminous dust that never quite settles, drifting endlessly through White Heaven's cloud seas.",
    ),
    "Aurora-Veined Shard": Item(
        name="Aurora-Veined Shard", category="Materials", subcategory="Essence",
        description="A crystal shard threaded with color, cut from one of White Heaven's own aurora light-path zones.",
    ),
    "Cloud Sea Mist Vial": Item(
        name="Cloud Sea Mist Vial", category="Materials", subcategory="Alchemy Root",
        description="A sealed vial of mist drawn straight from White Heaven's endless cloud seas -- it never fully stops moving.",
    ),
    "Nine Heavens Lotus Petal": Item(
        name="Nine Heavens Lotus Petal", category="Materials", subcategory="Alchemy Root",
        description="A single petal from a lotus rare enough that most cultivators only ever hear about it secondhand.",
    ),
    "Blinking Bird Feather": Item(
        name="Blinking Bird Feather", category="Materials", subcategory="Beast Trophy",
        description="A flight feather that still seems to flicker between two places at once, shed by a Blinking Bird.",
    ),
    "Remnant Heavenly Dog Fang": Item(
        name="Remnant Heavenly Dog Fang", category="Materials", subcategory="Beast Trophy",
        description="A fang drawn from a Remnant Heavenly Dog, unnervingly warm long after the hunt is over.",
    ),
    "Cloud Beast Hide": Item(
        name="Cloud Beast Hide", category="Materials", subcategory="Beast Trophy",
        description="Hide shed by a Cloud Beast, dense and half-solid the way the beast itself always seemed to be.",
    ),
}
