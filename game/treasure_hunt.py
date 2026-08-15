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
MAX_CLICKS_PER_BOARD = 7  # the board still has 25 tiles (and still guarantees a treasure tile
# is SOMEWHERE on it), but a player only gets to dig 7 of them -- finding the treasure isn't a
# certainty anymore, it's a real 7/25 draw.

TILE_CATEGORY_WEIGHTS = {"dud": 40, "small": 35, "decent": 20, "rare": 5}

# Weighted so the top tier lands at exactly the requested odds, not just "approximately".
MANUAL_PAGE_RANK_WEIGHTS = {4: 600, 5: 300, 6: 99, 7: 1}  # rank 7 exactly 1/1000
GU_QUALITY_WEIGHTS = {"Epic": 600, "Legendary": 300, "Mythic": 99, "Immortal": 1}  # Immortal exactly 1/1000
TREASURE_BONUS_WEIGHTS = {"accessory": 35, "avatar_gear": 35, "essence_pill": 28, "immortal_gu": 2}  # immortal_gu exactly 1/50
BEAST_CORE_TIER_WEIGHTS = {4: 40, 5: 30, 6: 20, 7: 10}
DECENT_SUB_WEIGHTS = {"manual_page": 30, "beast_core": 30, "essence_stone": 20, "essence_pill": 20}
# White Heaven's own "decent" sub-table (2026-08-14) -- adds a "herb" outcome the base game's
# own DECENT_SUB_WEIGHTS deliberately doesn't get (Tier N Herb has no equivalent base-game
# drop gap to fill; this closes White Heaven's own one, per explicit request).
WHITE_HEAVEN_DECENT_SUB_WEIGHTS = {"manual_page": 25, "beast_core": 25, "herb": 20, "essence_stone": 15, "essence_pill": 15}
RARE_SUB_WEIGHTS = {"accessory": 40, "gu": 30, "essence_pill": 30}

SMALL_MATERIAL_NAME = "Tier 1 Beast Material"
SMALL_STONE_RANGE = (50, 200)
TREASURE_ESSENCE_CRYSTAL_QTY = 200

# White Heaven's own board (see game/white_heaven.py, GameManager.start_treasure_hunt) --
# same TILE_CATEGORY_WEIGHTS/board shape, but every reward tier is shifted up to match the
# region's Tier 8/Rank 8 ceiling (see blacksmith.MAX_TIER, manual_data.MAX_MANUAL_RANK)
# instead of the base game's Tier 7 ceiling. MANUAL_PAGE_RANK_WEIGHTS/BEAST_CORE_TIER_WEIGHTS
# only have 3 rungs of headroom left above the old ceiling (6-8, not a full 4-wide window like
# the base tables), so both are renormalized to 3 entries rather than simply shifted.
WHITE_HEAVEN_MANUAL_PAGE_RANK_WEIGHTS = {6: 700, 7: 250, 8: 50}
WHITE_HEAVEN_BEAST_CORE_TIER_WEIGHTS = {6: 45, 7: 35, 8: 20}
# 2026-08-14: same 3-rung shape as WHITE_HEAVEN_BEAST_CORE_TIER_WEIGHTS above, for the new
# "herb" sub-outcome (see WHITE_HEAVEN_DECENT_SUB_WEIGHTS).
WHITE_HEAVEN_HERB_TIER_WEIGHTS = {6: 45, 7: 35, 8: 20}
SMALL_MATERIAL_NAME_WHITE_HEAVEN = "Tier 6 Beast Material"
SMALL_STONE_RANGE_WHITE_HEAVEN = (300, 900)
TREASURE_ESSENCE_CRYSTAL_QTY_WHITE_HEAVEN = 500


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


def grant_tile_reward(game, user_id: int, name: str, category: str, rng: Optional[random.Random] = None, white_heaven: bool = False) -> tuple:
    """Grants whatever `category` rolls and returns (emoji, label) for the revealed tile.
    `game` is a GameManager instance -- reuses its db/roll_and_grant_* methods the same way
    every other reward path in this codebase already does. Layers an independent Qi Ascension
    Pill bonus roll on top of EVERY dig (including a "dud"), one of only three drop sources
    for that pill -- see items.roll_qi_ascension_pill_drop's own docstring. white_heaven=True
    (see GameManager.start_treasure_hunt) shifts every reward tier's tables up to the region's
    own Tier 8/Rank 8 ceiling -- see WHITE_HEAVEN_MANUAL_PAGE_RANK_WEIGHTS et al above."""
    rng = rng or random.Random()
    emoji, label = _roll_base_tile_reward(game, user_id, name, category, rng, white_heaven)
    qi_ascension_pill = items.roll_qi_ascension_pill_drop(rng)
    if qi_ascension_pill:
        pill_name, pill_qty = qi_ascension_pill
        game.db.add_item(user_id, pill_name, pill_qty)
        label += f" + 🌟 {pill_qty}x {pill_name}"
        if emoji == "🕳️":
            emoji = "🌟"
    return emoji, label


