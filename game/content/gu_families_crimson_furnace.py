"""
Crimson Furnace Province (Core Formation) upgrade-family Gu — content expansion brief
section 10.1's own named list for this region. Same plain-data shape as the other two
regions' Gu family modules, merged into GU_FAMILIES from equipment.py the same way.

drop_rank 3 (one tier above Hundred Beast Mountains' drop_rank 2), matching this region's
monsters' own gu_rank=3.

Each leans into one reading of its one-word brief description, distinct from every
Rank-1/Rank-2 family already built:
  Furnace Heart Gu    — qi_stat (the brief's own "Qi and battle Qi" — battle Qi itself has
                         no separate equipment-bonus hook anywhere in this game, qi_stat is
                         the real stat that actually feeds both cultivation qi rate context
                         and battle Qi's own max via qi_stat, so this covers the brief's
                         intent without inventing a second, parallel "battle Qi" stat key).
  Magma Skin Gu       — DEF/HP + beast_damage_reduction_pct ("retaliation" isn't a real
                         mechanic — no counter-attack hook exists in combat.resolve_attack —
                         so this leans on "skin tough enough that retaliating barely matters"
                         instead of faking a counter-attack).
  Star-Iron Stomach Gu — stone_reward_bonus_pct + loot_chance_bonus_pct (the brief's own
                         "material or loot bonus", both at once).
  Ashwing Gu          — spd_stat + dodge_chance_pct ("death-resistance flavor" folds into
                         Ashwing Gu's own late-tier ignore_attack_chance rather than a
                         separate defeat-ward mechanic, which is already its own dedicated
                         effect_key elsewhere, not a Gu stat).
  Living Flame Gu     — physical_damage_pct + technique_damage_pct (the brief's own plain
                         "damage" — both damage types at once, a generalist offense family).
"""

GU_FAMILIES_CRIMSON_FURNACE = {
    "Furnace Heart Gu": {
        "drop_rank": 3,
        "qualities": {
            "Common": {"qi_stat": 15},
            "Uncommon": {"qi_stat": 24},
            "Rare": {"qi_stat": 36},
            "Epic": {"qi_stat": 52},
            "Legendary": {"qi_stat": 74},
            "Mythic": {"qi_stat": 104},
            "Immortal": {"qi_stat": 145},
        },
    },
    "Magma Skin Gu": {
        "drop_rank": 3,
        "qualities": {
            "Common": {"def_stat": 8, "hp": 30},
            "Uncommon": {"def_stat": 13, "hp": 48},
            "Rare": {"def_stat": 19, "hp": 70, "beast_damage_reduction_pct": 0.03},
            "Epic": {"def_stat": 28, "hp": 100, "beast_damage_reduction_pct": 0.05},
            "Legendary": {"def_stat": 40, "hp": 145, "beast_damage_reduction_pct": 0.08},
            "Mythic": {"def_stat": 56, "hp": 200, "beast_damage_reduction_pct": 0.12},
            "Immortal": {"def_stat": 78, "hp": 280, "beast_damage_reduction_pct": 0.18},
        },
    },
    "Star-Iron Stomach Gu": {
        "drop_rank": 3,
        "qualities": {
            "Common": {"stone_reward_bonus_pct": 0.03},
            "Uncommon": {"stone_reward_bonus_pct": 0.045, "loot_chance_bonus_pct": 0.02},
            "Rare": {"stone_reward_bonus_pct": 0.06, "loot_chance_bonus_pct": 0.03},
            "Epic": {"stone_reward_bonus_pct": 0.08, "loot_chance_bonus_pct": 0.05},
            "Legendary": {"stone_reward_bonus_pct": 0.11, "loot_chance_bonus_pct": 0.07},
            "Mythic": {"stone_reward_bonus_pct": 0.15, "loot_chance_bonus_pct": 0.10},
            "Immortal": {"stone_reward_bonus_pct": 0.20, "loot_chance_bonus_pct": 0.14},
        },
    },
    "Ashwing Gu": {
        "drop_rank": 3,
        "qualities": {
            "Common": {"spd_stat": 10, "dodge_chance_pct": 0.02},
            "Uncommon": {"spd_stat": 16, "dodge_chance_pct": 0.03},
            "Rare": {"spd_stat": 24, "dodge_chance_pct": 0.045},
            "Epic": {"spd_stat": 34, "dodge_chance_pct": 0.065},
            "Legendary": {"spd_stat": 48, "dodge_chance_pct": 0.09},
            "Mythic": {"spd_stat": 67, "dodge_chance_pct": 0.12},
            "Immortal": {"spd_stat": 92, "dodge_chance_pct": 0.16, "ignore_attack_chance": 0.05},
        },
    },
    "Living Flame Gu": {
        "drop_rank": 3,
        "qualities": {
            "Common": {"physical_damage_pct": 0.02},
            "Uncommon": {"physical_damage_pct": 0.03, "technique_damage_pct": 0.02},
            "Rare": {"physical_damage_pct": 0.045, "technique_damage_pct": 0.03},
            "Epic": {"physical_damage_pct": 0.065, "technique_damage_pct": 0.045},
            "Legendary": {"physical_damage_pct": 0.09, "technique_damage_pct": 0.065},
            "Mythic": {"physical_damage_pct": 0.13, "technique_damage_pct": 0.09},
            "Immortal": {"physical_damage_pct": 0.18, "technique_damage_pct": 0.13},
        },
    },
}
