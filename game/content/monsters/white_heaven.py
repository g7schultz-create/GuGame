"""
White Heaven's own hunt/raid roster (see game/white_heaven.py, /white_heaven,
GameManager.check_and_complete_white_heaven_travel). Fixed-difficulty, realm-INDEPENDENT
content -- mirrors content/monsters/blood_sea_ancestor.py's own shape (own Monster()
constants, own archetype baseline, NOT registered into monsters.HUNT_MONSTERS_BY_REALM/
RAID_GROUPS_BY_REALM, which are reserved for the per-player-realm ladder) rather than
content/monsters/dao_seeking.py's realm-indexed shape, since White Heaven is reachable by
anyone Dao Seeking realm and above (both Dao Seeking and Ancient Realm, the current top
realm) rather than tied to one specific realm_index.

Every hunt mob gets a real MonsterAbility.lifesteal_percent (the explicit "heals off damage
dealt, similar to the player" ask) -- this mechanic already exists end-to-end (hunt.py's
_monster_turn, team_battle.py's _resolve_enemy_hit both already apply it via
combat.resolve_attack's own heal return, see monsters.py's own MonsterAbility docstring and
blood_sea_ancestor.py's BLOOD_MOSQUITO_SWARM/BLOOD_POOL_LEECH precedent), no new plumbing.

-- Calibration (first-pass, same honest gap blood_sea_ancestor.py shipped with) --
Anchored off a real (if stale, per this codebase's own live-DB caveats) local snapshot of
the strongest known player (Spirit Severing Late, realm_index 18: 95,948 STR / 47,009 ATK /
58,130 DEF, ~579k HP per the historical REALM_SCALING_BOOST comment in monsters.py),
projected forward via realms.STEP_MULTIPLIERS' own compounding (index 18 -> 23, Dao Seeking
Peak: ~8.75x) to a "typical eligible White Heaven visitor" raw-stat ceiling of roughly
STR 839k / ATK 411k / DEF 508k / HP 5.06M -- deliberately a PURE-REALM-STAT projection with
no gear/pill/manual stacking modeled (same conservative baseline prior regions used), which
real players will exceed. Hunt-mob baseline below sits at roughly 65% of that projection
(hard, not a wall, for a genuinely equipped Dao Seeking cultivator; a curb-stomp for a
geared Ancient Realm one, which is the intended "reachable early, stays worth farming at the
top" shape). Raid boss sits well above even the Ancient-Realm-Peak projection (~66.5x the
same anchor) specifically so it survives a full team's combined output over several rounds
rather than one player's. Expect a retune pass once real White Heaven kills happen.
"""

from ...monsters import DropEntry, Monster, MonsterAbility

_HUNT_BASELINE = dict(hp=3_500_000, atk_stat=270_000, str_stat=550_000, def_stat=330_000, spd_stat=230_000, qi_stat=200_000)

# (hp, str, def, spd, atk) -- same 5-archetype framework blood_sea_ancestor.py/
# dao_seeking.py already established.
_ARCHETYPE_MULTIPLIER = {
    "Guardian": (1.20, 0.80, 1.35, 0.75, 0.90),
    "Skirmisher": (0.80, 0.95, 0.75, 1.35, 1.15),
    "Assassin": (0.70, 1.15, 0.70, 1.40, 1.30),
    "Brute": (1.10, 1.25, 0.95, 0.85, 1.10),
    "Mystic": (0.85, 1.00, 0.85, 1.10, 1.20),
}


def _stats(archetype: str) -> dict:
    hp_mult, str_mult, def_mult, spd_mult, atk_mult = _ARCHETYPE_MULTIPLIER[archetype]
    return dict(
        hp=round(_HUNT_BASELINE["hp"] * hp_mult),
        str_stat=round(_HUNT_BASELINE["str_stat"] * str_mult),
        def_stat=round(_HUNT_BASELINE["def_stat"] * def_mult),
        spd_stat=round(_HUNT_BASELINE["spd_stat"] * spd_mult),
        atk_stat=round(_HUNT_BASELINE["atk_stat"] * atk_mult),
        luck_stat=1,
        qi_stat=_HUNT_BASELINE["qi_stat"],
    )


# Generic Tier 8 materials only for now (see game/content/materials_white_heaven.py, added
# in a later phase, for the flavor-named White Heaven Floating Dust/Aurora-shard drops layered
# on top of these).
_HUNT_DROPS = [
    DropEntry(chance=1.00, item_name="Tier 8 Beast Core"),
    DropEntry(chance=0.70, item_name="Tier 8 Beast Material"),
    DropEntry(chance=0.30, item_name="Tier 8 Ore"),
]

BLINKING_BIRDS = Monster(
    name="Blinking Birds",
    realm="White Heaven",
    monster_type="Beast",
    habitat="The Cloud Seas",
    description="A flock that doesn't so much fly as blink from cloud to cloud, each landing already mid-strike before the eye catches up.",
    ability=MonsterAbility(name="Blink Strike", description="Vanishes and reappears mid-swing, then feeds on the wound it just opened.", str_multiplier=1.15, lifesteal_percent=0.15),
    drops=_HUNT_DROPS,
    gu_rank=8,
    encounter_weight=1.0,
    **_stats("Skirmisher"),
)

