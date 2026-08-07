"""
Gu "type" (see game/killer_move_gen.py, /killer_move) -- a thematic tag every Gu family/canon
entry/flat item carries, used to compute a Killer Move's harmony (how many of the 10 component
Gu share the core Gu's type) and its dominant kind (via TYPE_AFFINITY below). No such field
existed anywhere on Gu before this -- see the approved Killer Move plan's own research: only
canon_gu.py's 26 entries had a `path` (source-data only, never stored on the runtime Equipment
object), and the other ~350 catalog entries (quality-tier variants of ~50 tiered families/flat
items) had no thematic tagging of any kind.

Deliberately reuses the SAME tag vocabulary manual pages already use (manual_data.ALL_PATH_TAGS)
rather than inventing a 4th parallel taxonomy alongside cultivation_path (Righteous/Demonic/
Rogue), the Dao Paths' 14 names, and canon_gu.py's own path values -- canon Gu's 26 existing path
values map onto this vocabulary directly. A couple of tags outside that list ("light", "storage")
are added the same way manual_data.py itself extends ALL_PATH_TAGS beyond its own family table.

Only needs assigning at the family/canon-entry/flat-item level (~76 distinct names below), not
per catalog item -- every quality tier of one family shares its family's type.
"""

from typing import Dict, Optional

from . import equipment

# family/canon/flat name -> type tag. Canon Gu (see canon_gu.CANON_GU) reuse their own existing
# `path` field lowercased; everything else is assigned from its family name/theme.
GU_TYPE_BY_NAME: Dict[str, str] = {
    # equipment.py's own 4 base tiered families
    "Ironhide Boar Gu": "earth",
    "Charging Tusk Gu": "strength",
    "Blood Boar Gu": "blood",
    "Savage Boar Gu": "strength",
    # equipment.py's 3 flat starters (Iron Skin Gu/Boar Strength Gu also exist as Verdant
    # Borderlands tiered families below -- same name, same type either way, one entry serves both)
    "Iron Skin Gu": "earth",
    "Boar Strength Gu": "strength",
    "Charge Gu": "strength",
    # content/gu_families.py -- Verdant Borderlands (drop_rank 1)
    "Moon Rabbit Gu": "moon",
    "Blood Fang Gu": "blood",
    "Bone Shield Gu": "bone",
    "Concealed Fang Gu": "shadow",
    # content/gu_families_hundred_beast_mountains.py (drop_rank 2)
    "Granite Body Gu": "earth",
    "Cloudstep Gu": "wind",
    "Thunderhorn Gu": "lightning",
    "Ghost Eye Gu": "shadow",
    "Venom Web Gu": "poison",
    # content/gu_families_crimson_furnace.py (drop_rank 3)
    "Furnace Heart Gu": "fire",
    "Magma Skin Gu": "fire",
    "Star-Iron Stomach Gu": "metal",
    "Ashwing Gu": "fire",
    "Living Flame Gu": "fire",
    # content/gu_families_duskwraith_barrens.py (drop_rank 4)
    "Bonewrought Gu": "bone",
    "Duskfang Gu": "shadow",
    "Wraithmoth Gu": "dream",
    "Soulglass Gu": "soul",
    "Hollow Marrow Gu": "bone",
    # canon_gu.py's 26 -- lowercased straight from each entry's own `path` field
    "Moonlight Gu": "moon",
    "Little Light Gu": "light",
    "Liquor Worm": "food",
    "Wine Sack Flower Gu": "food",
    "Rice Pouch Grass Gu": "food",
    "Black Boar Gu": "strength",
    "White Boar Gu": "strength",
    "Copper Skin Gu": "strength",
    "Brute Force Longhorn Beetle Gu": "strength",
    "Mudskin Toad Gu": "earth",
    "Treasure Brass Toad": "storage",
    "Golden Bell Gu": "metal",
    "Water Spider Gu": "water",
    "Footprint Gu": "movement",
    "Bamboo Gentleman": "wood",
    "Relic Gu": "human",
    "Jade Skin Gu": "strength",
    "White Jade Gu": "strength",
    "Spiral Bone Spear Gu": "bone",
    "Moonshadow Gu": "moon",
    "All-Out Effort Gu": "strength",
    "Sky Canopy Gu": "light",
    "Battle Bone Wheel": "bone",
    "Heavenly Essence Treasure Lotus": "wood",
    "Spring Autumn Cicada": "time",
    "Fortune Rivalling Heaven Gu": "luck",
    # world_boss.py's 24 flat Gu
    "Strength Qi Gu": "strength",
    "Mountain Strength Gu": "earth",
    "Dragon Strength Gu": "strength",
    "Sword Escape Gu": "sword",
    "Flying Sword Gu": "sword",
    "Dog Shit Luck Gu": "luck",
    "Treasure Lotus Gu": "luck",
    "Battle Intent Gu": "strength",
    "Blood Deity Gu": "blood",
    "Iron Bone Gu": "bone",
    "Diamond Skin Gu": "earth",
    "Lightning Wings Gu": "lightning",
    "Dream Wings Gu": "dream",
    "Star Thought Gu": "star",
    "Divine Concealment Gu": "heaven",
    "Heavenly Secret Gu": "heaven",
    "Beast Soul Gu": "soul",
    "Human Qi Gu": "human",
    "Fixed Immortal Travel Gu": "space",
    "Connect Luck Gu": "luck",
    "Divine Travel Gu": "space",
    "Heavenly Web Gu": "heaven",
    "Worldly Escape Gu": "space",
    "Poison Gu": "poison",
}

# Every type tag actually used above -> which Killer Move "kind" it pushes toward. A Killer
# Move's mechanical kind is decided by whichever affinity is most common among its 10 component
# Gu (see killer_move_gen.dominant_kind) -- the core Gu only sets the move's flavor/name.
TYPE_AFFINITY: Dict[str, str] = {
    # damage -- aggressive/elemental/edged themes
    "strength": "damage", "shadow": "damage", "wind": "damage", "lightning": "damage",
    "poison": "damage", "fire": "damage", "sword": "damage",
    # buff -- defensive/vitality themes
    "earth": "buff", "blood": "buff", "metal": "buff", "bone": "buff",
    # essence -- restorative/gentle themes
    "moon": "essence", "light": "essence", "food": "essence", "water": "essence",
    # cultivation -- introspective/mystical themes
    "dream": "cultivation", "soul": "cultivation", "wood": "cultivation", "human": "cultivation",
    "star": "cultivation", "heaven": "cultivation", "time": "cultivation",
    # loot -- fortune/utility themes
    "storage": "loot", "movement": "loot", "luck": "loot", "space": "loot",
}


def gu_type_for(item_name: str) -> Optional[str]:
    """Resolves an owned/equipped Gu item's type. Tiered-family and canon items are stored as
    "Family (Quality)" (see equipment.gu_item_name) -- parse_gu_name strips the quality suffix
    to recover the family name. Flat items (starters, World Boss Gu) have no such suffix; their
    own bare name IS the lookup key."""
    family, _ = equipment.parse_gu_name(item_name)
    return GU_TYPE_BY_NAME.get(family or item_name)
