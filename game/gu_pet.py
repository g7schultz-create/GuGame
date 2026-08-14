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
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from . import accessories_data, gathering, items

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


# -- Refinement (design doc sections 2-4) -- see GameManager.refine_gu_pet -----------------

REFINE_MIN_SACRIFICE = 10
REFINE_MAX_SACRIFICE = 20

# Soul Nourishing Pill + Soul Crystal -- the SAME two catalyst items Nascent Soul Avatar
# leveling already uses (see avatar.AVATAR_LEVEL_UP_RECIPE), scaled per TARGET pet rank with
# the same tapering-multiplicative shape that recipe already uses, not per quantity sacrificed
# (quantity sacrificed instead feeds the success roll's material_quality_bonus below).
GU_PET_REFINE_CATALYST_RECIPE: Dict[int, Dict[str, int]] = {
    1: {"Soul Nourishing Pill": 3, "Soul Crystal": 1},
    2: {"Soul Nourishing Pill": 5, "Soul Crystal": 2},
    3: {"Soul Nourishing Pill": 8, "Soul Crystal": 3},
    4: {"Soul Nourishing Pill": 12, "Soul Crystal": 5},
    5: {"Soul Nourishing Pill": 18, "Soul Crystal": 8},
    6: {"Soul Nourishing Pill": 26, "Soul Crystal": 12},
    7: {"Soul Nourishing Pill": 36, "Soul Crystal": 17},
}


def refine_catalyst_recipe(target_rank: int) -> Dict[str, int]:
    return GU_PET_REFINE_CATALYST_RECIPE[max(MIN_RANK, min(target_rank, MAX_RANK))]


# Success-formula bonus per Gu Refiner rank index above the minimum required for the
# ATTEMPTED target rank (design doc section 3.1's own "(Refiner Level - Required Level) *
# 5%" term) -- layered ON TOP of professions.craft_success_chance's own absolute-rank curve
# (which already covers "base rate scales with rank" the way craft_gear/craft_pill do), so
# this term specifically rewards being over-ranked for an easy target rather than double-
# counting absolute rank twice.
REFINE_RANK_ABOVE_REQUIRED_BONUS_PCT = 0.05

# Material Quality Bonus (design doc section 3.1) -- scales with how many of the 10-20
# allowed copies were actually sacrificed, 0% at the minimum up to this cap at the maximum.
REFINE_MAX_MATERIAL_QUALITY_BONUS_PCT = 0.10


def material_quality_bonus_pct(quantity: int) -> float:
    span = REFINE_MAX_SACRIFICE - REFINE_MIN_SACRIFICE
    return REFINE_MAX_MATERIAL_QUALITY_BONUS_PCT * (max(0, min(quantity, REFINE_MAX_SACRIFICE) - REFINE_MIN_SACRIFICE) / span)


# Secondary banded roll splitting a success into Critical/Standard, or a failure into
# Minor/Major (design doc section 3.2) -- same "roll, then a secondary banded roll" shape
# accessories_data.DRAWBACK_ROLL_CHANCE already uses for its own secondary roll.
REFINE_CRITICAL_SHARE_OF_SUCCESS = 0.15
REFINE_MAJOR_FAILURE_SHARE_OF_FAILURE = 0.40

# Critical success shaves this many days off the rolled growth window (floored at
# GROWTH_DAYS_MIN) -- the design doc's own "reduced maturation-time requirement" option
# (its sibling option, "expanded baseline Satiety Capacity," would need a per-pet satiety
# cap field beyond this module's flat SATIETY_MAX, so this plan picks the one option that
# fits the existing schema rather than both).
CRITICAL_SUCCESS_GROWTH_DAYS_REDUCTION = 2

# Major failure's temporary Qi-regen debuff (design doc section 3.2's "Aperture Backlash") --
# reuses the existing buffs table's qi_multiplier_bonus mechanism with a negative value,
# capped well short of -100% so total_multiplier can never go negative or zero.
APERTURE_BACKLASH_QI_MULTIPLIER_PENALTY = -0.15
APERTURE_BACKLASH_DURATION_SECONDS = 30 * 60
MUTATED_GU_RESIDUE_ITEM_NAME = "Mutated Gu Residue"


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


