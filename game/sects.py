"""
Sects (see Sect_System_Design_For_Claude.md). Built incrementally, matching the doc's own
"phased" philosophy:

  Phase 1 -- core structure (create/join/leave), the 5-rank hierarchy with permissions, and
  a basic spirit-stone treasury.
  Phase 2 -- mentor/disciple teaching (this slice).

Contribution points, region wars, sect buildings, missions, and leaderboards are all still
out of scope -- nothing here fakes any of those; they're separate later phases.

Membership now goes through the doc's own Leader/Vice-Leader "Accept applications" gate:
/sect_join queues a pending sect_applications row (see database.py's table docstring)
instead of seating the applicant directly, and a Vice Leader or the Sect Leader reviews the
queue from /sect's Applications screen. The doc's separate "Invite" half (a member
proactively inviting someone in, rather than someone applying) isn't built -- nothing here
fakes it, it's still a real gap, just a smaller one than the whole application flow was.
Kicking still exists (Leader only, per the doc's own permission table) since removing a
member doesn't need any application machinery.

Mentor/disciple (see the section below): "(Optional) Experienced Inner Disciple" as an
alternate path to becoming a master was dropped -- there's no experience-tracking system to
gate that by, so the requirement is the doc's other, concrete one: Elder or higher. The
"Master's Realm Modifier" in the doc's Base Qi formula isn't defined numerically anywhere in
the doc, so it's interpreted here as the master's own effective qi rate (their real
cultivation strength -- gear, root, physique, manuals, all of it) rather than an arbitrary
flat number, which fits "the master channels experience and insight" and naturally scales
with realm the way the doc implies without a second undefined constant. No cap against the
disciple's own next-breakthrough requirement -- an earlier version of this system added one,
but a master's real cultivation strength (multiplied by the realm-gap table below) is now
allowed to carry a lesson as far as it earns, including past a full breakthrough on a large
enough gap. Sect buildings scaling the bonus, Contribution/Merit/Reputation/Loyalty/mentor
achievements/weekly rankings, "small luck increase while grouped," "higher inheritance
success chance," and mentor quests are all skipped -- either explicitly marked optional in
the doc or dependent on systems (contribution economy, a quest engine, buildings) that don't
exist yet in this codebase.

Personal disciples (see the section at the bottom of this file): a request beyond the design
doc's own scope, not something the doc describes -- a second, sect-independent mentor track
(/master_offer, /master_teach_all) that ANY player can use, no sect or Elder+ rank required,
capped lower (3 vs the sect track's 5) and taught in one bulk action on a much shorter
cooldown. Fully separate from the sect mentor track above (its own master/cooldown columns,
its own cap) rather than a generalization of it -- a player can hold both a sect disciple and
a personal disciple relationship at the same time, since they're unrelated pools.
"""

from typing import Optional

# Rank order, weakest to strongest -- mirrors professions.py's RANKS list shape (a plain
# ordered list + a lookup helper) rather than inventing a different convention for one more
# ranked-ladder system.
SECT_RANKS = ["Outer Disciple", "Inner Disciple", "Elder", "Vice Leader", "Sect Leader"]
OUTER_DISCIPLE, INNER_DISCIPLE, ELDER, VICE_LEADER, SECT_LEADER = SECT_RANKS
RANK_INDEX = {rank: i for i, rank in enumerate(SECT_RANKS)}

RANK_EMOJI = {
    "Sect Leader": "👑", "Vice Leader": "🔱", "Elder": "📜",
    "Inner Disciple": "🔵", "Outer Disciple": "⚪",
}

# Design doc's own stated limits (section "Core Structure").
MAX_MEMBERS = 50
MAX_VICE_LEADERS = 3
MAX_ELDERS = 10

