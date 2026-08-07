"""
Verdant Borderlands (Qi Condensation) hunt catalog — content expansion brief section 7.1.
Ironhide Boar itself is untouched and stays defined in game/monsters.py (the existing,
already-balance-tested anchor); this module adds the rest of that region's "Normal Hunts",
"Elite Hunts", and "Rare Encounter" entries around it.

Stats are hand-tuned against Ironhide Boar's own validated baseline (hp=65, atk=6, str=15,
def=7, spd=7, qi=20 — ~90% win rate for a fresh character, see IRONHIDE_BOAR's own comment)
using the brief's archetype multiplier table (section 6.3) as a starting point, then
adjusted from actual simulation results (see scratchpad/simulate_verdant_hunts.py) rather
than shipped as pure guesses — see each monster's own comment for its archetype and target
band (section 6.4: Normal ~80-92% win rate, Elite ~45-65%, Rare apex ~25-45% solo).

Each monster's "Rare" Gu slot now points at its own themed family from
game/content/gu_families.py (Concealed Fang Gu, Moon Rabbit Gu, Bone Shield Gu, Blood Fang
Gu, Iron Skin Gu — matching the brief's own per-monster write-ups), at Common quality, the
same convention every other hunt-dropped Gu in this game already uses (fusion via /gu is the
only way to reach higher qualities). Ironhide Boar itself is untouched — it still only rolls
TIER_1_GU_COMMON_POOL — but that pool now includes Boar Strength Gu too (see
gu_families.py), so Boar gained its own brief-intended signature Gu as a pure side effect of
the shared pool growing, without a single line of IRONHIDE_BOAR's own definition changing.
Red-Crest Crane and Hundred-Year Spirit Ginseng still use the shared pool / no Gu at all
respectively, matching the brief's own write-ups (neither names a signature Gu for them).
Two described mechanics are deliberately NOT implemented here, per the brief's own
section 2.4 ("mark it FUTURE HOOK... do not fake the effect"): Blood Fang Wolf's "increased
first-round damage" (needs a round-aware combat hook) and Grave-Moss Corpse Beetle's
"reduced incoming damage every third round" (needs monster-side conditional AI) — both
still hit hard/tank well through stats alone, just without the extra conditional behavior.
Hundred-Year Spirit Ginseng's "attempts to flee" is similarly represented honestly through
very high SPD/dodge rather than a fake auto-flee mechanic that isn't wired into /hunt.

Material drops are generic "Tier 1 Beast Core"/"Tier 1 Beast Material" only, across the
board — this region originally shipped with its own unique-named trophy materials (Ironhide
Bristle, Spirit Snake Fang, Moonlit Fur, etc., still defined as inert flavor items in
materials.py for anything that still references their names) as the non-Gu, non-Primeval-
Essence-Crystal drop line, later normalized to the same generic tiered items every other
drop table already uses; Gu drops and Primeval Essence Crystal drops are untouched.
"""

from ...monsters import DropEntry, Monster, MonsterAbility, TIER_1_GU_COMMON_POOL

BAMBOO_SHADOW_SNAKE = Monster(
    name="Bamboo Shadow Snake",
    realm="Rank 1 Beast",
    monster_type="Beast",
    habitat="Spiritual Bamboo Groves",
    description=(
        "A thin emerald serpent whose scales mimic the shifting shadows between spiritual "
        "bamboo stalks."
    ),
    # Assassin archetype (brief section 6.3: HP 0.70, STR 1.15, DEF 0.70, SPD 1.40, ATK 1.30
    # of a Brute baseline). The brief's own worked example (section 29) used hp=48/str=13/
    # str_multiplier=1.25 — simulated at ~99% win rate for a fresh character (well above the
    # ~80-92% target band), so hp/str/the ability's multiplier were all raised from that
    # starting point until simulate_verdant_hunts.py landed it in-band.
    hp=70, atk_stat=9, str_stat=16, def_stat=5, spd_stat=11, luck_stat=1, qi_stat=18,
    ability=MonsterAbility(
        name="Shadow Fang", description="A fast venomous bite delivered from concealment.", str_multiplier=1.35,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 1 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 1 Beast Material"),
        DropEntry(chance=0.30, item_name="Tier 1 Beast Material"),
        DropEntry(chance=0.05, item_name="Concealed Fang Gu (Common)"),
    ],
    gu_rank=1,
)

