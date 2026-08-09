import math
import random
from datetime import datetime, timezone
from typing import Optional

from .character_class import CLASSES
from .character_data import (
    PATHS,
    PHYSIQUE_SPECS_BY_NAME,
    PHYSIQUE_TIER_WEIGHTS,
    PHYSIQUE_TIERS,
    RACES,
    ROOT_SPECS_BY_NAME,
    ROOT_TIER_WEIGHTS,
    ROOT_TIERS,
)

# Base foundation stat roll ranges, before race/root/physique/path bonuses.
# Tunable — picked to land in the same ballpark as a fresh mortal-realm character.
BASE_STAT_RANGES = {
    "str_stat": (8, 16),
    "atk_stat": (6, 14),
    "hp": (80, 120),
    "spd_stat": (4, 10),
    "luck_stat": (0, 5),
    "qi_stat": (10, 25),
    "def_stat": (6, 14),
}


def roll_base_stats() -> dict:
    return {stat: random.randint(lo, hi) for stat, (lo, hi) in BASE_STAT_RANGES.items()}


def _total_bonus(key: str, *sources) -> float:
    return sum(getattr(source, "stat_bonuses", {}).get(key, 0) for source in sources if source is not None)


def compute_final_stats(base: dict, race, root_tier, physique_tier, path, character_class=None, physique_spec=None) -> dict:
    """physique_spec (see character_data.CharacterTraitSpec / PHYSIQUE_SPECS_BY_NAME) is a
    named physique's own ADDITIONAL foundation-stat bonus, layered on top of physique_tier's
    shared package exactly the same additive way a root's own spec layers on top of its
    shared tier package — physique_tier's own str_pct/hp_pct/def_pct are never reduced or
    replaced, a named physique just adds its own thematic stat (e.g. Swift Foot Body's own
    spd_pct) alongside it. _total_bonus already sums .stat_bonuses generically across
    whatever's in `sources`, so passing physique_spec as one more source is the whole change."""
    sources = (race, root_tier, physique_tier, path, character_class, physique_spec)
    return {
        "str_stat": max(1, round(base["str_stat"] * (1 + _total_bonus("str_pct", *sources)))),
        "atk_stat": max(1, round(base["atk_stat"] * (1 + _total_bonus("atk_pct", *sources)))),
        "hp": max(1, round(base["hp"] * (1 + _total_bonus("hp_pct", *sources)))),
        "spd_stat": max(1, round(base["spd_stat"] * (1 + _total_bonus("spd_pct", *sources)))),
        "def_stat": max(1, round(base["def_stat"] * (1 + _total_bonus("def_pct", *sources)))),
        "qi_stat": max(1, round(base["qi_stat"] * (1 + _total_bonus("qi_pct", *sources)))),
        "luck_stat": max(0, int(base["luck_stat"] + _total_bonus("luck_flat", *sources))),
    }


# Growth-pool stats a random +1 can land on (Human race, Legendary physique).
STAT_GROWTH_KEYS = ["str_stat", "atk_stat", "hp", "spd_stat", "def_stat", "qi_stat", "luck_stat"]
STAT_LABELS = {
    "str_stat": "STR", "atk_stat": "ATK", "hp": "HP", "spd_stat": "SPD",
    "def_stat": "DEF", "qi_stat": "QI", "luck_stat": "LCK",
}

# Stats scaled by a realm breakthrough's power_multiplier (see GameDatabase.apply_breakthrough).
POWER_STAT_KEYS = ("str_stat", "atk_stat", "spd_stat", "def_stat", "qi_stat", "hp")


def sql_round(value: float) -> int:
    """Round half away from zero, matching SQLite's ROUND() — Python's builtin round()
    uses banker's rounding, which can land 1 off from what the database actually writes."""
    return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)


def project_power_growth(player, power_multiplier: float) -> dict:
    """The exact per-stat gain a breakthrough's power_multiplier alone will apply —
    excludes any separate 'bonus random stat' roll, which can't be known in advance."""
    return {
        key: max(1, sql_round(player[key] * power_multiplier)) - player[key]
        for key in POWER_STAT_KEYS
    }

