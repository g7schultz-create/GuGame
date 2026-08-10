import random
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from . import gathering
from .database import GameDatabase

# Tunable numbers for rank 1 pills — expect these to be rebalanced as more ranks are added.
HEALING_HERB_PERCENT = 0.05
ESSENCE_GATHERING_PILL_PERCENT = 0.05
GREEN_LEAF_APTITUDE_CHANCE = 0.15
APERTURE_OPENING_QI_BONUS = 0.1
DEW_SPIRIT_ESSENCE_AMOUNT = 20
JADE_SPRING_QI_BONUS = 1.0
JADE_SPRING_DURATION_SECONDS = 30 * 60


@dataclass
class Item:
    name: str
    category: str
    description: str
    use: Optional[Callable[[GameDatabase, int], str]] = None  # None for inert materials with no effect yet
    rank: Optional[int] = None
    subcategory: Optional[str] = None


def _use_healing_herb(db: GameDatabase, user_id: int) -> str:
    healed, hp, max_hp = db.heal_percent(user_id, HEALING_HERB_PERCENT)
    return f"You feel rejuvenated, healing **{healed} HP** ({hp}/{max_hp})."


def _use_essence_gathering_pill(db: GameDatabase, user_id: int) -> str:
    restored, essence, max_essence = db.restore_essence_percent(user_id, ESSENCE_GATHERING_PILL_PERCENT)
    return f"Your primeval essence is replenished by **{restored}** ({essence}/{max_essence})."


def _use_green_leaf_qi_pill(db: GameDatabase, user_id: int) -> str:
    _, gained = db.settle_qi(user_id)
    gained_aptitude, new_aptitude = db.maybe_gain_aptitude(user_id, GREEN_LEAF_APTITUDE_CHANCE)
    message = f"You cultivate furiously, banking **{gained:,.2f} qi**."
    if gained_aptitude:
        message += f" Your comprehension deepens — **aptitude increased to {new_aptitude}**!"
    return message


def _use_aperture_opening_pellet(db: GameDatabase, user_id: int) -> str:
    new_multiplier = db.add_qi_multiplier(user_id, APERTURE_OPENING_QI_BONUS)
    return f"Your aperture widens permanently — qi multiplier is now **x{new_multiplier:.2f}**."


def _use_dew_spirit_pellet(db: GameDatabase, user_id: int) -> str:
    added, essence, max_essence = db.add_primeval_essence(user_id, DEW_SPIRIT_ESSENCE_AMOUNT)
    return f"Condensed spirit dew forms fresh primeval essence: **+{added}** ({essence}/{max_essence})."


def _use_jade_spring_pill(db: GameDatabase, user_id: int) -> str:
    db.add_buff(user_id, "Jade Spring Boost", JADE_SPRING_QI_BONUS, JADE_SPRING_DURATION_SECONDS)
    minutes = JADE_SPRING_DURATION_SECONDS // 60
    return f"A wave of vigor floods your meridians — **+{JADE_SPRING_QI_BONUS:.1f} qi multiplier** for {minutes} minutes!"


# A flat +2 was fine at a 1,000 essence starting cap but is meaningless once that cap has
# grown into the thousands at higher realms (e.g. ~10,000 at Nascent Soul) -- a % of the
# player's own max_primeval_essence instead, matching how every other essence-restoration
# mechanic in this codebase already scales (see _use_essence_restoration_pill), so a crystal
# is naturally worth more to a higher-realm cultivator without needing a second, parallel
# per-realm table.
PRIMEVAL_ESSENCE_CRYSTAL_PERCENT = 0.01


def _use_primeval_essence_crystal(db: GameDatabase, user_id: int) -> str:
    restored, essence, max_essence = db.restore_essence_percent(user_id, PRIMEVAL_ESSENCE_CRYSTAL_PERCENT)
    return f"The crystal dissolves into primeval essence: **+{restored}** ({essence}/{max_essence})."


