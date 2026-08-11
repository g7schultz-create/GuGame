"""
/inheritance_ground -- a 3-4 player INVITED team explores a named inheritance site: a shared
bubble board (treasure or battle bubbles, popped in turn order), a Final Trial, and a betrayal
twist. See game/inheritance_ground_data.py for content and GameManager's own inheritance-ground
methods (manager.py, right after the /raid gate section) for the business logic this view only
ever calls into, never duplicates.

Three views:
  InheritanceGroundLobbyView   -- invite/accept flow (leader + up to 3 invitees).
  InheritanceGroundView        -- the run itself: intro -> bubble board -> trial -> betrayal ->
                                   resolution, with a real multi-round team fight embedded as its
                                   own "battle" phase whenever a battle bubble is popped.
  AbandonInheritanceGroundView -- self-service escape hatch, same shape as AbandonRaidView/
                                   AbandonDiscoveryView, shipped from day one rather than added
                                   reactively (see the raid flee bug fixed in commit 0b6b712).
"""

import asyncio
import os

import discord

from . import avatar, inheritance_ground_data
from .base_view import GameView
from .content.monsters import blood_sea_ancestor
from .team_battle import EMPOWER_QI_COST, RaidEnemy, TeamBattleEngine
from .ui_utils import render_bar

BETRAYAL_DECISION_SECONDS = 60
BATTLE_ROUND_TIMEOUT_SECONDS = 30  # matches raid.ROUND_TIMEOUT_SECONDS's own pacing


def build_intro_image_file(ground_key: str) -> discord.File:
    """The intro embed's image (see inheritance_ground_data.GROUNDS[...]["intro_image"]) has to
    be attached as a real discord.File on whichever send/edit call first shows the intro phase --
    embed.set_image's "attachment://..." URL only resolves against a file attached to THAT SAME
    message. Shared by InheritanceGroundLobbyView._resolve (team invite flow) and cog.py's solo
    admin test-start path so the attach logic only lives in one place. Returns None (no image)
    if the ground has none configured or the file isn't present yet -- every caller degrades
    gracefully either way, same as build_embed's own os.path.exists guard."""
    image_path = inheritance_ground_data.GROUNDS[ground_key].get("intro_image")
    if image_path and os.path.exists(image_path):
        return discord.File(image_path, filename=os.path.basename(image_path))
    return None


class AbandonInheritanceGroundView(GameView):
    def __init__(self, user_id: int, game):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.game = game
        button = discord.ui.Button(label="Abandon Stuck Run", emoji="🗑️", style=discord.ButtonStyle.danger)
        button.callback = self._on_abandon
        self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your run to clear.", ephemeral=True)
            return False
        return True

    async def _on_abandon(self, interaction: discord.Interaction):
        await asyncio.to_thread(self.game.abandon_active_inheritance_ground, self.user_id)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="🗑️ Cleared — you can `/inheritance_ground` again now.", view=self)


