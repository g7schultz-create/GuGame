"""
Monsters for /hunt (MONSTERS) and /raid (BOSSES) — a small, easily-extended catalog.

Drop table semantics: each DropEntry is rolled independently against its own
`chance` (so multiple can drop, or none at all, in a single kill — matches a
"100%/75%/40%/5%/5%/1%" style table where the entries clearly aren't meant to
be mutually exclusive). A `pool` entry (instead of a fixed `item_name`) picks
one name from the list at random when it hits, for a drop line that's really
a category (e.g. "Tier 1 Gu" resolving to one of the four tiered Gu families
at Common quality — see equipment.GU_FAMILIES).
"""

import random
from dataclasses import dataclass, field
from typing import List, Optional

from . import canon_gu, realms
from .equipment import GU_FAMILIES, gu_item_name


@dataclass
class MonsterAbility:
    name: str
    description: str
    str_multiplier: float  # damage dealt on a hit = monster STR * this
    # Regenerator-archetype self-heal (see the content brief's section 6.2) — fraction of
    # damage dealt healed back to the monster on a landed hit, same mechanic
    # combat.resolve_attack already gives the player via lifesteal_percent, just applied to
    # the monster's own HP by whichever view resolves its turn (see hunt.py's _monster_turn).
    lifesteal_percent: float = 0.0


@dataclass
class DropEntry:
    chance: float
    item_name: Optional[str] = None
    quantity: int = 1
    pool: Optional[List[str]] = None

    def roll_names(self, chance_multiplier: float = 1.0) -> List[str]:
        if random.random() >= self.chance * chance_multiplier:
            return []
        if self.pool:
            return [random.choice(self.pool)]
        return [self.item_name]


@dataclass
class Monster:
    name: str
    realm: str
    monster_type: str
    habitat: str
    description: str
    hp: int
    atk_stat: int
    str_stat: int
    def_stat: int
    spd_stat: int
    luck_stat: int
    qi_stat: int
    ability: MonsterAbility
    drops: List[DropEntry] = field(default_factory=list)
    # Which canon_gu.CANON_GU "gu_rank" tier this monster's canon Gu drops roll against
    # (see canon_gu.roll_canon_gu_drop) — independent of the beast-material tier above.
    gu_rank: int = 1
    # Relative pick weight within hunt_monster_name_for_realm's per-realm pool, when more
    # than one monster shares a realm (see HUNT_MONSTERS_BY_REALM) — irrelevant to a
    # single-monster pool, which is why every pre-existing monster defaults to 1.0 without
    # changing its own encounter behavior.
    encounter_weight: float = 1.0
    # Cosmetic/organizational tag only (content brief section 5.2) — doesn't itself change
    # combat; a monster's actual difficulty comes entirely from its rolled stats/ability.
    elite: bool = False

    def stats(self) -> dict:
        return {
            "atk_stat": self.atk_stat, "str_stat": self.str_stat, "def_stat": self.def_stat,
            "spd_stat": self.spd_stat, "luck_stat": self.luck_stat, "qi_stat": self.qi_stat,
        }


# All four given Gu families are drop_rank 1 (see equipment.GU_FAMILIES) — a dropped Gu
# always starts at Common quality (per-family upgrading is handled by GameManager.upgrade_gu).
TIER_1_GU_COMMON_POOL = [
    gu_item_name(family, "Common") for family, data in GU_FAMILIES.items() if data["drop_rank"] == 1
]

# Name isn't specified in the source material beyond "a wild boar with metallic
# gray fur" — "Ironhide Boar" is my own pick to fit the Iron Charge ability and fur color.
IRONHIDE_BOAR = Monster(
    name="Ironhide Boar",
    realm="Rank 1 Beast",
    monster_type="Beast",
    habitat="Bamboo Forests, Mountain Valleys",
    description="A wild boar with metallic gray fur.",
    # Tuned down from the original (hp=120, atk=7, str=28, def=18, spd=12) — that block
    # reliably beat even a character with several breakthroughs. Simulated ~4000 fresh
    # (zero-breakthrough) characters against this version: ~90% win rate, averaging ~53%
    # HP lost on a win.
    hp=65,
    atk_stat=6,
    str_stat=15,
    def_stat=7,
    spd_stat=7,
    luck_stat=0,
    qi_stat=20,
    ability=MonsterAbility(
        name="Iron Charge",
        description="Deals 140% STR damage if it hits.",
        str_multiplier=1.4,
    ),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 1 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 1 Beast Material"),
        DropEntry(chance=0.40, item_name="Tier 2 Beast Material"),
        DropEntry(chance=0.05, pool=TIER_1_GU_COMMON_POOL),
        DropEntry(chance=0.05, item_name="Primeval Essence Crystal", quantity=5),
        DropEntry(chance=0.01, item_name="Tier 3 Beast Material"),
    ],
    gu_rank=1,
)