ITEMS: dict[str, Item] = {
    "Minor Recovery Pill": Item(
        name="Minor Recovery Pill",
        category="Healing",
        description="Restores 5% of max HP.",
        use=_use_healing_herb,
    ),
    "Lesser Foundation Pill": Item(
        name="Lesser Foundation Pill",
        category="Pills",
        rank=1,
        description="Restores 5% of max primeval essence, the foundation of your cultivation.",
        use=_use_essence_gathering_pill,
        subcategory="Essence Restoration",
    ),
    "Minor Cultivation Pill": Item(
        name="Minor Cultivation Pill",
        category="Pills",
        rank=1,
        description="Boosts cultivation, with a chance to gain 1 aptitude.",
        use=_use_green_leaf_qi_pill,
        subcategory="Cultivation Boost",
    ),
    "Cracked Aptitude Pill": Item(
        name="Cracked Aptitude Pill",
        category="Pills",
        rank=1,
        description="Permanently grants +0.1 to your qi multiplier.",
        use=_use_aperture_opening_pellet,
        subcategory="Qi Multiplier",
    ),
    "Dew Spirit Pellet": Item(
        name="Dew Spirit Pellet",
        category="Pills",
        rank=1,
        description="Condenses spirit dew into primeval essence.",
        use=_use_dew_spirit_pellet,
        subcategory="Essence Restoration",
    ),
    "Mortal Breakthrough Pill": Item(
        name="Mortal Breakthrough Pill",
        category="Pills",
        rank=1,
        description="Grants a large temporary cultivation boost for 30 minutes — a jolt to prime you for a breakthrough attempt.",
        use=_use_jade_spring_pill,
        subcategory="Qi Multiplier",
    ),
    "Primeval Essence Crystal": Item(
        name="Primeval Essence Crystal",
        category="Materials",
        description="A small crystallized shard of primeval essence, waiting to be absorbed.",
        use=_use_primeval_essence_crystal,
        subcategory="Essence",
    ),
}

# Beast Core and Beast Material tiers 1-7 — extended from the original Tier 1 Core /
# Tier 1-4 Material (dropped by beasts) up to 7 to match Ore/Herb/gear, for Blacksmith
# crafting. Tiers above what current monsters actually drop (see monsters.py) have no
# source yet — reserved for future higher-rank content, same as Tier 5-7 Ore/Herb were
# when /mine and /gather first shipped.
for _tier in range(1, 8):
    ITEMS[f"Tier {_tier} Beast Core"] = Item(
        name=f"Tier {_tier} Beast Core",
        category="Materials",
        description=f"The condensed vital energy of a slain Tier {_tier} beast. Used in Blacksmith crafting.",
        subcategory="Beast Material",
    )
    ITEMS[f"Tier {_tier} Beast Material"] = Item(
        name=f"Tier {_tier} Beast Material",
        category="Materials",
        description=f"Hide, bone, and sinew from a Tier {_tier} beast. Used in Blacksmith crafting.",
        subcategory="Beast Material",
    )
del _tier

# Ore (Miner) and Herb (Gatherer/Farmer) tiers 1-7 — generated rather than spelled out by
# hand since all 14 are mechanically identical (inert crafting/farming inputs, no `use`),
# differing only in tier.
for _tier in range(1, 8):
    ITEMS[f"Tier {_tier} Ore"] = Item(
        name=f"Tier {_tier} Ore",
        category="Materials",
        description=f"Raw tier {_tier} ore, mined from the earth. Used in Blacksmith crafting.",
        subcategory="Ore",
    )
    ITEMS[f"Tier {_tier} Herb"] = Item(
        name=f"Tier {_tier} Herb",
        category="Materials",
        description=f"A tier {_tier} medicinal herb. Used in Alchemist crafting, or grown further on a farm plot.",
        subcategory="Herb",
    )
del _tier

# Nascent Soul Avatar leveling materials (see game/avatar.py's AVATAR_LEVEL_UP_RECIPE) — fed
# through /avatar to level the avatar up, not self-consumed via /use like a pill. No source
# yet in Phase 1 (that's /split_body, a later phase), same honest gap Tier 5-7 Ore/Herb had
# before their own content caught up.
ITEMS["Soul Nourishing Pill"] = Item(
    name="Soul Nourishing Pill",
    category="Materials",
    description="A pill distilled for a cultivator's Nascent Soul avatar. Feed it through /avatar to strengthen the avatar.",
    subcategory="Avatar",
)
ITEMS["Soul Crystal"] = Item(
    name="Soul Crystal",
    category="Materials",
    description="A crystallized shard of soul essence. Feed it through /avatar alongside Soul Nourishing Pills to level up the avatar.",
    subcategory="Avatar",
)

