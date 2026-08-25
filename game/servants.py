"""
Servants -- a Reverend-Insanity-inspired gacha/collection system. Admin-only for now (see
/servant in cog.py) while the design is validated against real play. T1-T5 are generic
cultivator archetypes (e.g. "Qi Condensation Gu Apprentice"); T6-T7 are specific named characters (e.g.
"Fang Yuan") drawn loosely from the reference doc's own cast -- exact names/flavor are a
placeholder roster, meant to be confirmed/replaced later, not final art-of-record.

Pure data/logic, no DB/GameManager/discord dependency -- same split as grotto.py/world_boss.py.

Deliberately does NOT reuse chargen.py's SCARCE_TIER_NAMES/_unique_pool single-holder-per-name
scarcity model. That model removes a claimed name from the roll pool for EVERYONE (including
its own holder) the moment it's first claimed, which would make it impossible to ever roll a
duplicate of a named T6/T7 servant again -- directly breaking the star-up system, which needs
duplicates at every tier, T6/T7 included. Every name here is always re-rollable by anyone, any
number of times; T6/T7 are simply rare via TIER_WEIGHTS (and, within T7, via within_tier_weight
-- Fang Yuan is deliberately the rarest name IN T7, not just gated by T7's own 0.1% tier odds).
"""

import random
from dataclasses import dataclass
from typing import Dict, List, Optional

from . import avatar

# One distinct color-circle emoji per tier, for at-a-glance scanning in the Roster/Star Up/
# Equip/Automation selects and embeds -- T1 (common) through T7 (rarest).
TIER_EMOJI: Dict[int, str] = {1: "⚪", 2: "🟢", 3: "🔵", 4: "🟣", 5: "🟠", 6: "🔴", 7: "⚫"}


def tier_label(tier: int) -> str:
    return f"{TIER_EMOJI.get(tier, '')} T{tier}"


@dataclass
class Servant:
    name: str
    tier: int
    role_flavor: str
    description: str
    base_stats: Dict[str, float]
    support_bonus_key: str
    within_tier_weight: int
    image_url: Optional[str] = None  # left None throughout -- filled in later by hand


# Level-1(★1) foundation-stat point budget per tier -- scaled by STAR_STAT_MULTIPLIER per star
# level (see scaled_stat_bonuses), same tapering-growth idea as every other tiered magnitude
# table in this codebase (grotto.GROTTO_LEVEL_MULTIPLIER, avatar.AVATAR_LEVEL_MULTIPLIER).
TIER_STAT_BUDGET: Dict[int, int] = {1: 6, 2: 12, 3: 22, 4: 40, 5: 75, 6: 160, 7: 350}


def _stats(tier: int, primary: str, secondary: Optional[str] = None) -> Dict[str, float]:
    budget = TIER_STAT_BUDGET[tier]
    if secondary:
        return {primary: round(budget * 0.7), secondary: round(budget * 0.3)}
    return {primary: budget}


SERVANT_CATALOG: Dict[str, Servant] = {}


def _register(*rows: Servant):
    for row in rows:
        SERVANT_CATALOG[row.name] = row


# -- Tier 1-5: generic cultivator archetypes -------------------------------------------------