# A group boss, joinable by multiple players via /raid, now flanked by two mini-bosses —
# every enemy acts every round (see raid.py's round-based resolution), so total incoming
# pressure comes from all three at once rather than one attacker at a time, but drops off
# fast as adds die since a dead enemy no longer retaliates. Tuned by simulating a party of
# fresh (zero-breakthrough) mortal-realm cultivators WITH their auto-granted starter gear
# (worth roughly +3 STR/+3 DEF/+3 SPD/+10 HP/+2 LCK combined — easy to undercount and get
# a raid that's too easy) who focus-fire whichever enemy is lowest on HP each round, with
# no Guard/potions/Gu passives modeled (a deliberately pessimistic baseline — real play
# with those tools should do better): ~0% solo win rate vs. ~56% win rate for a party of
# 3, averaging ~1.3/3 survivors on a win. See scratchpad/balance_raid2.py for the sweep.
BOAR_KING = Monster(
    name="Boar King",
    realm="Rank 2 Beast",
    monster_type="Beast",
    habitat="Deep Mountain Dens",
    description="A colossal, scarred tusker that rules the mountain boar packs — its hide is thick enough to turn aside a spear.",
    hp=300,
    atk_stat=9,
    str_stat=18,
    def_stat=9,
    spd_stat=7,
    luck_stat=2,
    qi_stat=40,
    ability=MonsterAbility(
        name="Tyrant Charge",
        description="Deals 130% STR damage if it hits.",
        str_multiplier=1.3,
    ),
    drops=[
        # Raid boss chances/quantities scaled back to original after a brief experiment with
        # a much bigger bump (that generosity moved over to World Boss instead — see
        # world_boss.py). Herbs stay, mirroring Beast Material's own chance/quantity exactly
        # per the still-standing "herbs equal to beast materials" request.
        DropEntry(chance=1.00, item_name="Tier 2 Beast Material"),
        DropEntry(chance=1.00, item_name="Tier 2 Herb"),
        DropEntry(chance=0.70, item_name="Tier 2 Beast Core", quantity=2),
        DropEntry(chance=0.60, item_name="Tier 3 Beast Material"),
        DropEntry(chance=0.60, item_name="Tier 3 Herb"),
        DropEntry(chance=0.25, item_name="Tier 4 Beast Material"),
        DropEntry(chance=0.25, item_name="Tier 4 Herb"),
        DropEntry(chance=0.35, pool=TIER_1_GU_COMMON_POOL),
        # Rare-chance Tier 2 Gu families don't exist yet — reserved for future content,
        # deliberately no DropEntry here until at least one drop_rank-2 family is added.
    ],
    gu_rank=2,
)

# Mini-bosses flanking Boar King — identical stats, distinct names/flavor for variety.
# They don't carry their own drop table; the raid's loot (BOAR_KING.drops) is only
# rolled once total victory is achieved (every enemy in the group defeated).
BOAR_GUARD = Monster(
    name="Boar Guard",
    realm="Rank 1 Beast",
    monster_type="Beast",
    habitat="Deep Mountain Dens",
    description="One of the Boar King's tusked enforcers, bristling at its ruler's flank.",
    hp=85,
    atk_stat=8,
    str_stat=13,
    def_stat=7,
    spd_stat=7,
    luck_stat=0,
    qi_stat=15,
    ability=MonsterAbility(name="Tusk Jab", description="Deals 120% STR damage if it hits.", str_multiplier=1.2),
    drops=[],
    gu_rank=2,
)
BOAR_SKIRMISHER = Monster(
    name="Boar Skirmisher",
    realm="Rank 1 Beast",
    monster_type="Beast",
    habitat="Deep Mountain Dens",
    description="A lean, quick boar that harries prey the King has already run down.",
    hp=85,
    atk_stat=8,
    str_stat=13,
    def_stat=7,
    spd_stat=7,
    luck_stat=0,
    qi_stat=15,
    ability=MonsterAbility(name="Flank Bite", description="Deals 120% STR damage if it hits.", str_multiplier=1.2),
    drops=[],
    gu_rank=2,
)

