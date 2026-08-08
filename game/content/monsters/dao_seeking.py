"""
Ten Thousand Dao Wilderness (Dao Seeking, realm_index=5) hunt catalog — this region's own
hand-authored roster, same 5-normal/2-elite/1-rare shape every prior region (Crimson Furnace
Province, Duskwraith Barrens) established, same 5-archetype framework (Guardian/Skirmisher/
Assassin/Brute/Mystic: HP/STR/DEF/SPD/ATK multipliers off a shared per-realm baseline).

Theme: countless past cultivators came here to comprehend their own Dao (realms.GREAT_REALMS'
own flavor text: "begin walking the true path") -- most failed, and what's left behind are
twisted manifestations of an incomplete or corrupted Dao. Each of the 5 normal monsters is
tied to one of this game's own real Dao Paths (see game/dao_paths.py), rather than inventing
disconnected lore.

Tuning approach: Spirit Severing (realm_index=4) has no hand-authored content of its own to
chain a realm-to-realm ratio from the way Duskwraith Barrens chained off Crimson Furnace
Province, so this batch STARTED from monsters.REALM_SCALING_BOOST's own corrected
generic-formula output for realm_index=5 as an initial baseline -- but actually running that
baseline through scratchpad/simulate_dao_seeking_hunts.py (a realistic realm-20-stage,
pure-base-stat player, same pessimistic methodology every prior region's simulator used)
showed it was WAY too weak (~99-100% win rates across the board): a realm-20 character's own
pure breakthrough-stat compounding (5 Great Realm crossings + 15 substage steps from realm 0)
already outpaces the REALM_SCALING_BOOST-corrected factor on its own, before any of the extra
real-player bonuses (Dao Paths/Killer Move/Companion/Avatar/accessories) that boost was
actually meant to compensate for. So the generic formula was abandoned as a calibration
target and every stat here was instead tuned EMPIRICALLY against the simulator directly
(~1.42x over the original generic-formula-derived baseline for normals, ~1.25x further on top
for elites) until win rates landed in the same healthy bands Duskwraith Barrens' own
simulator run found (~80-92% normals, ~45-65% elites) -- see simulate_dao_seeking_hunts.py's
own module docstring for the full reasoning.

No new unique flavor-material items this batch (same "lean on the generic tier drops" scope
every prior region including Duskwraith Barrens settled on) -- drops lean on the existing
generic Tier 6 Beast Core/Material plus this region's own 5 new Gu families (see
gu_families_dao_seeking.py), one per archetype below.
"""

from ...monsters import DropEntry, Monster, MonsterAbility

STONEHEART_DAO_WARDEN = Monster(
    name="Stoneheart Dao Warden",
    realm="Rank 6 Beast",
    monster_type="Beast",
    habitat="Sundered Cliff Terraces, the Unmoving Vale",
    description="A cultivator who sought the Earth Dao's unyielding stillness and never found a way back out of it — flesh long since given way to living stone.",
    # Guardian archetype (HP 1.20, STR 0.80, DEF 1.35, SPD 0.75, ATK 0.90) against this
    # region's own realm-5 baseline, simulator-tuned (see module docstring).
    hp=1730625, atk_stat=119812, str_stat=266250, def_stat=209672, spd_stat=116484, luck_stat=1, qi_stat=443750,
    ability=MonsterAbility(
        name="Unmoving Verdict", description="A slow, immovable strike carrying the full weight of a stalled Dao.", str_multiplier=1.2,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 6 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 6 Beast Material"),
        DropEntry(chance=0.05, item_name="Stoneheart Gu (Common)"),
    ],
    gu_rank=6,
)

