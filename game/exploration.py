"""
/explore's loot table: a single weighted rarity-band roll (not independent per-entry rolls
like monster drops — you find ONE thing per trip), then a random pick within that band's
pool. Common is deliberately very likely; Mythic (the jackpot band — 100,000 spirit
stones, a Mythic/"Tier 6" quality Gu, or the one Legendary weapon in the game) stays
deliberately rare even at max Explorer rank, but Epic/Legendary — where Tier 8 materials,
rarer Gu, and manual pages actually live — now grow dramatically with Explorer investment
instead of barely moving.

2026-08-18, explicit request ("explorer levels matter a lot more... t8 resources much more
often / gu and manual pages"): the old redistribution split whatever weight Explorer rank
shifted off Common PROPORTIONALLY to each band's own existing weight — since Uncommon already
held the lion's share of the non-Common pool (250 of 400), nearly all of it landed there
regardless of rank, and Legendary/Mythic (weight 9/1) barely moved even at max rank (0.9% ->
1.03%, 0.1% -> 0.11%). Replaced with a fixed target allocation (REDISTRIBUTION_SHARE below)
that deliberately weights Epic/Legendary heaviest, plus a much bigger per-rank shift
(WEIGHT_SHIFT_PER_RANK 8 -> 30) — Legendary now reaches ~6% and Epic ~11% at max rank (was
~1%/4.6%), a real, keenly felt payoff for Explorer investment. Manual pages are also new here
(previously never obtainable via /explore at all) and White Heaven's own bonus Gu roll now
scales with rank too (see white_heaven_explore_bonus_gu_chance) instead of a flat 0.1%.
"""

import random

from . import items, manual_data
from .content.canon_gu_white_heaven import WHITE_HEAVEN_CANON_GU_NAMES
from .equipment import GU_FAMILIES, gu_item_name

# (band, weight) — sums to 1000; Mythic = 1/1000 = 0.1% before any Explorer rank bonus.
EXPLORE_BANDS = [
    ("Common", 600),
    ("Uncommon", 250),
    ("Rare", 100),
    ("Epic", 40),
    ("Legendary", 9),
    ("Mythic", 1),
]

# Weight shifted off Common per Explorer rank (and, separately, per point of Luck), then
# redistributed using REDISTRIBUTION_SHARE below (NOT proportional to each band's own
# existing weight — see this module's docstring for why that undersold Epic/Legendary badly).
# Capped so Common never drops below 50 weight (5%), even stacking max rank with a high Luck stat.
WEIGHT_SHIFT_PER_RANK = 30
LUCK_WEIGHT_SHIFT_PER_POINT = 2
MIN_COMMON_WEIGHT = 50

# Fixed target split of whatever weight gets shifted off Common — sums to 1.0. Epic and
# Legendary get the biggest shares since that's where Tier 8 materials (White Heaven pools),
# rarer Gu, and manual pages live; Mythic gets only a small slice so the true jackpot stays
# rare even at max Explorer rank, matching this module's own "almost impossible" intent.
REDISTRIBUTION_SHARE = {"Uncommon": 0.15, "Rare": 0.20, "Epic": 0.35, "Legendary": 0.25, "Mythic": 0.05}


def _weighted_bands(explorer_rank: int, luck_stat: int = 0):
    names = [name for name, _ in EXPLORE_BANDS]
    weights = [w for _, w in EXPLORE_BANDS]
    total_shift = WEIGHT_SHIFT_PER_RANK * explorer_rank + LUCK_WEIGHT_SHIFT_PER_POINT * max(0, luck_stat)
    shift = min(weights[0] - MIN_COMMON_WEIGHT, total_shift)
    if shift <= 0:
        return names, weights
    adjusted = [weights[0] - shift] + [w + shift * REDISTRIBUTION_SHARE[name] for name, w in zip(names[1:], weights[1:])]
    return names, adjusted


def _stones(lo: int, hi: int) -> dict:
    return {"stones": random.randint(lo, hi), "item_name": None, "quantity": 0}


def _item(item_name: str, lo: int, hi: int) -> dict:
    return {"stones": 0, "item_name": item_name, "quantity": random.randint(lo, hi)}


def _gu(quality: str) -> dict:
    family = random.choice(list(GU_FAMILIES.keys()))
    return {"stones": 0, "item_name": gu_item_name(family, quality), "quantity": 1}


# Manual pages were never obtainable via /explore before -- new 2026-08-18, gated to
# Epic/Legendary (the bands Explorer rank now boosts hardest, see REDISTRIBUTION_SHARE above)
# so Explorer investment is what unlocks them, same as it already gates Gu access starting at
# Rare. Base-game pool stays within ranks reachable outside White Heaven (max rank 7); White
# Heaven's own pool below uses its Rank 8-only pages instead.
_BASE_PAGE_POOL_BY_MAX_RANK = {
    4: [p.page_id for p in manual_data.PAGES.values() if p.rank <= 4],
    6: [p.page_id for p in manual_data.PAGES.values() if p.rank <= 6],
}


