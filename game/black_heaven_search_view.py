"""
/search_black_heaven -- an INVITED team (leader + up to 3, invite-restricted to players
already present in Black Heaven, or solo) pops a shared 20-bubble board: some bubbles hide
one of Black Heaven's own 15 Gu, essence crystals, essence pills, Rank 8 materials, or
nothing; others are guarded by a real, multi-round team fight against one of Black Heaven's
own battle-bubble monsters (see content/monsters/black_heaven.py) that gets more dangerous
with every consecutive battle bubble popped. Every bubble's real contents are revealed once
the team's pops run out, whether they got there or not. Direct structural mirror of
game/inheritance_ground_view.py's own three views, stripped of the Final Trial/betrayal/
backstab-duel phases entirely -- the bubble board IS the whole content here, so the phase
model is just intro -> bubble_board -> battle (per bubble) -> resolved.

Three views:
  BlackHeavenSearchLobbyView -- invite/accept flow (leader + up to 3 invitees). The one real
                                  difference from InheritanceGroundLobbyView: every invitee
                                  must currently be black_heaven_status == "present" (checked
                                  at both invite time and accept time via GameManager.
                                  check_black_heaven_search_eligibility) -- unlike Inheritance
                                  Ground, which can invite anyone regardless of location.
  BlackHeavenSearchView       -- the run itself, mixing in TeamBattleEngine (team_battle.py)
                                  for byte-identical battle-bubble combat to /raid.
  AbandonBlackHeavenSearchView -- self-service escape hatch, shipped from day one, same shape
                                  as every other stuck-state escape hatch in this codebase.
"""

import asyncio
import os

import discord

from . import avatar, black_heaven
from .black_heaven_view import build_black_heaven_image_file
from .base_view import GameView
from .team_battle import EMPOWER_QI_COST, RaidEnemy, TeamBattleEngine
from .ui_utils import format_number, render_bar

BATTLE_ROUND_TIMEOUT_SECONDS = 30  # matches raid.ROUND_TIMEOUT_SECONDS's own pacing

BUBBLE_ICON = {
    "gu": "🐛", "battle": "⚔️", "nothing": "💨",
    "essence_crystal": "💎", "essence_pill": "🧪", "materials": "⛏️", "ascension_pill": "💊",
    "immortal_notes": "📜",
}


class AbandonBlackHeavenSearchView(GameView):
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
        await asyncio.to_thread(self.game.abandon_active_black_heaven_search, self.user_id)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="🗑️ Cleared — you can `/search_black_heaven` again now.", view=self)


