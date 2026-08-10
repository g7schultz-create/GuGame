"""
Spirit Severing Dao Paths -- upon reaching Spirit Severing, cultivators earn Dao Marks (see
GameManager.grant_dao_marks) from combat/exploration activity and one-time realm-breakthrough
lump sums, then pour them into any of the 14 Dao Paths below for a permanent, ever-scaling
bonus. Marks can be freely allocated to any path a player likes, but once spent on a path they
can never be withdrawn or moved to another -- a skill tree, not a single once-and-done choice.

This module is pure logic -- no DB/GameManager/discord dependency, mirroring tournament.py's
and world_boss.py's own split from manager.py -- so the scaling math is directly unit-testable.
Each path's bonus is linear from 0 at 0 marks invested up to its own "at cap" value at
DAO_MARKS_CAP_PER_PATH marks invested (2000, "for now" -- a future cap raise only needs to
change that one constant). Most bonus keys plug directly into the existing
SPECIAL_BONUS_KEYS/crafted_pct_totals pools GameManager.compute_equipment_bonuses already
builds; a handful are new keys with their own bespoke consumption sites since no equivalent
mechanic existed anywhere in the codebase before this (fire_burn_damage_pct,
meditate_cooldown_reduction_pct, alchemy_bonus_pill_chance_pct, crafting_success_pct,
pill_save_chance_pct) -- see manager.py's Dao Path section for exactly where each is consumed.
"""

import random
from dataclasses import dataclass, field
from typing import Dict, Optional

DAO_MARKS_CAP_PER_PATH = 2000

ACTIVITY_MARKS_MIN = 1
ACTIVITY_MARKS_MAX = 3

FIRE_BURN_TICKS = 3


@dataclass
class DaoPathSpec:
    name: str
    tagline: str
    description: str
    bonus_at_cap: Dict[str, float] = field(default_factory=dict)


DAO_PATHS: Dict[str, DaoPathSpec] = {
    "Strength": DaoPathSpec(
        name="Strength",
        tagline="Raw physical might, without end.",
        description="STR scales directly with Dao Marks invested.",
        bonus_at_cap={"str_pct": 0.50},
    ),
    "Sword": DaoPathSpec(
        name="Sword",
        tagline="Every strike seeks the gap in the armor.",
        description="Armor penetration and critical strike chance scale with Dao Marks invested.",
        bonus_at_cap={"armor_penetration_pct": 0.25, "crit_chance_pct": 0.15},
    ),
    "Fire": DaoPathSpec(
        name="Fire",
        tagline="Let the world burn in your wake.",
        description="Your hits sear a lasting burn into the target, scaling with Dao Marks invested.",
        bonus_at_cap={"fire_burn_damage_pct": 0.40},
    ),
    "Blood": DaoPathSpec(
        name="Blood",
        tagline="Every drop spilled feeds your own vitality.",
        description="Max HP and lifesteal scale with Dao Marks invested.",
        bonus_at_cap={"hp_pct": 0.40, "lifesteal_percent": 0.20},
    ),
    "Soul": DaoPathSpec(
        name="Soul",
        tagline="Even death cannot fully sever you.",
        description="Qi lost on death is reduced, and your Nascent Soul Avatar grows stronger, scaling with Dao Marks invested.",
        bonus_at_cap={"death_qi_loss_reduction_pct": 0.50, "soul_skill_potency_pct": 0.30, "soul_projection_damage_pct": 0.30},
    ),
    "Wisdom": DaoPathSpec(
        name="Wisdom",
        tagline="Understanding is the truest cultivation.",
        description="Dao Comprehension and meditation's cooldown improve, scaling with Dao Marks invested.",
        bonus_at_cap={"dao_comprehension_pct": 0.25, "meditate_cooldown_reduction_pct": 0.40},
    ),
    "Luck": DaoPathSpec(
        name="Luck",
        tagline="Fortune favors the invested.",
        description="Cultivation speed, luck, and rare loot/stone find odds scale with Dao Marks invested.",
        bonus_at_cap={"cultivation_speed_pct": 0.25, "luck_flat": 200.0, "loot_chance_bonus_pct": 0.20, "stone_reward_bonus_pct": 0.20},
    ),
    "Refinement": DaoPathSpec(
        name="Refinement",
        tagline="Waste nothing; extract everything.",
        description="Chance for a bonus pill on a successful alchemy craft scales with Dao Marks invested.",
        bonus_at_cap={"alchemy_bonus_pill_chance_pct": 0.35},
    ),
    "Formation": DaoPathSpec(
        name="Formation",
        tagline="An unbreakable line holds forever.",
        description="Defense and max HP scale with Dao Marks invested.",
        bonus_at_cap={"def_pct": 0.45, "hp_pct": 0.30},
    ),
    "Enslavement": DaoPathSpec(
        name="Enslavement",
        tagline="Bind fate itself to your will.",
        description="A large max HP bonus scales with Dao Marks invested.",
        bonus_at_cap={"hp_pct": 0.70},
    ),
    "Time": DaoPathSpec(
        name="Time",
        tagline="Every moment bends to your pace.",
        description="All cooldowns are reduced, scaling with Dao Marks invested.",
        bonus_at_cap={"cooldown_reduction_pct": 0.30},
    ),
    "Space": DaoPathSpec(
        name="Space",
        tagline="Fold distance and possibility alike.",
        description="Crafting and alchemy success chance scale with Dao Marks invested.",
        bonus_at_cap={"crafting_success_pct": 0.25, "alchemy_success_pct": 0.25},
    ),
    "Food": DaoPathSpec(
        name="Food",
        tagline="A true chef never wastes a single pill.",
        description="Chance to not consume a Pill when you use one scales with Dao Marks invested.",
        bonus_at_cap={"pill_save_chance_pct": 0.40},
    ),
    "Transformation": DaoPathSpec(
        name="Transformation",
        tagline="All things are the same thing, differently arranged.",
        description="Unlocks /transmute -- converting an item into a random item of the same tier. Daily charges scale with Dao Marks invested.",
        bonus_at_cap={},  # daily charges come from transmute_charges() below, not the generic linear scale
    ),
}


