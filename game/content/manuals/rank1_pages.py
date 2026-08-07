"""
Rank 1 manual pages — Verdant Borderlands flavor (content expansion brief section 11.4's
own named list). manual_data.py already hand-authors 13 Rank 1 pages; this module adds the
35 remaining named entries from that same section, bringing Rank 1 up near the brief's own
25-35 page target (section 11.1) while rounding out two categories (Defense, Utility) that
previously had ZERO Rank 1 pages at all — a manual couldn't roll either category into its
optional slots before this, not because the game forbade it but because nothing existed to
pick.

Every effect key used below is one of the EFFECT_LABELS keys manager.py actually applies
(see GameManager.compute_equipment_bonuses / _qi_rate_components) — none of these pages use
the flavor-only keys a few of the ORIGINAL 13 pages have (night_escape_bonus, budget_bonus,
...; essence_capacity_flat was in this same dead-key list until it was renamed to the real,
consumed essence_capacity_pct — see database.py's _essence_capacity_multiplier), so nothing
new here is cosmetic. Utility pages use
loot_chance_bonus_pct/stone_reward_bonus_pct instead of a cultivation/combat stat — both are
real, already-consumed SPECIAL_BONUS_KEYS (hunt.py's loot roll, raid.py's stone reward), the
same class of effect an accessory can already roll. clue_chance_bonus_pct was deliberately
NOT used for any page here even though the design brief's own Utility flavor ("Beast Track
Reading" etc.) would suggest it — it turns out to be a pre-existing dead key (recognized and
displayable, but never actually read by any consumer anywhere in the codebase), and adding a
page that promises it would repeat the exact "described effect that doesn't work" problem
this session already fixed for manuals once. Left as a known gap, not silently faked.

Effect magnitudes match the existing 13 Rank 1 pages' own established range (power_value
3-5, single-stat effects roughly 3-8 depending on key) rather than being invented fresh.
"""

from ...manual_data import _register

# -- Foundation (2 existing: Breath of the Empty Aperture, River Pebble Foundation, Beast-Blood Foundation) --
_register(
    "Bamboo Root Breathing", "Foundation", 1, ["wood", "qi"], 3,
    {"cultivation_gain_pct": 4.0},
    description="A patient breathing method learned from bamboo groves — slow, steady, forgiving.",
)
_register(
    "Moonlit Aperture Opening", "Foundation", 1, ["moon", "aperture"], 4,
    {"cultivation_gain_pct": 5.0, "dodge_chance_pct": 2.0},
    description="Opens the aperture under moonlight, leaving the cultivator faintly harder to pin down.",
)
_register(
    "Iron Bone Foundation", "Foundation", 1, ["metal", "strength"], 4,
    {"cultivation_gain_pct": 3.0, "hp_pct": 5.0},
    description="Tempers the bones iron-hard before the flesh even catches up.",
)
_register(
    "Grave Moss Soul Anchoring", "Foundation", 1, ["soul", "earth"], 4,
    {"cultivation_gain_pct": 3.0, "deviation_resistance_pct": 3.0},
    flaw_pool=["reduced_healing"],
    description="Anchors the soul the way grave moss anchors itself to old stone — steady, if a little cold.",
)

# -- Circulation --
_register(
    "Coiling Snake Meridian Route", "Circulation", 1, ["poison", "movement"], 4,
    {"cultivation_speed_pct": 7.0, "dodge_chance_pct": 3.0},
    description="Qi coils and strikes like a snake through the meridians.",
)
_register(
    "Red Crane Wing Circulation", "Circulation", 1, ["wind", "movement"], 4,
    {"cultivation_speed_pct": 6.0, "physical_damage_pct": 3.0},
    description="Circulates qi in the same rhythm as a crane's wingbeat.",
)
_register(
    "Moon Rabbit Hidden Pulse", "Circulation", 1, ["moon", "luck"], 4,
    {"cultivation_speed_pct": 5.0, "essence_recovery_pct": 4.0},
    description="A soft, hare-quick pulse that's easy to miss and easy to sustain.",
)
_register(
    "Ironhide Furnace Breath", "Circulation", 1, ["metal", "strength"], 4,
    {"cultivation_speed_pct": 5.0, "hp_pct": 4.0},
    description="Burns qi through the meridians like a furnace tempers iron hide.",
)
_register(
    "Blood Fang Hunting Rhythm", "Circulation", 1, ["blood", "movement"], 5,
    {"cultivation_speed_pct": 6.0, "physical_damage_pct": 4.0},
    flaw_pool=["periodic_damage"],
    description="Circulates qi to the rhythm of a hunt — fast, aggressive, a little reckless.",
)

