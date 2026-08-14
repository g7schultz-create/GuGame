"""
Gu Pet — a single-slot companion acquired through the (previously dormant) Gu Refiner
profession: sacrifice 10-20 identical copies of one owned Gu (pure "energy mass", the
sacrificed Gu's own stats/identity never carry over) plus Soul Nourishing Pill/Soul Crystal
catalysts (the same two items Nascent Soul Avatar leveling already uses) into a blank Rank I
pet. See GameManager.refine_gu_pet.

Lifecycle, mirroring avatar.py's own role as the pure data/rules module (no Discord/DB code
here):
    growth (stage='growth')  -- one feed/24h for GU_PET_RANK_TO_RARITY-days worth of a
                                 7-14 day window (see growth_days_required), each feed adding
                                 permanent stat growth and tallying which of the 5 material
                                 categories was fed (see GameManager.feed_gu_pet).
    crystallization           -- once growth_days_fed reaches growth_days_required, the RATIO
                                 of everything fed (never the sacrificed Gu) locks in a
                                 permanent species + Path (see crystallize). Growth stops
                                 forever the moment this happens.
    mature (stage='mature')   -- satiety upkeep only (see GameManager._settle_gu_pet_satiety),
                                 gated behind whichever Combat/Cultivation Mode bonus the
                                 pet's locked species/Path grants.

Rank (1-7, int) is this module's own single source of truth — GU_PET_RANK_TO_RARITY is the
ONLY place rank ever converts to a rarity word (see game/gu_pet_images.py, which is the only
consumer that needs the word instead of the number), chosen to match accessories_data.
RARITY_ORDER exactly (the only existing rarity ladder with no leftover tier once mapped
1:1 onto Rank I-VII).
"""

import random
from typing import Dict, Optional, Tuple

from . import accessories_data

MIN_RANK = 1
MAX_RANK = 7

# Single source of truth for rank -> rarity word (see this module's own docstring) --
# generated FROM accessories_data.RARITY_ORDER rather than a second hardcoded list, so the
# two can never drift apart.
GU_PET_RANK_TO_RARITY: Dict[int, str] = dict(enumerate(accessories_data.RARITY_ORDER[:MAX_RANK], start=1))

# Gu Refiner profession rank INDEX (see professions.RANKS, 0=Novice..7=Dao Master) required
# to attempt refining each pet rank -- same "pet rank N needs profession rank index N-1"
# shape blacksmith.TIER_RANK_REQUIRED uses for its own Tier 8 (needs index 6, one below the
# ladder's own top), leaving Dao Master real headroom above even a Rank VII pet.
GU_PET_RANK_REQUIRED: Dict[int, int] = {rank: rank - 1 for rank in range(MIN_RANK, MAX_RANK + 1)}

# Per-rank scaling (design doc section 17's own "Rank Tier & Stat Scaling Matrix", expanded
# from the doc's own paired I-II/III-IV/V-VI grouping into one entry per rank -- both ranks in
# a pair share identical scaling). blacksmith_budget_bonus_range/manual_unique_bonus_range
# are (min, max) fractions an actual bonus gets rolled/resolved within (see GameManager.
# _gu_pet_cultivation_bonus, Phase 6) -- combat_multiplier is a flat scalar applied directly.
# satiety_material_tier reuses the SAME material tiers 1-7 blacksmith.ore_name/
# beast_material_name/beast_core_name, alchemy.herb_name, and items.alchemy_pill_name already
# produce -- a mature pet's upkeep feed must match its own rank's tier.
GU_PET_RANK_SCALING: Dict[int, dict] = {
    1: {"combat_multiplier": 1.0, "blacksmith_budget_bonus_range": (0.020, 0.040), "manual_unique_bonus_range": (0.015, 0.030), "satiety_material_tier": 1},
    2: {"combat_multiplier": 1.0, "blacksmith_budget_bonus_range": (0.020, 0.040), "manual_unique_bonus_range": (0.015, 0.030), "satiety_material_tier": 2},
    3: {"combat_multiplier": 1.5, "blacksmith_budget_bonus_range": (0.045, 0.075), "manual_unique_bonus_range": (0.035, 0.060), "satiety_material_tier": 3},
    4: {"combat_multiplier": 1.5, "blacksmith_budget_bonus_range": (0.045, 0.075), "manual_unique_bonus_range": (0.035, 0.060), "satiety_material_tier": 4},
    5: {"combat_multiplier": 2.2, "blacksmith_budget_bonus_range": (0.080, 0.110), "manual_unique_bonus_range": (0.065, 0.090), "satiety_material_tier": 5},
    6: {"combat_multiplier": 2.2, "blacksmith_budget_bonus_range": (0.080, 0.110), "manual_unique_bonus_range": (0.065, 0.090), "satiety_material_tier": 6},
    7: {"combat_multiplier": 3.0, "blacksmith_budget_bonus_range": (0.120, 0.150), "manual_unique_bonus_range": (0.100, 0.125), "satiety_material_tier": 7},
}


