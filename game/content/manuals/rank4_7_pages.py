"""
Rank 4-7 manual pages. Before this module, ranks 4-7 had only the 4-5 procedurally-
augmented pages each from manual_data.py's own _augment_rank (one page per name in
_RANK_POOL_PAGE_NAMES, round-robined across just 7 of the 10 categories) — Movement,
Utility, and Restriction were completely empty at EVERY rank from 4 through 7, the same
"can't even be rolled" gap rank1_pages.py/rank2_3_pages.py already fixed at ranks 1-3.

Ten pages per rank, one per category, closing that gap everywhere and giving every rank a
real (if still partial — see the bottom of this docstring) spread instead of one single
procedurally-generated page per category. Flavor for each rank borrows the SAME loose
realm-keyword theming manual_data.py's own existing rank 4-7 pages already established
(section 11.5 of the content brief: Core Formation's furnace/golden-core/star-iron for
Rank 4, a Dao/domain/law/time theme for Rank 5 matching "Dao Mark Engraving
Chapter"/"Five Domain Circulation" already there, an immortal/soul-dominion/void theme for
Rank 6 matching "Immortal Essence Conversion"/"Myriad Soul Dominion", and an Ancient-Realm
heaven-defying/sovereign/primordial theme for Rank 7 matching "Heaven-Defying
Foundation"/"Sovereign Body Chapter") — no monsters/regions for these realms exist yet in
this bot, same as when the ORIGINAL 4-5 procedural pages per rank were added; manual rank
doesn't have to wait on a fully-built region to exist.

A few page names below were deliberately changed from an initial draft that collided with
manual_data.py's own pre-existing procedural names for these same ranks (duplicate names
would silently overwrite the earlier PAGES entry) — see e.g. Void-Step Crossing Technique
(not "Void Crossing Method", already taken) and Undying Sovereign Body (not "Sovereign Body
Chapter", already taken).

Not a full pass at the brief's own 40/45/45/50-page Rank 4-7 targets (section 11.1) — same
"substantial first increment, not a full run" framing as rank2_3_pages.py.
"""

from ...manual_data import _register

# ================================================================================================
# RANK 4 — Core Formation flavor (furnace, golden core, alchemy, star-iron)
# ================================================================================================

_register(
    "Golden Core Compression Method", "Foundation", 4, ["metal", "refinement"], 8,
    {"cultivation_gain_pct": 11.0},
    description="Compresses cultivation base into something dense enough to resemble a golden core.",
)
_register(
    "Star-Iron Vein Circulation", "Circulation", 4, ["metal", "star"], 8,
    {"cultivation_speed_pct": 11.0, "essence_recovery_pct": 4.0},
    description="Circulates qi along paths mapped from a star-iron vein's own natural grain.",
)
_register(
    "Living Pill Refinement Chapter", "Refinement", 4, ["pill", "refinement"], 8,
    {"essence_purity_pct": 13.0},
    description="A refinement chapter written by someone who came uncomfortably close to making a pill that could think.",
)
_register(
    "Core Compression Breakthrough Record", "Breakthrough", 4, ["metal", "qi"], 7,
    {"breakthrough_success_pct": 8.0},
    flaw_pool=["breakthrough_backlash"],
    description="A record of forcing a cultivation base to compress before it was fully ready.",
)
_register(
    "Furnace-Tempered Fist", "Offense", 4, ["fire", "strength"], 8,
    {"physical_damage_pct": 12.0},
    description="A striking art tempered the same way good steel is — in a furnace, repeatedly.",
)
_register(
    "Star-Iron Body Tempering", "Defense", 4, ["metal", "strength"], 8,
    {"hp_pct": 10.0},
    description="Tempers the body against a standard drawn from star-iron ore itself.",
)
_register(
    "Alchemist's Discerning Eye", "Mind", 4, ["wisdom", "refinement"], 7,
    {"insight_gain_pct": 12.0},
    description="Trains the eye to read a pill's true quality before it's even finished cooling.",
)
_register(
    "Furnace-Step Evasion", "Movement", 4, ["fire", "movement"], 7,
    {"dodge_chance_pct": 10.0},
    description="A stepping method for staying clear of a furnace's own backdraft — and, incidentally, of a lot else.",
)
_register(
    "Ore Vein Sensing Method", "Utility", 4, ["earth", "wisdom"], 7,
    {"loot_chance_bonus_pct": 9.0},
    description="Senses the difference between a dead vein and one still worth digging.",
)
_register(
    "Furnace Oath of Refinement", "Restriction", 4, ["fire", "restriction"], 9,
    {"essence_purity_pct": 10.0},
    flaw_pool=["oath_upkeep"],
    description="Binds the cultivator to feed a furnace's own upkeep in exchange for real refining power.",
)

