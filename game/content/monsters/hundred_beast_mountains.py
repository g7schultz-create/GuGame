"""
Hundred Beast Mountains (Foundation Establishment) hunt catalog — content expansion brief
section 7.2. Unlike Verdant Borderlands, Foundation Establishment's HUNT anchor
(_generate_hunt_monster's realm-1 placeholder) was never a hand-authored, balance-tested
monster the way Ironhide Boar was — it's purely auto-scaled off Ironhide Boar's own numbers
by a flat 5x, which (see this module's own balance notes below) turns out to undercount a
REAL realm-4 (Foundation Establishment Early) character's actual stats substantially, since
real characters compound through 4 separate breakthroughs (3 substage x1.15 + 1 great-realm
x5.0 = ~7.6x total on a randomized base), not a flat 5x applied to one other monster's
already-hand-tuned numbers. So these 8 monsters are tuned against a REAL simulated realm-4
character (chargen.roll_base_stats() pushed through 4 real database.apply_breakthrough
calls, exactly what happens in actual play) rather than against the old placeholder's
numbers — see scratchpad/simulate_foundation_hunts.py for the methodology, matching Verdant
Borderlands' own precedent of always tuning off a real simulated player, not a guess.

Boar King (the existing raid boss) is untouched and stays exactly where it is — it's a RAID
boss, a completely separate list from this module's HUNT monsters, so there's no overlap or
conflict with "keep Boar King as an early Foundation raid" from the brief's own section 7.2.

Material drops are generic "Tier 2 Beast Core"/"Tier 2 Beast Material" only, across the
board — normalized the same way Verdant Borderlands' own drop tables were, away from this
region's original unique-named trophy materials (Granite Ape Marrow, Cloudstep Lynx Pelt,
etc., still defined as inert flavor items for anything that still references their names).
Gu drops and Primeval Essence Crystal drops are untouched.
"""

from ...monsters import DropEntry, Monster, MonsterAbility, TIER_1_GU_COMMON_POOL

GRANITE_BACK_APE = Monster(
    name="Granite-Back Ape",
    realm="Rank 2 Beast",
    monster_type="Beast",
    habitat="Granite Cliffs, Mountain Passes",
    description="A hulking ape whose back has calcified into something closer to stone than skin.",
    # Brute archetype (brief 6.3: HP 1.25, STR 1.20, DEF 1.00, SPD 0.80, ATK 0.90).
    hp=575, atk_stat=36, str_stat=108, def_stat=42, spd_stat=32, luck_stat=1, qi_stat=130,
    ability=MonsterAbility(
        name="Boulder Fist", description="A crushing overhead blow with a stone-hard fist.", str_multiplier=1.28,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 2 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 2 Beast Material"),
        DropEntry(chance=0.30, item_name="Tier 2 Beast Material"),
        DropEntry(chance=0.05, item_name="Granite Body Gu (Common)"),
    ],
    gu_rank=2,
)

CLOUDSTEP_LYNX = Monster(
    name="Cloudstep Lynx",
    realm="Rank 2 Beast",
    monster_type="Beast",
    habitat="High Ridgelines, Cloud Forests",
    description="A lynx that seems to find footing on air itself when the wind is right.",
    # Assassin archetype (brief 6.3: HP 0.70, STR 1.15, DEF 0.70, SPD 1.40, ATK 1.30).
    hp=322, atk_stat=52, str_stat=110, def_stat=29, spd_stat=56, luck_stat=1, qi_stat=130,
    ability=MonsterAbility(
        name="Windstep Claw", description="A near-instant claw strike from an impossible angle.", str_multiplier=1.28,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 2 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 2 Beast Material"),
        DropEntry(chance=0.30, item_name="Tier 2 Beast Material"),
        DropEntry(chance=0.05, item_name="Cloudstep Gu (Common)"),
    ],
    gu_rank=2,
)