_register(
    Servant("Fog Valley Disciple", 1, "Outer Sect Disciple", "A minor disciple from a fog-shrouded valley sect, still finding their Dao.", _stats(1, "qi_stat", "luck_stat"), "cultivation_speed_pct", 30, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541632518569336902/content.png?ex=6a8e4caa&is=6a8cfb2a&hm=d2a72aa4be466ae673ae6780e606dc66545241f96324b756dce6e2e200b263e5&"),
    Servant("Green Bull Clan Warrior", 1, "Clan Warrior", "A young warrior of the Green Bull Clan, blooded in border skirmishes.", _stats(1, "str_stat", "atk_stat"), "stone_reward_bonus_pct", 30, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541633145294692412/content.png?ex=6a8e4d3f&is=6a8cfbbf&hm=9010e88ecf392f28c4632f887ca97c66af32fa4aa7ab5c81dc448ee2ed974bca&"),
    Servant("Wild Root Scavenger", 1, "Wilderness Scavenger", "Survives on the fringes of civilization, foraging rare roots and herbs.", _stats(1, "spd_stat", "luck_stat"), "loot_chance_bonus_pct", 25, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541633499965169804/content.png?ex=6a8e4d94&is=6a8cfc14&hm=95008583e008daa833b9d0f4c24a412cfbe85eff5505a48f7147a8a122d1237b&"),
    Servant("Qi Condensation Gu Apprentice", 1, "Gu Apprentice", "A cultivator at the Qi Condensation realm, only just beginning to sense the Gu world's true scale.", _stats(1, "hp", "qi_stat"), "essence_regen_pct", 25, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541634341749399603/content.png?ex=6a8e4e5d&is=6a8cfcdd&hm=5b99c0f8b7a30231e09b71af136ee9615851d586ec031ddf91f8ae7dc77a7803&"),

    Servant("Rank Three Sect Elder", 2, "Sect Elder", "An elder of a minor sect, steady and well-versed in Gu lore.", _stats(2, "def_stat", "hp"), "mining_yield_pct", 25, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541634728417951794/content.png?ex=6a8e4eb9&is=6a8cfd39&hm=5ea4f3b3e85bd7c7ac357ad40b78d4dea4022bd4c643e4b6614837c114757989&"),
    Servant("Beast-Blood Warrior", 2, "Beast-Blood Warrior", "Has refined a beast-blood Gu into their own body, gaining ferocious strength.", _stats(2, "atk_stat", "str_stat"), "herb_yield_pct", 25, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541634997599993886/content.png?ex=6a8e4ef9&is=6a8cfd79&hm=366a1caa7b558ee32c38645fde015057fc74ff78cc484bcb512bec8cad362d95&"),
    Servant("Foundation Establishment Gu Master", 2, "Gu Master", "A Gu Master at the Foundation Establishment realm, commanding a modest collection of refined Gu.", _stats(2, "qi_stat", "atk_stat"), "cultivation_speed_pct", 20, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541635807641862254/content.png?ex=6a8e4fba&is=6a8cfe3a&hm=c7b0299bf4038d766a664e8f157758260adc436e7ba89daf13d3b81fcc20f0aa&"),
    Servant("Iron Fist Ancestor", 2, "Clan Ancestor", "A retired clan champion, fists still capable of shattering stone.", _stats(2, "str_stat", "def_stat"), "stone_reward_bonus_pct", 20, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541636310630932540/content.png?ex=6a8e5032&is=6a8cfeb2&hm=d86075d19fa99a688a54beb2f95d98482ad542c86d3709d4e49598a8aa9d84d9&"),

    Servant("Rank Four Sect Master", 3, "Sect Master", "Leads a mid-sized sect, balancing politics and cultivation.", _stats(3, "hp", "def_stat"), "loot_chance_bonus_pct", 20, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541636638525100095/content.png?ex=6a8e5080&is=6a8cff00&hm=f8a90805920f2d0496ca6c64d96172ae4eac25a25347c4110f0c55b9cc745ae7&"),
    Servant("Core Formation Gu Immortal", 3, "Gu Immortal", "A Gu Immortal at the Core Formation realm, their Dao Marks beginning to stabilize.", _stats(3, "qi_stat", "luck_stat"), "essence_regen_pct", 20, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541637070164861068/content.png?ex=6a8e50e7&is=6a8cff67&hm=7ba00d689f1da60788a4f355b46b20e28ed0cea975a04511f82c8714268d765f&"),
    Servant("Blood Sea Vanguard", 3, "Blood Sea Vanguard", "A vanguard fighter of the Blood Sea faction, fast and merciless.", _stats(3, "atk_stat", "spd_stat"), "mining_yield_pct", 15, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541637418590011432/content.png?ex=6a8e513a&is=6a8cffba&hm=10f2800fd19b94a28583fe28047d545118a0fc5d9870953e5e547cf9cf80f666&"),
    Servant("Nascent Gu Ancestor", 3, "Clan Ancestor", "An ancestor whose foundation has only just stabilized at this rank.", _stats(3, "def_stat", "qi_stat"), "herb_yield_pct", 15, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541637791929081977/content.png?ex=6a8e5193&is=6a8d0013&hm=33f4cddcbb540840e1c121c4aa1a073f65a6f0771fe364596ca428011dcc3e3a&"),

    Servant("Rank Five Small Clan Ancestor", 4, "Clan Ancestor", "The pillar of a small clan, their strength a matter of local legend.", _stats(4, "hp", "str_stat"), "cultivation_speed_pct", 15, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541650115796934666/content.png?ex=6a8e5d0e&is=6a8d0b8e&hm=8ab3a34accc3aec6f27e8af56857b740ba2f3ad80f8059f3f9292b4b83be2cea&"),
    Servant("Nascent Soul Gu Immortal", 4, "Gu Immortal", "A Gu Immortal at the Nascent Soul realm, wielding a well-rounded Gu collection.", _stats(4, "qi_stat", "atk_stat"), "stone_reward_bonus_pct", 15, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541637791929081977/content.png?ex=6a8e5193&is=6a8d0013&hm=33f4cddcbb540840e1c121c4aa1a073f65a6f0771fe364596ca428011dcc3e3a&"),
    Servant("Frost Sect Elder Ancestor", 4, "Sect Elder Ancestor", "An elder ancestor of a frost-aligned sect, cold and unshakeable.", _stats(4, "def_stat", "spd_stat"), "loot_chance_bonus_pct", 10, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541649603986980914/content.png?ex=6a8e5c94&is=6a8d0b14&hm=eb5a755c7fc7f65f0ec1e1158c3c1ffb1265f6e3efbf0ad377f49ae6277898f9&"),

    Servant("Rank Five Great Clan Ancestor", 5, "Great Clan Ancestor", "The founding pillar of a great clan, revered across the region.", _stats(5, "hp", "def_stat"), "essence_regen_pct", 10, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541638130740895814/content.png?ex=6a8e51e4&is=6a8d0064&hm=448817ddd4b9c23cfc956dbf25a6c4c9a24ee58424727e17c39832e9a633df10&"),
    Servant("Spirit Severing Gu Immortal", 5, "Gu Immortal", "A Gu Immortal at the Spirit Severing realm, their Dao Marks nearly complete.", _stats(5, "qi_stat", "str_stat"), "mining_yield_pct", 10, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541638434127618059/content.png?ex=6a8e522c&is=6a8d00ac&hm=9a0f1b54daf85fa35838e8676aa2aff171c2cebb0e0566c100f795aa0e1906a1&"),
    Servant("True Ancestor of a Thousand Gu", 5, "True Ancestor", "Has refined a thousand Gu across their long, storied life.", _stats(5, "atk_stat", "luck_stat"), "herb_yield_pct", 6, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541639189945253988/content.png?ex=6a8e52e1&is=6a8d0161&hm=5055944c20fe677c787da6617c84d24c3967072107e9665424cb24e93325b30f&"),
)

# -- Tier 6-7: specific named characters -- PLACEHOLDER roster, confirm final names/spelling
# against the user's own reference doc before treating this as final. within_tier_weight is
# deliberately steep at the top of T7 -- Fang Yuan's 8/100 share of T7 pulls (8%) makes him
# roughly 0.1% * 8% = 0.008% of ALL summons, meaningfully rarer than a common T6 name. ---------

_register(
    Servant("Weeping Blood Trench Ancestor", 6, "Trench Ancestor", "A fearsome ancestor of the Weeping Blood Trench, wreathed in old grudges.", _stats(6, "hp", "atk_stat"), "cultivation_speed_pct", 26, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541640481207881728/content.png?ex=6a8e5415&is=6a8d0295&hm=c22b6d8444381eeb25ab6d16f72499cc2eb463ec86f7e6b6c5cf6634018b7f40&"),
    Servant("Gu Yue Qing Shu", 6, "Gu Immortal Elder", "A brilliant, calculating Gu Immortal Elder, rarely caught off guard.", _stats(6, "qi_stat", "luck_stat"), "cultivation_speed_pct", 24, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541644278495715358/content.png?ex=6a8e579e&is=6a8d061e&hm=06178c438b305c769f99d2848ee962ed59da2d32006b680dfec29a5aa52f6041&"),
    Servant("Nine Distortion Wolf Ancestor", 6, "Wolf Clan Ancestor", "Leader of the Nine Distortion Wolf pack, blindingly fast in a hunt.", _stats(6, "spd_stat", "atk_stat"), "stone_reward_bonus_pct", 20, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541641298987978913/content.png?ex=6a8e54d7&is=6a8d0357&hm=9e3a13b69cbffbb46809425206f91d9ff0c572948b33ddc707c508d3ba6d9882&"),
    Servant("Meng Hu", 6, "Wolf King", "The Wolf King, brash and overwhelmingly powerful in a straight fight.", _stats(6, "str_stat", "atk_stat"), "loot_chance_bonus_pct", 16, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541641747942080522/content.png?ex=6a8e5543&is=6a8d03c3&hm=165d7ea7cbc94b17dbf4484391964d83e9d95552d9940a2217899300fdc62117&"),
    Servant("Chi You Furnace Ancestor", 6, "Furnace Ancestor", "Wields a body tempered like a furnace, radiating battle intent.", _stats(6, "atk_stat", "hp"), "cultivation_speed_pct", 14, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541643670762168370/content.png?ex=6a8e570d&is=6a8d058d&hm=65fc7132358337715c89874a926a6a191430da7a77caa7e98461f343c9102a5c&"),

    Servant("Wu Yong", 7, "Scheme Immortal", "A master of long cons and longer memories, always several moves ahead.", _stats(7, "luck_stat", "qi_stat"), "loot_chance_bonus_pct", 38, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541645329315922060/content.png?ex=6a8e5898&is=6a8d0718&hm=91e147c511943cc95fdb522f5a20ed7a5ba5d43eaf634487dcd5ac06ace42de7&"),
    Servant("Bai Ning Bing", 7, "Frost Immortal", "An icy, calculating Gu Immortal, feared for her patience as much as her power.", _stats(7, "qi_stat", "def_stat"), "essence_regen_pct", 32, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541642727073251438/content.png?ex=6a8e562c&is=6a8d04ac&hm=06d872e63b4b0c8e1f27e90092aa27ee8047f5db8a5a228416e39aec481e06e6&"),
    Servant("Hei Lou Lan", 7, "Gu Immortal Elder", "A reserved, unshakeable Gu Immortal Elder, said to have weathered calamities that broke lesser cultivators.", _stats(7, "hp", "def_stat"), "mining_yield_pct", 22, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541646117752537149/content.png?ex=6a8e5954&is=6a8d07d4&hm=2d8d1ea163b2ffba572f9c7c384b1ac44fea71cfe3f6ba52a6dab2af79ecfe09&"),
    Servant("Fang Yuan", 7, "Grand Supreme Elder Gu Immortal", "The rarest of the rare -- a Gu Immortal whose foresight spans centuries.", _stats(7, "qi_stat", "atk_stat"), "stone_reward_bonus_pct", 8, image_url="https://cdn.discordapp.com/attachments/427580710530973706/1541646510037405716/content.png?ex=6a8e59b2&is=6a8d0832&hm=f6a5f0d0368ecf78bbcbc5bf6ee1690159252546054fec94e578a794fc360fbc&"),
)


SERVANTS_BY_TIER: Dict[int, List[str]] = {}
for _servant in SERVANT_CATALOG.values():
    SERVANTS_BY_TIER.setdefault(_servant.tier, []).append(_servant.name)
del _servant


# -- Summon roll -- reuses world_boss.py's exact weighted-roll shape (random.choices over a
# fixed [(name, weight)] list) for both the tier roll and the within-tier name roll. -----------

TIER_WEIGHTS: Dict[int, float] = {1: 36.9, 2: 26, 3: 18, 4: 12, 5: 6, 6: 1, 7: 0.1}


def roll_tier(rng: Optional[random.Random] = None) -> int:
    r = rng or random
    tiers = list(TIER_WEIGHTS.keys())
    weights = list(TIER_WEIGHTS.values())
    return r.choices(tiers, weights=weights, k=1)[0]


def roll_named_servant(tier: int, rng: Optional[random.Random] = None) -> str:
    """Used by BOTH the main summon roll and evolution (a maxed T5/T6 servant rolling its new
    T6/T7 identity) -- same weighted roll, just fixed to a specific tier."""
    names = SERVANTS_BY_TIER[tier]
    weights = [SERVANT_CATALOG[n].within_tier_weight for n in names]
    return (rng or random).choices(names, weights=weights, k=1)[0]


def roll_servant(rng: Optional[random.Random] = None) -> str:
    return roll_named_servant(roll_tier(rng), rng)


# -- Summon currencies -- Spirit Stones is primary; the other two are ALTERNATIVES, not a
# simultaneous multi-currency requirement (see GameManager.summon_servant). Essence Pills/Manual
# Pages were dropped as summon currencies per explicit request (kept as valid Level-up-adjacent
# ideas, but not this) -- Beast Cores took their place instead. -----------------------------------

CURRENCY_STONES = "stones"
CURRENCY_ESSENCE_CRYSTALS = "essence_crystals"
CURRENCY_BEAST_CORES = "beast_cores"
SUMMON_CURRENCIES = (CURRENCY_STONES, CURRENCY_ESSENCE_CRYSTALS, CURRENCY_BEAST_CORES)

# Retuned 2026-08-24 against a REAL live spirit-stones leaderboard (top player ~38.9M stones) --
# the original 5,000 let the richest player buy ~7,800 pulls (effectively unlimited spam, would
# statistically farm multiple T7s through sheer volume). 100,000 keeps even a whale's spree
# bounded (~390 pulls, ~39% expected chance at a single T7) while most solidly-progressed
# players can only afford a small handful -- a real, felt cost per pull. Essence Crystals scaled
# by the same ~20x factor so it can't quietly become the "actually cheap" loophole currency.
SUMMON_COST_STONES = 100_000
SUMMON_COST_ESSENCE_CRYSTALS = 1000  # "Primeval Essence Crystal" -- flat untiered Materials item
SUMMON_COST_BEAST_CORES = 20         # "Tier {N} Beast Core", any tier, spent lowest-tier-first

SUMMON_CURRENCY_COST = {
    CURRENCY_STONES: SUMMON_COST_STONES,
    CURRENCY_ESSENCE_CRYSTALS: SUMMON_COST_ESSENCE_CRYSTALS,
    CURRENCY_BEAST_CORES: SUMMON_COST_BEAST_CORES,
}

PRIMEVAL_ESSENCE_CRYSTAL = "Primeval Essence Crystal"


# -- Star-up (within a tier, ★1->★7) -- adapts equipment.GU_UPGRADE_DUPLICATES_REQUIRED's shape
# but floors at 1 instead of 2, since star-up KEEPS the leveling instance and only consumes
# EXTRA copies as pure fuel (unlike Gu fusion, which destroys both copies to make a new one). --

MAX_STAR_LEVEL = 7
STAR_UP_DUPLICATES_REQUIRED: Dict[int, int] = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3}  # keyed by CURRENT star level
STAR_STAT_MULTIPLIER: Dict[int, float] = {1: 1.00, 2: 1.15, 3: 1.30, 4: 1.50, 5: 1.75, 6: 2.00, 7: 2.30}


# -- Level -- a SEPARATE progression axis from Star: fed with materials/resources (see below)
# rather than duplicate copies, so it advances even a lone, dupe-less copy of a servant. Reuses
# avatar.py's own 1-10 ladder/multiplier curve directly ("feed the avatar level up material"
# per explicit request), scaled by the servant's tier.

SERVANT_MAX_LEVEL = avatar.AVATAR_MAX_LEVEL  # 10, same ladder as Nascent Soul Avatar
LEVEL_STAT_MULTIPLIER = avatar.AVATAR_LEVEL_MULTIPLIER  # same tapering-growth curve, reused directly

SOUL_NOURISHING_PILL = avatar.SOUL_NOURISHING_PILL
SOUL_CRYSTAL = avatar.SOUL_CRYSTAL
LEVEL_UP_STONES_BASE = 3000  # per (tier * target level) step -- mirrors Grotto's Hairy Man dual pill+crystal+stones cost shape


def level_up_recipe(tier: int, current_level: int) -> Optional[Dict[str, int]]:
    """Soul Nourishing Pill / Soul Crystal cost to reach current_level+1 -- avatar.py's own
    recipe shape, scaled up by this servant's tier (a T7 costs 7x what a T1 does at the same
    level). None once already at SERVANT_MAX_LEVEL."""
    base_recipe = avatar.level_up_recipe(current_level)
    if base_recipe is None:
        return None
    return {item: qty * tier for item, qty in base_recipe.items()}


def level_up_stones_cost(tier: int, current_level: int) -> int:
    return LEVEL_UP_STONES_BASE * tier * (current_level + 1)


# -- Affinity -- grows passively the longer a servant stays EQUIPPED (Support or Combat),
# tracked as accumulated real seconds (servant_instances.affinity_seconds), lazily settled --
# see GameManager.equip_servant/unequip_servant and servants.current_affinity_seconds. Persists
# through star-ups automatically (same instance row) and is explicitly carried forward through
# evolution (see GameManager.evolve_servant) -- an accrued bond/investment, not tied to the
# servant's raw star/tier identity.

AFFINITY_CAP_SECONDS = 30 * 24 * 3600  # 30 real days equipped to reach max affinity
AFFINITY_MAX_BONUS_PCT = 0.20          # +20% multiplier on top of star/level at full affinity


def affinity_multiplier(affinity_seconds: int) -> float:
    ratio = min(1.0, max(0, affinity_seconds) / AFFINITY_CAP_SECONDS)
    return 1.0 + AFFINITY_MAX_BONUS_PCT * ratio


def current_affinity_seconds(instance: dict, now: int) -> int:
    """Lazy settlement, same shape as gu_pet's own satiety calc -- affinity_seconds is only
    ever a snapshot; while equipped_since_ts is set (the servant is CURRENTLY slotted), the
    live total also includes time elapsed since that snapshot."""
    equipped_since = instance.get("affinity_equipped_since_ts")
    base = instance.get("affinity_seconds", 0) or 0
    if not equipped_since:
        return base
    return base + max(0, now - equipped_since)


def scaled_stat_bonuses(servant: Servant, star_level: int, level: int = 1, affinity_seconds: int = 0) -> Dict[str, float]:
    mult = STAR_STAT_MULTIPLIER[star_level] * LEVEL_STAT_MULTIPLIER.get(level, 1.0) * affinity_multiplier(affinity_seconds)
    return {key: value * mult for key, value in servant.base_stats.items()}


# Support slot's own themed utility % -- scales with tier (bigger at T6/T7), star level, servant
# level, and affinity.
SUPPORT_BASE_PCT: Dict[int, float] = {1: 0.010, 2: 0.015, 3: 0.020, 4: 0.030, 5: 0.040, 6: 0.055, 7: 0.075}


def support_special_pct(servant: Servant, star_level: int, level: int = 1, affinity_seconds: int = 0) -> float:
    return (
        SUPPORT_BASE_PCT[servant.tier]
        * STAR_STAT_MULTIPLIER[star_level]
        * LEVEL_STAT_MULTIPLIER.get(level, 1.0)
        * affinity_multiplier(affinity_seconds)
    )


# support_bonus_key values that are NOT part of GameManager.SPECIAL_BONUS_KEYS -- mine/gather/
# farm never read that generic pool (see GameManager._grotto_yield_bonus's own comment), so a
# Support servant flavored around gathering needs its own direct-wired read instead
# (GameManager._servant_yield_bonus) rather than riding compute_equipment_bonuses.
YIELD_BONUS_KEYS = ("mining_yield_pct", "herb_yield_pct")

# support_bonus_key values that must be EXCLUDED from compute_equipment_bonuses' generic
# special pool entirely (not just left unread) -- cultivation_speed_pct is folded into
# database.py's _qi_rate_components instead (the REAL qi-rate hook; the generic pool is
# display-only and gets wholesale OVERWRITTEN by qi_status["manual_bonus"] later in that same
# function, so leaving it in the per-slot loop would be silently discarded dead weight, not a
# double-count -- see that function's own comment trail, which this exact trap has already hit
# for avatar gear/soul, Gu Pet, and Grotto).
SUPPORT_KEYS_OUTSIDE_GENERIC_POOL = YIELD_BONUS_KEYS + ("cultivation_speed_pct",)


# -- Evolution -- a maxed (★7) T5 or T6 servant can evolve into a freshly-rolled T6/T7 named
# servant (a full identity swap, not a fixed mapping -- see roll_named_servant above). ----------

EVOLVABLE_TIERS = (5, 6)


def can_evolve(tier: int, star_level: int) -> bool:
    return tier in EVOLVABLE_TIERS and star_level >= MAX_STAR_LEVEL


# -- Collection bonus -- a passive % just for owning distinct servants beyond your 2 equipped
# slots, per distinct NAME owned (duplicate/star-up-fuel copies of the same name don't count
# twice -- see GameDatabase.count_distinct_servant_names). ---------------------------------------

COLLECTION_BONUS_PCT_PER_UNIQUE = 0.005
COLLECTION_BONUS_CAP_PCT = 0.25  # caps at 50 distinct names owned


def collection_bonus_pct(distinct_names_owned: int) -> float:
    return min(distinct_names_owned * COLLECTION_BONUS_PCT_PER_UNIQUE, COLLECTION_BONUS_CAP_PCT)


# -- Support / Combat equip slots -- new slot_key values on the existing `equipped` table, NOT
# added to equipment.SLOTS (that list drives the generic gear-equip picker; Servant slots get
# their own dedicated UI in servant_view.py instead). --------------------------------------------

SLOT_KEY_SUPPORT = "servant_support"
SLOT_KEY_COMBAT = "servant_combat"
SERVANT_SLOT_KEYS = (SLOT_KEY_SUPPORT, SLOT_KEY_COMBAT)

# Support slot trades half its scaled base_stats for its support_bonus_key at full value --
# Combat slot is a pure stat stick at full scaled base_stats.
SUPPORT_STAT_FRACTION = 0.5


# -- Automation -- a servant IS both the identity and the worker at once (unlike Grotto's Ink/
# Hairy Men, which are separately-recruited units); automation_duty/automation_next_tick_ts live
# directly on the servant_instances row. See GameManager.assign_servant_duty/check_and_
# complete_servant_automation. ---------------------------------------------------------------

DUTY_MINE = "mine"
DUTY_GATHER = "gather"
DUTY_FARM = "farm"
AUTOMATION_DUTIES = (DUTY_MINE, DUTY_GATHER, DUTY_FARM)

MAX_AUTOMATION_SERVANTS = 3                        # mirrors grotto.GROTTO_MAX_INK_MEN's cap shape
AUTOMATION_TICK_INTERVAL_SECONDS = 24 * 3600        # one cycle/real day, same cadence as Ink/Hairy Men

# Automation YIELD scaling -- higher tier/star/level/affinity means a meaningfully BETTER
# automated worker, not just eligibility to work at all (see GameManager.check_and_complete_
# servant_automation). Same STAR_STAT_MULTIPLIER/LEVEL_STAT_MULTIPLIER/affinity_multiplier
# compounding stack as scaled_stat_bonuses/support_special_pct (up to ~8x at ★7/Lv10/max
# affinity), applied on top of a per-tier base -- a fully-invested T7 roughly DOUBLES yield;
# a fully-invested T1 tops out around +12%, since a T1 just isn't built for it no matter how
# much is invested in that one copy.
AUTOMATION_BASE_YIELD_PCT: Dict[int, float] = {1: 0.015, 2: 0.025, 3: 0.04, 4: 0.06, 5: 0.085, 6: 0.11, 7: 0.125}


def automation_yield_bonus_pct(servant: Servant, star_level: int, level: int = 1, affinity_seconds: int = 0) -> float:
    mult = STAR_STAT_MULTIPLIER[star_level] * LEVEL_STAT_MULTIPLIER.get(level, 1.0) * affinity_multiplier(affinity_seconds)
    return AUTOMATION_BASE_YIELD_PCT[servant.tier] * mult