GALE_DAO_HARRIER = Monster(
    name="Gale-Dao Harrier",
    realm="Rank 6 Beast",
    monster_type="Beast",
    habitat="the Ever-Rushing Draw, Windrazor Passes",
    description="Once sought the Wind Dao's total freedom; now it can't stop moving even if it wanted to, a blur that never once touches the ground.",
    # Skirmisher archetype (HP 0.80, STR 0.95, DEF 0.75, SPD 1.35, ATK 1.15), simulator-tuned.
    hp=1153750, atk_stat=153094, str_stat=316172, def_stat=116484, spd_stat=209672, luck_stat=1, qi_stat=443750,
    ability=MonsterAbility(
        name="Ceaseless Gale Strike", description="A fast, opportunistic strike out of a body that never stops moving.", str_multiplier=1.42,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 6 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 6 Beast Material"),
        DropEntry(chance=0.05, item_name="Gale Fang Gu (Common)"),
    ],
    gu_rank=6,
)

THUNDERSTEP_WRAITH = Monster(
    name="Thunderstep Wraith",
    realm="Rank 6 Beast",
    monster_type="Beast",
    habitat="the Riven Sky-Scar, Thunderfall Hollow",
    description="Chased the Lightning Dao's instant, absolute clarity and got only the instant part — it exists in flickers, never in one place long enough to be truly seen.",
    # Assassin archetype (HP 0.70, STR 1.15, DEF 0.70, SPD 1.40, ATK 1.30), simulator-tuned.
    hp=1009531, atk_stat=173062, str_stat=382734, def_stat=108719, spd_stat=217438, luck_stat=1, qi_stat=443750,
    ability=MonsterAbility(
        name="Thunderstep Cut", description="A near-instant strike out of a flicker of afterimage.", str_multiplier=1.3,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 6 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 6 Beast Material"),
        DropEntry(chance=0.05, item_name="Thunderstep Gu (Common)"),
    ],
    gu_rank=6,
)

CRIMSON_VEIN_DAO_BEAST = Monster(
    name="Crimson-Vein Dao Beast",
    realm="Rank 6 Beast",
    monster_type="Beast",
    habitat="the Bloodsoil Reaches, Scarlet Marrow Flats",
    description="Sought the Blood Dao's raw vitality and lost itself entirely to the hunger that came with it — every wound it deals feeds the same endless craving.",
    # Brute archetype (HP 1.25, STR 1.20, DEF 1.00, SPD 0.80, ATK 0.90), simulator-tuned --
    # Brute's own HP+STR combo (both above baseline at once) landed meaningfully harder than
    # the other 4 archetypes at the same scale, so its ability str_multiplier was pulled down
    # further than Duskwraith's own Barren Tusk-Ox equivalent (1.05 -> 0.85) to bring it back
    # into the same win-rate band as its siblings.
    hp=1802734, atk_stat=119812, str_stat=399375, def_stat=155312, spd_stat=124250, luck_stat=1, qi_stat=443750,
    ability=MonsterAbility(
        name="Vein-Deep Rend", description="A savage, blood-hungry tear.", str_multiplier=0.85,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 6 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 6 Beast Material"),
        DropEntry(chance=0.05, item_name="Crimson Vein Gu (Common)"),
    ],
    gu_rank=6,
)

HOLLOW_SAGE_WISP = Monster(
    name="Hollow Sage Wisp",
    realm="Rank 6 Beast",
    monster_type="Spirit",
    habitat="the Whispering Archive Ruins, Still-Water Hollow",
    description="A wisp of pure insight left over from a cultivator who saw too much of the Wisdom Dao too fast — the body burned away, the understanding never quite finished happening.",
    # Mystic archetype (HP 0.90, STR 0.85, DEF 0.90, SPD 1.00, ATK 1.10), simulator-tuned --
    # qi_stat carries the same ~8.6% Mystic bump Soulglass Serpent's own normal got in
    # Duskwraith Barrens.
    hp=1297969, atk_stat=146438, str_stat=282891, def_stat=139781, spd_stat=155312, luck_stat=0, qi_stat=481912,
    ability=MonsterAbility(
        name="Unfinished Insight", description="A searing, half-comprehended strike of raw Dao-light.", str_multiplier=1.5,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 6 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 6 Beast Material"),
        DropEntry(chance=0.05, item_name="Hollow Sage Gu (Common)"),
    ],
    gu_rank=6,
)

