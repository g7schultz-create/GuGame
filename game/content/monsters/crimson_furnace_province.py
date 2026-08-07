"""
Crimson Furnace Province (Core Formation) hunt catalog — content expansion brief section
7.3. Same situation as Hundred Beast Mountains: no pre-existing hand-authored realm-2 hunt
monster to preserve, so all 8 are new, tuned against a REAL simulated realm_index=8 (Core
Formation Early) character (chargen.roll_base_stats() pushed through 8 real
database.apply_breakthrough calls) rather than the old flat-scaled placeholder — see
scratchpad/simulate_crimson_furnace_hunts.py, same methodology as the other two regions.

Runaway Living Pill (the brief's own "Rare Encounter") is described as a branching-choice
encounter — "kill it for ingredients / capture it for a rare alchemy component / let it
escape for a future clue / Wisdom or Luck paths may do better" — none of which hunt.py
supports (no capture/negotiate/escape-consequence action exists, only Attack/Observe/Guard/
Flee/Empower/Gu ability/Class ability/Potion). Represented honestly as a real fight instead,
per this session's own established "don't fake it, mark as FUTURE HOOK" rule: erratic and
evasive (high SPD, moderate everything else) rather than a fake multi-outcome encounter, with
its own "rare alchemy component" reward folded into a real drop (a generic Tier 3 Beast
Core, per this file's own materials normalization below) instead of a choice-gated one. Same
known limitation as Hundred-Year Spirit Ginseng: pure evasion tuning can't push a real
win-rate-over-many-rounds simulation below ~100% when the monster's own offense is negligible
(a patient player always eventually lands enough hits with zero real risk) — it doesn't hit
the brief's own ~25-45% "rare apex" band the way Wandering Beast Tamer Remnant's raw-danger
version of the same slot does, and won't until a real flee/escape mechanic exists.

Balance (see scratchpad/simulate_crimson_furnace_hunts.py): all 5 normals landed in the
~80-92% target band, both elites in ~45-65%, on the second tuning pass.

Material drops are generic "Tier 3 Beast Core"/"Tier 3 Beast Material" only, across the
board — normalized the same way Verdant Borderlands' and Hundred Beast Mountains' own drop
tables were, away from this region's original unique-named trophy materials (Magma Scale,
Living Furnace Heart, Living Pill Core, etc., still defined as inert flavor items in
materials_crimson_furnace.py for anything that still references their names). Gu drops and
Primeval Essence Crystal drops are untouched.
"""

from ...monsters import DropEntry, Monster, MonsterAbility, TIER_1_GU_COMMON_POOL

MAGMA_SCALE_SALAMANDER = Monster(
    name="Magma-Scale Salamander",
    realm="Rank 3 Beast",
    monster_type="Beast",
    habitat="Volcanic Fissures, Forge-Warmed Caverns",
    description="A salamander whose scales have gone molten-orange from decades of basking beside active fissures.",
    # Guardian archetype (brief 6.3: HP 1.20, STR 0.80, DEF 1.35, SPD 0.75, ATK 0.90).
    hp=4078, atk_stat=262, str_stat=560, def_stat=427, spd_stat=221, luck_stat=1, qi_stat=700,
    ability=MonsterAbility(
        name="Molten Coil", description="A slow, heavily armored coiling strike.", str_multiplier=1.2,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 3 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 3 Beast Material"),
        DropEntry(chance=0.30, item_name="Tier 3 Beast Material"),
        DropEntry(chance=0.05, item_name="Magma Skin Gu (Common)"),
    ],
    gu_rank=3,
)

BRASS_FURNACE_HOUND = Monster(
    name="Brass Furnace Hound",
    realm="Rank 3 Beast",
    monster_type="Beast",
    habitat="Smithing City Outskirts, Forge Yards",
    description="A hound with a brass-plated hide, said to be bred by smiths to guard forges that never cool.",
    # Skirmisher archetype (brief 6.3: HP 0.80, STR 0.95, DEF 0.75, SPD 1.35, ATK 1.15).
    hp=2718, atk_stat=335, str_stat=665, def_stat=237, spd_stat=398, luck_stat=1, qi_stat=700,
    ability=MonsterAbility(
        name="Furnace Bite", description="A fast, forge-hot bite.", str_multiplier=1.42,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 3 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 3 Beast Material"),
        DropEntry(chance=0.30, item_name="Tier 3 Beast Material"),
        DropEntry(chance=0.05, item_name="Furnace Heart Gu (Common)"),
    ],
    gu_rank=3,
)

