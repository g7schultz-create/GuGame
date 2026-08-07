"""
/region -- a mortal-realm character's chosen geographic world location, letting them lean
into one of five playstyles (inheritance-hunting, tougher fights, richer materials, richer
trade goods, or richer manuals). Deliberately separate from search_data.REGIONS, which is
an unrelated per-realm DANGER TIER used by /search (see search_data.py's own module
docstring) -- a player's world_region and their /search region are two different axes.

Eligibility: only characters at Nascent Soul (realms.GREAT_REALMS index 3) or below can pick
one of these five mortal regions -- "later there will be immortal areas" above that, not yet
built. A character above the cap simply can't set/hold a world_region (see
GameManager.get_world_region_status's "eligible" flag); existing higher-realm characters are
unaffected since the column defaults to NULL.
"""

from dataclasses import dataclass

MAX_GREAT_REALM_INDEX_FOR_MORTAL_REGIONS = 3  # Nascent Soul and below (realms.GREAT_REALMS)

# How often a character may switch world regions -- long enough that "region-hop for a free
# roll on every action type" isn't a viable strategy, short enough that a genuine playstyle
# change doesn't feel like a punishment. TESTING: shortened like every other cooldown this
# session (/mine, /gather, /explore) -- revert to something like 6 * 3600 once testing is done.
REGION_CHANGE_COOLDOWN_SECONDS = 15 * 60


@dataclass
class WorldRegion:
    key: str
    name: str
    emoji: str
    tagline: str
    description: str


WORLD_REGIONS = {
    "southern_border": WorldRegion(
        key="southern_border",
        name="Southern Border",
        emoji="🗺️",
        tagline="Chance to find inheritances on any action.",
        description=(
            "A lawless frontier riddled with forgotten ruins. Every /mine, /gather, /explore, "
            "/hunt, and /raid carries a real chance to turn up a special discovery here, and "
            "the odds lean hardest toward inheritances specifically."
        ),
    ),
    "northern_plains": WorldRegion(
        key="northern_plains",
        name="Northern Plains",
        emoji="🐺",
        tagline="Tougher beasts in /hunt and /raid, with bigger loot to match.",
        description=(
            "Open, wind-scoured grassland ruled by packs of unusually strong beasts. Every "
            "/hunt and /raid you take here spawns a stronger-than-normal monster with a "
            "noticeably richer drop table."
        ),
    ),
    "eastern_sea": WorldRegion(
        key="eastern_sea",
        name="Eastern Sea",
        emoji="🌊",
        tagline="The richest region for materials -- and hoard-guardian monsters.",
        description=(
            "Storm-wracked coastline and reef, the richest region for raw materials. /mine and "
            "/gather yield more here, and /hunt or /raid occasionally turns up a stronger beast "
            "guarding a real hoard of herbs, ore, and monster materials."
        ),
    ),
    "western_desert": WorldRegion(
        key="western_desert",
        name="Western Desert",
        emoji="🏜️",
        tagline="Rich in trade -- more spirit stones, ink, and dust.",
        description=(
            "Endless dunes dotted with caravan routes and sun-bleached trading posts. Rewards "
            "lean toward spirit stones, manual ink, and insight dust here, and /hunt or /raid "
            "occasionally turns up a stronger beast guarding a hoard of spirit stones."
        ),
    ),
    "central_continent": WorldRegion(
        key="central_continent",
        name="Central Continent",
        emoji="🏯",
        tagline="The most prosperous and refined region -- more manuals, pages, ink, and dust.",
        description=(
            "The cultivation world's cultural heartland. Manual pages, ink, and insight dust "
            "drop more often here, and /hunt or /raid occasionally turns up a stronger beast "
            "guarding a completed manual's worth of pages."
        ),
    ),
}

WORLD_REGION_ORDER = ["southern_border", "northern_plains", "eastern_sea", "western_desert", "central_continent"]


def is_eligible(great_realm_index: int) -> bool:
    return great_realm_index <= MAX_GREAT_REALM_INDEX_FOR_MORTAL_REGIONS


