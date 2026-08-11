"""
Blood Sea Ancestor's Inheritance Ground (see game/inheritance_ground_data.py,
manager.py's roll_inheritance_ground_battle_monster) -- this ground's own dedicated battle-
bubble monster roster, replacing the earlier placeholder that just borrowed /hunt's generic
per-realm pool. Four rarity tiers (Common/Uncommon/Rare/Elite), each rarer tier both tougher
AND better-rewarding (see manager.py's BLOOD_SEA_RARITY_LOOT_SOURCE mapping onto
accessories_data.LOOT_SOURCE_TABLE's existing hunt_kill/raid_boss/world_boss tiers, plus
richer beast-material drops below) -- "loot getting better as it gets more elite," per the
brief.

Tuning approach: this ground's gu_rank=4 puts it at great_realm_index=3 (gu_rank-1) -- the
SAME realm content/monsters/duskwraith_barrens.py's own already-simulated roster occupies, so
that file's stat baseline (Guardian/Skirmisher/Assassin/Brute/Mystic archetype multipliers off
a shared per-realm anchor) is reused directly as this ground's own "Common" tier, with a
RARITY_MULTIPLIER stacked on top per tier below. This is a first-pass calibration (no live
per-monster simulation run, unlike Duskwraith's own validated numbers) -- same documented gap
Dao Seeking/Ancient Realm content shipped with this session; expect to retune off real player
results.

Each of these monsters' special mechanic is a small, real combat effect (see
monsters.MonsterAbility/Monster's own added fields, team_battle.py's _resolve_round/
_resolve_enemy_hit) -- not flavor text with no mechanical backing.
"""

from ...monsters import DropEntry, Monster, MonsterAbility

# -- Calibration (see module docstring) ---------------------------------------------------
_BASELINE = dict(hp=26000, atk_stat=2200, str_stat=4800, def_stat=2600, spd_stat=2000, luck_stat=1)
_QI_BY_RARITY = {"Common": 5500, "Uncommon": 6200, "Rare": 7000, "Elite": 8000}
_RARITY_MULTIPLIER = {"Common": 1.0, "Uncommon": 1.35, "Rare": 1.8, "Elite": 2.4}
# (hp, str, def, spd, atk) -- same 5-archetype framework duskwraith_barrens.py established.
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
        luck_stat=_BASELINE["luck_stat"],
        qi_stat=_QI_BY_RARITY[rarity],
    )


# -- Loot (see manager.py's grant_inheritance_ground_battle_loot / BLOOD_SEA_RARITY_LOOT_SOURCE
# for the accessory/artifact/canon-Gu side of "loot gets better with rarity" -- this only
# covers the beast-material/core side, same DropEntry shape every other region's monsters use.
_DROPS_BY_RARITY = {
    "Common": [
        DropEntry(chance=1.00, item_name="Tier 4 Beast Core"),
        DropEntry(chance=0.75, item_name="Tier 4 Beast Material"),
    ],
    "Uncommon": [
        DropEntry(chance=1.00, item_name="Tier 4 Beast Core"),
        DropEntry(chance=0.85, item_name="Tier 4 Beast Material"),
        DropEntry(chance=0.20, item_name="Tier 5 Beast Material"),
    ],
    "Rare": [
        DropEntry(chance=1.00, item_name="Tier 4 Beast Core", quantity=2),
        DropEntry(chance=0.90, item_name="Tier 4 Beast Material"),
        DropEntry(chance=0.40, item_name="Tier 5 Beast Material"),
        DropEntry(chance=0.15, item_name="Primeval Essence Crystal", quantity=6),
    ],
    "Elite": [
        DropEntry(chance=1.00, item_name="Tier 4 Beast Core", quantity=2),
        DropEntry(chance=1.00, item_name="Tier 4 Beast Material"),
        DropEntry(chance=0.60, item_name="Tier 5 Beast Material"),
        DropEntry(chance=0.30, item_name="Primeval Essence Crystal", quantity=12),
    ],
}


