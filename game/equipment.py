"""
Equipment: gear that occupies one of 9 slots and grants passive stat bonuses
while equipped. Ownership lives in the same `inventory` table Healing/Pills
use (equipment pieces are just items whose name happens to be in EQUIPMENT
instead of ITEMS); which owned piece sits in which slot is tracked in the
`equipped` table.

`stat_bonuses` keys match the foundation stat columns (str_stat, atk_stat, hp,
spd_stat, def_stat, qi_stat, luck_stat) for ordinary gear. Manuals are the one
exception — a manual's bonus is `cultivation_speed_pct`, which feeds the same
qi accrual rate as race/root/physique/path bonuses (see chargen.effective_qi_rate_bonus
and GameDatabase.settle_qi), not a flat stat.

Gu are a separate slot_type ("Gu", slot key "gu_ability") — they're what the
hunt combat screen calls your "Gu ability". Most gear is purely passive, but a
Gu can additionally define `active_ability`, an in-combat action (see
game/hunt.py) with its own damage multiplier and Qi cost.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ActiveAbility:
    name: str
    description: str
    str_multiplier: float  # damage dealt = attacker STR * this, instead of the normal 1.0x basic attack
    qi_cost: int = 0


@dataclass
class Equipment:
    name: str
    slot_type: str  # "Head", "Body", "Weapon", "Ring", "Earring", "Necklace", "Bracelet", "Artifact", "Manual", "Gu"
    rank: str  # display-only flavor rank for now (e.g. "F+"/"Rank 1") — no numeric formula behind it yet
    description: str
    stat_bonuses: Dict[str, float] = field(default_factory=dict)
    active_ability: Optional[ActiveAbility] = None


# (slot_key, display_label, accepted slot_type, emoji)
# Accessory slots used to be two generic "Accessory" slots — split into 6 typed slots
# (see accessories_data.py, the insanity_accessories_and_artifacts_system doc) so a Ring
# only fits a ring slot, an Earring only an earring slot, etc. Belt/waist/brooch items all
# share the single "bracelet" slot per the doc's own "one wrist/waist slot" rule, even
# though the doc's item table spells them Bracelet/Belt/Belt Token/Brooch — those are all
# normalized to slot_type "Bracelet" in the data layer. Artifact stays 2 generic slots
# (artifact_1 doubles as "primary" — the only one allowed a Major Active in combat per the
# doc's "Major Trigger limit" rule — artifact_2 as "support"); see ARTIFACT_PRIMARY_SLOT_KEY.
SLOTS = [
    ("head", "Head", "Head", "🪖"),
    ("body", "Body", "Body", "🛡️"),
    ("weapon", "Weapon", "Weapon", "⚔️"),
    ("ring_1", "Ring I", "Ring", "💍"),
    ("ring_2", "Ring II", "Ring", "💍"),
    ("earring_1", "Earring I", "Earring", "📿"),
    ("earring_2", "Earring II", "Earring", "📿"),
    ("necklace", "Necklace", "Necklace", "⛓️"),
    ("bracelet", "Bracelet/Belt", "Bracelet", "🪢"),
    ("artifact_1", "Primary Artifact", "Artifact", "💠"),
    ("artifact_2", "Support Artifact", "Artifact", "🔹"),
    ("manual", "Manual", "Manual", "📖"),
    ("gu_ability", "Gu Ability", "Gu", "🐛"),
]
ARTIFACT_PRIMARY_SLOT_KEY = "artifact_1"

SLOT_TYPE_BY_KEY = {key: slot_type for key, _, slot_type, _ in SLOTS}
SLOT_LABEL_BY_KEY = {key: label for key, label, _, _ in SLOTS}
SLOT_EMOJI_BY_KEY = {key: emoji for key, _, _, emoji in SLOTS}
# Keyed by slot_type instead of slot_key (unlike SLOT_EMOJI_BY_KEY above) — Ring, Earring,
# and Artifact each have two slot_keys sharing one slot_type, and this is for looking up a
# piece of Equipment's own emoji (which only knows its slot_type), not a specific slot.
SLOT_TYPE_EMOJI = {slot_type: emoji for _, _, slot_type, emoji in SLOTS}
# The reverse of SLOT_TYPE_BY_KEY — only meaningful for slot types with exactly ONE
# slot_key (Head/Body/Weapon/Necklace/Bracelet/Manual/Gu). Ring, Earring, and Artifact each
# have two slot_keys sharing one slot_type, so this dict silently keeps whichever one is
# built last for those three — fine for crafted_gear (only ever Weapon/Head/Body, each
# unique), not a general "find the slot for this slot_type" lookup.
SLOT_KEY_BY_TYPE = {slot_type: key for key, _, slot_type, _ in SLOTS}


EQUIPMENT: Dict[str, Equipment] = {
    "Rusty Practice Sword": Equipment(
        name="Rusty Practice Sword",
        slot_type="Weapon",
        rank="F+",
        description="A dull training blade, more rust than edge. Better than fists.",
        stat_bonuses={"str_stat": 3, "atk_stat": 2, "spd_stat": 1},
    ),
    "Worn Linen Clothes": Equipment(
        name="Worn Linen Clothes",
        slot_type="Body",
        rank="F+",
        description="Patched and thin, but it'll stop a scratch.",
        stat_bonuses={"hp": 10, "def_stat": 2},
    ),
    "Worn Headband": Equipment(
        name="Worn Headband",
        slot_type="Head",
        rank="F+",
        description="Keeps the sweat out of your eyes, if nothing else.",
        stat_bonuses={"def_stat": 1, "luck_stat": 1},
    ),
    "Rusty Jade Ring": Equipment(
        name="Rusty Jade Ring",
        slot_type="Ring",
        rank="F+",
        description="The jade has seen better centuries.",
        stat_bonuses={"qi_stat": 2, "luck_stat": 1},
    ),
    "Basic Flying Artifact": Equipment(
        name="Basic Flying Artifact",
        slot_type="Artifact",
        rank="F+",
        description="Barely gets you off the ground, but it counts.",
        stat_bonuses={"spd_stat": 2, "qi_stat": 1},
    ),
    "First Breathing Manual": Equipment(
        name="First Breathing Manual",
        slot_type="Manual",
        rank="F+",
        description="The most basic breathing technique in existence — the weakest cultivation manual there is.",
        stat_bonuses={"cultivation_speed_pct": 0.02},
    ),
    # The Mythic-tier jackpot in /explore's loot table (see exploration.py) — nothing else
    # drops it yet, so it's a pure "you got extremely lucky" trophy weapon for now. Uses
    # blacksmith.py's own str_pct/atk_pct currency (see CRAFTED_GEAR_PCT_TO_FLAT in this
    # file — compute_equipment_bonuses applies these identically no matter which item they
    # came from) instead of flat stats specifically so it can't be outgrown: a flat +40 STR
    # is only ever "best in slot" up to whatever realm makes a Tier 7 craft's percentage
    # roll worth more, and past that it's dead weight forever. 0.55 str_pct + 0.40 atk_pct =
    # 95 percentage points, comfortably past the ~75 an actual max-roll Tier 7 craft can ever
    # reach even with the rarest gear_budget_bonus_pct root (see blacksmith.TIER_PCT_BUDGET
    # and character_data's Long Hair Ancestor Root) — plus crit_chance_pct, which the
    # percentage-based crafting system has no way to roll onto a weapon at all.
    "Heaven-Severing Blade": Equipment(
        name="Heaven-Severing Blade",
        slot_type="Weapon",
        rank="Mythic",
        description="A blade said to have split a mountain in two — its edge outclasses anything even a Grandmaster blacksmith can forge. Finding one at all is almost unheard of.",
        stat_bonuses={"str_pct": 0.55, "atk_pct": 0.40, "crit_chance_pct": 0.08},
    ),
    "Iron Skin Gu": Equipment(
        name="Iron Skin Gu",
        slot_type="Gu",
        rank="Rank 1",
        description="+5 DEF permanently while equipped.",
        stat_bonuses={"def_stat": 5},
    ),
    "Boar Strength Gu": Equipment(
        name="Boar Strength Gu",
        slot_type="Gu",
        rank="Rank 1",
        description="+5 STR while equipped.",
        stat_bonuses={"str_stat": 5},
    ),
    "Charge Gu": Equipment(
        name="Charge Gu",
        slot_type="Gu",
        rank="Rank 1",
        description="Active skill: rush an enemy and deal bonus damage.",
        active_ability=ActiveAbility(
            name="Charge",
            description="Rush an enemy and deal bonus damage.",
            str_multiplier=1.5,
            qi_cost=10,
        ),
    ),
}

# -- Tiered Gu: quality-ladder Gu that drop from hunts/raids and fuse into higher tiers -----
#
# Unlike the starter Gu above (flat, single-tier), these come in 7 quality tiers of the
# same family. A dropped Gu always starts at Common; two copies of the same family+quality
# fuse into one copy of the next quality up (see GameManager.upgrade_gu). Each (family,
# quality) pair is registered into EQUIPMENT below as its own item, named "Family (Quality)",
# so the existing inventory/equip machinery (which is just keyed on item name) handles them
# with no schema changes.
#
# stat_bonuses here reuse the normal foundation-stat keys (hp, def_stat, str_stat, ...) plus
# a handful of new special keys consumed by combat code (GameManager.compute_equipment_bonuses
# sums them, hunt.py/raid.py thread them into combat.resolve_attack):
#   crit_chance_pct           -- added to the attacker's crit chance
#   crit_damage_pct           -- added to CRIT_DAMAGE_MULTIPLIER on a crit
#   beast_damage_reduction_pct-- extra fractional reduction on incoming damage from monster_type == "Beast"
#   ignore_attack_chance      -- chance to fully negate an incoming hit, after it lands
#   lifesteal_percent         -- attacker heals this fraction of damage dealt
#   low_hp_atk_bonus          -- flat STR bonus while below 50% HP

GU_QUALITY_ORDER = ["Common", "Uncommon", "Rare", "Epic", "Legendary", "Mythic", "Immortal"]
GU_QUALITY_STARS = {quality: i + 1 for i, quality in enumerate(GU_QUALITY_ORDER)}
GU_NEXT_QUALITY = {q: GU_QUALITY_ORDER[i + 1] for i, q in enumerate(GU_QUALITY_ORDER[:-1])}

# Duplicates needed to fuse FROM this quality to the next, applied to every Gu (not just
# the canon 26) so /upgrade_gu has one consistent rule rather than two different duplicate
# costs depending on which Gu you're fusing. Floored at 2 across every tier (even
# Common/Uncommon) so a fusion always genuinely consumes a pair rather than letting a
# single unpaired copy "upgrade" itself for free.
GU_UPGRADE_DUPLICATES_REQUIRED = {
    "Common": 2, "Uncommon": 2, "Rare": 2, "Epic": 3, "Legendary": 4, "Mythic": 5,
}

# Rough per-piece combat value, for sorting equipment lists best-first (see
# game/hunt.py, game/equipment_view.py, game/trading.py, game/gu_upgrade.py) — same spirit
# as GameManager.COMBAT_POWER_WEIGHTS (a player's aggregate score) but scoped to a single
# piece of gear's own stat_bonuses, so a big list (e.g. a hoarded Gu collection, easily past
# Discord's 25-option Select cap) shows its strongest pieces first instead of an arbitrary
# slice in whatever order EQUIPMENT happens to be registered.
GEAR_POWER_WEIGHTS = {
    "str_stat": 1.0, "atk_stat": 1.0, "def_stat": 1.0, "spd_stat": 1.0,
    "luck_stat": 0.5, "hp": 0.1, "qi_stat": 0.1,
}
# GEAR_POWER_WEIGHTS above only covers flat foundation stats — plenty of Gu (Blood Boar
# Gu's whole quality line, for one) are built entirely out of GameManager.SPECIAL_BONUS_KEYS
# percentages instead (lifesteal, crit, damage reduction, ...), which would otherwise score
# a flat 0 and sort dead last regardless of quality. Weights are rough unit conversions
# (e.g. crit_chance_pct's 0.01-per-point matches CRIT_CHANCE_PER_LUCK, so it's priced the
# same as luck_stat: 100 * 0.5) rather than a precise balance pass — this only drives sort
# order, not actual combat math.
SPECIAL_BONUS_POWER_WEIGHTS = {
    "crit_chance_pct": 50, "crit_damage_pct": 40, "lifesteal_percent": 150,
    "beast_damage_reduction_pct": 120, "ignore_attack_chance": 150, "dodge_chance_pct": 100,
    "stone_reward_bonus_pct": 60, "loot_chance_bonus_pct": 60, "essence_regen_pct": 60,
    "cultivation_speed_pct": 60,
    "low_hp_atk_bonus": 0.5,  # already a flat STR-like bonus, not a percentage — priced like str_stat
    # Percentage-based blacksmith gear (see blacksmith.py's roll_gear_stats) — weighted
    # evenly since, unlike the old flat system, a % is the same currency regardless of
    # which stat it's on (there's no more "HP numbers are just naturally huge" reason to
    # price it cheaper than STR the way GEAR_POWER_WEIGHTS' flat hp/qi_stat entries do).
    "str_pct": 100, "atk_pct": 100, "def_pct": 100, "spd_pct": 100, "hp_pct": 100, "qi_pct": 100,
    # Manual-only effects (see manual_view.EFFECT_LABELS / GameManager.compute_equipment_bonuses)
    # — no gear currently rolls these, but they're scored here too in case that changes.
    "breakthrough_success_pct": 80, "essence_purity_pct": 60, "technique_damage_pct": 90,
    "physical_damage_pct": 90, "insight_gain_pct": 50, "cooldown_reduction_pct": 90,
    "deviation_resistance_pct": 50,
    # Alchemy success bonus (see GameManager.craft_pill) — Crimson Furnace Province's own
    # accessories/artifact.
    "alchemy_success_pct": 60,
}
# Which flat player-stat column each percentage-based crafted_gear stat resolves against —
# see GameManager.compute_equipment_bonuses, the only place these keys are actually applied
# (everywhere else, including gear_power_score_from_stats above, just treats them as opaque
# scoring/display keys).
CRAFTED_GEAR_PCT_TO_FLAT = {
    "str_pct": "str_stat", "atk_pct": "atk_stat", "def_pct": "def_stat",
    "spd_pct": "spd_stat", "hp_pct": "hp", "qi_pct": "qi_stat",
}
# An active ability (Gu only) adds real combat value beyond its passive stat_bonuses —
# sized so a strong ability meaningfully outweighs a similar passive-only piece without
# completely dominating the sort by itself.
ACTIVE_ABILITY_POWER_BONUS = 10.0


def gear_power_score_from_stats(stat_bonuses: Dict[str, float]) -> float:
    """The same scoring math as gear_power_score, for a raw stat_bonuses dict that isn't
    (or isn't yet) wrapped in an Equipment — e.g. a crafted_gear instance's rolled stats,
    scored at craft time before it has a display name or anywhere else to live."""
    score = sum(stat_bonuses.get(stat, 0) * weight for stat, weight in GEAR_POWER_WEIGHTS.items())
    score += sum(stat_bonuses.get(stat, 0) * weight for stat, weight in SPECIAL_BONUS_POWER_WEIGHTS.items())
    return score


def gear_power_score(gear: "Equipment") -> float:
    score = gear_power_score_from_stats(gear.stat_bonuses)
    if gear.active_ability:
        score += ACTIVE_ABILITY_POWER_BONUS * gear.active_ability.str_multiplier
    return score


# Spirit stones per quality star (Common=1 star .. Immortal=7 stars — see GU_QUALITY_STARS)
# when breaking a Gu down instead of fusing it — a non-tiered Gu (the original starter
# handful, with no quality at all) counts as 1 star, the same as a base Common piece.
GU_BREAKDOWN_VALUE_PER_STAR = 20


def gu_breakdown_value(item_name: str) -> int:
    _, quality = parse_gu_name(item_name)
    stars = GU_QUALITY_STARS[quality] if quality else 1
    return GU_BREAKDOWN_VALUE_PER_STAR * stars

# Given verbatim by rank ("rank 1-2 Gu for the boss and the boar to drop") without a per-family
# rank split, so all four are filed under drop_rank 1 (matching the boar/boss's own Rank 1-2
# Beast level) — "Tier 2 Gu" drop pools are reserved for a future higher-rank family.
GU_FAMILIES = {
    "Ironhide Boar Gu": {
        "drop_rank": 1,
        "qualities": {
            "Common": {"hp": 10, "def_stat": 2},
            "Uncommon": {"hp": 15, "def_stat": 3},
            "Rare": {"hp": 22, "def_stat": 5, "beast_damage_reduction_pct": 0.03},
            "Epic": {"hp": 32, "def_stat": 8, "beast_damage_reduction_pct": 0.05},
            "Legendary": {"hp": 45, "def_stat": 12, "beast_damage_reduction_pct": 0.08, "ignore_attack_chance": 0.05},
            "Mythic": {"hp": 60, "def_stat": 16, "beast_damage_reduction_pct": 0.12, "ignore_attack_chance": 0.10},
            "Immortal": {"hp": 80, "def_stat": 22, "beast_damage_reduction_pct": 0.20, "ignore_attack_chance": 0.15},
        },
    },
    "Charging Tusk Gu": {
        "drop_rank": 1,
        "qualities": {
            "Common": {"str_stat": 5},
            "Uncommon": {"str_stat": 8},
            "Rare": {"str_stat": 12, "crit_chance_pct": 0.02},
            "Epic": {"str_stat": 16, "crit_chance_pct": 0.04},
            "Legendary": {"str_stat": 22, "crit_chance_pct": 0.06},
            "Mythic": {"str_stat": 30, "crit_chance_pct": 0.08},
            "Immortal": {"str_stat": 40, "crit_chance_pct": 0.10, "crit_damage_pct": 0.25},
        },
    },
    "Blood Boar Gu": {
        "drop_rank": 1,
        "qualities": {
            "Common": {"lifesteal_percent": 0.03},
            "Uncommon": {"lifesteal_percent": 0.05},
            "Rare": {"lifesteal_percent": 0.07},
            "Epic": {"lifesteal_percent": 0.10},
            "Legendary": {"lifesteal_percent": 0.14},
            "Mythic": {"lifesteal_percent": 0.18},
            "Immortal": {"lifesteal_percent": 0.25},
        },
    },
    "Savage Boar Gu": {
        "drop_rank": 1,
        "qualities": {
            "Common": {"str_stat": 8, "hp": 15},
            "Uncommon": {"str_stat": 12, "hp": 25},
            "Rare": {"str_stat": 18, "hp": 35},
            "Epic": {"str_stat": 25, "hp": 50, "low_hp_atk_bonus": 10},
            "Legendary": {"str_stat": 35, "hp": 70, "low_hp_atk_bonus": 15},
            "Mythic": {"str_stat": 50, "hp": 100, "low_hp_atk_bonus": 20},
            "Immortal": {"str_stat": 70, "hp": 150, "low_hp_atk_bonus": 30},
        },
    },
}

# Regional Gu families (see game/content/gu_families.py) — merged in before
# _register_tiered_gu() runs below, the same aggregator pattern items.py/monsters.py/
# manual_data.py all use for their own content-package merges. No import-order trick needed
# here: a Gu family is plain data with zero dependency on anything else in this module, so
# this could even sit at module top — it's placed here just to stay next to GU_FAMILIES
# itself for readability.
from .content.gu_families import VERDANT_BORDERLANDS_GU_FAMILIES  # noqa: E402
from .content.gu_families_hundred_beast_mountains import GU_FAMILIES_HUNDRED_BEAST_MOUNTAINS  # noqa: E402
from .content.gu_families_crimson_furnace import GU_FAMILIES_CRIMSON_FURNACE  # noqa: E402
from .content.gu_families_duskwraith_barrens import GU_FAMILIES_DUSKWRAITH_BARRENS  # noqa: E402
from .content.gu_families_dao_seeking import GU_FAMILIES_DAO_SEEKING  # noqa: E402

GU_FAMILIES.update(VERDANT_BORDERLANDS_GU_FAMILIES)
GU_FAMILIES.update(GU_FAMILIES_HUNDRED_BEAST_MOUNTAINS)
GU_FAMILIES.update(GU_FAMILIES_CRIMSON_FURNACE)
GU_FAMILIES.update(GU_FAMILIES_DUSKWRAITH_BARRENS)
GU_FAMILIES.update(GU_FAMILIES_DAO_SEEKING)

# Shared by every place that renders an Equipment's stat_bonuses (equipment_view.py's slot
# list, views.py's Inventory "Equipment" tab, and this module's own Gu descriptions) so the
# wording can't drift between them.
FOUNDATION_STAT_LABELS = {"str_stat": "STR", "atk_stat": "ATK", "hp": "HP", "spd_stat": "SPD", "def_stat": "DEF", "qi_stat": "QI", "luck_stat": "LCK"}
SPECIAL_STAT_TEXT = {
    "cultivation_speed_pct": lambda v: f"+{v * 100:.0f}% cultivation gain",
    "crit_chance_pct": lambda v: f"+{v * 100:.0f}% Crit Chance",
    "crit_damage_pct": lambda v: f"+{v * 100:.0f}% Crit Damage",
    "beast_damage_reduction_pct": lambda v: f"-{v * 100:.0f}% Beast damage taken",
    "ignore_attack_chance": lambda v: f"{v * 100:.0f}% chance to ignore an attack",
    "lifesteal_percent": lambda v: f"Heal {v * 100:.0f}% of damage dealt",
    "low_hp_atk_bonus": lambda v: f"+{v:g} ATK below 50% HP",
    "dodge_chance_pct": lambda v: f"+{v * 100:.0f}% Dodge Chance",
    "stone_reward_bonus_pct": lambda v: f"+{v * 100:.0f}% Spirit Stone rewards",
    "loot_chance_bonus_pct": lambda v: f"+{v * 100:.0f}% loot luck",
    "essence_regen_pct": lambda v: f"+{v * 100:.0f}% essence recovery",
    "clue_chance_bonus_pct": lambda v: f"+{v * 100:.0f}% clue/detection chance",
    # Percentage-based blacksmith gear (see blacksmith.py's roll_gear_stats) — displays as
    # "+X% STR" etc, reusing FOUNDATION_STAT_LABELS for the stat name.
    "str_pct": lambda v: f"+{v * 100:.1f}% STR",
    "atk_pct": lambda v: f"+{v * 100:.1f}% ATK",
    "def_pct": lambda v: f"+{v * 100:.1f}% DEF",
    "spd_pct": lambda v: f"+{v * 100:.1f}% SPD",
    "hp_pct": lambda v: f"+{v * 100:.1f}% HP",
    "qi_pct": lambda v: f"+{v * 100:.1f}% QI",
    # Manual-only effects (see manual_view.EFFECT_LABELS) — surfaced here too so
    # equipment_view.py's "Passive Bonuses" summary picks them up like any other bonus.
    "breakthrough_success_pct": lambda v: f"+{v * 100:.0f}% Breakthrough Success",
    "essence_purity_pct": lambda v: f"+{v * 100:.0f}% Essence Purity",
    "technique_damage_pct": lambda v: f"+{v * 100:.0f}% Technique Damage",
    "physical_damage_pct": lambda v: f"+{v * 100:.0f}% Physical Damage",
    "insight_gain_pct": lambda v: f"+{v * 100:.0f}% Insight Gain",
    "cooldown_reduction_pct": lambda v: f"-{v * 100:.0f}% Cooldowns",
    "deviation_resistance_pct": lambda v: f"+{v * 100:.0f}% Deviation Resistance",
    "alchemy_success_pct": lambda v: f"+{v * 100:.0f}% Alchemy Success",
    "armor_penetration_pct": lambda v: f"+{v * 100:.0f}% Armor Penetration",
    "death_qi_loss_reduction_pct": lambda v: f"-{v * 100:.0f}% Qi Lost on Death",
    "soul_skill_potency_pct": lambda v: f"+{v * 100:.0f}% Soul Skill Potency",
    "soul_projection_damage_pct": lambda v: f"+{v * 100:.0f}% Soul Projection Damage",
    # Spirit Severing Dao Paths (see game/dao_paths.py) — the handful of keys with no other
    # gear/manual precedent, surfaced here too so equipment_view.py's own "Passive Bonuses"
    # summary (and dao_path_view.py's per-path bonus display) render with consistent wording.
    "dao_comprehension_pct": lambda v: f"+{v * 100:.0f}% Dao Comprehension",
    "meditate_cooldown_reduction_pct": lambda v: f"-{v * 100:.0f}% Meditate Cooldown",
    "luck_flat": lambda v: f"+{v:g} Luck",
    "fire_burn_damage_pct": lambda v: f"+{v * 100:.0f}% Burn Damage",
    "alchemy_bonus_pill_chance_pct": lambda v: f"+{v * 100:.0f}% Bonus Pill Chance",
    "crafting_success_pct": lambda v: f"+{v * 100:.0f}% Crafting Success",
    "pill_save_chance_pct": lambda v: f"+{v * 100:.0f}% Pill Save Chance",
}


def describe_stat_bonuses(stat_bonuses: dict) -> str:
    parts = []
    for stat, value in stat_bonuses.items():
        if stat in SPECIAL_STAT_TEXT:
            parts.append(SPECIAL_STAT_TEXT[stat](value))
        elif stat in FOUNDATION_STAT_LABELS:
            parts.append(f"{FOUNDATION_STAT_LABELS[stat]}: {value:+d}")
        else:
            parts.append(f"{stat}: {value:+g}")
    return " • ".join(parts)


def gu_item_name(family: str, quality: str) -> str:
    return f"{family} ({quality})"


def parse_gu_name(item_name: str):
    """Reverses gu_item_name — returns (family, quality) or (None, None) if it isn't one.
    Checks the actual EQUIPMENT catalog rather than a specific families dict (GU_FAMILIES
    only covers the original 4 — this way it also recognizes canon_gu.py's 26, and
    whatever else gets registered as tiered Gu later, with no dependency either way)."""
    if item_name.endswith(")") and " (" in item_name:
        family, _, rest = item_name.rpartition(" (")
        quality = rest[:-1]
        if quality in GU_QUALITY_ORDER and gu_item_name(family, quality) in EQUIPMENT:
            return family, quality
    return None, None


# Total foundation-stat percentage budget per Gu quality — same 7-tier curve
# blacksmith.py's TIER_PCT_BUDGET already uses for crafted gear (Common..Immortal lining up
# 1:1 with blacksmith's Tier 1..7), so a Gu and a piece of gear of matching quality carry
# equal stat weight. Applied by foundation_stats_to_pct below.
GU_QUALITY_PCT_BUDGET = {
    "Common": 0.08, "Uncommon": 0.14, "Rare": 0.20, "Epic": 0.28,
    "Legendary": 0.37, "Mythic": 0.47, "Immortal": 0.60,
}
_PCT_KEY_FOR_FLAT_STAT = {flat: pct for pct, flat in CRAFTED_GEAR_PCT_TO_FLAT.items()}


def foundation_stats_to_pct(stat_bonuses: Dict[str, float], budget: float) -> Dict[str, float]:
    """Converts any foundation-stat keys (str_stat, atk_stat, hp, spd_stat, def_stat, qi_stat)
    into their _pct equivalents, splitting `budget` (e.g. 0.08 for an 8% total) across just
    the foundation stats present — weighted by GEAR_POWER_WEIGHTS (the same per-stat value
    scale already used to sort gear) so a family's original relative emphasis between stats
    survives the conversion even though a flat "10 hp" and a flat "2 def_stat" aren't
    equally strong. Every other key (crit_chance_pct, lifesteal_percent, low_hp_atk_bonus,
    ...) passes through unchanged — those are already percentages or intentionally flat."""
    present = {k: v for k, v in stat_bonuses.items() if k in _PCT_KEY_FOR_FLAT_STAT}
    result = {k: v for k, v in stat_bonuses.items() if k not in _PCT_KEY_FOR_FLAT_STAT}
    weights = {k: v * GEAR_POWER_WEIGHTS.get(k, 1.0) for k, v in present.items()}
    total_weight = sum(weights.values())
    if total_weight <= 0:
        return result
    for stat, weight in weights.items():
        pct = round(budget * (weight / total_weight), 3)
        if pct > 0:
            result[_PCT_KEY_FOR_FLAT_STAT[stat]] = pct
    return result


def _register_tiered_gu():
    for family_name, family_data in GU_FAMILIES.items():
        for quality in GU_QUALITY_ORDER:
            bonuses = family_data["qualities"].get(quality)
            if bonuses is None:
                continue
            item_name = gu_item_name(family_name, quality)
            stars = "★" * GU_QUALITY_STARS[quality]
            pct_bonuses = foundation_stats_to_pct(bonuses, GU_QUALITY_PCT_BUDGET[quality])
            EQUIPMENT[item_name] = Equipment(
                name=item_name,
                slot_type="Gu",
                rank=f"{stars} {quality}",
                description=f"{family_name} — {quality} quality. {describe_stat_bonuses(pct_bonuses)}.",
                stat_bonuses=pct_bonuses,
            )


_register_tiered_gu()

# -- Blacksmith-craftable gear (see /blacksmith, game/blacksmith.py for the recipe) --------
# Generic names for now ("I'll add the names of higher tier [gear] later") — one Sword
# (Weapon), Helm (Head), and Armor (Body) per tier 1-7, spanning roughly the same overall
# power growth as the Gu quality ladder over its 7 tiers.

BLACKSMITH_GEAR_STATS = {
    # atk_stat runs at roughly half of str_stat per tier — STR stays a Sword's primary
    # damage stat, but ATK (hit chance, plus a secondary damage role — see combat.py's
    # DAMAGE_PER_ATK) actually grows with weapon tier now instead of being untouched by
    # any craftable gear in the game.
    "Sword": {
        1: {"str_stat": 4, "atk_stat": 2},
        2: {"str_stat": 7, "atk_stat": 4},
        3: {"str_stat": 11, "atk_stat": 6},
        4: {"str_stat": 16, "atk_stat": 8},
        5: {"str_stat": 22, "atk_stat": 11},
        6: {"str_stat": 30, "atk_stat": 15},
        7: {"str_stat": 40, "atk_stat": 20, "crit_chance_pct": 0.05},
    },
    "Helm": {
        1: {"def_stat": 3, "luck_stat": 1},
        2: {"def_stat": 5, "luck_stat": 1},
        3: {"def_stat": 8, "luck_stat": 2},
        4: {"def_stat": 12, "luck_stat": 2},
        5: {"def_stat": 17, "luck_stat": 3},
        6: {"def_stat": 23, "luck_stat": 3},
        7: {"def_stat": 30, "luck_stat": 4},
    },
    "Armor": {
        1: {"hp": 20, "def_stat": 4},
        2: {"hp": 35, "def_stat": 7},
        3: {"hp": 55, "def_stat": 11},
        4: {"hp": 80, "def_stat": 16},
        5: {"hp": 115, "def_stat": 22},
        6: {"hp": 155, "def_stat": 29},
        7: {"hp": 200, "def_stat": 38},
    },
}

BLACKSMITH_GEAR_SLOT_TYPE = {"Sword": "Weapon", "Helm": "Head", "Armor": "Body"}
BLACKSMITH_GEAR_TYPES = list(BLACKSMITH_GEAR_STATS.keys())


def blacksmith_gear_name(gear_type: str, tier: int) -> str:
    return f"{gear_type} (T{tier})"


def _register_blacksmith_gear():
    for gear_type, tiers in BLACKSMITH_GEAR_STATS.items():
        for tier, stat_bonuses in tiers.items():
            item_name = blacksmith_gear_name(gear_type, tier)
            EQUIPMENT[item_name] = Equipment(
                name=item_name,
                slot_type=BLACKSMITH_GEAR_SLOT_TYPE[gear_type],
                rank=f"T{tier}",
                description=f"A Tier {tier} {gear_type.lower()}, forged by a Blacksmith. {describe_stat_bonuses(stat_bonuses)}.",
                stat_bonuses=dict(stat_bonuses),
            )


_register_blacksmith_gear()

# Granted (and auto-equipped into their matching slot) once a character is confirmed via /join.
# No "manual" entry here on purpose — a starting character gets a real assembled manual in
# their PRIMARY slot instead of the old legacy catalog item (see GameManager.confirm_
# character), so the legacy "manual" slot_key starts and stays empty rather than being
# permanently stuck showing a superseded Rank F+ item on every equipment/profile screen.
STARTER_EQUIPMENT = {
    "head": "Worn Headband",
    "body": "Worn Linen Clothes",
    "weapon": "Rusty Practice Sword",
    "ring_1": "Rusty Jade Ring",
    "artifact_1": "Basic Flying Artifact",
}
