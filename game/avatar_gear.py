"""
The Nascent Soul Avatar's own gear -- a genuinely separate equip-slot economy from the
player's own equipment.SLOTS/EQUIPMENT (see game/database.py's avatar_equipped/
avatar_gear_instances tables and GameManager.equip_avatar_gear_instance/
roll_and_grant_avatar_gear). Replaces the old Phase 1 flat 8-item catalog (Nascent/Ascendant x
Core/Vessel/Halo/Seal) with a real procedurally-rolled system, mirroring blacksmith.py's
roll_gear_stats -- the actual live budget-roll precedent in this codebase (NOT
accessories_gen.py's RANK_POWER_BUDGET/RARITY_BUDGET_MULTIPLIER, which turned out to be
confirmed-unused authoring guidance, not live code, when this was researched).

5 tiers, a fixed total percentage budget per tier, spent unevenly across a random subset of a
slot's own stat pool -- Core rolls from OFFENSE_KEYS, Vessel from DEFENSE_KEYS, Halo from
UTILITY_KEYS, Seal from DEFENSE_KEYS+UTILITY_KEYS. Drops from /rba (World Boss, commonly) and
raid bosses (rarely) -- see GameManager.roll_and_grant_avatar_gear -- gated on the avatar
being unlocked at all (Nascent Soul realm). Tier follows the drop source's own rank rather
than a hard equip-gate by realm substage: there's no real "Nascent Soul I-IX" ladder in this
game (only 4 substages exist per realm), so this mirrors every other loot system instead
(accessories, manual pages) of inventing one.

The old AVATAR_GEAR flat catalog + its power-weight table stay in this module, UNUSED for any
new grant, purely as a read-only fallback for players who still have a legacy piece equipped
(see GameManager._avatar_gear_power's instance-vs-catalog branch) -- nothing destroys
already-equipped data.
"""

import random
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from . import search_data

# (slot_key, label, slot_type, emoji) -- mirrors equipment.SLOTS' own tuple shape. Unchanged
# from Phase 1.
AVATAR_GEAR_SLOTS = [
    ("avatar_core", "Core", "Core", "🔥"),
    ("avatar_vessel", "Vessel", "Vessel", "🏺"),
    ("avatar_halo", "Halo", "Halo", "💫"),
    ("avatar_seal", "Seal", "Seal", "🔯"),
]
SLOT_TYPE_BY_KEY = {key: slot_type for key, _, slot_type, _ in AVATAR_GEAR_SLOTS}
SLOT_LABEL_BY_KEY = {key: label for key, label, _, _ in AVATAR_GEAR_SLOTS}
SLOT_EMOJI_BY_KEY = {key: emoji for key, _, _, emoji in AVATAR_GEAR_SLOTS}
SLOT_KEY_BY_TYPE = {slot_type: key for key, _, slot_type, _ in AVATAR_GEAR_SLOTS}

# -- Tiers -----------------------------------------------------------------------------------

TIER_BUDGET = {1: 8, 2: 10, 3: 12, 4: 15, 5: 20}
TIER_NAMES = {1: "Formed", 2: "Tempered", 3: "Perfected", 4: "Domainbound", 5: "Heaven-Defying"}
MIN_TIER = 1
MAX_TIER = 5


def tier_name(tier: int) -> str:
    return TIER_NAMES.get(tier, f"Tier {tier}")


# Spirit stones for selling an avatar gear instance to the /sell NPC vendor -- same tier-scaled
# convention as blacksmith.dismantle_stones, priced a little below its 30/tier rate since there's
# no material refund alongside it and avatar gear tiers only run 1-5, not 1-7.
SELL_STONES_PER_TIER = 25


def sell_stones(tier: int) -> int:
    return SELL_STONES_PER_TIER * tier


