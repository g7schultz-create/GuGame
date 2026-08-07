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
MAX_TIER = 7

# Alchemist rank index required to ATTEMPT each tier (0 == Novice, everyone) — same "early
# tier easy for everyone, higher tier needs levels" gate blacksmith.py's own
# TIER_RANK_REQUIRED already uses, and the same curve (tiers 1-2 open at rank 0, tier 7
# needs Grandmaster/index 5), so the two crafting professions stay in lockstep rather than
# inventing a second, different pace to learn. Separate from craft_success_chance, which
# still scales with rank on top of this gate once a tier is unlocked.
TIER_RANK_REQUIRED = {1: 0, 2: 0, 3: 1, 4: 2, 5: 3, 6: 4, 7: 5}


def rank_required_for_tier(tier: int) -> int:
    return TIER_RANK_REQUIRED.get(tier, 0)


def herb_cost(pill_type: str) -> int:
    return HERB_COST_PER_TYPE[pill_type]


def herb_name(tier: int) -> str:
    return f"Tier {tier} Herb"


def recipe_description(pill_type: str, tier: int) -> str:
    cost = herb_cost(pill_type)
    return f"{cost}x {herb_name(tier)} → 1x {items.alchemy_pill_name(pill_type, tier)}"