def feed_category_and_tier(item_name: str) -> Optional[Tuple[str, int]]:
    """Which of the 5 FEED_CATEGORIES item_name belongs to, plus its tier -- or None if it
    isn't a feedable item at all. Ore/Herb/Beast Material/Beast Core all share the generic
    "Tier N ..." naming gathering.item_tier already parses; Beast Material and Beast Core
    share the exact same items.py subcategory ("Beast Material" covers both), so this checks
    the item's own name suffix to tell them apart instead of trusting subcategory. Pills use
    their own `rank` field (already set to the pill's tier at registration, see items.py's
    tiered-pill loop) rather than gathering.item_tier's "Tier N ..." naming, which pill names
    don't follow."""
    item = items.ITEMS.get(item_name)
    if item is None:
        return None
    if item.category == "Pills" and item.rank is not None:
        return "pill", item.rank
    tier = gathering.item_tier(item_name)
    if tier is None:
        return None
    if item_name.endswith("Beast Core"):
        return "beast_core", tier
    if item_name.endswith("Beast Material"):
        return "beast_material", tier
    if item_name.endswith("Ore"):
        return "ore", tier
    if item_name.endswith("Herb"):
        return "herb", tier
    return None


# Primary/secondary stat_bonuses keys each category's feeding grows (design doc section 6's
# own Primary/Secondary Stat columns, mapped onto real, already-consumed stat_bonuses keys
# rather than inventing new ones -- secondary is None where the doc's own label has no clean
# existing equivalent). All 4 non-Pill categories reuse keys already read generically via
# GameManager.compute_equipment_bonuses' pool; Pill leans toward the pet's OWN Cultivation-
# mode identity (cultivation_speed_pct) rather than a combat stat, matching the doc's own
# "Pills -> Refinement path" framing. Ore uses hp_pct (a +X% max-HP bonus, the same
# percentage-flavored key blacksmith percentage gear already rolls), NOT the flat integer
# "hp" key foundation stats use elsewhere -- every category here grows by tiny fractional
# deltas per feed (see BASE_YIELD_PER_TIER), which only makes sense as a percentage.
CATEGORY_STAT_KEYS: Dict[str, Tuple[str, Optional[str]]] = {
    "beast_material": ("physical_damage_pct", "dodge_chance_pct"),
    "beast_core": ("technique_damage_pct", "crit_damage_pct"),
    "ore": ("hp_pct", "deviation_resistance_pct"),
    "herb": ("insight_gain_pct", "cooldown_reduction_pct"),
    "pill": ("cultivation_speed_pct", "essence_regen_pct"),
}

# Stat yield per feed = BASE_YIELD_PER_TIER * tier * quantity * (1 + streak bonus), the
# secondary stat getting SECONDARY_YIELD_FRACTION of the primary's delta. A Qi Multiplier
# Pill fed alongside a normal material doubles that single feed's yield (design doc section
# 7's "Doubles stat accumulation yields for that feeding") -- Aptitude Enhancing/Healing
# pills' own doc-described catalyst effects ("permanently raises the growth ceiling" /
# "resets conflicting path points, or bypasses cooldown") are deliberately NOT implemented:
# neither maps onto a concept this schema actually has (no per-pet growth ceiling exists to
# raise, and "conflicting path points" is never defined anywhere in the source doc) -- both
# pills still feed normally as ordinary Pill-category materials instead, an honest scope cut
# rather than guessing at underspecified behavior.
BASE_YIELD_PER_TIER = 0.01
SECONDARY_YIELD_FRACTION = 0.5
QI_MULTIPLIER_PILL_FEED_YIELD_MULTIPLIER = 2.0

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


# -- Crystallization: species + Path (design doc sections 8-9) --------------------------

