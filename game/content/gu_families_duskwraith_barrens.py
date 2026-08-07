"""
Duskwraith Barrens (Nascent Soul) upgrade-family Gu — this region's own named list, same
plain-data shape as the three regions before it, merged into GU_FAMILIES from equipment.py
the same way.

drop_rank 4 (one tier above Crimson Furnace Province's drop_rank 3), matching this region's
monsters' own gu_rank=4. Flat stats scale up roughly the same ~1.4x-per-tier curve the
rank 2->3 jump already used; percentage bonuses stay in the same rough endgame band the
earlier families already settled into (dodge/crit/reduction topping out in the mid-teens to
low-30s%) rather than compounding forever, so a rank-4 Immortal Gu is a clear step up without
making every earlier family's cap suddenly irrelevant.

Each ties to one of this region's own hunt monster archetypes:
  Bonewrought Gu — HP/DEF + beast_damage_reduction_pct at higher tiers (Bonewrought Golem's
                   own Guardian archetype — the "big wall" reading, same lineage as Granite
                   Body Gu -> Magma Skin Gu).
  Duskfang Gu    — SPD + crit chance/damage (Duskfang Jackal's own Skirmisher archetype —
                   a fast pack-hunter's opportunistic bite, distinct from Wraithmoth Gu's
                   evasion reading of the same SPD-heavy stat block).
  Wraithmoth Gu  — SPD + dodge/ignore_attack_chance (Wraithmoth's own Assassin archetype —
                   same lineage as Ashwing Gu, leaning fully into evasion instead of crit).
  Soulglass Gu   — qi_stat + insight_gain_pct (Soulglass Serpent's own Mystic archetype —
                   Nascent Soul's own "spiritual infant" theme read as raw Qi plus a real
                   boost to manual insight gain, same lineage as Furnace Heart Gu's qi_stat
                   but leaning into the soul/insight half of that reading).
  Hollow Marrow Gu — HP + lifesteal_percent (Hollow Marrow Behemoth's own Brute archetype —
                   same lineage as Blood Boar Gu's lifesteal, sized for a much bigger body).
"""

GU_FAMILIES_DUSKWRAITH_BARRENS = {
    "Bonewrought Gu": {
        "drop_rank": 4,
        "qualities": {
            "Common": {"def_stat": 11, "hp": 42},
            "Uncommon": {"def_stat": 18, "hp": 67},
            "Rare": {"def_stat": 26, "hp": 98, "beast_damage_reduction_pct": 0.04},
            "Epic": {"def_stat": 38, "hp": 140, "beast_damage_reduction_pct": 0.06},
            "Legendary": {"def_stat": 54, "hp": 200, "beast_damage_reduction_pct": 0.10},
            "Mythic": {"def_stat": 76, "hp": 280, "beast_damage_reduction_pct": 0.15},
            "Immortal": {"def_stat": 106, "hp": 390, "beast_damage_reduction_pct": 0.22},
        },
    },
    "Duskfang Gu": {
        "drop_rank": 4,
        "qualities": {
            "Common": {"spd_stat": 14, "crit_chance_pct": 0.02},
            "Uncommon": {"spd_stat": 22, "crit_chance_pct": 0.03},
            "Rare": {"spd_stat": 32, "crit_chance_pct": 0.045},
            "Epic": {"spd_stat": 46, "crit_chance_pct": 0.065},
            "Legendary": {"spd_stat": 64, "crit_chance_pct": 0.09, "crit_damage_pct": 0.15},
            "Mythic": {"spd_stat": 88, "crit_chance_pct": 0.12, "crit_damage_pct": 0.24},
            "Immortal": {"spd_stat": 120, "crit_chance_pct": 0.16, "crit_damage_pct": 0.35},
        },
    },
    "Wraithmoth Gu": {
        "drop_rank": 4,
        "qualities": {
            "Common": {"spd_stat": 14, "dodge_chance_pct": 0.025},
            "Uncommon": {"spd_stat": 22, "dodge_chance_pct": 0.04},
            "Rare": {"spd_stat": 33, "dodge_chance_pct": 0.055},
            "Epic": {"spd_stat": 47, "dodge_chance_pct": 0.08},
            "Legendary": {"spd_stat": 66, "dodge_chance_pct": 0.11, "ignore_attack_chance": 0.04},
            "Mythic": {"spd_stat": 92, "dodge_chance_pct": 0.15, "ignore_attack_chance": 0.07},
            "Immortal": {"spd_stat": 126, "dodge_chance_pct": 0.20, "ignore_attack_chance": 0.10},
        },
    },
    "Soulglass Gu": {
        "drop_rank": 4,
        "qualities": {
            "Common": {"qi_stat": 21},
            "Uncommon": {"qi_stat": 34, "insight_gain_pct": 0.02},
            "Rare": {"qi_stat": 50, "insight_gain_pct": 0.03},
            "Epic": {"qi_stat": 72, "insight_gain_pct": 0.05},
            "Legendary": {"qi_stat": 102, "insight_gain_pct": 0.07},
            "Mythic": {"qi_stat": 144, "insight_gain_pct": 0.10},
            "Immortal": {"qi_stat": 200, "insight_gain_pct": 0.14},
        },
    },
    "Hollow Marrow Gu": {
        "drop_rank": 4,
        "qualities": {
            "Common": {"hp": 55, "lifesteal_percent": 0.04},
            "Uncommon": {"hp": 85, "lifesteal_percent": 0.06},
            "Rare": {"hp": 125, "lifesteal_percent": 0.08},
            "Epic": {"hp": 175, "lifesteal_percent": 0.11},
            "Legendary": {"hp": 245, "lifesteal_percent": 0.15},
            "Mythic": {"hp": 340, "lifesteal_percent": 0.20},
            "Immortal": {"hp": 470, "lifesteal_percent": 0.27},
        },
    },
}
