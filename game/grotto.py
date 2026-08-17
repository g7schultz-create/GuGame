"""
Grotto -- a personal cultivation sanctuary the player invests resources into for permanent
passive buffs (cultivation speed above all, plus alchemy/blacksmith success and profession
yield). Levels 1-7 use standard tiered materials (mirrors blacksmith.py's own Ore/Beast
Material/Beast Core cost shape, one tier per level); levels 8-10 additionally require White
Heaven's 3 named Beast Trophy materials on top of Tier 8 materials, mirroring blacksmith.py's
own Tier 8->9 "keeps costing the old stuff, adds new named ingredients on top" precedent
exactly (see blacksmith.TIER_9_RECIPE_EXTRA).

Named "Grotto," not "Blessed Land" -- /search_forgotten_blessed_land already ships as an
unrelated one-shot treasure-hunt discovery (its White Heaven variant is even titled "Hidden
Grotto-Heaven" in-embed), so reusing that name here would collide.

Pure logic -- no DB/GameManager/discord dependency, mirroring avatar.py's own split from
manager.py. Spirit stone cost is handled separately from the materials recipe (see
level_up_stones_cost) since spirit_stones is a player column, not an inventory item, spent via
GameDatabase.spend_spirit_stones rather than remove_item -- same split every other "recipe +
currency" cost in this codebase already uses.
"""

from typing import Dict, Optional

from . import blacksmith

# Realm gate: realms.GREAT_REALMS[1] == "Foundation Establishment" -- same idiom avatar.py's
# own AVATAR_MIN_GREAT_REALM_INDEX uses. A meaningful mid-game investment, not a Day-1 unlock.
GROTTO_MIN_GREAT_REALM_INDEX = 1


def is_realm_eligible(great_realm_index: int) -> bool:
    return great_realm_index >= GROTTO_MIN_GREAT_REALM_INDEX


GROTTO_MAX_BASE_LEVEL = 7   # standard tiered materials, one tier per level
GROTTO_MAX_LEVEL = 10       # levels 8-10 additionally need White Heaven's 3 named trophies

# Same tapering-growth shape as avatar.AVATAR_LEVEL_MULTIPLIER / blacksmith.TIER_PCT_BUDGET.
GROTTO_LEVEL_MULTIPLIER: Dict[int, float] = {
    1: 1.00, 2: 1.20, 3: 1.45, 4: 1.75, 5: 2.10,
    6: 2.50, 7: 2.95, 8: 3.45, 9: 4.00, 10: 4.60,
}

# Level-1 base magnitude for each bonus -- scaled by GROTTO_LEVEL_MULTIPLIER per level, so
# cultivation_speed_pct reaches ~4.60 * 0.08 = ~37% at Level 10 -- comfortably "a lot," and by
# design the single largest passive cultivation source in the game.
GROTTO_BASE_BONUSES: Dict[str, float] = {
    "cultivation_speed_pct": 0.08,
    "alchemy_success_pct": 0.02,
    "grotto_crafting_success_pct": 0.02,
    "grotto_yield_pct": 0.02,
}


def grotto_bonuses(level: int) -> Dict[str, float]:
    """A founded grotto's current bonus dict -- {} at level 0 (not yet founded)."""
    if level <= 0:
        return {}
    multiplier = GROTTO_LEVEL_MULTIPLIER.get(level, 1.0)
    return {key: value * multiplier for key, value in GROTTO_BASE_BONUSES.items()}


# White Heaven's own 3 real Tier 8+ "Beast Trophy" materials (see content/materials_white_
# heaven.py) -- confirmed the only such items in the game; Black Heaven has none of its own.
GROTTO_TROPHY_MATERIALS = ("Blinking Bird Feather", "Remnant Heavenly Dog Fang", "Cloud Beast Hide")