# Which added mechanic fields live on Monster itself vs its MonsterAbility (see monsters.py) --
# _monster() below routes each **kwarg to the right dataclass automatically.
_MONSTER_LEVEL_MECHANIC_KEYS = {
    "enrage_atk_pct_per_stack", "enrage_stack_cap", "submerge_every_rounds",
    "submerge_duration_rounds", "random_blood_gu", "shield_while_ally_alive_pct",
}


def _monster(name, rarity, archetype, habitat, description, ability_name, ability_description, str_multiplier, **mechanic_kwargs) -> Monster:
    monster_kwargs = {k: v for k, v in mechanic_kwargs.items() if k in _MONSTER_LEVEL_MECHANIC_KEYS}
    ability_kwargs = {k: v for k, v in mechanic_kwargs.items() if k not in _MONSTER_LEVEL_MECHANIC_KEYS}
    return Monster(
        name=name,
        realm=f"Rank 4 Blood Sea ({rarity})",
        monster_type="Beast",
        habitat=habitat,
        description=description,
        ability=MonsterAbility(name=ability_name, description=ability_description, str_multiplier=str_multiplier, **ability_kwargs),
        drops=_DROPS_BY_RARITY[rarity],
        gu_rank=4,
        elite=(rarity == "Elite"),
        **_stats(rarity, archetype),
        **monster_kwargs,
    )


# -- Common ----------------------------------------------------------------------------------
BLOOD_MOSQUITO_SWARM = _monster(
    "Blood Mosquito Swarm", "Common", "Skirmisher",
    "The Shallow Blood Pools", "A humming cloud of crimson-winged mosquitoes, drawn to any warmth that still bleeds.",
    "Draining Bite", "Drains HP and heals itself for part of the damage dealt.", 1.10,
    lifesteal_percent=0.35,
)

CRIMSON_BLOOD_BAT = _monster(
    "Crimson Blood Bat", "Common", "Assassin",
    "The Cavern Roosts", "A fast, blood-slick bat that circles wounded prey, growing bolder the more it bleeds.",
    "Wound-Seeking Dive", "A fast attacker that becomes stronger against injured players.", 1.15,
    execute_damage_pct=0.35,
)

BLOODSKIN_CORPSE = _monster(
    "Bloodskin Corpse", "Common", "Guardian",
    "The Sunken Antechambers", "A slow, hide-wrapped guardian animated by the inheritance formation's own lingering will.",
    "Formation-Bound Slam", "A slow, heavily durable guardian animated by the inheritance formation.", 1.10,
)

# -- Uncommon --------------------------------------------------------------------------------
BLOODSCALE_SERPENT = _monster(
    "Bloodscale Serpent", "Uncommon", "Brute",
    "The Crimson Reeds", "A serpent whose scarlet scales weep a thin, corrosive blood that lingers in any wound it opens.",
    "Corrosive Fang", "Applies Bleed, dealing damage for several turns.", 1.15,
    bleed_damage_pct=0.18,
)

BLOOD_POOL_LEECH = _monster(
    "Blood Pool Leech", "Uncommon", "Mystic",
    "The Blood Pools", "A bloated leech that surfaces silently and fastens onto whoever lingers too close to the pools.",
    "Fastening Drain", "Attaches to the cultivator and continuously steals HP until killed.", 1.00,
    lifesteal_percent=0.25, bleed_damage_pct=0.12,
)

CRIMSON_BONE_SPIDER = _monster(
    "Crimson Bone Spider", "Uncommon", "Skirmisher",
    "The Ossuary Webs", "A spider of fused bone and dried blood, its webs slowing prey long before its fangs ever land.",
    "Binding Web", "Uses webs to reduce speed/evasion before attacking.", 1.05,
    debuff_spd_pct=0.30, debuff_dodge_pct=0.35,
)

