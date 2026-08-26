"""
"Immortal Raid" prototype -- an admin-only preview of a coordination-heavy raid boss encounter
(see game/immortal_raid_view.py, ImmortalRaidView) built around monsters.py's new opt-in
BossPhase/BossMove/break-gauge/hard-enrage/revival/lifesteal-reduction fields. Deliberately NOT
imported into monsters.py's own RAID_GROUPS_BY_REALM/BOSS_GROUPS/MONSTERS merge -- only
ImmortalRaidView/cog.py import HEAVEN_DEVOURING_DRAGON directly, so it can never become
selectable from /raid's own realm dropdown (same isolation blood_sea_ancestor.py's Inheritance
Ground roster already established).

Stat sizing worked from game/combat.py's real damage formula against an actual live strong
player's sheet (793.24M HP / 21.49M ATK / 171.74M STR / 12.01M SPD / 35.39M DEF / 574 LCK /
34.37M QI), not this codebase's own (much lower, Dao Seeking-era) in-repo boss content -- see
the approved plan (cryptic-nibbling-patterson.md) for the full worked math. Summary: a plain
attack from that player deals ~243.5M raw damage (crit-weighted average) before boss DEF
mitigates it; assuming a ~6-player raid of similar strength, boss HP/DEF/STR below are sized so
a full-attack-only clear takes roughly 10 rounds, leaving real room for coordination-check/
Formation/Save-Ally rounds before the hard_enrage_round=20 cutoff. All of these numbers are a
first pass, expect to retune once admins actually run the fight against real characters.
"""

from ...monsters import BossMove, BossPhase, DropEntry, Monster, MonsterAbility

WYRMLING = Monster(
    name="Devouring Wyrmling",
    realm="Rank 6 Beast (Raid)",
    monster_type="Beast",
    habitat="Spawned by the Heaven-Devouring Dragon",
    description="A half-formed shard of the Dragon's own hunger, given a body just solid enough to bite.",
    hp=300_000_000, atk_stat=1_500_000, str_stat=15_000_000, def_stat=20_000_000, spd_stat=5_000_000, luck_stat=10, qi_stat=1_000_000,
    ability=MonsterAbility(name="Gnawing Bite", description="A crude, hungry bite.", str_multiplier=1.2),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 6 Beast Core"),
        DropEntry(chance=0.60, item_name="Tier 6 Beast Material"),
    ],
    gu_rank=6,
)

HEAVEN_DEVOURING_DRAGON = Monster(
    name="Heaven-Devouring Dragon",
    realm="Rank 6 Beast (Raid)",
    monster_type="Beast",
    habitat="The Immortal Raid (admin-only preview)",
    description="A beast that gorged itself on Heavenly Dao until its own body could no longer contain what it swallowed. It comes apart in bursts of unraveling scale and devoured light.",
    hp=7_000_000_000, atk_stat=8_000_000, str_stat=60_000_000, def_stat=250_000_000,
    spd_stat=3_000_000, luck_stat=20, qi_stat=5_000_000,
    ability=MonsterAbility(name="Devouring Maw", description="Jaws wide enough to swallow a mountain.", str_multiplier=1.5),
    drops=[
        DropEntry(chance=1.00, item_name="Tier 6 Beast Core", quantity=4),
        DropEntry(chance=1.00, item_name="Tier 6 Beast Material", quantity=3),
        DropEntry(chance=0.35, item_name="Primeval Essence Crystal", quantity=20),
    ],
    break_gauge_max=1_500_000_000, break_gauge_damage_pct_of_hit=0.5,
    shattered_duration_rounds=2, shattered_damage_taken_pct_bonus=0.35, shattered_atk_pct_reduction=0.50,
    lifesteal_reduction_pct=0.6,
    phases=[
        BossPhase(hp_pct=0.66, atk_pct_bonus=0.15, announce="⚡ The Dragon's scales crack! (+15% ATK)"),
        BossPhase(
            hp_pct=0.33, atk_pct_bonus=0.25, move_weight_overrides={"Meteor Wing Barrage": 3.0},
            spawn_adds=[WYRMLING, WYRMLING], announce="🐲 The Dragon calls its Wyrmlings! (+25% ATK, two adds spawn)",
        ),
    ],
    moveset=[
        BossMove(
            "Meteor Wing Barrage", telegraph_rounds=2, damage_mode="cleave", str_multiplier=1.1,
            base_weight=2.0, cooldown_rounds=5,
            telegraph_text="The Dragon's wings glow — everyone will be hit in 2 rounds!",
            weight_conditions=[{"if": "hp_pct_below", "value": 0.5, "weight_multiplier": 2.0}],
        ),
        BossMove(
            "Heaven-Rending Roar", telegraph_rounds=2, formation_needed=3, interrupt_needed=2,
            coordination_success_damage_pct=0.05, coordination_failure_damage_pct=0.45,
            failure_boss_heal_pct=0.10, failure_boss_atk_pct_bonus=0.20, base_weight=2.5, cooldown_rounds=6,
            telegraph_text="The Dragon inhales! 3+ must hold Formation AND 2+ must Interrupt, or the party is devastated!",
        ),
        BossMove(
            "Consuming Maw", telegraph_rounds=1, damage_mode="single", str_multiplier=4.0,
            base_weight=1.5, cooldown_rounds=4,
            weight_conditions=[{"if": "defensive_formation_active", "weight_multiplier": 0.4}],
        ),
    ],
    hard_enrage_round=20, hard_enrage_damage_pct=1.0,
    hard_enrage_log="The Dragon completes its ascension — the raid is annihilated.",
    revival_enabled=True, revival_window_rounds=3, revival_hp_pct=0.30,
    gu_rank=6,
)