# -- Stat pool ---------------------------------------------------------------------------------
# Each key's %-granted per 1 budget point spent. 8 of these 13 keys already exist as real,
# combat-consumed GameManager.SPECIAL_BONUS_KEYS -- a rolled instance carrying them needs zero
# new combat wiring beyond flowing through the same generic compute_equipment_bonuses pool
# avatar-soul passives already use. 5 are new/consolidated: total_damage_pct,
# soul_projection_damage_pct, meditate_essence_bonus_pct, soul_skill_potency_pct,
# death_qi_loss_reduction_pct (existed for avatar souls already, now also gear-rollable --
# see the 3 death-penalty sites' consolidated single bonuses.get(...) read).
OFFENSE_KEYS: Tuple[str, ...] = (
    "total_damage_pct", "crit_chance_pct", "crit_damage_pct",
    "armor_penetration_pct", "boss_damage_bonus_pct", "soul_projection_damage_pct",
)
DEFENSE_KEYS: Tuple[str, ...] = ("hp_pct", "death_qi_loss_reduction_pct")
UTILITY_KEYS: Tuple[str, ...] = (
    "qi_pct", "cultivation_speed_pct", "meditate_essence_bonus_pct",
    "clue_chance_bonus_pct", "soul_skill_potency_pct",
)
SEAL_KEYS: Tuple[str, ...] = DEFENSE_KEYS + UTILITY_KEYS

POOL_BY_SLOT_TYPE: Dict[str, Tuple[str, ...]] = {
    "Core": OFFENSE_KEYS, "Vessel": DEFENSE_KEYS, "Halo": UTILITY_KEYS, "Seal": SEAL_KEYS,
}

AVATAR_GEAR_PCT_PER_POINT: Dict[str, float] = {
    "total_damage_pct": 0.01, "crit_chance_pct": 0.005, "crit_damage_pct": 0.02,
    "armor_penetration_pct": 0.015, "boss_damage_bonus_pct": 0.02, "soul_projection_damage_pct": 0.01,
    "hp_pct": 0.015, "death_qi_loss_reduction_pct": 0.02,
    "qi_pct": 0.015, "cultivation_speed_pct": 0.02, "meditate_essence_bonus_pct": 0.015,
    "clue_chance_bonus_pct": 0.015, "soul_skill_potency_pct": 0.01,
}

STAT_LABELS: Dict[str, str] = {
    "total_damage_pct": "Total Damage", "crit_chance_pct": "Crit Chance", "crit_damage_pct": "Crit Damage",
    "armor_penetration_pct": "Armor Penetration", "boss_damage_bonus_pct": "World Boss Damage",
    "soul_projection_damage_pct": "Soul Projection Damage", "hp_pct": "Max HP",
    "death_qi_loss_reduction_pct": "Soul-Damage Resistance", "qi_pct": "Max Qi",
    "cultivation_speed_pct": "Cultivation Speed", "meditate_essence_bonus_pct": "Meditate Essence Gain",
    "clue_chance_bonus_pct": "Inheritance-Search Luck", "soul_skill_potency_pct": "Soul Skill Potency",
}

# Rough per-1%-of-value scoring weight, same role equipment.SPECIAL_BONUS_POWER_WEIGHTS plays
# for the player's own gear -- only drives _avatar_gear_power's sort/sum, not actual combat
# math. Priced by how many budget points buy 1% of each stat (the inverse of
# AVATAR_GEAR_PCT_PER_POINT), so a piece's power score stays roughly stable across different
# stat rolls at the same tier regardless of which keys it happened to land on.
AVATAR_GEAR_POWER_WEIGHTS: Dict[str, float] = {key: 1.0 / pct for key, pct in AVATAR_GEAR_PCT_PER_POINT.items()}

MIN_STATS_ROLLED = 2
MAX_STATS_ROLLED = 4
FLOOR_BUDGET_SHARE = 0.3  # protects against an unlucky cut squeezing a chosen stat to ~0


def roll_avatar_gear_stats(slot_type: str, tier: int, rng: Optional[random.Random] = None) -> Dict[str, float]:
    """Spends `tier`'s percentage budget across a random subset of `slot_type`'s own stat
    pool -- mirrors blacksmith.roll_gear_stats' shape (random subset via rng.sample, uneven
    split via sorted rng.uniform cut points), with two differences: each slot has a
    different, SMALLER pool than blacksmith's uniform 6 (Vessel only has 2 keys, so the roll
    count clamps to the pool size -- every Vessel piece ends up rolling both of its keys), and
    each key has its own %-per-point rate instead of one flat conversion."""
    r = rng or random
    pool = POOL_BY_SLOT_TYPE[slot_type]
    budget = TIER_BUDGET[tier]
    count = r.randint(min(MIN_STATS_ROLLED, len(pool)), min(MAX_STATS_ROLLED, len(pool)))
    chosen = r.sample(pool, count)

    cuts = sorted(r.uniform(0, budget) for _ in range(count - 1))
    bounds = [0.0] + cuts + [budget]
    shares = [max(FLOOR_BUDGET_SHARE, bounds[i + 1] - bounds[i]) for i in range(count)]

    return {key: round(share * AVATAR_GEAR_PCT_PER_POINT[key], 4) for key, share in zip(chosen, shares)}