@dataclass
class GuPetSpecies:
    key: str
    name: str
    emoji: str
    tagline: str
    role_text: str
    path: str  # PATH_COMBAT | PATH_CULTIVATION
    # Cultivation-side species only -- {category: weight}, used by crystallize()'s nearest-
    # match against the pet's own fed_totals ratio. Combat-side species are instead picked by
    # a simple lean-threshold on the 2-category beast_material/beast_core split (see
    # COMBAT_ARCHETYPE_LEAN_THRESHOLD) since 3 archetypes over only 2 axes doesn't need (or
    # cleanly support) the same nearest-match math.
    preferred_categories: Dict[str, float] = field(default_factory=dict)


SPECIES_GRAND_FORGE_BEETLE = "grand_forge_beetle"
SPECIES_INK_SPITTER_CICADA = "ink_spitter_cicada"
SPECIES_BALANCE_FURNACE_TOAD = "balance_furnace_toad"
SPECIES_UNBOUND = "unbound_gu_pet"
SPECIES_VAMPIRIC_BEETLE = "vampiric_beetle"
SPECIES_FLAME_SPIT_MANTIS = "flame_spit_mantis"
SPECIES_CRAG_SHELL_TURTLE = "crag_shell_turtle"

# Design doc section 9's own 3 Cultivation-side species, plus an explicit fallback
# (SPECIES_UNBOUND) so crystallize() always resolves to something even when fed_totals'
# ore/herb/pill split doesn't lean toward any of the 3 -- see crystallize()'s own docstring.
SPECIES: Dict[str, GuPetSpecies] = {
    SPECIES_GRAND_FORGE_BEETLE: GuPetSpecies(
        key=SPECIES_GRAND_FORGE_BEETLE, name="Grand Forge Beetle", emoji="🪲",
        tagline="A tireless artisan-beast that hums with forge-heat.",
        role_text="Blacksmithing specialist — improves the stat budget on gear you forge.",
        path=PATH_CULTIVATION, preferred_categories={"ore": 0.55, "herb": 0.10, "pill": 0.35},
    ),
    SPECIES_INK_SPITTER_CICADA: GuPetSpecies(
        key=SPECIES_INK_SPITTER_CICADA, name="Ink-Spitter Cicada", emoji="🦗",
        tagline="Sings in a script only manual-scribes can read.",
        role_text="Manual crafting specialist — improves your odds of a Unique-rarity manual assembly.",
        path=PATH_CULTIVATION, preferred_categories={"ore": 0.10, "herb": 0.55, "pill": 0.35},
    ),
    SPECIES_BALANCE_FURNACE_TOAD: GuPetSpecies(
        key=SPECIES_BALANCE_FURNACE_TOAD, name="Balance-Furnace Toad", emoji="🐸",
        tagline="Never favors one craft over another.",
        role_text="Hybrid refinement specialist — a smaller boost to BOTH blacksmithing and manual crafting.",
        path=PATH_CULTIVATION, preferred_categories={"ore": 0.33, "herb": 0.33, "pill": 0.34},
    ),
    SPECIES_UNBOUND: GuPetSpecies(
        key=SPECIES_UNBOUND, name="Unbound Gu Pet", emoji="🐛",
        tagline="Never quite committed to one craft.",
        role_text="No specialty — a small, general cultivation-speed boost instead.",
        path=PATH_CULTIVATION, preferred_categories={},
    ),
    SPECIES_VAMPIRIC_BEETLE: GuPetSpecies(
        key=SPECIES_VAMPIRIC_BEETLE, name="Vampiric Beetle", emoji="🪲",
        tagline="Thrives on the wounds it carves.",
        role_text="Rend Claw applies a stacking Bleed; passively boosts Crit Chance and Crit Damage.",
        path=PATH_COMBAT,
    ),
    SPECIES_FLAME_SPIT_MANTIS: GuPetSpecies(
        key=SPECIES_FLAME_SPIT_MANTIS, name="Flame-Spit Mantis", emoji="🦋",
        tagline="Strikes once, precisely, through any guard.",
        role_text="Qi Burst pierces boss defense; passively boosts Armor Penetration.",
        path=PATH_COMBAT,
    ),
    SPECIES_CRAG_SHELL_TURTLE: GuPetSpecies(
        key=SPECIES_CRAG_SHELL_TURTLE, name="Crag-Shell Turtle", emoji="🐢",
        tagline="An unmoving wall between its bonded cultivator and death.",
        role_text="Automatically shields you when your HP drops low.",
        path=PATH_COMBAT,
    ),
}

