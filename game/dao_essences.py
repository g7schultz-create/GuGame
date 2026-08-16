"""
Dao Realm Essences -- upon reaching Dao Realm (the 8th and current top Great Realm), each of the
4 substage breakthroughs (Early/Middle/Late/Peak) offers a one-time, permanent pick among the 9
Dao Essences below. Picking one grants its full bonus immediately and removes it from the pool
for the player's remaining picks -- by Peak a player has collected 4 of the 9. Unlike the Spirit
Severing Dao Paths (see game/dao_paths.py), this is not a scaled investment system: there is no
"marks invested" fraction, a pick is either taken (full bonus) or not (nothing).

Pure logic -- no DB/GameManager/discord dependency, mirroring dao_paths.py's own split from
manager.py. Most bonus keys plug directly into the existing SPECIAL_BONUS_KEYS/crafted_pct_totals
pools GameManager.compute_equipment_bonuses already builds; pvp_damage_pct and gu_pet_power_pct
are new keys with their own bespoke consumption sites since no equivalent mechanic existed
anywhere in the codebase before this -- see manager.py's Dao Essence section, pvp_view.py, and
tournament.py for exactly where each is consumed. Essence of the Undying Vow's bonus dict is
intentionally empty -- it's a pure combat-mechanic unlock (once per encounter, a lethal blow
leaves you at 1 HP instead) implemented directly at each combat site rather than as a stat bonus.
"""

from dataclasses import dataclass, field
from typing import Dict

DAO_ESSENCE_PICK_LIMIT = 4

UNDYING_VOW_NAME = "Essence of the Undying Vow"
# Once-per-encounter revive: the retaliation buff granted the instant Undying Vow triggers. A
# single shared shape (name/bonus/duration) so every combat site (hunt.py, battlefield_view.py,
# team_battle.py, inheritance_ground_view.py, tournament.py) grants an identical buff via
# GameDatabase.add_buff's special_bonuses kwarg, riding the existing total_damage_pct key every
# combat loop already reads into its own damage_pct_bonus expression -- no new consumption site
# needed for the buff itself.
UNDYING_VOW_RETALIATION_BUFF_NAME = "Undying Vow"
UNDYING_VOW_RETALIATION_BONUS_PCT = 0.30
UNDYING_VOW_RETALIATION_DURATION_SECONDS = 60


@dataclass
class DaoEssenceSpec:
    name: str
    tagline: str
    description: str
    bonus: Dict[str, float] = field(default_factory=dict)


DAO_ESSENCES: Dict[str, DaoEssenceSpec] = {
    "Essence of Genesis": DaoEssenceSpec(
        name="Essence of Genesis",
        tagline="Where all Daos are born, none are foreign.",
        description="A generalist's Dao -- all six core stats rise together.",
        bonus={"str_pct": 0.10, "atk_pct": 0.10, "def_pct": 0.10, "spd_pct": 0.10, "hp_pct": 0.10, "qi_pct": 0.10},
    ),
    "Essence of Ruin": DaoEssenceSpec(
        name="Essence of Ruin",
        tagline="Kill before you are killed.",
        description="Critical strikes land harder and more often, and a weakened foe dies faster.",
        bonus={"crit_chance_pct": 0.20, "crit_damage_pct": 0.25, "execute_damage_pct": 0.15},
    ),
    "Essence of the Unbroken": DaoEssenceSpec(
        name="Essence of the Unbroken",
        tagline="A body that has died a thousand times fears no death.",
        description="Vitality, evasion, and resilience against beasts all deepen.",
        bonus={"hp_pct": 0.30, "dodge_chance_pct": 0.15, "beast_damage_reduction_pct": 0.25},
    ),
    "Essence of the Endless Now": DaoEssenceSpec(
        name="Essence of the Endless Now",
        tagline="Time is a river; you merely step sideways.",
        description="Every cooldown shortens, and meditation recovers faster still.",
        bonus={"cooldown_reduction_pct": 0.25, "meditate_cooldown_reduction_pct": 0.30},
    ),
    "Essence of the Boundless Sea": DaoEssenceSpec(
        name="Essence of the Boundless Sea",
        tagline="Qi without shore.",
        description="Cultivation quickens and the Qi stat itself grows.",
        bonus={"cultivation_speed_pct": 0.20, "qi_pct": 0.15},
    ),
    "Essence of Fortune's Hand": DaoEssenceSpec(
        name="Essence of Fortune's Hand",
        tagline="The Dao does not gamble; it simply already knows.",
        description="Luck, loot, and spirit stone rewards all rise.",
        bonus={"luck_flat": 300.0, "loot_chance_bonus_pct": 0.25, "stone_reward_bonus_pct": 0.25},
    ),
    "Essence of the Sovereign": DaoEssenceSpec(
        name="Essence of the Sovereign",
        tagline="Made for taking another cultivator's life.",
        description="Damage against other cultivators rises, and armor means less against you.",
        bonus={"pvp_damage_pct": 0.20, "armor_penetration_pct": 0.15},
    ),
    "Essence of the Myriad Gu": DaoEssenceSpec(
        name="Essence of the Myriad Gu",
        tagline="Your Gu Pet shares in your ascension.",
        description="Your active Gu Pet's combat power surges, and its bleed cuts deeper.",
        bonus={"gu_pet_power_pct": 0.25, "gu_pet_bleed_damage_pct": 0.20},
    ),
    UNDYING_VOW_NAME: DaoEssenceSpec(
        name=UNDYING_VOW_NAME,
        tagline="Death itself owes you a debt, and debts compound.",
        description=(
            "Once per encounter, a lethal blow instead leaves you at 1 HP, cleanses your active "
            "debuffs, and grants a brief retaliation strike."
        ),
        bonus={},
    ),
}
