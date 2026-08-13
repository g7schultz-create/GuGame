"""
Canon Gu catalog, from the Reverend Insanity-inspired Gu database spec supplied for this
project — layered into the EXISTING Gu architecture rather than replacing it: ownership
via the normal inventory table, quality folded into the item name via
equipment.gu_item_name (the spec's "star 1-7" maps 1:1 onto the existing Common..Immortal
quality ladder), and upgrades through the existing /upgrade_gu duplicate-fusion flow (see
equipment.GU_UPGRADE_DUPLICATES_REQUIRED for the spec's variable per-tier duplicate cost,
now used for every Gu in the game, not just these 26).

Only 7 of the 26 have a real passive wired up, matching the spec's own "make passive Gu
affect these systems" list: Liquor Worm (cultivation), Treasure Brass Toad (spirit
stones), Footprint Gu (loot chance), Water Spider Gu (dodge), Heavenly Essence Treasure
Lotus (essence-restore bonus) — plus Black Boar Gu/White Boar Gu, since their effect is
just a flat STR bonus the equipment system already handles for free. The other 19 are
damage/shield/silence/buff/instant abilities that need a real in-combat ability engine
(essence costs, cooldowns, effect types) hunt.py/raid.py don't have yet — deferred, the
same way Alchemist/Blacksmith crafting was until their recipes existed. Each of those
still grants a small role-flavored passive (derived from base_power) so equipping one
isn't a complete no-op while that engine doesn't exist yet.

Per the spec's drop rules: Gu with drop_weight == 0 (Unique/event-only — Spring Autumn
Cicada, Fortune Rivalling Heaven Gu) are registered as real, equippable items (so they can
still be granted for events) but are never eligible in roll_canon_gu_drop.
"""

import random

from . import equipment
from .content.canon_gu_white_heaven import (
    WHITE_HEAVEN_CANON_GU, WHITE_HEAVEN_FUNCTIONAL_EFFECT_BY_STAR, WHITE_HEAVEN_FUNCTIONAL_STAT_KEY,
)

# From the spec's STAR_EFFECT_MULTIPLIER table.
STAR_EFFECT_MULTIPLIER = {1: 1.00, 2: 1.12, 3: 1.25, 4: 1.40, 5: 1.58, 6: 1.80, 7: 2.05}

# name -> per-star "effect" value, transcribed directly from the spec's own Star Values
# tables for the 7 Gu that get a real passive (see _FUNCTIONAL_STAT_KEY) — using the
# spec's own precomputed numbers rather than re-deriving them from the raw formula.
_FUNCTIONAL_EFFECT_BY_STAR = {
    "Liquor Worm": [8, 9, 10, 11, 13, 14, 16],
    "Black Boar Gu": [5, 6, 6, 7, 8, 9, 10],
    "White Boar Gu": [7, 8, 9, 10, 11, 13, 14],
    "Treasure Brass Toad": [8, 9, 10, 11, 13, 14, 16],
    "Water Spider Gu": [8, 9, 10, 11, 13, 14, 16],
    "Footprint Gu": [10, 11, 12, 14, 16, 18, 20],
    "Heavenly Essence Treasure Lotus": [12, 13, 15, 17, 19, 22, 25],
}
# White Heaven's own 18 functional Gu (see content/canon_gu_white_heaven.py's own module
# docstring for the calibration approach) -- merged in before _register_canon_gu() runs.
_FUNCTIONAL_EFFECT_BY_STAR.update(WHITE_HEAVEN_FUNCTIONAL_EFFECT_BY_STAR)

