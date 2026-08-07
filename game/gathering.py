"""
Roll logic for /mine and /gather — both draw from the same tier-1-7 weighted shape (tier 7
is deliberately under 1%), differing only in which item name the tier maps to.
"""

import random
import re

# (weight, tier) — sums to 970; tier 7 = 5/970 ≈ 0.52%, comfortably under 1%.
RESOURCE_TIER_WEIGHTS = [
    (400, 1),
    (250, 2),
    (150, 3),
    (90, 4),
    (50, 5),
    (25, 6),
    (5, 7),
]

# random.randint range for a gather action's base quantity, before a profession's yield
# multiplier (see professions.yield_multiplier) is applied.
BASE_QUANTITY_RANGE = (1, 3)

# Luck nudges the tier roll toward better material: weight is moved off tier 1 (the most
# common) per luck point and redistributed proportionally across tiers 2-7, capped so
# tier 1 never drops below MIN_TIER1_WEIGHT — luck helps, it doesn't guarantee anything.
LUCK_WEIGHT_SHIFT_PER_POINT = 3
MIN_TIER1_WEIGHT = 100


def roll_tier(luck_stat: int = 0) -> int:
    weights = [w for w, _ in RESOURCE_TIER_WEIGHTS]
    tiers = [t for _, t in RESOURCE_TIER_WEIGHTS]
    shift = min(weights[0] - MIN_TIER1_WEIGHT, LUCK_WEIGHT_SHIFT_PER_POINT * max(0, luck_stat))
    if shift > 0:
        rest_total = sum(weights[1:])
        weights = [weights[0] - shift] + [w + shift * (w / rest_total) for w in weights[1:]]
    return random.choices(tiers, weights=weights, k=1)[0]


def roll_quantity(yield_multiplier: float = 1.0) -> int:
    base = random.randint(*BASE_QUANTITY_RANGE)
    return max(1, round(base * yield_multiplier))


# Display-only rarity label per tier, for embeds — no mechanical effect (the tier itself
# already drives odds/yield). Only the top 2 tiers earn the flashiest names, matching how
# rare a tier-6/7 roll actually is.
TIER_RARITY_NAMES = {
    1: "Common", 2: "Common", 3: "Uncommon", 4: "Uncommon", 5: "Rare", 6: "Epic", 7: "Legendary",
}

# Same color-coded emoji as the matching rarity name above, reusing the exact scheme
# character_data.ROOT_TIERS uses for Common/Uncommon/Rare/Epic/Legendary — so a glance at
# an ore/herb tells you at a glance how it stacks up against everything else in the bot,
# not just other ore. Two numeric tiers can share a color (T1/T2 are both "Common"); the
# tier number in the item name itself still tells those apart.
TIER_EMOJI = {1: "🟢", 2: "🟢", 3: "🔵", 4: "🔵", 5: "🟣", 6: "🟠", 7: "🟡"}

_TIER_NAME_RE = re.compile(r"^Tier (\d+) ")


def item_tier(item_name: str) -> int:
    """The leading numeric tier from a "Tier N ..." item name (Ore/Herb/Beast Material/
    etc.), or None for anything that isn't tiered that way (Gu, Primeval Essence Crystal,
    unique named drops, ...)."""
    match = _TIER_NAME_RE.match(item_name)
    return int(match.group(1)) if match else None


def format_collected(collected: dict) -> str:
    """"{qty}x {name}" per collected item for a /mine, /gather, or /explore result — tiered
    materials sorted ascending by tier (Tier 1 first, matching how player expect to scan a
    haul) and prefixed with a rarity-color emoji so the good stuff jumps out; anything
    without a tier (Gu, unique drops, ...) is listed after, alphabetically."""
    tiered = sorted(
        ((name, qty) for name, qty in collected.items() if item_tier(name) is not None),
        key=lambda pair: item_tier(pair[0]),
    )
    untiered = sorted((name, qty) for name, qty in collected.items() if item_tier(name) is None)
    parts = [f"{TIER_EMOJI[item_tier(name)]} {qty}x {name}" for name, qty in tiered]
    parts += [f"{qty}x {name}" for name, qty in untiered]
    return ", ".join(parts) or "Nothing yet"
