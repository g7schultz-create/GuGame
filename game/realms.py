"""
Cultivation realm progression, indexed by the player's flat `realm_index`.

Each Great Realm below is split into 4 substages — Early, Middle, Late, Peak —
so `realm_index` walks through GREAT_REALMS[0] Early/Middle/Late/Peak, then
GREAT_REALMS[1] Early/Middle/Late/Peak, and so on. Add more entries to
GREAT_REALMS later to extend the ladder; nothing else needs to change.

Power curve: every successful breakthrough multiplies STR/HP/SPD/DEF/QI(stat)
by a step multiplier (LCK is fortune, not fighting power, so it's untouched
here — it keeps growing from race/root/physique/path bonuses instead).
Crossing into a new Great Realm's Early stage applies a big multiplier;
moving between substages within the same Great Realm applies a small one.
Both the qi cost curve and the stat curve compound the same way, so the
"~5 lower-realm cultivators to match 1 higher-realm cultivator" framing holds
at any matching substage between two adjacent Great Realms.
"""

from dataclasses import dataclass
from typing import Optional

GREAT_REALMS = [
    {
        "name": "Qi Condensation",
        "description": "The beginning of cultivation. Learn to gather spiritual energy.",
    },
    {
        "name": "Foundation Establishment",
        "description": "Forge an unshakable cultivation foundation.",
    },
    {
        "name": "Core Formation",
        "description": "Condense a Golden Core. Greatly increases power.",
    },
    {
        "name": "Nascent Soul",
        "description": "A spiritual infant is born within the dantian.",
    },
    {
        "name": "Spirit Severing",
        "description": "Sever worldly karma and mortal attachments.",
    },
    {
        "name": "Dao Seeking",
        "description": "Comprehend one's Dao and begin walking the true path.",
    },
    {
        "name": "Ancient Realm",
        "description": "Body and soul approach perfection. Possess the power to influence the world itself.",
    },
    {
        "name": "Dao Realm",
        "description": "Transcend the boundary between mortal cultivation and true Dao — the essence of existence itself answers your call.",
    },
]

SUB_STAGES = ["Early", "Middle", "Late", "Peak"]

# Tunable growth constants.
BASE_QI_REQUIREMENT = 300          # qi cost of the very first breakthrough (Qi Condensation Early -> Middle)
SUBSTAGE_QI_GROWTH = 1.5           # extra qi cost per substage breakthrough within a Great Realm
GREAT_REALM_QI_GROWTH = 6.0        # additional qi cost multiplier crossing into a new Great Realm

SUBSTAGE_STAT_MULTIPLIER = 1.15    # power growth per substage breakthrough
GREAT_REALM_STAT_MULTIPLIER = 5.0  # power growth crossing into a new Great Realm


@dataclass
class RealmStage:
    index: int
    great_realm_index: int
    great_realm_name: str
    great_realm_description: str
    substage_name: str
    display_name: str


def _build_stages():
    stages = []
    qi_requirements = []  # qi_requirements[i] = qi cost to break through from stage i into stage i + 1
    step_multipliers = []  # step_multipliers[i] = stat multiplier applied when breaking through from stage i into stage i + 1
    qi_cost = None

    index = 0
    for great_realm_index, great_realm in enumerate(GREAT_REALMS):
        for substage_name in SUB_STAGES:
            if index > 0:
                crossing_great_realm = stages[-1].substage_name == "Peak"
                if qi_cost is None:
                    qi_cost = BASE_QI_REQUIREMENT
                elif crossing_great_realm:
                    qi_cost = round(qi_cost * SUBSTAGE_QI_GROWTH * GREAT_REALM_QI_GROWTH)
                else:
                    qi_cost = round(qi_cost * SUBSTAGE_QI_GROWTH)
                qi_requirements.append(qi_cost)
                step_multipliers.append(GREAT_REALM_STAT_MULTIPLIER if crossing_great_realm else SUBSTAGE_STAT_MULTIPLIER)

            stages.append(RealmStage(
                index=index,
                great_realm_index=great_realm_index,
                great_realm_name=great_realm["name"],
                great_realm_description=great_realm["description"],
                substage_name=substage_name,
                display_name=f"{great_realm['name']} ({substage_name})",
            ))
            index += 1

    return stages, qi_requirements, step_multipliers


STAGES, QI_REQUIREMENTS, STEP_MULTIPLIERS = _build_stages()


def realm_name(realm_index: int) -> str:
    if 0 <= realm_index < len(STAGES):
        return STAGES[realm_index].display_name
    return f"Beyond {STAGES[-1].display_name}"


def realm_description(realm_index: int) -> Optional[str]:
    if 0 <= realm_index < len(STAGES):
        return STAGES[realm_index].great_realm_description
    return None


def qi_required_for_next(realm_index: int):
    """Qi needed to attempt the next breakthrough, or None if already at the top stage."""
    if 0 <= realm_index < len(QI_REQUIREMENTS):
        return QI_REQUIREMENTS[realm_index]
    return None


def stat_multiplier_for_next(realm_index: int) -> float:
    """Multiplier applied to STR/HP/SPD/DEF/QI(stat) on a successful breakthrough out of realm_index."""
    if 0 <= realm_index < len(STEP_MULTIPLIERS):
        return STEP_MULTIPLIERS[realm_index]
    return 1.0


def is_great_realm_crossing(realm_index: int) -> bool:
    """Whether breaking through out of realm_index crosses into a new Great Realm's Early stage."""
    if 0 <= realm_index < len(STAGES):
        return STAGES[realm_index].substage_name == "Peak"
    return False


def is_max_realm(realm_index: int) -> bool:
    return realm_index >= len(STAGES) - 1
