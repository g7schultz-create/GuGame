"""
Duskwraith Barrens (Nascent Soul, realm_index=3) hunt catalog — this region's own hand-
authored roster, same 5-normal/2-elite/1-rare shape Crimson Furnace Province (Core
Formation) established, same 5-archetype framework (Guardian/Skirmisher/Assassin/Brute/
Mystic: HP/STR/DEF/SPD/ATK multipliers off a shared per-realm baseline).

Tuning approach: combat.resolve_attack's own formulas are linear in every stat once ATK and
SPD clear their respective hit-chance/dodge-chance saturation points (24 ATK, 55 SPD — both
utterly dwarfed by realm_index=12's thousands-of-points stat blocks), so scaling EVERY stat
on a realm_index=8-tuned monster by the same constant reproduces the same hits-to-kill and
the same dodge/hit rates almost exactly (see scratchpad/simulate_duskwraith_hunts.py's own
verification run). Every stat here is Crimson Furnace Province's own already-validated
monster scaled by realm_index=8 -> realm_index=12's real measured stat ratio (~7.6x, both
sides confirmed via chargen.roll_base_stats() pushed through realms.stat_multiplier_for_next
12 times vs. 8 times) — luck_stat is left at the same tiny flat value as before (unscaled,
matching how player Luck itself never scales off breakthroughs either). Verified by actually
running the realm-12 simulator: all 5 normals landed in the ~80-92% target band, both elites
in ~45-65%, on the first pass — confirming the linear-scaling shortcut instead of re-deriving
every stat from scratch.

No new unique flavor-material items this batch (scope was "more monsters and Gu" specifically)
— drops lean on the existing generic Tier 4 Beast Core/Material plus this region's own 5 new
Gu families (see gu_families_duskwraith_barrens.py), one per archetype below.
"""

from ...monsters import DropEntry, Monster, MonsterAbility

BONEWROUGHT_GOLEM = Monster(
    name="Bonewrought Golem",
    realm="Rank 4 Beast",
    monster_type="Beast",
    habitat="Sun-Bleached Boneyards, Cracked Salt Flats",
    description="A hulking construct of fused bone and barren dust, animated by whatever soul-light lingers this deep in the wastes.",
    # Guardian archetype (HP 1.20, STR 0.80, DEF 1.35, SPD 0.75, ATK 0.90) — Crimson Furnace
    # Province's Magma-Scale Salamander scaled by the realm 8->12 ratio (~7.6x).
    hp=30993, atk_stat=1991, str_stat=4256, def_stat=3245, spd_stat=1680, luck_stat=1, qi_stat=5320,
    ability=MonsterAbility(
        name="Boneshatter Slam", description="A slow, heavily armored slam.", str_multiplier=1.2,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 4 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 4 Beast Material"),
        DropEntry(chance=0.05, item_name="Bonewrought Gu (Common)"),
    ],
    gu_rank=4,
)

DUSKFANG_JACKAL = Monster(
    name="Duskfang Jackal",
    realm="Rank 4 Beast",
    monster_type="Beast",
    habitat="Twilight Scrublands, Bone-Strewn Trails",
    description="A lean pack-hunter that runs the barrens at dusk, fangs stained dark with old soul-dust.",
    # Skirmisher archetype (HP 0.80, STR 0.95, DEF 0.75, SPD 1.35, ATK 1.15) — Brass Furnace
    # Hound scaled by ~7.6x.
    hp=20657, atk_stat=2546, str_stat=5054, def_stat=1801, spd_stat=3025, luck_stat=1, qi_stat=5320,
    ability=MonsterAbility(
        name="Duskfang Bite", description="A fast, opportunistic bite.", str_multiplier=1.42,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 4 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 4 Beast Material"),
        DropEntry(chance=0.05, item_name="Duskfang Gu (Common)"),
    ],
    gu_rank=4,
)

WRAITHMOTH = Monster(
    name="Wraithmoth",
    realm="Rank 4 Beast",
    monster_type="Beast",
    habitat="Ash-Grey Dust Clouds, Moonless Hollows",
    description="A moth the size of a grown man, wings trailing fine grey dust — never quite lands, never quite stops watching.",
    # Assassin archetype (HP 0.70, STR 1.15, DEF 0.70, SPD 1.40, ATK 1.30) — Ashwing Crow
    # scaled by ~7.6x.
    hp=18080, atk_stat=2873, str_stat=6118, def_stat=1680, spd_stat=3139, luck_stat=1, qi_stat=5320,
    ability=MonsterAbility(
        name="Wraith-Touch Strike", description="A near-silent strike out of drifting dust.", str_multiplier=1.3,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 4 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 4 Beast Material"),
        DropEntry(chance=0.05, item_name="Wraithmoth Gu (Common)"),
    ],
    gu_rank=4,
)