# What fraction of the 2-category Combat split (beast_material vs beast_core) has to lean
# one way before crystallize() commits to that category's own archetype -- anything less
# lopsided lands on the balanced middle archetype (Crag-Shell Turtle) instead. 3 archetypes
# over 2 axes doesn't support (or need) the same nearest-match distance calc the 3-axis
# Cultivation side uses -- two clear leans plus one balanced middle covers the whole space.
COMBAT_ARCHETYPE_LEAN_THRESHOLD = 0.6


def crystallize(fed_totals: Dict[str, int]) -> Tuple[str, str]:
    """(species_key, path) a Gu Pet locks into once its growth phase completes, purely from
    the RATIO of fed_totals (see this module's own docstring -- the sacrificed Gu at
    acquisition never factors in at all). Always returns something real, even for a
    never-fed pet (shouldn't happen given feed_gu_pet's own gate, but this stays total
    rather than raising)."""
    total = sum(fed_totals.get(cat, 0) for cat in FEED_CATEGORIES)
    if total == 0:
        return SPECIES_UNBOUND, PATH_CULTIVATION

    combat_share = sum(fed_totals.get(cat, 0) for cat in COMBAT_PATH_CATEGORIES) / total
    # Design doc section 8.1: Beast Material/Core >=50% -> Combat; Ore/Herb/Pill >=50% ->
    # Cultivation/Artisan. The two buckets always sum to 100%, so an exact 50/50 split has to
    # pick a side -- this defaults to Cultivation/Artisan, the single source of truth for
    # that tie-break.
    path = PATH_COMBAT if combat_share > 0.5 else PATH_CULTIVATION

    if path == PATH_COMBAT:
        beast_material = fed_totals.get("beast_material", 0)
        beast_core = fed_totals.get("beast_core", 0)
        material_total = beast_material + beast_core
        material_share = beast_material / material_total if material_total else 0.5
        if material_share >= COMBAT_ARCHETYPE_LEAN_THRESHOLD:
            species = SPECIES_VAMPIRIC_BEETLE
        elif material_share <= 1 - COMBAT_ARCHETYPE_LEAN_THRESHOLD:
            species = SPECIES_FLAME_SPIT_MANTIS
        else:
            species = SPECIES_CRAG_SHELL_TURTLE
        return species, path

    cult_total = sum(fed_totals.get(cat, 0) for cat in CULTIVATION_PATH_CATEGORIES)
    if cult_total == 0:
        return SPECIES_UNBOUND, path
    fed_ratio = {cat: fed_totals.get(cat, 0) / cult_total for cat in CULTIVATION_PATH_CATEGORIES}
    best_species, best_distance = None, None
    for species_key in (SPECIES_GRAND_FORGE_BEETLE, SPECIES_INK_SPITTER_CICADA, SPECIES_BALANCE_FURNACE_TOAD):
        preferred = SPECIES[species_key].preferred_categories
        distance = sum(abs(fed_ratio[cat] - preferred.get(cat, 0)) for cat in CULTIVATION_PATH_CATEGORIES)
        if best_distance is None or distance < best_distance:
            best_species, best_distance = species_key, distance
    return best_species, path


# -- Cultivation Mode specialty bonuses (design doc section 10) -------------------------