# Regional named materials (see game/content/materials.py and the content expansion
# brief's section 9) — merged in the same aggregator style the brief itself recommends
# (section 24), so ITEMS stays the single source of truth callers already import from.
# Imported here rather than at module top since content/materials.py itself imports Item
# from this module — Item is already defined above by the time this line runs, so the
# import resolves cleanly with no circularity.
from .content.materials import VERDANT_MATERIALS  # noqa: E402
from .content.materials_hundred_beast_mountains import HUNDRED_BEAST_MOUNTAINS_MATERIALS  # noqa: E402
from .content.materials_crimson_furnace import CRIMSON_FURNACE_MATERIALS  # noqa: E402

ITEMS.update(VERDANT_MATERIALS)
ITEMS.update(HUNDRED_BEAST_MOUNTAINS_MATERIALS)
ITEMS.update(CRIMSON_FURNACE_MATERIALS)

# -- Alchemy-craftable pills (see /alchemy, game/alchemy.py) -------------------------------
# Generic names for now (real ones come later) — one item per (pill type, tier). Each of
# the 4 generic types costs 1 herb of the matching tier to craft; Pure Aptitude costs 2,
# since its guaranteed, no-side-effect aptitude gain is worth more than a chance at one.

CULTIVATION_BOOST_PILL_MULTIPLIER_PER_TIER = 0.05  # halved -- now multiplicative against a
# player's permanent qi_multiplier + character_bonus (see database.py's settle_qi/
# get_qi_status) instead of the old additive formula, so its real effect is much bigger per
# printed point than it used to be; halved to keep repeated Alchemist-crafted use from being
# as strong as Qi Sea Origin/Blood-Debt Ring's own gated, harder-to-repeat buffs.
CULTIVATION_BOOST_PILL_DURATION_SECONDS_BASE = 15 * 60
CULTIVATION_BOOST_PILL_DURATION_SECONDS_PER_TIER = 5 * 60

QI_MULTIPLIER_PILL_BONUS_PER_TIER = 0.05

ESSENCE_RESTORATION_PILL_PERCENT_PER_TIER = 0.05

APTITUDE_ENHANCING_PILL_CHANCE_PER_TIER = 0.05
APTITUDE_ENHANCING_PILL_MAX_CHANCE = 0.60

PURE_APTITUDE_PILL_AMOUNT_PER_TIER = 2

# Same 5%-per-tier rate as Essence Restoration above, applied to max_hp instead — a % heal
# stays proportionate regardless of how large max_hp grows with realm, so there's no
# analogous "cheap pill drains a runaway-large cap" balance issue to guard against here.
HEALING_PILL_PERCENT_PER_TIER = 0.05


def _use_cultivation_boost_pill(tier: int):
    def use(db: GameDatabase, user_id: int) -> str:
        bonus = CULTIVATION_BOOST_PILL_MULTIPLIER_PER_TIER * tier
        duration = CULTIVATION_BOOST_PILL_DURATION_SECONDS_BASE + CULTIVATION_BOOST_PILL_DURATION_SECONDS_PER_TIER * tier
        total_bonus, total_remaining = db.add_or_extend_cultivation_boost_buff(
            user_id, alchemy_pill_name("Cultivation Boost", tier), bonus, duration,
        )
        if total_remaining > duration:
            # Stacked onto an already-active buff of this SAME tier -- only the timer goes up
            # (the bonus is identical either way, since same-tier pills always grant the same
            # amount). A different tier is a completely separate, independently-timed buff --
            # see GameDatabase.add_or_extend_cultivation_boost_buff's own docstring.
            return (
                f"A wave of vigor floods your meridians — your **+{total_bonus:.2f} qi multiplier** buff "
                f"is extended to **{total_remaining // 60} minutes** remaining!"
            )
        return f"A wave of vigor floods your meridians — **+{bonus:.2f} qi multiplier** for {duration // 60} minutes!"
    return use