# -- Rare ------------------------------------------------------------------------------------
BLOOD_FANG_WOLF = _monster(
    "Blood Fang Wolf", "Rare", "Brute",
    "The Hunting Grounds", "A scarred wolf that grows more savage with every drop of blood spilled nearby, its own or otherwise.",
    "Bloodlust Fang", "Gains stacking ATK whenever either side loses HP.", 1.20,
    enrage_atk_pct_per_stack=0.08, enrage_stack_cap=6,
)

BLOOD_RIVER_PYTHON = _monster(
    "Blood River Python", "Rare", "Guardian",
    "The Deep Blood River", "A massive python that lives beneath the blood pools, its coils occasionally vanishing back into the crimson depths.",
    "Depth-Coiled Strike", "A massive beast that periodically submerges and becomes untargetable.", 1.10,
    submerge_every_rounds=3, submerge_duration_rounds=1,
)

# -- Elite -----------------------------------------------------------------------------------
BLOOD_GU_ABOMINATION = _monster(
    "Blood Gu Abomination", "Elite", "Mystic",
    "The Failed Refinement Pits", "A writhing mass fused from countless failed Blood Path Gu refinements, no two strikes ever quite the same.",
    "Failed Refinement Lash", "A creature created from countless failed Blood Path Gu refinements. Randomly uses different Blood Gu effects.", 1.10,
    random_blood_gu=True,
)

CRIMSON_FORMATION_GUARDIAN = _monster(
    "Crimson Formation Guardian", "Elite", "Guardian",
    "The Inner Sanctum", "An ancient construct bound to the inheritance's inner formation, all but untouchable while its formation nodes still hum.",
    "Formation-Bound Ward", "An ancient construct protecting the inner inheritance. Gains shields until players destroy its formation nodes.", 1.05,
    shield_while_ally_alive_pct=0.90,
)

# Crimson Formation Guardian's own destroyable formation nodes (see manager.py's
# roll_inheritance_ground_battle_monster / InheritanceGroundView's multi-target battle
# support) -- deliberately low-HP, low-threat "shield batteries" rather than real second
# combatants, so the fight is still fundamentally "burn the guardian's shield down by killing
# 2 small adds, then fight the guardian" rather than a 3-enemy slog.
CRIMSON_FORMATION_NODE = Monster(
    name="Crimson Formation Node",
    realm="Rank 4 Blood Sea (Elite)",
    monster_type="Construct",
    habitat="The Inner Sanctum",
    description="A humming crimson sigil-stone anchoring part of the guardian's shield -- fragile once actually struck.",
    ability=MonsterAbility(name="Sigil Discharge", description="A weak defensive discharge.", str_multiplier=0.4),
    drops=[],
    hp=8000, atk_stat=400, str_stat=500, def_stat=400, spd_stat=800, luck_stat=1, qi_stat=1000,
    gu_rank=4,
)

# -- Final Trial boss (see manager.py's roll_inheritance_ground_final_boss,
# InheritanceGroundView._on_face_trial) -- a real fight now, not a pure power-vs-threshold
# check: a DPS check (dps_check_first_turn/dps_check_interval_growth -- see
# team_battle.py's Phase 3.5) force-kills one random alive team member 5 rounds in, then
# again 6 rounds after that, then 7 more, etc. HP values are first-pass placeholders per
# explicit request ("15m hp for now") -- expect to retune once real teams have actually
# fought this. 99% of runs face the Demon Disciple; 1% face the true Ancestor's Blood Will
# instead (see BLOOD_SEA_ANCESTOR_BLOOD_WILL_CHANCE below) -- same HP-defined-directly,
# stats-derived-from-an-archetype-baseline approach the rest of this file uses, just with
# an explicit multiplier on top since these two sit well above even the Elite tier.
BLOOD_SEA_DEMON_DISCIPLE = Monster(
    name="Blood Sea Demon Disciple",
    realm="Rank 4 Blood Sea (Boss)",
    monster_type="Spirit",
    habitat="The Inner Sanctum",
    description="The Ancestor's last disciple, kept half-alive by the blood sea itself -- what's left of its will is entirely bent on making sure no one leaves with what they came for.",
    ability=MonsterAbility(name="Sanctum-Ending Strike", description="A relentless, sanctum-shaking strike.", str_multiplier=1.15),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 4 Beast Core", quantity=3),
        DropEntry(chance=1.00, item_name="Tier 5 Beast Material", quantity=2),
        DropEntry(chance=0.50, item_name="Primeval Essence Crystal", quantity=20),
    ],
    hp=15_000_000, atk_stat=25000, str_stat=48000, def_stat=42000, spd_stat=18000, luck_stat=1, qi_stat=25000,
    gu_rank=4,
    elite=True,
    dps_check_first_turn=5, dps_check_interval_growth=1,
)

