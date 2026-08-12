"""
Rank 8 manual pages — White Heaven content (see game/white_heaven.py, /white_heaven).
Rank 8 is a brand-new ceiling above the previous max (Rank 7), gated the same way White
Heaven itself is: reachable only via White Heaven's own hunt/raid/explore/sfbl reward
pools once a character is Dao Seeking realm or above.

Hand-authored (not procedurally-named like Rank 4-7's own pool), matching Rank 1-3's own
convention -- Rank 8 deserves real authored texture, not auto-generated names. One page
per PAGE_CATEGORIES entry (10 total, same "one per category" shape Rank 4-7 uses), covering
all 9 requested themes (heaven reused instead of a near-duplicate "heavenly" tag; light/
holy/life are the 3 genuinely new tags added in manual_data.py alongside this file).

Power/effect magnitudes scale up from Rank 7's own established range (power_value 12-14,
single-stat effects ~14-22%) by roughly the same ~1.4-1.5x MANUAL_RANK_TABLE[8] itself grows
by (350/230 ≈ 1.52x budget) -- a starting point for empirical tuning, not a final value.
"""

from ...manual_data import _register

_register(
    "Nine Heavens Origin Foundation", "Foundation", 8, ["heaven", "qi"], 18,
    {"cultivation_gain_pct": 30.0},
    description="A foundation principle drawn from the origin-qi of the Nine Heavens themselves, above any mortal aperture.",
)
_register(
    "Cloud Sea Nine Bends Circulation", "Circulation", 8, ["water", "movement"], 18,
    {"cultivation_speed_pct": 30.0},
    description="Circulates qi through nine bends, the way White Heaven's own cloud seas endlessly fold over themselves.",
)
_register(
    "Great Solar Furnace Refinement", "Refinement", 8, ["sun", "refinement"], 17,
    {"essence_purity_pct": 32.0},
    description="Refines essence in a furnace stoked by a captured sliver of the sun itself.",
)
_register(
    "Time-Defying Ascension Rite", "Breakthrough", 8, ["time", "heaven"], 17,
    {"breakthrough_success_pct": 20.0},
    flaw_pool=["breakthrough_backlash"],
    description="Forces the gate open a moment before time itself says it's ready — effective, but time collects its due either way.",
)
_register(
    "White Light Piercing Strike", "Offense", 8, ["light", "strength"], 18,
    {"technique_damage_pct": 30.0},
    description="A strike condensed from White Heaven's own light-path zones, piercing before the eye can track it.",
)
_register(
    "Holy Ward of the Nine Heavens", "Defense", 8, ["holy", "heaven"], 18,
    {"hp_pct": 26.0},
    description="A ward woven from something closer to a heavenly decree than an ordinary defensive art.",
)
_register(
    "Living Wood Wind-Step", "Movement", 8, ["wood", "wind"], 17,
    {"dodge_chance_pct": 24.0},
    description="Moves the way a living branch bends around a gale instead of fighting it.",
)
_register(
    "Starlight Comprehension Scripture", "Mind", 8, ["star", "wisdom"], 17,
    {"insight_gain_pct": 30.0},
    description="Reads a moment of insight the way an astronomer reads a falling star — brief, and unmistakable.",
)
_register(
    "Heavenly Life-Sensing Method", "Utility", 8, ["life", "wisdom"], 16,
    {"loot_chance_bonus_pct": 22.0},
    description="Senses living qi and buried treasure with the same heightened, heavenly clarity.",
)
_register(
    "Immortal Oath of the White Heaven", "Restriction", 8, ["heaven", "restriction"], 19,
    {"deviation_resistance_pct": 20.0},
    flaw_pool=["oath_upkeep"],
    description="An oath sworn to White Heaven itself, steadying the dao heart — as long as the oath keeps being fed.",
)