def _page(max_rank: int) -> dict:
    pool = _BASE_PAGE_POOL_BY_MAX_RANK[max_rank]
    return {"stones": 0, "item_name": None, "quantity": 0, "page_id": random.choice(pool), "page_quantity": 1}


BAND_POOLS = {
    "Common": lambda: random.choice([
        _stones(5, 15),
        _item("Tier 1 Ore", 1, 2),
        _item("Tier 1 Herb", 1, 2),
        _item("Tier 1 Beast Material", 1, 2),
    ]),
    "Uncommon": lambda: random.choice([
        _stones(15, 40),
        _item("Tier 2 Ore", 1, 2),
        _item("Tier 2 Herb", 1, 2),
        _item("Primeval Essence Crystal", 6, 12),
    ]),
    "Rare": lambda: random.choice([
        _stones(40, 100),
        _item("Tier 3 Ore", 1, 2),
        _item("Tier 3 Herb", 1, 2),
        _gu("Common"),
    ]),
    "Epic": lambda: random.choice([
        _stones(100, 300),
        _item("Tier 4 Ore", 1, 2),
        _item("Tier 4 Herb", 1, 2),
        _gu("Uncommon"),
        _page(4),
    ]),
    "Legendary": lambda: random.choice([
        _stones(300, 1000),
        _item("Tier 5 Ore", 1, 2),
        _item("Tier 5 Herb", 1, 2),
        _gu("Rare"),
        _page(6),
    ]),
    "Mythic": lambda: random.choice([
        {"stones": 100_000, "item_name": None, "quantity": 0},
        _gu("Mythic"),
        {"stones": 0, "item_name": "Heaven-Severing Blade", "quantity": 1},
    ]),
}


# The 10 hand-authored Rank 8 pages (see content/manuals/rank8_pages.py) -- White Heaven
# exclusive, so its own /explore pool is the natural place to make them reachable (matching
# that file's own docstring intent, which named "explore" as one of Rank 8's own reward pools
# even though nothing had actually wired it in until now).
_RANK_8_PAGE_IDS = [p.page_id for p in manual_data.PAGES.values() if p.rank == 8]


def _rank_8_page() -> dict:
    return {"stones": 0, "item_name": None, "quantity": 0, "page_id": random.choice(_RANK_8_PAGE_IDS), "page_quantity": 1}


# White Heaven's own /explore pool (see game/white_heaven.py) -- same 6-band curve/weighting
# as BAND_POOLS above, reskinned around the region's own flavor materials at low/mid bands and
# Tier 8 materials at the top, since /explore doesn't kill anything and Tier 8 Ore/Herb are
# otherwise only reachable via a White Heaven hunt/raid kill (see content/monsters/
# white_heaven.py). Deliberately does NOT reuse base BAND_POOLS' Mythic-band normal-Gu-family
# jackpot or the Heaven-Severing Blade -- White Heaven's own Gu jackpot is the separate
# roll_white_heaven_explore_bonus_gu bonus below instead, mirroring bonus_core/bonus_essence_
# pill's own "independent roll layered on top of the band pick" shape.
WHITE_HEAVEN_BAND_POOLS = {
    "Common": lambda: random.choice([
        _stones(20, 50),
        _item("White Heaven Floating Dust", 1, 3),
        _item("Tier 6 Ore", 1, 2),
        _item("Tier 6 Herb", 1, 2),
    ]),
    "Uncommon": lambda: random.choice([
        _stones(50, 150),
        _item("Aurora-Veined Shard", 1, 2),
        _item("Tier 7 Ore", 1, 2),
        _item("Cloud Sea Mist Vial", 1, 2),
    ]),
    "Rare": lambda: random.choice([
        _stones(150, 400),
        _item("Tier 7 Herb", 1, 2),
        _item("Nine Heavens Lotus Petal", 1, 2),
        _item("Aurora-Veined Shard", 2, 3),
    ]),
    "Epic": lambda: random.choice([
        _stones(400, 1000),
        _item("Tier 8 Ore", 1, 2),
        _item("Primeval Essence Crystal", 15, 30),
        _rank_8_page(),
    ]),
    "Legendary": lambda: random.choice([
        _stones(1000, 3000),
        _item("Tier 8 Herb", 1, 2),
        _item("Tier 8 Beast Material", 1, 2),
        _rank_8_page(),
    ]),
    "Mythic": lambda: random.choice([
        {"stones": 300_000, "item_name": None, "quantity": 0},
        _item("Tier 8 Beast Core", 2, 4),
        _rank_8_page(),
    ]),
}