def _use_qi_multiplier_pill(tier: int):
    def use(db: GameDatabase, user_id: int) -> str:
        bonus = QI_MULTIPLIER_PILL_BONUS_PER_TIER * tier
        new_multiplier = db.add_qi_multiplier(user_id, bonus)
        return f"Your aperture widens permanently — **+{bonus:.2f}** qi multiplier (now x{new_multiplier:.2f})."
    return use


def _use_qi_ascension_pill(tier: int):
    def use(db: GameDatabase, user_id: int) -> str:
        result = db.use_qi_ascension_pill(user_id, tier)
        if not result["used"]:
            return (
                f"Your dantian resists — you've already used **{result['max_uses']}** Qi Ascension "
                f"Pills at your current Great Realm. Break through further to unlock more."
            )
        pct = db.QI_ASCENSION_PCT_PER_TIER * tier * 100
        return (
            f"Your qi aperture violently expands — qi multiplier surges **+{pct:.0f}%** to "
            f"**x{result['new_multiplier']:.2f}** ({result['uses']}/{result['max_uses']} used this realm)!"
        )
    return use


def _use_essence_restoration_pill(tier: int):
    def use(db: GameDatabase, user_id: int) -> str:
        percent = ESSENCE_RESTORATION_PILL_PERCENT_PER_TIER * tier
        restored, essence, max_essence = db.restore_essence_percent(user_id, percent)
        return f"Your primeval essence is replenished by **{restored}** ({essence}/{max_essence})."
    return use


def _use_aptitude_enhancing_pill(tier: int):
    def use(db: GameDatabase, user_id: int) -> str:
        chance = min(APTITUDE_ENHANCING_PILL_MAX_CHANCE, APTITUDE_ENHANCING_PILL_CHANCE_PER_TIER * tier)
        gained, new_aptitude = db.maybe_gain_aptitude(user_id, chance, amount=1)
        if gained:
            return f"Your comprehension deepens — **aptitude increased to {new_aptitude}**!"
        return "You feel a faint stirring, but your aptitude doesn't budge this time."
    return use


def _use_pure_aptitude_pill(tier: int):
    def use(db: GameDatabase, user_id: int) -> str:
        amount = PURE_APTITUDE_PILL_AMOUNT_PER_TIER * tier
        _, new_aptitude = db.maybe_gain_aptitude(user_id, 1.0, amount=amount)
        return f"Pure insight floods your mind — **aptitude increased to {new_aptitude}**!"
    return use


def _use_healing_pill(tier: int):
    def use(db: GameDatabase, user_id: int) -> str:
        percent = HEALING_PILL_PERCENT_PER_TIER * tier
        healed, hp, max_hp = db.heal_percent(user_id, percent)
        return f"Your wounds knit shut — healing **{healed} HP** ({hp}/{max_hp})."
    return use


def alchemy_pill_effect_text(pill_type: str, tier: int) -> str:
    """Human-readable numeric effect of a craftable pill at a given tier — mirrors the exact
    math each pill's `use` callback above applies, for display in /alchemy before crafting."""
    if pill_type == "Cultivation Boost":
        bonus = CULTIVATION_BOOST_PILL_MULTIPLIER_PER_TIER * tier
        duration = CULTIVATION_BOOST_PILL_DURATION_SECONDS_BASE + CULTIVATION_BOOST_PILL_DURATION_SECONDS_PER_TIER * tier
        return f"+{bonus:.2f} qi multiplier for {duration // 60} minutes."
    if pill_type == "Qi Multiplier":
        bonus = QI_MULTIPLIER_PILL_BONUS_PER_TIER * tier
        return f"Permanently +{bonus:.2f} qi multiplier."
    if pill_type == "Aptitude Enhancing":
        chance = min(APTITUDE_ENHANCING_PILL_MAX_CHANCE, APTITUDE_ENHANCING_PILL_CHANCE_PER_TIER * tier)
        return f"{chance * 100:.0f}% chance to gain 1 aptitude."
    if pill_type == "Pure Aptitude":
        amount = PURE_APTITUDE_PILL_AMOUNT_PER_TIER * tier
        return f"Guaranteed +{amount} aptitude."
    if pill_type == "Healing":
        percent = HEALING_PILL_PERCENT_PER_TIER * tier
        return f"Restores {percent * 100:.0f}% of max HP."
    return ""


