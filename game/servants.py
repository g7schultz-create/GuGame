"""
Servants -- a Reverend-Insanity-inspired gacha/collection system (see /servant, /view_servant
in cog.py). T1-T5 are generic
cultivator archetypes (e.g. "Qi Condensation Gu Apprentice"); T6-T7 are specific named characters (e.g.
"Fang Yuan") drawn loosely from the reference doc's own cast -- exact names/flavor are a
placeholder roster, meant to be confirmed/replaced later, not final art-of-record.

Pure data/logic, no DB/GameManager/discord dependency -- same split as grotto.py/world_boss.py.

Deliberately does NOT reuse chargen.py's SCARCE_TIER_NAMES/_unique_pool single-holder-per-name
scarcity model. That model removes a claimed name from the roll pool for EVERYONE (including
its own holder) the moment it's first claimed, which would make it impossible to ever roll a
duplicate of a named T6/T7 servant again -- directly breaking the star-up system, which needs
duplicates at every tier, T6/T7 included. Every name here is always re-rollable by anyone, any
number of times; T6/T7 are simply rare via TIER_WEIGHTS (and, within T7, via within_tier_weight
-- Fang Yuan is deliberately the rarest name IN T7, not just gated by T7's own 0.1% tier odds).
"""

import random
from dataclasses import dataclass
from typing import Dict, List, Optional

from . import avatar, equipment

# One distinct color-circle emoji per tier, for at-a-glance scanning in the Roster/Star Up/
# Equip/Automation selects and embeds -- T1 (common) through T7 (rarest).
TIER_EMOJI: Dict[int, str] = {1: "⚪", 2: "🟢", 3: "🔵", 4: "🟣", 5: "🟠", 6: "🔴", 7: "⚫"}


def tier_label(tier: int) -> str:
    return f"{TIER_EMOJI.get(tier, '')} T{tier}"


@dataclass
class Servant:
    name: str
    tier: int
    role_flavor: str
    description: str
    base_stats: Dict[str, float]
    support_bonus_key: str
    within_tier_weight: int
    image_url: Optional[str] = None  # left None throughout -- filled in later by hand


# Level-1 (★1) foundation-stat PERCENTAGE budget per tier -- a flat stat bonus goes stale at
# high realms (a maxed T7's flat +245 QI is noise against a Spirit Severing+ player's real qi_
# stat), so Combat/Support stat bonuses are expressed as a % of the player's OWN stat instead,
# the exact mechanism Gu items already use for this same reason (see equipment.py's
# CRAFTED_GEAR_PCT_TO_FLAT / foundation_stats_to_pct docstring -- "instead of flat stats
# specifically so it can't be outgrown"). Scaled by STAR_STAT_MULTIPLIER/LEVEL_STAT_MULTIPLIER/
# affinity_multiplier per instance (see scaled_stat_bonuses) -- up to ~8x at full investment,
# so a maxed T7 reaches ~44% total (0.055 * 8.0), a maxed T1 reaches ~4% (0.005 * 8.0).
TIER_STAT_BUDGET_PCT: Dict[int, float] = {1: 0.005, 2: 0.008, 3: 0.012, 4: 0.018, 5: 0.026, 6: 0.038, 7: 0.055}


def _stats(primary: str, secondary: Optional[str] = None) -> Dict[str, float]:
    """A servant's fixed 70/30 relative weight between its two stats -- NOT a magnitude by
    itself. The real percentage comes from TIER_STAT_BUDGET_PCT * star/level/affinity,
    converted via equipment.foundation_stats_to_pct at read time (see scaled_stat_bonuses),
    which also re-weights by GEAR_POWER_WEIGHTS so e.g. a flat "hp" weight and a "def_stat"
    weight don't come out equally strong just because they were split 70/30 here."""
    if secondary:
        return {primary: 0.7, secondary: 0.3}
    return {primary: 1.0}


SERVANT_CATALOG: Dict[str, Servant] = {}


def _register(*rows: Servant):
    for row in rows:
        SERVANT_CATALOG[row.name] = row


# -- Tier 1-5: generic cultivator archetypes -------------------------------------------------

