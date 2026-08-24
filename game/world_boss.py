"""
World Boss (see World_Boss_System_Design.md) -- a recurring, server-wide encounter with one
shared HP pool every player chips away at, rewarded through a damage-weighted lottery so
weaker players stay meaningfully engaged instead of only the top damage dealer winning
anything. Built against the doc's own scope, with these adjustments the user explicitly
asked for:

  - Spawn cadence changed from the doc's "every 3-7 days" to a flat 3 hours after the
    previous boss is defeated or expires (WORLD_BOSS_RESPAWN_DELAY_SECONDS) -- a random
    boss from WORLD_BOSSES spawns automatically via a background task (see GameCog's
    world_boss_tick loop in cog.py), or immediately via the admin /raidboss_spawn override.
  - Dao Marks, Killer Moves, Contribution Points, and Sect Buffs are explicitly OUT of scope
    for this pass (per direct instruction) -- nothing below references or fakes any of them.
  - Attacking the boss is a single one-directional hit (per the doc's own pseudocode --
    `boss_damage[user_id] += damage; boss_hp -= damage`, no boss retaliation shown), not a
    full back-and-forth fight like /raid. This is deliberate, not a simplification: it's what
    lets "every cultivation realm" safely participate the doc asks for -- a fresh character
    can safely tap a world boss with zero death/HP risk, unlike joining a real /raid.
  - Two of the doc's named "Recommended Immortal Gu" -- Fortune Rivalling Heaven Gu and
    Heavenly Essence Treasure Lotus -- already exist as real, passive-bearing canon Gu
    (canon_gu.py), registered Unique/drop_weight-0 ("event-only"). The World Boss is exactly
    the kind of event that Unique tag was reserved for, so this module grants those two
    directly rather than defining duplicate items under the same name.
  - The doc's Spider Queen exclusive drops ("Poison Gu, Silk Equipment, Venom Artifacts")
    aren't concrete items anywhere else in the doc's own Gu/equipment lists -- three small
    new items (Poison Gu, Silk Robes, Venom Fang Ring) fill that gap so every boss still has
    real, distinct exclusive loot, rather than leaving one boss's table empty.
  - Most of the ~24 named Gu below get a REAL passive through an existing stat_bonuses key
    (crit/dodge/lifesteal/loot chance/cooldown reduction/etc. — see equipment.EQUIPMENT).
    A handful whose flavor doesn't map to anything that exists yet get canon_gu.py's own
    already-established fallback: a small flavor-appropriate stat bonus so equipping one
    isn't a complete no-op, honestly labeled "not modeled yet" in the description — the same
    call this codebase already made for 19 of its 26 canon Gu, not a new corner being cut.
  - "Boss Titles" and "Exclusive Cosmetic" (Mythic loot table) are dropped outright -- no
    title or cosmetic system exists anywhere in this codebase to hang them on.
  - Two genuinely new mechanics were wired for real rather than flavor-approximated:
    Flying Sword Gu (extra attack roll on a world boss hit) and Battle Intent Gu (damage
    scales with the player's own consecutive attacks against the current boss) -- see
    GameManager.attack_world_boss. A third, Worldly Escape Gu, reuses the exact daily-flag
    pattern try_use_daily_fatal_hit_negation already established -- retargeted from the doc's
    literal "PvP defeat" example to hunt/raid/battlefield's real death Qi-loss penalty
    instead, since PvP defeat already costs nothing in this game (see pvp_view.py's own
    "it's just a duel, no real harm done") and there's no "failed dangerous exploration"
    penalty separate from that to negate either.
"""

import random
import time
from typing import Optional

from . import equipment

# -- Spawn timing ---------------------------------------------------------------------------

WORLD_BOSS_RESPAWN_DELAY_SECONDS = 30 * 60  # user's explicit override of the doc's "weekly" -- was 3h, now 30 minutes
WORLD_BOSS_LIFETIME_SECONDS = 36 * 3600      # middle of the doc's own "24-48 hours" range
WORLD_BOSS_ATTACK_COOLDOWN_SECONDS = 20 * 60  # user's explicit override -- was 15 minutes, then 1 hour, now 20 minutes
# Each /raidboss_attack that's off cooldown lands this many independent attack rolls in one
# go (a "flurry"), rather than 1 -- user's explicit request. Flying Sword Gu's own bonus
# swing still fires per-roll on top of this, and Battle Intent Gu's ramp keeps counting up
# across all 5 (see GameManager.attack_world_boss).
WORLD_BOSS_ATTACKS_PER_COOLDOWN = 5