# -- Refinement (missed in the original pass — caught by validate_manual_pages' later
# all-10-categories check when Rank 4-7 pages were added; Rank 1 Refinement wasn't a hard
# generation failure like a missing Foundation/Circulation would be, since Refinement is
# optional, but a rank with zero Refinement pages still silently can't ever roll one) --
_register(
    "Bamboo Ash Distillation", "Refinement", 1, ["wood", "refinement"], 3,
    {"essence_purity_pct": 4.0},
    description="A simple distillation method using nothing more than bamboo ash and patience.",
)

# -- Breakthrough --
_register(
    "Beast Core Tempering Record", "Breakthrough", 1, ["strength", "qi"], 3,
    {"breakthrough_success_pct": 4.0},
    description="Tempers the aperture the same way a beast core is tempered before use.",
)
_register(
    "Moonrise Aperture Crossing", "Breakthrough", 1, ["moon", "aperture"], 3,
    {"breakthrough_success_pct": 3.0, "deviation_resistance_pct": 2.0},
    description="Times the crossing attempt to moonrise, when the aperture is said to soften.",
)
_register(
    "Blood Mist Gate Assault", "Breakthrough", 1, ["blood", "strength"], 4,
    {"breakthrough_success_pct": 5.0},
    flaw_pool=["breakthrough_backlash"],
    description="Forces the gate open through sheer aggression — effective, but unforgiving if it fails.",
)

# -- Offense --
_register(
    "Tusk-Driving Shoulder Strike", "Offense", 1, ["strength", "earth"], 3,
    {"physical_damage_pct": 5.0},
    description="A driving shoulder check modeled on a boar's charge.",
)
_register(
    "Snake Fang Finger", "Offense", 1, ["poison", "strength"], 3,
    {"physical_damage_pct": 4.0},
    flaw_pool=["periodic_damage"],
    description="A quick, fang-like finger strike aimed at soft points.",
)
_register(
    "Crane Beak Spear Art", "Offense", 1, ["wind", "spear"], 4,
    {"technique_damage_pct": 5.0},
    description="A spear form modeled on a crane's diving strike.",
)
_register(
    "Blood Fang Rending Claw", "Offense", 1, ["blood", "strength"], 4,
    {"physical_damage_pct": 6.0},
    flaw_pool=["periodic_damage"],
    description="A clawing strike meant to open, not just bruise.",
)
_register(
    "Grave Beetle Crushing Palm", "Offense", 1, ["earth", "strength"], 4,
    {"physical_damage_pct": 5.0, "hp_pct": 2.0},
    description="A slow, armored palm strike built for enduring the exchange, not winning it fast.",
)

# -- Defense (previously 0 Rank 1 pages — a manual couldn't roll this category at Rank 1 at all) --
_register(
    "Ironhide Stance", "Defense", 1, ["metal", "strength"], 4,
    {"hp_pct": 6.0},
    description="A grounded stance borrowed from the way an Ironhide Boar takes a hit.",
)
_register(
    "Jade Toad Poison Ward", "Defense", 1, ["poison", "water"], 4,
    {"hp_pct": 4.0, "essence_purity_pct": 3.0},
    description="Wards the body the way a Jade Shell Toad wards off its own poison.",
)
_register(
    "Grave Shell Meditation", "Defense", 1, ["earth", "soul"], 4,
    {"hp_pct": 5.0, "deviation_resistance_pct": 2.0},
    description="A slow, shell-like meditation that settles both body and spirit.",
)
_register(
    "Bamboo Bending Guard", "Defense", 1, ["wood", "movement"], 3,
    {"hp_pct": 3.0, "dodge_chance_pct": 2.0},
    description="Bends instead of breaking, the way bamboo does in a storm.",
)
_register(
    "Moon Fur Evasion Verse", "Defense", 1, ["moon", "movement"], 4,
    {"dodge_chance_pct": 6.0},
    description="A verse for slipping aside, the way a Moon-Eared Rabbit vanishes into underbrush.",
)