REMNANT_HEAVENLY_DOGS = Monster(
    name="Remnant Heavenly Dogs",
    realm="White Heaven",
    monster_type="Beast",
    habitat="The Aurora Resource Zones",
    description="What's left of a celestial hound pack, still hunting long after whatever bound them here stopped caring whether they ever stopped.",
    ability=MonsterAbility(name="Undying Fang", description="A relentless bite that keeps the pack going no matter how much it's already lost.", str_multiplier=1.05, lifesteal_percent=0.30),
    drops=_HUNT_DROPS,
    gu_rank=8,
    encounter_weight=1.0,
    **_stats("Guardian"),
)

CLOUD_BEASTS = Monster(
    name="Cloud Beasts",
    realm="White Heaven",
    monster_type="Beast",
    habitat="The Floating Continents",
    description="Enormous, slow-drifting creatures that seem woven from the floating continents themselves, absorbing blows like they were never really solid to begin with.",
    ability=MonsterAbility(name="Cloudbody Absorption", description="A dense, half-solid body that shrugs off and slowly regrows from damage.", str_multiplier=1.10, lifesteal_percent=0.20),
    drops=_HUNT_DROPS,
    gu_rank=8,
    encounter_weight=1.0,
    **_stats("Mystic"),
)

WHITE_HEAVEN_HUNT_MONSTERS = [BLINKING_BIRDS, REMNANT_HEAVENLY_DOGS, CLOUD_BEASTS]

# -- Raid: a hidden grotto-heaven's bound ancient Gu Immortal remnant, guarded by 2 lesser
# spirits -- [main, mini, mini] shape every other region's raid groups already use. Tuned
# well past even the Ancient-Realm-Peak solo projection above so solo (including
# /solo_raid) is impractical without a real team's combined output over several rounds --
# no hard minimum-participant gate (confirmed: pure stat tuning, not a new mechanic).
_RAID_DROPS_MAIN = [
    DropEntry(chance=1.00, item_name="Tier 8 Beast Core", quantity=3),
    DropEntry(chance=1.00, item_name="Tier 8 Beast Material", quantity=2),
    DropEntry(chance=1.00, item_name="Tier 8 Ore", quantity=2),
    DropEntry(chance=0.50, item_name="Primeval Essence Crystal", quantity=30),
]
_RAID_DROPS_ADD = [
    DropEntry(chance=1.00, item_name="Tier 8 Beast Core"),
    DropEntry(chance=0.60, item_name="Tier 8 Beast Material"),
]

GROTTO_HEAVENS_BOUND_IMMORTAL = Monster(
    name="Grotto-Heaven's Bound Immortal",
    realm="White Heaven",
    monster_type="Spirit",
    habitat="The Hidden Grotto-Heavens",
    description="An ancient Gu Immortal, sealed inside their own grotto-heaven since long before anyone alive was born -- whatever finally trapped them clearly isn't the same thing that's kept them dangerous.",
    ability=MonsterAbility(name="Sealed Immortal's Wrath", description="Centuries of sealed fury released all at once.", str_multiplier=1.20),
    drops=_RAID_DROPS_MAIN,
    # Tuned via a scratchpad simulation (combat.resolve_attack, pure raw-stat "Peak Dao
    # Seeking" synthetic players, no gear/pill modeling). This power band has a steep,
    # narrow win-rate threshold once HP pools/round counts get this large (attrition over
    # ~30 rounds means a small per-player DPS edge compounds fast) -- 4 iterations landed
    # here at ~0% solo / ~34% for 3 players / ~97% for 4, which doesn't hit "50-70% at BOTH
    # 3 and 4" but DOES hit the actual intent: solo is impossible, a partial team genuinely
    # struggles, and a full team is rewarded for bringing everyone. Expect a further retune
    # once real White Heaven teams have actually fought this.
    hp=30_500_000, atk_stat=560_000, str_stat=1_120_000, def_stat=730_000, spd_stat=275_000, luck_stat=1, qi_stat=430_000,
    gu_rank=8,
    elite=True,
)

GROTTO_GUARDIAN_SPIRIT = Monster(
    name="Grotto Guardian Spirit",
    realm="White Heaven",
    monster_type="Spirit",
    habitat="The Hidden Grotto-Heavens",
    description="A lesser spirit bound to the grotto-heaven's outer wards, real enough to fight but nowhere near what it's guarding.",
    ability=MonsterAbility(name="Ward-Bound Strike", description="A guarding spirit's own defensive strike.", str_multiplier=1.05),
    drops=_RAID_DROPS_ADD,
    hp=3_500_000, atk_stat=150_000, str_stat=240_000, def_stat=162_000, spd_stat=125_000, luck_stat=1, qi_stat=95_000,
    gu_rank=8,
)

WHITE_HEAVEN_RAID_GROUP = [GROTTO_HEAVENS_BOUND_IMMORTAL, GROTTO_GUARDIAN_SPIRIT, GROTTO_GUARDIAN_SPIRIT]
