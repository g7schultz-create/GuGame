"""
Combat stat formulas:

    ATK -> attacker's chance to hit at all, PLUS a secondary contribution to damage
    SPD -> a relative speed contest: the defender's chance to dodge a hit that landed,
           based on their SPD relative to the ATTACKER's own SPD (not an absolute number)
    LCK -> attacker's chance to land a critical hit
    STR -> the primary stat behind damage dealt on a non-crit hit
    DEF -> flat damage reduction

ATK's hit-chance formula caps out at MAX_HIT_CHANCE by just 24 points (see
HIT_CHANCE_PER_ATK below) — a fresh character's base roll is already 6-14, so without a
second job ATK effectively stops mattering within the first couple of realm breakthroughs,
no matter how much bigger the number gets from there. DAMAGE_PER_ATK gives it somewhere to
keep contributing at STR_stat's secondary rate, so growing it (via breakthroughs or gear)
keeps paying off well past the point hit chance itself saturates.

Dodge had the exact same problem, worse: DODGE_CHANCE_PER_SPD (0.01/point) against an
ABSOLUTE spd_stat meant any real player maxed out MAX_DODGE_CHANCE within the first realm or
two (55 SPD to cap — trivial when spd_stat reaches the tens of thousands by the endgame),
making SPD investment past that point (gear, Gu, pills, breakthroughs) completely wasted for
dodge specifically. 2026-08-17, explicit request ("dodge and speed stat matters"): reworked
into a RATIO against the ATTACKER's own SPD (mirrors hunt.py/raid.py/pvp_view.py's own
FLEE_CHANCE_PER_SPD_DIFF formula's "relative speed contest" framing, but ratio- rather than
difference-based, since a raw difference saturates just as fast once both sides' SPD reaches
real-player magnitude — verified against live player/monster SPD gaps, which already run into
the tens of thousands). A ratio is scale-invariant: doubling YOUR OWN spd_stat only helps if
it also grows relative to whatever's attacking you, so it never trivially saturates purely
from realm-driven absolute growth on both sides at once, and always has room to keep mattering
regardless of how large the raw numbers get.

All constants below are tunable.
"""

import random
from dataclasses import dataclass

BASE_HIT_CHANCE = 0.75
HIT_CHANCE_PER_ATK = 0.01
MIN_HIT_CHANCE = 0.50
MAX_HIT_CHANCE = 0.99

BASE_DODGE_CHANCE = 0.05  # dodge chance when defender_spd == attacker_spd exactly (an even speed matchup)
DODGE_RATIO_SCALE = 0.55  # multiplies the (defender-attacker)/(defender+attacker) ratio, which
                          # ranges -1 (attacker's SPD completely dominates) to +1 (defender's
                          # does) -- e.g. a defender with 2x the attacker's SPD lands around
                          # 23% dodge, 10x lands around 50%, asymptotically approaching
                          # MAX_DODGE_CHANCE only at an extreme (never realm-growth-trivial) edge
MIN_DODGE_CHANCE = 0.0
MAX_DODGE_CHANCE = 0.60
MONSTER_MAX_DODGE_CHANCE = 0.10  # separate, lower cap for monsters/raid bosses dodging a
                                 # player's attack — players felt like too many hits were
                                 # whiffing against high-SPD monsters; player-vs-player and
                                 # monster-vs-player dodge still use the normal MAX_DODGE_CHANCE.
                                 # Kept as a safety valve even under the new ratio formula (which
                                 # already naturally suppresses monster dodge on its own, since
                                 # real players consistently outscale their own realm's hunt
                                 # monster SPD by a wide margin) rather than removed outright.

BASE_CRIT_CHANCE = 0.05
CRIT_CHANCE_PER_LUCK = 0.01
MIN_CRIT_CHANCE = 0.0
MAX_CRIT_CHANCE = 0.75
CRIT_DAMAGE_MULTIPLIER = 1.5

DAMAGE_PER_STR = 1.0
DAMAGE_PER_ATK = 0.25  # secondary damage contribution — a quarter of STR's, so STR stays
                       # the primary damage stat and ATK stays primarily about hit chance,
                       # but a bigger ATK is never just a wasted number past the hit-chance cap
DAMAGE_VARIANCE = 0.15  # raw damage is randomized +/- this fraction
DEF_REDUCTION_PER_POINT = 0.5
MIN_DAMAGE = 1


def hit_chance(atk_stat: int) -> float:
    return max(MIN_HIT_CHANCE, min(MAX_HIT_CHANCE, BASE_HIT_CHANCE + atk_stat * HIT_CHANCE_PER_ATK))