BARREN_TUSK_OX = Monster(
    name="Barren Tusk-Ox",
    realm="Rank 4 Beast",
    monster_type="Beast",
    habitat="Cracked Salt Flats, Dust-Choked Ravines",
    description="A huge, shaggy ox whose tusks have grown long enough to plow the barrens' own hard-packed salt crust.",
    # Brute archetype (HP 1.25, STR 1.20, DEF 1.00, SPD 0.80, ATK 0.90) — Molten Shell
    # Scorpion scaled by ~7.6x.
    hp=32285, atk_stat=1991, str_stat=5928, def_stat=2402, spd_stat=1794, luck_stat=1, qi_stat=5320,
    ability=MonsterAbility(
        name="Tusk Ram", description="A slow, crushing ram.", str_multiplier=1.05,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 4 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 4 Beast Material"),
        DropEntry(chance=0.05, item_name="Hollow Marrow Gu (Common)"),
    ],
    gu_rank=4,
)

SOULGLASS_SERPENT = Monster(
    name="Soulglass Serpent",
    realm="Rank 4 Beast",
    monster_type="Beast",
    habitat="Glass-Sand Dunes, Whispering Hollows",
    description="A serpent whose scales fused into translucent glass under the barrens' endless dusk-light, faintly luminous within.",
    # Mystic archetype (HP 0.90, STR 0.85, DEF 0.90, SPD 1.00, ATK 1.10) — Ember Vein Python
    # scaled by ~7.6x.
    hp=23241, atk_stat=2432, str_stat=4522, def_stat=2158, spd_stat=2242, luck_stat=0, qi_stat=5776,
    ability=MonsterAbility(
        name="Glassfang Bite", description="A searing, soul-touched bite.", str_multiplier=1.5,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 4 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 4 Beast Material"),
        DropEntry(chance=0.05, item_name="Soulglass Gu (Common)"),
    ],
    gu_rank=4,
)

DUSKWRAITH_REAVER = Monster(
    name="Duskwraith Reaver",
    realm="Rank 4 Beast (Elite)",
    monster_type="Beast",
    habitat="The Barrens' Deep Hollows",
    description="A wraith-touched dust-wolf that hunts through the barrens' dead hours, said to be drawn to a cultivator's newly-formed nascent soul like a moth to flame — kin to the Warlord the whole hollow answers to.",
    # Crimson Furnace Lion scaled by ~7.6x.
    hp=37126, atk_stat=2386, str_stat=6536, def_stat=2645, spd_stat=1794, luck_stat=1, qi_stat=6232,
    ability=MonsterAbility(
        name="Reaver's Hollow Strike", description="A relentless, soul-touched strike.", str_multiplier=1.12,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 4 Beast Core"),
        DropEntry(chance=0.80, item_name="Tier 4 Beast Material"),
        DropEntry(chance=0.10, item_name="Wraithmoth Gu (Common)"),
        DropEntry(chance=0.05, item_name="Primeval Essence Crystal", quantity=6),
    ],
    gu_rank=4,
    encounter_weight=0.25,
    elite=True,
)

HOLLOW_MARROW_BEHEMOTH = Monster(
    name="Hollow Marrow Behemoth",
    realm="Rank 4 Beast (Elite)",
    monster_type="Beast",
    habitat="The Deep Boneyards",
    description="A behemoth whose hollowed-out bones hum faintly with trapped soul-light — kin to the Colossus that rules the deepest boneyard.",
    # Star-Iron Devouring Worm scaled by ~7.6x.
    hp=34094, atk_stat=2288, str_stat=5107, def_stat=3405, spd_stat=1680, luck_stat=1, qi_stat=6232,
    ability=MonsterAbility(
        name="Marrow-Crushing Slam", description="A crushing, bone-grinding slam.", str_multiplier=1.3,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 4 Beast Core"),
        DropEntry(chance=0.80, item_name="Tier 4 Beast Material"),
        DropEntry(chance=0.10, item_name="Hollow Marrow Gu (Common)"),
        DropEntry(chance=0.05, item_name="Primeval Essence Crystal", quantity=6),
    ],
    gu_rank=4,
    encounter_weight=0.25,
    elite=True,
)