DAO_SEVERED_COLOSSUS = Monster(
    name="Dao-Severed Colossus",
    realm="Rank 6 Beast (Elite)",
    monster_type="Beast",
    habitat="the Unmoving Vale's Deepest Terrace",
    description="Sought a Dao and found none at all -- what's left is a mindless engine of destruction with no path left to walk, kin to every stalled Warden this vale ever swallowed.",
    # Guardian-leaning, ~1.25x over the Guardian normal baseline (same "elite modestly above
    # its archetype peer" precedent Duskwraith Reaver/Hollow Marrow Behemoth used, tuned
    # slightly higher than Duskwraith's own 1.15x to land in the same ~45-65% simulated band).
    hp=2163281, atk_stat=149766, str_stat=332812, def_stat=262090, spd_stat=145605, luck_stat=1, qi_stat=519631,
    ability=MonsterAbility(
        name="Severed Verdict", description="A relentless, path-less strike with nothing left to hold it back.", str_multiplier=1.12,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 6 Beast Core"),
        DropEntry(chance=0.80, item_name="Tier 6 Beast Material"),
        DropEntry(chance=0.10, item_name="Stoneheart Gu (Common)"),
        DropEntry(chance=0.05, item_name="Primeval Essence Crystal", quantity=6),
    ],
    gu_rank=6,
    encounter_weight=0.25,
    elite=True,
)

TEN_THOUSAND_BLADE_INTENT_WRAITH = Monster(
    name="Ten-Thousand-Blade Intent Wraith",
    realm="Rank 6 Beast (Elite)",
    monster_type="Spirit",
    habitat="the Riven Sky-Scar's Deepest Fracture",
    description="Consumed entirely by battle intent chasing the Lightning Dao's instant clarity -- kin to every Thunderstep Wraith the sky-scar has ever produced, just further gone.",
    # Assassin-leaning, ~1.25x over the Assassin normal baseline (simulator-tuned).
    hp=1261914, atk_stat=216328, str_stat=478418, def_stat=135898, spd_stat=271797, luck_stat=1, qi_stat=519631,
    ability=MonsterAbility(
        name="Ten Thousand Cuts", description="A blur of strikes, each one carrying a fragment of unfinished battle intent.", str_multiplier=1.3,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 6 Beast Core"),
        DropEntry(chance=0.80, item_name="Tier 6 Beast Material"),
        DropEntry(chance=0.10, item_name="Thunderstep Gu (Common)"),
        DropEntry(chance=0.05, item_name="Primeval Essence Crystal", quantity=6),
    ],
    gu_rank=6,
    encounter_weight=0.25,
    elite=True,
)

NAMELESS_DAO_WANDERER = Monster(
    name="Nameless Dao Wanderer",
    realm="Rank 6 Spirit (Rare)",
    monster_type="Spirit",
    habitat="Wherever a fresh Dao insight draws it",
    description=(
        "Actually comprehended a fragment of a true Dao, and it changed them past recognition -- erratic, half-real, "
        "and never quite where the last strike landed."
    ),
    # Rare/apex encounter through erratic evasiveness (very high SPD, suppressed everything
    # else) -- same shape as Whispering Soul-Moth Queen. Same known, documented limitation:
    # pure evasion tuning can't push a real win-rate-over-many-rounds simulation below ~100%
    # when the monster's own offense is negligible, so this may not land in the "rare apex"
    # band the two elites above do -- an honest gap rather than a faked capture/negotiate
    # mechanic hunt.py doesn't support.
    hp=504766, atk_stat=73219, str_stat=99844, def_stat=62125, spd_stat=201906, luck_stat=3, qi_stat=244062,
    ability=MonsterAbility(
        name="Unfixed Step", description="An unpredictable, half-real strike from a body that hasn't fully settled into being one thing.", str_multiplier=0.95,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 6 Beast Material", quantity=3),
        DropEntry(chance=0.55, item_name="Tier 7 Beast Material"),
        DropEntry(chance=0.45, item_name="Primeval Essence Crystal", quantity=12),
    ],
    gu_rank=6,
    encounter_weight=0.08,
    elite=False,
)

