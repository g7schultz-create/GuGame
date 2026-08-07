"""
Hundred Beast Mountains (Foundation Establishment) upgrade-family Gu — content expansion
brief section 10.1's own named list for this region. Same plain-data shape as
game/content/gu_families.py's Verdant Borderlands set (and merged into GU_FAMILIES the
same way, from equipment.py) — split into its own module purely to keep each region's
content independently reviewable.

drop_rank 2 (one tier above Verdant Borderlands' drop_rank 1), matching this region's
monsters' own gu_rank=2 — TIER_1_GU_COMMON_POOL (drop_rank == 1 only) is untouched by
these; Ironbeak Vulture and Mountain-Burrowing Lizard's shared-pool "Rare" slots still only
reach the 10 Verdant Borderlands families, not these 5, the same "no rank-2 shared pool
exists yet" gap Boar King's own drop table already flagged before this batch (see its
comment: "Rare-chance Tier 2 Gu families don't exist yet — reserved for future content").
A rank-2 shared pool now COULD be built the same way TIER_1_GU_COMMON_POOL was, but that's
a Boar King balance change (adding a brand new drop line to previously-untouched, protected
content) rather than pure addition, so it's left as an explicit future option rather than
done silently here.

Each leans into a different reading of its one-word brief description, distinct from every
Rank-1 family already built:
  Granite Body Gu  — pure HP/DEF, heavier than Iron Skin Gu but with no % modifiers at all
                      (the "big dumb wall" reading of "HP/DEF").
  Cloudstep Gu     — pure SPD + dodge_chance_pct (the brief's own "SPD/dodge").
  Thunderhorn Gu   — STR + a burst physical_damage_pct that scales faster than it starts
                      (the brief's own "empowered damage" — a charge-like power curve).
  Ghost Eye Gu     — crit_chance_pct leading into ignore_attack_chance at high quality (the
                      brief's own "crit chance or ignore defense" — both, in sequence).
  Venom Web Gu     — beast_damage_reduction_pct + dodge_chance_pct (the brief's own "control
                      or poison future hook" — no status-effect system exists to hang a real
                      poison-DoT mechanic off, so this leans on "web = hard to pin down and
                      hard to be hurt by" instead of faking a poison mechanic).
"""

GU_FAMILIES_HUNDRED_BEAST_MOUNTAINS = {
    "Granite Body Gu": {
        "drop_rank": 2,
        "qualities": {
            "Common": {"hp": 20, "def_stat": 4},
            "Uncommon": {"hp": 32, "def_stat": 6},
            "Rare": {"hp": 48, "def_stat": 10},
            "Epic": {"hp": 70, "def_stat": 16},
            "Legendary": {"hp": 100, "def_stat": 24},
            "Mythic": {"hp": 140, "def_stat": 34},
            "Immortal": {"hp": 190, "def_stat": 48},
        },
    },
    "Cloudstep Gu": {
        "drop_rank": 2,
        "qualities": {
            "Common": {"spd_stat": 5, "dodge_chance_pct": 0.02},
            "Uncommon": {"spd_stat": 8, "dodge_chance_pct": 0.03},
            "Rare": {"spd_stat": 12, "dodge_chance_pct": 0.04},
            "Epic": {"spd_stat": 17, "dodge_chance_pct": 0.06},
            "Legendary": {"spd_stat": 24, "dodge_chance_pct": 0.08},
            "Mythic": {"spd_stat": 33, "dodge_chance_pct": 0.11},
            "Immortal": {"spd_stat": 45, "dodge_chance_pct": 0.15},
        },
    },
    "Thunderhorn Gu": {
        "drop_rank": 2,
        "qualities": {
            "Common": {"str_stat": 8},
            "Uncommon": {"str_stat": 13, "physical_damage_pct": 0.02},
            "Rare": {"str_stat": 19, "physical_damage_pct": 0.04},
            "Epic": {"str_stat": 27, "physical_damage_pct": 0.07},
            "Legendary": {"str_stat": 37, "physical_damage_pct": 0.10},
            "Mythic": {"str_stat": 50, "physical_damage_pct": 0.14},
            "Immortal": {"str_stat": 68, "physical_damage_pct": 0.19},
        },
    },
    "Ghost Eye Gu": {
        "drop_rank": 2,
        "qualities": {
            "Common": {"crit_chance_pct": 0.02},
            "Uncommon": {"crit_chance_pct": 0.035},
            "Rare": {"crit_chance_pct": 0.05},
            "Epic": {"crit_chance_pct": 0.07, "crit_damage_pct": 0.12},
            "Legendary": {"crit_chance_pct": 0.09, "crit_damage_pct": 0.20, "ignore_attack_chance": 0.03},
            "Mythic": {"crit_chance_pct": 0.12, "crit_damage_pct": 0.30, "ignore_attack_chance": 0.06},
            "Immortal": {"crit_chance_pct": 0.16, "crit_damage_pct": 0.42, "ignore_attack_chance": 0.10},
        },
    },
    "Venom Web Gu": {
        "drop_rank": 2,
        "qualities": {
            "Common": {"beast_damage_reduction_pct": 0.03},
            "Uncommon": {"beast_damage_reduction_pct": 0.05, "dodge_chance_pct": 0.02},
            "Rare": {"beast_damage_reduction_pct": 0.07, "dodge_chance_pct": 0.03},
            "Epic": {"beast_damage_reduction_pct": 0.10, "dodge_chance_pct": 0.04},
            "Legendary": {"beast_damage_reduction_pct": 0.14, "dodge_chance_pct": 0.06},
            "Mythic": {"beast_damage_reduction_pct": 0.19, "dodge_chance_pct": 0.09},
            "Immortal": {"beast_damage_reduction_pct": 0.26, "dodge_chance_pct": 0.13},
        },
    },
}
