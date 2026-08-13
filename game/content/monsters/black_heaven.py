"""
Black Heaven's own battle-bubble monster roster (see game/black_heaven_search_view.py,
GameManager.roll_black_heaven_battle_monster) -- fought whenever a Search Black Heaven bubble
pop reveals "battle" (see manager.py's BLACK_HEAVEN_MIN_BATTLE_BUBBLES). Same 4-rarity-tier,
5-archetype shape content/monsters/blood_sea_ancestor.py already established for Inheritance
Ground's own battle bubbles, and the same real-mechanic-per-monster discipline (reusing
MonsterAbility/Monster's existing execute_damage_pct/bleed_damage_pct/debuff_*/enrage_*/
submerge_*/random_blood_gu fields -- no new plumbing needed, "random_blood_gu" is a generic
re-roll-a-random-mechanic-each-attack field despite its Blood-Sea-flavored name).

Deliberately its own fixed-difficulty roster (gu_rank=8, NOT registered into monsters.py's
realm-keyed HUNT_MONSTERS_BY_REALM/RAID_GROUPS_BY_REALM), reachable ONLY through the bubble
board, same shape content/monsters/white_heaven.py's own hunt/raid roster already uses for a
region-gated, realm-independent pool.

-- Calibration (first-pass, same honest gap every prior region's own roster shipped with) --
Anchored off the SAME live-DB reference point White Heaven's own raid boss used (Spirit
Severing Late, realm_index 18, projected forward via realms.STEP_MULTIPLIERS' own compounding
to a "Peak Dao Seeking" raw-stat ceiling -- see content/monsters/white_heaven.py's own
docstring for the full derivation), verified via a scratchpad Monte Carlo simulation
(combat.resolve_attack, real TeamBattleEngine-shaped round math) rather than guessed or
derived from REALM_SCALING_BOOST. Common tier already reads as "very dangerous" (0% solo win
rate across every tier, by design) while staying winnable for an organized 3-4 person team;
Elite tier stays genuinely risky even for a full 4-person team (~30-40% observed at the first
encounter in a Search run). GameManager.BLACK_HEAVEN_BATTLE_STAT_MULTIPLIER_PER_BATTLE (0.35,
steeper than Inheritance Ground's own 0.20) then does real work as a team keeps popping battle
bubbles within one run -- by the 2nd-3rd consecutive battle even Common tier turns genuinely
lethal for anything less than a full team. Expect a further retune once real Search Black
Heaven runs have actually happened.
"""

from ...monsters import DropEntry, Monster, MonsterAbility

_BASELINE = dict(hp=18_000_000, atk_stat=380_000, str_stat=760_000, def_stat=480_000, spd_stat=220_000, qi_stat=300_000)
_RARITY_MULTIPLIER = {"Common": 1.0, "Uncommon": 1.25, "Rare": 1.55, "Elite": 2.0}
_QI_BY_RARITY = {"Common": 300_000, "Uncommon": 340_000, "Rare": 390_000, "Elite": 450_000}
# (hp, str, def, spd, atk) -- same 5-archetype framework every other region already established.
_ARCHETYPE_MULTIPLIER = {
    "Guardian": (1.20, 0.80, 1.35, 0.75, 0.90),
    "Skirmisher": (0.80, 0.95, 0.75, 1.35, 1.15),
    "Assassin": (0.70, 1.15, 0.70, 1.40, 1.30),
    "Brute": (1.10, 1.25, 0.95, 0.85, 1.10),
    "Mystic": (0.85, 1.00, 0.85, 1.10, 1.20),
}


def _stats(rarity: str, archetype: str) -> dict:
    rarity_mult = _RARITY_MULTIPLIER[rarity]
    hp_mult, str_mult, def_mult, spd_mult, atk_mult = _ARCHETYPE_MULTIPLIER[archetype]
    return dict(
        hp=round(_BASELINE["hp"] * hp_mult * rarity_mult),
        str_stat=round(_BASELINE["str_stat"] * str_mult * rarity_mult),
        def_stat=round(_BASELINE["def_stat"] * def_mult * rarity_mult),
        spd_stat=round(_BASELINE["spd_stat"] * spd_mult * rarity_mult),
        atk_stat=round(_BASELINE["atk_stat"] * atk_mult * rarity_mult),
        luck_stat=1,
        qi_stat=_QI_BY_RARITY[rarity],
    )