DAO_SEEKING_MONSTERS = [
    STONEHEART_DAO_WARDEN, GALE_DAO_HARRIER, THUNDERSTEP_WRAITH, CRIMSON_VEIN_DAO_BEAST, HOLLOW_SAGE_WISP,
    DAO_SEVERED_COLOSSUS, TEN_THOUSAND_BLADE_INTENT_WRAITH, NAMELESS_DAO_WANDERER,
]

# -- Ten Thousand Dao Wilderness raids ---------------------------------------------------
# Two raid groups, same "realm had no pre-existing raid, both fully new" situation Duskwraith
# Barrens was in -- tied thematically one step further past this module's own elite hunts,
# same "raid main is stronger than its elite hunt cousin" precedent. Same story as the hunt
# roster above: the original realm-5 raid-generic baseline (see module docstring) tested WAY
# too weak against simulate_dao_seeking_raids.py's realistic realm-20 3-party, so each group
# was scaled up empirically (Group 1 ~4.3x, Group 2 ~4.1x over that original baseline) until
# a party of 3 landed in the same ~60-70%-win-rate / ~2.4-survivors band Duskwraith Barrens'
# own two raid groups did; a solo player still can't win either fight (0% at party size 1),
# same as every prior region's raids.
HEAVEN_DEFYING_DAO_TYRANT = Monster(
    name="Heaven-Defying Dao Tyrant",
    realm="Rank 6 Beast (Raid)",
    monster_type="Spirit",
    habitat="the Wilderness' Own Sundered Heart",
    description="Tried to bend heaven's own will to fit their Dao instead of the other way around -- every lesser wanderer in the wilderness answers to what's left of them.",
    hp=6450000, atk_stat=193500, str_stat=387000, def_stat=193500, spd_stat=150500, luck_stat=2, qi_stat=860000,
    ability=MonsterAbility(
        name="Tyrant's Defiant Verdict", description="A strike backed by the full, unbroken weight of a Dao that refuses to yield.", str_multiplier=1.55,
    ),
    drops=[
        # Same shape/quantities as the generic realm 4-6 raid-main formula
        # (monsters._generate_raid_group) and Duskwraith Barrens' own Group 1 -- see that
        # generator's comment for the Soul Nourishing Pill/Soul Crystal quantity history.
        DropEntry(chance=1.00, item_name="Tier 6 Beast Material", quantity=2),
        DropEntry(chance=1.00, item_name="Tier 6 Herb", quantity=2),
        DropEntry(chance=0.70, item_name="Tier 6 Beast Core", quantity=2),
        DropEntry(chance=0.55, item_name="Tier 7 Beast Material"),
        DropEntry(chance=0.55, item_name="Tier 7 Herb"),
        DropEntry(chance=0.35, item_name="Gale Fang Gu (Common)"),
        DropEntry(chance=0.75, item_name="Soul Nourishing Pill", quantity=5),
        DropEntry(chance=0.60, item_name="Soul Crystal", quantity=5),
    ],
    gu_rank=6,
)
BROKEN_VOW_ACOLYTE = Monster(
    name="Broken Vow Acolyte",
    realm="Rank 6 Beast (Raid)",
    monster_type="Spirit",
    habitat="the Wilderness' Own Sundered Heart",
    description="Swore themselves to the Tyrant's own defiance and broke against it instead -- quick enough to flank while the Tyrant holds attention.",
    hp=1032000, atk_stat=116100, str_stat=189200, def_stat=81700, spd_stat=111800, luck_stat=0, qi_stat=206400,
    ability=MonsterAbility(name="Flanking Verdict", description="A quick, opportunistic strike.", str_multiplier=1.3),
    drops=[], gu_rank=6,
)
OATH_BOUND_REMNANT = Monster(
    name="Oath-Bound Remnant",
    realm="Rank 6 Beast (Raid)",
    monster_type="Spirit",
    habitat="the Wilderness' Own Sundered Heart",
    description="What's left of a cultivator too oath-bound to the Tyrant's own cause to ever leave, even now.",
    hp=1290000, atk_stat=94600, str_stat=154800, def_stat=111800, spd_stat=73100, luck_stat=0, qi_stat=180600,
    ability=MonsterAbility(name="Bound Strike", description="A slow, unshakable strike.", str_multiplier=1.15),
    drops=[], gu_rank=6,
)
HEAVEN_DEFYING_DAO_TYRANT_RAID_GROUP = [HEAVEN_DEFYING_DAO_TYRANT, BROKEN_VOW_ACOLYTE, OATH_BOUND_REMNANT]