BLOOD_SEA_ANCESTORS_BLOOD_WILL = Monster(
    name="Blood Sea Ancestor's Blood Will",
    realm="Rank 4 Blood Sea (True Boss)",
    monster_type="Spirit",
    habitat="The Inner Sanctum",
    description="Not an echo, not a disciple -- a fragment of the Ancestor's own unbroken will, drawn up from the deepest blood pool by a team it's decided is worth the effort.",
    ability=MonsterAbility(name="Ancestor's Undivided Will", description="A single, world-narrowing strike of pure will.", str_multiplier=1.15),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 4 Beast Core", quantity=5),
        DropEntry(chance=1.00, item_name="Tier 5 Beast Material", quantity=4),
        DropEntry(chance=1.00, item_name="Primeval Essence Crystal", quantity=30),
    ],
    hp=50_000_000, atk_stat=38000, str_stat=72000, def_stat=64000, spd_stat=27000, luck_stat=1, qi_stat=38000,
    gu_rank=4,
    elite=True,
    dps_check_first_turn=5, dps_check_interval_growth=1,
)
BLOOD_SEA_ANCESTORS_BLOOD_WILL_CHANCE = 0.01

# -- Rarity-tagged pools (see manager.py's roll_inheritance_ground_battle_monster) -----------
COMMON = [BLOOD_MOSQUITO_SWARM, CRIMSON_BLOOD_BAT, BLOODSKIN_CORPSE]
UNCOMMON = [BLOODSCALE_SERPENT, BLOOD_POOL_LEECH, CRIMSON_BONE_SPIDER]
RARE = [BLOOD_FANG_WOLF, BLOOD_RIVER_PYTHON]
ELITE = [BLOOD_GU_ABOMINATION, CRIMSON_FORMATION_GUARDIAN]

# Tier weighting (see manager.py's BLOOD_SEA_RARITY_TIER_WEIGHT) is per-TIER, not per-monster
# -- individual monsters within a tier are equal-weight.
ALL_MONSTERS_BY_RARITY = {"Common": COMMON, "Uncommon": UNCOMMON, "Rare": RARE, "Elite": ELITE}

# name -> rarity, for manager.py's grant_inheritance_ground_battle_loot to look up which loot
# tier a just-defeated monster's name maps to (dataclasses.replace-scaled copies keep the same
# .name, so this lookup works whether or not battle_number scaling was applied). Formation
# Node deliberately excluded -- it's a shield-battery sub-target, not a loot-granting kill.
# Both Final Trial bosses map to "Elite" odds for their bonus accessory/canon-Gu roll -- their
# OWN drops list is already richer than a normal Elite's, and the betrayal stage's
# share/backstab reward remains the actual "big" prize for clearing the trial at all.
RARITY_BY_NAME = {m.name: rarity for rarity, roster in ALL_MONSTERS_BY_RARITY.items() for m in roster}
RARITY_BY_NAME[BLOOD_SEA_DEMON_DISCIPLE.name] = "Elite"
RARITY_BY_NAME[BLOOD_SEA_ANCESTORS_BLOOD_WILL.name] = "Elite"