# -- Drops (see manager.py's grant_black_heaven_battle_loot for the accessory/artifact/canon-Gu
# side) -- reuses the same generic Tier 8 materials White Heaven's own ceiling-raise already
# introduced (no new named items), escalating chance/quantity by rarity same as every other
# region's own monster roster.
_DROPS_BY_RARITY = {
    "Common": [
        DropEntry(chance=1.00, item_name="Tier 8 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 8 Beast Material"),
    ],
    "Uncommon": [
        DropEntry(chance=1.00, item_name="Tier 8 Beast Core"),
        DropEntry(chance=0.85, item_name="Tier 8 Beast Material"),
        DropEntry(chance=0.30, item_name="Tier 8 Ore"),
    ],
    "Rare": [
        DropEntry(chance=1.00, item_name="Tier 8 Beast Core", quantity=2),
        DropEntry(chance=0.90, item_name="Tier 8 Beast Material"),
        DropEntry(chance=0.45, item_name="Tier 8 Ore"),
        DropEntry(chance=0.25, item_name="Primeval Essence Crystal", quantity=15),
    ],
    "Elite": [
        DropEntry(chance=1.00, item_name="Tier 8 Beast Core", quantity=2),
        DropEntry(chance=1.00, item_name="Tier 8 Beast Material"),
        DropEntry(chance=0.65, item_name="Tier 8 Ore"),
        DropEntry(chance=0.40, item_name="Primeval Essence Crystal", quantity=30),
    ],
}

_MONSTER_LEVEL_MECHANIC_KEYS = {
    "enrage_atk_pct_per_stack", "enrage_stack_cap", "submerge_every_rounds",
    "submerge_duration_rounds", "random_blood_gu",
}


def _monster(name, rarity, archetype, habitat, description, ability_name, ability_description, str_multiplier, **mechanic_kwargs) -> Monster:
    monster_kwargs = {k: v for k, v in mechanic_kwargs.items() if k in _MONSTER_LEVEL_MECHANIC_KEYS}
    ability_kwargs = {k: v for k, v in mechanic_kwargs.items() if k not in _MONSTER_LEVEL_MECHANIC_KEYS}
    return Monster(
        name=name,
        realm="Black Heaven",
        monster_type="Spirit",
        habitat=habitat,
        description=description,
        ability=MonsterAbility(name=ability_name, description=ability_description, str_multiplier=str_multiplier, **ability_kwargs),
        drops=_DROPS_BY_RARITY[rarity],
        gu_rank=8,
        elite=(rarity == "Elite"),
        **_stats(rarity, archetype),
        **monster_kwargs,
    )


# -- Common ------------------------------------------------------------------------------------
VOIDLING_SWARM = _monster(
    "Voidling Swarm", "Common", "Skirmisher",
    "The Starless Reaches", "A cloud of small dark shapes that were never quite solid to begin with, drawn to any warmth that isn't theirs.",
    "Devouring Swarm", "Feeds on whatever it strikes, healing itself off the wound.", 1.10,
    lifesteal_percent=0.30,
)

HOLLOW_WRAITH = _monster(
    "Hollow Wraith", "Common", "Assassin",
    "The Silent Wastes", "What's left of something that stopped being alive a long time before it stopped moving.",
    "Wound-Seeking Strike", "Grows far more dangerous once its target is already hurt.", 1.15,
    execute_damage_pct=0.35,
)

DUST_BOUND_HUSK = _monster(
    "Dust-Bound Husk", "Common", "Guardian",
    "The Buried Halls", "A slow, ash-caked shell that keeps standing long after whatever it used to guard stopped mattering.",
    "Ash-Bound Slam", "A slow, heavily durable guardian animated by nothing anyone can name.", 1.10,
)