# -- Per-realm /hunt and /raid selection ----------------------------------------------
#
# /hunt and /raid can now target any of the 7 Great Realms, not just Qi Condensation
# (Ironhide Boar) and Foundation Establishment (Boar King) — those two stay exactly as
# they were (already named and balance-tested), and every other realm gets a generated,
# genuinely-generic-for-now placeholder ("a real drop database is coming later" per the
# request), scaled off them using the SAME 5x-per-Great-Realm multiplier the rest of the
# game already uses for player power (realms.GREAT_REALM_STAT_MULTIPLIER) — since both
# sides of a same-realm fight scale by the identical factor, the relative difficulty a
# fresh character sees at their own realm stays close to Ironhide Boar/Boar King's already
# -validated ~90%/~56% win rates, without needing to re-tune every realm by hand. LCK is
# left unscaled, same as breakthroughs already do for players ("fortune, not power").

HUNT_ANCHOR_REALM_INDEX = 0  # Ironhide Boar
RAID_ANCHOR_REALM_INDEX = 1  # Boar King — one Great Realm up, same as it's always been

# Spirit Severing (great_realm_index 4) and Dao Seeking (5) get one extra Great-Realm step of
# scaling on top of the base curve below. Checked against real live-DB player power (2026-08-06):
# the strongest confirmed players were all sitting at Nascent Soul Peak, with EFFECTIVE combat
# stats (base + gear/manual/Dao Path/Killer Move/companion bonuses) already at ~10-30k STR and
# ~95-150k HP -- their own PROJECTED base stats alone after breaking through into Spirit Severing
# Early (x5 crossing a Great Realm) land around 40-95k STR / 270-470k HP, dwarfing the un-boosted
# formula's Spirit Severing output (~2-9k STR / 10-40k HP for raid/hunt respectively). The base
# curve was calibrated before Dao Paths, Killer Move, Dao Companion, the Nascent Soul Avatar, and
# the accessories/artifacts overhaul existed -- all of which stack additional effective power on
# top of pure realm breakthroughs, and compound more the further a player has progressed by the
# time they reach these two realms. A flat +1 exponent step (another full 5x) brings both realms
# back in line with that real growth without needing a bespoke one-off formula.
#
# Ancient Realm (great_realm_index 6, the top of the current ladder) gets a bigger +2 step
# (25x on top of the base curve) per explicit request to buff it a lot -- checked live-DB
# player power first (2026-08-06): the strongest confirmed player is still 2 full Great Realms
# below (Spirit Severing, ~96k STR/579k HP), so nobody is anywhere near encountering this yet;
# safe to tune aggressively now rather than needing a live-power check like 4/5 got.
REALM_SCALING_BOOST = {4: 1, 5: 1, 6: 2}


def _scale_stat(base: int, factor: float) -> int:
    return max(1, round(base * factor))


def _generate_hunt_monster(realm_index: int) -> Monster:
    realm_name = realms.GREAT_REALMS[realm_index]["name"]
    factor = realms.GREAT_REALM_STAT_MULTIPLIER ** (realm_index - HUNT_ANCHOR_REALM_INDEX + REALM_SCALING_BOOST.get(realm_index, 0))
    tier = realm_index + 1  # 7 realms, 7 beast material/core tiers — a clean 1:1 mapping
    return Monster(
        name=f"{realm_name} Beast",
        realm=f"Rank {tier} Beast",
        monster_type="Beast",
        habitat=f"Wherever {realm_name} cultivators roam",
        description=(
            f"A wild beast whose cultivation matches the {realm_name} realm. "
            "A generic placeholder — a proper name and drop table are coming later."
        ),
        hp=_scale_stat(IRONHIDE_BOAR.hp, factor),
        atk_stat=_scale_stat(IRONHIDE_BOAR.atk_stat, factor),
        str_stat=_scale_stat(IRONHIDE_BOAR.str_stat, factor),
        def_stat=_scale_stat(IRONHIDE_BOAR.def_stat, factor),
        spd_stat=_scale_stat(IRONHIDE_BOAR.spd_stat, factor),
        luck_stat=0,
        qi_stat=_scale_stat(IRONHIDE_BOAR.qi_stat, factor),
        ability=MonsterAbility(
            name="Realm Strike",
            description=f"Deals {IRONHIDE_BOAR.ability.str_multiplier * 100:.0f}% STR damage if it hits.",
            str_multiplier=IRONHIDE_BOAR.ability.str_multiplier,
        ),
        drops=[
            DropEntry(chance=1.00, item_name=f"Tier {tier} Beast Core"),
            DropEntry(chance=0.75, item_name=f"Tier {tier} Beast Material"),
        ],
        gu_rank=tier,
    )