# Rolled ONCE, at crystallization (see GameManager.crystallize_gu_pet), into the SAME
# stat_bonuses dict growth-feeding already writes to -- gear_budget_bonus_pct/manual_rarity_
# bonus_pct then ride GameManager._gu_pet_cultivation_bonus the same generic "root OR
# physique OR Gu OR active Cultivation-Mode Gu Pet" shape _trait_bonus already uses for
# every other such key. Combat-side species (Vampiric Beetle/Flame-Spit Mantis/Crag-Shell
# Turtle) return {} here -- their own specialty bonuses are Phase 7's concern.
TOAD_HYBRID_FRACTION = 0.5  # Balance-Furnace Toad's "smaller boost to BOTH" (see its role_text)
UNBOUND_CULTIVATION_SPEED_PCT_BASE = 0.02  # Unbound's own small flat fallback bonus (see its role_text), scaled by rank below


def roll_specialty_bonus(species_key: str, rank: int, rng: Optional[random.Random] = None) -> Dict[str, float]:
    r = rng or random
    scaling = rank_scaling(rank)
    if species_key == SPECIES_GRAND_FORGE_BEETLE:
        lo, hi = scaling["blacksmith_budget_bonus_range"]
        return {"gear_budget_bonus_pct": r.uniform(lo, hi)}
    if species_key == SPECIES_INK_SPITTER_CICADA:
        lo, hi = scaling["manual_unique_bonus_range"]
        return {"manual_rarity_bonus_pct": r.uniform(lo, hi)}
    if species_key == SPECIES_BALANCE_FURNACE_TOAD:
        blo, bhi = scaling["blacksmith_budget_bonus_range"]
        mlo, mhi = scaling["manual_unique_bonus_range"]
        return {
            "gear_budget_bonus_pct": r.uniform(blo, bhi) * TOAD_HYBRID_FRACTION,
            "manual_rarity_bonus_pct": r.uniform(mlo, mhi) * TOAD_HYBRID_FRACTION,
        }
    if species_key == SPECIES_UNBOUND:
        return {"cultivation_speed_pct": UNBOUND_CULTIVATION_SPEED_PCT_BASE * (rank / MAX_RANK)}
    return {}


# -- Combat Mode specialty bonuses (design doc section 10) ------------------------------

# Unlike the Cultivation-side specialty bonuses above (rolled ONCE at crystallization, into
# the pet's own stat_bonuses), these are a FIXED per-species base value scaled LIVE by
# GU_PET_RANK_SCALING[rank]["combat_multiplier"] and the current satiety multiplier at
# consumption time (see GameManager.compute_equipment_bonuses' own Combat-Mode Gu Pet block)
# -- no RNG roll needed since combat_multiplier already carries the rank-scaling job.
# gu_pet_bleed_damage_pct is deliberately a NEW, distinctly-named key from monsters.py's own
# bleed_damage_pct (an ability MONSTERS use against players, the opposite direction) -- see
# hunt.py/team_battle.py/tournament.py's own Gu Pet bleed-tick blocks, which reuse
# dao_paths.fire_burn_tick_damage/FIRE_BURN_TICKS's exact tick-engine shape (that constant is
# the shared tick-count for every DoT-style effect in this codebase, not fire-specific --
# Blazing Glory Sunfire Physique's own independent burn already reuses it the same way).
# Grand Forge Beetle/Ink-Spitter Cicada/Balance-Furnace Toad/Unbound (the Cultivation-side
# species) intentionally have no entry here -- their own specialty bonuses are the section
# just above.
COMBAT_SPECIALTY_BASE_VALUES: Dict[str, Dict[str, float]] = {
    SPECIES_VAMPIRIC_BEETLE: {"gu_pet_bleed_damage_pct": 0.08, "crit_chance_pct": 0.03, "crit_damage_pct": 0.10},
    SPECIES_FLAME_SPIT_MANTIS: {"armor_penetration_pct": 0.12},
}
# Crag-Shell Turtle's own "Automatically shields you when your HP drops low" role_text --
# reuses apply_encounter_start_bonuses' EXISTING encounter-start shield mechanism (the same
# one accessories with an encounter_shield effect already grant) instead of building a new
# HP-threshold proc system from scratch, same "adapt to what already exists, note the trade-
# off" style this codebase's own accessories_data.py uses throughout.
TURTLE_SHIELD_DEF_PCT_BASE = 0.15
TURTLE_SHIELD_DURATION_SECONDS = 180


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