def avatar_gear_instance_power_score(stat_bonuses: Dict[str, float]) -> float:
    return sum(stat_bonuses.get(key, 0) * weight for key, weight in AVATAR_GEAR_POWER_WEIGHTS.items())


def roll_avatar_gear_tier(source_tier: int, rng: Optional[random.Random] = None) -> int:
    """Same relative-offset shape accessories_gen.roll_rank already uses (see
    search_data.ITEM_RANK_RELATIVE_WEIGHTS), clamped to this system's own [1, 5] range
    instead of accessories' [1, 7]."""
    r = rng or random
    keys = list(search_data.ITEM_RANK_RELATIVE_WEIGHTS.keys())
    weights = list(search_data.ITEM_RANK_RELATIVE_WEIGHTS.values())
    offset = r.choices(keys, weights=weights, k=1)[0]
    return max(MIN_TIER, min(MAX_TIER, source_tier + offset))


def describe_avatar_gear_stat_bonuses(stat_bonuses: Dict[str, float]) -> str:
    return " • ".join(f"{STAT_LABELS.get(key, key)}: +{value * 100:.1f}%" for key, value in stat_bonuses.items())


# -- Legacy Phase 1 flat catalog -- UNUSED for any new grant, kept only so a still-equipped
# legacy piece (instance_id NULL in avatar_equipped) keeps reading/displaying/scoring
# correctly forever. See GameManager._avatar_gear_power's instance-vs-catalog branch.

@dataclass
class AvatarGear:
    name: str
    slot_type: str
    rank: str
    description: str
    stat_bonuses: Dict[str, float] = field(default_factory=dict)


AVATAR_GEAR: Dict[str, AvatarGear] = {
    "Nascent Core": AvatarGear(
        "Nascent Core", "Core", "Nascent",
        "A fledgling core, barely stable, for the avatar's offense.",
        {"avatar_offense": 8},
    ),
    "Ascendant Core": AvatarGear(
        "Ascendant Core", "Core", "Ascendant",
        "A refined offensive core, burning brighter.",
        {"avatar_offense": 18, "avatar_utility": 4},
    ),
    "Nascent Vessel": AvatarGear(
        "Nascent Vessel", "Vessel", "Nascent",
        "A fledgling vessel, steadying the avatar's form.",
        {"avatar_defense": 8},
    ),
    "Ascendant Vessel": AvatarGear(
        "Ascendant Vessel", "Vessel", "Ascendant",
        "A refined, sturdier vessel.",
        {"avatar_defense": 18, "avatar_utility": 4},
    ),
    "Nascent Halo": AvatarGear(
        "Nascent Halo", "Halo", "Nascent",
        "A faint halo of soul-light.",
        {"avatar_utility": 8},
    ),
    "Ascendant Halo": AvatarGear(
        "Ascendant Halo", "Halo", "Ascendant",
        "A brightening halo of soul-light.",
        {"avatar_utility": 18, "avatar_offense": 4},
    ),
    "Nascent Seal": AvatarGear(
        "Nascent Seal", "Seal", "Nascent",
        "A minor binding seal.",
        {"avatar_utility": 6, "avatar_defense": 2},
    ),
    "Ascendant Seal": AvatarGear(
        "Ascendant Seal", "Seal", "Ascendant",
        "A stronger binding seal.",
        {"avatar_utility": 14, "avatar_defense": 6},
    ),
}

LEGACY_AVATAR_GEAR_POWER_WEIGHTS = {"avatar_offense": 1.0, "avatar_defense": 1.0, "avatar_utility": 1.0}


def legacy_avatar_gear_power_score(gear: AvatarGear) -> float:
    return sum(gear.stat_bonuses.get(key, 0) * weight for key, weight in LEGACY_AVATAR_GEAR_POWER_WEIGHTS.items())


def describe_avatar_stat_bonuses(stat_bonuses: Dict[str, float]) -> str:
    labels = {"avatar_offense": "Offense", "avatar_defense": "Defense", "avatar_utility": "Utility"}
    return " • ".join(f"{labels.get(key, key)}: {value:+g}" for key, value in stat_bonuses.items())
