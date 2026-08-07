"""
Rank 2-3 manual pages — Verdant Borderlands flavor, continuing directly from
rank1_pages.py. The design brief only hand-names Rank 1 pages explicitly (section 11.4);
Rank 2+ content is described only as loose per-realm THEME keywords (section 11.5), so
these are authored fresh rather than transcribed from the brief, following its own page
design rules (section 11.3: stable ID, 2-4 coherent tags, one power_value, 1-3 real
effects, optional flaw, description) and its own per-page magnitude convention (rank 2/3
effect values run modestly above Rank 1's, not dramatically — this game leans on
rarity/coherence/comprehension multipliers for scaling, not huge jumps in raw page numbers;
compare Rank 1's "Nine Coiling Rivers" cultivation_speed_pct=8 to Rank 2's own existing
"Twin Current Circulation" at 9).

Before this module, Rank 2 had FIVE completely empty categories (Refinement, Defense, Mind,
Utility, Restriction) and Rank 3 had TWO (Utility, Restriction) — the same "can't even be
rolled" gap rank1_pages.py fixed for Rank 1's Defense/Utility. Every empty category at both
ranks is filled here.

Themes lean on content already built this session — the Blood Fang pack (hunt elite + raid
Alpha), Jade Shell Toad, Grave-Moss Corpse Beetle / the grave-themed discovery trio, Bamboo
Shadow Snake / Concealed Fang Gu — so a player progressing through this region keeps running
into the same handful of identities at deeper strength, per the brief's own section 3.3
("Identity") pillar, rather than an unrelated new cast at every rank.

Not a full pass at the brief's own 35/40-page Rank 2/3 targets (section 11.1) — this is a
substantial first increment (this module alone is comparable in size to rank1_pages.py) that
prioritizes closing every empty-category gap and adding real breadth; more can be added the
same way later.
"""

from ...manual_data import _register

# ================================================================================================
# RANK 2
# ================================================================================================

_register(
    "Twin Fang Foundation", "Foundation", 2, ["blood", "strength"], 6,
    {"cultivation_gain_pct": 7.0, "hp_pct": 4.0},
    description="A foundation principle built on the same bloodline discipline that holds a wolf pack together.",
)
_register(
    "Toad Marsh Circulation", "Circulation", 2, ["poison", "water"], 6,
    {"cultivation_speed_pct": 7.0, "essence_purity_pct": 4.0},
    description="Circulates qi through the body the slow, patient way a marsh toad processes its own poison.",
)
_register(
    "Grave Ash Refinement", "Refinement", 2, ["soul", "earth", "refinement"], 6,
    {"essence_purity_pct": 8.0},
    description="Refines essence the way grave ash refines itself — slowly, and without waste.",
)
_register(
    "Bamboo Sap Distillation", "Refinement", 2, ["wood", "refinement"], 6,
    {"essence_recovery_pct": 6.0, "essence_purity_pct": 3.0},
    description="A slow-drip distillation method borrowed from tapping bamboo sap.",
)
_register(
    "Toad Venom Concentration", "Refinement", 2, ["poison", "refinement"], 6,
    {"essence_purity_pct": 7.0, "hp_pct": 2.0},
    flaw_pool=["resource_drain"],
    description="Concentrates essence the way a Jade Shell Toad concentrates its own venom — potent, if handled carelessly.",
)
_register(
    "Alpha's Gate Method", "Breakthrough", 2, ["blood", "strength"], 5,
    {"breakthrough_success_pct": 5.0},
    description="Forces the aperture open with the same singular will that holds a wolf pack under one leader.",
)
_register(
    "Concealed Fang Strike", "Offense", 2, ["poison", "strength"], 6,
    {"physical_damage_pct": 7.0},
    flaw_pool=["periodic_damage"],
    description="A striking method meant to land once, from concealment, before anything can react.",
)
_register(
    "Crane Talon Follow-Through", "Offense", 2, ["wind", "spear"], 6,
    {"technique_damage_pct": 6.0, "dodge_chance_pct": 2.0},
    description="A spear technique that carries the momentum of a diving crane straight through the follow-up.",
)
_register(
    "Bone Shield Meditation", "Defense", 2, ["earth", "strength"], 6,
    {"hp_pct": 7.0, "deviation_resistance_pct": 2.0},
    description="A meditation on the same layered armor a Grave-Moss Corpse Beetle carries into old age.",
)
_register(
    "Iron Skin Tempering", "Defense", 2, ["metal", "strength"], 6,
    {"hp_pct": 6.0, "dodge_chance_pct": 2.0},
    description="Tempers the skin iron-hard without stiffening the body underneath it.",
)
_register(
    "Grave Shell Ward", "Defense", 2, ["earth", "soul"], 6,
    {"hp_pct": 5.0, "deviation_resistance_pct": 3.0},
    description="A warding technique learned from whatever it is that lets old grave-dwelling things keep their composure.",
)
_register(
    "Packmate Pursuit Step", "Movement", 2, ["blood", "movement"], 5,
    {"dodge_chance_pct": 5.0, "physical_damage_pct": 3.0},
    description="A pursuit rhythm meant to be run alongside others, not alone.",
)
_register(
    "Moonwell Reflection", "Mind", 2, ["moon", "wisdom"], 5,
    {"insight_gain_pct": 8.0, "cooldown_reduction_pct": 3.0},
    description="A meditation practiced beside still moonlit water, clear enough to think in.",
)
_register(
    "Toad Patience Verse", "Mind", 2, ["water", "wisdom"], 5,
    {"insight_gain_pct": 7.0, "essence_recovery_pct": 3.0},
    description="A verse about waiting motionless for exactly as long as it takes.",
)
_register(
    "Deep Grove Foraging Method", "Utility", 2, ["wood", "wisdom"], 5,
    {"loot_chance_bonus_pct": 6.0},
    description="A foraging method for groves deep enough that most cultivators never bother searching them.",
)
_register(
    "Pack Hunt Coordination", "Utility", 2, ["blood", "strength"], 5,
    {"stone_reward_bonus_pct": 5.0, "loot_chance_bonus_pct": 3.0},
    description="Notes on hunting as a pack rather than alone — more kills, and less of each one wasted.",
)
_register(
    "Moonlit Vow of Restraint", "Restriction", 2, ["moon", "restriction"], 7,
    {"dodge_chance_pct": 8.0},
    flaw_pool=["night_only"],
    description="A vow that trades daylight usefulness for real strength once the moon is up.",
)

