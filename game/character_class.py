"""
Combat classes (/join step, or `/choose_class` for characters confirmed before this
existed) — a permanent choice alongside Race/Path, but purely combat-facing: no
cultivation-speed/breakthrough-chance bonuses like Race/Path/Root/Physique carry.

Two independent bonus channels, mirroring how Race/Path bonuses already split:
    stat_bonuses     foundation-stat pct keys (hp_pct, def_pct, ...) — baked once into
                      the player's actual hp/def_stat/etc. via chargen.compute_final_stats
                      at /join confirm (or, for a pre-existing confirmed character using
                      `/choose_class`, applied as a one-time multiplicative nudge on top
                      of their current stats — see GameDatabase.apply_class_stat_bonuses).
    special_bonuses   combat-only keys consumed live every fight (e.g. lifesteal_percent)
                      — folded into GameManager.compute_equipment_bonuses alongside gear,
                      so they show up in /profile and /equipment the same way Gu passives do.

Each class's real distinguishing feature is its Class Ability (see the "Class Ability"
button in both game/raid.py and game/hunt.py) — Tank's Defend Ally, Support's Inspire,
Frostbinder's Freeze. /hunt is solo, so there's no ally to target: Tank's ability becomes
a self-only Brace (see hunt.py's BRACE_DAMAGE_REDUCTION) and Support's Inspire just buffs
the one person casting it; Frostbinder's Freeze needs no adaptation since it already only
ever targeted the enemy. Only one ability per class for now (Tank's "defend everyone at
once"/buff-on-defend and Support's observe-into-buff are earmarked for later; deliberately
not built yet).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class CharacterClass:
    name: str
    role: str  # "Tank" / "Support" / "DPS" — display label, distinct from `name`
    tagline: str
    display_bonuses: List[str]
    passive_name: str
    passive_text: str
    ability_name: str
    ability_text: str
    emoji: str
    stat_bonuses: Dict[str, float] = field(default_factory=dict)
    special_bonuses: Dict[str, float] = field(default_factory=dict)


CLASSES: Dict[str, CharacterClass] = {
    "Tank": CharacterClass(
        name="Tank",
        role="Tank",
        tagline="Plants themselves between the party and every fang aimed at it.",
        display_bonuses=["❤️ HP: +20%", "🛡️ DEF: +15%"],
        passive_name="Unshakable",
        passive_text="Permanently +20% HP and +15% DEF.",
        ability_name="Defend Ally",
        ability_text=(
            "In a raid, pick an ally — any hit meant for them this round lands on you "
            "instead, reduced by your own toughness. Solo (e.g. in a hunt), there's no one "
            "else to protect, so you Brace yourself instead for an even stronger Guard."
        ),
        emoji="🛡️",
        stat_bonuses={"hp_pct": 0.20, "def_pct": 0.15},
    ),
    "Support": CharacterClass(
        name="Support",
        role="Support",
        tagline="Turns a scattered party into one that fights as a whole.",
        display_bonuses=["✨ Party-wide buff on demand"],
        passive_name="Attuned",
        passive_text="No passive stat bonus — the whole party gets stronger when you act.",
        ability_name="Inspire",
        ability_text=(
            "Buff the entire party's STR and DEF for a few rounds (costs your attack that "
            "round). Solo (e.g. in a hunt), it's just you who gets buffed."
        ),
        emoji="💚",
    ),
    "Frostbinder": CharacterClass(
        name="Frostbinder",
        role="DPS",
        tagline="Channels the same bone-deep frost that runs through a Snowman's blood, honed into a killing edge.",
        display_bonuses=["🩸 Lifesteal: 15%"],
        passive_name="Frostbound Vitality",
        passive_text="Permanently heal for 15% of all damage you deal.",
        ability_name="Freeze",
        ability_text=(
            "Strike for reduced damage with a chance to freeze the target solid, making it "
            "skip its next attack. Works the same in a hunt or a raid."
        ),
        emoji="❄️",
        special_bonuses={"lifesteal_percent": 0.15},
    ),
}

CLASS_EMOJI = {name: cls.emoji for name, cls in CLASSES.items()}


def get_character_class(name: Optional[str]) -> Optional[CharacterClass]:
    return CLASSES.get(name) if name else None