ASHWING_CROW = Monster(
    name="Ashwing Crow",
    realm="Rank 3 Beast",
    monster_type="Beast",
    habitat="Ash-Choked Skies",
    description="A crow whose wings trail fine ash instead of shedding feathers — never quite lands, never quite stops watching.",
    # Assassin archetype (brief 6.3: HP 0.70, STR 1.15, DEF 0.70, SPD 1.40, ATK 1.30).
    hp=2379, atk_stat=378, str_stat=805, def_stat=221, spd_stat=413, luck_stat=1, qi_stat=700,
    ability=MonsterAbility(
        name="Ashfall Dive", description="A near-silent diving strike out of drifting ash.", str_multiplier=1.3,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 3 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 3 Beast Material"),
        DropEntry(chance=0.30, item_name="Tier 3 Beast Material"),
        DropEntry(chance=0.05, item_name="Ashwing Gu (Common)"),
    ],
    gu_rank=3,
)

MOLTEN_SHELL_SCORPION = Monster(
    name="Molten Shell Scorpion",
    realm="Rank 3 Beast",
    monster_type="Beast",
    habitat="Cooled Lava Fields",
    description="A scorpion whose shell hardened mid-molt over an active lava seam — its pincers still run hot.",
    # Brute archetype (brief 6.3: HP 1.25, STR 1.20, DEF 1.00, SPD 0.80, ATK 0.90).
    hp=4248, atk_stat=262, str_stat=780, def_stat=316, spd_stat=236, luck_stat=1, qi_stat=700,
    ability=MonsterAbility(
        name="Crushing Pincer", description="A slow, crushing pincer strike.", str_multiplier=1.05,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 3 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 3 Beast Material"),
        DropEntry(chance=0.30, item_name="Tier 3 Beast Material"),
        DropEntry(chance=0.05, pool=TIER_1_GU_COMMON_POOL),
    ],
    gu_rank=3,
)

EMBER_VEIN_PYTHON = Monster(
    name="Ember Vein Python",
    realm="Rank 3 Beast",
    monster_type="Beast",
    habitat="Warm Ash Burrows",
    description="A python with veins of visible ember running just beneath translucent scales.",
    # Mystic archetype (brief 6.3: HP 0.90, STR 0.85, DEF 0.90, SPD 1.00, ATK 1.10).
    hp=3058, atk_stat=320, str_stat=595, def_stat=284, spd_stat=295, luck_stat=0, qi_stat=760,
    ability=MonsterAbility(
        name="Ember Fang", description="A searing, venom-hot bite.", str_multiplier=1.5,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 3 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 3 Beast Material"),
        DropEntry(chance=0.30, item_name="Tier 3 Beast Material"),
        DropEntry(chance=0.05, pool=TIER_1_GU_COMMON_POOL),
    ],
    gu_rank=3,
)

CRIMSON_FURNACE_LION = Monster(
    name="Crimson Furnace Lion",
    realm="Rank 3 Beast (Elite)",
    monster_type="Beast",
    habitat="Furnace-Warmed Highlands",
    description="A lion whose mane burns like banked coals — kin to the Crimson Furnace Lion King the raid-tier pride answers to.",
    hp=4885, atk_stat=314, str_stat=860, def_stat=348, spd_stat=236, luck_stat=1, qi_stat=820,
    ability=MonsterAbility(
        name="Furnace Roar Strike", description="A roaring, furnace-hot strike.", str_multiplier=1.12,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 3 Beast Core"),
        DropEntry(chance=0.80, item_name="Tier 3 Beast Material"),
        DropEntry(chance=0.45, item_name="Tier 3 Beast Material"),
        DropEntry(chance=0.10, item_name="Living Flame Gu (Common)"),
        DropEntry(chance=0.05, item_name="Primeval Essence Crystal", quantity=6),
    ],
    gu_rank=3,
    encounter_weight=0.25,
    elite=True,
)

STAR_IRON_DEVOURING_WORM = Monster(
    name="Star-Iron Devouring Worm",
    realm="Rank 3 Beast (Elite)",
    monster_type="Beast",
    habitat="Meteor-Scarred Tunnels",
    description="A worm that burrows through fallen star-iron ore and digests it slower than it grows.",
    hp=4486, atk_stat=301, str_stat=672, def_stat=448, spd_stat=221, luck_stat=1, qi_stat=820,
    ability=MonsterAbility(
        name="Devouring Coil", description="A crushing, ore-grinding coil.", str_multiplier=1.3,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 3 Beast Core"),
        DropEntry(chance=0.80, item_name="Tier 3 Beast Material"),
        DropEntry(chance=0.45, item_name="Tier 3 Beast Material"),
        DropEntry(chance=0.10, item_name="Star-Iron Stomach Gu (Common)"),
        DropEntry(chance=0.05, item_name="Primeval Essence Crystal", quantity=6),
    ],
    gu_rank=3,
    encounter_weight=0.25,
    elite=True,
)