IRONBEAK_VULTURE = Monster(
    name="Ironbeak Vulture",
    realm="Rank 2 Beast",
    monster_type="Beast",
    habitat="Mountain Peaks, Thermal Updrafts",
    description="A vulture whose beak has gone iron-dark and iron-hard from a lifetime of cracking mountain-goat bone.",
    # Skirmisher archetype (brief 6.3: HP 0.80, STR 0.95, DEF 0.75, SPD 1.35, ATK 1.15).
    hp=368, atk_stat=46, str_stat=91, def_stat=32, spd_stat=54, luck_stat=1, qi_stat=130,
    ability=MonsterAbility(
        name="Diving Strike", description="A steep, wind-assisted diving strike with its beak.", str_multiplier=1.3,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 2 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 2 Beast Material"),
        DropEntry(chance=0.30, item_name="Tier 2 Beast Material"),
        DropEntry(chance=0.05, pool=TIER_1_GU_COMMON_POOL),
    ],
    gu_rank=2,
)

VENOM_MIST_SPIDER = Monster(
    name="Venom Mist Spider",
    realm="Rank 2 Beast",
    monster_type="Beast",
    habitat="Web-Choked Ravines",
    description="A spider large enough to blanket a ravine mouth in poisoned mist rather than mere silk.",
    # Mystic archetype (brief 6.3: HP 0.90, STR 0.85, DEF 0.90, SPD 1.00, ATK 1.10).
    hp=414, atk_stat=44, str_stat=92, def_stat=38, spd_stat=40, luck_stat=0, qi_stat=140,
    ability=MonsterAbility(
        name="Venom Mist Bite", description="A bite delivered through a cloud of its own poisoned mist.", str_multiplier=1.55,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 2 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 2 Beast Material"),
        DropEntry(chance=0.30, item_name="Tier 2 Beast Material"),
        DropEntry(chance=0.05, item_name="Venom Web Gu (Common)"),
    ],
    gu_rank=2,
)

MOUNTAIN_BURROWING_LIZARD = Monster(
    name="Mountain-Burrowing Lizard",
    realm="Rank 2 Beast",
    monster_type="Beast",
    habitat="Stone Burrows, Cliff Faces",
    description="A thick-scaled lizard that carves its den directly into mountain stone.",
    # Guardian archetype (brief 6.3: HP 1.20, STR 0.80, DEF 1.35, SPD 0.75, ATK 0.90).
    hp=552, atk_stat=36, str_stat=90, def_stat=57, spd_stat=30, luck_stat=0, qi_stat=130,
    ability=MonsterAbility(
        name="Stone Bite", description="A slow but heavily armored bite.", str_multiplier=1.45,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 2 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 2 Beast Material"),
        DropEntry(chance=0.30, item_name="Tier 2 Beast Material", quantity=1),
        DropEntry(chance=0.05, pool=TIER_1_GU_COMMON_POOL),
    ],
    gu_rank=2,
)

THUNDERHORN_YAK = Monster(
    name="Thunderhorn Yak",
    realm="Rank 2 Beast (Elite)",
    monster_type="Beast",
    habitat="High Storm Plateaus",
    description="A massive yak whose horns visibly crackle before it charges — the same bloodline the raid-tier Thunderhorn Herd Tyrant leads.",
    hp=660, atk_stat=43, str_stat=132, def_stat=48, spd_stat=32, luck_stat=1, qi_stat=160,
    ability=MonsterAbility(
        name="Thunder Charge", description="A lightning-wreathed charge.", str_multiplier=1.35,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 2 Beast Core"),
        DropEntry(chance=0.80, item_name="Tier 2 Beast Material"),
        DropEntry(chance=0.45, item_name="Tier 2 Beast Material"),
        DropEntry(chance=0.10, item_name="Thunderhorn Gu (Common)"),
        DropEntry(chance=0.05, item_name="Primeval Essence Crystal", quantity=5),
    ],
    gu_rank=2,
    encounter_weight=0.25,
    elite=True,
)