def _generate_raid_group(realm_index: int) -> List[Monster]:
    realm_name = realms.GREAT_REALMS[realm_index]["name"]
    factor = realms.GREAT_REALM_STAT_MULTIPLIER ** (realm_index - RAID_ANCHOR_REALM_INDEX + REALM_SCALING_BOOST.get(realm_index, 0))
    tier = realm_index + 1

    def scaled(source: Monster) -> dict:
        return {
            "hp": _scale_stat(source.hp, factor), "atk_stat": _scale_stat(source.atk_stat, factor),
            "str_stat": _scale_stat(source.str_stat, factor), "def_stat": _scale_stat(source.def_stat, factor),
            "spd_stat": _scale_stat(source.spd_stat, factor), "qi_stat": _scale_stat(source.qi_stat, factor),
        }

    main = Monster(
        name=f"{realm_name} Overlord", realm=f"Rank {tier} Beast", monster_type="Beast",
        habitat=f"Wherever {realm_name} cultivators roam",
        description=(
            f"A dominant beast of the {realm_name} realm, flanked by two lesser kin. "
            "A generic placeholder — a proper name and drop table are coming later."
        ),
        luck_stat=2,
        ability=MonsterAbility(
            name="Overlord's Wrath",
            description=f"Deals {BOAR_KING.ability.str_multiplier * 100:.0f}% STR damage if it hits.",
            str_multiplier=BOAR_KING.ability.str_multiplier,
        ),
        drops=[
            # Raid boss chances/quantities scaled back to original after a brief experiment
            # with a much bigger bump (that generosity moved over to World Boss instead — see
            # world_boss.py). Herbs stay, mirroring Beast Material's own chance/quantity
            # exactly per the still-standing "herbs equal to beast materials" request.
            DropEntry(chance=1.00, item_name=f"Tier {tier} Beast Material"),
            DropEntry(chance=1.00, item_name=f"Tier {tier} Herb"),
            DropEntry(chance=0.70, item_name=f"Tier {tier} Beast Core", quantity=2),
            DropEntry(chance=0.60, item_name=f"Tier {min(7, tier + 1)} Beast Material"),
            DropEntry(chance=0.60, item_name=f"Tier {min(7, tier + 1)} Herb"),
            DropEntry(chance=0.25, item_name=f"Tier {min(7, tier + 2)} Beast Material"),
            DropEntry(chance=0.25, item_name=f"Tier {min(7, tier + 2)} Herb"),
            # Nascent Soul Avatar leveling materials (see game/avatar.py's
            # AVATAR_LEVEL_UP_RECIPE and duskwraith_barrens.py's own matching addition) --
            # every realm this generator covers (4-6: Spirit Severing, Dao Seeking, Ancient
            # Realm) is already Nascent Soul (realm 3) or later, so the avatar system is
            # always unlocked here. Quantity history: 10 (initial big bump) -> 2 (turned down
            # 75%, felt like too little) -> 5 (buffed back up), a middle ground between the
            # two per explicit follow-up requests.
            DropEntry(chance=0.75, item_name="Soul Nourishing Pill", quantity=5),
            DropEntry(chance=0.60, item_name="Soul Crystal", quantity=5),
        ],
        gu_rank=tier,
        **scaled(BOAR_KING),
    )
    mini_kwargs = scaled(BOAR_GUARD)
    guard = Monster(
        name=f"{realm_name} Guard", realm=f"Rank {tier} Beast", monster_type="Beast",
        habitat=f"Wherever {realm_name} cultivators roam", description="One of the Overlord's enforcers.",
        luck_stat=0, ability=MonsterAbility(name="Guard Strike", description="Deals 120% STR damage if it hits.", str_multiplier=1.2),
        drops=[], gu_rank=tier, **mini_kwargs,
    )
    skirmisher = Monster(
        name=f"{realm_name} Skirmisher", realm=f"Rank {tier} Beast", monster_type="Beast",
        habitat=f"Wherever {realm_name} cultivators roam", description="A lean beast that harries prey the Overlord has run down.",
        luck_stat=0, ability=MonsterAbility(name="Flank Strike", description="Deals 120% STR damage if it hits.", str_multiplier=1.2),
        drops=[], gu_rank=tier, **mini_kwargs,
    )
    return [main, guard, skirmisher]