RUNAWAY_LIVING_PILL = Monster(
    name="Runaway Living Pill",
    realm="Rank 3 Alchemical (Rare)",
    monster_type="Alchemical",
    habitat="Alchemy Valley Ruins",
    description=(
        "A pill that condensed just enough awareness to run from the furnace before it finished cooking — "
        "erratic, evasive, and not entirely sure it wants to be caught."
    ),
    # Rare/apex encounter through erratic evasiveness (very high SPD, moderate everything
    # else) rather than raw danger — closer in spirit to Hundred-Year Spirit Ginseng's slot
    # than Wandering Beast Tamer Remnant's, matching the brief's own "captured, not fought
    # down" framing as closely as a straight fight honestly can.
    hp=1250, atk_stat=190, str_stat=260, def_stat=160, spd_stat=470, luck_stat=3, qi_stat=650,
    ability=MonsterAbility(
        name="Erratic Burst", description="An unpredictable, half-controlled burst of pill-qi.", str_multiplier=0.95,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 3 Beast Core"),
        DropEntry(chance=0.55, item_name="Tier 3 Beast Material"),
        DropEntry(chance=0.45, item_name="Primeval Essence Crystal", quantity=12),
    ],
    gu_rank=3,
    encounter_weight=0.08,
    elite=False,
)

CRIMSON_FURNACE_PROVINCE_MONSTERS = [
    MAGMA_SCALE_SALAMANDER, BRASS_FURNACE_HOUND, ASHWING_CROW, MOLTEN_SHELL_SCORPION, EMBER_VEIN_PYTHON,
    CRIMSON_FURNACE_LION, STAR_IRON_DEVOURING_WORM, RUNAWAY_LIVING_PILL,
]

# -- Crimson Furnace Province raids (content brief section 7.3's own "Raid 1"/"Raid 2") ------
# Unlike Hundred Beast Mountains (where Boar King already existed as realm 1's "first" raid,
# so Thunderhorn Herd Tyrant was purely additive), realm 2 had no pre-existing raid at all —
# just the generic _generate_raid_group placeholder — so BOTH of these are new, and both
# replace that placeholder outright (RAID_GROUPS_BY_REALM[2] becomes a 2-group weighted pool,
# same restructure Hundred Beast Mountains already established, just with no "keep the old
# one" leg this time). Both tie to this module's own elite hunt monsters one tier up, same
# "raid Alpha is stronger than its elite hunt cousin" precedent as Blood Fang Wolf/Thunderhorn
# Yak. Tuned against a real realm-8 (Core Formation Early) party: ~0% solo for both, ~62%
# for a party of 3 on Crimson Furnace Lion King and ~69% on Star-Iron Devourer.
CRIMSON_FURNACE_LION_KING = Monster(
    name="Crimson Furnace Lion King",
    realm="Rank 3 Beast (Raid)",
    monster_type="Beast",
    habitat="Furnace-Warmed Highlands",
    description="The pride's own furnace-maned ruler — every Crimson Furnace Lion on the highlands answers to it.",
    hp=7100, atk_stat=430, str_stat=1400, def_stat=470, spd_stat=250, luck_stat=1, qi_stat=1150,
    ability=MonsterAbility(
        name="Sovereign Furnace Roar", description="A roaring strike backed by the full weight of the pride's own ruler.", str_multiplier=1.55,
    ),
    drops=[
        # Raid boss chances/quantities scaled back to original after a brief experiment with
        # a much bigger bump (that generosity moved over to World Boss instead — see
        # world_boss.py). Herbs stay, mirroring Beast Material's own chance/quantity exactly
        # per the still-standing "herbs equal to beast materials" request.
        DropEntry(chance=1.00, item_name="Tier 3 Beast Material", quantity=2),
        DropEntry(chance=1.00, item_name="Tier 3 Herb", quantity=2),
        DropEntry(chance=0.70, item_name="Tier 3 Beast Core", quantity=2),
        DropEntry(chance=0.70, item_name="Tier 3 Beast Material", quantity=2),
        DropEntry(chance=0.70, item_name="Tier 3 Herb", quantity=2),
        DropEntry(chance=0.55, item_name="Tier 4 Beast Material"),
        DropEntry(chance=0.55, item_name="Tier 4 Herb"),
        DropEntry(chance=0.35, item_name="Living Flame Gu (Common)"),
    ],
    gu_rank=3,
)
ASHMANE_LIONESS = Monster(
    name="Ashmane Lioness",
    realm="Rank 3 Beast (Raid)",
    monster_type="Beast",
    habitat="Furnace-Warmed Highlands",
    description="One of the pride's own hunters, quick enough to flank while the King holds attention.",
    hp=2750, atk_stat=300, str_stat=660, def_stat=290, spd_stat=310, luck_stat=0, qi_stat=800,
    ability=MonsterAbility(name="Flanking Claw", description="A quick, opportunistic claw strike.", str_multiplier=1.3),
    drops=[], gu_rank=3,
)
FURNACE_CUB = Monster(
    name="Furnace Cub",
    realm="Rank 3 Beast (Raid)",
    monster_type="Beast",
    habitat="Furnace-Warmed Highlands",
    description="A young lion still learning to fight, but already hot-tempered enough to charge in anyway.",
    hp=1450, atk_stat=210, str_stat=400, def_stat=190, spd_stat=260, luck_stat=0, qi_stat=580,
    ability=MonsterAbility(name="Clumsy Pounce", description="An eager, not-quite-controlled pounce.", str_multiplier=1.15),
    drops=[], gu_rank=3,
)
CRIMSON_FURNACE_LION_KING_RAID_GROUP = [CRIMSON_FURNACE_LION_KING, ASHMANE_LIONESS, FURNACE_CUB]

