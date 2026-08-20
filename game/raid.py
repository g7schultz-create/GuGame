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
import os
import random
import time

import discord

from . import avatar, avatar_gear, canon_gu, chargen, dao_paths, white_heaven
from .equipment import parse_gu_name
from .base_view import GameView
from .character_class import CLASS_EMOJI
from .items import item_emoji, roll_essence_restoration_pill_drop
from .monsters import BOSS_GROUPS, roll_loot
from .team_battle import (
    DEFEND_ALLY_DAMAGE_REDUCTION,
    EMPOWER_QI_COST,
    FREEZE_PROC_CHANCE,
    FREEZE_STR_MULTIPLIER,
    GUARD_DAMAGE_REDUCTION,
    INSPIRE_DEF_BONUS_PCT,
    INSPIRE_DURATION_ROUNDS,
    INSPIRE_STR_BONUS_PCT,
    POTION_USE_CAP,
    AllyPickerView,
    PotionPickerView,
    RaidEnemy,
    TeamBattleEngine,
)
from .ui_utils import add_shuffled, format_number, render_bar

RAID_SPIRIT_STONE_MIN = 50
RAID_SPIRIT_STONE_MAX = 100
# Nascent Soul Avatar gear's raid drop source (see game/avatar_gear.py) — briefly bumped to
# 0.40 alongside a general raid boss loot increase, then scaled back to its original rate
# once that generosity moved over to World Boss instead (see world_boss.py).
RAID_AVATAR_GEAR_CHANCE = 0.08

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

# GUARD_DAMAGE_REDUCTION/EMPOWER_QI_COST/POTION_USE_CAP/DEFEND_ALLY_DAMAGE_REDUCTION/
# INSPIRE_*/FREEZE_* now live in team_battle.py (imported above) — shared with
# /inheritance_ground's battle bubbles via TeamBattleEngine, see that module's own docstring.

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