# Derived from this game's own breakthrough curve, but against the REALISTIC current
# ceiling, not the theoretical one. Raised again (1,000,000 -> 10,000,000) once the first two
# players actually reached Spirit Severing (great_realm_index 4 of 7): checked their real
# live-DB effective combat stats and simulated GameManager.resolve_world_boss_swing's own
# combat.resolve_attack call against WORLD_BOSS_DEF_STAT/SPD_STAT below -- a single 5-swing
# flurry (WORLD_BOSS_ATTACKS_PER_COOLDOWN) from either of them alone already dealt
# ~940,000-1,260,000 damage, meaning the old 1,000,000 HP could be one-shot in a single
# button click by one player, completely defeating the "server-wide, many-contributors" shared
# pool this system is built around. Raised again to 20,000,000 (2026-08-08, user's explicit
# request) as the playerbase's top end has grown since the 10,000,000 calibration above --
# back to the original first-tried value this constant was once walked back from (20,000,000
# -> 2,500,000 -> 1,500,000 -> 10,000,000). Raised again to 100,000,000 (2026-08-09, user's
# explicit request), then to 500,000,000 (2026-08-11, user's explicit request), then to
# 2,000,000,000 (2026-08-15, user's explicit request). Raised again to 50,000,000,000
# (2026-08-21, user-reported live damage: a top player was hitting 1,100,000,000 in a single
# flurry -- 55% of the old 2B ceiling in ONE button click, worse than the exact ratio that
# triggered every earlier raise above, and now compounded by the just-shipped rank-tier reward
# rework, which is supposed to reward a real multi-round, multi-contributor fight rather than
# whoever clicks first. 50B puts that same 1.1B hit back down around ~2%, the same rough ratio
# earlier raises targeted -- ongoing live-ops tuning either way, not a one-time number.
WORLD_BOSS_MAX_HP = 50_000_000_000
# Low on purpose -- a real fight's monster would scale DEF/SPD to be dangerous, but "every
# cultivation realm" being able to meaningfully participate (the doc's own stated goal) means
# even a fresh character's attack needs to land and deal more than the MIN_DAMAGE=1 floor.
WORLD_BOSS_DEF_STAT = 40
WORLD_BOSS_SPD_STAT = 15

# -- Roster (see the doc's "Multiple World Boss Ecosystem" table) -------------------------
# One is picked at random on each spawn (GameManager.maybe_spawn_world_boss). exclusive_pool
# names are ONLY eligible in THIS boss's Mythic-band roll (see roll_world_boss_loot) --
# they're what makes each boss's loot feel distinct rather than every spawn sharing one pool.

WORLD_BOSSES = {
    "ancient_desolate_boar_king": {
        "name": "Ancient Desolate Boar King",
        "theme": "Strength",
        "emoji": "🐗",
        "description": "A boar king so ancient its tusks have turned to stone, splitting the earth with every step.",
        "exclusive_pool": ["Strength Qi Gu", "Mountain Strength Gu", "Beast Soul Gu"],
    },
    "heavenly_roc": {
        "name": "Heavenly Roc",
        "theme": "Wind",
        "emoji": "🦅",
        "description": "A roc whose wingbeat splits the clouds, said to circle the world in a single breath.",
        "exclusive_pool": ["Lightning Wings Gu", "Flying Sword Gu"],
    },
    "dream_butterfly_monarch": {
        "name": "Dream Butterfly Monarch",
        "theme": "Dream",
        "emoji": "🦋",
        "description": "A monarch butterfly whose wings scatter fragments of other cultivators' dreams.",
        "exclusive_pool": ["Dream Wings Gu", "Star Thought Gu"],
    },
    "ancient_dragon_emperor": {
        "name": "Ancient Dragon Emperor",
        "theme": "Sword / Transformation",
        "emoji": "🐉",
        "description": "A dragon emperor mid-transformation, scales shedding into blades with every roar.",
        "exclusive_pool": ["Dragon Strength Gu", "Flying Sword Gu"],
    },
    "ten_thousand_spider_queen": {
        "name": "Ten Thousand Spider Queen",
        "theme": "Poison",
        "emoji": "🕷️",
        "description": "A spider queen whose webs run for miles, every thread laced with venom.",
        "exclusive_pool": ["Poison Gu", "Silk Robes", "Venom Fang Ring"],
    },
    "white_bone_emperor": {
        "name": "White Bone Emperor",
        "theme": "Bone",
        "emoji": "💀",
        "description": "An emperor of bleached bone, armored in the skeletons of a thousand fallen beasts.",
        "exclusive_pool": ["Iron Bone Gu", "Diamond Skin Gu"],
    },
    "primordial_sea_leviathan": {
        "name": "Primordial Sea Leviathan",
        "theme": "Water",
        "emoji": "🐋",
        "description": "A leviathan from before the seas had names, its wake alone capable of drowning cities.",
        "exclusive_pool": ["Treasure Lotus Gu", "Heavenly Essence Treasure Lotus"],
    },
}


