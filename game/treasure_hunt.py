"""
/search_forgotten_blessed_land's 5x5 treasure-hunt board. Pure roll/grant logic lives here,
kept separate from the view (mirrors manual_gen.py's own split between roll logic and its UI).

Reward tiers per direct request: ~40% dud, ~35% small, ~20% decent, ~5% rare-ish, plus exactly
one guaranteed "treasure" tile per board (not part of the weighted 24). Every reward type reuses
an existing grant mechanism (db.add_item/add_spirit_stones/add_player_page,
GameManager.roll_and_grant_accessory_artifact/roll_and_grant_avatar_gear) -- nothing new at the
item-generation level, only the tile-selection/weighting logic here is new.
"""

import random
from typing import Optional

from . import avatar_gear, equipment, items, manual_data

BOARD_SIZE = 25

TILE_CATEGORY_WEIGHTS = {"dud": 40, "small": 35, "decent": 20, "rare": 5}

# Weighted so the top tier lands at exactly the requested odds, not just "approximately".
MANUAL_PAGE_RANK_WEIGHTS = {4: 600, 5: 300, 6: 99, 7: 1}  # rank 7 exactly 1/1000
GU_QUALITY_WEIGHTS = {"Epic": 600, "Legendary": 300, "Mythic": 99, "Immortal": 1}  # Immortal exactly 1/1000
TREASURE_BONUS_WEIGHTS = {"accessory": 35, "avatar_gear": 35, "essence_pill": 28, "immortal_gu": 2}  # immortal_gu exactly 1/50
BEAST_CORE_TIER_WEIGHTS = {4: 40, 5: 30, 6: 20, 7: 10}
DECENT_SUB_WEIGHTS = {"manual_page": 30, "beast_core": 30, "essence_stone": 20, "essence_pill": 20}
RARE_SUB_WEIGHTS = {"accessory": 40, "gu": 30, "essence_pill": 30}

SMALL_MATERIAL_NAME = "Tier 1 Beast Material"
SMALL_STONE_RANGE = (50, 200)
TREASURE_ESSENCE_CRYSTAL_QTY = 200


def _weighted_choice(weights: dict, rng: random.Random):
    return rng.choices(list(weights.keys()), weights=list(weights.values()), k=1)[0]


def _essence_pill_tier(min_tier: int, max_tier: int, rng: random.Random) -> int:
    """Reuses items.ESSENCE_RESTORATION_PILL_TIER_WEIGHTS' relative weights, filtered to
    [min_tier, max_tier] and renormalized by _weighted_choice -- not a new drop curve, just a
    sub-range of the same existing one."""
    sub_weights = {t: w for t, w in items.ESSENCE_RESTORATION_PILL_TIER_WEIGHTS.items() if min_tier <= t <= max_tier}
    return _weighted_choice(sub_weights, rng)


def _gu_names_by_quality(quality: str) -> list:
    return [n for n, e in equipment.EQUIPMENT.items() if e.slot_type == "Gu" and equipment.parse_gu_name(n)[1] == quality]


def roll_board(rng: Optional[random.Random] = None) -> list:
    """25 tile category labels -- exactly one "treasure", the other 24 weighted dud/small/
    decent/rare -- shuffled so the treasure's grid position is unpredictable."""
    rng = rng or random.Random()
    categories = list(TILE_CATEGORY_WEIGHTS.keys())
    weights = list(TILE_CATEGORY_WEIGHTS.values())
    board = rng.choices(categories, weights=weights, k=BOARD_SIZE - 1)
    board.append("treasure")
    rng.shuffle(board)
    return board


def grant_tile_reward(game, user_id: int, name: str, category: str, rng: Optional[random.Random] = None) -> tuple:
    """Grants whatever `category` rolls and returns (emoji, label) for the revealed tile.
    `game` is a GameManager instance -- reuses its db/roll_and_grant_* methods the same way
    every other reward path in this codebase already does."""
    rng = rng or random.Random()
    db = game.db

    if category == "dud":
        return "🕳️", "Nothing"

    if category == "small":
        db.add_item(user_id, SMALL_MATERIAL_NAME, 1)
        stones = rng.randint(*SMALL_STONE_RANGE)
        db.add_spirit_stones(user_id, stones)
        return "🪨", f"{SMALL_MATERIAL_NAME} + {stones:,} 🪙"

    if category == "decent":
        sub = _weighted_choice(DECENT_SUB_WEIGHTS, rng)
        if sub == "manual_page":
            rank = _weighted_choice(MANUAL_PAGE_RANK_WEIGHTS, rng)
            page = rng.choice([p for p in manual_data.PAGES.values() if p.rank == rank])
            db.add_player_page(user_id, page.page_id, 1)
            return "📄", f"{page.name} (Rank {rank} page)"
        if sub == "beast_core":
            tier = _weighted_choice(BEAST_CORE_TIER_WEIGHTS, rng)
            item_name = f"Tier {tier} Beast Core"
            db.add_item(user_id, item_name, 1)
            return "💠", item_name
        if sub == "essence_stone":
            qty = rng.randint(3, 8)
            db.add_item(user_id, "Primeval Essence Crystal", qty)
            return "💎", f"{qty}x Primeval Essence Crystal"
        tier = _essence_pill_tier(1, 5, rng)
        item_name = f"Essence Restoration Pill (T{tier})"
        db.add_item(user_id, item_name, 1)
        return "💊", item_name

    if category == "rare":
        sub = _weighted_choice(RARE_SUB_WEIGHTS, rng)
        if sub == "accessory":
            granted = game.roll_and_grant_accessory_artifact(user_id, name, "treasure_hunt", 7, [])
            return ("✨", granted["affix"].name) if granted else ("🕳️", "Nothing (the roll fizzled)")
        if sub == "gu":
            quality = _weighted_choice(GU_QUALITY_WEIGHTS, rng)
            gu_name = rng.choice(_gu_names_by_quality(quality))
            db.add_item(user_id, gu_name, 1)
            return "🐛", gu_name
        tier = _essence_pill_tier(4, 7, rng)
        item_name = f"Essence Restoration Pill (T{tier})"
        db.add_item(user_id, item_name, 1)
        return "💊", item_name

    # "treasure" -- the guaranteed tile: always the big essence crystal payout, plus one bonus
    # roll from a separate pool (immortal_gu is the rare jackpot-within-the-jackpot at 1/50).
    db.add_item(user_id, "Primeval Essence Crystal", TREASURE_ESSENCE_CRYSTAL_QTY)
    label = f"{TREASURE_ESSENCE_CRYSTAL_QTY}x Primeval Essence Crystal"
    bonus = _weighted_choice(TREASURE_BONUS_WEIGHTS, rng)
    if bonus == "accessory":
        granted = game.roll_and_grant_accessory_artifact(user_id, name, "treasure_hunt", 7, [])
        if granted:
            label += f" + {granted['affix'].name}"
    elif bonus == "avatar_gear":
        granted = game.roll_and_grant_avatar_gear(user_id, name, "treasure_hunt", avatar_gear.MAX_TIER)
        label += f" + {avatar_gear.tier_name(granted['tier'])} {granted['slot_type']}"
    elif bonus == "essence_pill":
        tier = _essence_pill_tier(5, 7, rng)
        item_name = f"Essence Restoration Pill (T{tier})"
        db.add_item(user_id, item_name, 1)
        label += f" + {item_name}"
    else:  # immortal_gu
        gu_name = rng.choice(_gu_names_by_quality("Immortal"))
        db.add_item(user_id, gu_name, 1)
        label += f" + {gu_name}"
    return "🏆", label
