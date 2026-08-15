"""
Static catalog for the Manual/Inheritance/Secret Realm/Dream Realm system — same pattern as
items.ITEMS / equipment.EQUIPMENT: everything here is read-only game content, keyed by a
stable id, with per-player ownership tracked separately in the database (see
database.py's player_pages/manuals tables).

Ranks 1-3 are hand-authored per the design doc's own worked examples (section 6 and the
rank pool tables). Ranks 4-7 use the same doc's own named example pools (section 11) but
have their categories/tags/power values assigned procedurally (see _augment_rank) rather
than hand-tuned one at a time — this matches the design doc's own stated intent (section 19,
build-order point 9: "Expand to Rank 4-7 content gradually... keep high-rank Unique rewards
authored rather than fully random"). The generation ENGINE (manual_gen.py) fully supports
all 7 ranks either way; what varies is how much hand-authored texture each rank's pages have.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# -- Page categories (see design doc section 6) --------------------------------------------
# (category, required_min, required_max) — required_max is a soft cap on how many of that
# category a single manual should carry, not a hard schema limit.
PAGE_CATEGORIES = [
    "Foundation", "Circulation", "Refinement", "Breakthrough", "Offense", "Defense",
    "Movement", "Mind", "Utility", "Restriction",
]
REQUIRED_CATEGORY_COUNT = {
    "Foundation": (1, 1), "Circulation": (1, 1), "Refinement": (0, 1), "Breakthrough": (0, 1),
    "Offense": (0, 2), "Defense": (0, 2), "Movement": (0, 1), "Mind": (0, 1),
    "Utility": (0, 2), "Restriction": (0, 1),
}
# Categories select_page can pick from when filling "optional" slots — Foundation/
# Circulation/Breakthrough are handled explicitly by manual_gen.generate_manual instead.
OPTIONAL_CATEGORIES = ["Refinement", "Offense", "Defense", "Movement", "Mind", "Utility", "Restriction"]

# -- Path tags (see design doc section 6) ---------------------------------------------------
PATH_TAG_FAMILIES = {
    "Core cultivation": ["human", "heaven", "earth", "qi", "essence", "aperture", "immortal"],
    "Physical": ["strength", "transformation", "metal", "bone", "blood", "poison", "food"],
    "Mental / spiritual": ["wisdom", "soul", "dream", "emotion", "information", "rule", "restriction"],
    "Elemental / natural": ["fire", "water", "wood", "earth", "wind", "lightning", "ice", "moon", "sun", "star"],
    "Combat": ["sword", "blade", "spear", "bow", "weapon", "theft", "enslavement", "sound"],
    "Esoteric": ["time", "space", "luck", "formation", "refinement", "painting", "pill", "phantom"],
}
ALL_PATH_TAGS = [tag for tags in PATH_TAG_FAMILIES.values() for tag in tags]
# a couple of tags used below that aren't in the doc's own family table but are needed for
# a couple of the worked example pages (movement, healing) — kept minimal and additive.
ALL_PATH_TAGS += ["movement", "healing", "shadow"]
# Rank 8 (White Heaven, see content/manuals/rank8_pages.py) needs 3 tags that don't exist
# yet -- "light" (gu_types.py already uses "light" as a Gu-type tag in ITS OWN separate,
# unvalidated vocabulary, but never added it here despite documentation implying it had),
# "holy", "life". "heavenly" is deliberately NOT added -- rank 8 pages reuse the existing
# "heaven" tag instead of a near-duplicate.
ALL_PATH_TAGS += ["light", "holy", "life"]

# -- Manual rank table (see design doc section 5) -------------------------------------------
@dataclass
class RankSpec:
    page_slots: tuple  # (min, max)
    power_budget: int
    cultivation_bonus_range: tuple  # (min_pct, max_pct)


MANUAL_RANK_TABLE: Dict[int, RankSpec] = {
    1: RankSpec((3, 4), 10, (3, 8)),
    2: RankSpec((4, 5), 18, (6, 13)),
    3: RankSpec((5, 6), 30, (10, 20)),
    4: RankSpec((6, 7), 48, (15, 28)),
    # Ranks 5-7 buffed per explicit request: the original curve's own step ratio actually
    # SHRANK every rank (1.8x, 1.67x, 1.6x, 1.5x, 1.46x, 1.43x -- 72/105/150), making the top
    # of the ladder proportionally the LEAST rewarded part of it. Restored to a real growth
    # curve (~1.6-1.7x per step again, matching the low end) now that rank is honestly earned
    # per page rather than inherited from a single high-rank page (see assemble_manual's rank
    # averaging) -- a genuine Rank 7 manual is worth reaching for.
    5: RankSpec((7, 8), 95, (22, 38)),
    6: RankSpec((8, 9), 150, (30, 50)),
    7: RankSpec((9, 10), 230, (40, 65)),
    # Rank 8 (White Heaven only, see content/manuals/rank8_pages.py) continues the same
    # ~1.5-1.6x growth the 5-6-7 steps already use (150/95≈1.58, 230/150≈1.53) -- a starting
    # point for empirical tuning, not a final value.
    8: RankSpec((10, 11), 350, (55, 85)),
}
MAX_MANUAL_RANK = 8

# -- Gamble a completed manual for a page (2026-08-15, /manual's own "Gamble" button) -------
# Destroys a manual for a guaranteed page of the player's CHOSEN category, but at a rank
# that's rolled, not picked -- the actual "gamble." Weighted geometrically around (not capped
# by) the manual's own rank, so a low-rank manual keeps a real, if small, shot at the very top,
# and a high-rank manual mostly (but not purely) gets back what it's worth. This is the whole
# point of the button: converting a manual you don't need into one of a category you do, at
# roughly the same power level, with some variance either way.
GAMBLE_PAGE_RANK_BASE_WEIGHT = 100
GAMBLE_PAGE_RANK_DECAY_PER_STEP = 0.35


def gamble_page_rank_weights(manual_rank: int) -> Dict[int, float]:
    """{page_rank: weight} across every real page rank (1-MAX_MANUAL_RANK), peaked at
    page_rank == manual_rank and decaying by GAMBLE_PAGE_RANK_DECAY_PER_STEP per rank of
    distance in either direction."""
    return {
        page_rank: GAMBLE_PAGE_RANK_BASE_WEIGHT * (GAMBLE_PAGE_RANK_DECAY_PER_STEP ** abs(page_rank - manual_rank))
        for page_rank in range(1, MAX_MANUAL_RANK + 1)
    }


# -- Rarity (see design doc section 7) -------------------------------------------------------
RARITY_ORDER = ["Common", "Uncommon", "Rare", "Epic", "Legendary", "Mythic", "Divine", "Unique"]
RARITY_STARS = {rarity: i + 1 for i, rarity in enumerate(RARITY_ORDER)}

RARITY_EFFICIENCY = {
    "Common": 0.85, "Uncommon": 0.95, "Rare": 1.05, "Epic": 1.15,
    "Legendary": 1.28, "Mythic": 1.42, "Divine": 1.58, "Unique": 1.75,
}
RARITY_DEFECT_CHANCE = {
    "Common": 0.35, "Uncommon": 0.28, "Rare": 0.20, "Epic": 0.14,
    "Legendary": 0.09, "Mythic": 0.06, "Divine": 0.04, "Unique": 0.0,
}
RARITY_HIDDEN_EFFECT_CHANCE = {
    "Common": 0.0, "Uncommon": 0.02, "Rare": 0.06, "Epic": 0.12,
    "Legendary": 0.22, "Mythic": 0.35, "Divine": 0.55, "Unique": 1.0,
}
# Base drop weights (section 9) — item rarity once a reward category is already chosen.
RARITY_BASE_WEIGHTS = {
    "Common": 45.0, "Uncommon": 25.0, "Rare": 14.0, "Epic": 8.0,
    "Legendary": 4.5, "Mythic": 2.2, "Divine": 1.0, "Unique": 0.3,
}

# /assemble_manual's own craft-time rarity roll (see manager.assemble_manual) -- deliberately
# far more generous than RARITY_BASE_WEIGHTS' loot odds above (Unique there is 0.3/100 = 0.3%,
# vanishingly rare; here it's a full 10% per explicit request) since this is the payoff for a
# player's own deliberate page choices, not a passive loot roll. Still strictly descending so
# Unique reads as the rarest slice of the eight, same RARITY_ORDER either way.
ASSEMBLE_RARITY_WEIGHTS = {
    "Common": 25, "Uncommon": 20, "Rare": 16, "Epic": 12,
    "Legendary": 9, "Mythic": 5, "Divine": 3, "Unique": 10,
}


def weighted_rarity_choices(base_weights: Dict[str, float], bonus_pct: float) -> Dict[str, float]:
    """base_weights shifted toward the top of RARITY_ORDER by bonus_pct (see
    GameManager.assemble_manual's Ink-Spitter Cicada/Balance-Furnace Toad gu_pet.
    manual_rarity_bonus_pct hook) -- each rarity's weight is scaled up by (1 + bonus_pct *
    its own star tier / len(RARITY_ORDER)), so Unique (the top of the ladder) shifts the most
    and Common barely moves at all, rather than a flat rescale that would leave the
    distribution's shape unchanged. A no-op copy when bonus_pct is 0."""
    if not bonus_pct:
        return dict(base_weights)
    return {
        rarity: weight * (1 + bonus_pct * (RARITY_STARS[rarity] / len(RARITY_ORDER)))
        for rarity, weight in base_weights.items()
    }