_register(
    Servant("Fog Valley Disciple", 1, "Outer Sect Disciple", "A minor disciple from a fog-shrouded valley sect, still finding their Dao.", _stats("qi_stat", "luck_stat"), "cultivation_speed_pct", 30, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629599/Fog%20Valley%20Disciple.png"),
    Servant("Green Bull Clan Warrior", 1, "Clan Warrior", "A young warrior of the Green Bull Clan, blooded in border skirmishes.", _stats("str_stat", "atk_stat"), "stone_reward_bonus_pct", 30, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629623/Green%20Bull%20Clan%20Warrior.png"),
    Servant("Wild Root Scavenger", 1, "Wilderness Scavenger", "Survives on the fringes of civilization, foraging rare roots and herbs.", _stats("spd_stat", "luck_stat"), "loot_chance_bonus_pct", 25, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629633/Wild%20Root%20Scavenger.png"),
    Servant("Qi Condensation Gu Apprentice", 1, "Gu Apprentice", "A cultivator at the Qi Condensation realm, only just beginning to sense the Gu world's true scale.", _stats("hp", "qi_stat"), "essence_regen_pct", 25, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629645/Qi%20Condensation%20Gu%20Apprentice.png"),

    Servant("Rank Three Sect Elder", 2, "Sect Elder", "An elder of a minor sect, steady and well-versed in Gu lore.", _stats("def_stat", "hp"), "mining_yield_pct", 25, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629657/Rank%20Three%20Sect%20Elder.png"),
    Servant("Beast-Blood Warrior", 2, "Beast-Blood Warrior", "Has refined a beast-blood Gu into their own body, gaining ferocious strength.", _stats("atk_stat", "str_stat"), "herb_yield_pct", 25, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629668/Beast-Blood%20Warrior.png"),
    Servant("Foundation Establishment Gu Master", 2, "Gu Master", "A Gu Master at the Foundation Establishment realm, commanding a modest collection of refined Gu.", _stats("qi_stat", "atk_stat"), "cultivation_speed_pct", 20, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629679/Foundation%20Establishment%20Gu%20Master.png"),
    Servant("Iron Fist Ancestor", 2, "Clan Ancestor", "A retired clan champion, fists still capable of shattering stone.", _stats("str_stat", "def_stat"), "stone_reward_bonus_pct", 20, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629709/Iron%20Fist%20Ancestor.png"),

    Servant("Rank Four Sect Master", 3, "Sect Master", "Leads a mid-sized sect, balancing politics and cultivation.", _stats("hp", "def_stat"), "loot_chance_bonus_pct", 20, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629725/Rank%20Four%20Sect%20Master.png"),
    Servant("Core Formation Gu Immortal", 3, "Gu Immortal", "A Gu Immortal at the Core Formation realm, their Dao Marks beginning to stabilize.", _stats("qi_stat", "luck_stat"), "essence_regen_pct", 20, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629736/Core%20Formation%20Gu%20Immortal.png"),
    Servant("Blood Sea Vanguard", 3, "Blood Sea Vanguard", "A vanguard fighter of the Blood Sea faction, fast and merciless.", _stats("atk_stat", "spd_stat"), "mining_yield_pct", 15, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629747/Blood%20Sea%20Vanguard.png"),
    Servant("Pseudo Nascent Soul Ancestor", 3, "Clan Ancestor", "An ancestor whose foundation has only just stabilized at the threshold of Nascent Soul.", _stats("def_stat", "qi_stat"), "herb_yield_pct", 15, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787631409/8c4ae36e-4024-4156-91ea-997f025c06fd.png"),

    Servant("Rank Five Small Clan Ancestor", 4, "Clan Ancestor", "The pillar of a small clan, their strength a matter of local legend.", _stats("hp", "str_stat"), "cultivation_speed_pct", 15, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629780/Rank%20Five%20Small%20Clan%20Ancestor.png"),
    Servant("Nascent Soul Gu Immortal", 4, "Gu Immortal", "A Gu Immortal at the Nascent Soul realm, wielding a well-rounded Gu collection.", _stats("qi_stat", "atk_stat"), "stone_reward_bonus_pct", 15, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629806/Nascent%20Soul%20Gu%20Immortal.png"),
    Servant("Frost Sect Elder Ancestor", 4, "Sect Elder Ancestor", "An elder ancestor of a frost-aligned sect, cold and unshakeable.", _stats("def_stat", "spd_stat"), "loot_chance_bonus_pct", 10, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629820/Frost%20Sect%20Elder%20Ancestor.png"),

    Servant("Rank Five Great Clan Ancestor", 5, "Great Clan Ancestor", "The founding pillar of a great clan, revered across the region.", _stats("hp", "def_stat"), "essence_regen_pct", 10, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629832/Rank%20Five%20Great%20Clan%20Ancestor.png"),
    Servant("Spirit Severing Gu Immortal", 5, "Gu Immortal", "A Gu Immortal at the Spirit Severing realm, their Dao Marks nearly complete.", _stats("qi_stat", "str_stat"), "mining_yield_pct", 10, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629843/Spirit%20Severing%20Gu%20Immortal.png"),
    Servant("True Ancestor of a Thousand Gu", 5, "True Ancestor", "Has refined a thousand Gu across their long, storied life.", _stats("atk_stat", "luck_stat"), "herb_yield_pct", 6, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629851/True%20Ancestor%20of%20a%20Thousand%20Gu.png"),
)

# -- Tier 6-7: specific named characters -- PLACEHOLDER roster, confirm final names/spelling
# against the user's own reference doc before treating this as final. within_tier_weight is
# deliberately steep at the top of T7 -- Fang Yuan's 8/100 share of T7 pulls (8%) makes him
# roughly 0.1% * 8% = 0.008% of ALL summons, meaningfully rarer than a common T6 name. ---------

_register(
    Servant("Weeping Blood Trench Ancestor", 6, "Trench Ancestor", "A fearsome ancestor of the Weeping Blood Trench, wreathed in old grudges.", _stats("hp", "atk_stat"), "cultivation_speed_pct", 26, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629860/Weeping%20Blood%20Trench%20Ancestor.png"),
    Servant("Gu Yue Qing Shu", 6, "Gu Immortal Elder", "A brilliant, calculating Gu Immortal Elder, rarely caught off guard.", _stats("qi_stat", "luck_stat"), "cultivation_speed_pct", 24, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629904/Gu%20Yue%20Qing%20Shu.png"),
    Servant("Nine Distortion Wolf Ancestor", 6, "Wolf Clan Ancestor", "Leader of the Nine Distortion Wolf pack, blindingly fast in a hunt.", _stats("spd_stat", "atk_stat"), "stone_reward_bonus_pct", 20, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629869/Nine%20Distortion%20Wolf%20Ancestor.png"),
    Servant("Meng Hu", 6, "Wolf King", "The Wolf King, brash and overwhelmingly powerful in a straight fight.", _stats("str_stat", "atk_stat"), "loot_chance_bonus_pct", 16, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629877/Meng%20Hu.png"),
    Servant("Chi You Furnace Ancestor", 6, "Furnace Ancestor", "Wields a body tempered like a furnace, radiating battle intent.", _stats("atk_stat", "hp"), "cultivation_speed_pct", 14, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629896/Chi%20You%20Furnace%20Ancestor.png"),

    Servant("Wu Yong", 7, "Scheme Immortal", "A master of long cons and longer memories, always several moves ahead.", _stats("luck_stat", "qi_stat"), "loot_chance_bonus_pct", 38, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629912/Wu%20Yong.png"),
    Servant("Bai Ning Bing", 7, "Frost Immortal", "An icy, calculating Gu Immortal, feared for her patience as much as her power.", _stats("qi_stat", "def_stat"), "essence_regen_pct", 32, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787754305/file_000000002d6881fb88e8e60e08fe3927.webp"),
    Servant("Hei Lou Lan", 7, "Gu Immortal Elder", "A reserved, unshakeable Gu Immortal Elder, said to have weathered calamities that broke lesser cultivators.", _stats("hp", "def_stat"), "mining_yield_pct", 22, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629935/Hei%20Lou%20Lan.png"),
    Servant("Fang Yuan", 7, "Grand Supreme Elder Gu Immortal", "The rarest of the rare -- a Gu Immortal whose foresight spans centuries.", _stats("qi_stat", "atk_stat"), "stone_reward_bonus_pct", 8, image_url="https://res.cloudinary.com/iacgiql3/image/upload/v1787629923/Fang%20Yuan.png"),
)


SERVANTS_BY_TIER: Dict[int, List[str]] = {}
for _servant in SERVANT_CATALOG.values():
    SERVANTS_BY_TIER.setdefault(_servant.tier, []).append(_servant.name)
del _servant


# -- Summon roll -- reuses world_boss.py's exact weighted-roll shape (random.choices over a
# fixed [(name, weight)] list) for both the tier roll and the within-tier name roll. -----------

TIER_WEIGHTS: Dict[int, float] = {1: 36.9, 2: 26, 3: 18, 4: 12, 5: 6, 6: 1, 7: 0.1}


def roll_tier(rng: Optional[random.Random] = None) -> int:
    r = rng or random
    tiers = list(TIER_WEIGHTS.keys())
    weights = list(TIER_WEIGHTS.values())
    return r.choices(tiers, weights=weights, k=1)[0]


def roll_named_servant(tier: int, rng: Optional[random.Random] = None) -> str:
    """Used by BOTH the main summon roll and evolution (a maxed servant rolling its new
    T6/T7 identity) -- same weighted roll, just fixed to a specific tier."""
    names = SERVANTS_BY_TIER[tier]
    weights = [SERVANT_CATALOG[n].within_tier_weight for n in names]
    return (rng or random).choices(names, weights=weights, k=1)[0]


def roll_servant(rng: Optional[random.Random] = None) -> str:
    return roll_named_servant(roll_tier(rng), rng)


# -- Summon currencies -- Spirit Stones is primary; the other two are ALTERNATIVES, not a
# simultaneous multi-currency requirement (see GameManager.summon_servant). Essence Pills/Manual
# Pages were dropped as summon currencies per explicit request (kept as valid Level-up-adjacent
# ideas, but not this) -- Beast Cores took their place instead. -----------------------------------

CURRENCY_STONES = "stones"
CURRENCY_ESSENCE_CRYSTALS = "essence_crystals"
CURRENCY_BEAST_CORES = "beast_cores"
SUMMON_CURRENCIES = (CURRENCY_STONES, CURRENCY_ESSENCE_CRYSTALS, CURRENCY_BEAST_CORES)

# Retuned 2026-08-24, explicit request: 10,000 stones / 10 essence crystals / 10 beast cores --
# a deliberate step down from the earlier 100,000/1,000/20 leaderboard-calibrated pass, meant to
# make pulls come more often rather than stay a rare whale-only event.
SUMMON_COST_STONES = 10_000
SUMMON_COST_ESSENCE_CRYSTALS = 10   # "Primeval Essence Crystal" -- flat untiered Materials item
SUMMON_COST_BEAST_CORES = 10        # "Tier {N} Beast Core", any tier, spent lowest-tier-first

SUMMON_CURRENCY_COST = {
    CURRENCY_STONES: SUMMON_COST_STONES,
    CURRENCY_ESSENCE_CRYSTALS: SUMMON_COST_ESSENCE_CRYSTALS,
    CURRENCY_BEAST_CORES: SUMMON_COST_BEAST_CORES,
}

PRIMEVAL_ESSENCE_CRYSTAL = "Primeval Essence Crystal"


# -- Star-up (within a tier, ★1->★7) -- adapts equipment.GU_UPGRADE_DUPLICATES_REQUIRED's shape
# but floors at 1 instead of 2, since star-up KEEPS the leveling instance and only consumes
# EXTRA copies as pure fuel (unlike Gu fusion, which destroys both copies to make a new one). --

MAX_STAR_LEVEL = 7
STAR_UP_DUPLICATES_REQUIRED: Dict[int, int] = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3}  # keyed by CURRENT star level
STAR_STAT_MULTIPLIER: Dict[int, float] = {1: 1.00, 2: 1.15, 3: 1.30, 4: 1.50, 5: 1.75, 6: 2.00, 7: 2.30}


# -- Level -- a SEPARATE progression axis from Star: fed with materials/resources (see below)
# rather than duplicate copies, so it advances even a lone, dupe-less copy of a servant. Reuses
# avatar.py's own 1-10 ladder/multiplier curve directly ("feed the avatar level up material"
# per explicit request), scaled by the servant's tier.

SERVANT_MAX_LEVEL = avatar.AVATAR_MAX_LEVEL  # 10, same ladder as Nascent Soul Avatar
LEVEL_STAT_MULTIPLIER = avatar.AVATAR_LEVEL_MULTIPLIER  # same tapering-growth curve, reused directly

SOUL_NOURISHING_PILL = avatar.SOUL_NOURISHING_PILL
SOUL_CRYSTAL = avatar.SOUL_CRYSTAL
LEVEL_UP_STONES_BASE = 3000  # per (tier * target level) step -- mirrors Grotto's Hairy Man dual pill+crystal+stones cost shape


def level_up_recipe(tier: int, current_level: int) -> Optional[Dict[str, int]]:
    """Soul Nourishing Pill / Soul Crystal cost to reach current_level+1 -- avatar.py's own
    recipe shape, scaled up by this servant's tier (a T7 costs 7x what a T1 does at the same
    level). None once already at SERVANT_MAX_LEVEL."""
    base_recipe = avatar.level_up_recipe(current_level)
    if base_recipe is None:
        return None
    return {item: qty * tier for item, qty in base_recipe.items()}


def level_up_stones_cost(tier: int, current_level: int) -> int:
    return LEVEL_UP_STONES_BASE * tier * (current_level + 1)


# -- Affinity -- grows passively the longer a servant stays EQUIPPED (Support or Combat),
# tracked as accumulated real seconds (servant_instances.affinity_seconds), lazily settled --
# see GameManager.equip_servant/unequip_servant and servants.current_affinity_seconds. Persists
# through star-ups automatically (same instance row) and is explicitly carried forward through
# evolution (see GameManager.evolve_servant) -- an accrued bond/investment, not tied to the
# servant's raw star/tier identity.

AFFINITY_CAP_SECONDS = 30 * 24 * 3600  # 30 real days equipped to reach max affinity
AFFINITY_MAX_BONUS_PCT = 0.20          # +20% multiplier on top of star/level at full affinity


def affinity_multiplier(affinity_seconds: int) -> float:
    ratio = min(1.0, max(0, affinity_seconds) / AFFINITY_CAP_SECONDS)
    return 1.0 + AFFINITY_MAX_BONUS_PCT * ratio


def current_affinity_seconds(instance: dict, now: int) -> int:
    """Lazy settlement, same shape as gu_pet's own satiety calc -- affinity_seconds is only
    ever a snapshot; while equipped_since_ts is set (the servant is CURRENTLY slotted), the
    live total also includes time elapsed since that snapshot."""
    equipped_since = instance.get("affinity_equipped_since_ts")
    base = instance.get("affinity_seconds", 0) or 0
    if not equipped_since:
        return base
    return base + max(0, now - equipped_since)


# luck_stat has no _pct equivalent anywhere in this codebase (equipment.CRAFTED_GEAR_PCT_TO_FLAT
# doesn't cover it -- same gap Gu items already have), so foundation_stats_to_pct would pass it
# straight through UNCHANGED, freezing it at its raw catalog weight forever instead of scaling
# with tier/star/level/affinity like every other stat. Scaled here as a flat number instead,
# using the same budget/mult stack everything else uses so it still grows with investment --
# tuned so a fully-invested (★7/Lv10/max affinity) T7 servant with luck as its PRIMARY stat
# lands in the low hundreds.
LUCK_FLAT_SCALE = 1000


def scaled_stat_bonuses(servant: Servant, star_level: int, level: int = 1, affinity_seconds: int = 0) -> Dict[str, float]:
    """Returns stat_bonuses-shaped PERCENTAGES (str_pct/atk_pct/hp_pct/spd_pct/def_pct/qi_pct --
    see equipment.CRAFTED_GEAR_PCT_TO_FLAT) for every stat except luck_stat (see
    LUCK_FLAT_SCALE), not flat numbers -- compute_equipment_bonuses' existing crafted_pct_totals
    resolution (the same one Gu/blacksmith % stats already go through) converts these into a
    real flat delta against the player's OWN base stat at read time, so this stays meaningful at
    every realm instead of going stale like a flat bonus would.

    servant.base_stats' weights (0.7/0.3, see _stats) are pre-divided by each stat's own
    equipment.GEAR_POWER_WEIGHTS entry before being handed to foundation_stats_to_pct, which
    multiplies by that SAME weight again internally -- without this, a servant pairing a
    "cheap" stat (hp/qi_stat, weight 0.1) as primary against an "expensive" one (str/atk/def/
    spd, weight 1.0) as secondary would have the split silently INVERT (the cheap stat's 0.1x
    reweight makes it lose to the expensive stat's 0.3 share even at 0.7 nominal weight) --
    this cancels that out so the catalog's declared 70/30 emphasis always holds exactly,
    regardless of which two stats a given servant happens to pair."""
    mult = STAR_STAT_MULTIPLIER[star_level] * LEVEL_STAT_MULTIPLIER.get(level, 1.0) * affinity_multiplier(affinity_seconds)
    budget = TIER_STAT_BUDGET_PCT[servant.tier] * mult

    result: Dict[str, float] = {}
    pct_input: Dict[str, float] = {}
    for stat, weight in servant.base_stats.items():
        if stat == "luck_stat":
            result["luck_stat"] = round(weight * budget * LUCK_FLAT_SCALE, 1)
        else:
            gear_weight = equipment.GEAR_POWER_WEIGHTS.get(stat, 1.0) or 1.0
            pct_input[stat] = weight / gear_weight
    if pct_input:
        pct_weight_sum = sum(w for stat, w in servant.base_stats.items() if stat != "luck_stat")
        result.update(equipment.foundation_stats_to_pct(pct_input, budget * pct_weight_sum))
    return result


# Support slot's own themed utility % -- scales with tier (bigger at T6/T7), star level, servant
# level, and affinity.
SUPPORT_BASE_PCT: Dict[int, float] = {1: 0.010, 2: 0.015, 3: 0.020, 4: 0.030, 5: 0.040, 6: 0.055, 7: 0.075}


def support_special_pct(servant: Servant, star_level: int, level: int = 1, affinity_seconds: int = 0) -> float:
    return (
        SUPPORT_BASE_PCT[servant.tier]
        * STAR_STAT_MULTIPLIER[star_level]
        * LEVEL_STAT_MULTIPLIER.get(level, 1.0)
        * affinity_multiplier(affinity_seconds)
    )


# support_bonus_key values that are NOT part of GameManager.SPECIAL_BONUS_KEYS -- mine/gather/
# farm never read that generic pool (see GameManager._grotto_yield_bonus's own comment), so a
# Support servant flavored around gathering needs its own direct-wired read instead
# (GameManager._servant_yield_bonus) rather than riding compute_equipment_bonuses.
YIELD_BONUS_KEYS = ("mining_yield_pct", "herb_yield_pct")

# support_bonus_key values that must be EXCLUDED from compute_equipment_bonuses' generic
# special pool entirely (not just left unread) -- cultivation_speed_pct is folded into
# database.py's _qi_rate_components instead (the REAL qi-rate hook; the generic pool is
# display-only and gets wholesale OVERWRITTEN by qi_status["manual_bonus"] later in that same
# function, so leaving it in the per-slot loop would be silently discarded dead weight, not a
# double-count -- see that function's own comment trail, which this exact trap has already hit
# for avatar gear/soul, Gu Pet, and Grotto).
SUPPORT_KEYS_OUTSIDE_GENERIC_POOL = YIELD_BONUS_KEYS + ("cultivation_speed_pct",)


# -- Evolution -- a maxed (★7) servant at any tier below the top one can evolve into a freshly-
# rolled next-tier named servant (a full identity swap, not a fixed mapping -- see
# roll_named_servant above). Every tier 1-6 is evolvable; only Tier 7 (the top of TIER_WEIGHTS)
# has nowhere higher to go. --------------------------------------------------------------------

EVOLVABLE_TIERS = (1, 2, 3, 4, 5, 6)


def can_evolve(tier: int, star_level: int) -> bool:
    return tier in EVOLVABLE_TIERS and star_level >= MAX_STAR_LEVEL


# -- Collection bonus -- a passive % just for owning distinct servants beyond your 2 equipped
# slots, per distinct NAME owned (duplicate/star-up-fuel copies of the same name don't count
# twice -- see GameDatabase.count_distinct_servant_names). ---------------------------------------

COLLECTION_BONUS_PCT_PER_UNIQUE = 0.005
COLLECTION_BONUS_CAP_PCT = 0.25  # caps at 50 distinct names owned


def collection_bonus_pct(distinct_names_owned: int) -> float:
    return min(distinct_names_owned * COLLECTION_BONUS_PCT_PER_UNIQUE, COLLECTION_BONUS_CAP_PCT)


# -- Support / Combat equip slots -- new slot_key values on the existing `equipped` table, NOT
# added to equipment.SLOTS (that list drives the generic gear-equip picker; Servant slots get
# their own dedicated UI in servant_view.py instead). --------------------------------------------

SLOT_KEY_SUPPORT = "servant_support"
SLOT_KEY_COMBAT = "servant_combat"
SERVANT_SLOT_KEYS = (SLOT_KEY_SUPPORT, SLOT_KEY_COMBAT)

# Support slot trades half its scaled base_stats for its support_bonus_key at full value --
# Combat slot is a pure stat stick at full scaled base_stats.
SUPPORT_STAT_FRACTION = 0.5


# -- Automation -- a servant IS both the identity and the worker at once (unlike Grotto's Ink/
# Hairy Men, which are separately-recruited units); automation_duty/automation_next_tick_ts live
# directly on the servant_instances row. See GameManager.assign_servant_duty/check_and_
# complete_servant_automation. ---------------------------------------------------------------

DUTY_MINE = "mine"
DUTY_GATHER = "gather"
DUTY_FARM = "farm"
AUTOMATION_DUTIES = (DUTY_MINE, DUTY_GATHER, DUTY_FARM)

MAX_AUTOMATION_SERVANTS = 3                        # mirrors grotto.GROTTO_MAX_INK_MEN's cap shape
AUTOMATION_TICK_INTERVAL_SECONDS = 24 * 3600        # one cycle/real day, same cadence as Ink/Hairy Men

# Automation YIELD scaling -- higher tier/star/level/affinity means a meaningfully BETTER
# automated worker, not just eligibility to work at all (see GameManager.check_and_complete_
# servant_automation). Same STAR_STAT_MULTIPLIER/LEVEL_STAT_MULTIPLIER/affinity_multiplier
# compounding stack as scaled_stat_bonuses/support_special_pct (up to ~8x at ★7/Lv10/max
# affinity), applied on top of a per-tier base -- a fully-invested T7 roughly DOUBLES yield;
# a fully-invested T1 tops out around +12%, since a T1 just isn't built for it no matter how
# much is invested in that one copy.
AUTOMATION_BASE_YIELD_PCT: Dict[int, float] = {1: 0.015, 2: 0.025, 3: 0.04, 4: 0.06, 5: 0.085, 6: 0.11, 7: 0.125}


def automation_yield_bonus_pct(servant: Servant, star_level: int, level: int = 1, affinity_seconds: int = 0) -> float:
    mult = STAR_STAT_MULTIPLIER[star_level] * LEVEL_STAT_MULTIPLIER.get(level, 1.0) * affinity_multiplier(affinity_seconds)
    return AUTOMATION_BASE_YIELD_PCT[servant.tier] * mult
