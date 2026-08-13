"""
Black Heaven's 15 Rank 7/8 Unique Gu (see game/canon_gu.py, game/black_heaven.py) -- the
user's own full name/path/effect-idea list (6 at gu_rank 8, 9 at gu_rank 7), translated into
the existing canon-Gu architecture the same way White Heaven's own 20 were. Every entry has
drop_weight=0 (never eligible in canon_gu.roll_canon_gu_drop's normal weighted roll) --
reachable ONLY through Search Black Heaven's bubble board (see game/black_heaven_search_view.py,
GameManager.roll_black_heaven_bubble_gu / roll_black_heaven_battle_bonus_gu), never through a
per-kill roll the way White Heaven's own 20 are (see BLACK_HEAVEN_CANON_GU_NAMES below, kept
distinct from "any drop_weight==0 Gu" so no other batch's Uniques leak into this one's rolls).

Mechanical scope: same pragmatic approach as White Heaven's own 20 -- 13 of the 15 get a real,
already-wired passive (11 reusing an existing stat_bonuses key outright, 2 via the new
freeze_chance_pct key -- see hunt.py's _do_attack / team_battle.py's _resolve_round, the one
new infra extension this batch needed; a monster_frozen_rounds/frozen_rounds mechanism already
existed end to end for Frostbinder's own class ability, this just makes it Gu-grantable too).
Black Heaven Star Gu and Falling Star Gu are honestly scoped as flavor-only -- their described
multi-turn-charge-then-detonate mechanics are the same genuinely-new subsystem White Heaven's
own Nine Heavens Thunder Gu / Falling Heaven Star Gu already deferred, so they fall through to
canon_gu._stat_bonuses_for_star's existing generic role-power fallback.

canon_gu.py's own _FUNCTIONAL_STAT_KEY only supports ONE (stat_key, kind) pair per Gu name, not
a multi-key split -- White Heaven's own Seven-Colored Heavenly Light Gu already hit this same
limit (its 3-effect flavor text resolves to a single real dodge_chance_pct key). Two of this
batch's Gu have a similar two-effect description; each picks the more literal/central real
mechanic as its single key and honestly flags the other half as flavor-only in effect_text,
same convention: Soul Devouring Gu (lifesteal_percent real, armor-penetration flavor-only) and
Nightmare Web Gu (ignore_attack_chance real -- an exact match for "negate next attack that
hits" -- freeze/delay flavor-only).

Star-curve magnitudes sit close to White Heaven's own range (see canon_gu_white_heaven.py's
module docstring for that calibration approach), nudged slightly higher on a few top entries to
reflect "even more dangerous" -- still a first pass pending real player feedback, not a final
balance number.
"""

from ..equipment import GU_QUALITY_ORDER