# Which equipment stat_bonuses key each functional Gu's effect feeds, and whether the
# transcribed value is a flat number (permanent_strength) or a fraction of a percent
# (everything else here — the spec's numbers are percentage points, e.g. 8 means 8%).
_FUNCTIONAL_STAT_KEY = {
    "Liquor Worm": ("cultivation_speed_pct", "percent"),
    "Black Boar Gu": ("str_stat", "flat"),
    "White Boar Gu": ("str_stat", "flat"),
    "Treasure Brass Toad": ("stone_reward_bonus_pct", "percent"),
    "Water Spider Gu": ("dodge_chance_pct", "percent"),
    "Footprint Gu": ("loot_chance_bonus_pct", "percent"),
    "Heavenly Essence Treasure Lotus": ("essence_regen_pct", "percent"),
}
_FUNCTIONAL_STAT_KEY.update(WHITE_HEAVEN_FUNCTIONAL_STAT_KEY)

CANON_GU = [
    {"name": "Moonlight Gu", "gu_rank": 1, "path": "Moon", "role": "Attack", "rarity": "Common", "drop_weight": 130, "base_power": 12, "is_passive": False,
     "description": "Fires a crescent moonblade at an enemy.", "effect_text": "Deals Moon-path damage to one enemy. (Active ability — coming soon.)"},
    {"name": "Little Light Gu", "gu_rank": 1, "path": "Light", "role": "Support", "rarity": "Common", "drop_weight": 120, "base_power": 7, "is_passive": False,
     "description": "Produces light and strengthens compatible light or moon techniques.", "effect_text": "Boosts the next Light- or Moon-path Gu used. (Active ability — coming soon.)"},
    {"name": "Liquor Worm", "gu_rank": 1, "path": "Food", "role": "Cultivation", "rarity": "Rare", "drop_weight": 28, "base_power": 16, "is_passive": True,
     "description": "Improves the quality of primeval essence during cultivation.", "effect_text": "Passively increases Qi gained from /cultivate."},
    {"name": "Wine Sack Flower Gu", "gu_rank": 1, "path": "Food", "role": "Storage", "rarity": "Common", "drop_weight": 105, "base_power": 4, "is_passive": True,
     "description": "Stores wine and liquid refinement materials.", "effect_text": "Increases wine and liquid refinement-material drops. (Not modeled yet — coming soon.)"},
    {"name": "Rice Pouch Grass Gu", "gu_rank": 1, "path": "Food", "role": "Storage", "rarity": "Common", "drop_weight": 110, "base_power": 4, "is_passive": True,
     "description": "Stores provisions and basic cultivation supplies.", "effect_text": "Increases food, herb, and provision drops. (Not modeled yet — coming soon.)"},
    {"name": "Black Boar Gu", "gu_rank": 1, "path": "Strength", "role": "Permanent", "rarity": "Uncommon", "drop_weight": 65, "base_power": 18, "is_passive": True,
     "description": "Permanently strengthens the user's body with black-boar strength.", "effect_text": "Grants a permanent STR bonus."},
    {"name": "White Boar Gu", "gu_rank": 1, "path": "Strength", "role": "Permanent", "rarity": "Uncommon", "drop_weight": 55, "base_power": 20, "is_passive": True,
     "description": "Permanently strengthens the user's body with white-boar strength.", "effect_text": "Grants a larger permanent STR bonus than Black Boar Gu."},
    {"name": "Copper Skin Gu", "gu_rank": 1, "path": "Strength", "role": "Defense", "rarity": "Uncommon", "drop_weight": 72, "base_power": 13, "is_passive": False,
     "description": "Hardens the skin to reduce incoming physical damage.", "effect_text": "Reduces physical damage taken for several turns. (Active ability — coming soon.)"},
    {"name": "Brute Force Longhorn Beetle Gu", "gu_rank": 1, "path": "Strength", "role": "Attack", "rarity": "Uncommon", "drop_weight": 62, "base_power": 15, "is_passive": False,
     "description": "Temporarily increases raw physical strength.", "effect_text": "Temporarily increases physical attack. (Active ability — coming soon.)"},
    {"name": "Mudskin Toad Gu", "gu_rank": 1, "path": "Earth", "role": "Defense", "rarity": "Common", "drop_weight": 90, "base_power": 10, "is_passive": False,
     "description": "Coats the body in a layer of protective mud.", "effect_text": "Creates a temporary Earth-path shield. (Active ability — coming soon.)"},
    {"name": "Treasure Brass Toad", "gu_rank": 1, "path": "Storage", "role": "Storage", "rarity": "Rare", "drop_weight": 30, "base_power": 8, "is_passive": True,
     "description": "Stores valuable materials and currency.", "effect_text": "Increases spirit-stone rewards from raid victories."},
    {"name": "Golden Bell Gu", "gu_rank": 1, "path": "Metal", "role": "Defense", "rarity": "Rare", "drop_weight": 24, "base_power": 19, "is_passive": False,
     "description": "Creates a bell-shaped defensive barrier.", "effect_text": "Creates a strong Metal-path shield. (Active ability — coming soon.)"},
    {"name": "Water Spider Gu", "gu_rank": 1, "path": "Water", "role": "Movement", "rarity": "Common", "drop_weight": 88, "base_power": 9, "is_passive": True,
     "description": "Improves movement across water and wet terrain.", "effect_text": "Increases dodge chance."},
    {"name": "Footprint Gu", "gu_rank": 1, "path": "Movement", "role": "Tracking", "rarity": "Common", "drop_weight": 95, "base_power": 7, "is_passive": True,
     "description": "Reveals or records tracks left by targets.", "effect_text": "Increases loot chance on hunt/raid kills."},
    {"name": "Bamboo Gentleman", "gu_rank": 1, "path": "Wood", "role": "Utility", "rarity": "Uncommon", "drop_weight": 58, "base_power": 11, "is_passive": False,
     "description": "A refined utility Gu suited to investigation and restraint.", "effect_text": "Restrains an enemy. (Active ability — coming soon.)"},
    {"name": "Relic Gu", "gu_rank": 1, "path": "Human", "role": "Cultivation", "rarity": "Epic", "drop_weight": 8, "base_power": 30, "is_passive": False,
     "description": "Instantly advances mortal cultivation within its allowed rank.", "effect_text": "Grants a large one-time Qi reward. (Active ability — coming soon.)"},
    {"name": "Jade Skin Gu", "gu_rank": 2, "path": "Strength", "role": "Defense", "rarity": "Uncommon", "drop_weight": 52, "base_power": 26, "is_passive": False,
     "description": "Turns the skin jade-like and greatly improves defense.", "effect_text": "Reduces physical damage and grants minor poison resistance. (Active ability — coming soon.)"},
    {"name": "White Jade Gu", "gu_rank": 2, "path": "Strength", "role": "Defense", "rarity": "Rare", "drop_weight": 22, "base_power": 34, "is_passive": False,
     "description": "A stronger jade-body defense formed from compatible Gu.", "effect_text": "Powerful physical-defense buff and minor healing. (Active ability — coming soon.)"},
    {"name": "Spiral Bone Spear Gu", "gu_rank": 2, "path": "Bone", "role": "Attack", "rarity": "Uncommon", "drop_weight": 46, "base_power": 29, "is_passive": False,
     "description": "Launches a rotating bone spear with improved penetration.", "effect_text": "Armor-piercing Bone-path damage. (Active ability — coming soon.)"},
    {"name": "Moonshadow Gu", "gu_rank": 2, "path": "Moon", "role": "Restriction", "rarity": "Rare", "drop_weight": 19, "base_power": 31, "is_passive": False,
     "description": "Suppresses or interferes with an opponent's Gu activation.", "effect_text": "Chance to silence the target's next Gu use. (Active ability — coming soon.)"},
    {"name": "All-Out Effort Gu", "gu_rank": 3, "path": "Strength", "role": "Attack", "rarity": "Epic", "drop_weight": 7, "base_power": 58, "is_passive": False,
     "description": "Allows the user to unleash their accumulated strength more completely.", "effect_text": "Multiplies Strength-path damage for one attack. (Active ability — coming soon.)"},
    {"name": "Sky Canopy Gu", "gu_rank": 3, "path": "Light", "role": "Defense", "rarity": "Rare", "drop_weight": 14, "base_power": 52, "is_passive": False,
     "description": "Forms a powerful canopy of light for protection.", "effect_text": "Large Light-path shield. (Active ability — coming soon.)"},
    {"name": "Battle Bone Wheel", "gu_rank": 4, "path": "Bone", "role": "Attack", "rarity": "Legendary", "drop_weight": 3, "base_power": 92, "is_passive": False,
     "description": "A brutal bone-path battle Gu suited to repeated attacks.", "effect_text": "Repeated Bone-path damage. (Active ability — coming soon.)"},
    {"name": "Heavenly Essence Treasure Lotus", "gu_rank": 5, "path": "Wood", "role": "Resource", "rarity": "Mythic", "drop_weight": 1, "base_power": 140, "is_passive": True,
     "description": "Produces cultivation resources and accelerates essence recovery.", "effect_text": "Boosts primeval essence recovered from essence-restoring items."},
    # Gu Rank 7 (Ancient Realm) had no normally-droppable entry at all -- roll_canon_gu_drop's
    # "enemy_gu_rank or one rank below" fallback landed on rank 6, but that slot (Spring Autumn
    # Cicada) is ALSO drop_weight=0 (event-only), so Ancient Realm hunts/raids could never drop
    # a canon Gu at all. Same rarity/drop_weight as rank 5's own Mythic entry (the rarest tier
    # that's still normally obtainable, one step below the Unique/event-only tier ranks 6 and 8
    # sit at) rather than another event-only slot, since that wouldn't have closed the gap.
    # base_power=950 (2026-08-12, explicit request: "the strongest") -- strictly above every
    # other entry in this list, including the two drop_weight=0/Unique ones (Fortune Rivalling
    # Heaven Gu's 900, Spring Autumn Cicada's 500), since /killer_move's own core-Gu picker
    # lists all three side by side and the request was for it to win that comparison outright.
    {"name": "Primeval Origin Gu", "gu_rank": 7, "path": "Heaven", "role": "Attack", "rarity": "Mythic", "drop_weight": 1, "base_power": 950, "is_passive": False,
     "description": "A Gu condensed from the primeval origin-qi of creation itself, said to carry a sliver of the world's own genesis intent.",
     "effect_text": "Unleashes a devastating Heaven-path strike drawn from the world's origin. (Active ability — coming soon.)"},
    {"name": "Spring Autumn Cicada", "gu_rank": 6, "path": "Time", "role": "Rebirth", "rarity": "Unique", "drop_weight": 0, "base_power": 500, "is_passive": False,
     "description": "A time-path Immortal Gu associated with rebirth through the River of Time.", "effect_text": "Event-only Immortal Gu. Never drops normally. (Active ability — coming soon.)"},
    {"name": "Fortune Rivalling Heaven Gu", "gu_rank": 8, "path": "Luck", "role": "Luck", "rarity": "Unique", "drop_weight": 0, "base_power": 900, "is_passive": True,
     "description": "An extraordinary luck-path Immortal Gu; event-only in this game.", "effect_text": "Event-only Immortal Gu. Never drops normally. Greatly improves rare drops and encounters. (Not modeled yet.)"},
]