_ALCHEMY_PILL_USE_FACTORIES = {
    "Cultivation Boost": _use_cultivation_boost_pill,
    "Qi Multiplier": _use_qi_multiplier_pill,
    "Aptitude Enhancing": _use_aptitude_enhancing_pill,
    "Pure Aptitude": _use_pure_aptitude_pill,
    "Healing": _use_healing_pill,
}

# Pure Aptitude shelves next to Aptitude Enhancing — both are about aptitude, they just
# differ in reliability/cost (see the module docstring above).
_ALCHEMY_PILL_SUBCATEGORY = {
    "Cultivation Boost": "Cultivation Boost",
    "Qi Multiplier": "Qi Multiplier",
    "Aptitude Enhancing": "Aptitude Enhancing",
    "Pure Aptitude": "Aptitude Enhancing",
    "Healing": "Healing",
}

ALCHEMY_PILL_TYPES = list(_ALCHEMY_PILL_USE_FACTORIES.keys())


def alchemy_pill_name(pill_type: str, tier: int) -> str:
    return f"{pill_type} Pill (T{tier})"


for _pill_type in ALCHEMY_PILL_TYPES:
    for _tier in range(1, 8):
        _name = alchemy_pill_name(_pill_type, _tier)
        ITEMS[_name] = Item(
            name=_name,
            category="Pills",
            rank=_tier,
            description=f"A Tier {_tier} {_pill_type.lower()} pill, brewed by an Alchemist.",
            use=_ALCHEMY_PILL_USE_FACTORIES[_pill_type](_tier),
            subcategory=_ALCHEMY_PILL_SUBCATEGORY[_pill_type],
        )
del _pill_type, _tier, _name

# Essence Restoration Pill -- moved OUT of the Alchemist-craftable table above (per explicit
# user request) into a rare bonus find instead (see roll_essence_restoration_pill_drop
# below, and its call sites in exploration.py/raid.py/manager.py's world boss, secret realm,
# dream realm, and battlefield reward resolution). Registered as its own small loop, same
# tier shape (1-7), same use()/effect math (ESSENCE_RESTORATION_PILL_PERCENT_PER_TIER,
# _use_essence_restoration_pill are both untouched) -- only how you OBTAIN one changed, not
# what it does once you have it.
for _tier in range(1, 8):
    _name = alchemy_pill_name("Essence Restoration", _tier)
    ITEMS[_name] = Item(
        name=_name,
        category="Pills",
        rank=_tier,
        description=f"A Tier {_tier} essence restoration pill. A rare find -- no Alchemist can brew this one.",
        use=_use_essence_restoration_pill(_tier),
        subcategory="Essence Restoration",
    )
del _tier, _name

# ~1.5% per applicable roll -- deliberately low since this same roll fires across SEVEN
# different sources (see this comment's own call sites), each already fairly frequent
# individually; a genuinely "rare drop" needs to stay rare in aggregate, not just per-source.
# Weighted toward lower tiers, same shape as this codebase's other tiered-rarity tables (see
# gathering.RESOURCE_TIER_WEIGHTS) -- finding one at all is already rare, a high tier on top
# of that should be rarer still.
ESSENCE_RESTORATION_PILL_DROP_CHANCE = 0.015
ESSENCE_RESTORATION_PILL_TIER_WEIGHTS = {1: 35, 2: 25, 3: 16, 4: 10, 5: 7, 6: 4, 7: 3}
# A second, independent long-shot layered on top of the base roll above -- almost always
# just 1 pill; getting 2 or (rarely) 3 at once is itself a bonus, not the common case.
ESSENCE_RESTORATION_PILL_QUANTITY_WEIGHTS = {1: 75, 2: 20, 3: 5}