# -- The 15 Gu (canon_gu.CANON_GU's exact field shape) --------------------------------------
BLACK_HEAVEN_CANON_GU = [
    {
        "name": "Endless Night Gu", "gu_rank": 8, "path": "Dark", "role": "Defense", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1200, "is_passive": True,
        "description": "Wraps the user in a pocket of Black Heaven's own starless dark, thick enough that even a direct hit has to find them first.",
        "effect_text": "Creates a domain that reduces enemy accuracy and buffs the user's own evasion.",
    },
    {
        "name": "Soul Devouring Gu", "gu_rank": 8, "path": "Soul", "role": "Attack", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1300, "is_passive": True,
        "description": "Feeds directly on whatever's left of an opponent's soul once their defenses stop mattering.",
        "effect_text": "Heals the user from damage dealt (flavor -- also meant to damage straight through defense, not wired up separately from the heal).",
    },
    {
        "name": "Black Heaven Star Gu", "gu_rank": 8, "path": "Star", "role": "Attack", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1350, "is_passive": False,
        "description": "Marks a target the way Black Heaven's own dead stars are marked -- quietly, and only once, right before everything happens at once.",
        "effect_text": "Builds Star Marks per attack, then detonates them for huge burst damage on the 5th attack (flavor -- the charge mechanic itself isn't wired up yet).",
    },
    {
        "name": "Void Burial Gu", "gu_rank": 8, "path": "Dark", "role": "Control", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1250, "is_passive": True,
        "description": "Buries an opponent in a pocket of dead space just long enough for them to remember they were mid-swing.",
        "effect_text": "A real chance to freeze an enemy solid on hit, delaying their next action.",
    },
    {
        "name": "Ten Thousand Venoms Gu", "gu_rank": 8, "path": "Poison", "role": "Attack", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1200, "is_passive": True,
        "description": "Carries every venom Black Heaven's own dead things ever produced, layered until the count stops mattering.",
        "effect_text": "Applies a lingering poison DoT (flavor -- also meant to worsen enemy healing and defense, not wired up yet).",
    },
    {
        "name": "Night Sky Gu", "gu_rank": 8, "path": "Star", "role": "Permanent", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1450, "is_passive": True,
        "description": "A sliver of Black Heaven's own starless sky, worn close enough that the user starts to carry its weight.",
        "effect_text": "Amplifies total damage output on top of every other bonus -- the closest thing this list has to raw stat amplification.",
    },
    {
        "name": "Shadowless Perception Gu", "gu_rank": 7, "path": "Information", "role": "Tracking", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1000, "is_passive": True,
        "description": "Sees the way something already used to a lightless world sees -- shapes first, then whatever they're hiding.",
        "effect_text": "A large luck bonus that causes hidden inheritances and secret finds to appear more often.",
    },
    {
        "name": "Dark Venom Gu", "gu_rank": 7, "path": "Poison", "role": "Attack", "rarity": "Unique",
        "drop_weight": 0, "base_power": 950, "is_passive": True,
        "description": "A venom that doesn't peak on contact -- it just keeps compounding for as long as the fight keeps going.",
        "effect_text": "Poison damage that scales higher the longer combat continues.",
    },
    {
        "name": "Astral Wind Gu", "gu_rank": 7, "path": "Wind", "role": "Attack", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1050, "is_passive": True,
        "description": "Moves fast enough between stars that a single swing rarely arrives as just one hit.",
        "effect_text": "Fast, armor-penetrating strikes (flavor -- the doubled attack-chance half of this isn't wired up separately).",
    },
    {
        "name": "Soul Shackle Gu", "gu_rank": 7, "path": "Soul", "role": "Defense", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1000, "is_passive": True,
        "description": "Chains an opponent's own soul just tightly enough to slow whatever they're about to do next.",
        "effect_text": "Reduces incoming damage via a real defense bonus (flavor -- also meant to disable part of enemy lifesteal, not wired up yet).",
    },
    {
        "name": "Black Cloud Gu", "gu_rank": 7, "path": "Cloud", "role": "Defense", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1000, "is_passive": True,
        "description": "A cloud field dark enough to blur the user's own outline, let alone anyone standing near them.",
        "effect_text": "A defensive field that lowers enemy accuracy (flavor -- sharing the protection with allies isn't wired up yet).",
    },
    {
        "name": "Falling Star Gu", "gu_rank": 7, "path": "Star", "role": "Attack", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1100, "is_passive": False,
        "description": "A star that's already falling toward one specific point -- it just hasn't decided when to actually land.",
        "effect_text": "A delayed strike that gets stronger each turn charged, detonating on the 5th attack (flavor -- the charge mechanic itself isn't wired up yet).",
    },
    {
        "name": "Nightmare Web Gu", "gu_rank": 7, "path": "Dream", "role": "Control", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1050, "is_passive": True,
        "description": "Spins a web out of whatever an opponent was most afraid was about to hit them.",
        "effect_text": "A real chance to negate the next attack that hits the user (flavor -- delaying it instead, rather than negating it outright, isn't separately modeled).",
    },
    {
        "name": "Night Predator Gu", "gu_rank": 7, "path": "Transformation", "role": "Attack", "rarity": "Unique",
        "drop_weight": 0, "base_power": 1000, "is_passive": True,
        "description": "Shifts into something that hunts the way every apex predator in Black Heaven already learned to -- go for whatever's already hurt.",
        "effect_text": "Bonus damage against injured enemies (flavor -- true growing stacks rather than a flat bonus aren't separately modeled).",
    },
    {
        "name": "Dark Reflection Gu", "gu_rank": 7, "path": "Dark", "role": "Defense", "rarity": "Unique",
        "drop_weight": 0, "base_power": 950, "is_passive": True,
        "description": "A mirror-black ward that never quite decides whether it's protecting the user or punishing whoever's attacking them.",
        "effect_text": "Reflects a percentage of incoming damage back at the attacker.",
    },
]