# White Heaven's own 20 Rank 8 Unique Gu (see content/canon_gu_white_heaven.py) -- also
# drop_weight=0 like the 2 entries just above, but reachable through a SEPARATE roll
# (GameManager.roll_white_heaven_bonus_gu) rather than event-only manual grants.
CANON_GU.extend(WHITE_HEAVEN_CANON_GU)

CANON_GU_BY_NAME = {gu["name"]: gu for gu in CANON_GU}

_ROLE_FALLBACK_STAT = {"Attack": "str_stat", "Defense": "def_stat"}


def _stat_bonuses_for_star(gu_data: dict, star: int) -> dict:
    name = gu_data["name"]
    quality = equipment.GU_QUALITY_ORDER[star - 1]
    budget = equipment.GU_QUALITY_PCT_BUDGET[quality]
    if name in _FUNCTIONAL_STAT_KEY:
        key, kind = _FUNCTIONAL_STAT_KEY[name]
        value = _FUNCTIONAL_EFFECT_BY_STAR[name][star - 1]
        if kind == "flat":
            # Black Boar Gu / White Boar Gu's permanent STR bonus — a foundation stat, so it
            # goes through the same flat->pct conversion every other Gu uses, sized off the
            # same quality budget curve (matching equipment.foundation_stats_to_pct exactly,
            # just with one stat so weighting is a no-op).
            return equipment.foundation_stats_to_pct({key: value}, budget)
        return {key: value / 100}
    # No real mechanic yet — a small role-flavored passive derived from base_power, so the
    # Gu isn't a complete no-op while its real (active/instant) effect is still pending.
    power = round(gu_data["base_power"] * STAR_EFFECT_MULTIPLIER[star] * 0.15)
    stat = _ROLE_FALLBACK_STAT.get(gu_data["role"], "qi_stat")
    return equipment.foundation_stats_to_pct({stat: max(1, power)}, budget)


