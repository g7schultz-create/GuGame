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
                                   own "battle" phase whenever a battle bubble is popped, and (if
                                   anyone backstabs) a real live multi-way Attack/Guard duel --
                                   every backstabber their own side, every sharer one shared side
                                   -- as its own "backstab_duel" phase.
  AbandonInheritanceGroundView -- self-service escape hatch, same shape as AbandonRaidView/
                                   AbandonDiscoveryView, shipped from day one rather than added
                                   reactively (see the raid flee bug fixed in commit 0b6b712).
"""

import asyncio
import os
import random

import discord

from . import avatar, combat, inheritance_ground_data
from .base_view import GameView
from .content.monsters import blood_sea_ancestor
from .team_battle import EMPOWER_QI_COST, GUARD_DAMAGE_REDUCTION, RaidEnemy, TeamBattleEngine
from .ui_utils import render_bar

BETRAYAL_DECISION_SECONDS = 60
BATTLE_ROUND_TIMEOUT_SECONDS = 30  # matches raid.ROUND_TIMEOUT_SECONDS's own pacing
DUEL_ROUND_TIMEOUT_SECONDS = 30  # matches BATTLE_ROUND_TIMEOUT_SECONDS's own pacing
SHARER_SIDE = "sharers"  # the one shared duel "side" every Share-choosing member belongs to

BUBBLE_ICON = {"treasure": "💰", "battle": "⚔️", "nothing": "💨", "ascension_pill": "💊"}


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
        # Only the MOST RECENT bubble result -- replaced, never appended, so old notifications
        # disappear on the very next turn instead of piling up in a growing "So far" history.
        self.last_bubble_notice: str = None
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
        # True only while the CURRENT battle is the Final Trial's own boss fight (see
        # _start_final_boss_battle/_on_face_trial) rather than a bubble-board battle bubble --
        # _on_victory branches on this to decide what winning actually leads to.
        self.is_final_boss_battle = False

        self.betrayal_choices: dict = {}
        self.betrayal_epoch = 0
        self.share_grants: list = []
        self.betrayal_result: dict = None

        # Backstab duel (1+ backstabbers) -- a real, live, turn-based Attack/Guard multi-way
        # fight, resolved on the "backstab_duel" phase (see _start_backstab_duel). Every
        # backstabber is their OWN side (solo); every sharer shares ONE side (SHARER_SIDE) --
        # so a lone backstabber faces the whole sharer group, 2 backstabbers + sharers is a
        # real 3-way, and so on. Empty/zeroed until (if ever) a duel actually starts.
        self.duel_participants: dict = {}
        self.duel_actions: dict = {}
        self.duel_round = 1
        self.duel_log: list = []
        self._duel_round_epoch = 0

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
                    button = discord.ui.Button(label="", emoji=BUBBLE_ICON[category], style=discord.ButtonStyle.secondary, row=row, disabled=True)
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
                        label=f"{e.monster.name} — {max(0, e.hp):,.0f}/{e.max_hp:,.0f} HP", value=str(idx),
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
        elif self.phase == "backstab_duel":
            # Attack/Guard only, auto-targeted at a random living duelist on a different side
            # -- see _resolve_duel_round. No target-select: the request was "clicks
            # Attack/Guard", not a full manual-targeting FFA.
            attack_button = discord.ui.Button(label="Attack", emoji="⚔️", style=discord.ButtonStyle.danger)
            attack_button.callback = self._on_duel_attack
            self.add_item(attack_button)
            guard_button = discord.ui.Button(label="Guard", emoji="🛡️", style=discord.ButtonStyle.secondary)
            guard_button.callback = self._on_duel_guard
            self.add_item(guard_button)
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
            # defer() first -- every branch below does real DB work (loot grants, or settling
            # HP/Qi to start a battle) that can run past Discord's 3s ack window under load,
            # same reasoning as every other bulk-write callback in this codebase.
            await interaction.response.defer()
            category = self.board[index]
            self.revealed[index] = True
            if category == "battle":  # turn rotation PAUSES until the fight is actually won
                self.last_bubble_notice = None
                self.battles_fought += 1
                await asyncio.to_thread(self._start_battle)
                self.bubble_resolving = False
                await asyncio.to_thread(self._build_components)
                embed = await asyncio.to_thread(self.build_embed)
                await interaction.edit_original_response(embed=embed, view=self)
                self._start_battle_round_timer()
                return

            if category == "treasure":
                results = await asyncio.to_thread(self.game.grant_inheritance_ground_treasure_reward, self.ground_key, self.team)
                summary = "; ".join(f"**{name}**: {reward}" for name, reward in results)
                self.last_bubble_notice = f"💰 {summary}"
            elif category == "ascension_pill":
                results = await asyncio.to_thread(self.game.grant_inheritance_ground_pill_reward, self.team)
                summary = "; ".join(f"**{name}**: {reward}" for name, reward in results)
                self.last_bubble_notice = f"💊 The bubble held a stash of Qi Ascension Pills! {summary}"
            else:  # "nothing" -- a dud, matching BUBBLE_OUTCOME_WEIGHT's own possible outcomes
                self.last_bubble_notice = "💨 Just an empty bubble. Nothing here."
            self._advance_turn()
            self.phase = "pre_trial" if all(self.revealed) else "bubble_board"
            self.bubble_resolving = False
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.edit_original_response(embed=embed, view=self)

        return callback

    # -- battle (whole team fights together -- every alive member acts each round) ----------
    # asyncio.create_task (via _start_battle_round_timer) requires a running loop on the
    # CURRENT thread, so it's always called directly on the main thread, never from inside a
    # to_thread-dispatched function -- same discipline every other round timer in this
    # codebase already established (see commit 45e239a).

    def _begin_battle(self, monster):
        """Sync -- dispatched via asyncio.to_thread by its two callers below (a bubble-board
        battle bubble, or the Final Trial's own boss fight). Seeds every team member's full
        combat state via TeamBattleEngine._build_participant_state (team_battle.py) -- the
        exact same seeding /raid uses, so Empower/Gu Ability/Class Ability/Killer Move/Soul
        Projection all Just Work here too. inspire_rounds_remaining resets per battle (one
        inheritance-ground run can fight several battles back to back, and a buff from a
        PRIOR one shouldn't leak into the next)."""
        self.phase = "battle"
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

    def _start_battle(self):
        """A bubble-board battle bubble (see _make_bubble_callback)."""
        self.is_final_boss_battle = False
        monster = self.game.roll_inheritance_ground_battle_monster(self.ground_key, self.battles_fought)
        self._begin_battle(monster)

    def _start_final_boss_battle(self):
        """The Final Trial's own boss fight (see _on_face_trial) -- replaces the old pure
        power-vs-threshold check with a real fight against the Blood Sea Demon Disciple (99%)
        or the true Blood Sea Ancestor's Blood Will (1%, see GameManager.
        roll_inheritance_ground_final_boss)."""
        self.is_final_boss_battle = True
        monster = self.game.roll_inheritance_ground_final_boss(self.ground_key)
        self._begin_battle(monster)

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
        raid's self.status. Also the ONE place that notices a Final Trial boss victory just
        moved the phase straight to "betrayal" (see _on_victory) and starts its timer --
        asyncio.create_task needs a running loop on the CURRENT (main) thread, and this
        method's own to_thread calls have already returned by the time this check runs, so
        it's safe here the same way _start_battle_round_timer already relies on being called
        from a real async context, never from inside a to_thread-dispatched function."""
        phase_before = self.phase
        await asyncio.to_thread(self._resolve_round)
        await asyncio.to_thread(self._build_components)
        await self._refresh_message()
        if self.phase == "battle":
            self._start_battle_round_timer()
        elif self.phase == "betrayal" and phase_before != "betrayal":
            self._start_betrayal_timer()

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
        """Called by TeamBattleEngine._resolve_round (team_battle.py) once every enemy's HP
        hits 0 -- the "💥 ... is defeated!" log line is already added there, so this only
        handles ground-specific wrap-up. Battle loot (GameManager.
        grant_inheritance_ground_battle_loot -- rarity-scaled for this ground's own monster
        pool) is granted either way; what happens AFTER differs:
          - a bubble-board battle bubble: advance the turn and return to the board (or move
            on to the Final Trial if the board's fully cleared).
          - the Final Trial's own boss fight (self.is_final_boss_battle): go straight to the
            betrayal stage -- there's no separate math check anymore, beating the boss IS
            clearing the trial. _finish_round (the only caller reachable from a real async
            context) notices this phase land on "betrayal" and starts its timer."""
        monster = self.enemies[0].monster
        loot_results = self.game.grant_inheritance_ground_battle_loot(self.ground_key, self.team, monster)
        loot_summary = "; ".join(f"**{name}**: {text}" for name, text in loot_results)
        if self.is_final_boss_battle:
            self._log(f"🏆 The team brings down {monster.name}! {loot_summary}")
            self.phase = "betrayal"
            return
        self.last_bubble_notice = f"⚔️ The team defeats {monster.name}! {loot_summary}"
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
        """Starts a real fight against the Final Trial's boss (see
        _start_final_boss_battle) instead of the old pure power-vs-threshold check --
        beating it moves straight to betrayal (see _on_victory), losing the whole team ends
        the run immediately (see _on_wipe), exactly like a bubble-board battle bubble."""
        await interaction.response.defer()
        await asyncio.to_thread(self._start_final_boss_battle)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.edit_original_response(embed=embed, view=self)
        self._start_battle_round_timer()

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
        await self._finish_betrayal_resolution()

    def _make_betrayal_callback(self, choice: str):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id in self.betrayal_choices:
                await interaction.response.send_message("You've already made your choice.", ephemeral=True)
                return
            self.betrayal_choices[interaction.user.id] = choice
            confirm_text = (
                "🤝 You chose to **share the loot equally** (guaranteed either way) — if anyone backstabs, you'll also have to fight them for the bonus Core Gu."
                if choice == "share"
                else "🗡️ You chose to **backstab** — you'll have to fight whoever shared for the Core Gu."
            )
            await interaction.response.send_message(confirm_text, ephemeral=True)
            if len(self.betrayal_choices) >= len(self.team):
                await self._finish_betrayal_resolution()

        return callback

    async def _finish_betrayal_resolution(self):
        """Shared by both race paths that can conclude the betrayal vote (everyone clicked,
        or the timer ran out) -- resolves, rebuilds, refreshes, and -- since resolving can
        land the phase on "backstab_duel" instead of "resolved" (anyone backstabbed) -- starts
        that duel's own round timer. asyncio.create_task (via _start_duel_round_timer) needs
        a running loop on the CURRENT thread, so that check has to happen here in real async
        context, never inside the to_thread-dispatched _resolve_betrayal itself -- same
        discipline _finish_round already established for the betrayal timer itself."""
        await asyncio.to_thread(self._resolve_betrayal)
        await asyncio.to_thread(self._build_components)
        if self.message is not None:
            try:
                embed = await asyncio.to_thread(self.build_embed)
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass
        if self.phase == "backstab_duel":
            self._start_duel_round_timer()

    def _resolve_betrayal(self):
        """Sync -- always dispatched via asyncio.to_thread by _finish_betrayal_resolution,
        never called directly from an async context. Anyone who never clicked defaults to
        Share. Sharers ALWAYS get their share reward, whether or not anyone backstabbed --
        the duel below is only ever a fight over the extra Core Gu prize. 0 backstabbers
        resolves (and finishes the run) immediately; 1+ instead kicks off a real live duel
        (see _start_backstab_duel) between every backstabber (each their own side) and the
        sharers (one combined side) -- the run doesn't finish until THAT concludes (see
        _finish_backstab_duel)."""
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
            self._start_backstab_duel(backstabbers, sharers)
            return

        self.game.finish_inheritance_ground_run([uid for uid, _ in self.team])
        self.phase = "resolved"

    # -- backstab duel (anyone backstabs -- a real live multi-way Attack/Guard fight, not a
    # simulation) -- every backstabber is their OWN side, every sharer shares SHARER_SIDE, so a
    # lone backstabber faces the whole sharer group, 2 backstabbers + sharers is a real 3-way,
    # and so on. asyncio.create_task (via _start_duel_round_timer) requires a running loop on
    # the CURRENT thread, so it's always called directly on the main thread, never from inside
    # a to_thread-dispatched function -- same discipline every other round timer in this view
    # already established (see _start_battle_round_timer's own comment).

    def _duel_combat_stats(self, user_id: int) -> dict:
        """Base + equipped-gear stats only (no Empower/Gu Ability/physique traits/etc.) --
        the duel's scope is deliberately just Attack/Guard, mirroring pvp_view.py's own
        _player_combat_stats shape."""
        player = self.game.get_player_stats(user_id, self.duel_participants[user_id]["name"])
        bonuses = self.game.compute_equipment_bonuses(user_id)["stats"]
        return {
            "atk_stat": player["atk_stat"] + bonuses["atk_stat"],
            "str_stat": player["str_stat"] + bonuses["str_stat"],
            "def_stat": player["def_stat"] + bonuses["def_stat"],
            "spd_stat": player["spd_stat"] + bonuses["spd_stat"],
            "luck_stat": player["luck_stat"] + bonuses["luck_stat"],
        }

    def _duel_alive_ids(self):
        return [uid for uid, p in self.duel_participants.items() if not p["down"]]

    def _seed_duel_participant(self, uid: int, name: str, side: str):
        """Seeds one duelist's HP from their real current HP (same equipment-overlay pattern
        _build_participant_state/pvp_view use) -- this is a real fight with real stakes, not a
        harmless /pvp-style duel, matching "back stab ... for the loot" being a genuine risk."""
        equip_bonuses = self.game.compute_equipment_bonuses(uid)["stats"]
        hp_bonus = equip_bonuses["hp"]
        hp_settled = self.game.db.settle_hp_regen(uid)
        self.duel_participants[uid] = {
            "name": name, "hp": hp_settled["hp"] + hp_bonus, "max_hp": hp_settled["max_hp"] + hp_bonus,
            "hp_bonus": hp_bonus, "down": False, "side": side,
        }

    def _start_backstab_duel(self, backstabbers: list, sharers: list):
        """Sync -- called from within _resolve_betrayal, itself always dispatched via
        asyncio.to_thread."""
        self.phase = "backstab_duel"
        self.duel_participants = {}
        for uid, name in backstabbers:
            self._seed_duel_participant(uid, name, side=uid)  # each backstabber is their own side
        for uid, name in sharers:
            self._seed_duel_participant(uid, name, side=SHARER_SIDE)
        self.duel_actions = {}
        self.duel_round = 1
        names_b = ", ".join(name for _, name in backstabbers)
        if sharers:
            names_s = ", ".join(name for _, name in sharers)
            self.duel_log = [f"🗡️ {names_b} backstab the team! {names_s} fight back to defend the loot!"]
        else:
            self.duel_log = [f"🗡️ {names_b} turn on each other for the Core Gu!"]

    def _apply_duel_afk_actions(self):
        for uid in self._duel_alive_ids():
            self.duel_actions.setdefault(uid, "attack")

    def _start_duel_round_timer(self):
        self._duel_round_epoch += 1
        asyncio.create_task(self._duel_round_timeout(self._duel_round_epoch))

    async def _duel_round_timeout(self, epoch: int):
        await asyncio.sleep(DUEL_ROUND_TIMEOUT_SECONDS)
        if self.phase != "backstab_duel" or epoch != self._duel_round_epoch:
            return
        await asyncio.to_thread(self._apply_duel_afk_actions)
        await self._finish_duel_round()

    async def _submit_duel_action(self, user_id: int, action_type: str):
        self.duel_actions[user_id] = action_type
        if set(self._duel_alive_ids()).issubset(self.duel_actions.keys()):
            await self._finish_duel_round()
        else:
            await asyncio.to_thread(self._build_components)
            await self._refresh_message()

    async def _finish_duel_round(self):
        await asyncio.to_thread(self._resolve_duel_round)
        await asyncio.to_thread(self._build_components)
        await self._refresh_message()
        if self.phase == "backstab_duel":
            self._start_duel_round_timer()

    def _resolve_duel_round(self):
        """Sync -- dispatched via asyncio.to_thread by both callers above. Every duelist who
        attacks targets a randomly-chosen living duelist on a DIFFERENT side (no manual
        targeting -- the request scope is just Attack/Guard; same-side allies, i.e. fellow
        sharers, are never attacked); guarding halves whatever damage lands on you this round.
        Ends the round once at most one SIDE still has anyone alive -- not just one person,
        since the sharer side can have several survivors."""
        alive = self._duel_alive_ids()
        attackers = [uid for uid in alive if self.duel_actions.get(uid, "attack") == "attack"]
        random.shuffle(attackers)
        for uid in attackers:
            attacker = self.duel_participants[uid]
            if attacker["down"]:
                continue
            my_side = attacker["side"]
            targets = [t for t in self._duel_alive_ids() if self.duel_participants[t]["side"] != my_side]
            if not targets:
                continue
            target_uid = random.choice(targets)
            target = self.duel_participants[target_uid]
            guarding = self.duel_actions.get(target_uid) == "guard"
            result = combat.resolve_attack(
                self._duel_combat_stats(uid), self._duel_combat_stats(target_uid),
                incoming_reduction=GUARD_DAMAGE_REDUCTION if guarding else 0.0,
            )
            if not result.hit:
                self.duel_log.append(f"⚔️ **{attacker['name']}** attacks **{target['name']}** but misses!")
            elif result.dodged:
                self.duel_log.append(f"💨 **{target['name']}** dodges **{attacker['name']}**'s attack!")
            else:
                target["hp"] = max(0, target["hp"] - result.damage)
                crit = " (Critical!)" if result.crit else ""
                guard_note = " (guarded)" if guarding else ""
                self.duel_log.append(f"⚔️ **{attacker['name']}** hits **{target['name']}** for {result.damage} damage{crit}{guard_note}.")
                if target["hp"] <= 0:
                    target["down"] = True
                    self.duel_log.append(f"💀 **{target['name']}** is knocked out of the duel!")
        self.duel_log = self.duel_log[-6:]
        self.duel_actions = {}

        still_alive = self._duel_alive_ids()
        alive_sides = {self.duel_participants[uid]["side"] for uid in still_alive}
        if len(alive_sides) <= 1:
            self._finish_backstab_duel(still_alive)
        else:
            self.duel_round += 1

    def _finish_backstab_duel(self, still_alive: list):
        """still_alive: everyone left on the winning side (could be several sharers at once,
        or a single backstabber) -- possibly empty on a mutual-KO edge case where the last
        two blows land the same round, tiebroken randomly among every original duelist rather
        than leave the Core Gu unclaimed. One random survivor claims the prize either way."""
        winner_id = random.choice(still_alive) if still_alive else random.choice(list(self.duel_participants.keys()))
        winner = self.duel_participants[winner_id]
        gu_name = self.game.grant_inheritance_ground_bonus_gu(self.ground_key, winner_id, winner["name"])
        self.betrayal_result = {
            "winner_user_id": winner_id, "winner_name": winner["name"],
            "winner_was_backstabber": winner["side"] != SHARER_SIDE,
            "duel": {"events": list(self.duel_log)}, "gu_name": gu_name,
        }
        self.game.finish_inheritance_ground_run([uid for uid, _ in self.team])
        self.phase = "resolved"

    async def _on_duel_attack(self, interaction: discord.Interaction):
        p = self.duel_participants.get(interaction.user.id)
        if p is None:
            await interaction.response.send_message("You're not part of this duel.", ephemeral=True)
            return
        if p["down"]:
            await interaction.response.send_message("You've been knocked out of the duel.", ephemeral=True)
            return
        if interaction.user.id in self.duel_actions:
            await interaction.response.send_message("You've already locked in your action for this round.", ephemeral=True)
            return
        # An ephemeral confirmation, not a silent defer() -- per explicit request, this fight
        # should feel like a real private choice (mirrors the betrayal vote's own ephemeral
        # confirmations just above), not the quiet background-refresh /raid's battle rounds use.
        await interaction.response.send_message("⚔️ You attack!", ephemeral=True)
        await self._submit_duel_action(interaction.user.id, "attack")

    async def _on_duel_guard(self, interaction: discord.Interaction):
        p = self.duel_participants.get(interaction.user.id)
        if p is None:
            await interaction.response.send_message("You're not part of this duel.", ephemeral=True)
            return
        if p["down"]:
            await interaction.response.send_message("You've been knocked out of the duel.", ephemeral=True)
            return
        if interaction.user.id in self.duel_actions:
            await interaction.response.send_message("You've already locked in your action for this round.", ephemeral=True)
            return
        await interaction.response.send_message("🛡️ You brace for the next blow.", ephemeral=True)
        await self._submit_duel_action(interaction.user.id, "guard")

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
            if self.last_bubble_notice:
                # Only the most recent result -- deliberately NOT a growing history, so it
                # disappears again once the next bubble gets popped (see last_bubble_notice's
                # own field comment in __init__).
                embed.add_field(name="Just happened", value=self.last_bubble_notice[:1024], inline=False)
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
                    f"{'🛡️' if idx == 0 else '🔺'} **{e.monster.name}**{submerged_note} — {max(0, e.hp):,.0f}/{e.max_hp:,.0f} HP ({pct}%)\n`{render_bar(e.hp, e.max_hp)}`"
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
                    f"**{name}** — {max(0, p['hp']):,.0f}/{p['max_hp']:,.0f} HP ({pct}%) • {status}{empower_note}{soul_projection_note}\n"
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
                    "Choices are ephemeral — nobody sees anyone else's pick until it's resolved. If anyone backstabs, "
                    "it comes to a real fight over the Core Gu — every backstabber alone against the sharers together."
                ),
                color=discord.Color.gold(),
            )
            embed.set_footer(text=f"{responded}/{len(self.team)} have decided — resolves once everyone has, or in {BETRAYAL_DECISION_SECONDS}s.")
            return embed

        if self.phase == "backstab_duel":
            lines = []
            for uid, p in self.duel_participants.items():
                pct = int(100 * max(0, p["hp"]) / p["max_hp"]) if p["max_hp"] else 0
                if p["down"]:
                    status = "💀 knocked out"
                elif uid in self.duel_actions:
                    status = "✅ locked in"
                else:
                    status = "⏳ choosing..."
                side_badge = "🤝" if p["side"] == SHARER_SIDE else "🗡️"
                lines.append(
                    f"{side_badge} **{p['name']}** — {max(0, p['hp']):,.0f}/{p['max_hp']:,.0f} HP ({pct}%) • {status}\n"
                    f"`{render_bar(p['hp'], p['max_hp'])}`"
                )
            embed = discord.Embed(
                title=f"🗡️ {ground['name']} — Backstab Duel!",
                description="The team turns on itself — 🗡️ each backstabber fights alone, 🤝 the sharers defend together. Only one side walks away with the Core Gu.",
                color=discord.Color.dark_red(),
            )
            embed.add_field(name=f"⚔️ Duelists — Round {self.duel_round}", value="\n".join(lines)[:1024], inline=False)
            if self.duel_log:
                embed.add_field(name="📜 Recent Combat", value="\n".join(self.duel_log)[:1024], inline=False)
            embed.set_footer(text=f"Actions resolve once every standing duelist has chosen, or in {DUEL_ROUND_TIMEOUT_SECONDS}s.")
            return embed

        # "resolved"
        if self.battle_wipe:
            monster_name = self.enemies[0].monster.name if self.enemies else "a guardian"
            if self.is_final_boss_battle:
                description = f"{monster_name} proves too much — the team is overwhelmed during the Final Trial itself and forced to retreat."
            else:
                description = f"{monster_name} proves too much — the team is beaten back and forced to retreat before ever reaching the Trial."
            embed = discord.Embed(title=f"🗺️ {ground['name']} — Overwhelmed", description=description, color=discord.Color.dark_red())
            return embed

        lines = [f"🤝 **{name}** shares equally: {reward}" for name, reward in self.share_grants]
        if self.betrayal_result:
            if self.betrayal_result["winner_was_backstabber"]:
                lines.append(f"🗡️ **{self.betrayal_result['winner_name']}** overcomes the defenders and claims the {self.betrayal_result['gu_name']}!")
            else:
                lines.append(f"🛡️ The defenders hold! **{self.betrayal_result['winner_name']}** survives the backstab and claims the {self.betrayal_result['gu_name']}!")
            events = self.betrayal_result["duel"]["events"]
            if events:
                lines.append("\n".join(events[-5:]))
        embed = discord.Embed(
            title=f"🗺️ {ground['name']} — Run Complete!",
            description="\n".join(lines) if lines else "The run concludes.",
            color=discord.Color.gold(),
        )
        return embed