def roll_essence_restoration_pill_drop(rng: Optional[random.Random] = None) -> Optional[Tuple[str, int]]:
    """Independent rare-drop roll, called once per applicable reward moment (an /explore
    node, a /hunt or /raid kill, a World Boss contributor's guaranteed payout, a Secret
    Realm/Dream Realm discovery step, a battlefield wave/final reward). Returns
    (item_name, quantity) for an "Essence Restoration Pill (T{tier})", or None most of the
    time -- quantity is almost always 1, see ESSENCE_RESTORATION_PILL_QUANTITY_WEIGHTS."""
    r = rng or random
    if r.random() >= ESSENCE_RESTORATION_PILL_DROP_CHANCE:
        return None
    tiers = list(ESSENCE_RESTORATION_PILL_TIER_WEIGHTS.keys())
    tier_weights = list(ESSENCE_RESTORATION_PILL_TIER_WEIGHTS.values())
    tier = r.choices(tiers, weights=tier_weights, k=1)[0]
    quantities = list(ESSENCE_RESTORATION_PILL_QUANTITY_WEIGHTS.keys())
    quantity_weights = list(ESSENCE_RESTORATION_PILL_QUANTITY_WEIGHTS.values())
    quantity = r.choices(quantities, weights=quantity_weights, k=1)[0]
    return alchemy_pill_name("Essence Restoration", tier), quantity


# Qi Ascension Pill -- never Alchemist-craftable (unlike the flat, additive Qi Multiplier
# Pill above, this one MULTIPLIES qi_multiplier, so a reliable herb-and-brew supply would
# undermine its own per-realm use cap almost immediately). Rare drop only, per explicit
# request, from /search_forgotten_blessed_land, /explore, and World Boss specifically (see
# this function's own call sites) -- deliberately NOT wired into hunt/raid/secret realm/
# dream realm/battlefield the way Essence Restoration Pill is, since this pill's own
# use_qi_ascension_pill cap already bounds how much benefit stacking up a big stockpile
# can buy; a narrower drop pool keeps it a genuinely occasional find on top of that.
# Shelved under the existing "Qi Multiplier" subcategory rather than a new one -- see
# feedback_shared_category_lists_row_budget.md: growing a shared subcategory list can
# silently blow out row budget in OTHER, unrelated renderers.
for _tier in range(1, 8):
    _name = alchemy_pill_name("Qi Ascension", _tier)
    ITEMS[_name] = Item(
        name=_name,
        category="Pills",
        rank=_tier,
        description=(
            f"A Tier {_tier} Qi Ascension Pill. MULTIPLIES your qi multiplier by "
            f"+{GameDatabase.QI_ASCENSION_PCT_PER_TIER * _tier * 100:.0f}% per use instead of adding to it -- "
            f"capped at {GameDatabase.QI_ASCENSION_MAX_USES_PER_RANK} uses per Great Realm. A rare find -- no Alchemist can brew this one."
        ),
        use=_use_qi_ascension_pill(_tier),
        subcategory="Qi Multiplier",
    )
del _tier, _name

QI_ASCENSION_PILL_DROP_CHANCE = 0.01
QI_ASCENSION_PILL_TIER_WEIGHTS = {1: 35, 2: 25, 3: 16, 4: 10, 5: 7, 6: 4, 7: 3}


def roll_qi_ascension_pill_drop(rng: Optional[random.Random] = None) -> Optional[Tuple[str, int]]:
    """Independent rare-drop roll -- see this module's own comment just above for why this
    pill is drop-only and only from /search_forgotten_blessed_land, /explore, and World Boss.
    Returns (item_name, quantity) for a "Qi Ascension Pill (T{tier})", always quantity 1
    (no multi-drop bonus roll, unlike Essence Restoration -- this pill is strong enough per
    unit that stacking bonus quantities isn't worth the risk of a lucky multi-drop)."""
    r = rng or random
    if r.random() >= QI_ASCENSION_PILL_DROP_CHANCE:
        return None
    tiers = list(QI_ASCENSION_PILL_TIER_WEIGHTS.keys())
    tier_weights = list(QI_ASCENSION_PILL_TIER_WEIGHTS.values())
    tier = r.choices(tiers, weights=tier_weights, k=1)[0]
    return alchemy_pill_name("Qi Ascension", tier), 1


ITEM_CATEGORIES = ["Healing", "Pills", "Materials"]

# The top-level "Healing" category (Minor Recovery Pill etc.) has too few items to need
# splitting further -- distinct from the "Healing" alchemy pill type below, whose crafted
# Tier 1-7 pills live under the "Pills" category with their own Healing subcategory (see
# items.py's _use_healing_pill/_ALCHEMY_PILL_SUBCATEGORY) and need a button here to actually
# be reachable in /inventory -- this list was never updated when that pill type was added.
PILL_SUBCATEGORIES = ["Cultivation Boost", "Qi Multiplier", "Aptitude Enhancing", "Essence Restoration", "Healing"]