# How far past the tier cap (see the shared ROOT_TIERS-style "growth ladder" other systems in
# this codebase use) a new sect name/motto/banner may run before Discord's own embed field
# limits start mattering -- kept simple/generous since these are just flavor text, not a
# balance lever.
MAX_NAME_LENGTH = 40
MAX_MOTTO_LENGTH = 200
MAX_BANNER_LENGTH = 8  # a single emoji (some are multi-codepoint) is plenty


def rank_index(rank: Optional[str]) -> int:
    return RANK_INDEX.get(rank, -1)


def can_kick(actor_rank: str) -> bool:
    """Per the design doc's own permission table, only the Sect Leader can kick -- Vice
    Leader's list stops at "Invite members / Accept applications", no removal power."""
    return actor_rank == SECT_LEADER


def can_edit_sect_info(actor_rank: str) -> bool:
    """Rename / motto / banner -- all Sect-Leader-only per the doc (Vice Leader "cannot
    rename sect")."""
    return actor_rank == SECT_LEADER


def can_withdraw_treasury(actor_rank: str) -> bool:
    """Sect Leader can "Spend Sect Treasury" freely; Vice Leader can "Spend limited
    treasury" -- Phase 1 doesn't yet have anything a limited-spend cap would meaningfully
    gate (no sect shop/buildings/wars to spend on yet), so both ranks share one withdraw
    permission for now rather than inventing an arbitrary cap number the doc doesn't specify.
    Revisit once there's a real sink to spend treasury on."""
    return actor_rank in (SECT_LEADER, VICE_LEADER)


def can_approve_applications(actor_rank: str) -> bool:
    """Per the design doc's own permission table, "Accept applications" sits on the same
    Leader/Vice-Leader row as "Invite members" -- Elder and below don't get it, matching
    can_kick/can_withdraw_treasury's own reading of that row."""
    return actor_rank in (SECT_LEADER, VICE_LEADER)


def promotable_target_ranks(actor_rank: str) -> list:
    """Which ranks actor_rank is allowed to PROMOTE a member TO. Sect Leader can promote up
    to Vice Leader (everything below); Vice Leader can promote up to Elder (explicit request
    to extend past the design doc's original "Promote to Inner Disciple only" reading, so a
    Vice Leader can now fill Elder seats without waiting on the Leader); Elder can only
    promote Outer -> Inner Disciple. Nothing below Elder has promotion power at all."""
    if actor_rank == SECT_LEADER:
        return [INNER_DISCIPLE, ELDER, VICE_LEADER]
    if actor_rank == VICE_LEADER:
        return [INNER_DISCIPLE, ELDER]
    if actor_rank == ELDER:
        return [INNER_DISCIPLE]
    return []


def demotable_target_ranks(actor_rank: str) -> list:
    """Which ranks actor_rank is allowed to DEMOTE a member FROM (the target's current rank
    before the demotion). Sect Leader can demote anyone below Leader (Vice Leader, Elder,
    Inner Disciple); Vice Leader can demote an Elder or Inner Disciple (2026-08-15, explicit
    request to extend past the design doc's original Leader-only reading, mirroring
    promotable_target_ranks' own Vice-Leader cap at Elder -- a Vice Leader can create an
    Elder via promote, so it's symmetric that they can also undo one, but they can't touch a
    fellow Vice Leader or the Sect Leader, avoiding a peer power struggle). Nothing below
    Vice Leader has demote power at all."""
    if actor_rank == SECT_LEADER:
        return [VICE_LEADER, ELDER, INNER_DISCIPLE]
    if actor_rank == VICE_LEADER:
        return [ELDER, INNER_DISCIPLE]
    return []


def can_demote(actor_rank: str) -> bool:
    """Whether actor_rank has ANY demote power at all -- see demotable_target_ranks for the
    actual per-target-rank cap."""
    return bool(demotable_target_ranks(actor_rank))


# -- Mentor/disciple (design doc section "Mentor / Disciple System") -------------------------

# "Maximum 3-5 disciples" -- the top of the doc's own suggested range, since Phase 1 has no
# contribution economy yet to otherwise reward an active mentor for their time.
MAX_DISCIPLES_PER_MASTER = 5