def roll_boss_key(rng: Optional[random.Random] = None) -> str:
    return (rng or random).choice(list(WORLD_BOSSES.keys()))


# -- New items (boss equipment + Gu) --------------------------------------------------------
# Registered into the shared equipment.EQUIPMENT catalog at import time, the same pattern
# canon_gu.py's _register_canon_gu uses -- single fixed items, not part of the Gu star/quality
# ladder (these are meant to feel like singular "you got IT" trophies, not a leveling rung).

# No dedicated "boots" slot exists in this game's 9 slot types (see equipment.SLOTS) --
# mapped to Artifact instead, the closest existing slot with movement/flight flavor already
# established (see "Basic Flying Artifact").
_BOSS_EQUIPMENT = {
    "Heaven Crushing Belt": ("Bracelet", "A belt said to crush mountains with the wearer's own footsteps.", {"physical_damage_pct": 0.15, "crit_chance_pct": 0.05}),
    "Dragon Bone Ring": ("Ring", "Carved from a single vertebra of a dragon that died mid-cultivation.", {"hp": 500, "cultivation_speed_pct": 0.10}),
    "Immortal Silk Boots": ("Artifact", "Woven from silk that never touched the ground. No boot slot exists yet, so this flies instead.", {"spd_stat": 30, "dodge_chance_pct": 0.08}),
    "Desolate Beast Armor": ("Body", "Plate forged from a desolate beast's own hide -- still faintly warm.", {"hp": 700, "def_stat": 60, "boss_damage_bonus_pct": 0.15}),
    "Silk Robes": ("Body", "Spider-silk robes, light enough to dodge a killing blow.", {"spd_stat": 25, "dodge_chance_pct": 0.06}),
    "Venom Fang Ring": ("Ring", "Set with a fang that still weeps venom.", {"physical_damage_pct": 0.10, "crit_chance_pct": 0.04}),
}

