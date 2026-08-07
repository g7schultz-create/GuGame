"""
Dao Companion — two players bond together (see /offer_companion), each gaining a slice of
the other's raw stats that grows the longer they've been bonded, plus a once-daily "i dc"
qi burst for both of them. A purely mutual, symmetric peer bond (unlike sects.py's
master/disciple hierarchy) — this module only holds the pure constants/formula; GameManager
(game/manager.py) owns all the DB-backed state and orchestration.
"""

# "each cultivator gets a part of the others raw stats" -- starts modest and grows the longer
# the pair stays bonded, capped so it can never dominate a build. 20 weeks (~4.6 months) to
# reach the cap, rewarding a long-lived bond over a same-day pair-and-forget.
DAO_COMPANION_BASE_STAT_SHARE_PCT = 0.05
DAO_COMPANION_STAT_SHARE_PER_WEEK_PCT = 0.01
DAO_COMPANION_MAX_STAT_SHARE_PCT = 0.25

# "i dc" -- once per day, per player (see GameManager._check_cooldown / last_dc_burst_ts).
DAO_COMPANION_BURST_COOLDOWN_SECONDS = 86400
# Each partner's own qi rate x this many minutes (5h) -- no aptitude/realm scaling like
# /teach's formula, since this is a peer bond rather than a mentorship (see
# manager.dao_companion_burst).
DAO_COMPANION_BURST_RATE_MINUTES = 5 * 60

# The 7 foundation-stat columns shared between partners -- same set equipment.
# FOUNDATION_STAT_LABELS already names, read straight off players.<column> (raw base stats,
# untouched by gear/buffs/dao-path/companion bonuses themselves).
DAO_COMPANION_SHARED_STATS = ("str_stat", "atk_stat", "hp", "spd_stat", "def_stat", "qi_stat", "luck_stat")


def stat_share_pct(bonded_seconds: int) -> float:
    """Fraction of the partner's raw stats each side gains, as a function of how long the
    bond has existed -- linear ramp from the base up to the cap."""
    weeks = max(0, bonded_seconds) / (7 * 86400)
    return min(DAO_COMPANION_MAX_STAT_SHARE_PCT, DAO_COMPANION_BASE_STAT_SHARE_PCT + weeks * DAO_COMPANION_STAT_SHARE_PER_WEEK_PCT)