# -- Tunable bonus constants, one bundle per region -- GameManager's region_* helpers read
# these; see manager.py for exactly where each key plugs in. Every region gets an
# "action_discovery_chance" + "discovery_type_weights" pair (the "special inheritances,
# battlefields, and dream realms found when taking actions in these zones" passive shared by
# all five), plus whatever else that region's own passive described in the request adds.
REGION_BONUSES = {
    "southern_border": {
        "action_discovery_chance": 0.10,
        "discovery_type_weights": {"inheritance": 4.0, "battlefield": 1.0, "region_dream_realm": 1.0},
    },
    "northern_plains": {
        "action_discovery_chance": 0.04,
        "discovery_type_weights": {"inheritance": 1.0, "battlefield": 1.0, "region_dream_realm": 1.0},
        "monster_stat_multiplier": 1.20,
        "loot_chance_bonus_pct": 0.30,
    },
    "eastern_sea": {
        "action_discovery_chance": 0.04,
        "discovery_type_weights": {"inheritance": 1.0, "battlefield": 1.0, "region_dream_realm": 1.0},
        "gather_yield_multiplier": 1.25,
        "reward_material_multiplier": 1.25,
        "hoard_chance": 0.15,
        "hoard_stat_multiplier": 1.35,
    },
    "western_desert": {
        "action_discovery_chance": 0.04,
        "discovery_type_weights": {"inheritance": 1.0, "battlefield": 1.0, "region_dream_realm": 1.0},
        "explore_stone_multiplier": 1.30,
        "reward_stone_multiplier": 1.25,
        "reward_ink_dust_multiplier": 1.25,
        "hoard_chance": 0.15,
        "hoard_stat_multiplier": 1.35,
    },
    "central_continent": {
        "action_discovery_chance": 0.04,
        "discovery_type_weights": {"inheritance": 1.0, "battlefield": 1.0, "region_dream_realm": 1.0},
        "reward_ink_dust_multiplier": 1.20,
        "reward_page_bonus_chance": 0.30,
        "hoard_chance": 0.15,
        "hoard_stat_multiplier": 1.35,
    },
}


# -- Region-found inheritance rank tier (distinct from search_data's normal player-rank-
# derived discovery rank) -- "all up to luck and rank 1-6 items with rank 6 being 1/1000."
# Weights sum to 1000 so rank 6's weight of 1 IS exactly 1/1000 before any luck shift; luck
# only ever redistributes weight among ranks 1-5 (same convention as gathering.roll_tier),
# never touching rank 6's fixed 1-in-1000 floor -- luck helps you reach the jackpot rank
# faster, it doesn't ever guarantee it.
REGION_INHERITANCE_RANK_WEIGHTS = [(500, 1), (250, 2), (140, 3), (70, 4), (39, 5), (1, 6)]
REGION_INHERITANCE_LUCK_WEIGHT_SHIFT_PER_POINT = 2
REGION_INHERITANCE_MIN_RANK1_WEIGHT = 150


def roll_region_inheritance_rank(luck_stat: int, rng) -> int:
    weights = [w for w, _ in REGION_INHERITANCE_RANK_WEIGHTS]
    ranks = [r for _, r in REGION_INHERITANCE_RANK_WEIGHTS]
    shift = min(weights[0] - REGION_INHERITANCE_MIN_RANK1_WEIGHT, REGION_INHERITANCE_LUCK_WEIGHT_SHIFT_PER_POINT * max(0, luck_stat))
    if shift > 0:
        rest_total = sum(weights[1:-1])  # redistribute across ranks 2-5 only
        adjusted = [weights[0] - shift]
        for w in weights[1:-1]:
            adjusted.append(w + shift * (w / rest_total))
        adjusted.append(weights[-1])  # rank 6 stays exactly 1/1000, untouched by luck
        weights = adjusted
    return rng.choices(ranks, weights=weights, k=1)[0]