# Breakthrough chance: a flat base, plus race/root/physique/path bonuses, plus
# a small nudge from the character's rolled Luck. Clamped so it's never a sure
# thing or a sure failure. All tunable.
BASE_BREAKTHROUGH_CHANCE = 0.30
LUCK_BREAKTHROUGH_CHANCE_PER_POINT = 0.002
MIN_BREAKTHROUGH_CHANCE = 0.05
MAX_BREAKTHROUGH_CHANCE = 0.95

# Dao Comprehension: chance to get a bonus qi refund on a successful
# breakthrough, sized as a fraction of the qi that breakthrough just cost.
DAO_COMPREHENSION_BONUS_QI_FRACTION = 0.5


def effective_qi_rate_bonus(race, root_tier, physique_tier, path) -> float:
    """Cultivation Speed and Qi Recovery both just mean 'qi comes back faster' here, so they're summed together."""
    sources = (race, root_tier, physique_tier, path)
    return _total_bonus("cultivation_speed_pct", *sources) + _total_bonus("qi_recovery_pct", *sources)


def is_daytime() -> bool:
    """One server-wide UTC clock (no per-player timezone is tracked anywhere) — 06:00-17:59
    UTC counts as day, the other 12 hours count as night. Used by Ancient Solar/Moon Spiritual
    Root's own cultivation-speed bonus (see GameDatabase._qi_rate_components)."""
    return 6 <= datetime.now(timezone.utc).hour < 18


def effective_breakthrough_chance(race, root_tier, physique_tier, path, luck_stat: int = 0) -> float:
    bonus = _total_bonus("breakthrough_chance_pct", race, root_tier, physique_tier, path)
    chance = BASE_BREAKTHROUGH_CHANCE + bonus + luck_stat * LUCK_BREAKTHROUGH_CHANCE_PER_POINT
    return max(MIN_BREAKTHROUGH_CHANCE, min(MAX_BREAKTHROUGH_CHANCE, chance))


def effective_dao_comprehension_bonus(race, root_tier, physique_tier, path) -> float:
    return _total_bonus("dao_comprehension_pct", race, root_tier, physique_tier, path)


# Race/Physique combat passives that reduce incoming damage — folded into hunt.py/raid.py/
# pvp_view.py's incoming_reduction alongside Guard and Gu's beast_damage_reduction_pct, using
# the same multiplicative-stacking formula (1 - (1-a)*(1-b)*...) so none of them ever combine
# into a sure block on their own.
ROCKMAN_DAMAGE_REDUCTION = 0.15
ROCKMAN_DAMAGE_REDUCTION_HP_THRESHOLD = 0.5  # only while above 50% HP
RARE_PHYSIQUE_DAMAGE_REDUCTION = 0.05  # "Small damage reduction" — always on, no HP condition


def race_physique_damage_reduction(race_name: Optional[str], physique_tier_name: Optional[str], hp_ratio: float) -> float:
    reduction = 0.0
    if race_name == "Rockman" and hp_ratio > ROCKMAN_DAMAGE_REDUCTION_HP_THRESHOLD:
        reduction = 1 - (1 - reduction) * (1 - ROCKMAN_DAMAGE_REDUCTION)
    if physique_tier_name == "Rare":
        reduction = 1 - (1 - reduction) * (1 - RARE_PHYSIQUE_DAMAGE_REDUCTION)
    return reduction


# "Nameless Immortal Root"/"Nameless Immortal Physique" (see character_data.ROOT_TIERS/
# PHYSIQUE_TIERS' own "Unique" entries) are deliberately exempt from the one-holder-per-name
# scarcity every other Unique-tier (and now Godly-tier) name is bound by -- per explicit
# request ("many people can roll it"), so they never count as "claimed" for either exhausting
# that tier's pool or being filtered out of it. Both live in one set since root/physique names
# never collide.
GENERIC_UNIQUE_NAMES = {"Nameless Immortal Root", "Nameless Immortal Physique"}