class InheritanceGroundLobbyView(GameView):
    """leader + invitees (2 required, 1 optional) -- each invitee gets their own Accept/Decline
    gated to their own user_id (same check dao_companion_view.DaoCompanionRequestView.accept
    uses), tracked here rather than as separate messages so the leader sees one live roster."""

    def __init__(self, game, leader: discord.Member, invitees: list, ground_key: str):
        super().__init__(timeout=300)
        self.game = game
        self.leader = leader
        self.invitees = invitees  # [discord.Member, ...], first 2 required, 3rd (if any) optional
        self.ground_key = ground_key
        self.responses = {m.id: "pending" for m in invitees}
        self.resolved = False
        self.message: discord.Message = None
        self._build_components()

    def _required_ids(self):
        return {m.id for m in self.invitees[:2]}

    def _decided(self) -> bool:
        """True once the outcome is already determined -- either a required invitee declined
        (cancel immediately, no need to wait out the rest), or everyone required has accepted
        and anyone optional has responded or there simply isn't one."""
        if any(self.responses[uid] == "declined" for uid in self._required_ids()):
            return True
        if not all(self.responses[uid] == "accepted" for uid in self._required_ids()):
            return False
        optional_ids = {m.id for m in self.invitees[2:]}
        return all(self.responses[uid] != "pending" for uid in optional_ids)

    def _build_components(self):
        self.clear_items()
        if self.resolved:
            return
        accept_button = discord.ui.Button(label="Accept", emoji="✅", style=discord.ButtonStyle.success)
        accept_button.callback = self._on_accept
        self.add_item(accept_button)
        decline_button = discord.ui.Button(label="Decline", emoji="❌", style=discord.ButtonStyle.danger)
        decline_button.callback = self._on_decline
        self.add_item(decline_button)

    async def _respond(self, interaction: discord.Interaction, decision: str):
        if interaction.user.id not in self.responses:
            await interaction.response.send_message("This invitation isn't yours to answer.", ephemeral=True)
            return
        if self.responses[interaction.user.id] != "pending":
            await interaction.response.send_message("You've already responded.", ephemeral=True)
            return
        self.responses[interaction.user.id] = decision
        if self._decided():
            await self._resolve(interaction)
            return
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_accept(self, interaction: discord.Interaction):
        # Re-checked fresh here (not trusted from invite time) -- up to 5 minutes can pass
        # before someone clicks Accept, long enough to start another run in the meantime (an
        # invitee's OWN cooldown is deliberately not gated -- see
        # GameManager.check_inheritance_ground_eligibility). "You" phrasing since this is the
        # clicking player's own eligibility, unlike cog.py's invite-time check which is
        # third-person about an invitee.
        ok, reason_code, _remaining = await asyncio.to_thread(self.game.check_inheritance_ground_eligibility, interaction.user.id, interaction.user.display_name)
        if not ok:
            messages = {
                "not_confirmed": "You need to `/join` and confirm a character first.",
                "already_active": "You're already in another inheritance ground run — finish or abandon it first.",
            }
            await interaction.response.send_message(messages[reason_code], ephemeral=True)
            return
        await self._respond(interaction, "accepted")

    async def _on_decline(self, interaction: discord.Interaction):
        await self._respond(interaction, "declined")

    async def _resolve(self, interaction: discord.Interaction):
        self.resolved = True
        await asyncio.to_thread(self._build_components)
        required_ok = all(self.responses[uid] == "accepted" for uid in self._required_ids())
        if not required_ok:
            declined = [m.display_name for m in self.invitees if self.responses[m.id] == "declined"]
            embed = discord.Embed(
                title="🗺️ Inheritance Ground — Team Didn't Form",
                description=f"Not enough of the invited team accepted (declined: {', '.join(declined) or 'no response in time'}).",
                color=discord.Color.dark_grey(),
            )
            await interaction.response.edit_message(embed=embed, view=self)
            return
        team_members = [self.leader] + [m for m in self.invitees if self.responses.get(m.id) == "accepted"]
        team = [(m.id, m.display_name) for m in team_members]
        # Direct construction, NOT via asyncio.to_thread -- discord.py's own BaseView.__init__
        # binds an internal dispatch Future via asyncio.get_running_loop(); constructed on a
        # to_thread worker thread (no running loop there), that Future silently ends up None
        # and EVERY future button click on the view is then silently dropped (discord.py's own
        # _dispatch_item just no-ops). This is a hard rule for every View/Modal in this
        # codebase regardless of whether it personally calls create_task anywhere -- see
        # commit 45e239a, which fixed this exact bug across the whole codebase.
        run_view = InheritanceGroundView(self.game, self.ground_key, team)
        await asyncio.to_thread(self.game.start_active_inheritance_ground, [uid for uid, _ in team])
        embed = await asyncio.to_thread(run_view.build_embed)
        file = await asyncio.to_thread(build_intro_image_file, self.ground_key)
        if file:
            await interaction.response.edit_message(embed=embed, view=run_view, attachments=[file])
        else:
            await interaction.response.edit_message(embed=embed, view=run_view)
        run_view.message = await interaction.original_response()

    async def on_timeout(self):
        if self.resolved:
            return
        self.resolved = True
        for uid, status in self.responses.items():
            if status == "pending":
                self.responses[uid] = "declined"
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                embed = await asyncio.to_thread(self.build_embed)
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass

    def build_embed(self) -> discord.Embed:
        ground = inheritance_ground_data.GROUNDS[self.ground_key]
        status_emoji = {"pending": "⏳", "accepted": "✅", "declined": "❌"}
        lines = [f"🧍 **{self.leader.display_name}** (leader) ✅"]
        for m in self.invitees:
            optional_tag = " _(optional)_" if m not in self.invitees[:2] else ""
            lines.append(f"🧍 **{m.display_name}**{optional_tag} {status_emoji[self.responses[m.id]]}")
        embed = discord.Embed(
            title=f"🗺️ {ground['name']}",
            description=f"_{ground['flavor']}_\n\n" + "\n".join(lines),
            color=discord.Color.dark_gold(),
        )
        embed.set_footer(text="Both required invitees must Accept to begin. Expires in 5 min.")
        return embed


