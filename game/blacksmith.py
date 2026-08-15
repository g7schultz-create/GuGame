"""
/blacksmith: forge a weapon or armor piece from ore, beast material, and a beast core.
Every (gear type, tier) combination needs materials of that same tier — recipe() owns the
material cost. Since GameManager.craft_gear reworked what a successful forge actually
produces, this module also owns the two other pieces that make that possible:

  - TIER_RANK_REQUIRED: which Blacksmith profession rank (see professions.py) is needed to
    even ATTEMPT a given tier, so low tiers stay open to everyone and only the high tiers
    demand real investment — separate from craft_success_chance, which still scales with
    rank on top of this gate.
  - roll_gear_stats: the actual random stat roll for a freshly-forged piece.

PERCENTAGE-BASED, not flat (as of the realm-scaling rebalance) — a piece rolls +X% to a
random subset of STAT_KEYS rather than a flat +X. This exists because player stats compound
MULTIPLICATIVELY through realm breakthroughs (~7.6x per Great Realm — see realms.py's own
docstring: every breakthrough multiplies STR/HP/SPD/DEF/QI), while the old flat-bonus system
grew only arithmetically tier to tier. The two curves diverged so fast that a fully-geared
Tier 7 piece contributed well under 1% of a matching-realm character's total stats — gear
was meaningful at Tier 1-2 and cosmetic everywhere else. A percentage bonus sidesteps the
mismatch entirely: +15% STR is exactly as strong relatively whether the wearer's base STR is
12 or 2,000,000, so tier just needs to communicate "how good is this piece" on its own
terms, the same way manuals' cultivation_speed_pct already never had this problem. LCK is
deliberately excluded — realms.py's own docstring carves it out of the multiplicative curve
("LCK is fortune, not fighting power... untouched here"), so it was never the stat with a
scaling problem, and it keeps whatever small flat role it already had elsewhere.

Existing crafted_gear rows from before this change keep their old flat stat_bonuses forever
(retroactively reinterpreting someone's already-rolled "+40 STR" sword as "+40% STR" would
be an unpredictable, unrequested swing in their power) — see
GameManager.compute_equipment_bonuses / equipment.CRAFTED_GEAR_PCT_TO_FLAT for how both
flat-keyed (legacy) and pct-keyed (current) instances are told apart and applied correctly
side by side.

Each successful forge becomes its own row in the crafted_gear table (see database.py's
setup()) rather than a stack of an identical catalog item — GameManager assigns it a unique
gear_id there. equipment.py's static BLACKSMITH_GEAR_STATS/blacksmith_gear_name catalog
entries stick around only as the fixed-stat source for one-time migration of pre-rework
items (see database.py's setup()) and as a name-resolution fallback for old trade_offers
rows; nothing new is granted through them anymore.
"""

import random
from typing import Dict

# Flat per-craft cost, regardless of tier — only the TIER of each material required goes up.
ORE_COST = 2
BEAST_MATERIAL_COST = 1
BEAST_CORE_COST = 1

# Tier 8 (White Heaven materials only, see content/materials_white_heaven.py) deliberately
# costs MORE materials per craft, not just higher-tier ones — the flat cost above would make
# a Tier 8 piece feel as disposable as a Tier 1 one the moment a player has the Blacksmith
# rank for it, even though White Heaven's own drop economy is scarce and dangerous. A real
# per-piece investment, not a hard wall (Ore is deliberately the tightest of the three — see
# content/monsters/white_heaven.py's own drop chances — so it sets the real pace here).
TIER_8_ORE_COST = 6
TIER_8_BEAST_MATERIAL_COST = 4
TIER_8_BEAST_CORE_COST = 3

# Tier 9 (2026-08-14, "quasi 8.5") -- explicitly NOT another generic Tier-N-Ore/Material/Core
# rung (no "Tier 9 Ore" item exists, and none is being added) -- instead a distinct recipe
# built entirely from White Heaven's own named trophy/essence materials (content/materials_
# white_heaven.py) plus Primeval Essence Crystal, PLUS the same Tier 8 Ore/Material/Core costs
# reused on top (per explicit request: "using all of the materials below[,] essence crystals[,]
# and the materials already required to forge t8 gear"). A real step past Tier 8, not a
# reskin of it.
TIER_9_RECIPE_EXTRA = {
    "Blinking Bird Feather": 3, "Cloud Beast Hide": 3, "Remnant Heavenly Dog Fang": 3,
    "Aurora-Veined Shard": 5, "White Heaven Floating Dust": 5, "Primeval Essence Crystal": 50,
}

MIN_TIER = 1
MAX_TIER = 9

# The 6 stats a crafted piece's percentage budget can land in — every stat realm
# breakthroughs actually scale (see realms.py), swapping out LCK (which they don't) for
# SPD (which they do, but which the old flat-stat catalog never actually offered).
STAT_KEYS = ["str_pct", "atk_pct", "def_pct", "spd_pct", "hp_pct", "qi_pct"]

# Total percentage points (e.g. 20 == 20%) a piece spends across 2-4 of STAT_KEYS. Unlike
# the old flat TIER_POWER_BUDGET, this doesn't need to chase the realm curve at all — a
# percentage is already realm-relative — so tiers just need to feel like a steady quality
# climb. A piece dumping its whole budget into one stat is a genuinely great single-stat
# roll; split across 3-4 stats (the common case) it's a handful of double-digit percents.
TIER_PCT_BUDGET = {1: 8, 2: 14, 3: 20, 4: 28, 5: 37, 6: 47, 7: 60, 8: 76, 9: 95}