MOON_EARED_RABBIT = Monster(
    name="Moon-Eared Rabbit",
    realm="Rank 1 Beast",
    monster_type="Beast",
    habitat="Moonlit Clearings, Bamboo Forests",
    description="A pale rabbit that seems to drink moonlight, vanishing into the underbrush the instant it's threatened.",
    # Trickster-leaning: the brief's own 6.3 table has no numeric row for Trickster, so this
    # is hand-tuned toward "the safe pick of the five" rather than borrowed from an archetype
    # multiplier — deliberately the weakest normal-tier monster, but simulation still pushed
    # it up from an initial 100%-win-rate draft so choosing it isn't literally zero-risk.
    hp=62, atk_stat=8, str_stat=15, def_stat=4, spd_stat=13, luck_stat=3, qi_stat=16,
    ability=MonsterAbility(
        name="Moon Skip", description="A glancing strike thrown while already darting away.", str_multiplier=1.45,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 1 Beast Core"),
        DropEntry(chance=0.70, item_name="Tier 1 Beast Material"),
        DropEntry(chance=0.30, item_name="Tier 1 Beast Material"),
        DropEntry(chance=0.05, item_name="Moon Rabbit Gu (Common)"),
    ],
    gu_rank=1,
)

RED_CREST_CRANE = Monster(
    name="Red-Crest Crane",
    realm="Rank 1 Beast",
    monster_type="Beast",
    habitat="Riverbanks, Open Meadows",
    description="A territorial crane whose spear-like beak strikes faster than the eye can follow.",
    # Skirmisher archetype (brief 6.3: HP 0.80, STR 0.95, DEF 0.75, SPD 1.35, ATK 1.15),
    # raised from that starting ratio the same way as the rest of this file (see Bamboo
    # Shadow Snake's comment) after simulation showed the initial draft far too easy.
    hp=68, atk_stat=8, str_stat=17, def_stat=5, spd_stat=9, luck_stat=1, qi_stat=18,
    ability=MonsterAbility(
        name="Piercing Dive", description="A speed-driven diving strike with its beak.", str_multiplier=1.4,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 1 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 1 Beast Material"),
        DropEntry(chance=0.30, item_name="Tier 1 Beast Material"),
        DropEntry(chance=0.05, pool=TIER_1_GU_COMMON_POOL),
    ],
    gu_rank=1,
)

GRAVE_MOSS_CORPSE_BEETLE = Monster(
    name="Grave-Moss Corpse Beetle",
    realm="Rank 1 Beast",
    monster_type="Beast",
    habitat="Old Graves, Forest Floor",
    description="A shell-covered beetle feeding on the residual qi that lingers near old graves.",
    # Guardian archetype (brief 6.3: HP 1.20, STR 0.80, DEF 1.35, SPD 0.75, ATK 0.90) — tanky
    # and slow. High HP alone simulated as trivially easy (its low per-hit damage meant extra
    # rounds of exposure barely mattered), so its offense was raised to actually punish a
    # long fight, not just its raw HP.
    hp=78, atk_stat=8, str_stat=16, def_stat=9, spd_stat=5, luck_stat=0, qi_stat=20,
    ability=MonsterAbility(
        name="Shell Strike", description="A slow but heavily armored headbutt.", str_multiplier=1.22,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 1 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 1 Beast Material"),
        DropEntry(chance=0.30, item_name="Tier 1 Beast Material"),
        DropEntry(chance=0.05, item_name="Bone Shield Gu (Common)"),
    ],
    gu_rank=1,
)

BLOOD_FANG_WOLF = Monster(
    name="Blood Fang Wolf",
    realm="Rank 1 Beast (Elite)",
    monster_type="Beast",
    habitat="Deep Bamboo Forests",
    description="A lean, blood-maned wolf that hunts in the same borderlands Ironhide Boars roam — and preys on the weaker of them.",
    # Elite, Assassin-leaning (high STR/SPD, modest DEF) — targets ~45-65% win rate for a
    # fresh character per section 6.4, not the ~80-92% the normal tier above targets.
    hp=74, atk_stat=9, str_stat=21, def_stat=6, spd_stat=11, luck_stat=1, qi_stat=26,
    ability=MonsterAbility(
        name="Rending Bite", description="A vicious, blood-drawing bite.", str_multiplier=1.35,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 1 Beast Core"),
        DropEntry(chance=0.80, item_name="Tier 1 Beast Material"),
        DropEntry(chance=0.45, item_name="Tier 1 Beast Material"),
        DropEntry(chance=0.10, item_name="Blood Fang Gu (Common)"),
        DropEntry(chance=0.05, item_name="Primeval Essence Crystal", quantity=3),
    ],
    gu_rank=1,
    encounter_weight=0.25,
    elite=True,
)

