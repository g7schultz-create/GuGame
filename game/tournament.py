"""
PvP Tournament (/tournament) -- players sign up during a countdown window, a frozen "copy" of
their character (see GameManager._tournament_combat_snapshot) joins the roster, and once
signup closes every copy fights in a battle royale (random-target attacks, each round) until
one remains. Top 3 get real item rewards; everyone else gets spirit stones scaled by placement.

This module is pure logic -- no DB/GameManager/discord dependency, mirroring world_boss.py's
own split from manager.py -- so the simulation and reward table are directly unit-testable.

Combat itself reuses combat.resolve_attack, the exact same primitive /hunt, /raid, /pvp, and
World Boss all already share -- nothing new is invented at the attack-resolution level, only
the "N combatants, last one standing" loop around it.
"""

import random
from typing import Optional

from . import chargen, combat, dao_essences, dao_paths, equipment

# -- Lifecycle timing -------------------------------------------------------------------------

# Signup is now CONTINUOUS, per explicit request ("during the cool down people can sign up"):
# the signup window itself IS the full 4-hour cycle, and TOURNAMENT_COOLDOWN_SECONDS is 0, so
# GameManager.maybe_open_tournament opens the NEXT signup the instant the current one resolves
# (via the tick loop / TournamentView / /cd's shared get_tournament_status, same as before) --
# there's never a multi-hour gap where nobody can join. Net effect: a battle royale actually
# fires every 4 hours on the dot, but players can sign up for "whichever one's next" at any
# time in between, not just during a short window right after the previous one ended.
TOURNAMENT_SIGNUP_SECONDS = 4 * 3600
TOURNAMENT_COOLDOWN_SECONDS = 0
TOURNAMENT_MIN_PARTICIPANTS = 4            # smallest field where "top 3 + everyone else" means anything
TOURNAMENT_MAX_PARTICIPANTS = 64           # safety valve, not a realistic ceiling today
TOURNAMENT_MAX_ROUNDS = 150                # safety cap; HP-fraction tiebreak below if ever hit
TOURNAMENT_RUNNING_STALE_SECONDS = 120     # crash-recovery grace window -- see GameManager.resolve_tournament_if_ready
# How long /tournament still shows the last result before a fresh signup (already open behind
# it) takes over the screen -- no longer tied to TOURNAMENT_COOLDOWN_SECONDS (that's 0 now, so
# a fresh signup opens essentially immediately regardless); this is just a short courtesy
# window covering the rare case where a viewer catches the state between one resolving and the
# next tick/view reopening it, roughly matching the tick loop's own 5-minute cadence.
TOURNAMENT_COMPLETED_DISPLAY_SECONDS = 5 * 60


def _attack_kwargs(attacker_snapshot: dict, defender_snapshot: dict, defender_hp_ratio: float) -> dict:
    """Attacker-side kwargs mirror pvp_view.py's _do_attack; defender-side kwargs (dodge/ignore)
    mirror hunt.py/raid.py's fuller incoming-hit handling -- combined into one call since a
    tournament attack needs both halves at once, unlike pvp_view's two-separate-methods split."""
    a, d = attacker_snapshot["special"], defender_snapshot["special"]
    incoming_reduction = chargen.race_physique_damage_reduction(
        defender_snapshot.get("race"), defender_snapshot.get("physique_tier"), defender_hp_ratio,
    )
    return dict(
        crit_chance_bonus=a.get("crit_chance_pct", 0), crit_damage_bonus=a.get("crit_damage_pct", 0),
        lifesteal_percent=a.get("lifesteal_percent", 0),
        damage_pct_bonus=a.get("physical_damage_pct", 0) + a.get("total_damage_pct", 0) + a.get("pvp_damage_pct", 0),
        armor_penetration_pct=a.get("armor_penetration_pct", 0),
        dodge_chance_bonus=d.get("dodge_chance_pct", 0), ignore_chance=d.get("ignore_attack_chance", 0),
        incoming_reduction=incoming_reduction,
    )


def _describe_event(round_num: int, attacker_name: str, defender_name: str, result) -> str:
    if not result.hit:
        return f"Round {round_num}: {attacker_name} attacks {defender_name} but misses!"
    if result.dodged:
        return f"Round {round_num}: {defender_name} dodges {attacker_name}'s attack!"
    if result.ignored:
        return f"Round {round_num}: {defender_name}'s Gu shrugs off {attacker_name}'s attack entirely!"
    crit = " (Critical!)" if result.crit else ""
    return f"Round {round_num}: {attacker_name} hits {defender_name} for {result.damage} damage{crit}."