WHISPERING_SOUL_MOTH_QUEEN = Monster(
    name="Whispering Soul-Moth Queen",
    realm="Rank 4 Spirit (Rare)",
    monster_type="Spirit",
    habitat="Wherever a nascent soul's light draws it",
    description=(
        "A moth-queen woven from condensed soul-dust, drawn from leagues away by the light of a freshly-formed "
        "nascent soul — erratic, half-real, and never quite where the last strike landed."
    ),
    # Rare/apex encounter through erratic evasiveness (very high SPD, moderate everything
    # else) — same shape as Runaway Living Pill, scaled by ~7.6x. Same known limitation
    # flagged there: pure evasion tuning can't push a real win-rate-over-many-rounds
    # simulation below ~100% when the monster's own offense is negligible, so this doesn't
    # land in the "rare apex" band the way the two elites above do — an honest, documented
    # gap rather than a faked capture/negotiate mechanic hunt.py doesn't support.
    hp=9500, atk_stat=1444, str_stat=1976, def_stat=1216, spd_stat=3572, luck_stat=3, qi_stat=4940,
    ability=MonsterAbility(
        name="Whispering Dust Veil", description="An unpredictable, half-real veil of soul-dust.", str_multiplier=0.95,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 4 Beast Material", quantity=3),
        DropEntry(chance=0.55, item_name="Tier 5 Beast Material"),
        DropEntry(chance=0.45, item_name="Primeval Essence Crystal", quantity=12),
    ],
    gu_rank=4,
    encounter_weight=0.08,
    elite=False,
)

DUSKWRAITH_BARRENS_MONSTERS = [
    BONEWROUGHT_GOLEM, DUSKFANG_JACKAL, WRAITHMOTH, BARREN_TUSK_OX, SOULGLASS_SERPENT,
    DUSKWRAITH_REAVER, HOLLOW_MARROW_BEHEMOTH, WHISPERING_SOUL_MOTH_QUEEN,
]

# -- Duskwraith Barrens raids ------------------------------------------------------------
# Two raid groups, same "realm had no pre-existing raid, both fully new" situation Crimson
# Furnace Province was in — both tie to this module's own elite hunts one tier up, same
# "raid Alpha is stronger than its elite hunt cousin" precedent. Crimson Furnace Lion
# King/Star-Iron Devourer raid groups scaled by the same ~7.6x realm 8->12 ratio.
DUSKWRAITH_REAVER_WARLORD = Monster(
    name="Duskwraith Reaver Warlord",
    realm="Rank 4 Beast (Raid)",
    monster_type="Beast",
    habitat="The Barrens' Deep Hollows",
    description="The pack's own hollow-eyed ruler — every Duskwraith Reaver in the barrens answers to it.",
    hp=53960, atk_stat=3268, str_stat=10640, def_stat=3572, spd_stat=1900, luck_stat=1, qi_stat=8740,
    ability=MonsterAbility(
        name="Warlord's Hollow Reaping", description="A relentless strike backed by the full weight of the pack's own ruler.", str_multiplier=1.55,
    ),
    drops=[
        # Raid boss chances/quantities scaled back to original after a brief experiment with
        # a much bigger bump (that generosity moved over to World Boss instead — see
        # world_boss.py). Herbs stay, mirroring Beast Material's own chance/quantity exactly
        # per the still-standing "herbs equal to beast materials" request.
        DropEntry(chance=1.00, item_name="Tier 4 Beast Material", quantity=2),
        DropEntry(chance=1.00, item_name="Tier 4 Herb", quantity=2),
        DropEntry(chance=0.70, item_name="Tier 4 Beast Core", quantity=2),
        DropEntry(chance=0.55, item_name="Tier 5 Beast Material"),
        DropEntry(chance=0.55, item_name="Tier 5 Herb"),
        DropEntry(chance=0.35, item_name="Wraithmoth Gu (Common)"),
        # Nascent Soul Avatar leveling materials (see game/avatar.py's AVATAR_LEVEL_UP_RECIPE)
        # -- a smaller supplementary trickle alongside /split_body's own larger, dedicated
        # payout. Only Realm 3+ raid bosses drop these at all (see monsters._generate_raid_group
        # for the same addition at realms 4-6) since the avatar system doesn't unlock until
        # Nascent Soul.
        # Quantity history: 10 (initial big bump) -> 2 (turned down 75%, felt like too
        # little) -> 5 (buffed back up), a middle ground between the two per explicit
        # follow-up requests.
        DropEntry(chance=0.75, item_name="Soul Nourishing Pill", quantity=5),
        DropEntry(chance=0.60, item_name="Soul Crystal", quantity=5),
    ],
    gu_rank=4,
)
ASHEN_DUST_STALKER = Monster(
    name="Ashen Dust Stalker",
    realm="Rank 4 Beast (Raid)",
    monster_type="Beast",
    habitat="The Barrens' Deep Hollows",
    description="One of the pack's own hunters, quick enough to flank while the Warlord holds attention.",
    hp=20900, atk_stat=2280, str_stat=5016, def_stat=2204, spd_stat=2356, luck_stat=0, qi_stat=6080,
    ability=MonsterAbility(name="Flanking Strike", description="A quick, opportunistic strike.", str_multiplier=1.3),
    drops=[], gu_rank=4,
)
BONE_FANG_WHELP = Monster(
    name="Bone-Fang Whelp",
    realm="Rank 4 Beast (Raid)",
    monster_type="Beast",
    habitat="The Barrens' Deep Hollows",
    description="A young reaver still learning to hunt, but already hollow-eyed enough to charge in anyway.",
    hp=11020, atk_stat=1596, str_stat=3040, def_stat=1444, spd_stat=1976, luck_stat=0, qi_stat=4408,
    ability=MonsterAbility(name="Clumsy Lunge", description="An eager, not-quite-controlled lunge.", str_multiplier=1.15),
    drops=[], gu_rank=4,
)
DUSKWRAITH_REAVER_WARLORD_RAID_GROUP = [DUSKWRAITH_REAVER_WARLORD, ASHEN_DUST_STALKER, BONE_FANG_WHELP]