JADE_SHELL_TOAD = Monster(
    name="Jade Shell Toad",
    realm="Rank 1 Beast (Elite)",
    monster_type="Beast",
    habitat="Marshes, Slow Rivers",
    description="A heavy, jade-shelled toad whose poisonous breath seems to knit its own wounds shut mid-fight.",
    # Elite Regenerator — tanky, moderate damage, self-heals a fraction of damage dealt via
    # MonsterAbility.lifesteal_percent (see hunt.py's _monster_turn for how that's applied).
    hp=100, atk_stat=6, str_stat=15, def_stat=9, spd_stat=5, luck_stat=0, qi_stat=24,
    ability=MonsterAbility(
        name="Jade Breath", description="A corrosive poison breath that seems to feed something back to the toad.",
        str_multiplier=1.25, lifesteal_percent=0.30,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 1 Beast Core"),
        DropEntry(chance=0.80, item_name="Tier 1 Beast Material"),
        DropEntry(chance=0.45, item_name="Tier 1 Beast Material"),
        DropEntry(chance=0.10, item_name="Iron Skin Gu (Common)"),
        DropEntry(chance=0.05, item_name="Primeval Essence Crystal", quantity=3),
    ],
    gu_rank=1,
    encounter_weight=0.25,
    elite=True,
)

HUNDRED_YEAR_SPIRIT_GINSENG = Monster(
    name="Hundred-Year Spirit Ginseng",
    realm="Rank 1 Beast (Rare)",
    monster_type="Spirit Plant",
    habitat="Hidden Groves",
    description=(
        "A century-old ginseng root that has cultivated just enough spirit to move — barely "
        "any fight in it, but almost impossible to actually land a hit on."
    ),
    # Rare/apex encounter, but the "apex" here is evasiveness, not power — very low HP/
    # offense, very high SPD/LCK (dodge and crit both key off SPD/LCK — see combat.py), so a
    # fight against it is short and about whether you can land hits at all, not who out-
    # damages whom. Targets the low end of the "rare apex" band (section 6.4: ~25-45% solo)
    # through sheer evasiveness rather than raw danger.
    hp=30, atk_stat=2, str_stat=4, def_stat=2, spd_stat=16, luck_stat=5, qi_stat=14,
    ability=MonsterAbility(
        name="Root Lash", description="A weak, panicked lash of root tendrils.", str_multiplier=0.6,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 1 Beast Core"),
        DropEntry(chance=0.60, item_name="Tier 1 Beast Material"),
        DropEntry(chance=0.50, item_name="Primeval Essence Crystal", quantity=8),
    ],
    gu_rank=1,
    encounter_weight=0.08,
    elite=False,
)

VERDANT_BORDERLANDS_MONSTERS = [
    BAMBOO_SHADOW_SNAKE, MOON_EARED_RABBIT, RED_CREST_CRANE, GRAVE_MOSS_CORPSE_BEETLE,
    BLOOD_FANG_WOLF, JADE_SHELL_TOAD, HUNDRED_YEAR_SPIRIT_GINSENG,
]