def _try_undying_vow(defender: dict, target_id, undying_vow_used: set, burn_state: dict, gu_pet_bleed_state: dict, round_num: int, events: list) -> bool:
    """True (and marks the charge used) if this elimination was saved by Essence of the
    Undying Vow -- see run_battle_royale's own docstring for the full mechanic. Shared by all
    3 elimination sites (attack, fire burn tick, Gu Pet bleed tick)."""
    if not defender.get("has_undying_vow") or target_id in undying_vow_used:
        return False
    undying_vow_used.add(target_id)
    defender["hp"] = 1.0
    burn_state.pop(target_id, None)
    gu_pet_bleed_state.pop(target_id, None)
    defender["_retaliation_bonus"] = dao_essences.UNDYING_VOW_RETALIATION_BONUS_PCT
    events.append(f"Round {round_num}: 🌌 {defender['name']}'s Undying Vow flares — death itself yields!")
    return True


def run_battle_royale(participants: list, rng: Optional[random.Random] = None) -> dict:
    """participants: [{"user_id", "name", "snapshot", "has_undying_vow"}, ...] where snapshot is
    {"stats": {atk_stat,str_stat,def_stat,spd_stat,luck_stat,hp}, "special": {...}, "race",
    "physique_tier"} -- see GameManager._tournament_combat_snapshot -- and has_undying_vow is a
    plain bool checked FRESH by the caller (GameManager._run_and_complete_tournament), not part
    of the frozen snapshot (see that method's own comment on why). Returns {"events": [str],
    "placements": [{"rank","user_id","name"}, ...] (1=winner..N=last), "rounds_used", "capped"}.

    Each round: shuffle the currently-alive user_id list (no fixed turn-order advantage), then
    each alive id in that order attacks once -- skipped if it was eliminated as someone else's
    target earlier THIS round -- against a uniformly random OTHER currently-alive target. An
    attacker only ever damages someone else, never themself, so a round can eliminate at most
    (alive_count - 1) targets: the pool shrinks but can never reach 0, guaranteeing the
    `while len(alive) > 1` loop always terminates with exactly one eventual survivor (barring
    the TOURNAMENT_MAX_ROUNDS safety cap, tiebroken deterministically by remaining HP fraction).

    Essence of the Undying Vow (see game/dao_essences.py) is the one exception to "eliminated
    means gone" -- once per battle per holder, whatever would eliminate them instead leaves them
    at 1 HP, cleanses their burn/bleed DoTs, and arms a one-shot retaliation damage bonus on
    their own next attack (read once, then cleared -- see the attack loop below). This is a pure
    in-memory function with no DB access mid-call, so the buff can't ride GameDatabase.add_buff
    the way every other combat site's version of this essence does -- a local flag on the
    participant dict is the equivalent for the duration of just this one function call."""
    r = rng or random
    alive = {
        p["user_id"]: {
            "name": p["name"], "hp": float(p["snapshot"]["stats"]["hp"]),
            "max_hp": max(1.0, float(p["snapshot"]["stats"]["hp"])), "snapshot": p["snapshot"],
            "has_undying_vow": p.get("has_undying_vow", False),
        }
        for p in participants
    }
    # Fire Dao Path burn (see dao_paths.fire_burn_tick_damage) -- target user_id -> [damage_
    # per_tick, ticks_remaining], seeded/refreshed on a landed hit, ticked once per round
    # after every attacker's turn (see the burn-tick block below).
    burn_state: dict = {}
    # Vampiric Beetle Gu Pet's own bleed DoT (see gu_pet.COMBAT_SPECIALTY_BASE_VALUES'
    # gu_pet_bleed_damage_pct) -- same shape as burn_state above, a second independent
    # damage-over-time pool (see the bleed-tick block below).
    gu_pet_bleed_state: dict = {}
    # Essence of the Undying Vow -- user_ids who've already burned their once-per-battle charge.
    undying_vow_used: set = set()
    events, eliminated_order, rounds_used = [], [], 0
    while len(alive) > 1 and rounds_used < TOURNAMENT_MAX_ROUNDS:
        rounds_used += 1
        turn_order = list(alive.keys())
        r.shuffle(turn_order)
        for attacker_id in turn_order:
            if attacker_id not in alive or len(alive) <= 1:
                continue
            target_id = r.choice([uid for uid in alive if uid != attacker_id])
            attacker, defender = alive[attacker_id], alive[target_id]
            kwargs = _attack_kwargs(attacker["snapshot"], defender["snapshot"], defender["hp"] / defender["max_hp"])
            # Essence of the Undying Vow's retaliation bonus (see _try_undying_vow) -- armed by
            # this participant's own most recent revive, consumed on their very next attack.
            retaliation_bonus = attacker.pop("_retaliation_bonus", 0)
            if retaliation_bonus:
                kwargs["damage_pct_bonus"] += retaliation_bonus
            result = combat.resolve_attack(attacker["snapshot"]["stats"], defender["snapshot"]["stats"], **kwargs)
            events.append(_describe_event(rounds_used, attacker["name"], defender["name"], result))
            if result.hit and not result.dodged and not result.ignored:
                defender["hp"] = max(0.0, defender["hp"] - result.damage)
                if result.heal:
                    attacker["hp"] = min(attacker["max_hp"], attacker["hp"] + result.heal)
                fire_pct = attacker["snapshot"]["special"].get("fire_burn_damage_pct", 0)
                if fire_pct > 0 and defender["hp"] > 0:
                    tick_damage = dao_paths.fire_burn_tick_damage(result.damage, fire_pct)
                    if tick_damage > 0:
                        burn_state[target_id] = [tick_damage, dao_paths.FIRE_BURN_TICKS]
                gu_pet_bleed_pct = attacker["snapshot"]["special"].get("gu_pet_bleed_damage_pct", 0)
                if gu_pet_bleed_pct > 0 and defender["hp"] > 0:
                    tick_damage = dao_paths.fire_burn_tick_damage(result.damage, gu_pet_bleed_pct)
                    if tick_damage > 0:
                        gu_pet_bleed_state[target_id] = [tick_damage, dao_paths.FIRE_BURN_TICKS]
                if defender["hp"] <= 0 and not _try_undying_vow(defender, target_id, undying_vow_used, burn_state, gu_pet_bleed_state, rounds_used, events):
                    eliminated_order.append(target_id)
                    del alive[target_id]
                    burn_state.pop(target_id, None)
                    gu_pet_bleed_state.pop(target_id, None)

        # Fire Dao Path burn ticks -- once per round, after every attacker's turn. Stops the
        # instant only 1 combatant remains (same invariant the attack loop above already
        # guarantees) so this can never bring `alive` down to 0.
        for target_id in list(burn_state.keys()):
            if len(alive) <= 1:
                break
            if target_id not in alive:
                burn_state.pop(target_id, None)
                continue
            tick_damage, ticks_remaining = burn_state[target_id]
            defender = alive[target_id]
            actual = min(defender["hp"], tick_damage)
            defender["hp"] -= actual
            events.append(f"Round {rounds_used}: {defender['name']} burns for {actual:.0f} damage.")
            if defender["hp"] <= 0 and not _try_undying_vow(defender, target_id, undying_vow_used, burn_state, gu_pet_bleed_state, rounds_used, events):
                eliminated_order.append(target_id)
                del alive[target_id]
                burn_state.pop(target_id, None)
            else:
                ticks_remaining -= 1
                if ticks_remaining <= 0:
                    burn_state.pop(target_id, None)
                else:
                    burn_state[target_id][1] = ticks_remaining

        # Vampiric Beetle Gu Pet bleed ticks -- same shape as the Fire Dao Path burn ticks
        # just above, a second independent damage-over-time pool.
        for target_id in list(gu_pet_bleed_state.keys()):
            if len(alive) <= 1:
                break
            if target_id not in alive:
                gu_pet_bleed_state.pop(target_id, None)
                continue
            tick_damage, ticks_remaining = gu_pet_bleed_state[target_id]
            defender = alive[target_id]
            actual = min(defender["hp"], tick_damage)
            defender["hp"] -= actual
            events.append(f"Round {rounds_used}: {defender['name']} bleeds for {actual:.0f} damage.")
            if defender["hp"] <= 0 and not _try_undying_vow(defender, target_id, undying_vow_used, burn_state, gu_pet_bleed_state, rounds_used, events):
                eliminated_order.append(target_id)
                del alive[target_id]
                gu_pet_bleed_state.pop(target_id, None)
            else:
                ticks_remaining -= 1
                if ticks_remaining <= 0:
                    gu_pet_bleed_state.pop(target_id, None)
                else:
                    gu_pet_bleed_state[target_id][1] = ticks_remaining

    capped = len(alive) > 1
    if capped:
        remaining = sorted(alive.items(), key=lambda kv: kv[1]["hp"] / kv[1]["max_hp"])
        eliminated_order += [uid for uid, _ in remaining[:-1]]
        winner_id = remaining[-1][0]
    else:
        winner_id = next(iter(alive))

    ranked_ids = [winner_id] + list(reversed(eliminated_order))
    names = {p["user_id"]: p["name"] for p in participants}
    placements = [{"rank": i + 1, "user_id": uid, "name": names[uid]} for i, uid in enumerate(ranked_ids)]
    return {"events": events, "placements": placements, "rounds_used": rounds_used, "capped": capped}


