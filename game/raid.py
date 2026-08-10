"""
/raid: a boss encounter multiple players can join, styled after a Pokemon-doubles/trio
battle. The enemy side is a main boss plus two mini-bosses (see monsters.BOSS_GROUPS).
Every living participant AND every living enemy acts once per round, but the round only
resolves once every alive, joined participant has locked in an action — so it plays out
as simultaneous turns (choose your move blind, then everyone's move executes together)
rather than the old one-at-a-time exchange. Each round, a player picks which enemy to
Attack/use their Gu ability on, and independently which enemy to specifically Guard
against (reducing only that enemy's hit on them this round) — letting a coordinated party
focus fire while splitting up incoming damage.

Design decisions worth flagging:
- hunt.py's Observe didn't carry over: with no hidden info to reveal each round, "let the
  enemies hit you and do nothing else" wasn't worth a row of scarce button budget here.
- Loot is still independent per participant on total victory (every enemy in the group
  dead) — same 50-100 stones + the main boss's drop table, rolled once per participant,
  scaled by that participant's reward multiplier (see the AFK policy below).
- The potion select can't be filtered to "what the current viewer owns" since Discord
  renders one shared component list for everyone on the message; it lists every usable
  Healing/Pills item, and ownership/quantity is checked when a click actually happens.
- Rounds are on a fixed 30s clock (ROUND_TIMEOUT_SECONDS), not "30s since the last
  action" — it starts the moment a round begins collecting actions. Anyone still alive
  and undecided when it expires is auto-submitted a plain Attack on the main boss, and
  loses another 25% of their reward multiplier (AFK_LOOT_PENALTY), floored at 0% — it
  does NOT recover just by acting again afterward, so going AFK has a lasting cost.
  Staleness is tracked with an epoch counter rather than cancelling the pending asyncio
  timer task directly, since the timeout's own coroutine is sometimes the one starting
  the next round's timer — cancelling "yourself" mid-callback is asyncio-legal but is an
  easy way to accidentally interrupt your own cleanup code, so it's avoided entirely.
"""

import asyncio
import dataclasses
import random
import time

import discord

from . import avatar, avatar_gear, canon_gu, chargen, combat, dao_paths
from .base_view import GameView
from .character_class import CLASS_EMOJI
from .equipment import EQUIPMENT
from .items import ITEMS, roll_essence_restoration_pill_drop
from .monsters import BOSS_GROUPS, roll_loot
from .ui_utils import render_bar

GUARD_DAMAGE_REDUCTION = 0.5
EMPOWER_QI_COST = 15
POTION_USE_CAP = 3
RAID_SPIRIT_STONE_MIN = 50
RAID_SPIRIT_STONE_MAX = 100
# Nascent Soul Avatar gear's raid drop source (see game/avatar_gear.py) — briefly bumped to
# 0.40 alongside a general raid boss loot increase, then scaled back to its original rate
# once that generosity moved over to World Boss instead (see world_boss.py).
RAID_AVATAR_GEAR_CHANCE = 0.08
MAX_LOG_LINES = 8

ROUND_TIMEOUT_SECONDS = 30
AFK_LOOT_PENALTY = 0.25

# A one-time window right when the raid opens, before round 1's own action-collection clock
# starts — gives stragglers a chance to Join before anyone's first move locks in. Shown to
# players via Discord's own <t:...:R> relative timestamp markup (ticks down live in their
# client with zero bot-side polling/edits needed) rather than repeatedly editing the message.
RAID_JOIN_COUNTDOWN_SECONDS = 30

FLEE_BASE_CHANCE = 0.5
FLEE_CHANCE_PER_SPD_DIFF = 0.02
MIN_FLEE_CHANCE = 0.1
MAX_FLEE_CHANCE = 0.9

# Class Ability (see character_class.py / RaidView._on_class_ability) — one raid-only
# ability per class, dispatched off the clicking player's character_class:
#   Tank's Defend Ally        -> redirects an ally's incoming hits onto the Tank this round.
#   Support's Inspire         -> buffs the whole party's STR/DEF for a few rounds.
#   Frostbinder's Freeze      -> a weaker attack with a chance to skip the target's next hit.
DEFEND_ALLY_DAMAGE_REDUCTION = 0.25  # on top of the Tank's own passive +DEF/+HP
INSPIRE_STR_BONUS_PCT = 0.15
INSPIRE_DEF_BONUS_PCT = 0.15
INSPIRE_DURATION_ROUNDS = 3  # includes the round Inspire is cast in
FREEZE_STR_MULTIPLIER = 0.8
FREEZE_PROC_CHANCE = 0.5

# Main-boss-only telegraphed special attack (self.enemies[0] only — minis never charge one).
# The boss spends CHARGE_DURATION_ROUNDS rounds channeling instead of attacking normally,
# aimed at one randomly-chosen participant (announced immediately and kept visible in the
# embed every round it's charging), then unleashes a guaranteed-hit nuke at
# CHARGE_ATTACK_MULTIPLIER times its own ability's usual damage. combat.py's DEF reduction
# is flat, not a percentage (DEF_REDUCTION_PER_POINT), so raw stat gaps barely matter at
# these damage levels — the only real counters are the target's own Empowered ("full block")
# Guard (fully negates it, same as any other fully-blocked hit) or a Tank's Defend Ally
# redirecting it onto themselves (survivable, but a real chunk of the Tank's own HP — see
# _release_boss_charge/_resolve_enemy_hit, the same reduction pipeline every normal enemy
# attack already goes through). CHARGE_COOLDOWN_ROUNDS of normal attacks follow each release
# before the boss can start charging again; freezing the boss (Frostbinder) also pauses an
# in-progress charge, since a frozen enemy's whole turn — charge tick included — is skipped.
CHARGE_DURATION_ROUNDS = 3
CHARGE_COOLDOWN_ROUNDS = 3
CHARGE_FIRST_DELAY_ROUNDS = 1
CHARGE_ATTACK_MULTIPLIER = 3.5

STATUS_LABELS = {
    "starting": "Starting Soon", "fighting": "In Progress", "victory": "Victory!",
    "wiped": "Party Wiped", "abandoned": "Abandoned",
}
STATUS_COLORS = {
    "starting": discord.Color.blurple(),
    "fighting": discord.Color.dark_gold(),
    "victory": discord.Color.green(),
    "wiped": discord.Color.dark_red(),
    "abandoned": discord.Color.greyple(),
}


class RaidEnemy:
    def __init__(self, monster):
        self.monster = monster
        self.hp = monster.hp
        self.max_hp = monster.hp
        self.frozen_rounds = 0  # Frostbinder's Freeze — >0 means this enemy skips its next attack
        # Fire Dao Path burn (see dao_paths.fire_burn_tick_damage) -- seeded on a landed hit
        # from ANY Fire-path participant, ticks once per round in _resolve_round regardless of
        # whose turn queued the round.
        self.burn_damage_per_tick = 0
        self.burn_ticks_remaining = 0
        # Blazing Glory Sunfire Physique -- an independent second burn source, same "refreshes,
        # doesn't stack" shape as Fire Dao Path's above, ticked alongside it in Phase 1.5.
        self.sunfire_burn_damage_per_tick = 0
        self.sunfire_burn_ticks_remaining = 0

    @property
    def alive(self) -> bool:
        return self.hp > 0

    def stats(self) -> dict:
        return self.monster.stats()