GHOST_EYED_WHITE_TIGER = Monster(
    name="Ghost-Eyed White Tiger",
    realm="Rank 2 Beast (Elite)",
    monster_type="Beast",
    habitat="Fog-Wreathed Peaks",
    description="A pale tiger whose milky eyes see something other than what's actually standing in front of it.",
    hp=420, atk_stat=60, str_stat=132, def_stat=29, spd_stat=62, luck_stat=1, qi_stat=160,
    ability=MonsterAbility(
        name="Soulfear Pounce", description="A pounce that unsettles the mind as much as it wounds the body.", str_multiplier=1.3,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 2 Beast Core"),
        DropEntry(chance=0.80, item_name="Tier 2 Beast Material"),
        DropEntry(chance=0.45, item_name="Tier 2 Beast Material"),
        DropEntry(chance=0.10, item_name="Ghost Eye Gu (Common)"),
        DropEntry(chance=0.05, item_name="Primeval Essence Crystal", quantity=5),
    ],
    gu_rank=2,
    encounter_weight=0.25,
    elite=True,
)

WANDERING_BEAST_TAMER_REMNANT = Monster(
    name="Wandering Beast Tamer Remnant",
    realm="Rank 2 Cultivator (Rare)",
    monster_type="Human",
    habitat="Abandoned Beast-Taming Camps",
    description=(
        "The lingering, hostile remnant of a beast tamer who never let go of the mountains — genuinely "
        "dangerous, not evasive like the borderlands' own rare find."
    ),
    # A true "rare apex" per section 6.4 (25-45% solo win rate) through raw danger, unlike
    # Hundred-Year Spirit Ginseng's evasion-based version of the same slot.
    hp=520, atk_stat=68, str_stat=125, def_stat=46, spd_stat=46, luck_stat=2, qi_stat=150,
    ability=MonsterAbility(
        name="Commanding Strike", description="A strike backed by the same will that once commanded a den of beasts.", str_multiplier=1.6,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 2 Beast Material", quantity=2),
        DropEntry(chance=0.60, item_name="Tier 3 Beast Material"),
        DropEntry(chance=0.40, pool=TIER_1_GU_COMMON_POOL),
        DropEntry(chance=0.15, item_name="Primeval Essence Crystal", quantity=10),
    ],
    gu_rank=2,
    encounter_weight=0.08,
    elite=False,
)

HUNDRED_BEAST_MOUNTAINS_MONSTERS = [
    GRANITE_BACK_APE, CLOUDSTEP_LYNX, IRONBEAK_VULTURE, VENOM_MIST_SPIDER, MOUNTAIN_BURROWING_LIZARD,
    THUNDERHORN_YAK, GHOST_EYED_WHITE_TIGER, WANDERING_BEAST_TAMER_REMNANT,
]