# (name, description, stat_bonuses). Gu whose flavor doesn't map onto a real, already-
# consumed key (see this module's own docstring) get a small stand-in stat instead, noted
# with "(not modeled yet)" the same way canon_gu.py already flags its own 19 unmodeled Gu.
# Flying Sword Gu, Battle Intent Gu, Fixed Immortal Travel Gu, and Worldly Escape Gu carry NO
# stat_bonuses here -- their real mechanic is name-checked directly in GameManager (see this
# module's own docstring), the same way _try_negate_fatal_hit checks physique_tier by name
# rather than through the generic bonus pool.
_BOSS_GU = {
    "Strength Qi Gu": ("+15% Damage.", {"physical_damage_pct": 0.15}),
    "Mountain Strength Gu": ("+HP, +Defense.", {"hp": 600, "def_stat": 40}),
    "Dragon Strength Gu": ("Increased critical damage.", {"crit_damage_pct": 0.20}),
    "Sword Escape Gu": ("Chance to dodge attacks.", {"dodge_chance_pct": 0.10}),
    "Flying Sword Gu": ("Grants an additional attack roll each time you strike the World Boss.", {}),
    "Dog Shit Luck Gu": ("+25% item drop rate. (Rare-drop-chance/reroll clauses not modeled yet.)", {"loot_chance_bonus_pct": 0.25}),
    "Treasure Lotus Gu": ("Increased spirit stone income.", {"stone_reward_bonus_pct": 0.20}),
    "Battle Intent Gu": ("Your World Boss damage grows the more consecutive hits you land on it.", {}),
    "Blood Deity Gu": ("Lifesteal.", {"lifesteal_percent": 0.15}),
    "Iron Bone Gu": ("High defensive bonuses.", {"def_stat": 50, "hp": 300}),
    "Diamond Skin Gu": ("Large defensive bonuses (no generic incoming-damage-reduction key exists yet for gear, so this is stat-based rather than a true % mitigation).", {"def_stat": 70, "hp": 400}),
    "Lightning Wings Gu": ("Speed, cooldown reduction.", {"spd_stat": 40, "cooldown_reduction_pct": 0.10}),
    "Dream Wings Gu": ("Increased dream-realm discovery chance.", {"dream_realm_bias_pct": 0.05}),
    "Star Thought Gu": ("Improved essence purity (manual-coherence hook doesn't exist yet for gear, so this is a stand-in).", {"essence_purity_pct": 0.08}),
    "Divine Concealment Gu": ("Reduces death Qi-loss penalties (PvP included).", {"death_qi_loss_reduction_pct": 0.30}),
    "Heavenly Secret Gu": ("Better rewards from Secret Realms and Inheritances. (The World Boss clause is flavor only -- boss rewards are damage-weighted, not discovery-quality-based.)", {"discovery_quality_bias_pct": 0.05}),
    "Beast Soul Gu": ("Increased damage against beasts and the World Boss.", {"beast_damage_pct": 0.15, "boss_damage_bonus_pct": 0.10}),
    "Human Qi Gu": ("Faster cultivation.", {"cultivation_speed_pct": 0.08}),
    "Fixed Immortal Travel Gu": ("Instantly change world region, ignoring the usual cooldown.", {}),
    "Connect Luck Gu": ("+Luck. (Sharing it with a disciple/sect member isn't modeled yet -- no cross-player bonus-sharing exists.)", {"luck_stat": 25}),
    "Divine Travel Gu": ("Greatly increased exploration luck.", {"explore_luck_bonus_flat": 15}),
    "Heavenly Web Gu": ("+15% item drop rate. (Gu-capture-chance clause not modeled yet.)", {"loot_chance_bonus_pct": 0.15}),
    "Worldly Escape Gu": ("Once per day, ignore the Qi-loss penalty from a defeat. (PvP defeats already cost nothing in this game, so this covers hunt/raid/battlefield instead -- see GameManager.check_and_consume_worldly_escape.)", {}),
    "Poison Gu": ("A venomous bite, dealt with each strike. (No damage-over-time engine exists yet -- represented as bonus damage and lifesteal instead.)", {"physical_damage_pct": 0.08, "lifesteal_percent": 0.08}),
}

# Already exist as real canon Gu (canon_gu.py) -- reused directly rather than duplicated
# under the same name. Granted at "Immortal" (7-star) quality, the ceiling of that system.
_EXISTING_CANON_ULTRA_RARE_GU = ["Fortune Rivalling Heaven Gu", "Heavenly Essence Treasure Lotus"]

# Non-exclusive generic pools every boss's loot table can pull from, on top of its own
# exclusive_pool (see WORLD_BOSSES) -- built from the sets above minus whatever's exclusive
# to a specific boss, so a generic Legendary/Mythic hit still feels like real Gu, not filler.
# Computed BEFORE _register_items() below (not after, like it originally was) so registration
# can use it to assign each Gu's real rank -- see that function's own comment.
_ALL_EXCLUSIVE_NAMES = {name for boss in WORLD_BOSSES.values() for name in boss["exclusive_pool"]}
GENERIC_GU_POOL = [name for name in _BOSS_GU if name not in _ALL_EXCLUSIVE_NAMES]
GENERIC_EQUIPMENT_POOL = [name for name in _BOSS_EQUIPMENT if name not in _ALL_EXCLUSIVE_NAMES]