# A small independent shot at one of the 20 White Heaven canon Gu (see content/
# canon_gu_white_heaven.py) on every White Heaven /explore find -- /explore never kills
# anything, so it needs its own separate roll rather than reusing GameManager.
# roll_white_heaven_bonus_gu (hunt/raid's own per-kill version). Flat per-find chance (not
# band-weighted), same "independent of the main band pick" shape as bonus_core -- now scales
# with Explorer rank too (0.1% at rank 0 up to a capped 1% at max rank) instead of a flat
# number that Explorer investment did nothing for.
WHITE_HEAVEN_EXPLORE_BONUS_GU_CHANCE_BASE = 1 / 1000
WHITE_HEAVEN_EXPLORE_BONUS_GU_CHANCE_PER_RANK = 0.0013
WHITE_HEAVEN_EXPLORE_BONUS_GU_CHANCE_MAX = 1 / 100


def white_heaven_explore_bonus_gu_chance(explorer_rank: int) -> float:
    return min(
        WHITE_HEAVEN_EXPLORE_BONUS_GU_CHANCE_MAX,
        WHITE_HEAVEN_EXPLORE_BONUS_GU_CHANCE_BASE + WHITE_HEAVEN_EXPLORE_BONUS_GU_CHANCE_PER_RANK * explorer_rank,
    )


def roll_white_heaven_explore_bonus_gu(explorer_rank: int = 0):
    if random.random() >= white_heaven_explore_bonus_gu_chance(explorer_rank):
        return None
    name = random.choice(WHITE_HEAVEN_CANON_GU_NAMES)
    return gu_item_name(name, "Immortal")


def roll_explore(explorer_rank: int = 0, luck_stat: int = 0, white_heaven: bool = False) -> dict:
    """Returns {"band", "stones", "item_name", "quantity", "page_id", "page_quantity",
    "bonus_core", "bonus_essence_pill", "bonus_qi_ascension_pill", "bonus_white_heaven_gu"} --
    exactly one of stones/item_name/page_id is set for the main find; bonus_core (see
    roll_monster_core_bonus), bonus_essence_pill, bonus_qi_ascension_pill (each a
    (item_name, quantity) tuple or None, see items.roll_essence_restoration_pill_drop/
    roll_qi_ascension_pill_drop), and bonus_white_heaven_gu (an item_name or None, only ever
    non-None when white_heaven=True) are each a separate, independent long-shot that can turn
    up alongside any main find. white_heaven=True swaps the main find pool to
    WHITE_HEAVEN_BAND_POOLS (see GameManager.start_exploration_hunt) — the band curve itself
    (Luck/Explorer-rank weighting) is unchanged, only the reward tables differ."""
    names, weights = _weighted_bands(explorer_rank, luck_stat)
    band = random.choices(names, weights=weights, k=1)[0]
    pools = WHITE_HEAVEN_BAND_POOLS if white_heaven else BAND_POOLS
    result = pools[band]()
    result.setdefault("page_id", None)
    result.setdefault("page_quantity", 0)
    result["band"] = band
    result["bonus_core"] = roll_monster_core_bonus()
    result["bonus_essence_pill"] = items.roll_essence_restoration_pill_drop()
    result["bonus_qi_ascension_pill"] = items.roll_qi_ascension_pill_drop()
    result["bonus_white_heaven_gu"] = roll_white_heaven_explore_bonus_gu(explorer_rank) if white_heaven else None
    return result


# Independent bonus roll, checked once per /explore find on top of whatever the main band
# roll above already gave -- /explore doesn't otherwise ever grant a Beast Core (that's
# normally a guaranteed same-tier /hunt kill drop instead, see monsters._generate_hunt_
# monster), so this is a rare "you stumble across a fallen beast's core" long shot layered
# on top, tier 7 pinned to the requested 1/1000 and the rest of the ladder stepping down
# smoothly (roughly halving-to-doubling per tier) from there.
MONSTER_CORE_CHANCE_BY_TIER = {
    1: 1 / 20, 2: 1 / 50, 3: 1 / 100, 4: 1 / 200, 5: 1 / 350, 6: 1 / 600, 7: 1 / 1000,
}


def roll_monster_core_bonus():
    """Rarest tier checked first so a roll that clears multiple thresholds at once reports
    the best one it qualified for, instead of stopping at the first (most common) hit.
    Returns a "Tier N Beast Core" item name, or None."""
    for tier in range(7, 0, -1):
        if random.random() < MONSTER_CORE_CHANCE_BY_TIER[tier]:
            return f"Tier {tier} Beast Core"
    return None
