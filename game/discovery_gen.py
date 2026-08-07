"""
/search's actual roll logic — result weighting, momentum/pity, discovery theming, room/event
resolution, and loot generation. Mirrors the design doc's own pseudocode (section 17) closely
enough that the doc can be used as a reference while reading this module.

Reward integration: Gu/weapon/armor/material rewards are pulled straight from this game's
EXISTING catalogs (equipment.EQUIPMENT, items.ITEMS, canon_gu) rather than inventing a
parallel item system — a search-found Gu is a completely normal Gu, tradeable and equippable
the same way a hunt/raid drop is. Only manual pages and complete manuals are new content
types (see manual_data.py / manual_gen.py).
"""

import random
import time
from typing import Dict, List, Optional

from . import blacksmith, canon_gu, equipment, items, manual_data, manual_gen, search_data

MAX_CLUE_MOMENTUM_HISTORY = 200  # sanity bound, not user-facing


def weighted_choice(weights: Dict[str, float], rng: random.Random) -> str:
    keys = list(weights.keys())
    values = [max(0.0, w) for w in weights.values()]
    return rng.choices(keys, weights=values, k=1)[0]


def _apply_focus_modifier(weights: Dict[str, float], focus: str) -> Dict[str, float]:
    modifiers = search_data.SEARCH_FOCUS_MODIFIERS.get(focus, {})
    return {key: value * modifiers.get(key, 1.0) for key, value in weights.items()}


def roll_search_result(momentum: int, focus: str, rng: random.Random, clue_bonus: float = 0.0, dream_realm_bias: float = 0.0) -> dict:
    """Returns {"result": ..., "momentum_after": ..., "pity_forced": bool}. result is one of
    BASE_SEARCH_WEIGHTS' keys. clue_bonus (e.g. a root's clue_chance_bonus_pct — see
    character_data.CharacterTraitSpec) shifts weight off "nothing" and onto "clue", on the
    same 0-100 scale BASE_SEARCH_WEIGHTS' own values already use — a 0.01 bonus is worth 1 of
    those 100 points, floored so "nothing" can't go negative no matter how large the bonus.
    dream_realm_bias (a Soul-family root's own "soul/dream reward weighting") does the exact
    same shift, but off "nothing" and onto "dream_realm" instead — "better rewards from
    dream/soul content" read as "actually reaching that content more often", the same
    interpretation clue_bonus already uses for clue content."""
    weights = _apply_focus_modifier(dict(search_data.BASE_SEARCH_WEIGHTS), focus)
    if clue_bonus > 0:
        shift = min(weights["nothing"], clue_bonus * 100)
        weights["nothing"] -= shift
        weights["clue"] += shift
    if dream_realm_bias > 0:
        shift = min(weights["nothing"], dream_realm_bias * 100)
        weights["nothing"] -= shift
        weights["dream_realm"] += shift
    pity_forced = False

    if momentum >= search_data.MOMENTUM_SPECIAL_THRESHOLD:
        # Guaranteed special location — dream realms are never the guaranteed pick here
        # (per the doc: "not guaranteed unless a dream clue is completed").
        special_weights = {k: search_data.BASE_SEARCH_WEIGHTS[k] for k in ("inheritance", "secret_realm")}
        result = weighted_choice(special_weights, rng)
        pity_forced = True
    else:
        result = weighted_choice(weights, rng)
        if momentum >= search_data.MOMENTUM_CLUE_THRESHOLD and result not in ({"clue", "encounter"} | search_data.SPECIAL_RESULTS):
            result = "clue" if rng.random() < 0.5 else "encounter"
            pity_forced = True

    momentum_after = 0 if result in search_data.SPECIAL_RESULTS else momentum + 1
    return {"result": result, "momentum_after": momentum_after, "pity_forced": pity_forced}


def roll_difficulty(rng: random.Random, allow_forbidden: bool = False, quality_bias: float = 0.0) -> str:
    """quality_bias (e.g. a Heaven-family root's discovery_quality_bias_pct — see
    character_data.CharacterTraitSpec) shifts weight off Safe and onto Dangerous, the same
    "move N of the 100 weight points" trick this module's other bias params already use —
    higher difficulty means a harder discovery, but also a richer one (see search_data's own
    reward-by-difficulty scaling), so this is the "+discovery quality" the design brief asks
    for without inventing a second, parallel reward-quality axis."""
    bands = search_data.DIFFICULTY_BANDS if allow_forbidden else search_data.DIFFICULTY_BANDS[:-1]
    # Standard-weighted toward the middle of whatever's allowed — Safe/Standard most common.
    weights = {"Safe": 30, "Standard": 45, "Dangerous": 20, "Forbidden": 5}
    if quality_bias > 0 and "Safe" in bands and "Dangerous" in bands:
        shift = min(weights["Safe"], quality_bias * 100)
        weights = dict(weights, Safe=weights["Safe"] - shift, Dangerous=weights["Dangerous"] + shift)
    return weighted_choice({b: weights[b] for b in bands}, rng)