def _register_items():
    for name, (slot_type, description, stat_bonuses) in _BOSS_EQUIPMENT.items():
        equipment.EQUIPMENT[name] = equipment.Equipment(
            name=name, slot_type=slot_type, rank="World Boss", description=description, stat_bonuses=stat_bonuses,
        )
    for name, (description, stat_bonuses) in _BOSS_GU.items():
        # Real GU_QUALITY_ORDER rank (not the flat "World Boss" string equipment above still
        # uses) so these are eligible as a Killer Move core/component at their true rarity
        # (see equipment.gu_quality_for) instead of always reading as the lowest possible
        # quality -- per explicit request. Still single flat items, not part of the tiered
        # Family (Quality) naming/fusion ladder (see this module's own docstring on why) --
        # only the rank VALUE changes, not the naming convention. Mythic-band-exclusive Gu
        # (only obtainable via a specific boss's own exclusive_pool) rank higher than the
        # generic Rare/Legendary-band pool, mirroring the real difference in how hard each is
        # to obtain.
        rank = "Legendary" if name in _ALL_EXCLUSIVE_NAMES else "Epic"
        equipment.EQUIPMENT[name] = equipment.Equipment(
            name=name, slot_type="Gu", rank=rank, description=f"[World Boss] {description}", stat_bonuses=stat_bonuses,
        )


_register_items()

# -- Loot table (see the doc's own 5-tier table; weights sum to 1000) -----------------------
# "Boss Titles"/"Exclusive Cosmetic" dropped from Mythic -- no title or cosmetic system
# exists anywhere in this codebase to grant those through.

# Reweighted toward the better bands per explicit request ("should feel good to kill one") --
# Rare-or-better jumped from 10% to 30%, Legendary-or-better from 2% to 12%, Mythic from 0.2%
# to 3%. Killing a World Boss is meant to be THE big-reward event now (see the raid-boss loot
# rebalance's own comment on why raid boss loot moved here instead).
LOOT_BANDS = [
    ("Very Common", 400),
    ("Common", 300),
    ("Rare", 180),
    ("Legendary", 90),
    ("Mythic", 30),
]


def _stones(lo: int, hi: int) -> dict:
    return {"kind": "stones", "amount": random.randint(lo, hi)}


def _item(item_name: str, lo: int = 1, hi: int = 1) -> dict:
    return {"kind": "item", "item_name": item_name, "quantity": random.randint(lo, hi)}


def _tiered_material(prefix: str, tier_lo: int, tier_hi: int, lo: int, hi: int) -> dict:
    tier = random.randint(tier_lo, tier_hi)
    return _item(f"Tier {tier} {prefix}", lo, hi)


