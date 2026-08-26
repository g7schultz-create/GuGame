"""
/immortal_raid (admin-only preview): a coordination-heavy raid boss prototype built directly on
TeamBattleEngine (game/team_battle.py) -- the same base InheritanceGroundView uses -- rather than
subclassing RaidView (game/raid.py). RaidView's own single hardcoded telegraphed-charge special
would need to be immediately overridden away to make room for this encounter's full weighted
moveset (see monsters.Monster.moveset), so inheriting it just to neutralize it would be more
fragile than never inheriting it at all. RaidView itself needs zero changes for any of this.

New mechanics beyond what /raid and /inheritance_ground already share via TeamBattleEngine (see
the approved plan, cryptic-nibbling-patterson.md, for the full design rationale):
  - HP-threshold boss phases (monsters.Monster.phases), including one add-spawn phase.
  - A secondary Break Gauge with a repeatable "shattered" burst-damage window
    (monsters.Monster.break_gauge_max/shattered_*).
  - A weighted, multi-move boss AI (monsters.Monster.moveset) instead of one fixed special.
  - Formation/Interrupt actions feeding a telegraphed move's coordination-check requirement --
    succeed together or the whole party pays for it (monsters.Monster.moveset's BossMove.
    formation_needed/interrupt_needed).
  - A hard enrage/wipe timer, separate from the DPS-check timer /inheritance_ground's Blood Sea
    content already uses (monsters.Monster.hard_enrage_round).
  - Ally-driven Save Ally revival within a limited window (monsters.Monster.revival_enabled) --
    /raid and /inheritance_ground still have no ally-revival path at all; this is opt-in and
    doesn't change their behavior.
  - Lifesteal diminishment against this specific boss (monsters.Monster.lifesteal_reduction_pct)
    so a lifesteal-heavy build can't trivially out-sustain real, live-player-scale damage.

Reward design (contribution-tracked rewards, titles) is explicitly deferred -- victory here just
rolls the boss's own drop table + a flat spirit-stone range, not /raid's full root/physique/
avatar-gear reward stack, to keep this pass focused on validating the new combat mechanics.
"""

import asyncio
import random
import time

import discord

from . import avatar
from .base_view import GameView
from .character_class import CLASS_EMOJI
from .content.monsters.immortal_raid import HEAVEN_DEVOURING_DRAGON
from .items import item_emoji
from .monsters import roll_loot
from .team_battle import EMPOWER_QI_COST, RaidEnemy, TeamBattleEngine
from .ui_utils import format_number, render_bar

ROUND_TIMEOUT_SECONDS = 30
RAID_JOIN_COUNTDOWN_SECONDS = 30
AFK_LOOT_PENALTY = 0.25  # mirrors raid.py's own AFK policy

SAVE_ALLY_QI_COST = 20

# Placeholder reward sizing -- real reward design (contribution-tracked rewards, titles) is
# explicitly deferred (see the approved plan's backlog); this is just "clearly more than an
# ordinary /raid boss" for admin testing, not a tuned number.
IMMORTAL_RAID_SPIRIT_STONE_MIN = 500
IMMORTAL_RAID_SPIRIT_STONE_MAX = 1000

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


class SaveAllyPickerView(GameView):
    """Ephemeral menu opened by the Save Ally button -- lets the clicker pick which currently-
    down (but not yet permanently_out) ally to revive this round. Mirrors AllyPickerView's own
    shape (team_battle.py, Defend Ally's picker) but targets DOWN allies instead of alive ones."""

    def __init__(self, battle_view, saver_id: int, down_allies: list):
        super().__init__(timeout=60)
        select = discord.ui.Select(
            placeholder="Save who?",
            options=[discord.SelectOption(label=ally["name"], value=str(uid)) for uid, ally in down_allies],
        )

        async def on_pick(interaction):
            await battle_view._use_save_ally_for(interaction, saver_id, int(select.values[0]))

        select.callback = on_pick
        self.add_item(select)