# -- Page refinement (see design doc section 6) ----------------------------------------------
@dataclass
class RefinementSpec:
    duplicate_requirement: int  # additional duplicates needed to reach this level from the previous one
    effectiveness_bonus_pct: float
    stability_bonus: int
    flaw_repair_chance: float


REFINEMENT_LEVELS = ["Unstudied", "Studied", "Copied", "Annotated", "Perfected", "True Meaning"]
# effectiveness_bonus_pct/stability_bonus/flaw_repair_chance are spent at /assemble_manual time
# (see manual_gen.refinement_bonus_totals) against whichever specific page copies get consumed —
# a big payoff on purpose, since duplicates otherwise have no use besides refining and the
# design brief always intended refinement to meaningfully reward the grind, not just relabel
# the page.
REFINEMENT_SPEC: Dict[str, RefinementSpec] = {
    "Unstudied": RefinementSpec(0, 0.0, 0, 0.0),
    "Studied": RefinementSpec(0, 0.0, 0, 0.0),  # insight-cost, not duplicate-gated — see manual_gen.study_page
    "Copied": RefinementSpec(1, 0.20, 4, 0.15),
    "Annotated": RefinementSpec(2, 0.50, 10, 0.35),
    "Perfected": RefinementSpec(4, 1.00, 20, 0.75),
    # Was a dead stub (all-zero, explicitly refused by GameManager.refine_page) since this
    # level was first added — "rare insight item / inheritance-gated" never actually got a
    # real mechanic built. Unlocked (2026-08-14) as a real, bigger duplicate-gated step past
    # Perfected, per explicit request ("refine them past perfected for even more stats") —
    # same duplicate-spending flow as every level below it, just a steeper cost/payoff.
    "True Meaning": RefinementSpec(6, 1.50, 35, 1.00),
}
NEXT_REFINEMENT = {level: REFINEMENT_LEVELS[i + 1] for i, level in enumerate(REFINEMENT_LEVELS[:-1])}