# ================================================================================================
# RANK 5 — Dao/domain/law/time flavor (matching Dao Mark Engraving Chapter, Five Domain
# Circulation, Soul Palace Foundation already at this rank)
# ================================================================================================

_register(
    "Soul Palace Expansion Method", "Foundation", 5, ["soul", "aperture"], 9,
    {"cultivation_gain_pct": 13.0},
    description="Expands the soul palace one careful chamber at a time.",
)
_register(
    "Domain-Splitting Circulation", "Circulation", 5, ["formation", "qi"], 9,
    {"cultivation_speed_pct": 13.0},
    description="Circulates qi along boundary lines borrowed from formation domain theory.",
)
_register(
    "Law-Fire Refinement Chapter", "Refinement", 5, ["fire", "refinement", "rule"], 9,
    {"essence_purity_pct": 15.0},
    description="A refinement method that treats fire as a law to be comprehended, not just a heat source.",
)
_register(
    "Time-Worn Gate Crossing", "Breakthrough", 5, ["time", "qi"], 8,
    {"breakthrough_success_pct": 9.0},
    description="Times a breakthrough attempt against the aperture's own natural weathering, not against the calendar.",
)
_register(
    "Domain-Splitting Strike", "Offense", 5, ["formation", "strength"], 9,
    {"technique_damage_pct": 13.0},
    description="A striking technique that opens along a domain boundary rather than a body's own natural lines.",
)
_register(
    "Soul Palace Ward", "Defense", 5, ["soul", "rule"], 9,
    {"hp_pct": 11.0, "deviation_resistance_pct": 3.0},
    description="Wards the soul palace itself, not just the body built around it.",
)
_register(
    "Dao Mark Comprehension Verse", "Mind", 5, ["wisdom", "rule"], 8,
    {"insight_gain_pct": 14.0},
    description="A verse for reading the faint marks a Dao leaves on everything it's ever touched.",
)
_register(
    "Domain-Step Crossing", "Movement", 5, ["space", "movement"], 8,
    {"dodge_chance_pct": 11.0},
    description="Steps across a domain boundary the way most people step across a threshold.",
)
_register(
    "Law-Sense Surveying Method", "Utility", 5, ["formation", "wisdom"], 8,
    {"loot_chance_bonus_pct": 10.0},
    description="Surveys a place for the law-formations quietly shaping it, not just what's sitting on the surface.",
)
_register(
    "Time-Bound Cultivation Oath", "Restriction", 5, ["time", "restriction"], 10,
    {"cultivation_speed_pct": 8.0},
    flaw_pool=["oath_upkeep"],
    description="Borrows cultivation speed against a fixed, ongoing debt to time itself.",
)

# ================================================================================================
# RANK 6 — Immortal/soul-dominion/void flavor (matching Immortal Essence Conversion, Heaven-
# Earth Resonance, Myriad Soul Dominion already at this rank)
# ================================================================================================