class ImmortalRaidView(TeamBattleEngine, GameView):
    def __init__(self, game, boss_name: str = HEAVEN_DEVOURING_DRAGON.name):
        super().__init__(timeout=1800)  # long safety net, mirrors RaidView's own
        self.game = game
        self.raid_name = boss_name
        self.enemies = [RaidEnemy(HEAVEN_DEVOURING_DRAGON)]
        self.loot_table = HEAVEN_DEVOURING_DRAGON
        self.participants: dict = {}
        self.actions: dict = {}
        self.round = 1
        self.status = "starting"
        self.starts_at = int(time.time()) + RAID_JOIN_COUNTDOWN_SECONDS
        self.log: list = []
        self.result_loot: dict = {}
        self.stones_awarded: dict = {}
        self.message: discord.Message = None
        self._round_epoch = 0
        self.inspire_rounds_remaining = 0
        self._build_components()
        asyncio.create_task(self._start_countdown())

    # This view is shared by everyone in the raid, not owned by a single user -- no
    # interaction_check restriction; eligibility is enforced per-action instead (mirrors
    # RaidView's own).

    # -- join / round timer (mirrors RaidView's own shape, minus Flee/region loot) -----------

    def _validate_actor(self, user_id: int):
        if self.status == "starting":
            return None, f"The raid hasn't started yet — it begins <t:{self.starts_at}:R>."
        if self.status != "fighting":
            return None, "This raid has already ended."
        return super()._validate_actor(user_id)

    def _add_participant(self, user_id: int, name: str, player: dict):
        state = self._build_participant_state(user_id, name, player)
        state["loot_multiplier"] = 1.0
        self.participants[user_id] = state
        self.game.apply_encounter_start_bonuses(user_id, name)
        self._log(f"🙋 **{name}** joins the Immortal Raid!")

    async def _on_join(self, interaction: discord.Interaction):
        user = interaction.user
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
        self._begin_fight_or_abandon()
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def _apply_afk_actions(self):
        for user_id in self._alive_participant_ids():
            if user_id in self.actions:
                continue
            p = self.participants[user_id]
            p["loot_multiplier"] = max(0.0, p["loot_multiplier"] - AFK_LOOT_PENALTY)
            self.actions[user_id] = {"type": "attack", "target": 0, "guaranteed": False}
            self._log(f"⏱️ **{p['name']}** ran out of time and auto-attacks {self.enemies[0].monster.name}! (reward chance now {p['loot_multiplier'] * 100:.0f}%)")

    async def _start_countdown(self):
        await asyncio.sleep(RAID_JOIN_COUNTDOWN_SECONDS)
        if self.status != "starting":
            return
        self._begin_fight_or_abandon()
        await asyncio.to_thread(self._build_components)
        await self._refresh_message()

    def _begin_fight_or_abandon(self):
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
            return
        self._apply_afk_actions()
        await self._finish_round()

    async def _finish_round(self):
        await asyncio.to_thread(self._resolve_round)
        await asyncio.to_thread(self._build_components)
        await self._refresh_message()
        if self.status == "fighting" and self.participants:
            self._start_round_timer()

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

    # -- Formation / Interrupt / Save Ally -----------------------------------------------

    async def _on_formation(self, interaction: discord.Interaction):
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.defer()
        await self._submit_action(interaction.user.id, {"type": "formation"})

    async def _on_interrupt(self, interaction: discord.Interaction):
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.defer()
        await self._submit_action(interaction.user.id, {"type": "interrupt"})

    async def _on_save_ally(self, interaction: discord.Interaction):
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        if p["qi"] < SAVE_ALLY_QI_COST:
            await interaction.response.send_message(f"Not enough battle Qi for Save Ally (needs {SAVE_ALLY_QI_COST}).", ephemeral=True)
            return
        down_allies = [(uid, ally) for uid, ally in self.participants.items() if ally["down"] and not ally.get("permanently_out")]
        if not down_allies:
            await interaction.response.send_message("No one needs saving right now.", ephemeral=True)
            return
        picker = SaveAllyPickerView(self, interaction.user.id, down_allies)
        await interaction.response.send_message("Choose who to save this round:", view=picker, ephemeral=True)

    async def _use_save_ally_for(self, interaction: discord.Interaction, saver_id: int, target_down_id: int):
        p, error = self._validate_actor(saver_id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        target = self.participants.get(target_down_id)
        if target is None or not target["down"] or target.get("permanently_out"):
            await interaction.response.send_message("That ally can't be saved right now.", ephemeral=True)
            return
        if p["qi"] < SAVE_ALLY_QI_COST:
            await interaction.response.send_message(f"Not enough battle Qi for Save Ally (needs {SAVE_ALLY_QI_COST}).", ephemeral=True)
            return
        p["qi"] -= SAVE_ALLY_QI_COST
        await asyncio.to_thread(self._persist_qi, saver_id, p)
        await interaction.response.edit_message(content=f"✨ Saving **{target['name']}** this round.", view=None)
        await self._submit_action(saver_id, {"type": "save_ally", "target_down_id": target_down_id})

    def _resolve_revival_phase(self):
        """Overrides TeamBattleEngine's no-op default. Doubly opt-in -- bails immediately
        unless the boss has revival_enabled set (only this view's own Monster does)."""
        if not self.enemies or not self.enemies[0].monster.revival_enabled:
            return
        monster = self.enemies[0].monster
        for user_id, action in self.actions.items():
            if action.get("type") != "save_ally":
                continue
            target = self.participants.get(action.get("target_down_id"))
            if target is None or not target["down"] or target.get("permanently_out"):
                continue
            target["down"] = False
            target["hp"] = max(1, round(target["max_hp"] * monster.revival_hp_pct))
            self.game.db.set_hp(action["target_down_id"], max(1, target["hp"] - target.get("hp_bonus", 0)))
            target["down_round"] = None
            saver_name = self.participants.get(user_id, {}).get("name", "someone")
            self._log(f"✨ **{saver_name}** saves **{target['name']}**! They return with {target['hp']:.0f} HP.")

        for p in self.participants.values():
            if not p["down"] or p.get("permanently_out"):
                continue
            if p.get("down_round") is None:
                p["down_round"] = self.round
            elif self.round - p["down_round"] >= monster.revival_window_rounds:
                p["permanently_out"] = True
                self._log(f"💀 **{p['name']}**'s revival window has closed — they're out for the rest of the fight.")

    # -- Break Gauge / phases / weighted moveset AI / hard enrage ------------------------

    def _on_player_hit_landed(self, target: "RaidEnemy", p: dict, damage: int, label: str):
        """Overrides TeamBattleEngine's no-op default -- chips the target's Break Gauge."""
        monster = target.monster
        if monster.break_gauge_max <= 0 or target.shattered_rounds_remaining > 0 or target.break_gauge <= 0:
            return
        chip = damage * monster.break_gauge_damage_pct_of_hit
        if chip <= 0:
            return
        target.break_gauge = max(0, target.break_gauge - chip)
        if target.break_gauge <= 0:
            target.shattered_rounds_remaining = monster.shattered_duration_rounds
            self._log(f"💥 {monster.name}'s Dao Defense SHATTERS! Vulnerable for {monster.shattered_duration_rounds} round(s)!")

    def _maybe_advance_phase(self, enemy: "RaidEnemy"):
        """Overrides TeamBattleEngine's no-op default. A while loop (not a single check) so a
        rare, unusually large round of damage that crosses more than one phase threshold at
        once still advances correctly instead of getting stuck one phase behind."""
        monster = enemy.monster
        while enemy.phase_index < len(monster.phases) and enemy.hp <= enemy.max_hp * monster.phases[enemy.phase_index].hp_pct:
            next_phase = monster.phases[enemy.phase_index]
            enemy.phase_index += 1
            if next_phase.announce:
                self._log(next_phase.announce)
            for add_monster in next_phase.spawn_adds:
                self.enemies.append(RaidEnemy(add_monster))
                self._log(f"👹 {add_monster.name} joins the fight!")

    def _enemy_attack_multiplier(self, enemy: "RaidEnemy") -> float:
        """Overrides TeamBattleEngine's default (1.0) -- folds in permanent phase ATK bonuses
        (and a failed coordination check's own bonus_atk_pct) plus the shattered ATK reduction."""
        monster = enemy.monster
        multiplier = 1.0 + sum(phase.atk_pct_bonus for phase in monster.phases[:enemy.phase_index]) + enemy.bonus_atk_pct
        if enemy.shattered_rounds_remaining > 0:
            multiplier *= (1 - monster.shattered_atk_pct_reduction)
        return multiplier

    def _maybe_trigger_hard_enrage(self, enemy: "RaidEnemy"):
        """Overrides TeamBattleEngine's no-op default. hard_enrage_fired is a one-shot guard --
        self.round only ever increases, so without it this would refire every round past
        hard_enrage_round instead of exactly once."""
        monster = enemy.monster
        if not monster.hard_enrage_round or self.round < monster.hard_enrage_round or enemy.hard_enrage_fired:
            return
        enemy.hard_enrage_fired = True
        self._log(f"☠️ {monster.hard_enrage_log or (monster.name + ' unleashes its full power!')}")
        self._apply_party_wide_damage_pct(monster.hard_enrage_damage_pct, monster.name)

    def _select_weighted_move(self, enemy: "RaidEnemy"):
        eligible = [m for m in enemy.monster.moveset if enemy.phase_index >= m.min_phase and m.name not in enemy.move_cooldowns]
        if not eligible:
            return None
        overrides = {}
        for phase in enemy.monster.phases[:enemy.phase_index]:
            overrides.update(phase.move_weight_overrides)
        weights = [max(0.0, overrides.get(m.name, m.base_weight) * self._move_condition_multiplier(enemy, m)) for m in eligible]
        if sum(weights) <= 0:
            return None
        return random.choices(eligible, weights=weights)[0]

    def _move_condition_multiplier(self, enemy: "RaidEnemy", move) -> float:
        """Implements the doc's own weighted-AI pseudocode -- a small, open-ended condition
        list rather than a fixed enum, so new conditions don't need a new BossMove field each
        time. Unknown "if" kinds are silently ignored (multiplier unaffected)."""
        hp_pct = enemy.hp / enemy.max_hp if enemy.max_hp else 0
        players_dead = sum(1 for p in self.participants.values() if p["down"])
        formation_active = any(a.get("type") == "formation" for a in self.actions.values())
        multiplier = 1.0
        for cond in move.weight_conditions:
            kind = cond.get("if")
            if kind == "hp_pct_below" and hp_pct < cond.get("value", 0):
                multiplier *= cond.get("weight_multiplier", 1.0)
            elif kind == "players_dead_at_least" and players_dead >= cond.get("value", 0):
                multiplier *= cond.get("weight_multiplier", 1.0)
            elif kind == "defensive_formation_active" and formation_active:
                multiplier *= cond.get("weight_multiplier", 1.0)
            elif kind == "burn_stacks_active" and enemy.burn_ticks_remaining > 0:
                multiplier *= cond.get("weight_multiplier", 1.0)
        return multiplier

    def _maybe_handle_boss_charge(self, enemy: "RaidEnemy", idx: int, alive_ids: list, defend_map: dict) -> bool:
        """Overrides TeamBattleEngine's no-op default with the generalized weighted moveset AI
        -- a from-scratch override, NOT RaidView's own single-charge implementation (this view
        never inherits RaidView), so nothing here touches raid.py."""
        if not enemy.monster.moveset:
            return False
        if enemy.active_move is not None:
            return self._tick_or_release_move(enemy, idx, alive_ids, defend_map)
        for name in list(enemy.move_cooldowns):
            enemy.move_cooldowns[name] = max(0, enemy.move_cooldowns[name] - 1)
            if enemy.move_cooldowns[name] == 0:
                del enemy.move_cooldowns[name]
        move = self._select_weighted_move(enemy)
        if move is None:
            return False
        self._start_move(enemy, idx, move, alive_ids, defend_map)
        return True

    def _start_move(self, enemy: "RaidEnemy", idx: int, move, alive_ids: list, defend_map: dict):
        enemy.active_move = move
        if move.telegraph_rounds <= 0:
            self._release_move(enemy, idx, alive_ids, defend_map)
            return
        enemy.active_move_rounds_remaining = move.telegraph_rounds
        text = move.telegraph_text or f"{enemy.monster.name} begins {move.name}!"
        self._log(f"⚡ {text}")

    def _tick_or_release_move(self, enemy: "RaidEnemy", idx: int, alive_ids: list, defend_map: dict) -> bool:
        move = enemy.active_move
        enemy.active_move_rounds_remaining -= 1
        if enemy.active_move_rounds_remaining > 0:
            self._log(f"⚡ {enemy.monster.name}'s {move.name} builds — {enemy.active_move_rounds_remaining} round(s) left!")
            return True
        self._release_move(enemy, idx, alive_ids, defend_map)
        return True

    def _release_move(self, enemy: "RaidEnemy", idx: int, alive_ids: list, defend_map: dict):
        move = enemy.active_move
        enemy.active_move = None
        enemy.active_move_rounds_remaining = 0
        enemy.move_cooldowns[move.name] = move.cooldown_rounds
        self._log(f"💥 {enemy.monster.name} unleashes {move.name}!")
        if move.formation_needed or move.interrupt_needed:
            self._resolve_coordination_move(enemy, move)
            return
        if move.damage_mode == "party_pct":
            self._apply_party_wide_damage_pct(move.party_damage_pct, move.name)
            return
        if not alive_ids:
            return
        targets = list(alive_ids) if move.damage_mode == "cleave" else [random.choice(alive_ids)]
        for target_id in targets:
            if target_id not in self._alive_participant_ids():
                continue
            self._resolve_enemy_hit(
                enemy, idx, target_id, defend_map,
                str_multiplier=move.str_multiplier, guaranteed_hit=True, label=move.name,
            )

    def _resolve_coordination_move(self, enemy: "RaidEnemy", move):
        formation_count = sum(1 for a in self.actions.values() if a.get("type") == "formation")
        interrupt_count = sum(1 for a in self.actions.values() if a.get("type") == "interrupt")
        success = formation_count >= move.formation_needed and interrupt_count >= move.interrupt_needed
        tally = f"({formation_count}/{move.formation_needed} Formation, {interrupt_count}/{move.interrupt_needed} Interrupt)"
        if success:
            self._log(f"🛡️ The party disrupts {move.name}! {tally}")
            if move.coordination_success_damage_pct > 0:
                self._apply_party_wide_damage_pct(move.coordination_success_damage_pct, f"{move.name} (partial)")
        else:
            self._log(f"💥 The party fails to answer {move.name}! {tally}")
            self._apply_party_wide_damage_pct(move.coordination_failure_damage_pct, move.name)
            if move.failure_boss_heal_pct:
                healed = round(enemy.max_hp * move.failure_boss_heal_pct)
                enemy.hp = min(enemy.max_hp, enemy.hp + healed)
                self._log(f"💚 {enemy.monster.name} heals {format_number(healed)} HP!")
            if move.failure_boss_atk_pct_bonus:
                enemy.bonus_atk_pct += move.failure_boss_atk_pct_bonus

    def _apply_party_wide_damage_pct(self, pct: float, source_label: str):
        """The "-45% party HP" mechanic (a failed coordination check, its own partial-success
        cost, and the hard enrage wipe all funnel through this) -- a flat cut of each alive
        participant's OWN max_hp, bypassing hit/dodge/Guard entirely (mirrors the DPS-check's
        own "guaranteed, unavoidable" precedent), respecting only Undying Vow. Structurally
        copies Phase 1.65's existing bleed-tick down-handling (team_battle.py) rather than
        inventing new death-penalty/ward/escape logic."""
        if pct <= 0:
            return
        for user_id, p in list(self.participants.items()):
            if p["down"]:
                continue
            damage = round(p["max_hp"] * pct)
            if damage <= 0:
                continue
            p["hp"] -= damage
            if p["hp"] > 0:
                self._persist_hp(user_id, p)
                self._log(f"💥 **{p['name']}** takes {format_number(damage)} damage from {source_label}!")
                continue
            if self._try_undying_vow(user_id, p):
                p["hp"] = 1
                self._persist_hp(user_id, p)
                self._log(f"🌌 **{p['name']}**'s Undying Vow flares against {source_label} — death itself yields!")
                continue
            p["down"] = True
            self.game.db.set_hp(user_id, 1)
            ward_name = self.game.check_and_consume_defeat_ward(user_id)
            escape_gu_name = None if ward_name else self.game.check_and_consume_worldly_escape(user_id)
            if ward_name:
                self._log(f"✨ **{ward_name}** activates for **{p['name']}** — knocked out by {source_label}, but the Qi loss is warded away!")
            elif escape_gu_name:
                self._log(f"✨ **{escape_gu_name}** activates for **{p['name']}** — knocked out by {source_label}, but the Qi loss is escaped entirely!")
            else:
                bonuses = self.game.compute_equipment_bonuses(user_id)
                reduction = bonuses.get("death_qi_loss_reduction_pct", 0)
                qi_lost, _ = self.game.db.apply_death_penalty(user_id, reduction_pct=reduction)
                p["qi_lost_on_death"] = qi_lost
                self._log(f"💀 **{p['name']}** is knocked out by {source_label}, losing {format_number(qi_lost)} qi!")

    def _on_enemy_defeated(self, enemy: "RaidEnemy"):
        """Overrides TeamBattleEngine's no-op default -- collapses an in-progress move if the
        enemy holding it dies mid-telegraph (mirrors RaidView's identical charge-collapse)."""
        if enemy.active_move is not None:
            self._log(f"⚡ {enemy.monster.name}'s {enemy.active_move.name} collapses along with it!")
            enemy.active_move = None
            enemy.active_move_rounds_remaining = 0

    # -- victory / wipe ---------------------------------------------------------------------

    def _on_victory(self):
        self.status = "victory"
        for user_id, p in self.participants.items():
            multiplier = p.get("loot_multiplier", 1.0)
            loot = roll_loot(self.loot_table, chance_multiplier=multiplier)
            for item_name, quantity in loot.items():
                self.game.db.add_item(user_id, item_name, quantity)
            stones = round(random.randint(IMMORTAL_RAID_SPIRIT_STONE_MIN, IMMORTAL_RAID_SPIRIT_STONE_MAX) * multiplier)
            self.game.db.add_spirit_stones(user_id, stones)
            self.result_loot[user_id] = loot
            self.stones_awarded[user_id] = stones
        self._log(f"🎉 {self.raid_name} is defeated! Loot distributed to all {len(self.participants)} participants.")

    def _on_wipe(self):
        self.status = "wiped"
        self._log(f"💀 The entire party is knocked out. {self.raid_name} stands triumphant...")

    async def on_timeout(self):
        if self.status in ("starting", "fighting"):
            self.status = "abandoned"
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                embed = await asyncio.to_thread(self.build_embed)
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass

    # -- UI building --------------------------------------------------------------------

    def _build_components(self):
        self.clear_items()
        active = self.status == "fighting"
        can_join = self.status == "starting"

        if can_join:
            join_button = discord.ui.Button(label="Join Raid", emoji="🙋", style=discord.ButtonStyle.primary, row=0)
            join_button.callback = self._on_join
            self.add_item(join_button)
            start_button = discord.ui.Button(
                label="Start Now", emoji="▶️", style=discord.ButtonStyle.success, row=0, disabled=not self.participants,
            )
            start_button.callback = self._on_start_now
            self.add_item(start_button)
        else:
            formation_button = discord.ui.Button(label="Formation", emoji="🛡️", style=discord.ButtonStyle.primary, row=0, disabled=not active)
            formation_button.callback = self._on_formation
            self.add_item(formation_button)
            interrupt_button = discord.ui.Button(label="Interrupt", emoji="⚡", style=discord.ButtonStyle.primary, row=0, disabled=not active)
            interrupt_button.callback = self._on_interrupt
            self.add_item(interrupt_button)
            save_ally_button = discord.ui.Button(label="Save Ally", emoji="✨", style=discord.ButtonStyle.success, row=0, disabled=not active)
            save_ally_button.callback = self._on_save_ally
            self.add_item(save_ally_button)

        action_buttons = [
            ("Attack", "⚔️", discord.ButtonStyle.primary, self._on_attack),
            ("Guard", "🛡️", discord.ButtonStyle.secondary, self._on_guard),
        ]
        for label, emoji, style, callback in action_buttons:
            button = discord.ui.Button(label=label, emoji=emoji, style=style, row=1, disabled=not active)
            button.callback = callback
            self.add_item(button)

        empower_button = discord.ui.Button(label=f"Empower ({EMPOWER_QI_COST})", emoji="🔥", style=discord.ButtonStyle.success, row=1, disabled=not active)
        empower_button.callback = self._on_toggle_empower
        self.add_item(empower_button)

        class_button = discord.ui.Button(label="Class Ability", emoji="🎭", style=discord.ButtonStyle.success, row=1, disabled=not active)
        class_button.callback = self._on_class_ability
        self.add_item(class_button)

        target_options = [
            discord.SelectOption(label=f"{e.monster.name} — {format_number(max(0, e.hp))}/{format_number(e.max_hp)} HP", value=str(idx), emoji="🐲" if idx == 0 else "🐛")
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

        row3_buttons = [
            ("Use Gu Ability", "🐛", discord.ButtonStyle.primary, self._on_gu_ability),
            ("Use Killer Move", "🌀", discord.ButtonStyle.primary, self._on_killer_move),
            (f"Soul Projection ({format_number(avatar.SOUL_PROJECTION_QI_COST)})", "🌀", discord.ButtonStyle.success, self._on_soul_projection),
            ("Use Potion/Pill", "🧪", discord.ButtonStyle.success, self._on_open_potion_menu),
        ]
        for label, emoji, style, callback in row3_buttons:
            button = discord.ui.Button(label=label, emoji=emoji, style=style, row=3, disabled=not active)
            button.callback = callback
            self.add_item(button)

    def build_embed(self) -> discord.Embed:
        boss = self.enemies[0]
        if self.status == "starting":
            description = f"⏳ The Immortal Raid begins <t:{self.starts_at}:R> — click **Join Raid** now to be in it from round 1!"
        else:
            description = (
                f"Round **{self.round}** — everyone locks in an action, then the round resolves at once "
                f"(or after {ROUND_TIMEOUT_SECONDS}s, whichever comes first)."
            )
        if self.inspire_rounds_remaining > 0:
            description += f"\n✨ **Inspire active** — party STR/DEF boosted ({self.inspire_rounds_remaining} round(s) left)."
        if boss.active_move is not None:
            move = boss.active_move
            description += f"\n⚡ **{boss.monster.name} is preparing {move.name}!** It lands in {boss.active_move_rounds_remaining} round(s)."
            if move.formation_needed or move.interrupt_needed:
                formation_count = sum(1 for a in self.actions.values() if a.get("type") == "formation")
                interrupt_count = sum(1 for a in self.actions.values() if a.get("type") == "interrupt")
                description += (
                    f"\n🛡️ **Coordination check!** Formation: {formation_count}/{move.formation_needed} • "
                    f"⚡ Interrupt: {interrupt_count}/{move.interrupt_needed}"
                )

        embed = discord.Embed(title=f"👑 {self.raid_name} • {STATUS_LABELS[self.status]}", description=description, color=STATUS_COLORS[self.status])

        enemy_lines = []
        for idx, e in enumerate(self.enemies):
            icon = "🐲" if idx == 0 else "🐛"
            if not e.alive:
                enemy_lines.append(f"{icon} **{e.monster.name}** — 💀 Defeated")
                continue
            frozen_note = " ❄️ *Frozen*" if e.frozen_rounds > 0 else ""
            shattered_note = " 💥 *SHATTERED*" if e.shattered_rounds_remaining > 0 else ""
            pct = int(100 * max(0, e.hp) / e.max_hp)
            line = f"{icon} **{e.monster.name}**{frozen_note}{shattered_note} — {format_number(max(0, e.hp))}/{format_number(e.max_hp)} HP ({pct}%)\n`{render_bar(e.hp, e.max_hp)}`"
            if e.monster.break_gauge_max > 0:
                line += f"\nBreak Gauge: {format_number(max(0, e.break_gauge))}/{format_number(e.monster.break_gauge_max)} `{render_bar(e.break_gauge, e.monster.break_gauge_max)}`"
            enemy_lines.append(line)
        alive_count = sum(1 for e in self.enemies if e.alive)
        embed.add_field(name=f"⚔️ Enemies ({alive_count}/{len(self.enemies)} alive)", value="\n".join(enemy_lines)[:1024], inline=False)

        if self.participants:
            lines = []
            for uid, p in self.participants.items():
                class_emoji = CLASS_EMOJI.get(p.get("character_class"), "")
                pct = int(100 * max(0, p["hp"]) / p["max_hp"])
                if p.get("permanently_out"):
                    status = "☠️ out for the fight"
                elif p["down"]:
                    if boss.monster.revival_enabled and p.get("down_round") is not None:
                        remaining = max(0, boss.monster.revival_window_rounds - (self.round - p["down_round"]))
                        status = f"💀 knocked out (save within {remaining} round(s))"
                    else:
                        status = "💀 knocked out"
                elif uid in self.actions:
                    status = "✅ locked in"
                else:
                    status = "⏳ choosing..."
                target_idx = self._resolve_target_index(p)
                target_name = self.enemies[target_idx].monster.name if target_idx >= 0 else "—"
                penalty_note = f" • 🔻 reward {p['loot_multiplier'] * 100:.0f}%" if p.get("loot_multiplier", 1.0) < 1.0 else ""
                empower_note = " • ✨ Empowered" if p.get("empowered") else ""
                lines.append(
                    f"{class_emoji}**{p['name']}** — {format_number(max(0, p['hp']))}/{format_number(p['max_hp'])} HP ({pct}%) • 🎯 {target_name} • {status}{empower_note}{penalty_note}\n"
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
            qi_lines = [f"**{p['name']}**: {format_number(p.get('qi_lost_on_death', 0))} qi lost" for p in self.participants.values()]
            embed.add_field(
                name="💀 Outcome",
                value="The whole party was knocked out. No loot — regroup and try again.\n" + "\n".join(qi_lines),
                inline=False,
            )

        if self.status == "starting":
            footer_text = "Click Join Raid to be in it when the countdown ends — round 1 hasn't started yet."
        elif self.status == "fighting":
            footer_text = (
                "Pick a target, then Attack/Guard/Formation/Interrupt/Save Ally/Class Ability/Gu ability — actions are ephemeral. "
                f"AFK when the {ROUND_TIMEOUT_SECONDS}s clock runs out and you'll auto-attack the boss and lose 25% reward chance (down to 0%)."
            )
        else:
            footer_text = "This raid has ended."
        embed.set_footer(text=footer_text)
        return embed