# Tiers with one-holder-per-name scarcity (see _roll_tier/_unique_pool below). "Godly" only
# ever appears in PHYSIQUE_TIERS (character_data.PHYSIQUE_TIER_ORDER, not the root ladder) --
# tiers.get() on a ladder that doesn't have it just returns None and is skipped, same as
# "Unique" already being looked up safely on ladders that always have it.
SCARCE_TIER_NAMES = ("Unique", "Godly")


def _roll_tier(tier_weights: dict, tiers: dict, claimed_unique_names: set) -> str:
    weights = dict(tier_weights)
    for scarce_tier_name in SCARCE_TIER_NAMES:
        scarce_tier = tiers.get(scarce_tier_name)
        if scarce_tier is None:
            continue
        exclusive_names = [n for n in scarce_tier.names if n not in GENERIC_UNIQUE_NAMES]
        has_generic_fallback = len(exclusive_names) < len(scarce_tier.names)
        claimed_exclusive_count = len(claimed_unique_names & set(exclusive_names))
        # A generic fallback name (if this tier has one) is always still rollable no matter how
        # many exclusive names are claimed, so the tier itself never needs disabling.
        if not has_generic_fallback and claimed_exclusive_count >= len(exclusive_names):
            weights.pop(scarce_tier_name, None)
    names = list(weights.keys())
    return random.choices(names, weights=list(weights.values()), k=1)[0]


def _unique_pool(tier, claimed_unique_names: set) -> list:
    return [n for n in tier.names if n not in claimed_unique_names or n in GENERIC_UNIQUE_NAMES]


def roll_root(claimed_unique_names: set) -> tuple:
    tier_name = _roll_tier(ROOT_TIER_WEIGHTS, ROOT_TIERS, claimed_unique_names)
    tier = ROOT_TIERS[tier_name]
    pool = _unique_pool(tier, claimed_unique_names) if tier_name in SCARCE_TIER_NAMES else tier.names
    return tier_name, random.choice(pool)


def roll_physique(claimed_unique_names: set) -> tuple:
    tier_name = _roll_tier(PHYSIQUE_TIER_WEIGHTS, PHYSIQUE_TIERS, claimed_unique_names)
    tier = PHYSIQUE_TIERS[tier_name]
    pool = _unique_pool(tier, claimed_unique_names) if tier_name in SCARCE_TIER_NAMES else tier.names
    return tier_name, random.choice(pool)


def get_race(name: Optional[str]):
    return RACES.get(name) if name else None


def get_root_tier(name: Optional[str]):
    return ROOT_TIERS.get(name) if name else None


def get_root_spec(name: Optional[str]):
    """The named root's OWN mechanic (see character_data.CharacterTraitSpec) — None for a
    root name that doesn't have one yet (any tier above Uncommon, for now; see
    character_data.ROOT_SPECS_BY_NAME's own docstring for why). Every consumer treats a
    missing spec as "no extra bonus", never an error, so this is always safe to call."""
    return ROOT_SPECS_BY_NAME.get(name) if name else None


def get_physique_spec(name: Optional[str]):
    """Same idea as get_root_spec, for PHYSIQUE_SPECS_BY_NAME."""
    return PHYSIQUE_SPECS_BY_NAME.get(name) if name else None


def get_physique_tier(name: Optional[str]):
    return PHYSIQUE_TIERS.get(name) if name else None


def get_path(name: Optional[str]):
    return PATHS.get(name) if name else None


def get_character_class(name: Optional[str]):
    return CLASSES.get(name) if name else None


def unique_passive(tiers: dict, tier_name: Optional[str], item_name: Optional[str]) -> Optional[str]:
    if tier_name != "Unique" or not item_name:
        return None
    tier = tiers.get(tier_name)
    if tier is None or tier.unique_passives is None:
        return None
    return tier.unique_passives.get(item_name)