def _roll_base_tile_reward(game, user_id: int, name: str, category: str, rng: random.Random, white_heaven: bool = False) -> tuple:
    db = game.db

    if category == "dud":
        return ("🕳️", "An empty, long-sealed grotto") if white_heaven else ("🕳️", "Nothing")

    if category == "small":
        material_name = SMALL_MATERIAL_NAME_WHITE_HEAVEN if white_heaven else SMALL_MATERIAL_NAME
        stone_range = SMALL_STONE_RANGE_WHITE_HEAVEN if white_heaven else SMALL_STONE_RANGE
        db.add_item(user_id, material_name, 1)
        stones = rng.randint(*stone_range)
        db.add_spirit_stones(user_id, stones)
        return "🪨", f"{material_name} + {stones:,} 🪙"

    if category == "decent":
        sub = _weighted_choice(WHITE_HEAVEN_DECENT_SUB_WEIGHTS if white_heaven else DECENT_SUB_WEIGHTS, rng)
        if sub == "manual_page":
            rank_weights = WHITE_HEAVEN_MANUAL_PAGE_RANK_WEIGHTS if white_heaven else MANUAL_PAGE_RANK_WEIGHTS
            rank = _weighted_choice(rank_weights, rng)
            page = rng.choice([p for p in manual_data.PAGES.values() if p.rank == rank])
            db.add_player_page(user_id, page.page_id, 1)
            label = f"{page.name} (Rank {rank} page)"
            return ("📜", f"An ancient Immortal's forgotten ledger page -- {label}") if white_heaven else ("📄", label)
        if sub == "beast_core":
            tier_weights = WHITE_HEAVEN_BEAST_CORE_TIER_WEIGHTS if white_heaven else BEAST_CORE_TIER_WEIGHTS
            tier = _weighted_choice(tier_weights, rng)
            item_name = f"Tier {tier} Beast Core"
            db.add_item(user_id, item_name, 1)
            return "💠", item_name
        if sub == "herb":  # White Heaven only -- see WHITE_HEAVEN_DECENT_SUB_WEIGHTS
            tier = _weighted_choice(WHITE_HEAVEN_HERB_TIER_WEIGHTS, rng)
            item_name = f"Tier {tier} Herb"
            db.add_item(user_id, item_name, 1)
            return "🌿", item_name
        if sub == "essence_stone":
            qty = rng.randint(15, 30) if white_heaven else rng.randint(3, 8)
            db.add_item(user_id, "Primeval Essence Crystal", qty)
            return "💎", f"{qty}x Primeval Essence Crystal"
        tier = _essence_pill_tier(4, 7, rng) if white_heaven else _essence_pill_tier(1, 5, rng)
        item_name = f"Essence Restoration Pill (T{tier})"
        db.add_item(user_id, item_name, 1)
        return "💊", item_name

    if category == "rare":
        sub = _weighted_choice(RARE_SUB_WEIGHTS, rng)
        if sub == "accessory":
            granted = game.roll_and_grant_accessory_artifact(user_id, name, "treasure_hunt", 7, [])
            return ("✨", granted["affix"].name) if granted else ("🕳️", "Nothing (the roll fizzled)")
        if sub == "gu":
            # White Heaven's own find always comes out Immortal (2026-08-14, explicit
            # request) -- the base game keeps the real weighted roll (mostly Epic, Immortal
            # a genuine 1/1000 jackpot) so Immortal doesn't become trivially common there.
            quality = "Immortal" if white_heaven else _weighted_choice(GU_QUALITY_WEIGHTS, rng)
            gu_name = rng.choice(_gu_names_by_quality(quality))
            db.add_item(user_id, gu_name, 1)
            return "🐛", gu_name
        tier = _essence_pill_tier(4, 7, rng)
        item_name = f"Essence Restoration Pill (T{tier})"
        db.add_item(user_id, item_name, 1)
        return "💊", item_name

    # "treasure" -- the guaranteed tile: always the big essence crystal payout, plus one bonus
    # roll from a separate pool (immortal_gu is the rare jackpot-within-the-jackpot at 1/50).
    crystal_qty = TREASURE_ESSENCE_CRYSTAL_QTY_WHITE_HEAVEN if white_heaven else TREASURE_ESSENCE_CRYSTAL_QTY
    db.add_item(user_id, "Primeval Essence Crystal", crystal_qty)
    label = f"{crystal_qty}x Primeval Essence Crystal"
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
