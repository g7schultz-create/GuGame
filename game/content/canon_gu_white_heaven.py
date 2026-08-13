"""
White Heaven's 20 Rank 8 Unique Gu (see game/canon_gu.py, game/white_heaven.py) -- the
user's own full name/path/effect-idea list, translated into the existing canon-Gu
architecture rather than a new subsystem. Every entry has drop_weight=0 (never eligible in
canon_gu.roll_canon_gu_drop's normal weighted roll, same convention as the 2 pre-existing
Uniques Spring Autumn Cicada/Fortune Rivalling Heaven Gu) -- reachable ONLY through
GameManager.roll_white_heaven_bonus_gu's own separate, White-Heaven-kill-only roll (1/3000
per hunt kill, 1/1000 per raid participant -- see WHITE_HEAVEN_HUNT_BONUS_GU_CHANCE/
WHITE_HEAVEN_RAID_BONUS_GU_CHANCE) and exploration.roll_white_heaven_explore_bonus_gu's own
1/3000 per /explore find (see WHITE_HEAVEN_CANON_GU_NAMES below, kept distinct from "any
drop_weight==0 Gu" so the 2 pre-existing Uniques are never eligible for any of these rolls
either).

Mechanical scope (see the approved plan's own per-Gu table): everything routes through the
existing generic stat_bonuses/SPECIAL_BONUS_KEYS pool -- 18 of the 20 get a real,
already-wired passive (11 reusing an existing key outright, 7 via one of two small,
precedented infra extensions: the new dodge_cap_bonus_pct key, or extending HuntView/
TeamBattleEngine._trait_bonus to also read the equipped Gu, unlocking retaliation_damage_pct
through a Gu for the first time). Nine Heavens Thunder Gu and Falling Heaven Star Gu are
honestly scoped as flavor-only (their described multi-turn-charge mechanics are genuinely
new subsystems, out of scope here) -- they fall through to canon_gu._stat_bonuses_for_star's
existing generic role-power fallback, the same "coming soon" precedent 19 of the 26
pre-existing canon Gu already use. Heavenly Cloud Sea Gu's party-wide 4-target essence
sharing is similarly descoped from its otherwise-real self-heal passive.

Star-curve magnitudes (_FUNCTIONAL_EFFECT_BY_STAR below) start at roughly 1.3-1.8x the
richest existing canon Gu's own top-star numbers (Heavenly Essence Treasure Lotus's
essence_regen_pct: 12/13/15/17/19/22/25) -- there's no gu_rank 8 precedent to extrapolate
from, so treat these as a first pass pending real player feedback, not a final balance
number, same as every other numeric first-pass in this feature.
"""

from ..equipment import GU_QUALITY_ORDER