# Shortened from the doc's own "12-24 hours" to 3 hours per explicit request, made viable now
# that /teach hits the whole roster at once (see GameManager.sect_teach_all) instead of one
# disciple per use -- one shared cooldown across ALL of a master's disciples (see
# database.players.last_teach_ts), not per-disciple, so this still can't be spammed into a
# constant Qi drip.
TEACH_COOLDOWN_SECONDS = 3 * 3600

# Anti-abuse (design doc: "Disciple must remain in sect for a minimum time before switching
# masters") -- read broadly as "before entering ANY mentor relationship", not just a switch,
# since re-joining the sect already resets sect_joined_ts (see GameManager.sect_join), which
# covers the "switching" case for free without needing separate history tracking.
MIN_SECT_TENURE_BEFORE_MENTOR_SECONDS = 30 * 60

# "Base Qi = Realm Difference Multiplier x Master's Realm Modifier" -- the doc's own worked
# multiplier table, keyed by (master's Great Realm index) - (disciple's Great Realm index).
# A gap of 5+ realms is capped at the doc's own 3.5x ceiling rather than continuing to climb.
REALM_DIFF_QI_MULTIPLIER = {1: 1.25, 2: 1.6, 3: 2.1, 4: 2.8}
REALM_DIFF_QI_MULTIPLIER_CAP = 3.5

# "The bonus should also scale modestly with the master's aptitude" -- aptitude runs 0-100,
# so this caps out at a +50% swing (100 / 200) at a perfect roll, never the dominant factor.
TEACH_APTITUDE_SCALE_DIVISOR = 200.0

# "Master's Realm Modifier" (see this module's own docstring for why it's the master's real
# effective qi rate, not an arbitrary flat number) -- how many minutes' worth of that rate a
# single lesson is worth, before the realm-difference multiplier is applied. No cap against
# the disciple's own next-breakthrough requirement (see this module's own docstring) -- the
# realm-gap multiplier below is the only thing shaping how big a lesson gets from here.
TEACH_MASTER_RATE_MINUTES = 120

# "Master Benefits... Small cultivation gain" -- the only benefit from the doc's own list this
# codebase can implement for real yet (Contribution/Merit/Reputation/Loyalty/achievements/
# rankings all need systems that don't exist). Sized as a fraction of what the disciple
# received, so it scales with the same lesson rather than needing its own separate formula.
TEACH_MASTER_BONUS_PCT = 0.15


def can_accept_disciples(rank: str) -> bool:
    """"Elder or higher" per the doc -- see this module's own docstring for why the
    alternate "(Optional) Experienced Inner Disciple" path was dropped."""
    return rank_index(rank) >= rank_index(ELDER)


def realm_diff_qi_multiplier(realm_diff: int) -> float:
    if realm_diff >= 5:
        return REALM_DIFF_QI_MULTIPLIER_CAP
    return REALM_DIFF_QI_MULTIPLIER.get(realm_diff, 0.0)


# -- Personal disciples (no sect required) ---------------------------------------------------
# A second, independent mentor track: ANY player can take disciples this way, not just
# Elder+ sect members — no sect membership, no Elder+ rank, no MIN_SECT_TENURE wait. Lower
# cap, and taught in one bulk action (/master_teach_all) rather than one at a time (/teach).
# Same Qi formula as sect teaching either way (see GameManager.sect_teach /
# personal_teach_all) — the fairness/anti-exploit guardrails don't change just because a sect
# isn't involved.
MAX_PERSONAL_DISCIPLES = 3

# Per-DISCIPLE, not per-master: each disciple has their own independent clock (see
# database.players.personal_last_taught_ts), so /master_teach_all just teaches whoever's
# currently off cooldown each run instead of the whole roster sharing one gate that blocks
# everyone until the slowest disciple's timer clears.
PERSONAL_TEACH_COOLDOWN_SECONDS = 3 * 3600
