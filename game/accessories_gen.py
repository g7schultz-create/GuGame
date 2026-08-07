"""
Accessory/artifact roll logic — rarity, rank, and named-item selection from
accessories_data.ITEMS. Unlike blacksmith gear (procedurally rolled stats, no named
catalog) or manual pages (fixed named catalog, no live generation), this system leans
entirely on the hand-authored 73-item catalog rather than ALSO building a second
"invent a brand new item with a generated name" generator (design doc section 10's more
elaborate path) — the catalog already spans every rank and rarity in both categories (see
accessories_data.py's own coverage check), so a second generator would rarely produce
anything meaningfully different from just picking a named item. Path weighting (section 6)
still applies: an item sharing a theme tag with the roll's source is 3x as likely to be
picked as a neutral one.
"""

import random
from typing import List, Optional

from . import accessories_data as ad
from . import search_data


def weighted_choice(weights: dict, rng: random.Random) -> str:
    keys = list(weights.keys())
    values = [max(0.0, w) for w in weights.values()]
    return rng.choices(keys, weights=values, k=1)[0]


def roll_category(source_key: str, rng: random.Random) -> Optional[str]:
    """Whether a roll at this source produces an accessory, an artifact, or neither —
    see accessories_data.LOOT_SOURCE_TABLE."""
    odds = ad.LOOT_SOURCE_TABLE.get(source_key)
    if not odds:
        return None
    roll = rng.random()
    if roll < odds.get("accessory", 0):
        return "Accessory"
    if roll < odds.get("accessory", 0) + odds.get("artifact", 0):
        return "Artifact"
    return None


def roll_rarity(category: str, rng: random.Random) -> str:
    weights = ad.ACCESSORY_RARITY_WEIGHTS if category == "Accessory" else ad.ARTIFACT_RARITY_WEIGHTS
    return weighted_choice(weights, rng)


def roll_rank(source_rank: int, rng: random.Random) -> int:
    offset = int(weighted_choice({str(k): v for k, v in search_data.ITEM_RANK_RELATIVE_WEIGHTS.items()}, rng))
    return max(1, min(7, source_rank + offset))


def _path_weight(item: "ad.Affix", theme_tags: List[str]) -> float:
    if not theme_tags:
        return ad.PATH_NEUTRAL_WEIGHT
    item_paths = set(item.paths)
    tag_set = set(t.lower() for t in theme_tags)
    if item_paths & tag_set:
        return ad.PATH_MATCH_WEIGHT
    # "Opposed" isn't a maintained pairing table (no canon opposed-path list exists) — an
    # item that shares no tag at all with the source is treated as neutral rather than
    # actively opposed, since guessing an opposition would be more misleading than useful.
    return ad.PATH_NEUTRAL_WEIGHT


def select_item(category: str, rank: int, rarity: str, theme_tags: List[str], rng: random.Random) -> Optional["ad.Affix"]:
    """Picks a named item matching (category, rarity), rank <= the roll's rank, path-weighted
    toward theme_tags — widening the rank window if nothing matches yet (same "fall back
    rather than dead-roll" reasoning as manual_gen._roll_pages)."""
    pool = [item for item in ad.ITEMS.values() if item.category == category and item.rarity == rarity]
    if not pool:
        return None
    for max_rank in (rank, rank + 1, rank + 2, 7):
        candidates = [item for item in pool if item.rank <= max_rank]
        if candidates:
            weights = {item.item_id: _path_weight(item, theme_tags) for item in candidates}
            chosen_id = weighted_choice(weights, rng)
            return ad.ITEMS[chosen_id]
    return None


def roll_accessory_or_artifact(source_key: str, source_rank: int, theme_tags: List[str], rng: random.Random) -> Optional["ad.Affix"]:
    """End-to-end roll: category -> rarity -> rank -> named item. Returns None if this
    source simply didn't produce an accessory/artifact this time (see roll_category)."""
    category = roll_category(source_key, rng)
    if category is None:
        return None
    rarity = roll_rarity(category, rng)
    rank = roll_rank(source_rank, rng)
    return select_item(category, rank, rarity, theme_tags, rng)