class RaidView(TeamBattleEngine, GameView):
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
    # _alive_enemies/_alive_participant_ids/_persist_hp/_persist_qi/_try_negate_fatal_hit/
    # _try_avatar_fatal_block/_soul_projection_bonuses/_log/_equipped_gu/_trait_bonus/
    # _attacker_stats/_resolve_target_index all now live on TeamBattleEngine (team_battle.py).

    def _clear_active_raid_for_all(self):
        """Called from every terminal-status transition (victory/wiped/abandoned/timeout) so
        GameManager.has_active_raid lets every joined participant start or join a new raid
        again -- see cog.py's raid command / _on_join's own gate. Bulk, not per-user, since a
        raid is a shared encounter and everyone's flag needs releasing together."""
        self.game.db.clear_active_raid_bulk(list(self.participants.keys()))

    def _validate_actor(self, user_id: int):
        """Raid's own status-machine checks, then delegates to TeamBattleEngine's shared
        not-joined/knocked-out/already-acted checks."""
        if self.status == "starting":
            return None, f"The raid hasn't started yet — it begins <t:{self.starts_at}:R>."
        if self.status != "fighting":
            return None, "This raid has already ended."
        return super()._validate_actor(user_id)

    # _submit_action/_refresh_message now live on TeamBattleEngine (team_battle.py).

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
    # _resolve_round/_resolve_enemy_hit now live on TeamBattleEngine (team_battle.py) --
    # only raid-specific hooks/overrides remain below.

    def _resolve_flee_phase(self):
        """Overrides TeamBattleEngine's no-op default -- chance is based on the party's
        speed vs. the average of whatever enemies are still standing."""
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

    def _on_enemy_defeated(self, enemy: "RaidEnemy"):
        """Overrides TeamBattleEngine's no-op default -- a defeated main boss (self.enemies[0])
        collapses any in-progress charge along with it."""
        if enemy is self.enemies[0] and self.charge_target_id is not None:
            self.charge_target_id = None
            self._log(f"⚡ {enemy.monster.name}'s charging attack collapses along with it!")

    def _maybe_handle_boss_charge(self, enemy: "RaidEnemy", idx: int, alive_ids: list, defend_map: dict) -> bool:
        """Main-boss-only (idx == 0 — minis never charge one) telegraphed special (see
        CHARGE_DURATION_ROUNDS above). Returns True if the boss's turn this round was spent
        charging or releasing it (no normal attack happens that round), False if it should
        just attack normally instead -- overrides TeamBattleEngine's no-op default."""
        if idx != 0:
            return False
        boss = enemy
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
        # (it doesn't attack normally this round either — see _maybe_handle_boss_charge), so
        # only CHARGE_DURATION_ROUNDS - 1 more ticks are needed before
        # _tick_or_release_boss_charge releases it — otherwise the charge would silently take
        # one round longer than CHARGE_DURATION_ROUNDS actually promises.
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
            # White Heaven's own 20 Rank 8 Unique Gu (see GameManager.roll_white_heaven_bonus_gu)
            # -- one independent 1/1000 roll per participant, same as canon_drop just above,
            # only ever eligible against a White Heaven boss (detected via its own realm field).
            if self.enemies[0].monster.realm == "White Heaven":
                bonus_gu = self.game.roll_white_heaven_bonus_gu(self.game.WHITE_HEAVEN_RAID_BONUS_GU_CHANCE)
                if bonus_gu:
                    loot[bonus_gu] = loot.get(bonus_gu, 0) + 1
                    self._log(f"🌟 A Rank 8 Unique Gu descends from White Heaven itself for **{p['name']}** — **{bonus_gu}**!")

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
        """Builds and inserts one participant's full combat-state dict via
        TeamBattleEngine._build_participant_state, then layers raid-only reward fields on
        top (loot_multiplier, world_region loot/hoard mods -- each joiner rolls their OWN
        region bonus independently, unlike the shared stat_multiplier decided once at raid
        creation, since spirit stones/materials/pages are already granted per-participant at
        _on_victory). Shared by _on_join (the Join button, mid-"starting"-window) and
        cog.py's /solo_raid (the caller is auto-joined immediately, no button click involved)
        — sync, callers dispatch via asyncio.to_thread themselves."""
        state = self._build_participant_state(user_id, name, player)
        region_mods = self.game.region_encounter_modifiers(user_id, name)
        state["loot_multiplier"] = 1.0
        state["region_loot_chance_bonus_pct"] = region_mods["loot_chance_bonus_pct"]
        state["region_hoard_label"] = region_mods["hoard_label"]
        state["region_hoard_reward"] = region_mods["hoard_reward"]
        self.participants[user_id] = state
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

    # _track_battle_qi_spent/_consume_empower_cost/_on_attack/_apply_guard_or_potion_qi_restore/
    # _on_guard now live on TeamBattleEngine (team_battle.py) -- Flee stays raid-only below.

    async def _on_flee(self, interaction: discord.Interaction):
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.defer()
        await self._submit_action(interaction.user.id, {"type": "flee"})

    # _on_toggle_empower/_on_gu_ability/_on_killer_move/_on_class_ability/_on_soul_projection/
    # _use_defend_ally_for/_on_open_potion_menu/_use_potion_for now live on TeamBattleEngine
    # (team_battle.py).

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
        # Anti-macro button shuffling is scoped to White Heaven raids only (see
        # ui_utils.add_shuffled) -- per explicit request, since White Heaven raids are the ones
        # that actually pay out Primeval Essence Crystals worth macro-farming; every other
        # combat view (hunt/battlefield/pvp/Inheritance Ground, and non-White-Heaven raids)
        # went back to a plain fixed button order.
        is_white_heaven_raid = self.enemies[0].monster.realm == "White Heaven"
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
        row1_buttons = []
        for label, emoji, style, callback in action_buttons:
            button = discord.ui.Button(label=label, emoji=emoji, style=style, row=1, disabled=not active)
            button.callback = callback
            row1_buttons.append(button)

        empower_button = discord.ui.Button(label=f"Empower ({EMPOWER_QI_COST})", emoji="✨", style=discord.ButtonStyle.success, row=1, disabled=not active)
        empower_button.callback = self._on_toggle_empower
        row1_buttons.append(empower_button)

        # Dispatches to Defend Ally/Inspire/Freeze based on the clicking player's own
        # character_class (see _on_class_ability) — one shared button since this view is
        # rendered identically for every participant regardless of their class.
        class_button = discord.ui.Button(label="Class Ability", emoji="🎭", style=discord.ButtonStyle.success, row=1, disabled=not active)
        class_button.callback = self._on_class_ability
        row1_buttons.append(class_button)
        if is_white_heaven_raid:
            add_shuffled(self, row1_buttons)
        else:
            for button in row1_buttons:
                self.add_item(button)

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

        row3_buttons = []
        gu_button = discord.ui.Button(label="Use Gu Ability", emoji="🐛", style=discord.ButtonStyle.primary, row=3, disabled=not active)
        gu_button.callback = self._on_gu_ability
        row3_buttons.append(gu_button)

        # Additive alongside Use Gu Ability above, not a replacement -- like it, this view is
        # shared across every participant, so it can only gate on the shared `active` flag
        # here; the real equipped/affordability checks happen per-clicker inside
        # _on_killer_move itself, same convention Soul Projection's own button just below uses.
        killer_move_button = discord.ui.Button(label="Use Killer Move", emoji="🌀", style=discord.ButtonStyle.primary, row=3, disabled=not active)
        killer_move_button.callback = self._on_killer_move
        row3_buttons.append(killer_move_button)

        # Nascent Soul Avatar's Soul Projection (see avatar.py) — like Empower/Class Ability
        # above, this view is rendered identically for every participant, so it can only gate
        # on the shared `active` flag here; the real soul-chosen/affordability checks happen
        # per-clicker inside _on_soul_projection itself.
        soul_projection_button = discord.ui.Button(
            label=f"Soul Projection ({format_number(avatar.SOUL_PROJECTION_QI_COST)})", emoji="🌀",
            style=discord.ButtonStyle.success, row=3, disabled=not active,
        )
        soul_projection_button.callback = self._on_soul_projection
        row3_buttons.append(soul_projection_button)

        # A per-player select (built fresh from just the clicking user's inventory) rather
        # than a shared one on this view — see _on_open_potion_menu. The full catalog of
        # usable Healing/Pills items (41 and counting, after the tiered Alchemy pills) blew
        # past Discord's 25-option cap on a Select, which silently 400'd this whole message
        # ("The application did not respond") every single time /raid was used.
        potion_button = discord.ui.Button(label="Use Potion/Pill", emoji="🧪", style=discord.ButtonStyle.success, row=3, disabled=not active)
        potion_button.callback = self._on_open_potion_menu
        row3_buttons.append(potion_button)
        if is_white_heaven_raid:
            add_shuffled(self, row3_buttons)
        else:
            for button in row3_buttons:
                self.add_item(button)

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

        # Heavenly Sight Gu (see content/canon_gu_white_heaven.py) -- this embed is shared
        # across the whole party (one message, not personalized per viewer, see
        # equipment_view.py's own "shared render" note for the same constraint), so if ANY
        # participant has it equipped, the reveal is shown to the whole party rather than
        # trying to build a per-viewer variant. Equipped Gu names carry a "(Quality)" suffix
        # -- parse_gu_name strips it to recover the bare family name.
        def _has_heavenly_sight(uid):
            gu_name = self.game.db.get_equipped(uid).get("gu_ability")
            return gu_name and (parse_gu_name(gu_name)[0] or gu_name) == "Heavenly Sight Gu"

        if any(_has_heavenly_sight(uid) for uid in self.participants):
            sight_lines = [
                f"**{e.monster.name}** — 🎯 ATK `{format_number(e.monster.atk_stat)}` ⚔️ STR `{format_number(e.monster.str_stat)}` 🛡️ DEF `{format_number(e.monster.def_stat)}` 🏃 SPD `{format_number(e.monster.spd_stat)}`"
                + (f" • 💉 heals {e.monster.ability.lifesteal_percent:.0%} of damage dealt" if e.monster.ability.lifesteal_percent > 0 else "")
                for e in self.enemies if e.alive
            ]
            if sight_lines:
                embed.add_field(name="👁️ Heavenly Sight", value="\n".join(sight_lines)[:1024], inline=False)

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
                loot_text = ", ".join(f"{item_emoji(name)} {name} x{qty}" for name, qty in loot.items()) or "nothing else"
                loot_lines.append(f"**{p['name']}**: {stones} 🪙 + {loot_text}")
            embed.add_field(name="🎁 Loot (rolled per participant)", value="\n".join(loot_lines)[:1024], inline=False)
        elif self.status == "wiped":
            # Per-player Qi lost (see TeamBattleEngine's qi_lost_on_death, team_battle.py) --
            # the shared "Recent Combat" log already says this too, but it can scroll out of
            # MAX_LOG_LINES well before a longer fight actually ends, so it's worth a clear,
            # permanent callout here per explicit request.
            qi_lines = [
                f"**{p['name']}**: {format_number(p.get('qi_lost_on_death', 0))} qi lost" for p in self.participants.values()
            ]
            embed.add_field(
                name="💀 Outcome",
                value="The whole party was knocked out. No loot — regroup and try again.\n" + "\n".join(qi_lines),
                inline=False,
            )

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
        # Same "attach once at send, keep pointing every later embed at it" convention as
        # hunt.py's identical block -- see its own comment for why.
        if self.enemies[0].monster.realm == "White Heaven" and os.path.exists(white_heaven.WHITE_HEAVEN_IMAGE_PATH):
            embed.set_image(url=f"attachment://{os.path.basename(white_heaven.WHITE_HEAVEN_IMAGE_PATH)}")
        return embed


# PotionPickerView/AllyPickerView (opened by "Use Potion/Pill"/a Tank's "Class Ability")
# now live in team_battle.py, shared with /inheritance_ground's battle bubbles.


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