BLACK_HEAVEN_CANON_GU_NAMES = [gu["name"] for gu in BLACK_HEAVEN_CANON_GU]

# -- Real, already-wired passives (13 of 15 -- see module docstring for the 2 exceptions) ---
BLACK_HEAVEN_FUNCTIONAL_STAT_KEY = {
    "Endless Night Gu": ("dodge_chance_pct", "percent"),
    "Soul Devouring Gu": ("lifesteal_percent", "percent"),
    "Void Burial Gu": ("freeze_chance_pct", "percent"),
    "Ten Thousand Venoms Gu": ("fire_burn_damage_pct", "percent"),
    "Night Sky Gu": ("total_damage_pct", "percent"),
    "Shadowless Perception Gu": ("clue_chance_bonus_pct", "percent"),
    "Dark Venom Gu": ("fire_burn_damage_pct", "percent"),
    "Astral Wind Gu": ("armor_penetration_pct", "percent"),
    "Soul Shackle Gu": ("def_stat", "flat"),
    "Black Cloud Gu": ("dodge_chance_pct", "percent"),
    "Nightmare Web Gu": ("ignore_attack_chance", "percent"),
    "Night Predator Gu": ("execute_damage_pct", "percent"),
    "Dark Reflection Gu": ("retaliation_damage_pct", "percent"),
}

# name -> [star 1..7 value] -- see module docstring for the calibration approach.
BLACK_HEAVEN_FUNCTIONAL_EFFECT_BY_STAR = {
    "Endless Night Gu": [7, 8, 9, 11, 13, 16, 18],
    "Soul Devouring Gu": [11, 12, 14, 17, 20, 23, 27],
    "Void Burial Gu": [8, 9, 11, 13, 15, 18, 21],
    "Ten Thousand Venoms Gu": [18, 21, 24, 28, 32, 37, 43],
    "Night Sky Gu": [13, 15, 18, 21, 25, 29, 34],
    "Shadowless Perception Gu": [8, 9, 11, 13, 15, 18, 21],
    "Dark Venom Gu": [14, 16, 19, 22, 26, 30, 35],
    "Astral Wind Gu": [7, 8, 10, 12, 14, 16, 19],
    "Soul Shackle Gu": [6, 7, 8, 9, 10, 12, 14],
    "Black Cloud Gu": [5, 6, 7, 8, 10, 12, 14],
    "Nightmare Web Gu": [4, 5, 6, 7, 9, 11, 13],
    "Night Predator Gu": [9, 10, 12, 14, 17, 20, 23],
    "Dark Reflection Gu": [7, 8, 10, 12, 14, 16, 19],
}

assert len(BLACK_HEAVEN_CANON_GU) == 15
assert set(BLACK_HEAVEN_FUNCTIONAL_STAT_KEY) == set(BLACK_HEAVEN_FUNCTIONAL_EFFECT_BY_STAR)
assert all(len(v) == len(GU_QUALITY_ORDER) for v in BLACK_HEAVEN_FUNCTIONAL_EFFECT_BY_STAR.values())