# Content-package monsters (see game/content/monsters/verdant_borderlands.py) — imported
# here, after every base dataclass/instance/generator above is already defined, rather than
# at module top: verdant_borderlands.py itself does `from ...monsters import Monster,
# MonsterAbility, DropEntry, TIER_1_GU_COMMON_POOL`, and by the time THIS line runs, this
# module (game.monsters) is already registered in sys.modules with all of those names bound
# as attributes — so that import resolves cleanly with no real circularity, same trick
# items.py uses for game/content/materials.py.
from .content.monsters.verdant_borderlands import VERDANT_BORDERLANDS_MONSTERS, VERDANT_BORDERLANDS_RAID_GROUP
from .content.monsters.hundred_beast_mountains import HUNDRED_BEAST_MOUNTAINS_MONSTERS, HUNDRED_BEAST_MOUNTAINS_RAID_GROUP
from .content.monsters.crimson_furnace_province import (
    CRIMSON_FURNACE_LION_KING_RAID_GROUP,
    CRIMSON_FURNACE_PROVINCE_MONSTERS,
    STAR_IRON_DEVOURER_RAID_GROUP,
)
from .content.monsters.duskwraith_barrens import (
    DUSKWRAITH_BARRENS_MONSTERS,
    DUSKWRAITH_REAVER_WARLORD_RAID_GROUP,
    HOLLOW_MARROW_COLOSSUS_RAID_GROUP,
)
from .content.monsters.dao_seeking import (
    DAO_SEEKING_MONSTERS,
    HEAVEN_DEFYING_DAO_TYRANT_RAID_GROUP,
    WORLD_SUNDERING_INTENT_COLOSSUS_RAID_GROUP,
)

# HUNT_MONSTERS_BY_REALM: realm_index -> [Monster, ...], the pool hunt_monster_name_for_realm
# picks from. Every realm except 0, 1, 2, 3, and 5 still has exactly one generic generated
# monster, so its own encounter behavior is completely unchanged; realm 0 has a real pool
# (Ironhide Boar, unchanged, plus the Verdant Borderlands catalog), realm 1 has Hundred Beast
# Mountains, realm 2 has Crimson Furnace Province, realm 3 has Duskwraith Barrens, and realm 5
# now has Ten Thousand Dao Wilderness — like realms 1, 2, and 3, there was no pre-existing
# hand-authored realm-5 hunt monster to keep as an anchor, so all 8 are new.
HUNT_MONSTERS_BY_REALM = {
    HUNT_ANCHOR_REALM_INDEX: [IRONHIDE_BOAR, *VERDANT_BORDERLANDS_MONSTERS],
    1: HUNDRED_BEAST_MOUNTAINS_MONSTERS,
    2: CRIMSON_FURNACE_PROVINCE_MONSTERS,
    3: DUSKWRAITH_BARRENS_MONSTERS,
    5: DAO_SEEKING_MONSTERS,
}
for _realm_index in range(len(realms.GREAT_REALMS)):
    if _realm_index not in HUNT_MONSTERS_BY_REALM:
        HUNT_MONSTERS_BY_REALM[_realm_index] = [_generate_hunt_monster(_realm_index)]

