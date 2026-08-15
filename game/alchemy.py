"""
/alchemy: craft a pill from herbs. Every (pill type, tier) combination needs herbs of that
same tier — the actual pill catalog and per-type effects live in items.py
(ALCHEMY_PILL_TYPES, alchemy_pill_name); this module just owns the recipe (herb cost) and,
as of the Alchemist rank gate below, which tiers a given rank can even attempt.
"""

from . import items

# 1 herb of the matching tier for most generic types; Pure Aptitude costs 2 since its effect
# is guaranteed and has no side effects, unlike the others. Essence Restoration is no longer
# craftable at all — moved to a rare bonus drop instead (see items.
# roll_essence_restoration_pill_drop), per explicit user request; this table simply no
# longer has an entry for it, so /alchemy stops offering it as a pill type to brew.
HERB_COST_PER_TYPE = {
    "Cultivation Boost": 1,
    "Qi Multiplier": 1,
    "Aptitude Enhancing": 1,
    "Pure Aptitude": 2,
    "Healing": 1,
}

MIN_TIER = 1
MAX_TIER = 8

# Alchemist rank index required to ATTEMPT each tier (0 == Novice, everyone) — same "early
# tier easy for everyone, higher tier needs levels" gate blacksmith.py's own
# TIER_RANK_REQUIRED already uses, and the same curve (tiers 1-2 open at rank 0, tier 7
# needs Grandmaster/index 5), so the two crafting professions stay in lockstep rather than
# inventing a second, different pace to learn. Separate from craft_success_chance, which
# still scales with rank on top of this gate once a tier is unlocked. Tier 8 (2026-08-14)
# needs Heavenly Master (index 6), mirroring blacksmith's own Tier 8 gate exactly.
TIER_RANK_REQUIRED = {1: 0, 2: 0, 3: 1, 4: 2, 5: 3, 6: 4, 7: 5, 8: 6}

# Tier 8 pills need real White Heaven rarities on top of the normal herb cost, not just a
# higher herb tier -- "Nine Heavens Lotus Petal"/"Cloud Sea Mist Vial" (content/materials_
# white_heaven.py) were purely inert flavor items until now. Empty for every other tier.
BONUS_INGREDIENTS_TIER_8 = {"Nine Heavens Lotus Petal": 3, "Cloud Sea Mist Vial": 3}


def rank_required_for_tier(tier: int) -> int:
    return TIER_RANK_REQUIRED.get(tier, 0)


def herb_cost(pill_type: str) -> int:
    return HERB_COST_PER_TYPE[pill_type]


def herb_name(tier: int) -> str:
    return f"Tier {tier} Herb"


def bonus_ingredients(tier: int) -> dict:
    """Extra ingredients a tier's recipe needs on top of the normal herb cost -- empty for
    every tier except 8 (see BONUS_INGREDIENTS_TIER_8). A real dict copy each call so a
    caller mutating the result (e.g. merging it into a bigger requirements dict) never
    mutates the shared module-level constant."""
    return dict(BONUS_INGREDIENTS_TIER_8) if tier == 8 else {}


def recipe_description(pill_type: str, tier: int) -> str:
    cost = herb_cost(pill_type)
    parts = [f"{cost}x {herb_name(tier)}"] + [f"{qty}x {mat}" for mat, qty in bonus_ingredients(tier).items()]
    return f"{' + '.join(parts)} → 1x {items.alchemy_pill_name(pill_type, tier)}"