HOLLOW_MARROW_COLOSSUS = Monster(
    name="Hollow Marrow Colossus",
    realm="Rank 4 Beast (Raid)",
    monster_type="Beast",
    habitat="The Deep Boneyards",
    description="The largest of the boneyard's behemoths, grown massive on decades of buried soul-light.",
    hp=55860, atk_stat=3078, str_stat=8816, def_stat=4788, spd_stat=1558, luck_stat=1, qi_stat=8968,
    ability=MonsterAbility(
        name="Colossal Marrow Crush", description="A crushing, bone-grinding slam backed by the boneyard's own largest behemoth.", str_multiplier=1.62,
    ),
    drops=[
        # Raid boss chances/quantities scaled back to original after a brief experiment with
        # a much bigger bump (that generosity moved over to World Boss instead — see
        # world_boss.py). Herbs stay, mirroring Beast Material's own chance/quantity exactly
        # per the still-standing "herbs equal to beast materials" request.
        DropEntry(chance=1.00, item_name="Tier 4 Beast Material", quantity=2),
        DropEntry(chance=1.00, item_name="Tier 4 Herb", quantity=2),
        DropEntry(chance=0.70, item_name="Tier 4 Beast Core", quantity=2),
        DropEntry(chance=0.55, item_name="Tier 5 Beast Material"),
        DropEntry(chance=0.55, item_name="Tier 5 Herb"),
        DropEntry(chance=0.35, item_name="Hollow Marrow Gu (Common)"),
        # Nascent Soul Avatar leveling materials -- see DUSKWRAITH_REAVER_WARLORD's own
        # comment above for why only Realm 3+ raid bosses carry these.
        # Quantity turned down 75% from the initial bump (10 -> 2) -- the earlier 10-per-drop
        # rate was overshooting what avatar leveling actually needs (Level II only costs 5
        # Pills/2 Crystals total), per explicit follow-up request.
        DropEntry(chance=0.75, item_name="Soul Nourishing Pill", quantity=2),
        DropEntry(chance=0.60, item_name="Soul Crystal", quantity=2),
    ],
    gu_rank=4,
)
MARROW_LEECH = Monster(
    name="Marrow Leech",
    realm="Rank 4 Beast (Raid)",
    monster_type="Beast",
    habitat="The Deep Boneyards",
    description="A small, fast bone-parasite that rides the Colossus's own hide, biting at anything that gets close.",
    hp=10260, atk_stat=1710, str_stat=2660, def_stat=1482, spd_stat=2280, luck_stat=0, qi_stat=3952,
    ability=MonsterAbility(name="Parasitic Bite", description="A quick, latching bite.", str_multiplier=1.15),
    drops=[], gu_rank=4,
)
OSSUARY_WIGHT = Monster(
    name="Ossuary Wight",
    realm="Rank 4 Beast (Raid)",
    monster_type="Beast",
    habitat="The Deep Boneyards",
    description="Old bone and older dust given a slow, deliberate kind of life by the boneyard's own residual soul-light.",
    hp=23180, atk_stat=2052, str_stat=4104, def_stat=3040, spd_stat=1406, luck_stat=0, qi_stat=5624,
    ability=MonsterAbility(name="Bone Slam", description="A slow, heavy slam.", str_multiplier=1.2),
    drops=[], gu_rank=4,
)
HOLLOW_MARROW_COLOSSUS_RAID_GROUP = [HOLLOW_MARROW_COLOSSUS, MARROW_LEECH, OSSUARY_WIGHT]