# Upkeep feeding for a MATURE pet (see GameManager.feed_gu_pet_satiety) -- unlike growth-
# phase feed_gu_pet, this has no daily gate (satiety is an ongoing resource, not a one-time
# growth milestone) but DOES require the item's tier to exactly match GU_PET_RANK_SCALING
# [pet_rank]["satiety_material_tier"], any of the 5 feed categories.
SATIETY_REFILL_PER_ITEM = 10.0


def satiety_band(satiety: float) -> Tuple[float, str]:
    """(output_multiplier, label) for a given satiety value."""
    for low, high, multiplier, label in SATIETY_BANDS:
        if low <= satiety <= high:
            return multiplier, label
    return 0.0, "Starving"


# -- Combat/Cultivation Mode toggle (design doc section 13) ------------------------------

# Its own dedicated players.last_gu_pet_mode_switch_ts column, not GameManager._check_
# cooldown -- that helper is for player-ACTION cooldowns (one /hunt, one /gamble, ...), not a
# per-pet state toggle with no action-log entry of its own. MODE_SWITCH_FEE_SPIRIT_STONES is
# genuinely new to this codebase -- no existing "pay to skip a cooldown" mechanic to reuse,
# so this is deliberately simple: a flat fee, no formula, priced well under AVATAR_SOUL_
# REROLL_COST (200) since skipping a 10-minute wait is a minor convenience, not a reroll of
# something valuable.
MODE_SWITCH_COOLDOWN_SECONDS = 10 * 60
MODE_SWITCH_FEE_SPIRIT_STONES = 50


# -- AI portrait flavor traits (see game/gu_pet_images.py's build_pet_prompt) ------------

# Neither source spec defines where an image prompt's element/color-palette/temperament
# should come from -- these are small fixed word-bank tables derived from species+path,
# the same idiom accessories_data.py's own NAME_MATERIALS/NAME_CONCEPTS use for accessory/
# artifact name generation, rather than a separate trait-roll system.
FLAVOR_ELEMENT: Dict[str, str] = {
    SPECIES_GRAND_FORGE_BEETLE: "earth and molten metal",
    SPECIES_INK_SPITTER_CICADA: "ink and starlight",
    SPECIES_BALANCE_FURNACE_TOAD: "balanced yin-yang qi",
    SPECIES_UNBOUND: "raw, undirected spirit qi",
    SPECIES_VAMPIRIC_BEETLE: "crimson blood qi",
    SPECIES_FLAME_SPIT_MANTIS: "searing flame",
    SPECIES_CRAG_SHELL_TURTLE: "ancient stone",
}
FLAVOR_COLOR_PALETTE: Dict[str, str] = {
    SPECIES_GRAND_FORGE_BEETLE: "burnished bronze and ember-orange",
    SPECIES_INK_SPITTER_CICADA: "midnight indigo and pale jade",
    SPECIES_BALANCE_FURNACE_TOAD: "amber and deep teal",
    SPECIES_UNBOUND: "shifting silver-grey",
    SPECIES_VAMPIRIC_BEETLE: "black carapace veined with crimson",
    SPECIES_FLAME_SPIT_MANTIS: "obsidian and molten gold",
    SPECIES_CRAG_SHELL_TURTLE: "mossy grey stone and jade",
}
FLAVOR_TEMPERAMENT_BY_PATH: Dict[str, str] = {
    PATH_CULTIVATION: "serene and contemplative",
    PATH_COMBAT: "fierce and battle-worn",
}
# Rank-scaled framing, echoing GU_PET_RANK_TO_RARITY's own 7-tier ladder without duplicating
# its wording -- a Rank I pet reads as freshly hatched, a Rank VII pet as a legend.
FLAVOR_RANK_INTENSITY: Dict[int, str] = {
    1: "a young, newly-hatched", 2: "a young, newly-hatched",
    3: "a matured", 4: "a powerful, battle-tested",
    5: "a powerful, battle-tested", 6: "an ancient, legendary",
    7: "a mythical, world-shaking",
}