class InheritanceGroundView(TeamBattleEngine, GameView):
    def __init__(self, game, ground_key: str, team: list):
        super().__init__(timeout=600)
        self.game = game
        self.ground_key = ground_key
        self.team = team  # [(user_id, name), ...]
        self.phase = "intro"
        # Bubble board (replaces the old branching-choice stages) -- see manager.
        # generate_inheritance_ground_board for how it's built. turn_index cycles through
        # self.team -- only that member may pop the next bubble (enforced in the bubble
        # callback itself, not interaction_check, since a disabled discord.ui.Button can't be
        # "disabled for one viewer but not another" -- everyone sees the same button state).
        self.board: list = []
        self.revealed: list = []
        self.turn_index = 0
        self.board_log: list = []  # (name_or_None, "treasure"/"battle", text)
        self.bubble_resolving = False  # re-entrancy guard, mirrors raid.py's own click guards
        self.battles_fought = 0  # feeds roll_inheritance_ground_battle_monster's own scaling

        # "battle" phase state -- populated by _start_battle when a battle bubble is popped
        # (see TeamBattleEngine, team_battle.py, for the full Attack/Guard/Empower/Gu Ability/
        # Class Ability/Killer Move/Soul Projection/Potion-menu combat engine this now shares
        # with /raid). Left in place afterward (harmless, just stale) until the next battle
        # overwrites it.
        self.enemies: list = []
        self.participants: dict = {}
        self.actions: dict = {}
        self.round = 1
        self.log: list = []
        self.inspire_rounds_remaining = 0
        self.battle_wipe = False  # True once a battle ends the run early (team wiped)
        self._battle_round_epoch = 0

        self.trial_result: dict = None
        self.betrayal_choices: dict = {}
        self.betrayal_epoch = 0
        self.share_grants: list = []
        self.betrayal_result: dict = None
        self.message: discord.Message = None
        self._build_components()

    def _team_ids(self):
        return {uid for uid, _ in self.team}

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self._team_ids():
            await interaction.response.send_message("This isn't your inheritance ground run.", ephemeral=True)
            return False
        return True

    def _ground(self):
        return inheritance_ground_data.GROUNDS[self.ground_key]

    def _advance_turn(self):
        self.turn_index = (self.turn_index + 1) % len(self.team)

    # -- components ----------------------------------------------------------------------

    def _build_components(self):
        self.clear_items()
        if self.phase == "intro":
            button = discord.ui.Button(label="Continue", emoji="➡️", style=discord.ButtonStyle.primary)
            button.callback = self._on_intro_continue
            self.add_item(button)
        elif self.phase == "bubble_board":
            for index, category in enumerate(self.board):
                row = index // 5
                if self.revealed[index]:
                    icon = "💰" if category == "treasure" else "⚔️"
                    button = discord.ui.Button(label="", emoji=icon, style=discord.ButtonStyle.secondary, row=row, disabled=True)
                else:
                    button = discord.ui.Button(label="?", emoji="🫧", style=discord.ButtonStyle.primary, row=row)
                    button.callback = self._make_bubble_callback(index)
                self.add_item(button)
        elif self.phase == "battle":
            # Full TeamBattleEngine action set (team_battle.py) -- same combat loop /raid
            # runs. Most battles are single-enemy (no target-select needed, every action
            # just targets self.enemies[0]) -- Crimson Formation Guardian's own fight is the
            # one exception (guardian + 2 formation nodes, see _start_battle), so the select
            # only appears when there's actually more than one enemy to choose between.
            if len(self.enemies) > 1:
                target_options = [
                    discord.SelectOption(
                        label=f"{e.monster.name} — {max(0, e.hp):.0f}/{e.max_hp:.0f} HP", value=str(idx),
                        emoji="🛡️" if idx == 0 else "🔺",
                    )
                    for idx, e in enumerate(self.enemies) if e.alive
                ]
                target_select = discord.ui.Select(
                    placeholder="Choose your target (for Attack/Guard/Gu ability)..." if target_options else "No targets left",
                    options=target_options or [discord.SelectOption(label="None", value="none")],
                    disabled=not target_options,
                    row=2,
                )
                target_select.callback = self._on_pick_target
                self.add_item(target_select)

            attack_button = discord.ui.Button(label="Attack", emoji="⚔️", style=discord.ButtonStyle.danger, row=0)
            attack_button.callback = self._on_attack
            self.add_item(attack_button)
            guard_button = discord.ui.Button(label="Guard", emoji="🛡️", style=discord.ButtonStyle.secondary, row=0)
            guard_button.callback = self._on_guard
            self.add_item(guard_button)
            empower_button = discord.ui.Button(label=f"Empower ({EMPOWER_QI_COST})", emoji="✨", style=discord.ButtonStyle.success, row=0)
            empower_button.callback = self._on_toggle_empower
            self.add_item(empower_button)
            class_button = discord.ui.Button(label="Class Ability", emoji="🎭", style=discord.ButtonStyle.success, row=0)
            class_button.callback = self._on_class_ability
            self.add_item(class_button)

            gu_button = discord.ui.Button(label="Use Gu Ability", emoji="🐛", style=discord.ButtonStyle.primary, row=1)
            gu_button.callback = self._on_gu_ability
            self.add_item(gu_button)
            killer_move_button = discord.ui.Button(label="Use Killer Move", emoji="🌀", style=discord.ButtonStyle.primary, row=1)
            killer_move_button.callback = self._on_killer_move
            self.add_item(killer_move_button)
            soul_projection_button = discord.ui.Button(
                label=f"Soul Projection ({avatar.SOUL_PROJECTION_QI_COST:,})", emoji="🌀",
                style=discord.ButtonStyle.success, row=1,
            )
            soul_projection_button.callback = self._on_soul_projection
            self.add_item(soul_projection_button)
            potion_button = discord.ui.Button(label="Use Potion/Pill", emoji="🧪", style=discord.ButtonStyle.success, row=1)
            potion_button.callback = self._on_open_potion_menu
            self.add_item(potion_button)
        elif self.phase == "pre_trial":
            button = discord.ui.Button(label="Face the Trial", emoji="⚔️", style=discord.ButtonStyle.danger)
            button.callback = self._on_face_trial
            self.add_item(button)
        elif self.phase == "betrayal":
            share_button = discord.ui.Button(label="Share Loot Equally", emoji="🤝", style=discord.ButtonStyle.success)
            share_button.callback = self._make_betrayal_callback("share")
            self.add_item(share_button)
            backstab_button = discord.ui.Button(label="Backstab for Core Gu", emoji="🗡️", style=discord.ButtonStyle.danger)
            backstab_button.callback = self._make_betrayal_callback("backstab")
            self.add_item(backstab_button)
        # "trial_result" and "resolved" phases have no buttons -- purely display states.

    # -- intro -----------------------------------------------------------------------------

    async def _on_intro_continue(self, interaction: discord.Interaction):
        self.phase = "bubble_board"
        self.board = await asyncio.to_thread(self.game.generate_inheritance_ground_board, len(self.team))
        self.revealed = [False] * len(self.board)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    # -- bubble board (turn-based -- only self.team[self.turn_index] may pop the next bubble) --

    def _make_bubble_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            current_uid, current_name = self.team[self.turn_index]
            if interaction.user.id != current_uid:
                await interaction.response.send_message(f"It's **{current_name}**'s turn to pop a bubble.", ephemeral=True)
                return
            if self.bubble_resolving or self.revealed[index]:
                await interaction.response.defer()
                return
            self.bubble_resolving = True
            # defer() first -- both branches below do real DB work (loot grants, or settling
            # HP/Qi to start a battle) that can run past Discord's 3s ack window under load,
            # same reasoning as every other bulk-write callback in this codebase.
            await interaction.response.defer()
            category = self.board[index]
            self.revealed[index] = True
            if category == "treasure":
                results = await asyncio.to_thread(self.game.grant_inheritance_ground_treasure_reward, self.ground_key, self.team)
                summary = "; ".join(f"**{name}**: {reward}" for name, reward in results)
                self.board_log.append((None, "treasure", summary))
                self._advance_turn()
                self.phase = "pre_trial" if all(self.revealed) else "bubble_board"
                self.bubble_resolving = False
                await asyncio.to_thread(self._build_components)
                embed = await asyncio.to_thread(self.build_embed)
                await interaction.edit_original_response(embed=embed, view=self)
            else:  # "battle" -- turn rotation PAUSES until the fight is actually won
                self.battles_fought += 1
                await asyncio.to_thread(self._start_battle)
                self.bubble_resolving = False
                await asyncio.to_thread(self._build_components)
                embed = await asyncio.to_thread(self.build_embed)
                await interaction.edit_original_response(embed=embed, view=self)
                self._start_battle_round_timer()

        return callback

    # -- battle (whole team fights together -- every alive member acts each round) ----------
    # asyncio.create_task (via _start_battle_round_timer) requires a running loop on the
    # CURRENT thread, so it's always called directly on the main thread, never from inside a
    # to_thread-dispatched function -- same discipline every other round timer in this
    # codebase already established (see commit 45e239a).

    def _start_battle(self):
        """Sync -- dispatched via asyncio.to_thread by its one caller above. Seeds the
        monster (scaled by battles_fought, see roll_inheritance_ground_battle_monster) and
        every team member's full combat state via TeamBattleEngine._build_participant_state
        (team_battle.py) -- the exact same seeding /raid uses, so Empower/Gu Ability/Class
        Ability/Killer Move/Soul Projection all Just Work here too. inspire_rounds_remaining
        resets per battle bubble (unlike /raid, one inheritance-ground run can fight several
        battle bubbles back to back, and a buff from a PRIOR fight shouldn't leak into the
        next one)."""
        self.phase = "battle"
        monster = self.game.roll_inheritance_ground_battle_monster(self.ground_key, self.battles_fought)
        self.enemies = [RaidEnemy(monster)]
        if monster.name == blood_sea_ancestor.CRIMSON_FORMATION_GUARDIAN.name:
            # Crimson Formation Guardian's own shield_while_ally_alive_pct only means anything
            # alongside other living enemies -- spawn its 2 formation nodes as real,
            # independently-targetable/killable extra enemies (see team_battle.py's Phase 1
            # shield dispatch, this view's own target-select in _build_components).
            self.enemies += [RaidEnemy(blood_sea_ancestor.CRIMSON_FORMATION_NODE) for _ in range(2)]
        self.participants = {}
        for uid, name in self.team:
            player = self.game.get_player_stats(uid, name)
            self.participants[uid] = self._build_participant_state(uid, name, player)
            self.game.apply_encounter_start_bonuses(uid, name)
        self.actions = {}
        self.round = 1
        self.inspire_rounds_remaining = 0
        self.log = [f"⚔️ {monster.name} blocks the way!"]

    def _apply_afk_actions(self):
        """Auto-submits a plain Attack for anyone who didn't act before the round's clock
        ran out -- mirrors raid.py's own _apply_afk_actions, minus its reward-multiplier
        penalty (inheritance ground's battle bubbles don't have their own separate loot
        multiplier concept to dock)."""
        for user_id in self._alive_participant_ids():
            if user_id in self.actions:
                continue
            p = self.participants[user_id]
            self.actions[user_id] = {"type": "attack", "target": 0, "guaranteed": False}
            self._log(f"⏱️ **{p['name']}** ran out of time and auto-attacks {self.enemies[0].monster.name}!")

    def _start_battle_round_timer(self):
        self._battle_round_epoch += 1
        asyncio.create_task(self._battle_round_timeout(self._battle_round_epoch))

    async def _battle_round_timeout(self, epoch: int):
        await asyncio.sleep(BATTLE_ROUND_TIMEOUT_SECONDS)
        if self.phase != "battle" or epoch != self._battle_round_epoch:
            return  # this round already resolved on its own (or the run ended) before this fired
        await asyncio.to_thread(self._apply_afk_actions)
        await self._finish_round()

    async def _finish_round(self):
        """Called by TeamBattleEngine._submit_action (team_battle.py) once every alive
        participant has locked in an action, and directly by _battle_round_timeout above --
        mirrors raid.py's own _finish_round shape (resolve -> rebuild -> refresh -> restart
        the round timer if the fight is still ongoing), keyed on self.phase instead of
        raid's self.status."""
        await asyncio.to_thread(self._resolve_round)
        await asyncio.to_thread(self._build_components)
        await self._refresh_message()
        if self.phase == "battle":
            self._start_battle_round_timer()

    async def _on_pick_target(self, interaction: discord.Interaction):
        """Only ever wired up when len(self.enemies) > 1 (see _build_components) -- mirrors
        raid.py's own _on_pick_target."""
        p = self.participants.get(interaction.user.id)
        if p is None:
            await interaction.response.send_message("This isn't your inheritance ground run.", ephemeral=True)
            return
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 2)
        try:
            idx = int(select.values[0])
        except ValueError:
            await interaction.response.defer()
            return
        p["target_index"] = idx
        await interaction.response.send_message(f"🎯 Targeting **{self.enemies[idx].monster.name}** for your next Attack/Guard/Gu ability.", ephemeral=True)

    def _on_victory(self):
        """Called by TeamBattleEngine._resolve_round (team_battle.py) once the guardian's HP
        hits 0 -- the "💥 ... is defeated!" log line is already added there, so this only
        handles ground-specific wrap-up: granting battle loot (see GameManager.
        grant_inheritance_ground_battle_loot -- rarity-scaled for this ground's own monster
        pool, a no-op bonus roll for anything else), then advancing the bubble-board turn and
        returning to it (or moving on to the Final Trial if the board's fully cleared)."""
        monster = self.enemies[0].monster
        loot_results = self.game.grant_inheritance_ground_battle_loot(self.ground_key, self.team, monster)
        loot_summary = "; ".join(f"**{name}**: {text}" for name, text in loot_results)
        self.board_log.append((None, "battle", f"The team defeats {monster.name}! {loot_summary}"))
        self._advance_turn()
        self.phase = "pre_trial" if all(self.revealed) else "bubble_board"

    def _on_wipe(self):
        """Called by TeamBattleEngine._resolve_round (team_battle.py) once every participant
        is down -- ends the run immediately, same stakes as a failed Final Trial, no betrayal."""
        self._log("💀 The team is overwhelmed and forced to retreat!")
        self.game.finish_inheritance_ground_run([uid for uid, _ in self.team])
        self.battle_wipe = True
        self.phase = "resolved"

    # -- final trial -------------------------------------------------------------------------

    async def _on_face_trial(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.trial_result = await asyncio.to_thread(
            self.game.resolve_inheritance_ground_trial, self.ground_key, self.team, 0.0,
        )
        if self.trial_result["success"]:
            self.phase = "betrayal"
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.edit_original_response(embed=embed, view=self)
            self._start_betrayal_timer()
        else:
            await asyncio.to_thread(self.game.finish_inheritance_ground_run, [uid for uid, _ in self.team])
            self.phase = "resolved"
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.edit_original_response(embed=embed, view=self)

    # -- betrayal ----------------------------------------------------------------------------
    # asyncio.create_task (via _start_betrayal_timer) requires a running loop on the CURRENT
    # thread, so it's always called directly on the main thread, never from inside a
    # to_thread-dispatched function -- same discipline hunt.py/raid.py/battlefield_view.py's
    # own round timers already established this session.

    def _start_betrayal_timer(self):
        self.betrayal_epoch += 1
        asyncio.create_task(self._betrayal_timeout(self.betrayal_epoch))

    async def _betrayal_timeout(self, epoch: int):
        await asyncio.sleep(BETRAYAL_DECISION_SECONDS)
        if self.phase != "betrayal" or epoch != self.betrayal_epoch:
            return
        await asyncio.to_thread(self._resolve_betrayal)
        await asyncio.to_thread(self._build_components)
        if self.message is not None:
            try:
                embed = await asyncio.to_thread(self.build_embed)
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass

    def _make_betrayal_callback(self, choice: str):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id in self.betrayal_choices:
                await interaction.response.send_message("You've already made your choice.", ephemeral=True)
                return
            self.betrayal_choices[interaction.user.id] = choice
            confirm_text = (
                "🤝 You chose to **share the loot equally**."
                if choice == "share"
                else "🗡️ You chose to **backstab** — if anyone else does too, you'll duel for the Core Gu."
            )
            await interaction.response.send_message(confirm_text, ephemeral=True)
            if len(self.betrayal_choices) >= len(self.team):
                await asyncio.to_thread(self._resolve_betrayal)
                await asyncio.to_thread(self._build_components)
                if self.message is not None:
                    try:
                        embed = await asyncio.to_thread(self.build_embed)
                        await self.message.edit(embed=embed, view=self)
                    except discord.HTTPException:
                        pass

        return callback

    def _resolve_betrayal(self):
        """Sync -- always dispatched via asyncio.to_thread by its two callers above, never
        called directly from an async context. Anyone who never clicked defaults to Share."""
        if self.phase != "betrayal":
            return  # already resolved by the other race path (click-triggered vs timeout)
        for uid, _name in self.team:
            self.betrayal_choices.setdefault(uid, "share")
        sharers = [(uid, name) for uid, name in self.team if self.betrayal_choices[uid] == "share"]
        backstabbers = [(uid, name) for uid, name in self.team if self.betrayal_choices[uid] == "backstab"]

        self.share_grants = [
            (name, self.game.grant_inheritance_ground_share_reward(self.ground_key, uid, name))
            for uid, name in sharers
        ]
        if backstabbers:
            self.betrayal_result = self.game.resolve_inheritance_ground_betrayal(backstabbers)
            gu_name = self.game.grant_inheritance_ground_bonus_gu(
                self.ground_key, self.betrayal_result["winner_user_id"], self.betrayal_result["winner_name"],
            )
            self.betrayal_result["gu_name"] = gu_name

        self.game.finish_inheritance_ground_run([uid for uid, _ in self.team])
        self.phase = "resolved"

    # -- display -----------------------------------------------------------------------------

    async def on_timeout(self):
        if self.phase == "resolved":
            return
        # Safety net -- the same "clear everyone's flag" call the betrayal path already makes,
        # covering the case where the view's own 600s idle timeout fires before betrayal ever
        # started (e.g. the team abandons mid-board / mid-battle / mid-trial-decision).
        await asyncio.to_thread(self.game.finish_inheritance_ground_run, [uid for uid, _ in self.team])
        self.phase = "resolved"
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                embed = await asyncio.to_thread(self.build_embed)
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass

    def build_embed(self) -> discord.Embed:
        """Builds this phase's embed, then points it at the run's intro image (if the ground
        has one and the file exists) so it stays visible below every phase's own content, not
        just the intro -- the actual discord.File is only ATTACHED once, at send time (see
        InheritanceGroundLobbyView._resolve/build_intro_image_file), but it physically stays
        on the message across every subsequent edit that doesn't explicitly clear attachments
        (none of this view's edit_message/message.edit calls pass attachments=), so every
        later embed just needs to keep pointing its own image at that same attachment to
        render it."""
        embed = self._build_phase_embed()
        image_path = self._ground().get("intro_image")
        if image_path and os.path.exists(image_path):
            embed.set_image(url=f"attachment://{os.path.basename(image_path)}")
        return embed

    def _build_phase_embed(self) -> discord.Embed:
        ground = self._ground()
        team_names = ", ".join(name for _, name in self.team)

        if self.phase == "intro":
            embed = discord.Embed(
                title=f"🗺️ {ground['name']}",
                description=f"_{ground['flavor']}_\n\n**Team:** {team_names}",
                color=discord.Color.dark_gold(),
            )
            embed.set_footer(text="Click Continue when the team is ready to head in.")
            return embed

        if self.phase == "bubble_board":
            current_name = self.team[self.turn_index][1]
            revealed_count = sum(self.revealed)
            embed = discord.Embed(
                title=f"🗺️ {ground['name']} — Explore the Ruins",
                description=(
                    "A field of shimmering bubbles hides the way forward — some hold treasure, "
                    "others hide a guardian ready to fight. Take turns popping one.\n\n"
                    f"**It's {current_name}'s turn.**"
                ),
                color=discord.Color.dark_gold(),
            )
            if self.board_log:
                lines = []
                for _name, kind, text in self.board_log[-6:]:
                    lines.append(f"{'💰' if kind == 'treasure' else '⚔️'} {text}")
                embed.add_field(name="So far", value="\n".join(lines)[:1024], inline=False)
            embed.set_footer(text=f"{revealed_count}/{len(self.board)} bubbles popped.")
            return embed

        if self.phase == "battle":
            monster = self.enemies[0].monster  # the "main" enemy (Formation Guardian, if this fight has adds) always sits at index 0
            enemy_lines = []
            for idx, e in enumerate(self.enemies):
                if not e.alive:
                    enemy_lines.append(f"{'🛡️' if idx == 0 else '🔺'} **{e.monster.name}** — 💀 Defeated")
                    continue
                pct = int(100 * max(0, e.hp) / e.max_hp) if e.max_hp else 0
                submerged_note = " 🌊 *Submerged*" if e.submerged_rounds_remaining > 0 else ""
                enemy_lines.append(
                    f"{'🛡️' if idx == 0 else '🔺'} **{e.monster.name}**{submerged_note} — {max(0, e.hp):,}/{e.max_hp:,} HP ({pct}%)\n`{render_bar(e.hp, e.max_hp)}`"
                )
            description = "\n".join(enemy_lines)
            if self.inspire_rounds_remaining > 0:
                description += f"\n✨ **Inspire active** — party STR/DEF boosted ({self.inspire_rounds_remaining} round(s) left)."
            embed = discord.Embed(
                title=f"⚔️ Battle {self.battles_fought} — {monster.name}",
                description=description,
                color=discord.Color.dark_red(),
            )
            lines = []
            for uid, name in self.team:
                p = self.participants.get(uid)
                if p is None:
                    continue
                pct = int(100 * max(0, p["hp"]) / p["max_hp"]) if p["max_hp"] else 0
                if p["down"]:
                    status = "💀 knocked out"
                elif uid in self.actions:
                    status = "✅ locked in"
                else:
                    status = "⏳ choosing..."
                empower_note = " • ✨ Empowered" if p.get("empowered") else ""
                soul_projection_note = (
                    f" • 🌀 Soul Projection ({p['soul_projection_rounds_remaining']})"
                    if p.get("soul_projection_rounds_remaining", 0) > 0 else ""
                )
                lines.append(
                    f"**{name}** — {max(0, p['hp']):,}/{p['max_hp']:,} HP ({pct}%) • {status}{empower_note}{soul_projection_note}\n"
                    f"`{render_bar(p['hp'], p['max_hp'])}`"
                )
            embed.add_field(name=f"🧍 Team — Round {self.round}", value="\n".join(lines)[:1024], inline=False)
            if self.log:
                embed.add_field(name="📜 Recent Combat", value="\n".join(self.log)[:1024], inline=False)
            embed.set_footer(text=f"Actions resolve once every standing member has chosen, or in {BATTLE_ROUND_TIMEOUT_SECONDS}s.")
            return embed

        if self.phase == "pre_trial":
            embed = discord.Embed(
                title=f"🗺️ {ground['name']} — {ground['guardian_name']} Awaits",
                description="The team has cleared the ruins and stands before the Final Trial.",
                color=discord.Color.dark_gold(),
            )
            embed.set_footer(text="Face the Trial when ready — there's no turning back.")
            return embed

        if self.phase == "betrayal":
            responded = len(self.betrayal_choices)
            embed = discord.Embed(
                title=f"🗺️ {ground['name']} — Trial Cleared!",
                description=(
                    f"The team breaks through {ground['guardian_name']}'s last defenses. The vault lies open.\n\n"
                    "Each member must now privately choose: **Share Loot Equally**, or **Backstab for Core Gu**.\n"
                    "Choices are ephemeral — nobody sees anyone else's pick until it's resolved."
                ),
                color=discord.Color.gold(),
            )
            embed.set_footer(text=f"{responded}/{len(self.team)} have decided — resolves once everyone has, or in {BETRAYAL_DECISION_SECONDS}s.")
            return embed

        # "resolved"
        if self.battle_wipe:
            monster_name = self.enemies[0].monster.name if self.enemies else "a guardian"
            embed = discord.Embed(
                title=f"🗺️ {ground['name']} — Overwhelmed",
                description=(
                    f"{monster_name} proves too much — the team is beaten back and forced to retreat "
                    "before ever reaching the Trial."
                ),
                color=discord.Color.dark_red(),
            )
            return embed

        if self.trial_result is not None and not self.trial_result["success"]:
            embed = discord.Embed(
                title=f"🗺️ {ground['name']} — Trial Failed",
                description=(
                    f"{ground['guardian_name']} proves too strong. The team retreats with nothing but bruises "
                    f"and a few scavenged scraps.\n\n(Team Power {self.trial_result['team_power']:.0f} vs. "
                    f"required {self.trial_result['threshold']:.0f}.)"
                ),
                color=discord.Color.dark_red(),
            )
            return embed

        lines = [f"🤝 **{name}** shares equally: {reward}" for name, reward in self.share_grants]
        if self.betrayal_result:
            if self.betrayal_result["duel"] is None:
                lines.append(f"🗡️ **{self.betrayal_result['winner_name']}** was the only backstabber and claims the {self.betrayal_result['gu_name']} outright!")
            else:
                lines.append(f"⚔️ The backstabbers turn on each other! **{self.betrayal_result['winner_name']}** wins the duel and claims the {self.betrayal_result['gu_name']}!")
                events = self.betrayal_result["duel"]["events"]
                if events:
                    lines.append("\n".join(events[-5:]))
        embed = discord.Embed(
            title=f"🗺️ {ground['name']} — Run Complete!",
            description="\n".join(lines) if lines else "The run concludes.",
            color=discord.Color.gold(),
        )
        return embed