def theme_for_discovery(discovery_type: str, rng: random.Random) -> dict:
    table = {
        "inheritance": search_data.INHERITANCE_THEMES,
        "secret_realm": search_data.SECRET_REALM_THEMES,
        "dream_realm": search_data.DREAM_REALM_FORMS,
    }[discovery_type]
    return rng.choice(table)


def roll_item_rank(location_rank: int, difficulty: str, rng: random.Random) -> int:
    offset = weighted_choice({str(k): v for k, v in search_data.ITEM_RANK_RELATIVE_WEIGHTS.items()}, rng)
    rank = location_rank + int(offset) + search_data.DIFFICULTY_RANK_OFFSET.get(difficulty, 0)
    return max(1, min(manual_data.MAX_MANUAL_RANK, rank))


def roll_rarity(source_key: str, rng: random.Random) -> str:
    weights = dict(manual_data.RARITY_BASE_WEIGHTS)
    for rarity, mult in search_data.SOURCE_RARITY_MULTIPLIERS.get(source_key, {}).items():
        weights[rarity] = weights.get(rarity, 0) * mult
    return weighted_choice(weights, rng)


def _gu_quality_for_rarity(rarity: str) -> str:
    idx = min(len(equipment.GU_QUALITY_ORDER) - 1, manual_data.RARITY_ORDER.index(rarity))
    return equipment.GU_QUALITY_ORDER[idx]


def _roll_gu_reward(location_rank: int, rarity: str, rng: random.Random) -> Optional[str]:
    quality = _gu_quality_for_rarity(rarity)
    candidates = [
        name for name, gear in equipment.EQUIPMENT.items()
        if gear.slot_type == "Gu" and equipment.parse_gu_name(name)[1] == quality
    ]
    if not candidates:
        candidates = [name for name, gear in equipment.EQUIPMENT.items() if gear.slot_type == "Gu"]
    return rng.choice(candidates) if candidates else None


def _roll_equipment_reward(kind: str, location_rank: int, rng: random.Random) -> dict:
    """Rolls a fresh crafted_gear instance (see blacksmith.roll_gear_stats) — a weapon/armor
    drop from a discovery is the same underlying gear /blacksmith forges, so it gets the
    same unique id + random stats rather than a separate static item."""
    tier = max(blacksmith.MIN_TIER, min(blacksmith.MAX_TIER, location_rank))
    gear_type = "Sword" if kind == "weapon" else rng.choice(["Helm", "Armor"])
    return {"kind": "crafted_gear", "base_type": gear_type, "tier": tier, "stat_bonuses": blacksmith.roll_gear_stats(tier, rng)}


def _roll_material_reward(location_rank: int, rng: random.Random) -> tuple:
    tier = max(1, min(7, location_rank))
    kind = rng.choice(["Ore", "Herb", "Beast Material"])
    name = f"Tier {tier} {kind}" if kind != "Beast Material" else f"Tier {tier} Beast Material"
    quantity = rng.randint(1, 3)
    return name, quantity


def _roll_pages(location_rank: int, count: int, theme_tags: List[str], rng: random.Random) -> List[str]:
    pool = [p for p in manual_data.PAGES.values() if p.rank <= location_rank + 1]
    if not pool:
        return []
    tag_set = set(theme_tags)
    weighted_pool = [p for p in pool if tag_set & set(p.tags)] or pool
    return [rng.choice(weighted_pool).page_id for _ in range(min(count, len(weighted_pool)))]