def _register_canon_gu():
    for gu_data in CANON_GU:
        for star, quality in enumerate(equipment.GU_QUALITY_ORDER, start=1):
            item_name = equipment.gu_item_name(gu_data["name"], quality)
            stat_bonuses = _stat_bonuses_for_star(gu_data, star)
            stars_text = "★" * star
            equipment.EQUIPMENT[item_name] = equipment.Equipment(
                name=item_name,
                slot_type="Gu",
                rank=f"{stars_text} {quality}",
                description=(
                    f"[Canon] {gu_data['name']} — {gu_data['path']} path, {gu_data['role']} role, "
                    f"Gu Rank {gu_data['gu_rank']}, {quality} quality. {gu_data['description']} "
                    f"{gu_data['effect_text']} {equipment.describe_stat_bonuses(stat_bonuses)}."
                ),
                stat_bonuses=stat_bonuses,
            )


_register_canon_gu()

# -- Weighted drops (see the spec's DROP RULES) -------------------------------------------

DROP_CHANCE_BY_ENCOUNTER = {"normal": 0.04, "elite": 0.10, "mini_boss": 0.20, "world_boss": 0.45}


def roll_canon_gu_drop(enemy_gu_rank: int, encounter_kind: str = "normal", luck_bonus: float = 0.0, chance_multiplier: float = 1.0):
    """Rolls the canon Gu catalog: base chance by encounter_kind (+luck_bonus, then scaled
    by chance_multiplier — e.g. a raid's AFK reward penalty, mirroring monsters.roll_loot),
    then a drop_weight-weighted pick among Gu at enemy_gu_rank or one rank below (DROP RULE
    1). Always drops at Common quality/star 1 ("a newly obtained Gu starts at 1 star").
    Returns an item_name, or None if nothing dropped. drop_weight == 0 (Unique/event-only)
    Gu are never eligible (DROP RULE 3)."""
    chance = (DROP_CHANCE_BY_ENCOUNTER.get(encounter_kind, 0.04) + luck_bonus) * chance_multiplier
    if random.random() >= chance:
        return None
    eligible = [
        gu for gu in CANON_GU
        if gu["drop_weight"] > 0 and gu["gu_rank"] in (enemy_gu_rank, max(1, enemy_gu_rank - 1))
    ]
    if not eligible:
        return None
    chosen = random.choices(eligible, weights=[gu["drop_weight"] for gu in eligible], k=1)[0]
    return equipment.gu_item_name(chosen["name"], "Common")