# -- Coherence bands (see design doc section 5) -----------------------------------------------
@dataclass
class CoherenceBand:
    label: str
    power_multiplier: float
    deviation_modifier: int


def _coherence_band(score: int) -> CoherenceBand:
    score = max(0, min(100, score))
    if score <= 29:
        return CoherenceBand("Chaotic", 0.80, 15)
    if score <= 49:
        return CoherenceBand("Flawed", 0.90, 8)
    if score <= 69:
        return CoherenceBand("Stable", 1.00, 0)
    if score <= 84:
        return CoherenceBand("Harmonious", 1.08, -5)
    if score <= 94:
        return CoherenceBand("Perfected", 1.15, -8)
    return CoherenceBand("True Inheritance", 1.22, -10)


# -- Flaws (see design doc section 8) ----------------------------------------------------------
@dataclass
class Flaw:
    flaw_id: str
    severity: str  # Minor, Moderate, Major
    text: str
    tags: List[str] = field(default_factory=list)
    compensation_budget: int = 0
    hidden: bool = False


FLAW_SEVERITY_BUDGET = {"Minor": (1, 3), "Moderate": (4, 8), "Major": (9, 15)}

FLAWS: Dict[str, Flaw] = {
    "night_only": Flaw("night_only", "Minor", "Works only at night.", ["moon", "shadow"], 2),
    "resource_drain": Flaw("resource_drain", "Minor", "+5% resource use.", [], 2),
    "regional_weakness": Flaw("regional_weakness", "Minor", "Reduced effect outside its native region.", [], 3, hidden=True),
    "periodic_damage": Flaw("periodic_damage", "Moderate", "Deals periodic damage to the user.", ["blood"], 5),
    "equipment_lockout": Flaw("equipment_lockout", "Moderate", "Incompatible with one equipment class.", [], 6, hidden=True),
    "reduced_healing": Flaw("reduced_healing", "Moderate", "Reduced healing received.", [], 5),
    "oath_upkeep": Flaw("oath_upkeep", "Moderate", "Requires a matching resource periodically.", ["restriction"], 7),
    "breakthrough_backlash": Flaw("breakthrough_backlash", "Major", "Failed breakthroughs deal backlash damage.", [], 12),
    "permanent_scar": Flaw("permanent_scar", "Major", "Leaves a scar until repaired.", [], 11, hidden=True),
    "rare_upkeep": Flaw("rare_upkeep", "Major", "Consumes a rare resource to maintain.", [], 13),
}