STAR_IRON_DEVOURER = Monster(
    name="Star-Iron Devourer",
    realm="Rank 3 Beast (Raid)",
    monster_type="Beast",
    habitat="Meteor-Scarred Tunnels",
    description="The largest of the tunnel-worms, grown massive on decades of fallen star-iron ore.",
    hp=7350, atk_stat=405, str_stat=1160, def_stat=630, spd_stat=205, luck_stat=1, qi_stat=1180,
    ability=MonsterAbility(
        name="Devouring Maw", description="A crushing, ore-grinding bite backed by the tunnel's own largest worm.", str_multiplier=1.62,
    ),
    drops=[
        # Raid boss chances/quantities scaled back to original after a brief experiment with
        # a much bigger bump (that generosity moved over to World Boss instead — see
        # world_boss.py). Herbs stay, mirroring Beast Material's own chance/quantity exactly
        # per the still-standing "herbs equal to beast materials" request.
        DropEntry(chance=1.00, item_name="Tier 3 Beast Material", quantity=2),
        DropEntry(chance=1.00, item_name="Tier 3 Herb", quantity=2),
        DropEntry(chance=0.70, item_name="Tier 3 Beast Core", quantity=2),
        DropEntry(chance=0.70, item_name="Tier 3 Beast Material", quantity=2),
        DropEntry(chance=0.70, item_name="Tier 3 Herb", quantity=2),
        DropEntry(chance=0.55, item_name="Tier 4 Beast Material"),
        DropEntry(chance=0.55, item_name="Tier 4 Herb"),
        DropEntry(chance=0.35, item_name="Star-Iron Stomach Gu (Common)"),
    ],
    gu_rank=3,
)
METAL_PARASITE = Monster(
    name="Metal Parasite",
    realm="Rank 3 Beast (Raid)",
    monster_type="Beast",
    habitat="Meteor-Scarred Tunnels",
    description="A small, fast ore-parasite that rides the Devourer's own hide, biting at anything that gets close.",
    hp=1350, atk_stat=225, str_stat=350, def_stat=195, spd_stat=300, luck_stat=0, qi_stat=520,
    ability=MonsterAbility(name="Parasitic Bite", description="A quick, latching bite.", str_multiplier=1.15),
    drops=[], gu_rank=3,
)
FURNACE_SLAG_ELEMENTAL = Monster(
    name="Furnace Slag Elemental",
    realm="Rank 3 Beast (Raid)",
    monster_type="Beast",
    habitat="Meteor-Scarred Tunnels",
    description="Cooled slag and old ore given a slow, deliberate kind of life by the tunnel's own residual heat.",
    hp=3050, atk_stat=270, str_stat=540, def_stat=400, spd_stat=185, luck_stat=0, qi_stat=740,
    ability=MonsterAbility(name="Slag Slam", description="A slow, heavy slam.", str_multiplier=1.2),
    drops=[], gu_rank=3,
)
STAR_IRON_DEVOURER_RAID_GROUP = [STAR_IRON_DEVOURER, METAL_PARASITE, FURNACE_SLAG_ELEMENTAL]
