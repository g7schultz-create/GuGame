"""
Killer Move (see /killer_move) -- procedurally assembled from a core Gu + 10 component Gu,
"similar to manual": a harmony score from how well the components match the core Gu's type
(see game/gu_types.py) determines a power multiplier band (mirrors manual_gen._coherence_band's
exact shape), the components' own quality determines how close to the move's tier ceiling its
effects land, and a small word-bag name generator produces a themed name -- same combinator
shape as manual_gen.generate_manual_name, but actually biased by the core Gu's type (manual's
version accepts a primary_path argument and never uses it).

Pure logic -- no DB/GameManager/discord dependency, mirrors manual_gen.py's own split from
manager.py, so the harmony/effect-generation math is directly unit-testable.
"""

import random
from dataclasses import dataclass
from typing import Dict, List, Optional

from . import equipment, gu_types

# -- Mortal vs Immortal tier -------------------------------------------------------------------
# Derived once from the existing Gu quality ladder (equipment.GU_QUALITY_ORDER) rather than a
# new hand-assigned property -- Common/Uncommon/Rare core -> Mortal, Epic and up -> Immortal.
MOVE_TIER_BY_QUALITY: Dict[str, str] = {
    quality: ("Mortal" if index < 3 else "Immortal")
    for index, quality in enumerate(equipment.GU_QUALITY_ORDER)
}

# -- Qi cost, as a % of the caster's max qi_stat (the same battle_qi resource Empower/Gu
# abilities already spend) -----------------------------------------------------------------
QI_COST_PCT_BY_TIER = {"Mortal": 0.25, "Immortal": 0.70}

# -- Effect ceilings per tier, before harmony/component-quality scaling below ----------------
DAMAGE_STR_MULTIPLIER_CEILING = {"Mortal": 2.5, "Immortal": 6.0}
BUFF_STAT_PCT_CEILING = {"Mortal": 0.15, "Immortal": 0.50}
BUFF_DURATION_SECONDS = {"Mortal": 600, "Immortal": 3600}
ESSENCE_PCT_CEILING = {"Mortal": 0.15, "Immortal": 0.50}
SUPPORT_PCT_CEILING = {"Mortal": 0.10, "Immortal": 0.40}  # cultivation / loot
SUPPORT_DURATION_SECONDS = {"Mortal": 600, "Immortal": 3600}

BUFF_KEYS = ["str_pct", "atk_pct", "def_pct", "lifesteal_pct"]
MIN_BUFF_KEYS_ROLLED = 1
MAX_BUFF_KEYS_ROLLED = 3


@dataclass
class HarmonyBand:
    label: str
    power_multiplier: float


def _harmony_band(score: int) -> HarmonyBand:
    """Same 6 bands/multipliers as manual_gen._coherence_band -- reusing the exact numbers
    rather than inventing a second set, so "harmony" carries the same weight players already
    know from assembling manuals."""
    score = max(0, min(100, score))
    if score <= 29:
        return HarmonyBand("Chaotic", 0.80)
    if score <= 49:
        return HarmonyBand("Flawed", 0.90)
    if score <= 69:
        return HarmonyBand("Stable", 1.00)
    if score <= 84:
        return HarmonyBand("Harmonious", 1.08)
    if score <= 94:
        return HarmonyBand("Perfected", 1.15)
    return HarmonyBand("True Inheritance", 1.22)


def calculate_harmony(core_type: Optional[str], component_types: List[str]) -> int:
    """0-100: +10 per component sharing the core Gu's type, plus a +15 "pure build" bonus if
    all 10 do. Simpler than manual_gen.calculate_coherence's multi-factor score -- a Killer
    Move has no Foundation/Circulation-equivalent structural categories to satisfy, just "how
    on-theme is the mix.\""""
    if not component_types or core_type is None:
        return 0
    matches = sum(1 for t in component_types if t == core_type)
    score = matches * 10
    if matches == len(component_types):
        score += 15
    return max(0, min(100, score))