class BlackHeavenSearchLobbyView(GameView):
    """leader + invitees (2 required, 1 optional) -- direct mirror of
    InheritanceGroundLobbyView's own accept/decline shape, plus one real addition: every
    invitee must currently be present in Black Heaven (re-checked fresh at accept time, not
    just invite time, since up to 5 minutes can pass)."""

    def __init__(self, game, leader: discord.Member, invitees: list):
        super().__init__(timeout=300)
        self.game = game
        self.leader = leader
        self.invitees = invitees
        self.responses = {m.id: "pending" for m in invitees}
        self.resolved = False
        self.message: discord.Message = None
        self._build_components()

    def _required_ids(self):
        return {m.id for m in self.invitees[:2]}

    def _decided(self) -> bool:
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
        cancel_button = discord.ui.Button(label="Cancel Invite", emoji="🚫", style=discord.ButtonStyle.secondary)
        cancel_button.callback = self._on_cancel
        self.add_item(cancel_button)

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
        # Re-checked fresh here (not trusted from invite time) -- "you" phrasing since this is
        # the clicking player's own eligibility, unlike cog.py's invite-time check which is
        # third-person about an invitee.
        ok, reason_code, _remaining = await asyncio.to_thread(self.game.check_black_heaven_search_eligibility, interaction.user.id, interaction.user.display_name)
        if not ok:
            messages = {
                "not_confirmed": "You need to `/join` and confirm a character first.",
                "already_active": "You're already in another Search Black Heaven run — finish or abandon it first.",
                "not_present": "You're not currently in Black Heaven, so you can't join this Search.",
            }
            await interaction.response.send_message(messages[reason_code], ephemeral=True)
            return
        await self._respond(interaction, "accepted")

    async def _on_decline(self, interaction: discord.Interaction):
        await self._respond(interaction, "declined")

    async def _on_cancel(self, interaction: discord.Interaction):
        """Leader-only -- lets the leader free up their one-pending-invite slot (see
        GameManager.has_pending_black_heaven_search_invite) without waiting out the full 5min
        timeout or badgering invitees into declining."""
        if interaction.user.id != self.leader.id:
            await interaction.response.send_message("Only the leader can cancel this invite.", ephemeral=True)
            return
        if self.resolved:
            await interaction.response.defer()
            return
        self.resolved = True
        await asyncio.to_thread(self.game.clear_black_heaven_search_invite_pending, self.leader.id)
        await asyncio.to_thread(self._build_components)
        embed = discord.Embed(
            title="🌑 Search Black Heaven — Invite Cancelled",
            description=f"**{self.leader.display_name}** cancelled this invite.",
            color=discord.Color.dark_grey(),
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def _resolve(self, interaction: discord.Interaction):
        self.resolved = True
        await asyncio.to_thread(self.game.clear_black_heaven_search_invite_pending, self.leader.id)
        await asyncio.to_thread(self._build_components)
        required_ok = all(self.responses[uid] == "accepted" for uid in self._required_ids())
        if not required_ok:
            declined = [m.display_name for m in self.invitees if self.responses[m.id] == "declined"]
            embed = discord.Embed(
                title="🌑 Search Black Heaven — Team Didn't Form",
                description=f"Not enough of the invited team accepted (declined: {', '.join(declined) or 'no response in time'}).",
                color=discord.Color.dark_grey(),
            )
            await interaction.response.edit_message(embed=embed, view=self)
            return
        team_members = [self.leader] + [m for m in self.invitees if self.responses.get(m.id) == "accepted"]
        team = [(m.id, m.display_name) for m in team_members]
        # Direct construction, NOT via asyncio.to_thread -- discord.py's own View.__init__
        # binds an internal dispatch Future via asyncio.get_running_loop(); a to_thread worker
        # thread has no running loop, so that Future silently ends up unusable and every
        # future button click on the view is dropped. Hard rule for every View/Modal in this
        # codebase (see commit 45e239a).
        run_view = BlackHeavenSearchView(self.game, team)
        await asyncio.to_thread(self.game.start_active_black_heaven_search, [uid for uid, _ in team])
        embed = await asyncio.to_thread(run_view.build_embed)
        # The lobby's own invite embed never shows the shared image (mirrors Inheritance
        # Ground's identical choice) -- it's only attached once the run actually starts here.
        file = await asyncio.to_thread(build_black_heaven_image_file)
        if file:
            await interaction.response.edit_message(embed=embed, view=run_view, attachments=[file])
        else:
            await interaction.response.edit_message(embed=embed, view=run_view)
        run_view.message = await interaction.original_response()

    async def on_timeout(self):
        if self.resolved:
            return
        self.resolved = True
        await asyncio.to_thread(self.game.clear_black_heaven_search_invite_pending, self.leader.id)
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
        status_emoji = {"pending": "⏳", "accepted": "✅", "declined": "❌"}
        lines = [f"🧍 **{self.leader.display_name}** (leader) ✅"]
        for m in self.invitees:
            optional_tag = " _(optional)_" if m not in self.invitees[:2] else ""
            lines.append(f"🧍 **{m.display_name}**{optional_tag} {status_emoji[self.responses[m.id]]}")
        embed = discord.Embed(
            title="🌑 Search Black Heaven",
            description=(
                "_Twenty bubbles wait in the starless dark. Some hold something incredible. "
                "Some hold something that will kill you._\n\n" + "\n".join(lines)
            ),
            color=discord.Color.dark_purple(),
        )
        embed.set_footer(text="Both required invitees must Accept to begin. The leader can Cancel. Expires in 5 min.")
        return embed


class BlackHeavenSearchView(TeamBattleEngine, GameView):
    def __init__(self, game, team: list):
        super().__init__(timeout=600)
        self.game = game
        self.team = team  # [(user_id, name), ...], team[0] is always the leader
        self.leader_id = team[0][0]
        self.phase = "intro"

        self.board: list = []
        self.revealed: list = []
        self.actually_clicked: list = []
        self.board_exhausted = False
        self.turn_index = 0
        self.last_bubble_notice: str = None
        self.gu_roll_result: dict = None  # set once the "gu" bubble is popped -- see grant_black_heaven_gu_reward
        self.bubble_resolving = False
        self.battles_fought = 0  # feeds roll_black_heaven_battle_monster's own scaling

        # "battle" phase state (see TeamBattleEngine, team_battle.py) -- populated by
        # _start_battle whenever a battle bubble is popped. Always exactly one enemy (Black
        # Heaven's own roster has no Formation-Guardian-style multi-add fight), so
        # _build_components never needs a target-select.
        self.enemies: list = []
        self.participants: dict = {}
        self.actions: dict = {}
        self.round = 1
        self.log: list = []
        self.inspire_rounds_remaining = 0
        self.battle_wipe = False  # True once a battle ends the run early (team wiped)
        self._battle_round_epoch = 0

        self.message: discord.Message = None
        self._build_components()

    def _team_ids(self):
        return {uid for uid, _ in self.team}

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self._team_ids():
            await interaction.response.send_message("This isn't your Search Black Heaven run.", ephemeral=True)
            return False
        return True

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
                    missed = self.board_exhausted and not self.actually_clicked[index]
                    button = discord.ui.Button(label="Missed" if missed else "", emoji=BUBBLE_ICON[category], style=discord.ButtonStyle.secondary, row=row, disabled=True)
                else:
                    button = discord.ui.Button(label="?", emoji="🫧", style=discord.ButtonStyle.primary, row=row)
                    button.callback = self._make_bubble_callback(index)
                self.add_item(button)
            if self.board_exhausted:
                continue_button = discord.ui.Button(label="Continue", emoji="➡️", style=discord.ButtonStyle.primary, row=4)
                continue_button.callback = self._on_bubble_board_continue
                self.add_item(continue_button)
        elif self.phase == "battle":
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
                label=f"Soul Projection ({format_number(avatar.SOUL_PROJECTION_QI_COST)})", emoji="🌀",
                style=discord.ButtonStyle.success, row=1,
            )
            soul_projection_button.callback = self._on_soul_projection
            self.add_item(soul_projection_button)
            potion_button = discord.ui.Button(label="Use Potion/Pill", emoji="🧪", style=discord.ButtonStyle.success, row=1)
            potion_button.callback = self._on_open_potion_menu
            self.add_item(potion_button)
        # "resolved" has no buttons -- purely a display state.

    # -- intro -----------------------------------------------------------------------------

    async def _on_intro_continue(self, interaction: discord.Interaction):
        self.phase = "bubble_board"
        self.board = await asyncio.to_thread(self.game.generate_black_heaven_board, len(self.team))
        self.revealed = [False] * len(self.board)
        self.actually_clicked = [False] * len(self.board)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    # -- bubble board (turn-based -- only self.team[self.turn_index] may pop the next bubble) --

    def _max_bubble_pops(self) -> int:
        return self.game.max_black_heaven_pops(len(self.team))

    def _reveal_remaining_bubbles(self):
        self.board_exhausted = True
        self.revealed = [True] * len(self.board)

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
            await interaction.response.defer()
            category = self.board[index]
            self.revealed[index] = True
            self.actually_clicked[index] = True
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

            if category == "gu":
                self.gu_roll_result = await asyncio.to_thread(self.game.grant_black_heaven_gu_reward, self.team)
                self.last_bubble_notice = f"🐛 **A rare Gu!** The whole team rolls for it:\n{self._gu_roll_field_text()}"
            elif category == "essence_crystal":
                results = await asyncio.to_thread(self.game.grant_black_heaven_essence_crystal_reward, self.team)
                summary = "\n".join(f"**{name}**: {reward}" for name, reward in results)
                self.last_bubble_notice = f"💎 The bubble held a cache of Primeval Essence Crystals!\n{summary}"
            elif category == "essence_pill":
                results = await asyncio.to_thread(self.game.grant_black_heaven_essence_pill_reward, self.team)
                summary = "\n".join(f"**{name}**: {reward}" for name, reward in results)
                self.last_bubble_notice = f"🧪 The bubble held a stash of Essence Restoration Pills!\n{summary}"
            elif category == "materials":
                results = await asyncio.to_thread(self.game.grant_black_heaven_material_reward, self.team)
                summary = "\n".join(f"**{name}**: {reward}" for name, reward in results)
                self.last_bubble_notice = f"⛏️ The bubble held a cache of Rank 8 materials!\n{summary}"
            elif category == "ascension_pill":
                results = await asyncio.to_thread(self.game.grant_black_heaven_pill_reward, self.team)
                summary = "\n".join(f"**{name}**: {reward}" for name, reward in results)
                self.last_bubble_notice = f"💊 The bubble held a stash of Qi Ascension Pills!\n{summary}"
            elif category == "immortal_notes":
                results = await asyncio.to_thread(self.game.grant_black_heaven_immortal_notes_reward, self.team)
                summary = "\n".join(f"**{name}**: {reward}" for name, reward in results)
                self.last_bubble_notice = f"📜 The bubble held a bundle of Immortal Notes!\n{summary}"
            else:  # "nothing"
                self.last_bubble_notice = "💨 Just an empty bubble. Nothing here."
            if sum(self.actually_clicked) >= self._max_bubble_pops():
                self._reveal_remaining_bubbles()
            else:
                self._advance_turn()
            self.bubble_resolving = False
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.edit_original_response(embed=embed, view=self)

        return callback

    async def _on_bubble_board_continue(self, interaction: discord.Interaction):
        """Only shown once board_exhausted -- the bubble board IS the whole run, so this just
        ends it (unlike Inheritance Ground's own Continue, which moves on to a Final Trial)."""
        await asyncio.to_thread(self.game.finish_black_heaven_search_run, [uid for uid, _ in self.team], self.leader_id)
        self.phase = "resolved"
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    # -- battle (whole team fights together -- every alive member acts each round) ----------
    # asyncio.create_task (via _start_battle_round_timer) requires a running loop on the
    # CURRENT thread, so it's always called directly on the main thread, never from inside a
    # to_thread-dispatched function -- same discipline every other round timer in this
    # codebase already established (see commit 45e239a).

    def _start_battle(self):
        """Sync -- dispatched via asyncio.to_thread by its caller. Seeds every team member's
        full combat state via TeamBattleEngine._build_participant_state (team_battle.py) --
        the exact same seeding /raid uses, so Empower/Gu Ability/Class Ability/Killer Move/
        Soul Projection all Just Work here too."""
        monster = self.game.roll_black_heaven_battle_monster(self.battles_fought)
        self.phase = "battle"
        self.enemies = [RaidEnemy(monster)]
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
        """Auto-submits a plain Attack for anyone who didn't act before the round's clock ran
        out -- mirrors InheritanceGroundView's own identical helper."""
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
        participant has locked in an action, and directly by _battle_round_timeout above."""
        await asyncio.to_thread(self._resolve_round)
        await asyncio.to_thread(self._build_components)
        await self._refresh_message()
        if self.phase == "battle":
            self._start_battle_round_timer()

    def _on_victory(self):
        """Called by TeamBattleEngine._resolve_round (team_battle.py) once the enemy's HP
        hits 0 -- grants battle loot, then returns to the board (or reveals it as exhausted
        if this fight used up the team's last pop)."""
        monster = self.enemies[0].monster
        loot_results = self.game.grant_black_heaven_battle_loot(self.team, monster)
        loot_summary = "\n".join(f"**{name}**: {text}" for name, text in loot_results)
        self.last_bubble_notice = f"⚔️ The team defeats {monster.name}!\n{loot_summary}"
        if sum(self.actually_clicked) >= self._max_bubble_pops():
            self._reveal_remaining_bubbles()
        else:
            self._advance_turn()
        self.phase = "bubble_board"

    def _on_wipe(self):
        """Called by TeamBattleEngine._resolve_round (team_battle.py) once every participant
        is down -- ends the run immediately, same real stakes as Inheritance Ground's own
        battle-bubble wipe."""
        self._log("💀 The team is overwhelmed and forced to retreat!")
        self.game.finish_black_heaven_search_run([uid for uid, _ in self.team], self.leader_id)
        self.battle_wipe = True
        self.phase = "resolved"

    # -- display -----------------------------------------------------------------------------

    async def on_timeout(self):
        if self.phase == "resolved":
            return
        # Safety net -- covers the view's own 600s idle timeout firing before the run reached
        # a natural terminal state (e.g. the team abandons mid-board/mid-battle).
        await asyncio.to_thread(self.game.finish_black_heaven_search_run, [uid for uid, _ in self.team], self.leader_id)
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
        """Builds this phase's embed, then points it at the shared Black Heaven image (if the
        file exists) so it stays visible below every phase's own content -- the actual
        discord.File is only ATTACHED once, at send time (see cog.py's /search_black_heaven),
        but it physically stays on the message across every subsequent edit that doesn't
        explicitly clear attachments (none of this view's edit_message/message.edit calls do),
        so every later embed just needs to keep pointing at that same attachment to render it
        (mirrors hunt.py/raid.py's identical White Heaven convention)."""
        embed = self._build_phase_embed()
        if os.path.exists(black_heaven.BLACK_HEAVEN_IMAGE_PATH):
            embed.set_image(url=f"attachment://{os.path.basename(black_heaven.BLACK_HEAVEN_IMAGE_PATH)}")
        return embed

    def _gu_roll_field_text(self) -> str:
        """Shared by both the bubble-board-exhausted embed and the final "resolved" embed --
        see grant_black_heaven_gu_reward (manager.py) for what's actually in gu_roll_result."""
        roll_lines = "\n".join(
            f"🎲 **{name}**: {roll}" + (" 🏆" if name == self.gu_roll_result["winner_name"] and roll == self.gu_roll_result["winner_roll"] else "")
            for name, roll in self.gu_roll_result["rolls"]
        )
        return (
            f"**{self.gu_roll_result['gu_name']}** — _{self.gu_roll_result['effect_text']}_\n"
            f"{roll_lines}\n"
            f"🏆 **{self.gu_roll_result['winner_name']}** wins with a **{self.gu_roll_result['winner_roll']}** and claims it!"
        )

    def _build_phase_embed(self) -> discord.Embed:
        team_names = ", ".join(name for _, name in self.team)

        if self.phase == "intro":
            embed = discord.Embed(
                title="🌑 Search Black Heaven",
                description=(
                    "_Twenty bubbles wait in the starless dark. Some hold something incredible. "
                    f"Some hold something that will kill you._\n\n**Team:** {team_names}"
                ),
                color=discord.Color.dark_purple(),
            )
            embed.set_footer(text="Click Continue when the team is ready.")
            return embed

        if self.phase == "bubble_board":
            max_pops = self._max_bubble_pops()
            pops_used = sum(self.actually_clicked)
            if self.board_exhausted:
                if self.gu_roll_result:
                    gu_line = (
                        f"🐛 Your team found **{self.gu_roll_result['gu_name']}**! "
                        f"_{self.gu_roll_result['effect_text']}_\n"
                        f"🏆 **{self.gu_roll_result['winner_name']}** won the roll-off with a **{self.gu_roll_result['winner_roll']}** and claims it."
                    )
                else:
                    gu_line = "🐛 The Gu was hidden in one of the bubbles your team never got to — it's gone unclaimed."
                embed = discord.Embed(
                    title="🌑 Search Black Heaven — The Dark Falls Silent",
                    description=(
                        f"Your team has used all {max_pops} of its turns here. The rest of the "
                        f"bubbles pop open on their own, revealing what they held.\n\n{gu_line}"
                    ),
                    color=discord.Color.dark_purple(),
                )
                if self.last_bubble_notice:
                    embed.add_field(name="Last thing your team actually found", value=self.last_bubble_notice[:1024], inline=False)
                embed.set_footer(text=f"{pops_used}/{max_pops} bubbles explored, {len(self.board)} shown. Click Continue when ready.")
                return embed

            current_name = self.team[self.turn_index][1]
            embed = discord.Embed(
                title="🌑 Search Black Heaven",
                description=(
                    "A field of bubbles hides in the dark — some hold something incredible, "
                    "others hide something that could kill you. Take turns popping one.\n\n"
                    f"**It's {current_name}'s turn.**"
                ),
                color=discord.Color.dark_purple(),
            )
            if self.last_bubble_notice:
                embed.add_field(name="Just happened", value=self.last_bubble_notice[:1024], inline=False)
            embed.set_footer(text=f"{pops_used}/{max_pops} turns used — {len(self.board)} bubbles hidden here.")
            return embed

        if self.phase == "battle":
            enemy = self.enemies[0]
            pct = int(100 * max(0, enemy.hp) / enemy.max_hp) if enemy.max_hp else 0
            description = f"⚔️ **{enemy.monster.name}** — {format_number(max(0, enemy.hp), decimals=0)}/{format_number(enemy.max_hp, decimals=0)} HP ({pct}%)\n`{render_bar(enemy.hp, enemy.max_hp)}`"
            if self.inspire_rounds_remaining > 0:
                description += f"\n✨ **Inspire active** — party STR/DEF boosted ({self.inspire_rounds_remaining} round(s) left)."
            embed = discord.Embed(
                title=f"⚔️ Battle {self.battles_fought} — {enemy.monster.name}",
                description=description,
                color=discord.Color.dark_red(),
            )
            lines = []
            for uid, name in self.team:
                p = self.participants.get(uid)
                if p is None:
                    continue
                p_pct = int(100 * max(0, p["hp"]) / p["max_hp"]) if p["max_hp"] else 0
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
                    f"**{name}** — {format_number(max(0, p['hp']), decimals=0)}/{format_number(p['max_hp'], decimals=0)} HP ({p_pct}%) • {status}{empower_note}{soul_projection_note}\n"
                    f"`{render_bar(p['hp'], p['max_hp'])}`"
                )
            embed.add_field(name=f"🧍 Team — Round {self.round}", value="\n".join(lines)[:1024], inline=False)
            if self.log:
                embed.add_field(name="📜 Recent Combat", value="\n".join(self.log)[:1024], inline=False)
            embed.set_footer(text=f"Actions resolve once every standing member has chosen, or in {BATTLE_ROUND_TIMEOUT_SECONDS}s.")
            return embed

        # "resolved"
        if self.battle_wipe:
            monster_name = self.enemies[0].monster.name if self.enemies else "a guardian"
            embed = discord.Embed(
                title="🌑 Search Black Heaven — Overwhelmed",
                description=f"{monster_name} proves too much — the team is beaten back and forced to retreat.",
                color=discord.Color.dark_red(),
            )
            qi_lines = [f"**{p['name']}**: {format_number(p.get('qi_lost_on_death', 0))} qi lost" for p in self.participants.values()]
            if qi_lines:
                embed.add_field(name="💀 Qi Lost", value="\n".join(qi_lines)[:1024], inline=False)
            if self.gu_roll_result:
                embed.add_field(name="🐛 Gu Found Before the Wipe", value=self._gu_roll_field_text()[:1024], inline=False)
            return embed

        gu_line = (
            f"🐛 Your team walks out with **{self.gu_roll_result['gu_name']}**."
            if self.gu_roll_result else
            "🐛 The Gu bubble went unclaimed this run."
        )
        embed = discord.Embed(
            title="🌑 Search Black Heaven — Concluded",
            description=f"Your team makes it back out of the dark.\n\n{gu_line}",
            color=discord.Color.dark_purple(),
        )
        if self.gu_roll_result:
            embed.add_field(name="🐛 Gu Roll-Off", value=self._gu_roll_field_text()[:1024], inline=False)
        return embed
