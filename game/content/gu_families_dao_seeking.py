"""
Ten Thousand Dao Wilderness (Dao Seeking) upgrade-family Gu — this region's own named list,
same plain-data shape as the four regions before it, merged into GU_FAMILIES from equipment.py
the same way.

drop_rank 6 (two tiers above Duskwraith Barrens' drop_rank 4), matching this region's monsters'
own gu_rank=6. Flat stats scale up the same ~1.4x-per-tier curve every prior jump used (two
more steps over Duskwraith Barrens' own rank-4 numbers, ~1.96x total). Percentage bonuses
DELIBERATELY stay in the same rough endgame band every earlier region already settled into
(dodge/crit/reduction topping out in the mid-teens to low-30s%) rather than compounding
forever — per Duskwraith Barrens' own stated design rule, a higher-rank Immortal Gu should be
a clear step up on flat power without making every earlier family's own percentage cap
suddenly irrelevant.

Each ties to one of this region's own hunt monster archetypes (and, one level further out, to
one of this game's real Dao Paths — see game/content/monsters/dao_seeking.py's own module
docstring for the full theme):
  Stoneheart Gu    — DEF/HP + beast_damage_reduction_pct at higher tiers (Stoneheart Dao
                     Warden's own Guardian archetype/Earth Dao — the "big wall" reading, same
                     lineage as Bonewrought Gu -> Granite Body Gu -> Magma Skin Gu).
  Gale Fang Gu     — SPD + crit chance/damage (Gale-Dao Harrier's own Skirmisher archetype/
                     Wind Dao — a ceaseless, opportunistic strike pattern, distinct from
                     Thunderstep Gu's evasion reading of the same SPD-heavy stat block).
  Thunderstep Gu   — SPD + dodge/ignore_attack_chance (Thunderstep Wraith's own Assassin
                     archetype/Lightning Dao — same lineage as Wraithmoth Gu, leaning fully
                     into evasion instead of crit).
  Crimson Vein Gu  — HP + lifesteal_percent (Crimson-Vein Dao Beast's own Brute archetype/
                     Blood Dao — same lineage as Hollow Marrow Gu's lifesteal, sized for an
                     even hungrier body).
  Hollow Sage Gu   — qi_stat + insight_gain_pct (Hollow Sage Wisp's own Mystic archetype/
                     Wisdom Dao — pure leftover insight read as raw Qi plus a real boost to
                     manual insight gain, same lineage as Soulglass Gu).
"""

GU_FAMILIES_DAO_SEEKING = {
    "Stoneheart Gu": {
        "drop_rank": 6,
        "qualities": {
            "Common": {"def_stat": 22, "hp": 82},
            "Uncommon": {"def_stat": 35, "hp": 131},
            "Rare": {"def_stat": 51, "hp": 192, "beast_damage_reduction_pct": 0.04},
            "Epic": {"def_stat": 74, "hp": 274, "beast_damage_reduction_pct": 0.06},
            "Legendary": {"def_stat": 106, "hp": 392, "beast_damage_reduction_pct": 0.10},
            "Mythic": {"def_stat": 149, "hp": 549, "beast_damage_reduction_pct": 0.15},
            "Immortal": {"def_stat": 208, "hp": 764, "beast_damage_reduction_pct": 0.23},
        },
    },
    "Gale Fang Gu": {
        "drop_rank": 6,
        "qualities": {
            "Common": {"spd_stat": 27, "crit_chance_pct": 0.02},
            "Uncommon": {"spd_stat": 43, "crit_chance_pct": 0.03},
            "Rare": {"spd_stat": 63, "crit_chance_pct": 0.045},
            "Epic": {"spd_stat": 90, "crit_chance_pct": 0.065},
            "Legendary": {"spd_stat": 125, "crit_chance_pct": 0.09, "crit_damage_pct": 0.15},
            "Mythic": {"spd_stat": 172, "crit_chance_pct": 0.12, "crit_damage_pct": 0.25},
            "Immortal": {"spd_stat": 235, "crit_chance_pct": 0.17, "crit_damage_pct": 0.36},
        },
    },
    "Thunderstep Gu": {
        "drop_rank": 6,
        "qualities": {
            "Common": {"spd_stat": 27, "dodge_chance_pct": 0.025},
            "Uncommon": {"spd_stat": 43, "dodge_chance_pct": 0.04},
            "Rare": {"spd_stat": 65, "dodge_chance_pct": 0.055},
            "Epic": {"spd_stat": 92, "dodge_chance_pct": 0.08},
            "Legendary": {"spd_stat": 129, "dodge_chance_pct": 0.11, "ignore_attack_chance": 0.04},
            "Mythic": {"spd_stat": 180, "dodge_chance_pct": 0.16, "ignore_attack_chance": 0.075},
            "Immortal": {"spd_stat": 247, "dodge_chance_pct": 0.21, "ignore_attack_chance": 0.11},
        },
    },
    "Crimson Vein Gu": {
        "drop_rank": 6,
        "qualities": {
            "Common": {"hp": 108, "lifesteal_percent": 0.04},
            "Uncommon": {"hp": 167, "lifesteal_percent": 0.06},
            "Rare": {"hp": 245, "lifesteal_percent": 0.08},
            "Epic": {"hp": 343, "lifesteal_percent": 0.11},
            "Legendary": {"hp": 480, "lifesteal_percent": 0.15},
            "Mythic": {"hp": 666, "lifesteal_percent": 0.21},
            "Immortal": {"hp": 921, "lifesteal_percent": 0.28},
        },
    },
    "Hollow Sage Gu": {
        "drop_rank": 6,
        "qualities": {
            "Common": {"qi_stat": 41},
            "Uncommon": {"qi_stat": 67, "insight_gain_pct": 0.02},
            "Rare": {"qi_stat": 98, "insight_gain_pct": 0.03},
            "Epic": {"qi_stat": 141, "insight_gain_pct": 0.05},
            "Legendary": {"qi_stat": 200, "insight_gain_pct": 0.07},
            "Mythic": {"qi_stat": 282, "insight_gain_pct": 0.11},
            "Immortal": {"qi_stat": 392, "insight_gain_pct": 0.15},
        },
    },
}