# -- Manual page dataclass + catalog -----------------------------------------------------------
@dataclass
class ManualPage:
    page_id: str
    name: str
    category: str
    rank: int
    tags: List[str]
    power_value: int
    base_effects: Dict[str, float] = field(default_factory=dict)
    flaw_pool: List[str] = field(default_factory=list)
    source_theme: Optional[str] = None
    description: str = ""


PAGES: Dict[str, ManualPage] = {}


def _slug(name: str) -> str:
    return "pg_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _register(name, category, rank, tags, power_value, base_effects, flaw_pool=None, source_theme=None, description=""):
    page_id = _slug(name)
    PAGES[page_id] = ManualPage(
        page_id=page_id, name=name, category=category, rank=rank, tags=tags, power_value=power_value,
        base_effects=base_effects, flaw_pool=flaw_pool or [], source_theme=source_theme, description=description,
    )
    return page_id


# -- Rank 1-3: hand-authored core pages (design doc sections 6 and 11) -------------------------
_register(
    "Breath of the Empty Aperture", "Foundation", 1, ["qi", "aperture", "human"], 4,
    {"cultivation_gain_pct": 5.0, "essence_capacity_pct": 4.0},
    flaw_pool=["reduced_healing"], description="+5% cultivation gain and +4% essence capacity.",
)
_register(
    "Nine Coiling Rivers", "Circulation", 1, ["water", "qi", "movement"], 4,
    {"cultivation_speed_pct": 8.0, "essence_recovery_pct": 4.0},
    flaw_pool=["regional_weakness"], description="+8% cultivation speed; +4% essence recovery.",
)
_register(
    "River Pebble Foundation", "Foundation", 1, ["water", "qi"], 3,
    {"cultivation_gain_pct": 4.0}, description="A gentle, forgiving foundation principle.",
)
_register(
    "Gentle Stream Circulation", "Circulation", 1, ["water", "movement"], 3,
    {"cultivation_speed_pct": 5.0, "essence_recovery_pct": 3.0},
)
_register(
    "Patient Gate Breakthrough", "Breakthrough", 1, ["water", "qi"], 3,
    {"breakthrough_success_pct": 3.0},
)
_register(
    "Beast-Blood Foundation", "Foundation", 1, ["blood", "strength"], 4,
    {"cultivation_gain_pct": 3.0, "hp_pct": 4.0},
)
_register(
    "Iron Hide Circulation", "Circulation", 1, ["metal", "strength"], 3,
    {"cultivation_speed_pct": 3.0, "hp_pct": 5.0},
)
_register(
    "Strong Back Stance", "Offense", 1, ["strength"], 3,
    {"physical_damage_pct": 4.0},
)
_register(
    "Charging Gate Notes", "Breakthrough", 1, ["strength"], 3,
    {"breakthrough_success_pct": 2.0},
    flaw_pool=["periodic_damage"],
)
_register(
    "Clear Mind Verse", "Mind", 1, ["wisdom", "soul"], 3,
    {"insight_gain_pct": 6.0, "cooldown_reduction_pct": 2.0},
)
_register(
    "First-Step Breakthrough Notes", "Breakthrough", 1, ["human", "qi"], 3,
    {"breakthrough_success_pct": 3.0},
)