# ================================================================================================
# RANK 3
# ================================================================================================

_register(
    "Hollow Grave Foundation", "Foundation", 3, ["soul", "earth"], 9,
    {"cultivation_gain_pct": 10.0, "deviation_resistance_pct": 3.0},
    description="A foundation principle drawn from descending into a hollow grave and coming back out steadier than before.",
)
_register(
    "Blood Pack Circulation", "Circulation", 3, ["blood", "movement"], 9,
    {"cultivation_speed_pct": 10.0, "physical_damage_pct": 4.0},
    description="Circulates qi at a pack's own hunting rhythm — always moving, never quite at rest.",
)
_register(
    "Poison Marsh Distillation", "Refinement", 3, ["poison", "water", "refinement"], 9,
    {"essence_purity_pct": 11.0},
    description="A refinement method perfected somewhere deep in a poison-choked marsh.",
)
_register(
    "Pack Alpha's Breakthrough Rite", "Breakthrough", 3, ["blood", "strength"], 8,
    {"breakthrough_success_pct": 7.0},
    flaw_pool=["breakthrough_backlash"],
    description="Forces the gate the way a pack leader forces a challenge — decisively, and at real cost if it fails.",
)
_register(
    "Alpha Fang Rending Art", "Offense", 3, ["blood", "strength"], 9,
    {"physical_damage_pct": 11.0},
    flaw_pool=["periodic_damage"],
    description="A rending technique modeled on the Blood Fang pack's own leader, not its followers.",
)
_register(
    "Toad Breath Technique", "Offense", 3, ["poison", "water"], 9,
    {"technique_damage_pct": 9.0},
    description="A corrosive breath technique refined well past what any ordinary toad could manage.",
)
_register(
    "Shell Matriarch Ward", "Defense", 3, ["earth", "soul"], 9,
    {"hp_pct": 9.0, "deviation_resistance_pct": 3.0},
    description="A warding stance named for whatever presides deepest in a beetle swarm's own burial ground.",
)
_register(
    "Deep Marsh Insulation", "Defense", 3, ["water", "poison"], 9,
    {"hp_pct": 7.0, "essence_purity_pct": 3.0},
    description="Insulates the body against a marsh's own toxins, and incidentally against a great deal else.",
)
_register(
    "Ambusher's Vanishing Step", "Movement", 3, ["shadow", "movement"], 8,
    {"dodge_chance_pct": 9.0},
    description="A step meant to close distance unseen and then simply not be where the counterattack lands.",
)
_register(
    "Gravekeeper's Watch Meditation", "Mind", 3, ["soul", "wisdom"], 8,
    {"insight_gain_pct": 11.0, "deviation_resistance_pct": 2.0},
    description="A meditation practiced the way a long, patient watch over the dead is practiced — for years, without complaint.",
)
_register(
    "Hollow Grove Surveying Method", "Utility", 3, ["earth", "wisdom"], 8,
    {"loot_chance_bonus_pct": 7.0, "stone_reward_bonus_pct": 3.0},
    description="A surveying method for reading what a hollow, half-collapsed grove is actually hiding.",
)
_register(
    "Pack Territory Mapping", "Utility", 3, ["blood", "wisdom"], 8,
    {"loot_chance_bonus_pct": 8.0},
    description="A mapping method for reading exactly how far a pack's hunting territory really extends.",
)
_register(
    "Grave Vow of Silence", "Restriction", 3, ["soul", "restriction"], 9,
    {"insight_gain_pct": 9.0},
    flaw_pool=["oath_upkeep"],
    description="A vow of silence sworn over an old grave — clarity bought with an ongoing, binding cost.",
)
_register(
    "Blood Debt Fang Oath", "Restriction", 3, ["blood", "restriction"], 9,
    {"physical_damage_pct": 10.0},
    flaw_pool=["oath_upkeep"],
    description="Power borrowed against a standing blood debt to the pack — real, as long as the debt keeps getting paid.",
)