# Blacksmith rank index required to ATTEMPT each tier (0 == Novice, everyone). "Early tier
# easy for everyone, higher tier needs levels" — tiers 1-2 are open at rank 0, tier 7 needs
# Grandmaster (index 5). Tier 8 (White Heaven materials only, see content/materials_white_
# heaven.py) needs Heavenly Master (index 6) — real headroom professions.RANKS already had,
# nothing used it until now. Tier 9 claims the LAST remaining headroom, Dao Master (index 7)
# — professions.RANKS/SUCCESS_CHANCE_PER_RANK already had an entry for it, unused until now.
TIER_RANK_REQUIRED = {1: 0, 2: 0, 3: 1, 4: 2, 5: 3, 6: 4, 7: 5, 8: 6, 9: 7}

MIN_STATS_ROLLED = 2
MAX_STATS_ROLLED = 4


def ore_name(tier: int) -> str:
    return f"Tier {tier} Ore"


def beast_material_name(tier: int) -> str:
    return f"Tier {tier} Beast Material"


def beast_core_name(tier: int) -> str:
    return f"Tier {tier} Beast Core"


def recipe(tier: int) -> dict:
    """{item_name: quantity} needed to craft any gear type at this tier. Explicit per-tier
    dispatch (tier == 8 / tier == 9), NOT "tier >= MAX_TIER" -- that shortcut broke the moment
    Tier 9 was added above Tier 8, since Tier 8 needed to keep its own real recipe rather than
    silently reverting to the generic 1-7 formula."""
    if tier == 9:
        return {
            ore_name(8): TIER_8_ORE_COST, beast_material_name(8): TIER_8_BEAST_MATERIAL_COST,
            beast_core_name(8): TIER_8_BEAST_CORE_COST, **TIER_9_RECIPE_EXTRA,
        }
    if tier == 8:
        return {
            ore_name(tier): TIER_8_ORE_COST,
            beast_material_name(tier): TIER_8_BEAST_MATERIAL_COST,
            beast_core_name(tier): TIER_8_BEAST_CORE_COST,
        }
    return {
        ore_name(tier): ORE_COST,
        beast_material_name(tier): BEAST_MATERIAL_COST,
        beast_core_name(tier): BEAST_CORE_COST,
    }


def dismantle_yield(tier: int) -> dict:
    """Partial materials back for scrapping a crafted piece nobody wants — always exactly 1
    of each material at the piece's own tier. recipe()'s material COUNTS never scale with
    tier (only the materials' own tier does), so a flat "1 back" is already a consistent
    partial refund at every tier without needing its own scaling table. Tier 9 has no generic
    "Tier 9 Ore/Material/Core" item at all (see recipe()'s own tier==9 branch) -- would
    otherwise hand back nonexistent items -- so it returns 1 of each REAL ingredient its own
    recipe actually uses instead."""
    if tier == 9:
        return {name: 1 for name in recipe(9)}
    return {
        ore_name(tier): 1,
        beast_material_name(tier): 1,
        beast_core_name(tier): 1,
    }


# Spirit stones also recovered on dismantle, on top of the materials above -- tier-scaled so
# scrapping a Tier 7 piece is meaningfully better than a Tier 1 one, same convention every
# other tiered reward in this game already follows.
DISMANTLE_STONES_PER_TIER = 30


def dismantle_stones(tier: int) -> int:
    return DISMANTLE_STONES_PER_TIER * tier


def rank_required_for_tier(tier: int) -> int:
    return TIER_RANK_REQUIRED.get(tier, 0)


def crafted_gear_display_name(base_type: str, tier: int, gear_id: int) -> str:
    return f"{base_type} (T{tier}) #{gear_id}"


def roll_gear_stats(tier: int, rng: random.Random, budget_bonus_pct: float = 0.0) -> Dict[str, float]:
    """Spends this tier's percentage budget across a random 2-4 of STAT_KEYS. Landing on a
    random subset rather than spreading across all 6 every time keeps a low-tier piece from
    being diluted into a bunch of +1%s, and gives each roll a couple of standout stats
    instead of a flat, samey spread. Values are fractions (0.08 == +8%), matching every
    other percentage stat_bonus already in this codebase (cultivation_speed_pct etc).

    budget_bonus_pct is a Refinement-family root's own gear_budget_bonus_pct (see
    character_data.CharacterTraitSpec, e.g. Long Hair Ancestor Root) — a relative boost to
    the tier's whole budget rather than a flat add, so it scales the same way percentage
    systems already do across every tier instead of needing separate flat tuning per tier
    (mirrors why crafted gear itself moved to percentages in the first place — see this
    module's own docstring).
    """
    budget = TIER_PCT_BUDGET[tier] * (1 + budget_bonus_pct)
    count = rng.randint(MIN_STATS_ROLLED, MAX_STATS_ROLLED)
    chosen = rng.sample(STAT_KEYS, count)

    # Random cut points split the budget unevenly across the chosen stats (a dominant stat
    # or two plus a couple of minor ones) rather than always dividing it dead evenly.
    cuts = sorted(rng.uniform(0, budget) for _ in range(count - 1))
    bounds = [0.0] + cuts + [budget]
    shares = [bounds[i + 1] - bounds[i] for i in range(count)]

    # Floored at 0.1% — an unlucky cut can otherwise squeeze a chosen stat's share down to a
    # sliver that rounds to a dead, cosmetically-broken "+0.0%" entry.
    return {stat: max(0.1, round(share, 1)) / 100 for stat, share in zip(chosen, shares)}
