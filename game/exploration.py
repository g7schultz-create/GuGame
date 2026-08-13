"""
/explore's loot table: a single weighted rarity-band roll (not independent per-entry rolls
like monster drops — you find ONE thing per trip), then a random pick within that band's
pool. Common is deliberately very likely; Mythic (the jackpot band — 100,000 spirit
stones, a Mythic/"Tier 6" quality Gu, or the one Legendary weapon in the game) is
deliberately almost impossible. Explorer profession rank shifts a little weight off Common
onto the rest, without ever making Mythic anything but very, very rare.
"""

import random

from . import items
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

# Weight shifted off Common per Explorer rank (and, separately, per point of Luck),
# redistributed proportionally across the other bands. Capped so Common never drops below
# 50 weight (5%), even stacking max rank with a high Luck stat.
WEIGHT_SHIFT_PER_RANK = 8
LUCK_WEIGHT_SHIFT_PER_POINT = 2
MIN_COMMON_WEIGHT = 50


def _weighted_bands(explorer_rank: int, luck_stat: int = 0):
    names = [name for name, _ in EXPLORE_BANDS]
    weights = [w for _, w in EXPLORE_BANDS]
    total_shift = WEIGHT_SHIFT_PER_RANK * explorer_rank + LUCK_WEIGHT_SHIFT_PER_POINT * max(0, luck_stat)
    shift = min(weights[0] - MIN_COMMON_WEIGHT, total_shift)
    if shift <= 0:
        return names, weights
    rest_total = sum(weights[1:])
    adjusted = [weights[0] - shift] + [w + shift * (w / rest_total) for w in weights[1:]]
    return names, adjusted


def _stones(lo: int, hi: int) -> dict:
    return {"stones": random.randint(lo, hi), "item_name": None, "quantity": 0}


def _item(item_name: str, lo: int, hi: int) -> dict:
    return {"stones": 0, "item_name": item_name, "quantity": random.randint(lo, hi)}


def _gu(quality: str) -> dict:
    family = random.choice(list(GU_FAMILIES.keys()))
    return {"stones": 0, "item_name": gu_item_name(family, quality), "quantity": 1}


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
    ]),
    "Legendary": lambda: random.choice([
        _stones(300, 1000),
        _item("Tier 5 Ore", 1, 2),
        _item("Tier 5 Herb", 1, 2),
        _gu("Rare"),
    ]),
    "Mythic": lambda: random.choice([
        {"stones": 100_000, "item_name": None, "quantity": 0},
        _gu("Mythic"),
        {"stones": 0, "item_name": "Heaven-Severing Blade", "quantity": 1},
    ]),
}


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
    ]),
    "Legendary": lambda: random.choice([
        _stones(1000, 3000),
        _item("Tier 8 Herb", 1, 2),
        _item("Tier 8 Beast Material", 1, 2),
    ]),
    "Mythic": lambda: random.choice([
        {"stones": 300_000, "item_name": None, "quantity": 0},
        _item("Tier 8 Beast Core", 2, 4),
    ]),
}

# A small independent shot at one of the 20 White Heaven canon Gu (see content/
# canon_gu_white_heaven.py) on every White Heaven /explore find -- /explore never kills
# anything, so it needs its own separate roll rather than reusing GameManager.
# roll_white_heaven_bonus_gu (hunt/raid's own per-kill version). Flat per-find chance (not
# band-weighted), same "independent of the main band pick" shape as bonus_core.
WHITE_HEAVEN_EXPLORE_BONUS_GU_CHANCE = 1 / 3000


def roll_white_heaven_explore_bonus_gu():
    if random.random() >= WHITE_HEAVEN_EXPLORE_BONUS_GU_CHANCE:
        return None
    name = random.choice(WHITE_HEAVEN_CANON_GU_NAMES)
    return gu_item_name(name, "Common")


def roll_explore(explorer_rank: int = 0, luck_stat: int = 0, white_heaven: bool = False) -> dict:
    """Returns {"band", "stones", "item_name", "quantity", "bonus_core", "bonus_essence_pill",
    "bonus_qi_ascension_pill", "bonus_white_heaven_gu"} — either stones or item_name is set
    (never both) for the main find; bonus_core (see roll_monster_core_bonus),
    bonus_essence_pill, bonus_qi_ascension_pill (each a (item_name, quantity) tuple or None,
    see items.roll_essence_restoration_pill_drop/roll_qi_ascension_pill_drop), and
    bonus_white_heaven_gu (an item_name or None, only ever non-None when white_heaven=True) are
    each a separate, independent long-shot that can turn up alongside any main find.
    white_heaven=True swaps the main find pool to WHITE_HEAVEN_BAND_POOLS (see GameManager.
    start_exploration_hunt) — the band curve itself (Luck/Explorer-rank weighting) is
    unchanged, only the reward tables differ."""
    names, weights = _weighted_bands(explorer_rank, luck_stat)
    band = random.choices(names, weights=weights, k=1)[0]
    pools = WHITE_HEAVEN_BAND_POOLS if white_heaven else BAND_POOLS
    result = pools[band]()
    result["band"] = band
    result["bonus_core"] = roll_monster_core_bonus()
    result["bonus_essence_pill"] = items.roll_essence_restoration_pill_drop()
    result["bonus_qi_ascension_pill"] = items.roll_qi_ascension_pill_drop()
    result["bonus_white_heaven_gu"] = roll_white_heaven_explore_bonus_gu() if white_heaven else None
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