_register(
    "Immortal Essence Foundation", "Foundation", 6, ["immortal", "essence"], 11,
    {"cultivation_gain_pct": 16.0, "essence_capacity_pct": 8.0},
    description="A foundation principle built on essence that no longer behaves like an ordinary cultivator's — the vessel itself grows to hold more.",
)
_register(
    "Heaven-Earth Resonance Circulation", "Circulation", 6, ["heaven", "earth"], 11,
    {"cultivation_speed_pct": 16.0},
    description="Circulates qi in resonance with heaven and earth both at once, rather than drawing from either alone.",
)
_register(
    "Void-Touched Refinement Method", "Refinement", 6, ["space", "refinement"], 11,
    {"essence_purity_pct": 18.0},
    description="A refinement method that briefly opens toward the void to burn away every last impurity.",
)
_register(
    "Tribulation Tempering Verse", "Breakthrough", 6, ["immortal", "qi"], 10,
    {"breakthrough_success_pct": 11.0},
    flaw_pool=["breakthrough_backlash"],
    description="Tempers a breakthrough attempt against a tribulation's own weight before actually facing one.",
)
_register(
    "Myriad Soul Strike", "Offense", 6, ["soul", "immortal"], 11,
    {"technique_damage_pct": 16.0},
    description="A striking technique that channels more than one soul's worth of intent into a single blow.",
)
_register(
    "Void Body Ward", "Defense", 6, ["space", "immortal"], 11,
    {"hp_pct": 14.0},
    description="Wards the body by letting part of it briefly not quite be there.",
)
_register(
    "Myriad Soul Dominion Verse", "Mind", 6, ["soul", "wisdom"], 10,
    {"insight_gain_pct": 17.0},
    description="A verse for holding a myriad of soul-fragments in mind at once without losing track of any of them.",
)
_register(
    "Void-Step Crossing Technique", "Movement", 6, ["space", "movement"], 10,
    {"dodge_chance_pct": 13.0},
    description="Crosses short distances through the edge of the void rather than the ground in between.",
)
_register(
    "Heaven-Earth Sensing Method", "Utility", 6, ["heaven", "wisdom"], 10,
    {"loot_chance_bonus_pct": 12.0},
    description="Reads the resonance between heaven and earth for whatever they're both quietly pointing toward.",
)
_register(
    "Immortal Essence Upkeep Oath", "Restriction", 6, ["immortal", "restriction"], 12,
    {"essence_purity_pct": 14.0},
    flaw_pool=["oath_upkeep"],
    description="Binds the cultivator to a standing immortal-essence upkeep in exchange for real refining purity.",
)

# ================================================================================================
# RANK 7 — Ancient Realm flavor (matching Heaven-Defying Foundation, River of Time Reversal,
# Fate-Breaking Final Verse already at this rank)
# ================================================================================================

_register(
    "Heaven-Defying Foundation Art", "Foundation", 7, ["immortal", "heaven"], 13,
    {"cultivation_gain_pct": 20.0},
    description="A foundation art built explicitly against what heaven expects a cultivator to be capable of.",
)
_register(
    "Law-Boundless Meridian Art", "Circulation", 7, ["rule", "qi"], 13,
    {"cultivation_speed_pct": 20.0},
    description="Circulates qi through meridians that no longer recognize any particular law as a boundary.",
)
_register(
    "Primordial Essence Refinement", "Refinement", 7, ["immortal", "refinement"], 13,
    {"essence_purity_pct": 22.0},
    description="A refinement method that reaches back toward essence in something close to its primordial state.",
)
_register(
    "Fate-Breaking Gate Rite", "Breakthrough", 7, ["luck", "qi"], 12,
    {"breakthrough_success_pct": 14.0},
    flaw_pool=["breakthrough_backlash"],
    description="A rite for forcing a gate open against whatever fate had planned for the attempt instead.",
)
_register(
    "Sovereign Body Strike", "Offense", 7, ["immortal", "strength"], 13,
    {"physical_damage_pct": 20.0},
    description="A striking art meant for a body that's stopped being merely mortal in every way but name.",
)
_register(
    "Undying Sovereign Body", "Defense", 7, ["immortal", "heaven"], 13,
    {"hp_pct": 18.0},
    description="A defensive principle built for a body that intends to simply refuse to stop functioning.",
)
_register(
    "River of Time Comprehension", "Mind", 7, ["time", "wisdom"], 12,
    {"insight_gain_pct": 21.0},
    description="Comprehends a moment by reading it as one still point in a much longer river.",
)
_register(
    "Time-Reversal Step", "Movement", 7, ["time", "movement"], 12,
    {"dodge_chance_pct": 16.0},
    description="A step timed so precisely it looks, from the outside, like it happened a moment before the attack that caused it.",
)
_register(
    "World-Law Sensing Method", "Utility", 7, ["rule", "wisdom"], 12,
    {"loot_chance_bonus_pct": 15.0},
    description="Senses the deep world-laws governing a place well enough to know what it's actually protecting.",
)
_register(
    "Fate-Bound Sovereign Oath", "Restriction", 7, ["luck", "restriction"], 14,
    {"breakthrough_success_pct": 10.0},
    flaw_pool=["oath_upkeep"],
    description="Trades a portion of the cultivator's own fate for a standing breakthrough advantage.",
)