def scaled_bonus(path_name: str, marks_invested: int) -> Dict[str, float]:
    """Linear 0 -> bonus_at_cap as marks_invested goes 0 -> DAO_MARKS_CAP_PER_PATH; clamped so
    over-cap investment (shouldn't happen -- allocate_dao_marks refuses it -- but this defends
    anyway) never exceeds the cap value."""
    spec = DAO_PATHS.get(path_name)
    if spec is None:
        return {}
    fraction = min(1.0, max(0.0, marks_invested) / DAO_MARKS_CAP_PER_PATH)
    return {key: value * fraction for key, value in spec.bonus_at_cap.items()}


def random_activity_marks() -> int:
    """1-3 Dao Marks -- the flat per-action grant for /hunt, /raid, /explore, /battlefield,
    /world_boss (attack), and each tournament placement. Single source of truth so every call
    site rolls identically."""
    return random.randint(ACTIVITY_MARKS_MIN, ACTIVITY_MARKS_MAX)


# realm_index_after landing exactly on one of Spirit Severing's 4 substages -> one-time lump
# sum. Keyed by (great_realm_name, substage_name) rather than a raw realm_index so this module
# never has to hardcode realms.py's index math (great_realm_index * 4 + substage_offset) -- the
# caller (GameManager.attempt_breakthrough) already has a realms.RealmStage object in hand and
# just passes its two name fields through.
_SPIRIT_SEVERING_BREAKTHROUGH_RANGES = {
    "Early": (200, 400),
    "Middle": (300, 500),
    "Late": (400, 700),
    "Peak": (1000, 1000),
}

# Same lump-sum-per-breakthrough shape as Spirit Severing above, per explicit request that
# Ancient Realm "still" grants Dao Marks per breakthrough rather than the mechanic staying
# Spirit-Severing-only forever. Scaled ~3x Spirit Severing's own ranges (Dao Seeking, the
# realm in between, deliberately keeps getting nothing -- only these two Great Realms grant a
# breakthrough lump sum) -- a Peak-Ancient-Realm breakthrough alone funds most of a fresh
# DAO_MARKS_CAP_PER_PATH path (2000), a fitting one-time payout for the very top of the ladder.
_ANCIENT_REALM_BREAKTHROUGH_RANGES = {
    "Early": (600, 1200),
    "Middle": (900, 1500),
    "Late": (1200, 2100),
    "Peak": (3000, 3000),
}

_BREAKTHROUGH_MARK_RANGES_BY_GREAT_REALM = {
    "Spirit Severing": _SPIRIT_SEVERING_BREAKTHROUGH_RANGES,
    "Ancient Realm": _ANCIENT_REALM_BREAKTHROUGH_RANGES,
}


def breakthrough_marks(great_realm_name: str, substage_name: str) -> Optional[int]:
    """One-time Dao Marks lump sum for breaking through INTO one of Spirit Severing's or
    Ancient Realm's 4 substages. None for every other breakthrough (any other Great Realm,
    including Dao Seeking in between)."""
    ranges = _BREAKTHROUGH_MARK_RANGES_BY_GREAT_REALM.get(great_realm_name)
    if ranges is None:
        return None
    bounds = ranges.get(substage_name)
    if bounds is None:
        return None
    low, high = bounds
    return random.randint(low, high)


def transmute_charges(marks_invested: int) -> int:
    """1 base charge/day + 1 per 500 Dao Marks invested in Transformation, capped at 5/day."""
    return min(5, 1 + marks_invested // 500)


def fire_burn_tick_damage(hit_damage: int, fire_burn_damage_pct: float) -> int:
    """Total burn damage from one hit is fire_burn_damage_pct of that hit's damage, split evenly
    across FIRE_BURN_TICKS subsequent ticks. Returns the per-tick amount (at least 1 whenever the
    hit did damage and the path bonus is active, so a burn never silently rounds to nothing)."""
    if fire_burn_damage_pct <= 0 or hit_damage <= 0:
        return 0
    return max(1, round(hit_damage * fire_burn_damage_pct / FIRE_BURN_TICKS))
