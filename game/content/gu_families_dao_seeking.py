"""
Ten Thousand Dao Wilderness (Dao Seeking) upgrade-family Gu — this region's own named list,
same plain-data shape as the four regions before it, merged into GU_FAMILIES from equipment.py
the same way.

drop_rank 6 (two tiers above Duskwraith Barrens' drop_rank 4), matching this region's monsters'
own gu_rank=6. Unlike every prior region's Gu families (which give their primary stat as a flat
number), this region's primary stats are PERCENTAGE bonuses (def_pct/hp_pct/spd_pct/qi_pct) --
per explicit request. These already ride the exact same generic resolution path crafted gear's
own str_pct/atk_pct/def_pct/spd_pct/hp_pct/qi_pct use (see equipment.CRAFTED_GEAR_PCT_TO_FLAT
and GameManager.compute_equipment_bonuses' crafted_pct_totals loop) -- no new plumbing needed,
each just resolves against the player's own real current stat (max_hp for hp_pct) instead of
adding a fixed number. Curve reuses this same file's own crit_chance_pct shape exactly
(2/3/4.5/6.5/9/12/17% Common->Immortal) for every primary-stat percentage, so a rank-6 Gu's
primary stat stays in the same "mid-teens to low-30s%" endgame band every other percentage
effect across every region already settled into, rather than compounding into something that
dwarfs a whole crafted-gear piece's own tier-6 budget (blacksmith.TIER_PCT_BUDGET[6] == 47%
split across 2-4 stats). Secondary percentage effects (crit/dodge/lifesteal/insight_gain/
beast_damage_reduction) are unchanged from the original design.

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
            "Common": {"def_pct": 0.02, "hp_pct": 0.02},
            "Uncommon": {"def_pct": 0.03, "hp_pct": 0.03},
            "Rare": {"def_pct": 0.045, "hp_pct": 0.045, "beast_damage_reduction_pct": 0.04},
            "Epic": {"def_pct": 0.065, "hp_pct": 0.065, "beast_damage_reduction_pct": 0.06},
            "Legendary": {"def_pct": 0.09, "hp_pct": 0.09, "beast_damage_reduction_pct": 0.10},
            "Mythic": {"def_pct": 0.12, "hp_pct": 0.12, "beast_damage_reduction_pct": 0.15},
            "Immortal": {"def_pct": 0.17, "hp_pct": 0.17, "beast_damage_reduction_pct": 0.23},
        },
    },
    "Gale Fang Gu": {
        "drop_rank": 6,
        "qualities": {
            "Common": {"spd_pct": 0.02, "crit_chance_pct": 0.02},
            "Uncommon": {"spd_pct": 0.03, "crit_chance_pct": 0.03},
            "Rare": {"spd_pct": 0.045, "crit_chance_pct": 0.045},
            "Epic": {"spd_pct": 0.065, "crit_chance_pct": 0.065},
            "Legendary": {"spd_pct": 0.09, "crit_chance_pct": 0.09, "crit_damage_pct": 0.15},
            "Mythic": {"spd_pct": 0.12, "crit_chance_pct": 0.12, "crit_damage_pct": 0.25},
            "Immortal": {"spd_pct": 0.17, "crit_chance_pct": 0.17, "crit_damage_pct": 0.36},
        },
    },
    "Thunderstep Gu": {
        "drop_rank": 6,
        "qualities": {
            "Common": {"spd_pct": 0.02, "dodge_chance_pct": 0.025},
            "Uncommon": {"spd_pct": 0.03, "dodge_chance_pct": 0.04},
            "Rare": {"spd_pct": 0.045, "dodge_chance_pct": 0.055},
            "Epic": {"spd_pct": 0.065, "dodge_chance_pct": 0.08},
            "Legendary": {"spd_pct": 0.09, "dodge_chance_pct": 0.11, "ignore_attack_chance": 0.04},
            "Mythic": {"spd_pct": 0.12, "dodge_chance_pct": 0.16, "ignore_attack_chance": 0.075},
            "Immortal": {"spd_pct": 0.17, "dodge_chance_pct": 0.21, "ignore_attack_chance": 0.11},
        },
    },
    "Crimson Vein Gu": {
        "drop_rank": 6,
        "qualities": {
            "Common": {"hp_pct": 0.02, "lifesteal_percent": 0.04},
            "Uncommon": {"hp_pct": 0.03, "lifesteal_percent": 0.06},
            "Rare": {"hp_pct": 0.045, "lifesteal_percent": 0.08},
            "Epic": {"hp_pct": 0.065, "lifesteal_percent": 0.11},
            "Legendary": {"hp_pct": 0.09, "lifesteal_percent": 0.15},
            "Mythic": {"hp_pct": 0.12, "lifesteal_percent": 0.21},
            "Immortal": {"hp_pct": 0.17, "lifesteal_percent": 0.28},
        },
    },
    "Hollow Sage Gu": {
        "drop_rank": 6,
        "qualities": {
            "Common": {"qi_pct": 0.02},
            "Uncommon": {"qi_pct": 0.03, "insight_gain_pct": 0.02},
            "Rare": {"qi_pct": 0.045, "insight_gain_pct": 0.03},
            "Epic": {"qi_pct": 0.065, "insight_gain_pct": 0.05},
            "Legendary": {"qi_pct": 0.09, "insight_gain_pct": 0.07},
            "Mythic": {"qi_pct": 0.12, "insight_gain_pct": 0.11},
            "Immortal": {"qi_pct": 0.17, "insight_gain_pct": 0.15},
        },
    },
}