# -- Uncommon ----------------------------------------------------------------------------------
WITHERING_SHADE = _monster(
    "Withering Shade", "Uncommon", "Brute",
    "The Rot Fields", "A shade that leaves everything it touches a little more dead than it found it.",
    "Withering Touch", "Applies a lingering wound that keeps bleeding for several turns.", 1.15,
    bleed_damage_pct=0.20,
)

DEEP_DARK_LEECH = _monster(
    "Deep Dark Leech", "Uncommon", "Mystic",
    "The Black Pools", "Surfaces without a ripple and fastens onto whoever lingers too close to water that shouldn't be that still.",
    "Fastening Drain", "Attaches and continuously drains HP for itself while the wound keeps bleeding.", 1.00,
    lifesteal_percent=0.25, bleed_damage_pct=0.10,
)

WEB_SPUN_NIGHTCRAWLER = _monster(
    "Web-Spun Nightcrawler", "Uncommon", "Skirmisher",
    "The Webbed Hollow", "Spins webs invisible in the dark long before its target ever notices its footing is already gone.",
    "Binding Web", "Uses webbing to cut speed and evasion before it ever strikes.", 1.05,
    debuff_spd_pct=0.30, debuff_dodge_pct=0.35,
)

# -- Rare --------------------------------------------------------------------------------------
ASHEN_RAVAGER = _monster(
    "Ashen Ravager", "Rare", "Brute",
    "The Ember-Dead Wastes", "Grows more savage with every drop of blood spilled nearby, its own or otherwise.",
    "Ravaging Frenzy", "Gains stacking ATK whenever either side loses HP.", 1.20,
    enrage_atk_pct_per_stack=0.09, enrage_stack_cap=6,
)

DEPTH_COILED_HORROR = _monster(
    "Depth-Coiled Horror", "Rare", "Guardian",
    "The Abyssal Trench", "Lives beneath the black water, its coils occasionally vanishing back into the depths mid-fight.",
    "Depth-Coiled Strike", "Periodically submerges and becomes untargetable.", 1.10,
    submerge_every_rounds=3, submerge_duration_rounds=1,
)

# -- Elite -------------------------------------------------------------------------------------
FORMLESS_DEVOURER = _monster(
    "Formless Devourer", "Elite", "Mystic",
    "The Unmade Depths", "Never settles on one shape or one way of hurting something -- by the time you've learned one, it's already using another.",
    "Unmade Strike", "Randomly uses a different dangerous effect on every attack.", 1.10,
    random_blood_gu=True,
)

GRAVE_BOUND_COLOSSUS = _monster(
    "Grave-Bound Colossus", "Elite", "Brute",
    "The Collapsed Throne", "Something enormous that was buried once, badly, and has spent every moment since remembering how angry that made it.",
    "Grave-Bound Fury", "Gains stacking ATK, faster and further than lesser things manage, whenever either side loses HP.", 1.20,
    enrage_atk_pct_per_stack=0.12, enrage_stack_cap=8,
)

# -- Rarity-tagged pools (see manager.py's roll_black_heaven_battle_monster) --------------------
COMMON = [VOIDLING_SWARM, HOLLOW_WRAITH, DUST_BOUND_HUSK]
UNCOMMON = [WITHERING_SHADE, DEEP_DARK_LEECH, WEB_SPUN_NIGHTCRAWLER]
RARE = [ASHEN_RAVAGER, DEPTH_COILED_HORROR]
ELITE = [FORMLESS_DEVOURER, GRAVE_BOUND_COLOSSUS]

ALL_MONSTERS_BY_RARITY = {"Common": COMMON, "Uncommon": UNCOMMON, "Rare": RARE, "Elite": ELITE}

RARITY_BY_NAME = {m.name: rarity for rarity, roster in ALL_MONSTERS_BY_RARITY.items() for m in roster}