# Tapering-growth spirit stone cost for levels 1-7 (the base cap, no trophies needed) --
# same quadratic-ish escalation shape as most other meaningful sink costs in this codebase.
# Calibrated 2026-08-17 against TWO real live-player snapshots of the same player (Shion),
# 11 days apart, which is exactly why this is two constants instead of one uniform formula:
#
#   Snapshot 1 (stale, Spirit Severing, 619,362 stones): the original base=500 totaled only
#   192,500 across all 10 levels (31% of her stash, one-shottable) -- badly undersold "invest
#   LOTS of resources." Bumped to base=2000.
#
#   Snapshot 2 (live, Dao Seeking Peak, 1,904,072 stones, deep Tier 8 material surplus --
#   2500+ Beast Core, 1000+ Ore, 28-39 of every White Heaven trophy): base=2000's own level
#   1-7 total (280,000, 14.7% of her stash) still felt right for an accessible "base cap" any
#   engaged player can reach -- kept as-is. But the SAME base=2000 quadratic applied to levels
#   8-10 only reached 770,000 total (40% of her stash, and she could afford every material
#   requirement outright already), letting her fully max the grotto -- the single biggest
#   passive-bonus sink in the game -- for less than half her liquid stones. Levels 8-10 are
#   explicitly the "upgrade FURTHER" endgame tier (per the original request), so they get their
#   own steeper multiplier instead of continuing the same quadratic -- see
#   GROTTO_TROPHY_LEVEL_STONES_MULTIPLIER below.
GROTTO_LEVEL_STONES_BASE = 2000

# Levels 8-10 grow off Level 7's own cost by this multiplier per trophy step (1, 2, 3) instead
# of continuing the base quadratic -- pushes the full 1-10 total to 2,013,424 (106% of Shion's
# CURRENT 1,904,072 stones), correctly requiring real saving/earning to fully max out even for
# an already-wealthy, deep-endgame player, while leaving the base cap (levels 1-7) untouched.
GROTTO_TROPHY_LEVEL_STONES_MULTIPLIER = 2.2


def level_up_stones_cost(target_level: int) -> int:
    if target_level <= GROTTO_MAX_BASE_LEVEL:
        return GROTTO_LEVEL_STONES_BASE * target_level * target_level
    trophy_step = target_level - GROTTO_MAX_BASE_LEVEL  # 1, 2, 3
    level_7_cost = GROTTO_LEVEL_STONES_BASE * GROTTO_MAX_BASE_LEVEL * GROTTO_MAX_BASE_LEVEL
    return round(level_7_cost * GROTTO_TROPHY_LEVEL_STONES_MULTIPLIER ** trophy_step)


def level_up_recipe(current_level: int) -> Optional[Dict[str, int]]:
    """Material cost only (see level_up_stones_cost for the separate spirit-stone cost) --
    None once already at GROTTO_MAX_LEVEL, nothing left to invest toward. Keyed by the level
    being REACHED (1-10).

    Retuned 2026-08-17 against the same live Shion snapshot as the stone curve (see
    level_up_stones_cost's own comment) after the base multipliers left materials trivial at
    every level -- levels 1-7's old (4,3,2)*target totals were dwarfed by her Tier 1-7 stock,
    and even trophy_step=3's old cumulative (36 Tier 8 Ore / 24 Beast Material / 18 Beast Core
    / 12 of each trophy) barely dented her 1000+/2000+/2500+ Tier 8 basics or her 28-39 of each
    named trophy. Base tier (1-7) bumped modestly ((6,4,3)*target) so newer players still feel
    real per-level cost growth. The trophy tier (8-10) is where the real grind now lives: Tier
    8 basics scale up 5x (30/20/15 per trophy_step) -- still comfortably inside a whale's
    stockpile, since those are meant to gate players who JUST reached the endgame, not punish
    ones who over-farmed it -- but each named trophy now costs 8 * trophy_step (8/16/24,
    cumulative 48), which is deliberately MORE than Shion's own 28-39 owned of any single kind.
    Maxing the grotto now requires going back out and hunting White Heaven's 3 trophy mobs
    specifically, even for an already-invested player, rather than being covered outright by
    existing surplus.
    """
    target = current_level + 1
    if target > GROTTO_MAX_LEVEL:
        return None
    if target <= GROTTO_MAX_BASE_LEVEL:
        tier = target
        return {
            blacksmith.ore_name(tier): 6 * target,
            blacksmith.beast_material_name(tier): 4 * target,
            blacksmith.beast_core_name(tier): 3 * target,
        }
    # Levels 8-10: reuses Tier 8 Ore/Beast Material/Beast Core (same "keeps costing the old
    # stuff" shape as blacksmith.TIER_9_RECIPE_EXTRA), adding White Heaven's 3 named trophies
    # on top, scaled by how far past the base cap this level reaches (1, 2, 3).
    trophy_step = target - GROTTO_MAX_BASE_LEVEL
    recipe = {
        blacksmith.ore_name(8): 30 * trophy_step,
        blacksmith.beast_material_name(8): 20 * trophy_step,
        blacksmith.beast_core_name(8): 15 * trophy_step,
    }
    for trophy in GROTTO_TROPHY_MATERIALS:
        recipe[trophy] = 8 * trophy_step
    return recipe