# -- Movement (Moon-Shadow Step already exists at Rank 1) --
_register(
    "Red Crane Short Flight", "Movement", 1, ["wind", "movement"], 4,
    {"dodge_chance_pct": 5.0},
    description="A short, controlled flight used to slip past a strike rather than block it.",
)
_register(
    "Bamboo Snake Concealment", "Movement", 1, ["shadow", "movement"], 3,
    {"dodge_chance_pct": 4.0},
    flaw_pool=["night_only"],
    description="Stillness and shadow borrowed from a snake at rest in bamboo shade.",
)
_register(
    "Wolf Pack Pursuit", "Movement", 1, ["blood", "movement"], 4,
    {"dodge_chance_pct": 3.0, "physical_damage_pct": 3.0},
    description="A pursuit rhythm meant for closing distance, not just escaping.",
)

# -- Mind (Clear Mind Verse already exists at Rank 1) --
_register(
    "Graveyard Silence Meditation", "Mind", 1, ["soul", "wisdom"], 4,
    {"insight_gain_pct": 8.0},
    description="A meditation practiced in silence deep enough to hear old ghosts think.",
)
_register(
    "Moon Reflection Thought", "Mind", 1, ["moon", "wisdom"], 3,
    {"insight_gain_pct": 6.0, "cooldown_reduction_pct": 2.0},
    description="Clears the mind the way still water reflects the moon.",
)
_register(
    "Hunter's Patient Gaze", "Mind", 1, ["wisdom", "strength"], 3,
    {"insight_gain_pct": 5.0, "cooldown_reduction_pct": 2.0},
    description="The stillness of a hunter waiting for the one moment that matters.",
)

# -- Utility (previously 0 Rank 1 pages — see this module's own docstring for why these use
# loot_chance_bonus_pct/stone_reward_bonus_pct rather than clue_chance_bonus_pct) --
_register(
    "Spirit Herb Recognition", "Utility", 1, ["wood", "wisdom"], 3,
    {"loot_chance_bonus_pct": 4.0},
    description="Trains the eye to spot a spirit herb worth picking among a hundred ordinary ones.",
)
_register(
    "Beast Track Reading", "Utility", 1, ["earth", "wisdom"], 3,
    {"loot_chance_bonus_pct": 5.0},
    description="Reads a beast's trail closely enough to know what it's carrying before the fight even starts.",
)
_register(
    "Minor Gu Feeding Notes", "Utility", 1, ["strength", "food"], 3,
    {"stone_reward_bonus_pct": 4.0},
    description="Notes on feeding a young Gu efficiently — and on what a well-fed one is worth.",
)
_register(
    "Hidden Cave Survey Method", "Utility", 1, ["earth", "wisdom"], 3,
    {"loot_chance_bonus_pct": 4.0, "stone_reward_bonus_pct": 3.0},
    description="A surveyor's method for reading a cave's shape before committing to explore it.",
)

# -- Restriction (Silent Devouring Vow already exists at Rank 1) --
_register(
    "Blood Oath Feeding Method", "Restriction", 1, ["blood", "restriction"], 5,
    {"physical_damage_pct": 6.0},
    flaw_pool=["oath_upkeep"],
    description="Strength bought with a standing blood oath — reliable only as long as the oath is fed.",
)
_register(
    "Night-Only Moon Scripture", "Restriction", 1, ["moon", "restriction"], 5,
    {"dodge_chance_pct": 7.0},
    flaw_pool=["night_only"],
    description="A scripture that only truly opens under moonlight.",
)
_register(
    "Corpse Moss Grave Vow", "Restriction", 1, ["soul", "restriction"], 5,
    {"deviation_resistance_pct": 5.0},
    flaw_pool=["oath_upkeep"],
    description="A vow sworn over grave moss — steadying, but binding.",
)