def _quality_strength_fraction(component_qualities: List[Optional[str]]) -> float:
    """0.5-1.0: how strong the 10 component Gu's own qualities are on average, normalized
    against the full Common..Immortal ladder (a flat/non-tiered Gu with no quality counts as
    1 star, the same convention equipment.gu_breakdown_value already uses). Floored at 0.5 so
    a move is never trivially weak even from all-Common components -- harmony (theme match) is
    meant to be the real skill-expression lever, not just "did you happen to consume
    high-quality Gu.\""""
    if not component_qualities:
        return 0.5
    stars = [equipment.GU_QUALITY_STARS.get(quality, 1) for quality in component_qualities]
    avg_star = sum(stars) / len(stars)
    ladder_span = len(equipment.GU_QUALITY_ORDER) - 1
    fraction = (avg_star - 1) / ladder_span if ladder_span else 0.0
    return 0.5 + 0.5 * max(0.0, min(1.0, fraction))


def _effect_multiplier(harmony: int, component_qualities: List[Optional[str]]) -> float:
    """0-1.0: how close to its tier's ceiling a move's effects land. The harmony band's
    power_multiplier alone ranges 0.80-1.22 (mirrors manual_gen's own bands, centered on
    Stable == 1.00), so multiplying it straight through against a "ceiling" constant could
    exceed that ceiling by up to 22% at the best harmony band -- clamped to 1.0 here so the
    DAMAGE_STR_MULTIPLIER_CEILING/BUFF_STAT_PCT_CEILING/etc tables really are hard ceilings
    (only reachable, never exceeded), matching what the approved plan's own "up to ~Nx" table
    promises. True Inheritance harmony + max component quality is the only way to reach 1.0
    exactly; anything short of that lands proportionally below the ceiling."""
    return min(1.0, _harmony_band(harmony).power_multiplier * _quality_strength_fraction(component_qualities))


def dominant_kind(component_types: List[str], core_type: Optional[str]) -> str:
    """Majority vote through gu_types.TYPE_AFFINITY -- the 10 COMPONENTS decide the move's
    mechanical kind ("based on what gu were put into it"), the core Gu only sets its name/
    flavor. Ties are broken by the core Gu's own affinity, then whichever tied kind sorts
    first (deterministic, never random)."""
    votes: Dict[str, int] = {}
    for gu_type in component_types:
        affinity = gu_types.TYPE_AFFINITY.get(gu_type)
        if affinity:
            votes[affinity] = votes.get(affinity, 0) + 1
    if not votes:
        return gu_types.TYPE_AFFINITY.get(core_type, "damage")
    best = max(votes.values())
    leaders = sorted(kind for kind, count in votes.items() if count == best)
    core_affinity = gu_types.TYPE_AFFINITY.get(core_type)
    return core_affinity if core_affinity in leaders else leaders[0]


def roll_combat_effects(kind: str, tier: str, harmony: int, component_qualities: List[Optional[str]], rng: random.Random) -> dict:
    """kind == 'damage' -> {'str_multiplier'}; kind == 'buff' -> a random 1-3 of BUFF_KEYS plus
    'duration_seconds', budget split unevenly via sorted random cut-points -- same
    blacksmith.roll_gear_stats shape (fixed budget -> random subset -> uneven split)."""
    multiplier = _effect_multiplier(harmony, component_qualities)
    if kind == "damage":
        return {"str_multiplier": round(DAMAGE_STR_MULTIPLIER_CEILING[tier] * multiplier, 2)}

    budget = BUFF_STAT_PCT_CEILING[tier] * multiplier
    count = rng.randint(MIN_BUFF_KEYS_ROLLED, min(MAX_BUFF_KEYS_ROLLED, len(BUFF_KEYS)))
    chosen = rng.sample(BUFF_KEYS, count)
    cuts = sorted(rng.uniform(0, budget) for _ in range(count - 1))
    bounds = [0.0] + cuts + [budget]
    shares = [bounds[i + 1] - bounds[i] for i in range(count)]
    effects = {key: max(0.001, round(share, 3)) for key, share in zip(chosen, shares)}
    effects["duration_seconds"] = BUFF_DURATION_SECONDS[tier]
    return effects