# -- Hundred Beast Mountains raid: Thunderhorn Herd Tyrant (content brief section 7.2's
# "Second Raid" — Boar King stays as the region's "first of two regional raids", untouched,
# in game/monsters.py; this is purely additive, giving realm 1 two possible /raid targets
# the same way RAID_GROUPS_BY_REALM was restructured to support) --------------------------
# The brief's own three mechanics for this fight: "Main boss uses a charge" (Herd Tyrant's
# own Charge ability, same str_multiplier-driven pattern every other charge/rending/strike
# ability in this game already uses — no new mechanic needed), "Guardian protects the boss"
# (represented honestly through the Storm-Calf Guardian's own high DEF/HP rather than a
# taunt/redirect mechanic that doesn't exist in raid.py — a party that doesn't focus it down
# first eats real damage from it every round instead), and "Swarm applies repeated light
# pressure" (the Lightning Tick Swarm is just a third enemy with low HP/DEF but a real
# attack every round, same as how Boar Guard/Boar Skirmisher already add "repeated" pressure
# alongside Boar King — raid.py's own every-enemy-acts-every-round design already gives a
# third body real repeated presence with zero new engineering).
#
# Tuned against a REAL Foundation Establishment (realm_index=4) party — unlike Boar King,
# which (per its own comment) was deliberately calibrated for a party of Qi-Condensation-era
# characters attempting an above-their-level raid, this is a brand new realm-1 raid
# introduced alongside genuinely realm-4-calibrated hunt content (see
# hundred_beast_mountains.py's own hunt-monster balance notes on why the OLD flat-5x
# placeholder undercounted real player power) — so it's calibrated to match the players who'd
# actually be at Foundation Establishment already, not to double as a QC-era stepping stone
# the way Boar King does. Same pessimistic baseline (starter gear only, no
# Guard/potions/Gu passives): ~0% solo, ~72% for a party of 3, averaging ~2.4/3 survivors —
# landed in-band on the first pass, no further tuning needed.
THUNDERHORN_HERD_TYRANT = Monster(
    name="Thunderhorn Herd Tyrant",
    realm="Rank 2 Beast (Raid)",
    monster_type="Beast",
    habitat="High Storm Plateaus",
    description="The storm-crowned bull that leads every Thunderhorn Yak on the plateau — lightning doesn't strike it so much as follow it.",
    hp=1420, atk_stat=58, str_stat=178, def_stat=64, spd_stat=34, luck_stat=1, qi_stat=220,
    ability=MonsterAbility(
        name="Herd Tyrant's Charge", description="A lightning-wreathed charge backed by the full weight of the herd's own leader.", str_multiplier=1.35,
    ),
    drops=[
        # Raid boss chances/quantities scaled back to original after a brief experiment with
        # a much bigger bump (that generosity moved over to World Boss instead — see
        # world_boss.py). Herbs stay, mirroring Beast Material's own chance/quantity exactly
        # per the still-standing "herbs equal to beast materials" request.
        DropEntry(chance=1.00, item_name="Tier 2 Beast Material", quantity=2),
        DropEntry(chance=1.00, item_name="Tier 2 Herb", quantity=2),
        DropEntry(chance=0.70, item_name="Tier 2 Beast Core", quantity=2),
        DropEntry(chance=0.70, item_name="Tier 2 Beast Material", quantity=2),
        DropEntry(chance=0.70, item_name="Tier 2 Herb", quantity=2),
        DropEntry(chance=0.55, item_name="Tier 3 Beast Material"),
        DropEntry(chance=0.55, item_name="Tier 3 Herb"),
        DropEntry(chance=0.35, item_name="Thunderhorn Gu (Common)"),
    ],
    gu_rank=2,
)
STORM_CALF_GUARDIAN = Monster(
    name="Storm-Calf Guardian",
    realm="Rank 2 Beast (Raid)",
    monster_type="Beast",
    habitat="High Storm Plateaus",
    description="A younger, thicker-hided bull that plants itself between the herd's leader and anything foolish enough to approach.",
    hp=680, atk_stat=34, str_stat=95, def_stat=82, spd_stat=24, luck_stat=0, qi_stat=160,
    ability=MonsterAbility(
        name="Bulwark Strike", description="A slow, heavily armored headbutt.", str_multiplier=1.1,
    ),
    drops=[], gu_rank=2,
)
LIGHTNING_TICK_SWARM = Monster(
    name="Lightning Tick Swarm",
    realm="Rank 2 Beast (Raid)",
    monster_type="Beast",
    habitat="High Storm Plateaus",
    description="A crackling mass of storm-ticks that rides the herd, biting whatever gets close.",
    hp=190, atk_stat=32, str_stat=48, def_stat=14, spd_stat=48, luck_stat=0, qi_stat=90,
    ability=MonsterAbility(
        name="Static Bite", description="A quick, static-charged bite.", str_multiplier=1.0,
    ),
    drops=[], gu_rank=2,
)

HUNDRED_BEAST_MOUNTAINS_RAID_GROUP = [THUNDERHORN_HERD_TYRANT, STORM_CALF_GUARDIAN, LIGHTNING_TICK_SWARM]