# -- The 20 Gu (canon_gu.CANON_GU's exact field shape) --------------------------------------
WHITE_HEAVEN_CANON_GU = [
    {
        "name": "Heavenly Sun Gu", "gu_rank": 8, "path": "Fire", "role": "Attack", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1250, "is_passive": True,
        "description": "A sliver of White Heaven's own captured sunfire, sealed into a Gu that burns hotter the longer a fight drags on.",
        "effect_text": "Massive radiant damage; applies a lingering Scorch and weakens whatever it burns.",
    },
    {
        "name": "Nine Heavens Thunder Gu", "gu_rank": 8, "path": "Lightning", "role": "Attack", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1300, "is_passive": False,
        "description": "Calls down heavenly lightning that never quite finishes discharging -- it just keeps building toward something worse.",
        "effect_text": "Repeated hits build Tribulation Marks toward a huge final strike after 5 turns (flavor -- the charge mechanic itself isn't wired up yet).",
    },
    {
        "name": "Boundless Cloud Gu", "gu_rank": 8, "path": "Cloud", "role": "Defense", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1150, "is_passive": True,
        "description": "Wraps the user in a personal cloud domain, thick enough to blur both silhouette and footing.",
        "effect_text": "Increased dodge, movement, and damage reduction.",
    },
    {
        "name": "Heaven Crossing Gu", "gu_rank": 8, "path": "Space", "role": "Movement", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1200, "is_passive": True,
        "description": "Folds the space directly ahead of a killing blow, so the user is simply somewhere else when it lands.",
        "effect_text": "Teleportation / instant movement; in combat, an additional chance to completely evade an attack.",
    },
    {
        "name": "Immemorial Heavenly Wind Gu", "gu_rank": 8, "path": "Wind", "role": "Attack", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1200, "is_passive": True,
        "description": "A wind that predates every sect currently arguing about who first tamed it.",
        "effect_text": "Extremely high speed and armor-penetrating damage.",
    },
    {
        "name": "Primordial Heavenly Qi Gu", "gu_rank": 8, "path": "Qi", "role": "Resource", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1150, "is_passive": True,
        "description": "Circulates a thread of qi old enough to remember when White Heaven itself was still forming.",
        "effect_text": "Restores essence, increases max essence, and empowers Killer Moves.",
    },
    {
        "name": "Heavenly Sight Gu", "gu_rank": 8, "path": "Light", "role": "Tracking", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1100, "is_passive": True,
        "description": "Sees an opponent the way White Heaven's own light-path zones see everything -- all the way through.",
        "effect_text": "Reveals enemy stats in the hunt/raid embed while equipped, plus a real bonus to landing critical hits on exposed weak points.",
    },
    {
        "name": "Heaven's Wing Gu", "gu_rank": 8, "path": "Wind", "role": "Movement", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1150, "is_passive": True,
        "description": "Grants real flight, if only for as long as it takes to close -- or cross -- the distance that matters.",
        "effect_text": "Faster White Heaven travel time, plus speed, evasion, and bonus damage on the first attack of a fight.",
    },
    {
        "name": "Seven-Colored Heavenly Light Gu", "gu_rank": 8, "path": "Light", "role": "Support", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1200, "is_passive": True,
        "description": "Cycles through every color White Heaven's aurora zones ever produced, never settling on just one.",
        "effect_text": "Randomly cycles through several powerful elemental/light buffs (flavor -- resolves as a strong, steady evasion buff mechanically).",
    },
    {
        "name": "Great Sun Furnace Gu", "gu_rank": 8, "path": "Fire", "role": "Utility", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1150, "is_passive": True,
        "description": "A portable furnace stoked by the same captured sunfire Heavenly Sun Gu carries, tuned for refinement instead of ruin.",
        "effect_text": "Burns enemies, and improves Gu refinement and material quality.",
    },
    {
        "name": "Nine Cloud Palace Gu", "gu_rank": 8, "path": "Cloud", "role": "Defense", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1200, "is_passive": True,
        "description": "Raises a palace of cloud-layers around the user, each one built to absorb exactly one more hit than the last.",
        "effect_text": "A defensive Gu that creates layered shields, reducing damage from beast-type attackers especially.",
    },
    {
        "name": "Tribulation Lightning Gu", "gu_rank": 8, "path": "Lightning", "role": "Attack", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1250, "is_passive": True,
        "description": "Strikes hardest at whatever least expects to be struck by something its own size.",
        "effect_text": "Increasing damage scales against higher-realm enemies and bosses.",
    },
    {
        "name": "Falling Heaven Star Gu", "gu_rank": 8, "path": "Star", "role": "Attack", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1300, "is_passive": False,
        "description": "Calls down a star that's already falling -- the only question is how long the user makes it wait.",
        "effect_text": "A massive star strike, stronger after several turns of charging (flavor -- the charge mechanic itself isn't wired up yet).",
    },
    {
        "name": "Void Cloud Gu", "gu_rank": 8, "path": "Space", "role": "Defense", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1200, "is_passive": True,
        "description": "Spatial clouds that don't just hide the user -- they quietly lie to anything trying to aim at them.",
        "effect_text": "Distorts enemy targeting, raising dodge chance genuinely past the normal cap.",
    },
    {
        "name": "Heavenly Reflection Gu", "gu_rank": 8, "path": "Light", "role": "Defense", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1150, "is_passive": True,
        "description": "A mirror-bright ward that never quite decides whether it's protecting the user or punishing whoever's attacking them.",
        "effect_text": "Reflects a percentage of incoming damage back at the attacker.",
    },
    {
        "name": "Yang Extremity Gu", "gu_rank": 8, "path": "Yin-Yang", "role": "Attack", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1200, "is_passive": True,
        "description": "Burns with pure Yang at its most extreme -- the kind that heals the one wielding it just by being spent.",
        "effect_text": "Converts Yang energy into damage, healing, and resistance.",
    },
    {
        "name": "White Heaven Escape Gu", "gu_rank": 8, "path": "Space", "role": "Rebirth", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1150, "is_passive": True,
        "description": "A last-resort fold in space, tuned specifically for the moment a fight was never actually winnable.",
        "effect_text": "A near-perfect escape Gu -- can break pursuit and meaningfully reduces qi lost even when a fight is lost.",
    },
    {
        "name": "World-Crossing Wind Gu", "gu_rank": 8, "path": "Wind", "role": "Utility", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1150, "is_passive": True,
        "description": "A wind that's crossed enough of the world to stop caring which direction it's blowing.",
        "effect_text": "Reduces cooldowns and lets attacks strike multiple targets.",
    },
    {
        "name": "Heavenly Cloud Sea Gu", "gu_rank": 8, "path": "Cloud", "role": "Support", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1200, "is_passive": True,
        "description": "Spreads a field of White Heaven's own cloud sea, thick enough to carry qi back to whoever's standing in it.",
        "effect_text": "Continuously restores the user's own essence (flavor -- picking up to 4 players to share it with isn't wired up yet).",
    },
    {
        "name": "White Heaven Sovereign Gu", "gu_rank": 8, "path": "Heaven", "role": "Permanent", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1400, "is_passive": True,
        "description": "A domain-type Gu that doesn't so much fight for the user as declare, briefly, that the user IS the domain.",
        "effect_text": "Amplifies total damage output on top of every other bonus -- the closest thing this list has to raw stat amplification.",
    },
]