class RaidView(GameView):
    def __init__(self, game, boss_name: str, stat_multiplier: float = 1.0):
        super().__init__(timeout=1800)  # long safety net — raids are meant to run for a while
        self.game = game
        self.raid_name = boss_name
        # world_regions.py's Northern Plains "more powerful monsters" passive, decided once
        # by whoever started the raid (see cog.py's /raid) since the enemy group is one
        # shared HP pool for the whole party — a scaled COPY of each boss/mini-boss, never
        # mutating the shared BOSS_GROUPS catalog instances.
        group = BOSS_GROUPS[boss_name]
        if stat_multiplier != 1.0:
            group = [
                dataclasses.replace(
                    m, hp=max(1, round(m.hp * stat_multiplier)), atk_stat=max(1, round(m.atk_stat * stat_multiplier)),
                    str_stat=max(1, round(m.str_stat * stat_multiplier)), def_stat=max(1, round(m.def_stat * stat_multiplier)),
                    spd_stat=max(1, round(m.spd_stat * stat_multiplier)),
                )
                for m in group
            ]
        self.enemies = [RaidEnemy(m) for m in group]
        self.loot_table = group[0]  # the main boss's drop table pays out the raid
        self.participants: dict = {}  # user_id -> participant dict
        self.actions: dict = {}  # user_id -> queued action for the round currently being collected
        self.round = 1
        self.status = "starting"
        self.starts_at = int(time.time()) + RAID_JOIN_COUNTDOWN_SECONDS
        self.log: list = []
        self.result_loot: dict = {}
        self.stones_awarded: dict = {}
        self.message: discord.Message = None
        self._round_epoch = 0  # bumped each time a round's timer (re)starts, to detect stale timeouts
        self.inspire_rounds_remaining = 0  # Support's Inspire — see _attacker_stats
        # Main boss's telegraphed charge special (see CHARGE_DURATION_ROUNDS above) —
        # charge_target_id is the participant it's aimed at (None if not currently charging).
        self.charge_target_id = None
        self.charge_rounds_remaining = 0
        self.charge_cooldown_remaining = CHARGE_FIRST_DELAY_ROUNDS
        self._build_components()
        asyncio.create_task(self._start_countdown())

    # This view is shared by everyone in the raid, not owned by a single user — no
    # interaction_check restriction; eligibility is enforced per-action instead.

    # -- helpers -----------------------------------------------------------

    def _alive_enemies(self):
        return [e for e in self.enemies if e.alive]

    def _alive_participant_ids(self):
        return [uid for uid, p in self.participants.items() if not p["down"]]

    def _persist_hp(self, user_id: int, p: dict):
        """Writes p["hp"] back to the DB — minus hp_bonus, since the stored hp/max_hp columns
        stay gear-independent (db.set_hp's own clamp is against the un-bonused max_hp, so
        persisting the inflated number would just get silently cut back down)."""
        self.game.db.set_hp(user_id, max(1, p["hp"] - p.get("hp_bonus", 0)))

    def _persist_qi(self, user_id: int, p: dict):
        """Writes p["qi"] back to the DB — minus qi_bonus, mirroring _persist_hp
        (db.set_battle_qi's own clamp is against the un-bonused qi_stat column, so
        persisting the inflated number would just get silently cut back down)."""
        self.game.db.set_battle_qi(user_id, max(0.0, p["qi"] - p.get("qi_bonus", 0)))

    def _try_negate_fatal_hit(self, user_id: int, p: dict) -> bool:
        """Mythic Physique's "ignore the first fatal hit each day" — True (and consumes the
        day's charge) only for a Mythic-physique participant who hasn't already used it today."""
        if p.get("physique_tier") != "Mythic":
            return False
        return self.game.db.try_use_daily_fatal_hit_negation(user_id)

    def _try_avatar_fatal_block(self, user_id: int, p: dict) -> bool:
        """Nascent Soul Avatar's own once-daily fatal-blow shield — independent of Mythic
        Physique's charge above (a participant with both gets two separate saves), gated
        only on having chosen an avatar soul at all, not on level or which soul."""
        if not p.get("avatar_soul"):
            return False
        return self.game.db.try_use_daily_avatar_fatal_block(user_id)

    def _soul_projection_bonuses(self, user_id: int, p: dict) -> dict:
        """Extra amounts Soul Projection adds on top of the passive while active this round
        for THIS participant — empty when inactive or no soul chosen. Keyed the same as
        compute_equipment_bonuses' special dict for the keys the attack/defense resolve_attack
        calls read; Formation Soul's flat STR/DEF and Demon Soul's low_hp_atk_bonus are
        consumed directly in _attacker_stats instead."""
        if p.get("soul_projection_rounds_remaining", 0) <= 0:
            return {}
        soul_name = p.get("avatar_soul")
        soul = avatar.get_avatar_soul(soul_name)
        if soul is None:
            return {}
        multiplier = self.game.soul_projection_multiplier(user_id)
        return {
            key: avatar.soul_projection_bonus(soul_name, p.get("avatar_level", 1), key, multiplier)
            for key in avatar.SOUL_PROJECTION_KEYS.get(soul.name, ())
        }

    def _log(self, text: str):
        self.log.append(text)
        self.log = self.log[-MAX_LOG_LINES:]

    def _clear_active_raid_for_all(self):
        """Called from every terminal-status transition (victory/wiped/abandoned/timeout) so
        GameManager.has_active_raid lets every joined participant start or join a new raid
        again -- see cog.py's raid command / _on_join's own gate. Bulk, not per-user, since a
        raid is a shared encounter and everyone's flag needs releasing together."""
        self.game.db.clear_active_raid_bulk(list(self.participants.keys()))

    def _equipped_gu(self, user_id: int):
        gu_name = self.game.get_equipped(user_id).get("gu_ability")
        return EQUIPMENT.get(gu_name) if gu_name else None

    def _trait_bonus(self, p: dict, key: str) -> float:
        """A participant's named root AND named physique own stat_bonuses value for `key`
        (see character_data.CharacterTraitSpec), summed — mirrors hunt.py's identical helper,
        just reading off the participant dict instead of self."""
        root_spec = chargen.get_root_spec(p.get("root_name"))
        physique_spec = chargen.get_physique_spec(p.get("physique_name"))
        root_value = root_spec.stat_bonuses.get(key, 0) if root_spec else 0
        physique_value = physique_spec.stat_bonuses.get(key, 0) if physique_spec else 0
        return root_value + physique_value

    def _attacker_stats(self, user_id: int, p: dict) -> tuple:
        """Returns (stats, bonuses, soul_projection_bonuses) — the third element is computed
        here (needed for the flat-stat fold-in below) and handed back so callers don't have
        to re-derive it (soul_projection_multiplier does real DB reads)."""
        bonuses = self.game.compute_equipment_bonuses(user_id)
        stats_bonus = bonuses["stats"]
        player = self.game.get_player_stats(user_id, p["name"])
        stats = {
            "atk_stat": player["atk_stat"] + stats_bonus["atk_stat"],
            "str_stat": player["str_stat"] + stats_bonus["str_stat"],
            "def_stat": player["def_stat"] + stats_bonus["def_stat"],
            "spd_stat": player["spd_stat"] + stats_bonus["spd_stat"],
            "luck_stat": player["luck_stat"] + stats_bonus["luck_stat"],
        }
        if self.inspire_rounds_remaining > 0:
            stats["str_stat"] = round(stats["str_stat"] * (1 + INSPIRE_STR_BONUS_PCT))
            stats["def_stat"] = round(stats["def_stat"] * (1 + INSPIRE_DEF_BONUS_PCT))
        # Formation Soul's REAL passive (see avatar.py) -- every OTHER alive same-sect
        # participant with Formation Soul buffs THIS participant's STR/DEF, always on (no
        # Soul Projection needed). Pure in-memory scan against each participant's own cached
        # sect_id/avatar_soul (see _on_join), no DB calls. Never buffs the Formation Soul
        # holder themselves this way -- "sect members fighting ALONGSIDE you," matching the
        # soul's own passive_text.
        sect_id = p.get("sect_id")
        if sect_id:
            for other_id, other in self.participants.items():
                if other_id == user_id or other.get("down") or other.get("sect_id") != sect_id:
                    continue
                if other.get("avatar_soul") != "Formation Soul":
                    continue
                str_bonus = avatar.scaled_bonus(other["avatar_soul"], other.get("avatar_level", 1), "sect_buff_str_pct")
                def_bonus = avatar.scaled_bonus(other["avatar_soul"], other.get("avatar_level", 1), "sect_buff_def_pct")
                if str_bonus:
                    stats["str_stat"] = round(stats["str_stat"] * (1 + str_bonus))
                if def_bonus:
                    stats["def_stat"] = round(stats["def_stat"] * (1 + def_bonus))
        # Heavenly Solar Physique -- every OTHER alive participant (no sect gate, unlike
        # Formation Soul above -- "every friendly character" per explicit request) with this
        # physique buffs THIS participant's DEF, always on. Same self-exclusion as Formation
        # Soul: the holder buffs allies fighting alongside them, not themselves this way.
        for other_id, other in self.participants.items():
            if other_id == user_id or other.get("down"):
                continue
            def_aura_pct = chargen.get_physique_spec(other.get("physique_name"))
            def_aura_pct = def_aura_pct.stat_bonuses.get("ally_def_aura_pct", 0) if def_aura_pct else 0
            if def_aura_pct:
                stats["def_stat"] = round(stats["def_stat"] * (1 + def_aura_pct))
        # Soul Projection (see avatar.py): Formation Soul's ACTIVE version buffs the caster's
        # own STR/DEF (their ally-targeted passive is the scan just above); Demon Soul's
        # amplified low_hp_atk_bonus folds into the SAME below-50%-HP-gated flat bonus the
        # passive version already uses, just below, rather than a separate ungated add.
        sp = self._soul_projection_bonuses(user_id, p)
        if sp.get("sect_buff_str_pct"):
            stats["str_stat"] = round(stats["str_stat"] * (1 + sp["sect_buff_str_pct"]))
        if sp.get("sect_buff_def_pct"):
            stats["def_stat"] = round(stats["def_stat"] * (1 + sp["sect_buff_def_pct"]))
        low_hp_bonus = bonuses.get("low_hp_atk_bonus", 0) + sp.get("low_hp_atk_bonus", 0)
        if low_hp_bonus and 0 < p["hp"] < p["max_hp"] * 0.5:
            stats["str_stat"] += low_hp_bonus
        # Phoenix Feather-family physique: the same "below 50% HP" threshold, but a % bonus.
        low_hp_str_pct = self.game._trait_bonus(player, "low_hp_str_pct_bonus")
        if low_hp_str_pct and 0 < p["hp"] < p["max_hp"] * 0.5:
            stats["str_stat"] = round(stats["str_stat"] * (1 + low_hp_str_pct))
        # Clear Mind-family physique's encounter-start adaptive stat (see _on_join).
        adaptive_key = p.get("adaptive_stat_key")
        if adaptive_key:
            stats[adaptive_key] = round(stats[adaptive_key] * (1 + self.game._trait_bonus(player, "encounter_start_adaptive_stat_pct")))
        return stats, bonuses, sp

    def _resolve_target_index(self, p: dict) -> int:
        """The enemy index a player's next action should hit — their preferred target if
        it's still alive, otherwise the first alive enemy. -1 if nothing's left standing."""
        alive = self._alive_enemies()
        if not alive:
            return -1
        idx = p.get("target_index", 0)
        if idx >= len(self.enemies) or not self.enemies[idx].alive:
            idx = self.enemies.index(alive[0])
        return idx

    def _validate_actor(self, user_id: int):
        """Returns (participant, error_message_or_None)."""
        if self.status == "starting":
            return None, f"The raid hasn't started yet — it begins <t:{self.starts_at}:R>."
        if self.status != "fighting":
            return None, "This raid has already ended."
        p = self.participants.get(user_id)
        if p is None:
            return None, "Join the raid before acting!"
        if p["down"]:
            return None, "You've been knocked out and can't act for the rest of this raid."
        if user_id in self.actions:
            return None, "You've already locked in your action for this round — wait for it to resolve."
        return p, None

    async def _submit_action(self, user_id: int, action: dict):
        self.actions[user_id] = action
        if self._alive_participant_ids() and set(self._alive_participant_ids()).issubset(self.actions.keys()):
            await self._finish_round()
        else:
            await asyncio.to_thread(self._build_components)
            await self._refresh_message()

    async def _refresh_message(self):
        if self.message is not None:
            try:
                embed = await asyncio.to_thread(self.build_embed)
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass

    def _apply_afk_actions(self):
        """Auto-submits a plain Attack on the main boss for anyone who didn't act before
        the round's clock ran out, and docks their reward multiplier for it."""
        for user_id in self._alive_participant_ids():
            if user_id in self.actions:
                continue
            p = self.participants[user_id]
            p["loot_multiplier"] = max(0.0, p["loot_multiplier"] - AFK_LOOT_PENALTY)
            self.actions[user_id] = {"type": "attack", "target": 0, "guaranteed": False}
            self._log(f"⏱️ **{p['name']}** ran out of time and auto-attacks {self.enemies[0].monster.name}! (reward chance now {p['loot_multiplier'] * 100:.0f}%)")

    async def _start_countdown(self):
        """The one-time RAID_JOIN_COUNTDOWN_SECONDS join window — runs once, right when the
        view is created, independent of the (possibly-not-yet-started) per-round timer."""
        await asyncio.sleep(RAID_JOIN_COUNTDOWN_SECONDS)
        if self.status != "starting":
            return  # already moved on some other way (e.g. Start Now, or the whole view timing out)
        # _begin_fight_or_abandon can call _start_round_timer -> asyncio.create_task, which
        # requires a running loop in the CURRENT thread -- stays un-wrapped, on the main
        # thread, same reasoning as hunt.py/pvp_view.py/battlefield_view.py's identical
        # _finish_round split. It's pure in-memory state either way, no DB calls.
        self._begin_fight_or_abandon()
        await asyncio.to_thread(self._build_components)
        await self._refresh_message()

    def _begin_fight_or_abandon(self):
        """Ends the "starting" join window early or on schedule — shared by the countdown
        timeout above and the Start Now button, so both go through the exact same
        participants-check/transition logic."""
        if self.participants:
            self.status = "fighting"
            self._start_round_timer()
        else:
            self.status = "abandoned"
            self._log("😶 No one joined in time — the raid disperses.")

    def _start_round_timer(self):
        self._round_epoch += 1
        asyncio.create_task(self._round_timeout(self._round_epoch))

    async def _round_timeout(self, epoch: int):
        await asyncio.sleep(ROUND_TIMEOUT_SECONDS)
        if self.status != "fighting" or epoch != self._round_epoch:
            return  # the round already resolved on its own (or the raid ended) before this fired
        self._apply_afk_actions()  # pure in-memory state, no DB calls
        await self._finish_round()

    async def _finish_round(self):
        await asyncio.to_thread(self._resolve_round)
        await asyncio.to_thread(self._build_components)
        await self._refresh_message()
        # _start_round_timer's asyncio.create_task requires a running loop in the CURRENT
        # thread -- must run here, on the main thread, not inside either to_thread call above.
        if self.status == "fighting" and self.participants:
            self._start_round_timer()

    # -- round resolution ---------------------------------------------------

    def _resolve_round(self):
        # Phase 0: Support's Inspire — resolved before damage so this round's own attacks
        # already benefit. Doesn't stack in magnitude (multiple Supports just refresh the
        # same duration), and costs the caster their attack that round.
        for user_id, action in self.actions.items():
            if action["type"] != "inspire":
                continue
            p = self.participants.get(user_id)
            if p is None or p["down"]:
                continue
            self.inspire_rounds_remaining = INSPIRE_DURATION_ROUNDS
            self._log(f"✨ **{p['name']}** inspires the party — STR and DEF surge!")

        # Phase 0.5: Soul Projection (see avatar.py) — same "resolve before damage so this
        # round's own attacks already benefit" placement as Inspire above, but PER-
        # PARTICIPANT (unlike Inspire's single shared flag) since souls differ per player.
        for user_id, action in self.actions.items():
            if action["type"] != "soul_projection":
                continue
            p = self.participants.get(user_id)
            if p is None or p["down"]:
                continue
            soul = avatar.get_avatar_soul(p.get("avatar_soul"))
            if soul is None:
                continue
            p["soul_projection_rounds_remaining"] = avatar.soul_projection_duration(soul)
            self._log(f"🌀 **{p['name']}** channels {avatar.SOUL_PROJECTION_NAME} — {soul.name}'s power surges through them!")

        # Phase 1: player attacks / Gu abilities / Freeze / Soul Projection / damage-kind
        # Killer Moves, in submission order.
        for user_id, action in list(self.actions.items()):
            p = self.participants.get(user_id)
            if p is None or p["down"] or action["type"] not in ("attack", "gu", "freeze", "soul_projection", "killer_move"):
                continue
            alive = self._alive_enemies()
            if not alive:
                break
            target_idx = action["target"]
            if target_idx < 0 or target_idx >= len(self.enemies) or not self.enemies[target_idx].alive:
                target = alive[0]
            else:
                target = self.enemies[target_idx]

            attacker_stats, bonuses, sp = self._attacker_stats(user_id, p)
            is_gu = action["type"] == "gu"
            is_freeze = action["type"] == "freeze"
            is_soul_projection = action["type"] == "soul_projection"
            is_killer_move = action["type"] == "killer_move"
            if is_gu:
                str_multiplier = action["ability"].str_multiplier
                label = action["ability"].name
            elif is_freeze:
                str_multiplier = FREEZE_STR_MULTIPLIER
                label = "Freeze"
            elif is_soul_projection:
                # Struck with the buff this SAME action just activated (Phase 0.5 already
                # set p["soul_projection_rounds_remaining"] above, so _attacker_stats' own sp
                # read here already reflects it) -- not a toggle-then-attack like Empower,
                # the projection itself IS the attack.
                str_multiplier = 1.0
                label = avatar.SOUL_PROJECTION_NAME
            elif is_killer_move:
                str_multiplier = action["move"]["effects"]["str_multiplier"]
                label = action["move"]["name"]
            else:
                str_multiplier = 1.0
                label = "Attack"
            # Gu abilities / Freeze / Soul Projection / Killer Moves count as "technique"
            # damage; a plain Attack is "physical" — see manual_view.EFFECT_LABELS'
            # technique_damage_pct/physical_damage_pct.
            base_damage_pct_bonus = (bonuses.get("technique_damage_pct", 0) if (is_gu or is_freeze or is_soul_projection or is_killer_move) else bonuses.get("physical_damage_pct", 0)) + bonuses.get("total_damage_pct", 0)
            # A Lightning-family root's empower_damage_pct (only on an actually-Empowered
            # attack) and a Fire-family root's battle-Qi trigger (consumed on whichever
            # attack comes next, hit or miss — see _track_battle_qi_spent) — mirrors hunt.py's
            # identical _do_attack handling.
            root_spec = chargen.get_root_spec(p.get("root_name"))
            if action.get("guaranteed"):
                base_damage_pct_bonus += self._trait_bonus(p, "empower_damage_pct")
            if p.get("fire_str_pending"):
                base_damage_pct_bonus += root_spec.fire_battle_qi_str_bonus_pct
                p["fire_str_pending"] = False
            # Swift Foot-family physique's Momentum (consumed on whichever basic Attack comes
            # next, hit or miss) and Strong Bone-family physique's every-3rd-basic-Attack
            # bonus — both "basic Attack" only, mirrors hunt.py's identical _do_attack.
            lunar_armor_pen = 0.0
            if label == "Attack":
                if p.get("dodge_momentum_pending"):
                    base_damage_pct_bonus += self._trait_bonus(p, "dodge_momentum_str_bonus_pct")
                    p["dodge_momentum_pending"] = False
                p["attack_count"] = p.get("attack_count", 0) + 1
                if p["attack_count"] % 3 == 0:
                    base_damage_pct_bonus += self._trait_bonus(p, "every_third_attack_bonus_pct")
                # Heavenly Solar/Lunar Physique -- both read the stack count BEFORE this
                # attack (grown by prior landed basic Attacks), same "read old count,
                # increment after a landed hit" order Iron Skin's own guard_stacks uses.
                # Per-player dict entry (not an instance attribute) since raid tracks several
                # participants at once -- mirrors guard_stacks/attack_count's own p.get(...) idiom.
                base_damage_pct_bonus += self._trait_bonus(p, "solar_stack_damage_pct") * p.get("solar_stacks", 0)
                lunar_armor_pen = self._trait_bonus(p, "lunar_stack_armor_pen_pct") * p.get("lunar_stacks", 0)
            # Heavenly Lunar Physique -- basic Attacks hit EVERY alive enemy instead of just
            # the chosen one, per explicit request. Snapshotted once per action so a kill
            # mid-volley doesn't retroactively shrink who else gets hit; each target still
            # gets its own independent hit/dodge/crit roll and damage number below (a real
            # AOE cleave, not one roll copied to every enemy).
            if label == "Attack" and self._trait_bonus(p, "lunar_aoe_attacks"):
                attack_targets = list(alive)
            else:
                attack_targets = [target]
            any_hit_landed = False
            for target in attack_targets:
                if not target.alive:
                    continue
                damage_pct_bonus = base_damage_pct_bonus
                # A Strength-family root's beast_damage_pct only applies against Beast-type
                # enemies — the offensive counterpart to Gu's existing beast_damage_reduction_pct.
                if target.monster.monster_type == "Beast":
                    damage_pct_bonus += self._trait_bonus(p, "beast_damage_pct")
                # Demon Soul's execute_damage_pct (passive + Soul Projection's amplified delta)
                # only applies once the target's already below half HP, mirroring hunt.py's
                # identical caller-side pattern.
                if target.hp > 0 and target.hp < target.max_hp * 0.5:
                    damage_pct_bonus += bonuses.get("execute_damage_pct", 0) + sp.get("execute_damage_pct", 0)
                result = combat.resolve_attack(
                    attacker_stats, target.stats(), str_multiplier=str_multiplier,
                    guaranteed_hit=action.get("guaranteed", False),
                    crit_chance_bonus=bonuses.get("crit_chance_pct", 0) + sp.get("crit_chance_pct", 0),
                    crit_damage_bonus=bonuses.get("crit_damage_pct", 0) + sp.get("crit_damage_pct", 0),
                    lifesteal_percent=bonuses.get("lifesteal_percent", 0) + sp.get("lifesteal_percent", 0),
                    damage_pct_bonus=damage_pct_bonus,
                    armor_penetration_pct=bonuses.get("armor_penetration_pct", 0) + sp.get("armor_penetration_pct", 0) + lunar_armor_pen,
                    max_dodge_chance=combat.MONSTER_MAX_DODGE_CHANCE,
                )
                if not result.hit:
                    self._log(f"❌ **{p['name']}** uses {label} on {target.monster.name} but misses!")
                    # Moonlight-family physique: the first Gu ability that misses each encounter
                    # refunds half its Qi cost — mirrors hunt.py's identical _on_gu_ability handling.
                    if is_gu and not p.get("gu_miss_refunded"):
                        refund_pct = self._trait_bonus(p, "gu_miss_qi_refund_pct")
                        if refund_pct:
                            p["gu_miss_refunded"] = True
                            refund = round(action["ability"].qi_cost * refund_pct)
                            if refund > 0:
                                p["qi"] = min(p["max_qi"], p["qi"] + refund)
                                self._persist_qi(user_id, p)
                                self._log(f"🌙 **{p['name']}**'s miss wasn't a total loss — {refund} Qi flows back.")
                elif result.dodged:
                    self._log(f"💨 {target.monster.name} dodges **{p['name']}**'s {label}!")
                else:
                    any_hit_landed = True
                    target.hp = max(0, target.hp - result.damage)
                    # Paradise Earth Inheritor Root's Merit needs to know who DIDN'T deal the
                    # most damage this raid — see _on_victory.
                    p["damage_dealt"] = p.get("damage_dealt", 0) + result.damage
                    crit = " (Critical!)" if result.crit else ""
                    heal_text = ""
                    if result.heal:
                        p["hp"] = min(p["max_hp"], p["hp"] + result.heal)
                        self._persist_hp(user_id, p)
                        heal_text = f" 💚 +{result.heal} HP"
                    self._log(f"⚔️ **{p['name']}** hits {target.monster.name} for {result.damage} damage{crit}.{heal_text}")
                    # Fire Dao Path: refreshes (doesn't stack) on every landed hit from ANY
                    # Fire-path participant -- see the Phase 1.5 tick loop below for where this
                    # actually deals damage, once per round.
                    fire_burn_pct = bonuses.get("fire_burn_damage_pct", 0)
                    if fire_burn_pct > 0 and target.hp > 0:
                        tick_damage = dao_paths.fire_burn_tick_damage(result.damage, fire_burn_pct)
                        if tick_damage > 0:
                            target.burn_damage_per_tick = tick_damage
                            target.burn_ticks_remaining = dao_paths.FIRE_BURN_TICKS
                            self._log(f"🔥 **{p['name']}**'s flames catch hold of {target.monster.name}!")
                    # Blazing Glory Sunfire Physique: same "refreshes, doesn't stack" shape as Fire
                    # Dao Path's burn above, but sized off the target's max HP rather than this
                    # hit's damage -- a separate, independently-ticking burn source (Phase 1.5).
                    sunfire_pct = self._trait_bonus(p, "sunfire_burn_max_hp_pct")
                    if sunfire_pct > 0 and target.hp > 0:
                        total_burn = round(target.max_hp * sunfire_pct)
                        tick_damage = max(1, round(total_burn / dao_paths.FIRE_BURN_TICKS))
                        target.sunfire_burn_damage_per_tick = tick_damage
                        target.sunfire_burn_ticks_remaining = dao_paths.FIRE_BURN_TICKS
                        self._log(f"☀️ **{p['name']}**'s sunfire catches hold of {target.monster.name}!")
                    if target.hp <= 0:
                        self._log(f"💥 {target.monster.name} is defeated!")
                        if target is self.enemies[0] and self.charge_target_id is not None:
                            self.charge_target_id = None
                            self._log(f"⚡ {target.monster.name}'s charging attack collapses along with it!")
                        # Phoenix Feather-family physique: "defeating an enemy restores battle
                        # Qi" -- fires once per kill even within one AOE volley (each defeat is
                        # its own event), unlike the stack growth below which is once per action.
                        kill_qi_restore_pct = self._trait_bonus(p, "kill_qi_restore_pct")
                        if kill_qi_restore_pct:
                            restored = round(p["max_qi"] * kill_qi_restore_pct)
                            if restored > 0:
                                p["qi"] = min(p["max_qi"], p["qi"] + restored)
                                self._persist_qi(user_id, p)
                                self._log(f"🔥 **{p['name']}**'s kill rekindles {restored} battle Qi.")
                    elif is_freeze and random.random() < FREEZE_PROC_CHANCE:
                        target.frozen_rounds = max(target.frozen_rounds, 1)
                        self._log(f"❄️ {target.monster.name} is frozen solid and will miss its next attack!")
            # Heavenly Solar/Lunar Physique stack growth -- ONCE per action if at least one
            # target was hit, never once per target, so a Lunar Physique AOE swing that lands
            # on several enemies at once doesn't grow stacks several times faster than a
            # normal single-target attacker.
            if label == "Attack" and any_hit_landed:
                p["solar_stacks"] = min(5, p.get("solar_stacks", 0) + 1)
                p["lunar_stacks"] = min(5, p.get("lunar_stacks", 0) + 1)

        # Phase 1.5: Fire Dao Path burn ticks -- once per round, for every enemy with an
        # active burn (seeded by a landed hit somewhere in Phase 1 above), independent of
        # whose turn queued this round's actions. Can finish an enemy off on its own, same as
        # any other damage source.
        for enemy in self.enemies:
            if enemy.burn_ticks_remaining <= 0 or not enemy.alive:
                continue
            burn_damage = min(enemy.hp, enemy.burn_damage_per_tick)
            enemy.hp -= burn_damage
            enemy.burn_ticks_remaining -= 1
            self._log(f"🔥 {enemy.monster.name} burns for {burn_damage} damage!")
            if enemy.hp <= 0:
                self._log(f"💥 {enemy.monster.name} is defeated!")
                if enemy is self.enemies[0] and self.charge_target_id is not None:
                    self.charge_target_id = None
                    self._log(f"⚡ {enemy.monster.name}'s charging attack collapses along with it!")

        # Phase 1.6: Blazing Glory Sunfire Physique burn ticks -- same shape as Phase 1.5
        # above, just a separate, independently-ticking damage pool.
        for enemy in self.enemies:
            if enemy.sunfire_burn_ticks_remaining <= 0 or not enemy.alive:
                continue
            burn_damage = min(enemy.hp, enemy.sunfire_burn_damage_per_tick)
            enemy.hp -= burn_damage
            enemy.sunfire_burn_ticks_remaining -= 1
            self._log(f"☀️ {enemy.monster.name} burns in sunfire for {burn_damage} damage!")
            if enemy.hp <= 0:
                self._log(f"💥 {enemy.monster.name} is defeated!")
                if enemy is self.enemies[0] and self.charge_target_id is not None:
                    self.charge_target_id = None
                    self._log(f"⚡ {enemy.monster.name}'s charging attack collapses along with it!")

        # Phase 2: flee attempts — chance is based on the party's speed vs. the average of
        # whatever enemies are still standing.
        alive_enemies = self._alive_enemies()
        avg_enemy_spd = (sum(e.monster.spd_stat for e in alive_enemies) / len(alive_enemies)) if alive_enemies else 6
        left_ids = []
        for user_id, action in self.actions.items():
            if action["type"] != "flee":
                continue
            p = self.participants.get(user_id)
            if p is None or p["down"]:
                continue
            attacker_stats, _, _ = self._attacker_stats(user_id, p)
            chance = FLEE_BASE_CHANCE + (attacker_stats["spd_stat"] - avg_enemy_spd) * FLEE_CHANCE_PER_SPD_DIFF
            chance += self._trait_bonus(p, "flee_chance_flat")
            chance = max(MIN_FLEE_CHANCE, min(MAX_FLEE_CHANCE, chance))
            fled = random.random() < chance
            # Void-family physique: once per encounter, a failed flee gets one immediate
            # reroll at the same chance — mirrors hunt.py's identical _on_flee handling.
            if not fled and not p.get("flee_reroll_used") and self._trait_bonus(p, "flee_reroll_once"):
                p["flee_reroll_used"] = True
                fled = random.random() < chance
                if fled:
                    self._log(f"🌀 **{p['name']}**'s physique bends space for a second chance!")
            if fled:
                self._log(f"🏃 **{p['name']}** breaks away and flees the raid!")
                left_ids.append(user_id)
            else:
                self._log(f"❌ **{p['name']}** fails to escape!")
        for user_id in left_ids:
            del self.participants[user_id]
            self.actions.pop(user_id, None)
        if left_ids:
            # A fleeing participant leaves the raid's own participants dict here, but the
            # whole-raid terminal states (_on_victory/_on_wipe/on_timeout) never fire for
            # them specifically -- without this, their active_raid_started_ts flag stayed set
            # until GameManager.ACTIVE_RAID_STALE_SECONDS self-healed it (up to 2h), even
            # though they'd successfully left and had nothing left to finish.
            self.game.db.clear_active_raid_bulk(left_ids)

        if not self._alive_enemies():
            self._on_victory()
            self.actions.clear()
            return

        # Phase 3: enemy attacks — every living enemy hits a random alive, still-present
        # player; a Guard only reduces damage from the specific enemy it targeted. A Tank's
        # Defend Ally fully redirects whatever would've hit their chosen ally onto the Tank
        # instead (last Defend on a given ally wins if more than one Tank picks them).
        defend_map = {}  # defended_user_id -> defender_user_id
        for uid, action in self.actions.items():
            if action["type"] != "defend_ally":
                continue
            defender = self.participants.get(uid)
            if defender and not defender["down"]:
                defend_map[action["defended"]] = uid

        for idx, enemy in enumerate(self.enemies):
            if not enemy.alive:
                continue
            if enemy.frozen_rounds > 0:
                enemy.frozen_rounds -= 1
                self._log(f"🥶 {enemy.monster.name} is frozen and can't attack this round!")
                continue
            alive_ids = self._alive_participant_ids()
            if not alive_ids:
                break
            if idx == 0 and self._handle_boss_charge(enemy, alive_ids, defend_map):
                continue  # this round's "turn" was spent charging/releasing the special, not a normal attack
            target_id = random.choice(alive_ids)
            self._resolve_enemy_hit(enemy, idx, target_id, defend_map, enemy.monster.ability.str_multiplier)

        self.actions.clear()
        self.round += 1
        if self.inspire_rounds_remaining > 0:
            self.inspire_rounds_remaining -= 1
        # Soul Projection is per-participant (unlike Inspire's single shared flag), so this
        # is a loop rather than one decrement.
        for p in self.participants.values():
            if p.get("soul_projection_rounds_remaining", 0) > 0:
                p["soul_projection_rounds_remaining"] -= 1
        if self.participants and all(p["down"] for p in self.participants.values()):
            self._on_wipe()

    def _resolve_enemy_hit(self, enemy: "RaidEnemy", idx: int, target_id: int, defend_map: dict, str_multiplier: float, guaranteed_hit: bool = False, label: str = None):
        """Resolves one enemy attack against target_id — after any Tank Defend Ally
        redirect, Guard reduction, beast-resistance, and race/physique reduction — shared by
        both a normal enemy attack and the main boss's own charged special (see
        _release_boss_charge), so the two go through the exact same mitigation pipeline."""
        alive_ids = self._alive_participant_ids()
        redirected_from = None
        if target_id in defend_map and defend_map[target_id] in alive_ids and defend_map[target_id] != target_id:
            redirected_from = target_id
            target_id = defend_map[target_id]
        p = self.participants[target_id]
        ability_label = label or enemy.monster.ability.name
        if redirected_from is not None:
            self._log(f"🛡️ **{p['name']}** steps in to defend **{self.participants[redirected_from]['name']}** from {enemy.monster.name}'s {ability_label}!")

        action = self.actions.get(target_id)
        guard_reduction = DEFEND_ALLY_DAMAGE_REDUCTION if redirected_from is not None else 0.0
        if action and action["type"] == "guard" and action["target"] == idx:
            guard_reduction = max(guard_reduction, 1.0 if action.get("full_block") else GUARD_DAMAGE_REDUCTION)

        bonuses = self.game.compute_equipment_bonuses(target_id)
        beast_reduction = bonuses.get("beast_damage_reduction_pct", 0) if enemy.monster.monster_type == "Beast" else 0
        total_reduction = 1 - (1 - guard_reduction) * (1 - beast_reduction)
        # Rockman's "-15% dmg above 50% HP" and Rare Physique's small flat reduction.
        race_physique_reduction = chargen.race_physique_damage_reduction(
            p.get("race"), p.get("physique_tier"), p["hp"] / p["max_hp"],
        )
        if race_physique_reduction:
            total_reduction = 1 - (1 - total_reduction) * (1 - race_physique_reduction)
        # Iron Skin-family physique's Guard stacks (permanent for the rest of the encounter)
        # and Stone Muscle-family physique's high-HP damage reduction — mirrors hunt.py's
        # identical _monster_turn handling.
        guard_stack_reduction = self._trait_bonus(p, "guard_stack_def_pct") * p.get("guard_stacks", 0)
        if guard_stack_reduction:
            total_reduction = 1 - (1 - total_reduction) * (1 - guard_stack_reduction)
        if p["hp"] > p["max_hp"] * 0.6:
            high_hp_reduction = self._trait_bonus(p, "high_hp_damage_reduction_pct")
            if high_hp_reduction:
                total_reduction = 1 - (1 - total_reduction) * (1 - high_hp_reduction)
        if total_reduction >= 1.0:
            self._log(f"🛡️ **{p['name']}** fully blocks {enemy.monster.name}'s {ability_label}!")
            return

        # Frost Soul's Soul Projection amplifies dodge/ignore-attack specifically on THIS
        # (incoming-attack) call — never a player's own Phase 1 attack, which doesn't read
        # either kwarg at all.
        attacker_stats, _, sp = self._attacker_stats(target_id, p)
        result = combat.resolve_attack(
            enemy.stats(), attacker_stats, str_multiplier=str_multiplier, incoming_reduction=total_reduction,
            guaranteed_hit=guaranteed_hit, ignore_chance=bonuses.get("ignore_attack_chance", 0) + sp.get("ignore_attack_chance", 0),
            dodge_chance_bonus=bonuses.get("dodge_chance_pct", 0) + sp.get("dodge_chance_pct", 0),
        )
        if not result.hit:
            self._log(f"❌ {enemy.monster.name} attacks **{p['name']}** but misses!")
        elif result.dodged:
            self._log(f"💨 **{p['name']}** dodges {enemy.monster.name}'s {ability_label}!")
            # Swift Foot-family physique's Momentum — only the FIRST dodge each encounter
            # arms the bonus (consumed in Phase 1's attack handling above).
            if not p.get("dodge_momentum_triggered") and self._trait_bonus(p, "dodge_momentum_str_bonus_pct"):
                p["dodge_momentum_pending"] = True
                p["dodge_momentum_triggered"] = True
        elif result.ignored:
            self._log(f"🛡️ **{p['name']}**'s Gu shrugs off {enemy.monster.name}'s attack entirely!")
        elif p["hp"] - result.damage <= 0 and (self._try_negate_fatal_hit(target_id, p) or self._try_avatar_fatal_block(target_id, p)):
            self._log(f"✨ {enemy.monster.name}'s {ability_label} should have killed **{p['name']}** — their body refuses to fall!")
        else:
            p["hp"] = max(0, p["hp"] - result.damage)
            self._persist_hp(target_id, p)
            crit = " (Critical!)" if result.crit else ""
            self._log(f"🩸 {enemy.monster.name} hits **{p['name']}** for {result.damage} damage{crit} with {ability_label}." if label else f"🩸 {enemy.monster.name} hits **{p['name']}** for {result.damage} damage{crit}.")
            if p["hp"] <= 0:
                p["down"] = True
                self.game.db.set_hp(target_id, 1)
                ward_name = self.game.check_and_consume_defeat_ward(target_id)
                if ward_name:
                    self._log(f"✨ **{ward_name}** activates for **{p['name']}** — knocked out, but the Qi loss is warded away!")
                elif self.game.check_and_consume_worldly_escape(target_id):
                    self._log(f"✨ **Worldly Escape Gu** activates for **{p['name']}** — knocked out, but the Qi loss is escaped entirely!")
                else:
                    # Consolidated single read of the generic pool (root/physique/Gu/avatar
                    # soul/avatar gear all fold in there now — see
                    # GameManager.compute_equipment_bonuses) instead of separate manual reads
                    # per source, which would double-count once this key also lives in
                    # SPECIAL_BONUS_KEYS.
                    reduction = bonuses.get("death_qi_loss_reduction_pct", 0)
                    qi_lost, _ = self.game.db.apply_death_penalty(target_id, reduction_pct=reduction)
                    self._log(f"💀 **{p['name']}** is knocked out, losing {qi_lost:,.2f} qi!")
            # Immovable Mountain Physique: surviving a landed hit reflects a portion of the
            # damage taken straight back at the attacker -- guaranteed (no separate hit/dodge/
            # crit roll of its own), mirrors hunt.py's identical _monster_turn handling. A
            # retaliation kill here is left for the next round's own Phase 2 alive-enemies
            # check to notice, same precedent Phase 1.5's own burn-tick kills already set.
            if p["hp"] > 0 and enemy.hp > 0:
                retaliation_pct = self._trait_bonus(p, "retaliation_damage_pct")
                if retaliation_pct > 0:
                    retaliation_damage = max(1, round(result.damage * retaliation_pct))
                    enemy.hp = max(0, enemy.hp - retaliation_damage)
                    self._log(f"🪨 **{p['name']}** retaliates for {retaliation_damage} damage!")
                    if enemy.hp <= 0:
                        self._log(f"💥 {enemy.monster.name} is defeated!")
                        if enemy is self.enemies[0] and self.charge_target_id is not None:
                            self.charge_target_id = None
                            self._log(f"⚡ {enemy.monster.name}'s charging attack collapses along with it!")

    def _handle_boss_charge(self, boss: "RaidEnemy", alive_ids: list, defend_map: dict) -> bool:
        """Main-boss-only telegraphed special (see CHARGE_DURATION_ROUNDS above). Returns
        True if the boss's turn this round was spent charging or releasing it (no normal
        attack happens that round), False if it should just attack normally instead."""
        if self.charge_target_id is not None:
            self._tick_or_release_boss_charge(boss, alive_ids, defend_map)
            return True
        if self.charge_cooldown_remaining > 0:
            self.charge_cooldown_remaining -= 1
            return False
        self._start_boss_charge(boss, alive_ids)
        return True

    def _start_boss_charge(self, boss: "RaidEnemy", alive_ids: list):
        target_id = random.choice(alive_ids)
        self.charge_target_id = target_id
        # This round IS the first of the CHARGE_DURATION_ROUNDS the boss spends channeling
        # (it doesn't attack normally this round either — see _handle_boss_charge), so only
        # CHARGE_DURATION_ROUNDS - 1 more ticks are needed before _tick_or_release_boss_charge
        # releases it — otherwise the charge would silently take one round longer than
        # CHARGE_DURATION_ROUNDS actually promises.
        self.charge_rounds_remaining = CHARGE_DURATION_ROUNDS - 1
        target_name = self.participants[target_id]["name"]
        self._log(
            f"⚡ {boss.monster.name} begins channeling a devastating attack at **{target_name}**! "
            f"It lands in {self.charge_rounds_remaining} more round(s) — an Empowered Guard from "
            f"{target_name} or a Tank's Defend Ally is the real counter."
        )

    def _tick_or_release_boss_charge(self, boss: "RaidEnemy", alive_ids: list, defend_map: dict):
        self.charge_rounds_remaining -= 1
        if self.charge_rounds_remaining > 0:
            target = self.participants.get(self.charge_target_id)
            target_name = target["name"] if target and self.charge_target_id in alive_ids else "its original target"
            self._log(f"⚡ {boss.monster.name}'s charge builds toward **{target_name}** — {self.charge_rounds_remaining} round(s) left!")
            return
        self._release_boss_charge(boss, alive_ids, defend_map)

    def _release_boss_charge(self, boss: "RaidEnemy", alive_ids: list, defend_map: dict):
        target_id = self.charge_target_id
        self.charge_target_id = None
        self.charge_cooldown_remaining = CHARGE_COOLDOWN_ROUNDS
        if target_id not in alive_ids:
            target_id = random.choice(alive_ids)
            self._log(f"⚡ {boss.monster.name}'s original target is gone — the charged attack lashes out at **{self.participants[target_id]['name']}** instead!")
        self._log(f"💥 {boss.monster.name} unleashes its fully-charged attack!")
        self._resolve_enemy_hit(
            boss, 0, target_id, defend_map,
            str_multiplier=boss.monster.ability.str_multiplier * CHARGE_ATTACK_MULTIPLIER,
            guaranteed_hit=True, label=f"{boss.monster.ability.name} (Overcharged)",
        )

    # -- A few Unique roots' own bespoke mechanics, all resolved once per raid victory ------
    # (see character_data.py's Unique section for each root's full description).
    SOUL_FRAGMENTS_PER_BOSS = 8
    SOUL_FRAGMENTS_WEEKLY_CAP = 40  # -> at most 40 bonus insight dust/week from this source
    MERIT_PER_NON_TOP_DAMAGE = 1
    MERIT_WEEKLY_CAP = 5
    MERIT_HEAL_PCT = 0.10
    CONNECT_LUCK_MIN_PARTY = 3
    CONNECT_LUCK_STONE_BONUS_PCT = 0.10
    THIEVING_HEAVEN_MATERIAL_TIER_RANGE = (1, 3)

    def _on_victory(self):
        self.status = "victory"
        self._clear_active_raid_for_all()
        boss_gu_rank = self.enemies[0].monster.gu_rank
        # Paradise Earth Inheritor Root's Merit needs to know who DIDN'T deal the most damage
        # — computed once, before the per-participant loop below, off the running totals Phase
        # 1 built up in p["damage_dealt"] all raid.
        top_damage_id = max(self.participants, key=lambda uid: self.participants[uid].get("damage_dealt", 0), default=None)
        for user_id, p in self.participants.items():
            multiplier = p.get("loot_multiplier", 1.0) * (1 + p.get("region_loot_chance_bonus_pct", 0.0))
            root_spec = chargen.get_root_spec(p.get("root_name"))
            beast_qty_bonus = self._trait_bonus(p, "beast_material_quantity_bonus_pct")
            loot = roll_loot(self.loot_table, chance_multiplier=multiplier, beast_material_quantity_bonus_pct=beast_qty_bonus)

            bonuses = self.game.compute_equipment_bonuses(user_id)
            effective_luck = self.game.get_player_stats(user_id, p["name"])["luck_stat"] + bonuses["stats"]["luck_stat"]
            canon_drop = canon_gu.roll_canon_gu_drop(
                boss_gu_rank, "world_boss", luck_bonus=min(0.05, effective_luck * 0.001), chance_multiplier=multiplier,
            )
            if canon_drop:
                loot[canon_drop] = loot.get(canon_drop, 0) + 1

            # Thieving Heaven Inheritor Root's Otherworldly Theft — once daily, one extra
            # roll from a plain tiered-material pool. By construction this never touches Gu,
            # canon, or Unique-catalog items, so it can never duplicate/steal a Unique/event/
            # first-clear reward — the guardrail is satisfied by the pool itself, not a filter.
            if root_spec and root_spec.name == "Thieving Heaven Inheritor Root" and self.game.db.try_use_unique_daily_charge(user_id):
                tier = random.randint(*self.THIEVING_HEAVEN_MATERIAL_TIER_RANGE)
                stolen_item = f"Tier {tier} Beast Material"
                loot[stolen_item] = loot.get(stolen_item, 0) + 1
                self._log(f"🕵️ **{p['name']}**'s Otherworldly Theft snatches an extra **{stolen_item}**!")

            # Essence Restoration Pill: rare bonus roll for every raid victor (see items.
            # roll_essence_restoration_pill_drop's own docstring for why this moved here
            # instead of the Alchemist craft table). quantity is usually 1, occasionally more.
            essence_pill = roll_essence_restoration_pill_drop()
            if essence_pill:
                pill_name, pill_qty = essence_pill
                loot[pill_name] = loot.get(pill_name, 0) + pill_qty
                self._log(f"💧 **{p['name']}** finds {pill_qty}x rare **{pill_name}**!")

            for item_name, quantity in loot.items():
                self.game.db.add_item(user_id, item_name, quantity)

            stone_bonus = 1.0 + bonuses.get("stone_reward_bonus_pct", 0)
            # Giant Sun Inheritor Root's Connect Luck — a real group of 3+ raiders (not just
            # this player alone) earns everyone holding the root a small stone bonus.
            if root_spec and root_spec.name == "Giant Sun Inheritor Root" and len(self.participants) >= self.CONNECT_LUCK_MIN_PARTY:
                stone_bonus += self.CONNECT_LUCK_STONE_BONUS_PCT
            stones = round(random.randint(RAID_SPIRIT_STONE_MIN, RAID_SPIRIT_STONE_MAX) * multiplier * stone_bonus)
            self.game.db.add_spirit_stones(user_id, stones)
            self.result_loot[user_id] = loot
            self.stones_awarded[user_id] = stones
            # Spirit Severing Dao Marks (see GameManager.grant_dao_marks) -- silently a no-op
            # for anyone who hasn't reached Spirit Severing yet.
            self.game.grant_dao_marks(user_id)

            # Spectral Soul Inheritor Root's Soul Devouring — Soul Fragments from a boss kill
            # (never a player kill — this is only ever reached via a raid BOSS's own defeat),
            # capped weekly, auto-converted into bonus Insight Dust rather than needing a
            # separate spend command.
            if root_spec and root_spec.name == "Spectral Soul Inheritor Root":
                before = self.game.db.peek_unique_weekly_resource(user_id)
                after = self.game.db.add_unique_weekly_resource(user_id, self.SOUL_FRAGMENTS_PER_BOSS, self.SOUL_FRAGMENTS_WEEKLY_CAP)
                gained_dust = after - before
                if gained_dust > 0:
                    granted = self.game._grant_insight_dust(user_id, gained_dust)
                    self._log(f"👻 **{p['name']}**'s Soul Devouring converts fallen essence into +{granted} Insight Dust!")

            # Paradise Earth Inheritor Root's Merit — helping win without dealing the most
            # damage, capped weekly, auto-spent on bonus healing.
            if root_spec and root_spec.name == "Paradise Earth Inheritor Root" and user_id != top_damage_id:
                before = self.game.db.peek_unique_weekly_resource(user_id)
                after = self.game.db.add_unique_weekly_resource(user_id, self.MERIT_PER_NON_TOP_DAMAGE, self.MERIT_WEEKLY_CAP)
                if after > before:
                    healed, hp, max_hp = self.game.db.heal_percent(user_id, self.MERIT_HEAL_PCT)
                    if healed > 0:
                        self._log(f"🌾 **{p['name']}** earns Merit for their part in the raid — +{healed} HP.")

            hoard_reward = p.get("region_hoard_reward")
            if hoard_reward:
                hoard_text = self.game.grant_reward(user_id, p["name"], hoard_reward)
                self._log(f"🏆 **{p['name']}**'s share of the hoard ({p.get('region_hoard_label', 'a hoard')}): {hoard_text}!")

            granted = self.game.roll_and_grant_accessory_artifact(user_id, p["name"], "raid_boss", boss_gu_rank, [])
            if granted:
                self._log(f"✨ **{p['name']}** also finds **{granted['affix'].name}**!")

            # Nascent Soul Avatar gear (see game/avatar_gear.py) — raids are this system's
            # "rarely" source, gated on the avatar being unlocked at all. boss_gu_rank
            # already equals realm_index+1 (see monsters.py), so subtracting 3 recovers the
            # same realm_index-based source_tier the approved plan specifies, clamped to a
            # minimum of 1 for an overqualified avatar-unlocked player raiding a low-realm boss.
            if self.game.is_avatar_unlocked(user_id, p["name"]) and random.random() < RAID_AVATAR_GEAR_CHANCE:
                gear_tier = max(1, min(avatar_gear.MAX_TIER - 1, boss_gu_rank - 3))
                gear_granted = self.game.roll_and_grant_avatar_gear(user_id, p["name"], "raid_boss", gear_tier)
                self._log(f"🔥 **{p['name']}**'s avatar also finds a **{avatar_gear.tier_name(gear_granted['tier'])} {gear_granted['slot_type']}**!")
        self._log(f"🎉 {self.raid_name}'s warband is defeated! Loot distributed to all {len(self.participants)} participants.")

    def _on_wipe(self):
        self.status = "wiped"
        self._clear_active_raid_for_all()
        self._log(f"💀 The entire party is knocked out. {self.raid_name}'s warband stands triumphant...")

    # -- action handlers -----------------------------------------------------

    def _add_participant(self, user_id: int, name: str, player: dict):
        """Builds and inserts one participant's full combat-state dict (equipment overlay,
        region modifiers, physique/root per-encounter state, etc.). Shared by _on_join (the
        Join button, mid-"starting"-window) and cog.py's /solo_raid (the caller is
        auto-joined immediately, no button click involved) — sync, callers dispatch via
        asyncio.to_thread themselves."""
        # Equipped gear's flat "hp"/"qi_stat" stat_bonuses are folded in as a live overlay
        # on top of the persisted (gear-independent) hp/max_hp and battle_qi/qi_stat
        # columns, same as atk/str/def/spd/luck already work — see _persist_hp/_persist_qi
        # for why writes back to the DB subtract them back out again.
        equip_bonuses = self.game.compute_equipment_bonuses(user_id)["stats"]
        hp_bonus = equip_bonuses["hp"]
        qi_bonus = equip_bonuses["qi_stat"]
        hp_settled = self.game.db.settle_hp_regen(user_id)
        # Sturdy Frame-family physique's battle_qi_regen_bonus_pct — same rate-multiplier
        # hunt.py's own settle_battle_qi call applies.
        regen_bonus = self.game._trait_bonus(player, "battle_qi_regen_bonus_pct")
        qi_settled = self.game.db.settle_battle_qi(user_id, regen_rate_bonus_pct=regen_bonus)
        alive = self._alive_enemies()
        default_target = self.enemies.index(alive[0]) if alive else 0
        # Each joiner rolls their OWN world_region loot/hoard bonus independently (unlike
        # the shared stat_multiplier decided once at raid creation) — spirit stones/
        # materials/pages are already granted per-participant at _on_victory, so this fits
        # that same per-participant shape rather than needing a group-wide roll.
        region_mods = self.game.region_encounter_modifiers(user_id, name)
        self.participants[user_id] = {
            "name": name, "hp": hp_settled["hp"] + hp_bonus, "max_hp": hp_settled["max_hp"] + hp_bonus, "down": False,
            "qi": qi_settled["battle_qi"] + qi_bonus, "max_qi": qi_settled["qi_stat"] + qi_bonus, "empowered": False,
            "target_index": default_target, "potions_used": 0, "loot_multiplier": 1.0,
            "character_class": player["character_class"], "hp_bonus": hp_bonus, "qi_bonus": qi_bonus,
            "race": player["race"], "physique_tier": player["physique_tier"],
            "region_loot_chance_bonus_pct": region_mods["loot_chance_bonus_pct"],
            "region_hoard_label": region_mods["hoard_label"], "region_hoard_reward": region_mods["hoard_reward"],
            # A Fire-family root's "spend 30% of your battle Qi this encounter" trigger
            # (see character_data.CharacterTraitSpec / hunt.py's identical
            # _track_battle_qi_spent) — tracked per-participant since a raid has several
            # people spending Qi at once.
            "root_name": player["root_name"], "qi_spent": 0.0, "fire_str_pending": False, "fire_triggered": False,
            # Common-tier physique combat state (see character_data.py's Common physique
            # section / hunt.py's identical per-participant fields) — also per-participant.
            "physique_name": player["physique_name"], "guard_stacks": 0,
            "dodge_momentum_pending": False, "dodge_momentum_triggered": False, "attack_count": 0,
            "first_gu_use_discounted": False, "guard_or_potion_qi_restored": False,
            "damage_dealt": 0.0, "adaptive_stat_key": None,
            # Uncommon/Rare-tier physique combat state (see character_data.py for the families).
            "first_empower_discounted": False, "flee_reroll_used": False, "gu_miss_refunded": False,
            # Nascent Soul Avatar (see avatar.py) — avatar_soul/avatar_level needed for both
            # Soul Projection and the passive fold-in inside _attacker_stats; sect_id for
            # Formation Soul's real ally-targeted raid buff (pure in-memory scan against
            # every other participant's own cached sect_id, no per-round DB calls).
            "avatar_soul": player["avatar_soul"], "avatar_level": player["avatar_level"], "sect_id": player["sect_id"],
            "soul_projection_rounds_remaining": 0,
        }
        # Clear Mind-family physique's encounter-start adaptive stat — compared against the
        # main boss specifically (self.enemies[0]) as "the opponent", same one-time-at-join
        # computation hunt.py's own single-monster version uses.
        physique_spec = chargen.get_physique_spec(player["physique_name"])
        if physique_spec and physique_spec.stat_bonuses.get("encounter_start_adaptive_stat_pct"):
            boss = self.enemies[0].monster
            ratios = {
                "atk_stat": player["atk_stat"] / max(1, boss.atk_stat),
                "def_stat": player["def_stat"] / max(1, boss.def_stat),
                "spd_stat": player["spd_stat"] / max(1, boss.spd_stat),
            }
            self.participants[user_id]["adaptive_stat_key"] = min(ratios, key=ratios.get)
        self.game.apply_encounter_start_bonuses(user_id, name)
        self.game.start_active_raid(user_id)
        self._log(f"🙋 **{name}** joins the raid!")

    async def _on_join(self, interaction: discord.Interaction):
        user = interaction.user
        # Joining is only open during the "starting" countdown window -- once the raid has
        # actually begun (status "fighting"), late joins are refused entirely (per explicit
        # request; this used to allow joining mid-fight too). A distinct message for each
        # case so "you're too late, it already started" reads differently from "it's already
        # completely over."
        if self.status == "fighting":
            await interaction.response.send_message("This raid has already started — you can't join once it's underway.", ephemeral=True)
            return
        if self.status != "starting":
            await interaction.response.send_message("This raid has already ended.", ephemeral=True)
            return
        if user.id in self.participants:
            await interaction.response.send_message("You're already in this raid.", ephemeral=True)
            return
        player = await asyncio.to_thread(self.game.get_player_stats, user.id, user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message("You need to `/join` and confirm a character first.", ephemeral=True)
            return
        if self.game.has_active_raid(player):
            abandon_view = AbandonRaidView(user.id, self.game)
            await interaction.response.send_message("🐉 Finish your current raid first!", view=abandon_view, ephemeral=True)
            return

        await asyncio.to_thread(self._add_participant, user.id, user.display_name, player)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_start_now(self, interaction: discord.Interaction):
        if self.status != "starting":
            await interaction.response.send_message("This raid has already started.", ephemeral=True)
            return
        if interaction.user.id not in self.participants:
            await interaction.response.send_message("Join the raid before starting it!", ephemeral=True)
            return
        self._log(f"▶️ **{interaction.user.display_name}** starts the raid early!")
        # _begin_fight_or_abandon can call _start_round_timer -> asyncio.create_task, which
        # must run on the main thread -- see _start_countdown's identical comment. Pure
        # in-memory state, no DB calls.
        self._begin_fight_or_abandon()
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_target(self, interaction: discord.Interaction):
        p = self.participants.get(interaction.user.id)
        if p is None:
            await interaction.response.send_message("Join the raid first!", ephemeral=True)
            return
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 2)
        try:
            idx = int(select.values[0])
        except ValueError:
            await interaction.response.defer()
            return
        p["target_index"] = idx
        await interaction.response.send_message(f"🎯 Targeting **{self.enemies[idx].monster.name}** for your next Attack/Guard/Gu ability.", ephemeral=True)

    def _track_battle_qi_spent(self, p: dict, amount: float):
        """Mirrors hunt.py's _track_battle_qi_spent — see the participant dict's own comment
        (in _on_join) for why this state lives per-participant here instead of on self. Reads
        via .get() throughout (not p[...]) so a participant dict from anywhere that predates
        these keys just behaves as "no root, never triggers" instead of a hard KeyError."""
        root_spec = chargen.get_root_spec(p.get("root_name"))
        if not root_spec or p.get("fire_triggered") or not root_spec.fire_battle_qi_trigger_fraction:
            return
        p["qi_spent"] = p.get("qi_spent", 0.0) + amount
        max_qi = p.get("max_qi", 0)
        threshold = max_qi * root_spec.fire_battle_qi_trigger_fraction
        if max_qi > 0 and p["qi_spent"] >= threshold:
            p["fire_str_pending"] = True
            p["fire_triggered"] = True

    def _consume_empower_cost(self, user_id: int, p: dict) -> bool:
        """If Empower is toggled on and affordable, spends it and returns True — shared by
        _on_attack and _on_guard. Thunder Muscle-family physique's "first Empower each
        encounter costs 2 less battle Qi" is applied before the affordability check, same
        "can help you afford it" convention hunt.py's identical _consume_empower uses."""
        cost = EMPOWER_QI_COST
        discount_pending = not p.get("first_empower_discounted")
        if discount_pending:
            discount = self._trait_bonus(p, "first_empower_discount_flat")
            if discount:
                cost = max(0, cost - discount)
        empowered = p["empowered"] and p["qi"] >= cost
        if empowered:
            p["qi"] -= cost
            self._persist_qi(user_id, p)
            self._track_battle_qi_spent(p, cost)
            if discount_pending:
                p["first_empower_discounted"] = True
        return empowered

    async def _on_attack(self, interaction: discord.Interaction):
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        empowered = await asyncio.to_thread(self._consume_empower_cost, interaction.user.id, p)
        p["empowered"] = False
        # No separate "Action locked in" confirmation — the shared raid embed's participant
        # list already shows "✅ locked in" per person once _submit_action runs, so a new
        # ephemeral message every single round was pure redundant spam over a multi-round raid.
        await interaction.response.defer()
        await self._submit_action(interaction.user.id, {"type": "attack", "target": self._resolve_target_index(p), "guaranteed": empowered})

    def _apply_guard_or_potion_qi_restore(self, user_id: int, p: dict):
        """River Walker-family physique's "Using Guard or a potion restores 3% of max battle
        Qi, once per encounter" — mirrors hunt.py's identical helper."""
        if p.get("guard_or_potion_qi_restored"):
            return
        restore_pct = self._trait_bonus(p, "guard_or_potion_qi_restore_pct")
        if not restore_pct:
            return
        p["guard_or_potion_qi_restored"] = True
        restored = round(p["max_qi"] * restore_pct)
        if restored > 0:
            p["qi"] = min(p["max_qi"], p["qi"] + restored)
            self._persist_qi(user_id, p)
            self._log(f"💧 **{p['name']}**'s physique restores {restored} battle Qi.")

    async def _on_guard(self, interaction: discord.Interaction):
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        empowered = await asyncio.to_thread(self._consume_empower_cost, interaction.user.id, p)
        p["empowered"] = False
        # Iron Skin-family physique's Guard stack (permanent for the rest of the encounter —
        # see _resolve_enemy_hit) and River Walker-family physique's Guard/potion Qi restore.
        p["guard_stacks"] = min(2, p.get("guard_stacks", 0) + 1)
        await asyncio.to_thread(self._apply_guard_or_potion_qi_restore, interaction.user.id, p)
        target_idx = self._resolve_target_index(p)
        await interaction.response.defer()
        await self._submit_action(interaction.user.id, {"type": "guard", "target": target_idx, "full_block": empowered})

    async def _on_flee(self, interaction: discord.Interaction):
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.defer()
        await self._submit_action(interaction.user.id, {"type": "flee"})

    async def _on_toggle_empower(self, interaction: discord.Interaction):
        p = self.participants.get(interaction.user.id)
        if p is None:
            await interaction.response.send_message("Join the raid first!", ephemeral=True)
            return
        if p["down"]:
            await interaction.response.send_message("You've been knocked out.", ephemeral=True)
            return
        if interaction.user.id in self.actions:
            await interaction.response.send_message("You've already locked in your action for this round.", ephemeral=True)
            return
        if not p["empowered"] and p["qi"] < EMPOWER_QI_COST:
            await interaction.response.send_message(f"Not enough battle Qi to Empower (needs {EMPOWER_QI_COST}).", ephemeral=True)
            return
        p["empowered"] = not p["empowered"]
        # No separate "Empower armed/cancelled" confirmation — same reasoning as _on_attack/
        # _on_guard's own removed confirmation: the shared raid embed's participant list now
        # shows "✨ empowered" per person (see build_embed) once armed, so a new ephemeral
        # message every toggle was pure redundant spam over a multi-round raid. Edits the
        # shared message directly (like _on_join/_on_start_now) rather than defer +
        # _refresh_message, since there's no async work in between that would need one.
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_gu_ability(self, interaction: discord.Interaction):
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        gu = await asyncio.to_thread(self._equipped_gu, interaction.user.id)
        ability = gu.active_ability if gu else None
        if not ability:
            await interaction.response.send_message("You have no active Gu ability equipped.", ephemeral=True)
            return
        # Sturdy Frame-family physique's "first Gu activation each encounter costs 1 less
        # Qi" — applied before the affordability check, mirrors hunt.py's identical handling.
        qi_cost = ability.qi_cost
        if not p.get("first_gu_use_discounted"):
            discount = self._trait_bonus(p, "first_gu_use_discount_flat")
            if discount:
                qi_cost = max(0, qi_cost - discount)
                p["first_gu_use_discounted"] = True
        if p["qi"] < qi_cost:
            await interaction.response.send_message(f"Not enough Qi to use {ability.name} (needs {qi_cost}).", ephemeral=True)
            return

        def _resolve():
            p["qi"] -= qi_cost
            self._persist_qi(interaction.user.id, p)
            self._track_battle_qi_spent(p, qi_cost)

        await asyncio.to_thread(_resolve)
        await interaction.response.defer()
        await self._submit_action(interaction.user.id, {"type": "gu", "target": self._resolve_target_index(p), "ability": ability})

    async def _on_killer_move(self, interaction: discord.Interaction):
        """Additive alongside _on_gu_ability above, not a replacement -- see hunt.py's
        identical twin for the full reasoning. A fresh DB read for the equipped move (not the
        cached participant dict `p`) mirrors _equipped_gu's own "always live" convention."""
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        player_row = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, p["name"])
        move = await asyncio.to_thread(self.game.get_equipped_killer_move, player_row, "combat")
        if not move:
            await interaction.response.send_message("You have no Killer Move equipped in your Combat slot.", ephemeral=True)
            return
        qi_cost = await asyncio.to_thread(self.game.killer_move_qi_cost, player_row, move)
        if p["qi"] < qi_cost:
            await interaction.response.send_message(f"Not enough Qi to use {move['name']} (needs {qi_cost:,}).", ephemeral=True)
            return
        p["qi"] -= qi_cost
        await asyncio.to_thread(self._persist_qi, interaction.user.id, p)
        await interaction.response.defer()
        if move["kind"] == "damage":
            await self._submit_action(interaction.user.id, {"type": "killer_move", "target": self._resolve_target_index(p), "move": move})
        else:
            # Buff-kind: applied immediately (no target/enemy resolution needed) -- the
            # queued action is just a placeholder so round-completion tracking still counts
            # this as this player's turn, same as Guard/Defend Ally's own non-attack actions.
            await asyncio.to_thread(self.game.apply_killer_move_buff, interaction.user.id, player_row, move)
            self._log(f"✨ **{p['name']}**'s {move['name']} surges through them!")
            await self._submit_action(interaction.user.id, {"type": "killer_move_buff"})

    async def _on_class_ability(self, interaction: discord.Interaction):
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        class_name = p.get("character_class")

        if class_name == "Tank":
            alive_allies = [(uid, ally) for uid, ally in self.participants.items() if not ally["down"] and uid != interaction.user.id]
            if not alive_allies:
                await interaction.response.send_message("There's no one else alive to defend.", ephemeral=True)
                return
            picker = _AllyPickerView(self, interaction.user.id, alive_allies)
            await interaction.response.send_message("Choose who to Defend this round:", view=picker, ephemeral=True)
            return

        if class_name == "Support":
            await interaction.response.defer()
            await self._submit_action(interaction.user.id, {"type": "inspire"})
            return

        if class_name == "Frostbinder":
            await interaction.response.defer()
            await self._submit_action(interaction.user.id, {"type": "freeze", "target": self._resolve_target_index(p)})
            return

        await interaction.response.send_message("You haven't chosen a class yet — run `/choose_class` to unlock a raid ability.", ephemeral=True)

    async def _on_soul_projection(self, interaction: discord.Interaction):
        """Independent of class -- gated on having chosen an avatar soul via /avatar instead.
        Qi is spent immediately (like Empower's own cost, see _consume_empower_cost) rather
        than at round-resolution time; the buff itself is applied in Phase 0.5 of
        _resolve_round, live before Phase 1 processes this SAME action as a real strike
        against the caster's current target (see Phase 1's `is_soul_projection` branch) --
        not just a buff-and-pass like Inspire."""
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        soul = avatar.get_avatar_soul(p.get("avatar_soul"))
        if soul is None:
            await interaction.response.send_message(
                "Your avatar hasn't chosen a soul yet — run `/avatar` to awaken it.", ephemeral=True,
            )
            return
        if p["qi"] < avatar.SOUL_PROJECTION_QI_COST:
            await interaction.response.send_message(
                f"Not enough battle Qi for Soul Projection (needs {avatar.SOUL_PROJECTION_QI_COST:,}).", ephemeral=True,
            )
            return
        p["qi"] -= avatar.SOUL_PROJECTION_QI_COST
        await asyncio.to_thread(self._persist_qi, interaction.user.id, p)
        await interaction.response.defer()
        await self._submit_action(interaction.user.id, {"type": "soul_projection", "target": self._resolve_target_index(p)})

    async def _use_defend_ally_for(self, interaction: discord.Interaction, defender_id: int, defended_id: int):
        p, error = self._validate_actor(defender_id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        defended = self.participants.get(defended_id)
        if defended is None or defended["down"]:
            await interaction.response.send_message("That ally can't be defended right now.", ephemeral=True)
            return
        await interaction.response.edit_message(content=f"🛡️ Defending **{defended['name']}** this round.", view=None)
        await self._submit_action(defender_id, {"type": "defend_ally", "defended": defended_id})

    async def _on_open_potion_menu(self, interaction: discord.Interaction):
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        if p["potions_used"] >= POTION_USE_CAP:
            await interaction.response.send_message(f"You've hit this raid's potion cap ({POTION_USE_CAP}).", ephemeral=True)
            return
        inventory = await asyncio.to_thread(self.game.get_inventory, interaction.user.id)
        usable = [
            item for item in ITEMS.values()
            if item.category in ("Healing", "Pills") and item.use is not None and inventory.get(item.name, 0) > 0
        ]
        if not usable:
            await interaction.response.send_message("You don't have any usable potions or pills.", ephemeral=True)
            return
        picker = _PotionPickerView(self, interaction.user.id, inventory, usable)
        await interaction.response.send_message("Pick a potion/pill to use:", view=picker, ephemeral=True)

    async def _use_potion_for(self, interaction: discord.Interaction, user_id: int, item_name: str):
        p, error = self._validate_actor(user_id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        if p["potions_used"] >= POTION_USE_CAP:
            await interaction.response.send_message(f"You've hit this raid's potion cap ({POTION_USE_CAP}).", ephemeral=True)
            return
        ok, message = await asyncio.to_thread(self.game.use_item, user_id, p["name"], item_name)
        if not ok:
            await interaction.response.send_message(message, ephemeral=True)
            return
        p["potions_used"] += 1
        fresh = await asyncio.to_thread(self.game.get_player_stats, user_id, p["name"])
        p["hp"] = min(p["max_hp"], fresh["hp"] + p.get("hp_bonus", 0))
        await asyncio.to_thread(self._apply_guard_or_potion_qi_restore, user_id, p)
        await interaction.response.send_message(f"🧪 Used **{item_name}** — {message}", ephemeral=True)
        await self._submit_action(user_id, {"type": "potion", "item_name": item_name})

    async def on_timeout(self):
        if self.status in ("starting", "fighting"):
            self.status = "abandoned"
            await asyncio.to_thread(self._clear_active_raid_for_all)
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                embed = await asyncio.to_thread(self.build_embed)
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass

    # -- UI building -----------------------------------------------------

    def _build_components(self):
        self.clear_items()
        active = self.status == "fighting"
        # Joining closes once the raid actually starts (see _on_join's own comment) -- the
        # button is removed entirely once fighting begins (not just disabled), so it's
        # UI-invisible rather than a dead greyed-out control to click on.
        can_join = self.status == "starting"

        if can_join:
            join_button = discord.ui.Button(label="Join Raid", emoji="🙋", style=discord.ButtonStyle.primary, row=0)
            join_button.callback = self._on_join
            self.add_item(join_button)

        if self.status == "starting":
            start_button = discord.ui.Button(
                label="Start Now", emoji="▶️", style=discord.ButtonStyle.success, row=0, disabled=not self.participants,
            )
            start_button.callback = self._on_start_now
            self.add_item(start_button)

        action_buttons = [
            ("Attack", "⚔️", discord.ButtonStyle.primary, self._on_attack),
            ("Guard", "🛡️", discord.ButtonStyle.secondary, self._on_guard),
            ("Flee", "🏃", discord.ButtonStyle.danger, self._on_flee),
        ]
        for label, emoji, style, callback in action_buttons:
            button = discord.ui.Button(label=label, emoji=emoji, style=style, row=1, disabled=not active)
            button.callback = callback
            self.add_item(button)

        empower_button = discord.ui.Button(label=f"Empower ({EMPOWER_QI_COST})", emoji="✨", style=discord.ButtonStyle.success, row=1, disabled=not active)
        empower_button.callback = self._on_toggle_empower
        self.add_item(empower_button)

        # Dispatches to Defend Ally/Inspire/Freeze based on the clicking player's own
        # character_class (see _on_class_ability) — one shared button since this view is
        # rendered identically for every participant regardless of their class.
        class_button = discord.ui.Button(label="Class Ability", emoji="🎭", style=discord.ButtonStyle.success, row=1, disabled=not active)
        class_button.callback = self._on_class_ability
        self.add_item(class_button)

        target_options = [
            discord.SelectOption(label=f"{e.monster.name} — {max(0, e.hp):.0f}/{e.max_hp:.0f} HP", value=str(idx), emoji="👑" if idx == 0 else "🐗")
            for idx, e in enumerate(self.enemies) if e.alive
        ]
        target_select = discord.ui.Select(
            placeholder="Choose your target (for Attack/Guard/Gu ability)..." if target_options else "No targets left",
            options=target_options or [discord.SelectOption(label="None", value="none")],
            disabled=not target_options or not active,
            row=2,
        )
        target_select.callback = self._on_pick_target
        self.add_item(target_select)

        gu_button = discord.ui.Button(label="Use Gu Ability", emoji="🐛", style=discord.ButtonStyle.primary, row=3, disabled=not active)
        gu_button.callback = self._on_gu_ability
        self.add_item(gu_button)

        # Additive alongside Use Gu Ability above, not a replacement -- like it, this view is
        # shared across every participant, so it can only gate on the shared `active` flag
        # here; the real equipped/affordability checks happen per-clicker inside
        # _on_killer_move itself, same convention Soul Projection's own button just below uses.
        killer_move_button = discord.ui.Button(label="Use Killer Move", emoji="🌀", style=discord.ButtonStyle.primary, row=3, disabled=not active)
        killer_move_button.callback = self._on_killer_move
        self.add_item(killer_move_button)

        # Nascent Soul Avatar's Soul Projection (see avatar.py) — like Empower/Class Ability
        # above, this view is rendered identically for every participant, so it can only gate
        # on the shared `active` flag here; the real soul-chosen/affordability checks happen
        # per-clicker inside _on_soul_projection itself.
        soul_projection_button = discord.ui.Button(
            label=f"Soul Projection ({avatar.SOUL_PROJECTION_QI_COST:,})", emoji="🌀",
            style=discord.ButtonStyle.success, row=3, disabled=not active,
        )
        soul_projection_button.callback = self._on_soul_projection
        self.add_item(soul_projection_button)

        # A per-player select (built fresh from just the clicking user's inventory) rather
        # than a shared one on this view — see _on_open_potion_menu. The full catalog of
        # usable Healing/Pills items (41 and counting, after the tiered Alchemy pills) blew
        # past Discord's 25-option cap on a Select, which silently 400'd this whole message
        # ("The application did not respond") every single time /raid was used.
        potion_button = discord.ui.Button(label="Use Potion/Pill", emoji="🧪", style=discord.ButtonStyle.success, row=3, disabled=not active)
        potion_button.callback = self._on_open_potion_menu
        self.add_item(potion_button)

    def build_embed(self) -> discord.Embed:
        if self.status == "starting":
            description = f"⏳ Raid begins <t:{self.starts_at}:R> — click **Join Raid** now to be in it from round 1!"
        else:
            description = (
                f"Round **{self.round}** — everyone locks in an action, then the round resolves at once "
                f"(or after {ROUND_TIMEOUT_SECONDS}s, whichever comes first)."
            )
        if self.inspire_rounds_remaining > 0:
            description += f"\n✨ **Inspire active** — party STR/DEF boosted ({self.inspire_rounds_remaining} round(s) left)."
        if self.charge_target_id is not None:
            charge_target = self.participants.get(self.charge_target_id)
            charge_target_name = charge_target["name"] if charge_target else "someone"
            description += (
                f"\n⚡ **{self.enemies[0].monster.name} is charging a devastating attack at {charge_target_name}!** "
                f"It lands in {self.charge_rounds_remaining} round(s) — an Empowered Guard from them or a Tank's "
                "Defend Ally is the real counter."
            )
        embed = discord.Embed(title=f"👑 {self.raid_name} Raid • {STATUS_LABELS[self.status]}", description=description, color=STATUS_COLORS[self.status])

        enemy_lines = []
        for idx, e in enumerate(self.enemies):
            icon = "👑" if idx == 0 else "🐗"
            if not e.alive:
                enemy_lines.append(f"{icon} **{e.monster.name}** — 💀 Defeated")
                continue
            frozen_note = " ❄️ *Frozen*" if e.frozen_rounds > 0 else ""
            pct = int(100 * max(0, e.hp) / e.max_hp)
            enemy_lines.append(
                f"{icon} **{e.monster.name}**{frozen_note} — {max(0, e.hp):.0f}/{e.max_hp:.0f} HP ({pct}%)\n`{render_bar(e.hp, e.max_hp)}`"
            )
        alive_count = sum(1 for e in self.enemies if e.alive)
        embed.add_field(name=f"⚔️ Enemies ({alive_count}/{len(self.enemies)} alive)", value="\n".join(enemy_lines)[:1024], inline=False)

        if self.participants:
            lines = []
            for uid, p in self.participants.items():
                class_emoji = CLASS_EMOJI.get(p.get("character_class"), "")
                pct = int(100 * max(0, p["hp"]) / p["max_hp"])
                if p["down"]:
                    status = "💀 knocked out"
                elif uid in self.actions:
                    status = "✅ locked in"
                else:
                    status = "⏳ choosing..."
                target_idx = self._resolve_target_index(p)
                target_name = self.enemies[target_idx].monster.name if target_idx >= 0 else "—"
                penalty_note = f" • 🔻 reward {p['loot_multiplier'] * 100:.0f}%" if p.get("loot_multiplier", 1.0) < 1.0 else ""
                charge_note = " • ⚡ **CHARGE TARGET**" if uid == self.charge_target_id else ""
                # Empower's only visible feedback now that its own toggle confirmation is gone
                # (see _on_toggle_empower) -- p["empowered"] is always False again by the time
                # status flips to "locked in" (consumed into the submitted action right away),
                # so this only ever shows while still "choosing", never alongside it.
                empower_note = " • ✨ Empowered" if p.get("empowered") else ""
                soul_projection_note = (
                    f" • 🌀 Soul Projection ({p['soul_projection_rounds_remaining']})"
                    if p.get("soul_projection_rounds_remaining", 0) > 0 else ""
                )
                lines.append(
                    f"{class_emoji}**{p['name']}** — {max(0, p['hp']):.0f}/{p['max_hp']:.0f} HP ({pct}%) • 🎯 {target_name} • {status}{empower_note}{soul_projection_note}{penalty_note}{charge_note}\n"
                    f"`{render_bar(p['hp'], p['max_hp'])}`"
                )
            embed.add_field(name=f"🧍 Participants ({len(self.participants)})", value="\n".join(lines)[:1024], inline=False)
        else:
            embed.add_field(name="🧍 Participants", value="No one has joined yet — click **Join Raid**!", inline=False)

        if self.log:
            embed.add_field(name="📜 Recent Combat", value="\n".join(self.log), inline=False)

        if self.status == "victory":
            loot_lines = []
            for uid, p in self.participants.items():
                loot = self.result_loot.get(uid, {})
                stones = self.stones_awarded.get(uid, 0)
                loot_text = ", ".join(f"{name} x{qty}" for name, qty in loot.items()) or "nothing else"
                loot_lines.append(f"**{p['name']}**: {stones} 🪙 + {loot_text}")
            embed.add_field(name="🎁 Loot (rolled per participant)", value="\n".join(loot_lines)[:1024], inline=False)
        elif self.status == "wiped":
            embed.add_field(name="💀 Outcome", value="The whole party was knocked out. No loot — regroup and try again.", inline=False)

        if self.status == "starting":
            footer_text = "Click Join Raid to be in it when the countdown ends — round 1 hasn't started yet."
        elif self.status == "fighting":
            footer_text = (
                "Pick a target, then Attack/Guard/use your Gu ability/Class Ability against it — actions are ephemeral. "
                f"AFK when the {ROUND_TIMEOUT_SECONDS}s clock runs out and you'll auto-attack the boss and lose 25% reward chance (down to 0%)."
            )
        else:
            footer_text = "This raid has ended."
        embed.set_footer(text=footer_text)
        return embed


class _PotionPickerView(GameView):
    """Ephemeral, per-player potion menu opened by RaidView's "Use Potion/Pill" button.
    Built fresh from just the clicking player's inventory, so it's naturally well under
    Discord's 25-option cap on a Select — unlike a select living directly on the shared
    raid message, which every participant sees and which would have to list every usable
    item in the whole game rather than just what one player actually owns."""

    def __init__(self, raid_view: RaidView, user_id: int, inventory: dict, usable: list):
        super().__init__(timeout=60)
        select = discord.ui.Select(
            placeholder="Use a potion/pill...",
            options=[
                discord.SelectOption(label=f"{item.name} x{inventory[item.name]}", value=item.name, description=item.description[:100])
                for item in usable[:25]
            ],
        )

        async def on_pick(interaction: discord.Interaction):
            await raid_view._use_potion_for(interaction, user_id, select.values[0])

        select.callback = on_pick
        self.add_item(select)


class _AllyPickerView(GameView):
    """Ephemeral menu opened by a Tank's "Class Ability" button (Defend Ally) — lets them
    pick which currently-alive ally to protect this round without needing a shared select
    living directly on the raid message (same reasoning as _PotionPickerView)."""

    def __init__(self, raid_view: RaidView, defender_id: int, alive_allies: list):
        super().__init__(timeout=60)
        select = discord.ui.Select(
            placeholder="Defend who?",
            options=[discord.SelectOption(label=ally["name"], value=str(uid)) for uid, ally in alive_allies],
        )

        async def on_pick(interaction: discord.Interaction):
            await raid_view._use_defend_ally_for(interaction, defender_id, int(select.values[0]))

        select.callback = on_pick
        self.add_item(select)


class AbandonRaidView(GameView):
    """Self-service escape hatch attached to the "finish your current raid first" refusal
    (see cog.py's /raid command and RaidView._on_join) -- a player's active_raid_started_ts
    flag has no dependency on any specific RaidView instance still existing, so if their
    original raid message scrolled away, got deleted, or the bot restarted before a terminal
    state could clear it for them, they'd otherwise be stuck until
    GameManager.ACTIVE_RAID_STALE_SECONDS (2h) self-heals it with no way to act sooner."""

    def __init__(self, user_id: int, game):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.game = game
        button = discord.ui.Button(label="Abandon Stuck Raid", emoji="🗑️", style=discord.ButtonStyle.danger)
        button.callback = self._on_abandon
        self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your raid slot to clear.", ephemeral=True)
            return False
        return True

    async def _on_abandon(self, interaction: discord.Interaction):
        await asyncio.to_thread(self.game.abandon_active_raid, self.user_id)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="🗑️ Cleared — you can `/raid` or join a new one now.", view=self)