# -- Verdant Borderlands raid: Blood Fang Wolf Alpha (replaces realm 0's generic
# _generate_raid_group placeholder, the same way VERDANT_BORDERLANDS_MONSTERS replaced the
# hunt placeholder) --------------------------------------------------------------------------
# The pack the solo Blood Fang Wolf elite hunt monster above belongs to — same identity
# thread as the brief's own section 32 worked example (Blood Fang Hunter's Inheritance ->
# Blood Fang Wolf hunt -> this raid -> a future Packlord Fang Necklace accessory). Tuned
# against a party of 3 fresh (zero-breakthrough) Qi Condensation characters WITH their
# auto-granted starter gear, no Guard/potions/Gu passives modeled (same pessimistic
# baseline BOAR_KING's own tuning comment uses): ~0% solo win rate, ~71% for a party of 3,
# averaging ~2.3/3 survivors on a win (Boar King itself scores ~70% in the same simulator
# methodology, so the two raids land at comparable relative difficulty).
BLOOD_FANG_WOLF_ALPHA = Monster(
    name="Blood Fang Wolf Alpha",
    realm="Rank 1 Beast (Raid)",
    monster_type="Beast",
    habitat="Deep Bamboo Forests",
    description="The scarred, blood-maned leader of the Blood Fang pack — every lesser wolf in the borderlands answers to it.",
    hp=180, atk_stat=11, str_stat=25, def_stat=8, spd_stat=12, luck_stat=1, qi_stat=35,
    ability=MonsterAbility(
        name="Alpha's Rending Bite", description="A ferocious, pack-leading bite.", str_multiplier=1.33,
    ),
    drops=[
        # Raid boss chances/quantities scaled back to original after a brief experiment with
        # a much bigger bump (that generosity moved over to World Boss instead — see
        # world_boss.py). Herbs stay, mirroring Beast Material's own chance/quantity exactly
        # per the still-standing "herbs equal to beast materials" request.
        DropEntry(chance=1.00, item_name="Tier 1 Beast Material"),
        DropEntry(chance=1.00, item_name="Tier 1 Herb"),
        DropEntry(chance=0.70, item_name="Tier 1 Beast Core", quantity=2),
        DropEntry(chance=0.70, item_name="Tier 1 Beast Material", quantity=2),
        DropEntry(chance=0.70, item_name="Tier 1 Herb", quantity=2),
        DropEntry(chance=0.60, item_name="Tier 2 Beast Material"),
        DropEntry(chance=0.60, item_name="Tier 2 Herb"),
        DropEntry(chance=0.25, item_name="Tier 3 Beast Material"),
        DropEntry(chance=0.25, item_name="Tier 3 Herb"),
        DropEntry(chance=0.35, pool=TIER_1_GU_COMMON_POOL),
        # A notably better shot at the pack's own signature Gu than the solo elite hunt
        # offers, still Common quality, matching every other hunt/raid-dropped Gu in the
        # game (fusion via /gu is the only way up from there).
        DropEntry(chance=0.20, item_name="Blood Fang Gu (Common)"),
    ],
    gu_rank=1,
)
# Mini-bosses flanking the Alpha — identical stats, distinct names/flavor, same pattern as
# BOAR_GUARD/BOAR_SKIRMISHER. They don't carry their own drop table; the raid's loot
# (BLOOD_FANG_WOLF_ALPHA.drops) only rolls once every enemy in the group is defeated.
_BLOOD_FANG_PACKMATE_STATS = dict(hp=58, atk_stat=8, str_stat=17, def_stat=5, spd_stat=11, luck_stat=0, qi_stat=20)
BLOOD_FANG_STALKER = Monster(
    name="Blood Fang Stalker",
    realm="Rank 1 Beast (Raid)",
    monster_type="Beast",
    habitat="Deep Bamboo Forests",
    description="One of the Alpha's pack, circling wide to flank whoever the leader is fighting.",
    ability=MonsterAbility(name="Flanking Bite", description="A quick bite from the side.", str_multiplier=1.15),
    drops=[], gu_rank=1,
    **_BLOOD_FANG_PACKMATE_STATS,
)
BLOOD_FANG_AMBUSHER = Monster(
    name="Blood Fang Ambusher",
    realm="Rank 1 Beast (Raid)",
    monster_type="Beast",
    habitat="Deep Bamboo Forests",
    description="One of the Alpha's pack, lunging in from concealment the moment blood is drawn.",
    ability=MonsterAbility(name="Sudden Lunge", description="A sudden lunge out of hiding.", str_multiplier=1.15),
    drops=[], gu_rank=1,
    **_BLOOD_FANG_PACKMATE_STATS,
)

VERDANT_BORDERLANDS_RAID_GROUP = [BLOOD_FANG_WOLF_ALPHA, BLOOD_FANG_STALKER, BLOOD_FANG_AMBUSHER]