WHITE_HEAVEN_CANON_GU_NAMES = [gu["name"] for gu in WHITE_HEAVEN_CANON_GU]

# -- Real, already-wired passives (18 of 20 -- see module docstring for the 2 exceptions) ---
WHITE_HEAVEN_FUNCTIONAL_STAT_KEY = {
    "Heavenly Sun Gu": ("fire_burn_damage_pct", "percent"),
    "Boundless Cloud Gu": ("dodge_chance_pct", "percent"),
    "Heaven Crossing Gu": ("ignore_attack_chance", "percent"),
    "Immemorial Heavenly Wind Gu": ("armor_penetration_pct", "percent"),
    "Primordial Heavenly Qi Gu": ("essence_regen_pct", "percent"),
    "Heavenly Sight Gu": ("crit_chance_pct", "percent"),
    "Heaven's Wing Gu": ("dodge_chance_pct", "percent"),
    "Seven-Colored Heavenly Light Gu": ("dodge_chance_pct", "percent"),
    "Great Sun Furnace Gu": ("crafting_success_pct", "percent"),
    "Nine Cloud Palace Gu": ("beast_damage_reduction_pct", "percent"),
    "Tribulation Lightning Gu": ("boss_damage_bonus_pct", "percent"),
    "Void Cloud Gu": ("dodge_cap_bonus_pct", "percent"),
    "Heavenly Reflection Gu": ("retaliation_damage_pct", "percent"),
    "Yang Extremity Gu": ("lifesteal_percent", "percent"),
    "White Heaven Escape Gu": ("death_qi_loss_reduction_pct", "percent"),
    "World-Crossing Wind Gu": ("cooldown_reduction_pct", "percent"),
    "Heavenly Cloud Sea Gu": ("essence_regen_pct", "percent"),
    "White Heaven Sovereign Gu": ("total_damage_pct", "percent"),
}

# name -> [star 1..7 value] -- see module docstring for the calibration approach.
WHITE_HEAVEN_FUNCTIONAL_EFFECT_BY_STAR = {
    "Heavenly Sun Gu": [20, 23, 26, 30, 35, 40, 46],
    "Boundless Cloud Gu": [6, 7, 8, 10, 12, 14, 16],
    "Heaven Crossing Gu": [5, 6, 7, 8, 10, 12, 14],
    "Immemorial Heavenly Wind Gu": [8, 9, 11, 13, 15, 18, 21],
    "Primordial Heavenly Qi Gu": [16, 18, 21, 24, 28, 33, 38],
    "Heavenly Sight Gu": [5, 6, 7, 8, 10, 12, 14],
    "Heaven's Wing Gu": [6, 7, 8, 10, 12, 14, 16],
    "Seven-Colored Heavenly Light Gu": [6, 7, 8, 10, 12, 14, 16],
    "Great Sun Furnace Gu": [10, 12, 14, 16, 19, 22, 26],
    "Nine Cloud Palace Gu": [14, 16, 18, 21, 25, 29, 34],
    "Tribulation Lightning Gu": [14, 16, 18, 21, 25, 29, 34],
    "Void Cloud Gu": [4, 5, 6, 7, 8, 10, 12],
    "Heavenly Reflection Gu": [8, 9, 11, 13, 15, 18, 21],
    "Yang Extremity Gu": [10, 11, 13, 15, 18, 21, 25],
    "White Heaven Escape Gu": [16, 18, 21, 24, 28, 33, 38],
    "World-Crossing Wind Gu": [12, 14, 16, 19, 22, 26, 30],
    "Heavenly Cloud Sea Gu": [14, 16, 18, 21, 25, 29, 34],
    "White Heaven Sovereign Gu": [12, 14, 16, 19, 22, 26, 30],
}

assert len(WHITE_HEAVEN_CANON_GU) == 20
assert set(WHITE_HEAVEN_FUNCTIONAL_STAT_KEY) == set(WHITE_HEAVEN_FUNCTIONAL_EFFECT_BY_STAR)
assert all(len(v) == len(GU_QUALITY_ORDER) for v in WHITE_HEAVEN_FUNCTIONAL_EFFECT_BY_STAR.values())