# -- Placement rewards --------------------------------------------------------------------------
# Calibrated against every existing spirit-stone scale already in this game: /pvp win = 15-40
# (manager.py), /raid win = 50-100 (raid.py), blacksmith.DISMANTLE_STONES_PER_TIER = 30/tier,
# manager.SALVAGE_STONES_PER_RANK_RARITY_STAR = 15, World Boss's realistic per-contributor
# guaranteed stones in the low thousands. A tournament placement is a harder-earned, GUARANTEED
# outcome (beat real opponents in an elimination bracket) rather than a lucky roll, so it sits
# clearly above /pvp/raid/dismantle but below World Boss's best-case ceiling (reachable by
# anyone, passively, at zero risk). Gu quality is a clean guaranteed descending ladder
# (Epic/Rare/Uncommon) instead of layering more RNG onto already-chance-based avatar/crafted
# gear rolls. Essence pills use a FIXED tier per rank rather than
# items.roll_essence_restoration_pill_drop's own tier-1-weighted RNG -- a guaranteed top-3
# reward shouldn't risk handing 1st a worse pill than 3rd by bad luck.
TOURNAMENT_PLACEMENT_REWARDS = {
    # essence_crystal_qty set per explicit request (250/150/100/50 for 1st/2nd/3rd/everyone
    # else) -- everything else (stones, Gu quality, avatar/crafted gear chances, essence pills)
    # unchanged from the original calibration above.
    1: {"stones": 5000, "essence_crystal_qty": 250, "gu_quality": "Epic",
        "avatar_gear_chance": 0.50, "avatar_gear_source_tier": 5,
        "crafted_gear_chance": 0.20, "crafted_gear_tier_range": (6, 7),
        "essence_pill_tier": 3, "essence_pill_qty": 2},
    2: {"stones": 2500, "essence_crystal_qty": 150, "gu_quality": "Rare",
        "avatar_gear_chance": 0.30, "avatar_gear_source_tier": 4,
        "crafted_gear_chance": 0.10, "crafted_gear_tier_range": (5, 6),
        "essence_pill_tier": 2, "essence_pill_qty": 2},
    3: {"stones": 1200, "essence_crystal_qty": 100, "gu_quality": "Uncommon",
        "avatar_gear_chance": 0.15, "avatar_gear_source_tier": 3,
        "crafted_gear_chance": 0.05, "crafted_gear_tier_range": (4, 5),
        "essence_pill_tier": 1, "essence_pill_qty": 2},
}