def generate_loot(category_key: str, source_key: str, location_rank: int, difficulty: str, theme_tags: List[str], rng: random.Random) -> dict:
    """Returns a reward description dict: {"kind": ..., ...}. `kind` is one of "stones",
    "item", "pages", "manual", "clue" — see discovery_gen callers for how each is granted."""
    item_rank = roll_item_rank(location_rank, difficulty, rng)
    rarity = roll_rarity(source_key, rng)

    if category_key in ("spirit_stones",):
        base = {1: 20, 2: 60, 3: 150, 4: 350, 5: 700, 6: 1400, 7: 2500}[item_rank]
        quality_mult = 1 + search_data.DIFFICULTY_REWARD_QUALITY_PCT.get(difficulty, 0) / 100
        return {"kind": "stones", "amount": max(1, round(base * quality_mult * rng.uniform(0.8, 1.2)))}

    if category_key in ("manual_page_bundle", "manual_page", "high_quality_pages"):
        count = {"manual_page": 1, "manual_page_bundle": rng.randint(2, 4), "high_quality_pages": rng.randint(2, 3)}[category_key]
        return {"kind": "pages", "page_ids": _roll_pages(item_rank, count, theme_tags, rng)}

    if category_key in ("complete_manual", "breakthrough_page"):
        if category_key == "breakthrough_page":
            pages = _roll_pages(item_rank, 1, theme_tags, rng)
            breakthrough_pages = [pid for pid in manual_data.PAGES if manual_data.PAGES[pid].category == "Breakthrough" and manual_data.PAGES[pid].rank <= item_rank + 1]
            return {"kind": "pages", "page_ids": (breakthrough_pages[:1] or pages)}
        manual = manual_gen.generate_manual(source_key, item_rank, rarity, theme_tags, complete=True, seed=rng.randrange(1, 2**31))
        return {"kind": "manual", "manual": manual}

    if category_key in ("signature_gu", "wild_gu", "dream_gu"):
        name = _roll_gu_reward(item_rank, rarity, rng)
        return {"kind": "item", "item_name": name, "quantity": 1} if name else {"kind": "stones", "amount": 20}

    if category_key == "weapon":
        return _roll_equipment_reward("weapon", item_rank, rng)

    if category_key == "armor":
        return _roll_equipment_reward("armor", item_rank, rng)

    if category_key in ("cultivation_resource", "rare_material_bundle", "dream_material"):
        name, qty = _roll_material_reward(item_rank, rng)
        return {"kind": "item", "item_name": name, "quantity": qty}

    if category_key in ("clue_or_key", "realm_key"):
        return {"kind": "clue", "fragments": 1}

    if category_key in ("hidden_line_repair", "path_attainment", "recipe_fragment", "unique_legacy", "unique_treasure", "unique_memory_seed"):
        # Exotic/narrative-only reward types the design doc names (path fragments, legacy
        # seals, path attainment, ...) are folded into the manual crafting currencies
        # (Ink/Insight Dust) rather than each getting its own dedicated item/column — same
        # economy, less surface area to maintain.
        return {"kind": "insight", "amount": rng.randint(3, 10)}

    if category_key == "manual_currency_bundle":
        # TESTING: see search_data.MANUAL_CURRENCY_BUNDLE_WEIGHT's own comment — a much
        # bigger, ink-AND-dust roll than the "insight"-only categories above.
        return {"kind": "manual_currency", "ink": rng.randint(30, 50), "dust": rng.randint(30, 50)}

    # Unrecognized category — a safe stones fallback rather than a crash.
    return {"kind": "stones", "amount": 15}


def resolve_step(discovery_type: str, location_rank: int, difficulty: str, theme_tags: List[str], rng: random.Random, is_final: bool) -> dict:
    """Rolls one room/event/stage and its reward. Returns {"name": ..., "reward": {...}}."""
    if discovery_type == "inheritance":
        step_name = weighted_choice(search_data.INHERITANCE_ROOM_TABLE, rng)
        table = search_data.INHERITANCE_FINAL_CHEST_TABLE if is_final else {"cultivation_resource": 50, "manual_page": 30, "spirit_stones": 20}
        source_key = "inheritance_final" if is_final else "inheritance_room"
    elif discovery_type == "secret_realm":
        step_name = weighted_choice(search_data.SECRET_REALM_EVENT_TABLE, rng)
        table = search_data.SECRET_REALM_BOSS_CHEST_TABLE if is_final else {"rare_material_bundle": 50, "spirit_stones": 30, "wild_gu": 20}
        source_key = "secret_realm_boss" if is_final else "encounter"
    else:
        step_name = weighted_choice(search_data.DREAM_REALM_STAGE_TABLE, rng)
        table = search_data.DREAM_REALM_COMPLETION_TABLE if is_final else {"high_quality_pages": 50, "hidden_line_repair": 30, "dream_material": 20}
        source_key = "dream_completion" if is_final else "encounter"

    category = weighted_choice(table, rng)
    reward = generate_loot(category, source_key, location_rank, difficulty, theme_tags, rng)
    return {"name": step_name, "category": category, "reward": reward}