def dodge_chance(defender_spd: int, attacker_spd: int) -> float:
    total = defender_spd + attacker_spd
    ratio = (defender_spd - attacker_spd) / total if total > 0 else 0.0
    return max(MIN_DODGE_CHANCE, min(MAX_DODGE_CHANCE, BASE_DODGE_CHANCE + DODGE_RATIO_SCALE * ratio))


def crit_chance(luck_stat: int) -> float:
    return max(MIN_CRIT_CHANCE, min(MAX_CRIT_CHANCE, BASE_CRIT_CHANCE + luck_stat * CRIT_CHANCE_PER_LUCK))


def damage_reduction(def_stat: int) -> float:
    return def_stat * DEF_REDUCTION_PER_POINT


def _raw_damage(str_stat: int, atk_stat: int) -> float:
    spread = random.uniform(1 - DAMAGE_VARIANCE, 1 + DAMAGE_VARIANCE)
    return (str_stat * DAMAGE_PER_STR + atk_stat * DAMAGE_PER_ATK) * spread


@dataclass
class AttackResult:
    hit: bool
    dodged: bool
    crit: bool
    damage: int
    ignored: bool = False  # defender's Gu (e.g. Ironhide Boar Gu) negated the hit entirely
    heal: int = 0  # attacker lifesteal (e.g. Blood Boar Gu) — HP to restore to the attacker


def resolve_attack(
    attacker_stats: dict,
    defender_stats: dict,
    str_multiplier: float = 1.0,
    incoming_reduction: float = 0.0,
    guaranteed_hit: bool = False,
    crit_chance_bonus: float = 0.0,
    crit_damage_bonus: float = 0.0,
    ignore_chance: float = 0.0,
    lifesteal_percent: float = 0.0,
    dodge_chance_bonus: float = 0.0,
    damage_pct_bonus: float = 0.0,
    max_dodge_chance: float = MAX_DODGE_CHANCE,
    armor_penetration_pct: float = 0.0,
) -> AttackResult:
    """Both dicts need atk_stat, str_stat, spd_stat, def_stat, luck_stat.
    str_multiplier scales raw damage (e.g. a 140%-STR ability passes 1.4).
    incoming_reduction is an extra fractional damage cut applied on top (e.g. Guard, or a
    Gu's flat damage-type resist — callers sum every applicable source into one value).
    guaranteed_hit (Qi-empowered attack) skips both the hit and dodge rolls entirely.
    crit_chance_bonus/crit_damage_bonus are Gu-sourced additions on top of the base crit formula.
    ignore_chance is the defender's chance (e.g. a Gu passive) to negate an already-landed hit.
    lifesteal_percent is the attacker's chance-free heal, as a fraction of damage dealt.
    dodge_chance_bonus is the defender's Gu-sourced addition on top of the base dodge formula.
    damage_pct_bonus is the attacker's flat final-damage increase (e.g. a manual's
    technique_damage_pct/physical_damage_pct — see manual_view.EFFECT_LABELS).
    max_dodge_chance overrides the usual MAX_DODGE_CHANCE cap — callers where the defender is
    a monster pass MONSTER_MAX_DODGE_CHANCE instead, since a high-SPD monster dodging 60% of
    the time felt overtuned; player and PvP defenders keep the normal cap.
    armor_penetration_pct is the attacker's fractional reduction of the DEFENDER's effective
    DEF stat before damage_reduction is applied (e.g. Sword Soul — see avatar.py)."""
    if not guaranteed_hit:
        if random.random() >= hit_chance(attacker_stats["atk_stat"]):
            return AttackResult(hit=False, dodged=False, crit=False, damage=0)

        if random.random() < min(max_dodge_chance, dodge_chance(defender_stats["spd_stat"], attacker_stats["spd_stat"]) + dodge_chance_bonus):
            return AttackResult(hit=True, dodged=True, crit=False, damage=0)

    if ignore_chance > 0 and random.random() < ignore_chance:
        return AttackResult(hit=True, dodged=False, crit=False, damage=0, ignored=True)

    is_crit = random.random() < min(1.0, crit_chance(attacker_stats["luck_stat"]) + crit_chance_bonus)
    dmg = _raw_damage(attacker_stats["str_stat"], attacker_stats["atk_stat"]) * str_multiplier
    if is_crit:
        dmg *= (CRIT_DAMAGE_MULTIPLIER + crit_damage_bonus)
    effective_def = defender_stats["def_stat"] * (1 - armor_penetration_pct)
    dmg -= damage_reduction(effective_def)
    dmg *= (1 - incoming_reduction)
    dmg *= (1 + damage_pct_bonus)

    damage = max(MIN_DAMAGE, round(dmg))
    heal = round(damage * lifesteal_percent) if lifesteal_percent > 0 else 0
    return AttackResult(hit=True, dodged=False, crit=is_crit, damage=damage, heal=heal)
