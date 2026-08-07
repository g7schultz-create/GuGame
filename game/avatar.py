"""
Nascent Soul Avatar — Phase 2 adds real combat consumption on top of Phase 1's data model
(see the approved plans for both). Realm-gated at Nascent Soul (great_realm_index 3, see
realms.GREAT_REALMS): once there, a player runs /avatar to pick a "soul" (see SOULS below)
and can feed it Soul Nourishing Pills + Soul Crystals through /avatar to level it from I to X.

Two independent bonus channels, deliberately mirroring character_class.py's own split:
    special_bonuses   combat-only keys, LIVE-READ every time (never baked into flat stats
                      like a root/physique roll) so a soul reroll can never leave stale
                      bonuses behind. Values here are the Level I base magnitude —
                      AVATAR_LEVEL_MULTIPLIER scales it further (see scaled_bonus). Folded
                      into GameManager.compute_equipment_bonuses alongside root/physique/Gu
                      (Phase 2), plus a handful of standalone consumption sites this generic
                      pool can't reach (death_qi_loss_reduction_pct's 3 death-penalty sites,
                      sect_buff_str_pct/def_pct's raid-only ally targeting — see each view's
                      own comments for why).

Every soul shares ONE active ability, Soul Projection — "the power of your nascent soul for
3 turns" — the same "one shared button, per-type flavor" shape Class Ability already uses
(see character_class.py's own docstring). Cost/base-duration are fixed across every soul;
SOUL_PROJECTION_KEYS says which of each soul's own special_bonuses keys it actually amplifies
(not always every key a soul has — some, like Wisdom Soul's original cooldown/search pair or
Soul Path Soul's own avatar_power_pct/death_qi_loss_reduction_pct, have no per-turn combat
meaning and stay passive-only forever; see soul_projection_bonus's own docstring for the
"delta on top vs. full amount" distinction).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Realm gate: realms.GREAT_REALMS[3] == "Nascent Soul" — same idiom used everywhere else in
# this codebase for realm checks: realms.STAGES[player["realm_index"]].great_realm_index.
AVATAR_MIN_GREAT_REALM_INDEX = 3


def is_realm_eligible(great_realm_index: int) -> bool:
    return great_realm_index >= AVATAR_MIN_GREAT_REALM_INDEX


AVATAR_MAX_LEVEL = 10
AVATAR_LEVEL_NAMES = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]


def level_name(level: int) -> str:
    return AVATAR_LEVEL_NAMES[level - 1] if 1 <= level <= AVATAR_MAX_LEVEL else str(level)


# Scales both a soul's passive magnitude and Soul Projection's buff size once Phase 2 reads
# it — a smooth, mildly-accelerating curve (not the steep realm-breakthrough curve, which is
# reserved for actually crossing a Great Realm) matching blacksmith.TIER_PCT_BUDGET's own
# tapering-growth shape. Purely descriptive in Phase 1 ("Avatar Power" in the /avatar UI).
AVATAR_LEVEL_MULTIPLIER = {
    1: 1.00, 2: 1.12, 3: 1.25, 4: 1.40, 5: 1.58,
    6: 1.78, 7: 2.00, 8: 2.25, 9: 2.55, 10: 2.90,
}

SOUL_PROJECTION_NAME = "Soul Projection"
SOUL_PROJECTION_QI_COST = 1000  # battle Qi (the in-combat resource Empower/Class Ability already spend)
SOUL_PROJECTION_DURATION_TURNS = 3
# Baseline strength of Soul Projection's temporary bonus relative to the passive's own
# level-scaled magnitude -- scaled further by equipped avatar gear and Soul Path Soul's own
# avatar_power_pct, see GameManager.soul_projection_multiplier (manager.py). A bare Level I
# avatar with no gear projects at exactly this multiplier; better gear/a Soul Path soul push
# it higher, finally giving avatar_gear.py's stat_bonuses a real combat purpose.
SOUL_PROJECTION_BASE_MULTIPLIER = 2.0


@dataclass
class AvatarSoul:
    name: str
    tagline: str
    emoji: str
    display_bonuses: List[str]
    passive_name: str
    passive_text: str
    ability_text: str  # this soul's own flavor of what Soul Projection does once Phase 2 wires it up
    special_bonuses: Dict[str, float] = field(default_factory=dict)


SOULS: Dict[str, AvatarSoul] = {
    "Sword Soul": AvatarSoul(
        name="Sword Soul",
        tagline="A blade-spirit given form — every strike carries a killing edge.",
        emoji="⚔️",
        display_bonuses=["💥 Crit Damage: +10%", "🗡️ Armor Penetration: +12%"],
        passive_name="Edge Intent",
        passive_text="Permanently +10% Crit Damage and +12% Armor Penetration.",
        ability_text="Your nascent sword-soul manifests and guides your blade — Crit Damage and Armor Penetration are dramatically amplified for 3 turns.",
        special_bonuses={"crit_damage_pct": 0.10, "armor_penetration_pct": 0.12},
    ),
    "Blood Soul": AvatarSoul(
        name="Blood Soul",
        tagline="Thrives on the blood it spills, growing hardier with every wound dealt.",
        emoji="🩸",
        display_bonuses=["🩸 Lifesteal: 18%", "❤️ HP: +15%"],
        passive_name="Bloodbound Vitality",
        passive_text="Permanently heal for 18% of all damage you deal, and +15% HP.",
        ability_text="Your nascent blood-soul surges through your veins — Lifesteal and HP are dramatically amplified for 3 turns.",
        special_bonuses={"lifesteal_percent": 0.18, "hp_pct": 0.15},
    ),
    "Wisdom Soul": AvatarSoul(
        name="Wisdom Soul",
        tagline="Sees the shape of fate a step ahead of everyone else.",
        emoji="📖",
        display_bonuses=["⏱️ Rest/Meditate Cooldowns: -12%", "🧭 Inheritance-Search Quality: +6%", "🎯 Crit Chance: +5%"],
        passive_name="Clear Sight",
        passive_text="Permanently -12% Rest/Meditate cooldowns, +6% chance at better inheritance-search results, and +5% Crit Chance.",
        # Cooldown reduction/search quality have no per-turn combat meaning, so unlike every
        # other soul, Wisdom Soul's Soul Projection doesn't amplify its ORIGINAL two keys at
        # all -- crit_chance_pct exists specifically to give it something real to project
        # (see SOUL_PROJECTION_KEYS); the other two stay passive-only forever.
        ability_text="Your nascent wisdom-soul sharpens your senses to a killing point — Crit Chance is dramatically amplified for 3 turns.",
        special_bonuses={"cooldown_reduction_pct": 0.12, "clue_chance_bonus_pct": 0.06, "crit_chance_pct": 0.05},
    ),
    "Strength Soul": AvatarSoul(
        name="Strength Soul",
        tagline="A mountain given a soul — immovable, and immensely strong.",
        emoji="💪",
        display_bonuses=["❤️ HP: +20%", "👑 World Boss Damage: +12%"],
        passive_name="Immovable Body",
        passive_text="Permanently +20% HP and +12% damage against World Bosses.",
        ability_text="Your nascent strength-soul floods your body with power — HP and World Boss damage are dramatically amplified for 3 turns.",
        special_bonuses={"hp_pct": 0.20, "boss_damage_bonus_pct": 0.12},
    ),
    "Soul Path Soul": AvatarSoul(
        name="Soul Path Soul",
        tagline="Walks the Soul Path itself — its own avatar is stronger for it, and death loses some of its grip.",
        emoji="👻",
        display_bonuses=["🌌 Avatar Power: +25%", "💀 Death Qi Loss: -6%"],
        passive_name="Soul-Deep Resolve",
        passive_text="Your avatar's own abilities are permanently 25% stronger, and you lose 6% less qi on defeat.",
        # Has no combat stat of its own worth amplifying (avatar_power_pct/
        # death_qi_loss_reduction_pct aren't per-turn things) -- its own Soul Projection
        # instead lasts a full turn longer (see soul_projection_duration), while its
        # avatar_power_pct passive strengthens EVERY soul's Soul Projection multiplier
        # (including its own, while equipped -- see GameManager.soul_projection_multiplier).
        ability_text="Your nascent soul-soul projects with unmatched endurance — Soul Projection lasts a turn longer than usual, its force already strengthened by your own soul's deep resolve.",
        special_bonuses={"avatar_power_pct": 0.25, "death_qi_loss_reduction_pct": 0.06},
    ),
    "Formation Soul": AvatarSoul(
        name="Formation Soul",
        tagline="Weaves the fates of everyone fighting alongside it into one stronger whole.",
        emoji="🔯",
        display_bonuses=["🛡️ Sect Ally STR/DEF (in a raid): +8%"],
        passive_name="Bound Formation",
        passive_text="Permanently grants sect members fighting alongside you in a raid +8% STR and +8% DEF.",
        ability_text="Your nascent formation-soul binds the battlefield together — your sect allies' STR/DEF amplification is dramatically strengthened for 3 turns.",
        special_bonuses={"sect_buff_str_pct": 0.08, "sect_buff_def_pct": 0.08},
    ),
    "Frost Soul": AvatarSoul(
        name="Frost Soul",
        tagline="A soul of endless winter — as hard to hit as it is to hurt.",
        emoji="❄️",
        display_bonuses=["💨 Dodge Chance: +7%", "🛡️ Ignore-Attack Chance: +6%"],
        passive_name="Winter's Grace",
        passive_text="Permanently +7% Dodge Chance and a 6% chance to entirely ignore an incoming attack.",
        ability_text="Your nascent frost-soul wreathes you in killing cold — Dodge and Ignore-Attack chance are dramatically amplified for 3 turns.",
        special_bonuses={"dodge_chance_pct": 0.07, "ignore_attack_chance": 0.06},
    ),
    "Demon Soul": AvatarSoul(
        name="Demon Soul",
        tagline="Hungers for a wounded enemy's death above all else.",
        emoji="👹",
        display_bonuses=["⚔️ ATK below 50% HP: +25", "☠️ Execute Damage: +15%"],
        passive_name="Death Hunger",
        passive_text="Permanently +25 ATK while below 50% HP, and +15% damage against low-HP enemies.",
        ability_text="Your nascent demon-soul claws free — ATK and Execute damage are dramatically amplified for 3 turns.",
        special_bonuses={"low_hp_atk_bonus": 25, "execute_damage_pct": 0.15},
    ),
}

SOUL_EMOJI = {name: soul.emoji for name, soul in SOULS.items()}


def get_avatar_soul(name: Optional[str]) -> Optional[AvatarSoul]:
    return SOULS.get(name) if name else None


def scaled_bonus(avatar_soul_name: Optional[str], avatar_level: int, key: str) -> float:
    """A player's current avatar soul's special_bonuses[key], scaled by their avatar's
    level -- 0 if no soul chosen or the soul doesn't grant that key. Single source of truth
    for "how much of X does this player's avatar currently grant" — used both by
    GameManager.compute_equipment_bonuses' generic fold-in AND by the handful of standalone
    sites that read a key outside that pool (death_qi_loss_reduction_pct's 3 death-penalty
    sites, Formation Soul's raid-only ally targeting)."""
    soul = get_avatar_soul(avatar_soul_name)
    if soul is None:
        return 0.0
    base = soul.special_bonuses.get(key, 0)
    if not base:
        return 0.0
    return base * AVATAR_LEVEL_MULTIPLIER.get(avatar_level, 1.0)


# Which of each soul's own special_bonuses keys Soul Projection actually amplifies while
# active -- NOT every key a soul has (see each soul's own ability_text/comments above for why
# some are passive-only forever). Soul Path Soul projects nothing of its own; see
# soul_projection_duration instead.
SOUL_PROJECTION_KEYS: Dict[str, Tuple[str, ...]] = {
    "Sword Soul": ("crit_damage_pct", "armor_penetration_pct"),
    "Blood Soul": ("lifesteal_percent",),  # not hp_pct -- every combat view bakes HP bonuses once at __init__, never recomputed per-attack, so a temporary HP swing has nowhere clean to apply
    "Wisdom Soul": ("crit_chance_pct",),
    "Strength Soul": ("boss_damage_bonus_pct",),  # not hp_pct, same reasoning as Blood Soul
    "Soul Path Soul": (),
    "Formation Soul": ("sect_buff_str_pct", "sect_buff_def_pct"),
    "Frost Soul": ("dodge_chance_pct", "ignore_attack_chance"),
    "Demon Soul": ("low_hp_atk_bonus", "execute_damage_pct"),
}

# The only projected keys with ZERO passive component (never appear in
# GameManager.SPECIAL_BONUS_KEYS, so bonuses.get(key, 0) is always 0 for them already) --
# soul_projection_bonus adds the FULL scaled amount for these, and only the DELTA on top of
# the passive for every other projected key, so the passive contribution never gets
# double-counted once Soul Projection is also active.
FULL_AMOUNT_PROJECTION_KEYS = {"sect_buff_str_pct", "sect_buff_def_pct"}


def soul_projection_duration(soul: AvatarSoul) -> int:
    """Soul Path Soul's own 'stronger avatar abilities' theme manifests as one extra turn,
    since it has no stat key of its own worth amplifying (see SOUL_PROJECTION_KEYS)."""
    return SOUL_PROJECTION_DURATION_TURNS + (1 if soul.name == "Soul Path Soul" else 0)


def soul_projection_bonus(avatar_soul_name: Optional[str], avatar_level: int, key: str, multiplier: float) -> float:
    """Extra amount of `key` Soul Projection adds ON TOP of whatever's already flowing
    passively, while active — 0 if this soul doesn't project that key at all (only each
    soul's SOUL_PROJECTION_KEYS entries amplify). `multiplier` is the caller's own
    GameManager.soul_projection_multiplier(user_id) result (gear/Soul-Path-scaled)."""
    soul = get_avatar_soul(avatar_soul_name)
    if soul is None or key not in SOUL_PROJECTION_KEYS.get(soul.name, ()):
        return 0.0
    base = soul.special_bonuses.get(key, 0)
    if not base:
        return 0.0
    scaled = base * AVATAR_LEVEL_MULTIPLIER.get(avatar_level, 1.0)
    if key in FULL_AMOUNT_PROJECTION_KEYS:
        return scaled * multiplier
    return scaled * (multiplier - 1)


# -- Leveling: feed Soul Nourishing Pills + Soul Crystals through /avatar to level up -----
# Exact-recipe-per-level, consumed atomically in one "Feed to Level Up" click (no
# partial-progress bar -- that pattern belongs to /split_body's time-based mission instead).

SOUL_NOURISHING_PILL = "Soul Nourishing Pill"
SOUL_CRYSTAL = "Soul Crystal"

# Keyed by the level being REACHED (2-10). Tapering multiplicative curve (~1.8x -> 1.34x on
# pills, ~1.5x -> 1.36x on crystals), matching blacksmith.TIER_PCT_BUDGET's own smooth-
# acceleration shape rather than a steeper curve. Tunable placeholders -- no acquisition path
# exists yet in Phase 1 (that's /split_body, a later phase).
AVATAR_LEVEL_UP_RECIPE = {
    2: {SOUL_NOURISHING_PILL: 5, SOUL_CRYSTAL: 2},
    3: {SOUL_NOURISHING_PILL: 9, SOUL_CRYSTAL: 3},
    4: {SOUL_NOURISHING_PILL: 14, SOUL_CRYSTAL: 5},
    5: {SOUL_NOURISHING_PILL: 21, SOUL_CRYSTAL: 8},
    6: {SOUL_NOURISHING_PILL: 30, SOUL_CRYSTAL: 12},
    7: {SOUL_NOURISHING_PILL: 42, SOUL_CRYSTAL: 17},
    8: {SOUL_NOURISHING_PILL: 58, SOUL_CRYSTAL: 24},
    9: {SOUL_NOURISHING_PILL: 79, SOUL_CRYSTAL: 33},
    10: {SOUL_NOURISHING_PILL: 106, SOUL_CRYSTAL: 45},
}


def level_up_recipe(current_level: int) -> Optional[Dict[str, int]]:
    """None once already at AVATAR_MAX_LEVEL -- nothing left to feed toward."""
    return AVATAR_LEVEL_UP_RECIPE.get(current_level + 1)