# Materials grew large enough (beast parts + 7 ore tiers + 7 herb tiers + essence) to need
# splitting the same way Pills did. Beast Trophy/Alchemy Root were added later via
# game/content/materials*.py and never got added here -- without them, /inventory, /profile,
# and /trade all silently strand those 23 items with no subcategory button to reach them.
MATERIAL_SUBCATEGORIES = ["Ore", "Herb", "Beast Material", "Beast Trophy", "Alchemy Root", "Essence", "Avatar"]


def items_in_category(category: str, subcategory: Optional[str] = None):
    return [
        item for item in ITEMS.values()
        if item.category == category and (subcategory is None or item.subcategory == subcategory)
    ]


def subcategories_in_category(category: str):
    if category == "Pills":
        return PILL_SUBCATEGORIES
    if category == "Materials":
        return MATERIAL_SUBCATEGORIES
    return []


def item_effective_tier(item: "Item") -> Optional[int]:
    """Crafted Pills carry an explicit `rank`; Materials (Ore/Herb/Beast Material/...) don't --
    their tier lives only in the item NAME instead (see gathering.item_tier's "Tier N ..."
    parse). This normalizes both into one tier lookup for anything that needs to compare items
    across that split -- currently just the Transformation Dao Path's /transmute."""
    if item.rank is not None:
        return item.rank
    return gathering.item_tier(item.name)


CATEGORY_EMOJI = {"Healing": "🩹", "Pills": "💊", "Materials": "📦"}
SUBCATEGORY_EMOJI = {
    "Cultivation Boost": "⚡", "Qi Multiplier": "✨", "Aptitude Enhancing": "🧠", "Essence Restoration": "💧",
    "Healing": "🩹", "Ore": "⛏️", "Herb": "🌿", "Beast Material": "🐗", "Essence": "💎", "Avatar": "👻",
    "Beast Trophy": "🏆", "Alchemy Root": "🌱",
}


def item_emoji(item_name: str) -> str:
    """Best-effort display emoji for an ITEMS entry — subcategory beats category, falling
    back to a generic box for anything uncategorized. Equipment (weapons/armor/Gu/etc — a
    separate catalog) has its own lookup, keyed by slot_type — see equipment.SLOT_TYPE_EMOJI."""
    item = ITEMS.get(item_name)
    if item is None:
        return "📦"
    if item.subcategory and item.subcategory in SUBCATEGORY_EMOJI:
        return SUBCATEGORY_EMOJI[item.subcategory]
    return CATEGORY_EMOJI.get(item.category, "📦")


# -- /sell (NPC vendor "garbage dump") -------------------------------------------------------
# Per-unit spirit-stone price the /sell vendor pays for an ordinary ITEMS entry. Deliberately
# below every other liquidation rate in the game (blacksmith.DISMANTLE_STONES_PER_TIER=30,
# manager.SALVAGE_STONES_PER_RANK_RARITY_STAR=15, equipment.GU_BREAKDOWN_VALUE_PER_STAR=20) so
# this reads as decluttering, not a competing farm loop.
SELL_STONES_PER_TIER = 8        # "Tier N ..." named items (gathering.item_tier) -- Ore/Herb/Beast Core/Beast Material
SELL_STONES_PER_RANK = 10       # Item.rank 1-7 (Pills)
SELL_STONES_FLAT_FALLBACK = 5   # no tier, no rank -- Beast Trophy/Alchemy Root regionals, Minor Recovery Pill, etc.


def sell_value(item_name: str) -> int:
    """Per-unit price /sell pays for one ordinary ITEMS entry. Tier (parsed from the item's
    own name) beats rank beats a flat fallback -- the same precedence order gathering.item_tier's
    own callers already use elsewhere."""
    tier = gathering.item_tier(item_name)
    if tier is not None:
        return SELL_STONES_PER_TIER * tier
    item = ITEMS.get(item_name)
    if item is not None and item.rank is not None:
        return SELL_STONES_PER_RANK * item.rank
    return SELL_STONES_FLAT_FALLBACK