WORLD_SUNDERING_INTENT_COLOSSUS = Monster(
    name="World-Sundering Intent Colossus",
    realm="Rank 6 Beast (Raid)",
    monster_type="Beast",
    habitat="the Wilderness' Deepest Fracture",
    description="A colossus grown massive on decades of accumulated, unresolved battle intent -- the wilderness' own deepest fracture never quite closes around it.",
    hp=6560000, atk_stat=172200, str_stat=348500, def_stat=246000, spd_stat=114800, luck_stat=2, qi_stat=779000,
    ability=MonsterAbility(
        name="World-Sundering Crush", description="A crushing, world-cracking slam backed by the wilderness' own largest colossus.", str_multiplier=1.62,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 6 Beast Material", quantity=2),
        DropEntry(chance=1.00, item_name="Tier 6 Herb", quantity=2),
        DropEntry(chance=0.70, item_name="Tier 6 Beast Core", quantity=2),
        DropEntry(chance=0.55, item_name="Tier 7 Beast Material"),
        DropEntry(chance=0.55, item_name="Tier 7 Herb"),
        DropEntry(chance=0.35, item_name="Crimson Vein Gu (Common)"),
        DropEntry(chance=0.75, item_name="Soul Nourishing Pill", quantity=5),
        DropEntry(chance=0.60, item_name="Soul Crystal", quantity=5),
    ],
    gu_rank=6,
)
SPLINTERED_WILL_WISP = Monster(
    name="Splintered Will Wisp",
    realm="Rank 6 Beast (Raid)",
    monster_type="Spirit",
    habitat="the Wilderness' Deepest Fracture",
    description="A fast, fractured sliver of the Colossus's own splintered will, darting ahead of the main bulk.",
    hp=902000, atk_stat=106600, str_stat=172200, def_stat=73800, spd_stat=114800, luck_stat=0, qi_stat=205000,
    ability=MonsterAbility(name="Splinter Strike", description="A quick, fractured strike.", str_multiplier=1.15),
    drops=[], gu_rank=6,
)
ECHO_OF_A_FAILED_ASCENSION = Monster(
    name="Echo of a Failed Ascension",
    realm="Rank 6 Beast (Raid)",
    monster_type="Spirit",
    habitat="the Wilderness' Deepest Fracture",
    description="The lingering echo of a cultivator whose ascension attempt fed directly into the Colossus's own growth.",
    hp=1189000, atk_stat=94300, str_stat=155800, def_stat=102500, spd_stat=73800, luck_stat=0, qi_stat=180400,
    ability=MonsterAbility(name="Echoing Slam", description="A slow, heavy slam.", str_multiplier=1.2),
    drops=[], gu_rank=6,
)
WORLD_SUNDERING_INTENT_COLOSSUS_RAID_GROUP = [WORLD_SUNDERING_INTENT_COLOSSUS, SPLINTERED_WILL_WISP, ECHO_OF_A_FAILED_ASCENSION]