def roll_world_boss_loot(boss_key: str, contribution_scale: float = 1.0) -> dict:
    """One roll of the 5-tier band table, tier-appropriate reward inside it. Everything
    except the "boss_exclusive"/"accessory_roll" sentinel kinds below is a ready-to-grant
    reward dict (see GameManager.grant_reward); those two are resolved by the caller, which
    has access to the boss's roster entry and the accessory-roll machinery this module
    deliberately doesn't import (keeps this module pure data/rolling, no GameManager
    dependency). contribution_scale (0.0-1.0+) nudges stone amounts up for a bigger hit."""
    boss = WORLD_BOSSES[boss_key]
    names = [name for name, _ in LOOT_BANDS]
    weights = [w for _, w in LOOT_BANDS]
    band = random.choices(names, weights=weights, k=1)[0]

    if band == "Very Common":
        reward = random.choice([
            _stones(500, 2000),
            _tiered_material("Herb", 1, 3, 10, 30),
            _tiered_material("Ore", 1, 3, 10, 30),
        ])
    elif band == "Common":
        # Beast Material quantity bumped 10x (1-3 -> 10-30), Herb added alongside it at the
        # exact same tier range/quantity (herb-material parity), and Primeval Essence Crystal
        # added as a real option here for the first time (a big stack, per explicit request)
        # -- World Boss is the deliberately generous, "feel good to kill" event now.
        reward = random.choice([
            _stones(2000, 6000),
            _tiered_material("Beast Material", 2, 4, 10, 30),
            _tiered_material("Herb", 2, 4, 10, 30),
            _item("Primeval Essence Crystal", 100, 300),
            _item(random.choice(GENERIC_EQUIPMENT_POOL)),
        ])
    elif band == "Rare":
        # Gu given two picks out of four (instead of one out of three) to weight "high tier
        # Gu" noticeably higher, per explicit request.
        reward = random.choice([
            _stones(6000, 15000),
            _item(random.choice(GENERIC_GU_POOL)),
            _item(random.choice(GENERIC_GU_POOL)),
            {"kind": "accessory_roll"},
        ])
    elif band == "Legendary":
        # Beast Core quantity bumped 10x (1-2 -> 10-20). Gu split out of the old combined
        # equipment+Gu pool into its own two picks (instead of being diluted 50/50 inside one
        # merged option) to weight "high tier Gu" noticeably higher, per explicit request.
        # 2026-08-21 loot pool rework: tier ceiling raised 7 -> 8 (every other endgame reward
        # source -- Grotto, White Heaven, /explore -- now treats Tier 8 as the real top of the
        # ladder; Legendary topping out at 7 read as behind), stones range nudged up to match.
        reward = random.choice([
            _stones(15000, 50000),
            _tiered_material("Beast Core", 5, 8, 10, 20),
            _item(random.choice(GENERIC_EQUIPMENT_POOL)),
            _item(random.choice(GENERIC_GU_POOL)),
            _item(random.choice(GENERIC_GU_POOL)),
            {"kind": "accessory_roll"},
        ])
    else:  # Mythic
        # 2026-08-21: added a real stones option -- every OTHER band already has one as a
        # fallback, but Mythic never did, meaning the single biggest loot band could never
        # hand out a big currency payout at all, only items/accessories. Sized well above
        # Legendary's own ceiling to stay the top of the ladder.
        reward = random.choice([
            {"kind": "boss_exclusive"},
            _item(equipment.gu_item_name(random.choice(_EXISTING_CANON_ULTRA_RARE_GU), "Immortal")),
            {"kind": "accessory_roll"},
            _stones(80000, 150000),
        ])

    if reward.get("kind") == "stones":
        reward["amount"] = round(reward["amount"] * max(0.5, contribution_scale))
    reward["band"] = band
    return reward


# -- Contribution rank tiers (2026-08-21, explicit request: "worth it for people to attack
# based on rankings") -- everything above (guaranteed stones, the damage-weighted lottery) was
# already damage-SHARE-based, but every other per-contributor roll (Essence Restoration Pill,
# Qi Ascension Pill, avatar gear, manual page) was flat/equal for every contributor regardless
# of rank -- a 1-damage tap got the exact same 85% avatar-gear roll as the #1 damage dealer.
# These tiers, keyed off PLACEMENT (contributors are already damage-sorted DESC, see
# GameDatabase.get_world_boss_contributors), give top ranks a real, visible reason to climb
# beyond their own linear stone share.
RANK_TIER_TOP1 = "top1"
RANK_TIER_TOP3 = "top3"
RANK_TIER_TOP10 = "top10"
RANK_TIER_PARTICIPANT = "participant"

RANK_TIER_LABELS = {
    RANK_TIER_TOP1: "🥇 #1 Damage", RANK_TIER_TOP3: "🥈 Top 3", RANK_TIER_TOP10: "🏅 Top 10", RANK_TIER_PARTICIPANT: "Participant",
}


def contribution_rank_tier(rank: int) -> str:
    if rank == 1:
        return RANK_TIER_TOP1
    if rank <= 3:
        return RANK_TIER_TOP3
    if rank <= 10:
        return RANK_TIER_TOP10
    return RANK_TIER_PARTICIPANT


# Extra INDEPENDENT rolls per tier for each of the 3 rare-item mechanics (Essence Restoration
# Pill, Qi Ascension Pill, manual page) -- on top of the 1 baseline roll every contributor
# already gets, at that mechanic's own existing odds (unchanged). Multiple hits across the
# extra rolls all stack (see GameManager._end_world_boss) rather than only the best one
# counting, so climbing tiers is strictly better, never a wash.
EXTRA_RARE_ROLLS_BY_TIER = {
    RANK_TIER_TOP1: 3, RANK_TIER_TOP3: 2, RANK_TIER_TOP10: 1, RANK_TIER_PARTICIPANT: 0,
}

