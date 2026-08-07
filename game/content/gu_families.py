"""
Verdant Borderlands (Qi Condensation) upgrade-family Gu — content expansion brief section
10.1's own named list for this region. Pure data: a Gu family is just {"drop_rank": int,
"qualities": {quality: stat_bonuses}}, the exact same shape as equipment.py's own 4 existing
families (Ironhide Boar/Charging Tusk/Blood Boar/Savage Boar Gu) — equipment.py merges this
dict into GU_FAMILIES and _register_tiered_gu() does the rest (naming, descriptions,
EQUIPMENT registration, fusion-ladder eligibility) automatically, so nothing here needs its
own registration code.

The brief names 6 families (Iron Skin, Boar Strength, Moon Rabbit, Blood Fang, Bone Shield,
Concealed Fang) but only describes each in one word ("DEF", "STR", "luck/search", "crit or
low-HP offense", "beast damage reduction", "ATK or first-strike"). Each below leans into ONE
reading of that word deliberately DIFFERENT from what the 4 existing families already cover,
so all 10 families end up with a distinct build identity rather than overlapping ones:

  Iron Skin Gu       — pure DEF/HP + beast_damage_reduction_pct, no ignore_attack_chance
                        (Ironhide Boar Gu already owns "tanky all-rounder WITH ignore_attack"
                        — this one is the narrower "just very hard to hurt" build).
  Boar Strength Gu   — pure STR + physical_damage_pct (Charging Tusk Gu already owns the
                        STR+crit build, so this one skips crit for raw, and-additive damage%).
  Moon Rabbit Gu     — luck_stat + loot_chance_bonus_pct + stone_reward_bonus_pct (the
                        brief's own "luck/search" — an economy/collection build, a lane no
                        existing family touches at all).
  Blood Fang Gu      — crit_chance_pct + low_hp_atk_bonus + crit_damage_pct, i.e. BOTH
                        readings of "crit or low-HP offense" at once, hybridized rather than
                        picking one (Charging Tusk owns pure crit, Savage Boar owns pure
                        low-HP — this is deliberately the aggressive middle ground).
  Bone Shield Gu     — beast_damage_reduction_pct + ignore_attack_chance leading, minimal
                        DEF/HP (a beast-counter specialist, vs. Iron Skin's general tank).
  Concealed Fang Gu  — atk_stat + dodge_chance_pct (+ a late physical_damage_pct spike) —
                        "first-strike bonus" isn't an implemented mechanic (no round-aware
                        combat hook exists — see verdant_borderlands.py's own monster
                        docstring for the same call made there), so this leans on the
                        "ATM/evasive ambush striker" reading instead of faking one.

Every stat_bonuses key used below is real and already consumed somewhere in the combat/loot
pipeline (see GameManager.compute_equipment_bonuses/SPECIAL_BONUS_KEYS, hunt.py's loot roll,
raid.py's stone reward) — none of these six invent a new mechanic.
"""

VERDANT_BORDERLANDS_GU_FAMILIES = {
    "Iron Skin Gu": {
        "drop_rank": 1,
        "qualities": {
            "Common": {"def_stat": 3},
            "Uncommon": {"def_stat": 5},
            "Rare": {"def_stat": 8, "hp": 10},
            "Epic": {"def_stat": 12, "hp": 18},
            "Legendary": {"def_stat": 17, "hp": 28, "beast_damage_reduction_pct": 0.05},
            "Mythic": {"def_stat": 24, "hp": 40, "beast_damage_reduction_pct": 0.10},
            "Immortal": {"def_stat": 34, "hp": 60, "beast_damage_reduction_pct": 0.18},
        },
    },
    "Boar Strength Gu": {
        "drop_rank": 1,
        "qualities": {
            "Common": {"str_stat": 6},
            "Uncommon": {"str_stat": 10},
            "Rare": {"str_stat": 15, "physical_damage_pct": 0.02},
            "Epic": {"str_stat": 20, "physical_damage_pct": 0.04},
            "Legendary": {"str_stat": 28, "physical_damage_pct": 0.06},
            "Mythic": {"str_stat": 38, "physical_damage_pct": 0.09},
            "Immortal": {"str_stat": 52, "physical_damage_pct": 0.12, "hp": 20},
        },
    },
    "Moon Rabbit Gu": {
        "drop_rank": 1,
        "qualities": {
            "Common": {"luck_stat": 2},
            "Uncommon": {"luck_stat": 4},
            "Rare": {"luck_stat": 6, "loot_chance_bonus_pct": 0.03},
            "Epic": {"luck_stat": 9, "loot_chance_bonus_pct": 0.05},
            "Legendary": {"luck_stat": 13, "loot_chance_bonus_pct": 0.08},
            "Mythic": {"luck_stat": 18, "loot_chance_bonus_pct": 0.12},
            "Immortal": {"luck_stat": 25, "loot_chance_bonus_pct": 0.18, "stone_reward_bonus_pct": 0.05},
        },
    },
    "Blood Fang Gu": {
        "drop_rank": 1,
        "qualities": {
            "Common": {"crit_chance_pct": 0.02},
            "Uncommon": {"crit_chance_pct": 0.03, "low_hp_atk_bonus": 4},
            "Rare": {"crit_chance_pct": 0.04, "low_hp_atk_bonus": 7},
            "Epic": {"crit_chance_pct": 0.06, "low_hp_atk_bonus": 11, "crit_damage_pct": 0.10},
            "Legendary": {"crit_chance_pct": 0.08, "low_hp_atk_bonus": 16, "crit_damage_pct": 0.18},
            "Mythic": {"crit_chance_pct": 0.11, "low_hp_atk_bonus": 22, "crit_damage_pct": 0.28},
            "Immortal": {"crit_chance_pct": 0.15, "low_hp_atk_bonus": 30, "crit_damage_pct": 0.40},
        },
    },
    "Bone Shield Gu": {
        "drop_rank": 1,
        "qualities": {
            "Common": {"beast_damage_reduction_pct": 0.04},
            "Uncommon": {"beast_damage_reduction_pct": 0.06},
            "Rare": {"beast_damage_reduction_pct": 0.09, "def_stat": 3},
            "Epic": {"beast_damage_reduction_pct": 0.13, "def_stat": 5},
            "Legendary": {"beast_damage_reduction_pct": 0.18, "def_stat": 8, "ignore_attack_chance": 0.04},
            "Mythic": {"beast_damage_reduction_pct": 0.25, "def_stat": 12, "ignore_attack_chance": 0.08},
            "Immortal": {"beast_damage_reduction_pct": 0.35, "def_stat": 17, "ignore_attack_chance": 0.14},
        },
    },
    "Concealed Fang Gu": {
        "drop_rank": 1,
        "qualities": {
            "Common": {"atk_stat": 4},
            "Uncommon": {"atk_stat": 7, "dodge_chance_pct": 0.02},
            "Rare": {"atk_stat": 11, "dodge_chance_pct": 0.03},
            "Epic": {"atk_stat": 15, "dodge_chance_pct": 0.05},
            "Legendary": {"atk_stat": 21, "dodge_chance_pct": 0.07},
            "Mythic": {"atk_stat": 29, "dodge_chance_pct": 0.10},
            "Immortal": {"atk_stat": 40, "dodge_chance_pct": 0.15, "physical_damage_pct": 0.08},
        },
    },
}