# 4th place onward: tapers off from just under 3rd's guaranteed stones down to a flat floor
# that's still above /pvp's own max win (40) -- even a round-1 elimination beats skipping the
# tournament entirely for a duel. The floor is flat, not participant-count-scaled, so a huge
# field's dead-last doesn't get an inflated reward just because more people showed up.
TOURNAMENT_PARTICIPATION_BASE_STONES = 600      # awarded at rank 4, the first non-podium rank
TOURNAMENT_PARTICIPATION_STEP_PER_RANK = 60     # subtracted per rank further back
TOURNAMENT_PARTICIPATION_FLOOR_STONES = 60      # dead last, regardless of field size
# Flat (not tapered) -- every non-podium finisher who actually signed up and fought gets the
# same 50 essence crystals, per explicit request ("everyone else who signed up gets 50").
TOURNAMENT_PARTICIPATION_ESSENCE_CRYSTAL_QTY = 50


def participation_stones(rank: int) -> int:
    return max(
        TOURNAMENT_PARTICIPATION_FLOOR_STONES,
        TOURNAMENT_PARTICIPATION_BASE_STONES - TOURNAMENT_PARTICIPATION_STEP_PER_RANK * (rank - 4),
    )


# -- Bonus Essence Restoration Pill lottery -----------------------------------------------------
# Per explicit request: 3 independent rolls, each an Essence Restoration Pill at a random tier
# out of 5, handed to a uniformly random participant -- "distributed randomly to anyone who
# joined" (not damage/placement-weighted, unlike World Boss's own lottery or this same
# tournament's own placement ladder above). Deliberately capped at tiers 1-5, not the pill's
# full 1-7 range (see items.ESSENCE_RESTORATION_PILL_TIER_WEIGHTS) -- tiers 6-7 stay a rarer
# find exclusive to that natural drop table, so this bonus doesn't quietly outclass it.
TOURNAMENT_BONUS_PILL_ROLL_COUNT = 3
TOURNAMENT_BONUS_PILL_TIERS = [1, 2, 3, 4, 5]