# Avatar gear chance per tier -- WORLD_BOSS_AVATAR_GEAR_CHANCE (0.85) is the participant
# baseline; top ranks climb toward (and #1 lands exactly on) a guarantee. Gear's own TIER is
# already fixed at avatar_gear.MAX_TIER for everyone (nothing higher to give), so chance is
# the only lever available here.
AVATAR_GEAR_CHANCE_BY_TIER = {
    RANK_TIER_TOP1: 1.00, RANK_TIER_TOP3: 0.95, RANK_TIER_TOP10: 0.90, RANK_TIER_PARTICIPANT: 0.85,
}

# A bonus roll of the SAME 5-tier loot band table the damage-weighted lottery already draws
# from (see roll_world_boss_loot) -- fully independent of and additional to the lottery, which
# is unchanged. This is the direct "better loot pool, worth ranking for" lever: #1 always gets
# one, Top 3 usually does, Top 10 sometimes does, and a plain participant never does (their own
# shot at the loot pool is still the damage-weighted lottery, same as before).
BONUS_LOOT_ROLL_CHANCE_BY_TIER = {
    RANK_TIER_TOP1: 1.00, RANK_TIER_TOP3: 0.60, RANK_TIER_TOP10: 0.25, RANK_TIER_PARTICIPANT: 0.0,
}


# -- Guaranteed rewards -- every participant gets stones scaled by their % of total damage
# (the doc's own "5% -> 50,000 / 20% -> 200,000 / 50% -> 500,000" example is the same linear
# shape, just scaled way down). Originally capped at 10,000 stones per 100% contribution to
# stay proportionate to /explore's own top-band rewards; explicitly raised 10x per direct
# request, so 100% contribution now caps at 100,000 stones -- a deliberate, much bigger World
# Boss payout, not an oversight.
GUARANTEED_STONES_PER_DAMAGE_PCT = 100_000


def guaranteed_reward_stones(damage_dealt: int, total_boss_damage: int) -> int:
    if total_boss_damage <= 0:
        return 0
    pct = damage_dealt / total_boss_damage
    return round(pct * GUARANTEED_STONES_PER_DAMAGE_PCT)


# Independent damage-weighted draws run at boss end (see GameManager._end_world_boss) -- was
# 1, now 4 (3 more added per explicit request). Each roll is fully independent (same
# contribution weights, no removal of a prior winner), so the same top contributor can win
# more than one roll -- simplest reading of "more lottery rolls", not "more distinct winners".
WORLD_BOSS_LOTTERY_ROLL_COUNT = 4


def weighted_lottery_winner(contributions: dict, rng: Optional[random.Random] = None) -> Optional[int]:
    """Player Weight = Player Damage / Total Boss Damage (the doc's own formula) -- picks one
    user_id from {user_id: damage_dealt}, proportional to their share. Returns None if
    contributions is empty or everyone dealt 0 damage."""
    candidates = [(uid, dmg) for uid, dmg in contributions.items() if dmg > 0]
    if not candidates:
        return None
    (rng or random).shuffle(candidates)  # random.choices ties break on list order otherwise
    user_ids = [uid for uid, _ in candidates]
    weights = [dmg for _, dmg in candidates]
    return (rng or random).choices(user_ids, weights=weights, k=1)[0]


# Manual page bonus roll -- every contributor gets an independent shot at this (same "everyone
# gets their own roll" convention the essence-pill/avatar-gear per-contributor rolls in
# GameManager._end_world_boss already use, NOT tied to the damage-weighted lottery above).
# User's own explicit odds.
MANUAL_PAGE_DROP_ODDS = {7: 1 / 2000, 6: 1 / 1000, 5: 1 / 200}


def roll_manual_page_rank(rng: Optional[random.Random] = None) -> Optional[int]:
    """One shared draw sliced rarest-tier-first (not 3 independent per-tier checks), so a
    single contributor can win a page from at most one tier per boss kill, while each tier
    still lands at EXACTLY its own stated odds (see MANUAL_PAGE_DROP_ODDS) -- same "fixed
    slices of one draw" shape LOOT_BANDS above already uses. Returns the winning rank (7/6/5)
    or None (the overwhelmingly common case: 1 - 1/2000 - 1/1000 - 1/200 ~= 99.35%)."""
    roll = (rng or random).random()
    threshold = 0.0
    for rank in (7, 6, 5):  # rarest first
        threshold += MANUAL_PAGE_DROP_ODDS[rank]
        if roll < threshold:
            return rank
    return None
