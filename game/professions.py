"""
Profession leveling: 7 professions climbing the same 8-rank ladder by studying (see
GameManager.study) — a real-time gate, not an XP grind. Only one profession can be
studied at a time (a deliberate resource-allocation choice — no early-abandon/switch yet,
you finish or you wait), starting around an hour per rank and stretching to two weeks by
the final rank.

Miner/Gatherer/Farmer ranks scale gathering/harvest yield; Explorer rank improves
/explore's odds of a better rarity band; Alchemist rank scales /alchemy's success chance
(see craft_success_chance) — the first of the three crafting professions to have its rank
actually do something. Blacksmith/Gu Refiner can be studied and ranked up like the rest,
but still have no crafting action wired to their rank — that's a separate follow-up once
their recipes are defined, same as Alchemist was until now.
"""

from typing import Optional

PROFESSIONS = ["Miner", "Gatherer", "Alchemist", "Blacksmith", "Gu Refiner", "Explorer", "Farmer"]

# Matches the emoji each profession's own action command already uses (⛏️ /mine, 🌿
# /gather, ⚗️ /alchemy, 🔨 /blacksmith, 🧭 /explore, 🌾 /farm) — Gu Refiner has no crafting
# action wired up yet (see the module docstring), so it borrows the general Gu emoji.
PROFESSION_EMOJI = {
    "Miner": "⛏️", "Gatherer": "🌿", "Alchemist": "⚗️", "Blacksmith": "🔨",
    "Gu Refiner": "🐛", "Explorer": "🧭", "Farmer": "🌾",
}

RANKS = ["Novice", "Apprentice", "Adept", "Expert", "Master", "Grandmaster", "Heavenly Master", "Dao Master"]
MAX_RANK_INDEX = len(RANKS) - 1  # 7, Dao Master

# Hours of studying required to advance FROM rank index i TO i+1 (7 steps for 8 ranks).
# Tunable — starts near an hour, ends at two weeks for the final step.
STUDY_HOURS_PER_STEP = [1, 4, 12, 24, 72, 168, 336]

# Applied to gathering/harvest quantity (Miner/Gatherer/Farmer) at the matching rank index.
YIELD_MULTIPLIER_PER_RANK = [1.0, 1.15, 1.3, 1.5, 1.75, 2.0, 2.5, 3.0]

# Crafting success chance (Alchemist now; Blacksmith/Gu Refiner once they have recipes)
# at the matching rank index — Dao Master crafts flawlessly, everyone else risks the
# materials on a failed attempt.
SUCCESS_CHANCE_PER_RANK = [0.50, 0.60, 0.68, 0.75, 0.82, 0.88, 0.94, 1.00]

# player column storing each profession's rank index.
RANK_COLUMN = {name: f"{name.lower().replace(' ', '_')}_rank" for name in PROFESSIONS}


def rank_name(rank_index: int) -> str:
    return RANKS[max(0, min(rank_index, MAX_RANK_INDEX))]


def yield_multiplier(rank_index: int) -> float:
    return YIELD_MULTIPLIER_PER_RANK[max(0, min(rank_index, MAX_RANK_INDEX))]


def craft_success_chance(rank_index: int) -> float:
    return SUCCESS_CHANCE_PER_RANK[max(0, min(rank_index, MAX_RANK_INDEX))]


def hours_required(rank_index: int) -> Optional[float]:
    """Hours of studying to advance from rank_index to rank_index + 1, or None if already maxed."""
    if rank_index >= MAX_RANK_INDEX:
        return None
    return STUDY_HOURS_PER_STEP[rank_index]