_register(
    "Iron Blood Furnace", "Refinement", 3, ["blood", "strength", "refinement"], 9,
    {"essence_purity_pct": 10.0, "momentum_on_damage": 1.0},
    flaw_pool=["oath_upkeep"],
    description="+10% essence purity; damage taken adds temporary cultivation momentum.",
)
_register(
    "Moon-Shadow Step", "Movement", 1, ["moon", "shadow", "movement"], 4,
    {"dodge_chance_pct": 6.0, "night_escape_bonus": 1.0},
    flaw_pool=["night_only"],
    description="+6% dodge and improved escape checks at night.",
)
_register(
    "Heaven-Splitting Thought", "Offense", 4, ["wisdom", "sword", "information"], 12,
    {"technique_damage_pct": 7.0, "expose_weakness": 1.0},
    description="+7% technique damage; first attack exposes one enemy weakness.",
)
_register(
    "Jade Heart Barrier", "Defense", 3, ["wood", "emotion", "healing"], 9,
    {"hp_pct": 8.0, "deviation_resistance_pct": 5.0},
    flaw_pool=["equipment_lockout"],
    description="+8% maximum HP and +5% deviation resistance.",
)
_register(
    "Silent Devouring Vow", "Restriction", 1, ["theft", "food", "restriction"], 8,
    {"budget_bonus": 8.0},
    flaw_pool=["oath_upkeep"],
    description="+8 budget if the cultivator consumes a matching resource daily.",
)

# Twin/Rank 2 core set
_register(
    "Twin Current Circulation", "Circulation", 2, ["water", "fire", "qi"], 6,
    {"cultivation_speed_pct": 9.0, "essence_recovery_pct": 5.0},
)
_register(
    "Copper Furnace Body", "Foundation", 2, ["metal", "refinement"], 6,
    {"cultivation_gain_pct": 6.0, "hp_pct": 6.0},
)
_register(
    "Moon Veil Step", "Movement", 2, ["moon", "movement"], 5,
    {"dodge_chance_pct": 5.0},
)
_register(
    "Blood Echo Strike", "Offense", 2, ["blood", "sound"], 6,
    {"physical_damage_pct": 8.0},
    flaw_pool=["periodic_damage"],
)
_register(
    "Stable Second Aperture Notes", "Breakthrough", 2, ["qi", "aperture"], 5,
    {"breakthrough_success_pct": 4.0},
)