# RAID_GROUPS_BY_REALM: realm_index -> [[main_boss, *minis], ...] — a LIST of possible raid
# groups per realm, mirroring HUNT_MONSTERS_BY_REALM's own pool restructure. Realm 0 has just
# Blood Fang Wolf Alpha (replacing its old _generate_raid_group placeholder); realm 1 has
# TWO real groups — Boar King (untouched, still the region's "first" raid) and Thunderhorn
# Herd Tyrant (the brief's own "second" raid); realms 2, 3, and 5 now also have two each —
# Crimson Furnace Lion King/Star-Iron Devourer, Duskwraith Reaver Warlord/Hollow Marrow
# Colossus, and Heaven-Defying Dao Tyrant/World-Sundering Intent Colossus — with no
# pre-existing raid to preserve at any of those realms, so all of those pairs are new
# (replacing the old single-group placeholder outright). Every realm gets a weighted-random
# pick among its own groups (by each group's main boss's encounter_weight); every realm past
# 0-3 and 5 still has exactly one generic generated group, so its own behavior is completely
# unchanged.
RAID_GROUPS_BY_REALM = {
    RAID_ANCHOR_REALM_INDEX: [[BOAR_KING, BOAR_GUARD, BOAR_SKIRMISHER], HUNDRED_BEAST_MOUNTAINS_RAID_GROUP],
    HUNT_ANCHOR_REALM_INDEX: [VERDANT_BORDERLANDS_RAID_GROUP],
    2: [CRIMSON_FURNACE_LION_KING_RAID_GROUP, STAR_IRON_DEVOURER_RAID_GROUP],
    3: [DUSKWRAITH_REAVER_WARLORD_RAID_GROUP, HOLLOW_MARROW_COLOSSUS_RAID_GROUP],
    5: [HEAVEN_DEFYING_DAO_TYRANT_RAID_GROUP, WORLD_SUNDERING_INTENT_COLOSSUS_RAID_GROUP],
}
for _realm_index in range(len(realms.GREAT_REALMS)):
    if _realm_index not in RAID_GROUPS_BY_REALM:
        RAID_GROUPS_BY_REALM[_realm_index] = [_generate_raid_group(_realm_index)]
del _realm_index

MONSTERS = {monster.name: monster for pool in HUNT_MONSTERS_BY_REALM.values() for monster in pool}

BOSSES = {group[0].name: group[0] for groups in RAID_GROUPS_BY_REALM.values() for group in groups}

# Boss name -> [main boss, *minis] — the full enemy roster a /raid spawns. Index 0's
# drop table is what the raid pays out on total victory; the rest are support adds.
BOSS_GROUPS = {group[0].name: group for groups in RAID_GROUPS_BY_REALM.values() for group in groups}


def hunt_monster_name_for_realm(great_realm_index: int) -> str:
    """Weighted-random pick from that realm's pool (see Monster.encounter_weight) — a
    single-monster pool always just returns that monster, so every realm except 0/1 behaves
    exactly as before this pool restructure."""
    pool = HUNT_MONSTERS_BY_REALM[great_realm_index]
    return random.choices(pool, weights=[m.encounter_weight for m in pool])[0].name


def raid_boss_name_for_realm(great_realm_index: int) -> str:
    """Weighted-random pick among that realm's possible raid groups (by each group's main
    boss's own encounter_weight) — a single-group realm always just returns that group's
    boss, so every realm except 1 behaves exactly as before this restructure."""
    groups = RAID_GROUPS_BY_REALM[great_realm_index]
    return random.choices(groups, weights=[group[0].encounter_weight for group in groups])[0][0].name


def roll_loot(monster: Monster, chance_multiplier: float = 1.0, beast_material_quantity_bonus_pct: float = 0.0) -> dict:
    """Rolls the monster's drop table, returns {item_name: quantity}. chance_multiplier
    scales every entry's drop chance (e.g. a raid's AFK reward penalty) — 0 guarantees
    nothing drops, 1 (the default) is the table's normal odds. beast_material_quantity_bonus_pct
    is a Strength-family root's own "beast materials have +X% quantity chance" (see
    character_data.CharacterTraitSpec) — a per-hit chance at +1 extra, only on drops actually
    named "... Beast Material" (not Beast Core, not anything else), rolled independently of
    whether the entry itself hit."""
    loot: dict = {}
    for entry in monster.drops:
        for name in entry.roll_names(chance_multiplier):
            quantity = entry.quantity
            if beast_material_quantity_bonus_pct > 0 and "Beast Material" in name and random.random() < beast_material_quantity_bonus_pct:
                quantity += 1
            loot[name] = loot.get(name, 0) + quantity
    return loot