def rank_scaling(rank: int) -> dict:
    return GU_PET_RANK_SCALING[max(MIN_RANK, min(rank, MAX_RANK))]


def rank_to_rarity(rank: int) -> str:
    return GU_PET_RANK_TO_RARITY[max(MIN_RANK, min(rank, MAX_RANK))]


def gu_refiner_rank_required(target_rank: int) -> int:
    return GU_PET_RANK_REQUIRED[max(MIN_RANK, min(target_rank, MAX_RANK))]


# -- Growth phase -----------------------------------------------------------------------

GROWTH_DAYS_MIN = 7
GROWTH_DAYS_MAX = 14
FEED_COOLDOWN_SECONDS = 86400  # one feed per real day -- see this module's own docstring
# for why this is deliberately NOT routed through GameManager._check_cooldown.

FEED_STREAK_BONUS_PER_DAY_PCT = 0.01
FEED_STREAK_BONUS_CAP_PCT = 0.10


def growth_days_required(rng: Optional[random.Random] = None) -> int:
    r = rng or random
    return r.randint(GROWTH_DAYS_MIN, GROWTH_DAYS_MAX)


def streak_bonus_pct(feed_streak_days: int) -> float:
    return min(FEED_STREAK_BONUS_CAP_PCT, max(0, feed_streak_days) * FEED_STREAK_BONUS_PER_DAY_PCT)


# The 5 feeding-material categories (design doc section 6) -- each maps onto a real,
# already-existing item family rather than inventing new ones.
FEED_CATEGORIES = ("beast_material", "beast_core", "ore", "herb", "pill")

# Combat-vs-Cultivation Path assignment (design doc section 8.1) -- the two buckets are
# complementary and always sum to 100% of fed_totals, so an exact 50/50 split has to pick a
# side; this defaults to Cultivation/Artisan Specialist (documented here as the single source
# of truth for that tie-break, see crystallize()).
COMBAT_PATH_CATEGORIES = ("beast_material", "beast_core")
CULTIVATION_PATH_CATEGORIES = ("ore", "herb", "pill")
PATH_COMBAT = "Combat Specialist"
PATH_CULTIVATION = "Cultivation Specialist"

MODE_COMBAT = "combat"
MODE_CULTIVATION = "cultivation"
STAGE_GROWTH = "growth"
STAGE_MATURE = "mature"


# -- Satiety (design doc sections 11-12) -------------------------------------------------

# (min_inclusive, max_inclusive, output_multiplier, label) -- checked top-down, first match
# wins. Cultivation Mode drains this by real elapsed hours; Combat Mode drains a flat amount
# per dispatch instead (see GameManager._settle_gu_pet_satiety / apply_encounter_start_bonuses).
SATIETY_BANDS: Tuple[Tuple[int, int, float, str], ...] = (
    (80, 100, 1.10, "Well-Fed"),
    (21, 79, 1.00, "Satiated"),
    (1, 20, 0.50, "Hungry"),
    (0, 0, 0.0, "Starving"),
)

SATIETY_MAX = 100.0
# Cultivation Mode: flat drain per real hour. Combat Mode: flat drain per dispatch (a single
# /hunt, /raid, /battlefield, /inheritance_ground, or /search_black_heaven encounter start --
# see apply_encounter_start_bonuses' own call sites).
SATIETY_DRAIN_PER_CULTIVATION_HOUR = 100.0 / (7 * 24)  # empties over ~1 week of pure idle time
SATIETY_DRAIN_PER_COMBAT_DISPATCH = 4.0  # empties over ~25 dispatches with no re-feeding


def satiety_band(satiety: float) -> Tuple[float, str]:
    """(output_multiplier, label) for a given satiety value."""
    for low, high, multiplier, label in SATIETY_BANDS:
        if low <= satiety <= high:
            return multiplier, label
    return 0.0, "Starving"