# Rank 3 remainder
_register(
    "Threefold Sea Compression", "Refinement", 3, ["water", "refinement"], 9,
    {"essence_purity_pct": 9.0, "resource_reduction_pct": 5.0},
)
_register(
    "Soul Lantern Meditation", "Mind", 3, ["soul", "wisdom"], 8,
    {"insight_gain_pct": 10.0},
)
_register(
    "Hundred-Step Sword Breath", "Offense", 3, ["sword", "wind"], 9,
    {"technique_damage_pct": 9.0},
)
_register(
    "Red Gate Breakthrough", "Breakthrough", 3, ["blood", "fire"], 8,
    {"breakthrough_success_pct": 5.0},
)
_register(
    "Empty Moon Foundation", "Foundation", 3, ["moon", "shadow"], 9,
    {"cultivation_gain_pct": 9.0},
)
_register(
    "Moon-Shadow Circulation", "Circulation", 3, ["moon", "shadow", "movement"], 8,
    {"cultivation_speed_pct": 9.0},
)
_register(
    "Veiled Step", "Movement", 3, ["shadow", "movement"], 7,
    {"dodge_chance_pct": 7.0},
)
_register(
    "Silent Blade", "Offense", 3, ["shadow", "sword"], 8,
    {"first_strike_night_bonus_pct": 8.0},
    flaw_pool=["night_only"],
)
_register(
    "Eclipse Breakthrough", "Breakthrough", 3, ["moon", "shadow"], 8,
    {"breakthrough_success_pct": 6.0},
)


# -- Ranks 4-7: procedurally augmented from the design doc's own named example pools ------------
_TAG_KEYWORDS = {
    "aperture": ["aperture"], "qi": ["qi", "breath", "star calculation"], "essence": ["essence"],
    "strength": ["strength", "iron", "bone", "back", "mountain", "crushing"], "blood": ["blood"],
    "metal": ["copper", "iron", "metal", "bronze", "star iron", "law-web"],
    "wisdom": ["wisdom", "thought", "calculation", "star", "domain"], "soul": ["soul", "spirit", "lantern", "palace"],
    "dream": ["dream"], "emotion": ["heart"],
    "fire": ["fire", "furnace", "flame", "crimson", "law furnace"], "water": ["water", "river", "sea", "tide", "time-ripple"],
    "wood": ["wood", "jade", "forest"], "earth": ["earth", "mountain", "domain core"],
    "wind": ["wind"], "lightning": ["thunder", "lightning"], "ice": ["ice", "frost"],
    "moon": ["moon"], "sun": ["sun", "solar"], "star": ["star", "starfall"],
    "sword": ["sword", "blade", "saber", "greatsword"], "spear": ["spear", "halberd"],
    "weapon": ["weapon", "gauntlet", "hammer", "banner"],
    "theft": ["devour"], "enslavement": ["seal", "bind", "web"], "sound": ["echo", "resonance", "bell", "chime"],
    "time": ["time", "tribulation", "worn"], "space": ["void", "space", "anchor", "crossing"],
    "luck": ["fate"], "formation": ["formation", "law", "web", "resonance"],
    "refinement": ["refinement", "furnace", "conversion", "compression", "engraving"],
    "human": ["human"], "immortal": ["immortal", "heaven", "sovereign", "divine", "tribulation"],
    "movement": ["step", "escape", "walk", "shadow", "phantom", "mist", "crossing"],
    "healing": ["heart"],
}

# (rank pool page names from design doc section 11)
_RANK_POOL_PAGE_NAMES = {
    4: ["Seven Furnace Conversion", "Phantom River Escape", "Mountain-Heart Immovability", "Star Calculation Chapter"],
    5: ["Dao Mark Engraving Chapter", "Five Domain Circulation", "Soul Palace Foundation", "Crimson Law Furnace", "Time-Worn Breakthrough Record"],
    6: ["Immortal Essence Conversion", "Heaven-Earth Resonance", "Myriad Soul Dominion", "Void Crossing Method", "Tribulation Tempering Chapter"],
    7: ["Heaven-Defying Foundation", "Boundless Law Circulation", "River of Time Reversal", "Sovereign Body Chapter", "Fate-Breaking Final Verse"],
}
# Round-robin category assignment per rank pool, always opening on Foundation/Circulation/
# Breakthrough so generate_manual's required-category fill always has real options at every rank.
_ROUND_ROBIN_CATEGORIES = ["Foundation", "Circulation", "Breakthrough", "Offense", "Defense", "Mind", "Refinement"]