def roll_support_effects(kind: str, tier: str, harmony: int, component_qualities: List[Optional[str]], rng: random.Random) -> dict:
    """kind == 'essence' -> {'pct'} (instant); kind in ('cultivation', 'loot') -> {'pct',
    'duration_seconds'} (timed buff)."""
    multiplier = _effect_multiplier(harmony, component_qualities)
    if kind == "essence":
        return {"pct": round(ESSENCE_PCT_CEILING[tier] * multiplier, 3)}
    return {"pct": round(SUPPORT_PCT_CEILING[tier] * multiplier, 3), "duration_seconds": SUPPORT_DURATION_SECONDS[tier]}


# -- Name generation --------------------------------------------------------------------------
# Same prefix+core+finisher word-bag combinator as manual_gen.generate_manual_name, except the
# core word is actually drawn from a type-keyed pool for real thematic naming.
NAME_PREFIXES = [
    "Ninefold", "Heaven-Rending", "Blood-Soaked", "Silent", "Boundless", "Ashen",
    "Ember-Touched", "Hollow", "Voidborn", "Thousand-Fold",
]
NAME_FINISHERS = ["Strike", "Technique", "Art", "Judgment", "Extermination", "Reckoning", "Rite", "Blow"]

NAME_CORE_WORDS_BY_TYPE: Dict[str, List[str]] = {
    "fire": ["Inferno", "Cinder", "Ember", "Blaze"],
    "water": ["Tide", "Torrent", "Current", "Deluge"],
    "wood": ["Root", "Bloom", "Bough", "Verdant"],
    "metal": ["Blade", "Ingot", "Alloy", "Edge"],
    "earth": ["Mountain", "Bedrock", "Tremor", "Stone"],
    "lightning": ["Thunder", "Storm", "Bolt", "Static"],
    "wind": ["Gale", "Cyclone", "Zephyr", "Squall"],
    "poison": ["Venom", "Miasma", "Blight", "Toxin"],
    "blood": ["Crimson", "Bloodline", "Vein", "Scarlet"],
    "bone": ["Marrow", "Ossuary", "Ribcage", "Skeleton"],
    "shadow": ["Umbra", "Eclipse", "Gloom", "Nightfall"],
    "moon": ["Moonfall", "Lunar", "Crescent", "Nightglow"],
    "star": ["Starfall", "Constellation", "Comet", "Nova"],
    "light": ["Halo", "Luminance", "Beacon", "Glow"],
    "sword": ["Sword", "Blade", "Edge", "Fang"],
    "strength": ["Fist", "Titan", "Colossus", "Juggernaut"],
    "wisdom": ["Insight", "Enlightenment", "Clarity", "Sage"],
    "soul": ["Spirit", "Wraith", "Soulfire", "Phantom"],
    "dream": ["Reverie", "Slumber", "Nightmare", "Mirage"],
    "time": ["Chronos", "Hourglass", "Epoch", "Instant"],
    "space": ["Void", "Rift", "Horizon", "Expanse"],
    "luck": ["Fortune", "Fate", "Providence", "Chance"],
    "formation": ["Array", "Lattice", "Sigil", "Grid"],
    "human": ["Mortal", "Ascendant", "Vanguard", "Sovereign"],
    "heaven": ["Celestial", "Divine", "Empyrean", "Sky"],
    "food": ["Harvest", "Feast", "Nourish", "Bounty"],
    "storage": ["Vault", "Cache", "Hoard", "Repository"],
    "movement": ["Stride", "Flicker", "Dash", "Wake"],
}
_FALLBACK_CORE_WORDS = ["Dragon", "River", "Mountain", "Heart", "Aperture"]


def generate_killer_move_name(primary_type: Optional[str], rng: random.Random) -> str:
    prefix = rng.choice(NAME_PREFIXES)
    core = rng.choice(NAME_CORE_WORDS_BY_TYPE.get(primary_type, _FALLBACK_CORE_WORDS))
    finisher = rng.choice(NAME_FINISHERS)
    return f"{prefix} {core} {finisher}"