# -- Ink Men (see GameManager.recruit_ink_man/assign_ink_man/check_and_complete_ink_men_work) --
# Passively work through a player's owned manual-page duplicates, one refinement-level-up per
# tick, by calling the EXISTING GameManager.refine_page on the player's behalf -- no new
# refinement logic, just automation of it.

GROTTO_MAX_INK_MEN = 3
INK_MAN_TICK_INTERVAL_SECONDS = 24 * 3600  # one refine attempt/real day, matches Gu Pet feeding's own cadence
INK_MAN_RECRUIT_STONES_BASE = 2000

# Manual Ink/Insight Dust -- the two manual currencies (player columns, spent via
# GameDatabase.spend_manual_ink/spend_insight_dust, same as spirit_stones -- NOT inventory
# items) -- fitting for an Ink Man, tapering cost per additional one already owned (0-indexed,
# the FIRST recruit uses already_owned=0).
INK_MAN_RECRUIT_INK_BASE = 40
INK_MAN_RECRUIT_DUST_BASE = 40


def ink_man_recruit_ink_cost(already_owned: int) -> int:
    return INK_MAN_RECRUIT_INK_BASE * (already_owned + 1)


def ink_man_recruit_dust_cost(already_owned: int) -> int:
    return INK_MAN_RECRUIT_DUST_BASE * (already_owned + 1)


def ink_man_recruit_stones_cost(already_owned: int) -> int:
    return INK_MAN_RECRUIT_STONES_BASE * (already_owned + 1)


# -- Hairy Men (see GameManager.recruit_hairy_man/assign_hairy_man/check_and_complete_hairy_
# men_work) -- passively bless ONE specific Legendary+ Gu instance over time.

GROTTO_MAX_HAIRY_MEN = 3
HAIRY_MAN_TICK_INTERVAL_SECONDS = 24 * 3600  # same daily cadence as Ink Men
HAIRY_MAN_RECRUIT_STONES_BASE = 3000

# Same two catalysts Gu Pet refinement and Avatar leveling already use -- Hairy Man's own
# established in-game lore is already Gu-refinement-flavored (see character_data.py's
# gu_refiner_success_pct/gu_refiner_failure_refund_pct passives).
SOUL_NOURISHING_PILL = "Soul Nourishing Pill"
SOUL_CRYSTAL = "Soul Crystal"


def hairy_man_recruit_recipe(already_owned: int) -> Dict[str, int]:
    step = already_owned + 1
    return {SOUL_NOURISHING_PILL: 6 * step, SOUL_CRYSTAL: 2 * step}


def hairy_man_recruit_stones_cost(already_owned: int) -> int:
    return HAIRY_MAN_RECRUIT_STONES_BASE * (already_owned + 1)


GU_LEGENDARY_PLUS_QUALITIES = ("Legendary", "Mythic", "Immortal")

# +2%/tick of the instance's own BASE stat_bonuses, capped at +40% total (20 ticks -- ~20 real
# days at one tick/day fully blesses a Gu, a meaningful but not endless investment).
GROTTO_BLESSING_PCT_PER_TICK = 0.02
GROTTO_BLESSING_MAX_TICKS = 20


def blessing_bonus_stat_bonuses(base_stat_bonuses: Dict[str, float], blessing_ticks: int) -> Dict[str, float]:
    """The ACCRUED extra on top of a Gu instance's base stat_bonuses at a given number of
    blessing ticks -- pure function of (base, ticks), so it can be recomputed fresh each tick
    rather than needing its own incremental-update logic."""
    ticks = max(0, min(blessing_ticks, GROTTO_BLESSING_MAX_TICKS))
    pct = GROTTO_BLESSING_PCT_PER_TICK * ticks
    return {key: value * pct for key, value in base_stat_bonuses.items()}