_EFFECT_KEY_BY_CATEGORY = {
    "Foundation": "cultivation_gain_pct", "Circulation": "cultivation_speed_pct",
    "Refinement": "essence_purity_pct", "Breakthrough": "breakthrough_success_pct",
    "Offense": "technique_damage_pct", "Defense": "hp_pct", "Movement": "dodge_chance_pct",
    "Mind": "insight_gain_pct", "Utility": "utility_effect_pct", "Restriction": "budget_bonus",
}


def _infer_tags(name: str) -> List[str]:
    lower = name.lower()
    tags = [tag for tag, keywords in _TAG_KEYWORDS.items() if any(kw in lower for kw in keywords)]
    return tags or ["qi"]  # every page needs at least one tag to ever match a primary path


def _augment_rank(rank: int, names: List[str]):
    spec = MANUAL_RANK_TABLE[rank]
    per_page_power = max(2, round(spec.power_budget / max(1, spec.page_slots[1])))
    for i, name in enumerate(names):
        category = _ROUND_ROBIN_CATEGORIES[i % len(_ROUND_ROBIN_CATEGORIES)]
        tags = _infer_tags(name)
        effect_key = _EFFECT_KEY_BY_CATEGORY[category]
        effect_value = round(per_page_power * 1.15, 1)  # rough power_value -> pct conversion, refined by manual_gen's budget math
        _register(name, category, rank, tags, per_page_power, {effect_key: effect_value})


for _rank, _names in _RANK_POOL_PAGE_NAMES.items():
    _augment_rank(_rank, _names)
del _rank, _names

# Content-package Rank 1 pages (see game/content/manuals/rank1_pages.py) — imported here,
# after _register is already defined and every page above is already registered, rather
# than at module top: rank1_pages.py itself does `from ...manual_data import _register`,
# and by the time THIS line runs, this module (game.manual_data) is already in sys.modules
# with _register bound as an attribute — same late-import trick items.py/monsters.py use
# for their own content-package merges. rank1_pages.py registers directly into PAGES via
# _register's own side effect, so nothing needs to be assigned here.
from .content.manuals import rank1_pages  # noqa: E402, F401
from .content.manuals import rank2_3_pages  # noqa: E402, F401
from .content.manuals import rank4_7_pages  # noqa: E402, F401
from .content.manuals import rank8_pages  # noqa: E402, F401


# -- Name generation (see design doc section 7) --------------------------------------------------
NAME_PREFIXES = ["Ninefold", "Silent", "Crimson", "Boundless", "Hollow", "Jade", "Starfall", "Heaven-Defying"]
NAME_CORE_IMAGES = ["River", "Furnace", "Cicada", "Moon", "Mountain", "Mirror", "Dragon", "Heart", "Aperture"]
NAME_METHOD_WORDS = ["Scripture", "Canon", "Art", "Sutra", "Record", "Method", "Manual", "True Inheritance"]


# Every page's display name is unique across the whole catalog (verified in
# test_manual_pages_by_name.py) -- used by cog.py's /grant_manual_page so admins can look a
# page up by the name they'd actually see in-game, not its internal pg_... slug id.
PAGES_BY_NAME: Dict[str, ManualPage] = {page.name: page for page in PAGES.values()}


def pages_by_category(rank_max: Optional[int] = None) -> Dict[str, List[ManualPage]]:
    grouped: Dict[str, List[ManualPage]] = {cat: [] for cat in PAGE_CATEGORIES}
    for page in PAGES.values():
        if rank_max is not None and page.rank > rank_max:
            continue
        grouped[page.category].append(page)
    return grouped