def roll_bonus_pill_winners(participant_user_ids: list, rng: Optional[random.Random] = None) -> list:
    """TOURNAMENT_BONUS_PILL_ROLL_COUNT independent, uniform-random draws -- repeats allowed
    (the same participant can win more than one roll), mirroring how
    GameManager._end_world_boss now runs multiple independent World Boss lottery rolls rather
    than just one. Each roll also independently picks a random tier from
    TOURNAMENT_BONUS_PILL_TIERS. Returns [(user_id, tier), ...one entry per roll], or [] if
    there were no participants to give anything to."""
    if not participant_user_ids:
        return []
    r = rng or random
    return [
        (r.choice(participant_user_ids), r.choice(TOURNAMENT_BONUS_PILL_TIERS))
        for _ in range(TOURNAMENT_BONUS_PILL_ROLL_COUNT)
    ]


# -- Bonus Epic Gu lottery -----------------------------------------------------------------
# Per explicit request: 2 more independent, uniform-random rolls (repeats allowed, same flat
# shape as the pill lottery above), each granting one random Epic-quality Gu family to a
# random participant.
TOURNAMENT_BONUS_EPIC_GU_ROLL_COUNT = 2


def roll_bonus_epic_gu_winners(participant_user_ids: list, rng: Optional[random.Random] = None) -> list:
    """TOURNAMENT_BONUS_EPIC_GU_ROLL_COUNT independent, uniform-random draws -- repeats
    allowed, same flat lottery shape as roll_bonus_pill_winners. Each roll also independently
    picks a random Epic-quality Gu family from the full catalog (same family-quality filter
    GameManager._grant_tournament_placement_reward already uses for the guaranteed podium Gu).
    Returns [(user_id, gu_family), ...one entry per roll], or [] if there were no
    participants."""
    if not participant_user_ids:
        return []
    r = rng or random
    epic_families = [family for family, data in equipment.GU_FAMILIES.items() if "Epic" in data["qualities"]]
    return [
        (r.choice(participant_user_ids), r.choice(epic_families))
        for _ in range(TOURNAMENT_BONUS_EPIC_GU_ROLL_COUNT)
    ]


# -- Bonus Nascent Soul avatar gear chance ------------------------------------------------------
# Per explicit request: ONE roll, not guaranteed ("chance to spawn"), checked once for the whole
# tournament rather than per-player -- if it hits, one random participant with their avatar
# actually unlocked (picked by the caller, since unlock status lives in GameManager/DB, not
# here) gets a bonus avatar gear piece. source_tier is deliberately LOWER than every podium
# reward's own avatar_gear_source_tier (5/4/3 for 1st/2nd/3rd) -- "chance to spawn high tier is
# lower", per explicit request -- so this bonus skews toward Formed/Tempered rather than
# competing with what winning the tournament outright already grants.
TOURNAMENT_BONUS_AVATAR_GEAR_CHANCE = 0.40
TOURNAMENT_BONUS_AVATAR_GEAR_SOURCE_TIER = 2


def roll_bonus_avatar_gear_chance(rng: Optional[random.Random] = None) -> bool:
    r = rng or random
    return r.random() < TOURNAMENT_BONUS_AVATAR_GEAR_CHANCE
