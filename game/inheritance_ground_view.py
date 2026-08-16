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
from typing import Optional

import discord

from . import avatar, chargen, combat, inheritance_ground_data
from .base_view import GameView
from .content.monsters import blood_sea_ancestor
from .team_battle import (
    AllyPickerView, DEFEND_ALLY_DAMAGE_REDUCTION, EMPOWER_QI_COST, FREEZE_PROC_CHANCE,
    FREEZE_STR_MULTIPLIER, GUARD_DAMAGE_REDUCTION, INSPIRE_DEF_BONUS_PCT, INSPIRE_DURATION_ROUNDS,
    INSPIRE_STR_BONUS_PCT, RaidEnemy, TeamBattleEngine,
)
from .ui_utils import format_number, render_bar

BETRAYAL_DECISION_SECONDS = 60
BATTLE_ROUND_TIMEOUT_SECONDS = 30  # matches raid.ROUND_TIMEOUT_SECONDS's own pacing
DUEL_ROUND_TIMEOUT_SECONDS = 30  # matches BATTLE_ROUND_TIMEOUT_SECONDS's own pacing
SHARER_SIDE = "sharers"  # the one shared duel "side" every Share-choosing member belongs to

BUBBLE_ICON = {
    "treasure": "💰", "battle": "⚔️", "nothing": "💨", "ascension_pill": "💊",
    "essence_crystal": "💎", "essence_pill": "🧪", "materials": "🌿", "immortal_notes": "📜",
}


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
        # team[0] is always the leader -- either the solo team of exactly one (cog.py) or
        # InheritanceGroundLobbyView._resolve's own [self.leader] + accepted invitees, leader
        # always first. Only the leader's own cooldown starts when the run finishes (see
        # GameManager.finish_inheritance_ground_run) -- invited teammates shouldn't have their
        # own next run gated behind someone else's.
        self.leader_id = team[0][0]
        self.phase = "intro"
        # Bubble board (replaces the old branching-choice stages) -- see manager.
        # generate_inheritance_ground_board for how it's built. turn_index cycles through
        # self.team -- only that member may pop the next bubble (enforced in the bubble
        # callback itself, not interaction_check, since a disabled discord.ui.Button can't be
        # "disabled for one viewer but not another" -- everyone sees the same button state).
        self.board: list = []
        self.revealed: list = []
        # True only for bubbles a team member ACTUALLY clicked -- distinct from self.revealed,
        # which also goes True for every bubble _reveal_remaining_bubbles shows once the
        # team's pop cap is hit, purely for display (no reward rolled/granted for those).
        self.actually_clicked: list = []
        # True once the team has used every pop max_inheritance_ground_pops allows -- the board
        # then shows every bubble (real finds AND what was missed) plus a Continue button,
        # instead of more interactive "?" bubbles. See _reveal_remaining_bubbles.
        self.board_exhausted = False
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
        # Set only when EVERY member chose Share (0 backstabbers, see _resolve_betrayal) --
        # the Core Gu doesn't just go unclaimed in that case, the whole team rolls 1-100 and
        # the highest roll wins it, per explicit request.
        self.share_dice_result: dict = None
        # Rolled the instant the team reaches "betrayal" (see _on_victory) and shown in that
        # phase's own embed -- the WHOLE team gets to see exactly what's at stake before
        # anyone chooses Share or Backstab. Whoever wins the duel is granted this SAME name,
        # never re-rolled at grant time (see _finish_backstab_duel).
        self.core_gu_preview: Optional[str] = None

        # Backstab duel (1+ backstabbers) -- a real, live, turn-based multi-way fight with the
        # SAME full action set (Attack/Guard/Empower/Class Ability/Gu Ability/Killer Move/Soul
        # Projection/Potion) and manual player targeting a battle bubble gets, resolved on the
        # "backstab_duel" phase (see _start_backstab_duel). Deliberately reuses self.participants/
        # self.actions/self.round/self.log (the SAME state a battle bubble fight uses) rather
        # than a separate duel-only dict, so the whole TeamBattleEngine action-submission
        # pipeline (_validate_actor/_submit_action/_attacker_stats/Empower/Potion menu/Defend
        # Ally picker/etc.) Just Works here too -- see _resolve_duel_round/_resolve_duel_hit for
        # the PvP-specific targeting/mitigation layered on top. Every backstabber is their OWN
        # side (solo); every sharer shares ONE side (SHARER_SIDE) -- so a lone backstabber faces
        # the whole sharer group, 2 backstabbers + sharers is a real 3-way, and so on.
        # duel_inspire_rounds_remaining is side-scoped (Support's Inspire should only buff the
        # caster's own side) -- see _duel_attacker_stats for why the SHARED self.
        # inspire_rounds_remaining a normal battle uses is forced to 0 during a duel instead.
        self.duel_inspire_rounds_remaining: dict = {}
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
                    # Once the pop cap is hit, _reveal_remaining_bubbles flips every remaining
                    # bubble's revealed flag too, purely for display -- "Missed" tells those
                    # apart from the ones the team actually clicked and were granted.
                    missed = self.board_exhausted and not self.actually_clicked[index]
                    button = discord.ui.Button(label="Missed" if missed else "", emoji=BUBBLE_ICON[category], style=discord.ButtonStyle.secondary, row=row, disabled=True)
                else:
                    button = discord.ui.Button(label="?", emoji="🫧", style=discord.ButtonStyle.primary, row=row)
                    button.callback = self._make_bubble_callback(index)
                self.add_item(button)
            if self.board_exhausted:
                # Row 4 is free -- 20 bubbles at 5/row fills rows 0-3.
                continue_button = discord.ui.Button(label="Continue to the Trial", emoji="➡️", style=discord.ButtonStyle.primary, row=4)
                continue_button.callback = self._on_bubble_board_continue
                self.add_item(continue_button)
        elif self.phase == "battle":
            # Full TeamBattleEngine action set (team_battle.py) -- same combat loop /raid
            # runs. Most battles are single-enemy (no target-select needed, every action
            # just targets self.enemies[0]) -- Crimson Formation Guardian's own fight is the
            # one exception (guardian + 2 formation nodes, see _start_battle), so the select
            # only appears when there's actually more than one enemy to choose between.
            if len(self.enemies) > 1:
                target_options = [
                    discord.SelectOption(
                        label=f"{e.monster.name} — {format_number(max(0, e.hp), decimals=0)}/{format_number(e.max_hp, decimals=0)} HP", value=str(idx),
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
                label=f"Soul Projection ({format_number(avatar.SOUL_PROJECTION_QI_COST)})", emoji="🌀",
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
            # Full raid-parity action set (same as the "battle" phase above) plus manual player
            # targeting -- per explicit request. Target-select is ALWAYS shown here (unlike the
            # "battle" phase's own enemy select, which only appears for 2+ enemies) since
            # picking WHO to fight is the whole point in a multi-way duel.
            target_options = [
                discord.SelectOption(
                    label=f"{p['name']} — {format_number(max(0, p['hp']), decimals=0)}/{format_number(p['max_hp'], decimals=0)} HP", value=str(uid),
                    emoji="🤝" if p["side"] == SHARER_SIDE else "🗡️",
                )
                for uid, p in self.participants.items() if not p["down"]
            ]
            target_select = discord.ui.Select(
                placeholder="Choose your target (for Attack/Guard/Gu ability/Killer Move)..." if target_options else "No targets left",
                options=target_options or [discord.SelectOption(label="None", value="none")],
                disabled=not target_options,
                row=2,
            )
            target_select.callback = self._on_duel_pick_target
            self.add_item(target_select)

            attack_button = discord.ui.Button(label="Attack", emoji="⚔️", style=discord.ButtonStyle.danger, row=0)
            attack_button.callback = self._on_duel_attack
            self.add_item(attack_button)
            guard_button = discord.ui.Button(label="Guard", emoji="🛡️", style=discord.ButtonStyle.secondary, row=0)
            guard_button.callback = self._on_duel_guard
            self.add_item(guard_button)
            empower_button = discord.ui.Button(label=f"Empower ({EMPOWER_QI_COST})", emoji="✨", style=discord.ButtonStyle.success, row=0)
            empower_button.callback = self._on_toggle_empower
            self.add_item(empower_button)
            class_button = discord.ui.Button(label="Class Ability", emoji="🎭", style=discord.ButtonStyle.success, row=0)
            class_button.callback = self._on_duel_class_ability
            self.add_item(class_button)

            gu_button = discord.ui.Button(label="Use Gu Ability", emoji="🐛", style=discord.ButtonStyle.primary, row=1)
            gu_button.callback = self._on_duel_gu_ability
            self.add_item(gu_button)
            killer_move_button = discord.ui.Button(label="Use Killer Move", emoji="🌀", style=discord.ButtonStyle.primary, row=1)
            killer_move_button.callback = self._on_duel_killer_move
            self.add_item(killer_move_button)
            soul_projection_button = discord.ui.Button(
                label=f"Soul Projection ({format_number(avatar.SOUL_PROJECTION_QI_COST)})", emoji="🌀",
                style=discord.ButtonStyle.success, row=1,
            )
            soul_projection_button.callback = self._on_duel_soul_projection
            self.add_item(soul_projection_button)
            potion_button = discord.ui.Button(label="Use Potion/Pill", emoji="🧪", style=discord.ButtonStyle.success, row=1)
            potion_button.callback = self._on_open_potion_menu
            self.add_item(potion_button)
        # "trial_result" and "resolved" phases have no buttons -- purely display states.

    # -- intro -----------------------------------------------------------------------------

    async def _on_intro_continue(self, interaction: discord.Interaction):
        self.phase = "bubble_board"
        self.board = await asyncio.to_thread(self.game.generate_inheritance_ground_board, len(self.team))
        self.revealed = [False] * len(self.board)
        self.actually_clicked = [False] * len(self.board)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    # -- bubble board (turn-based -- only self.team[self.turn_index] may pop the next bubble) --

    def _max_bubble_pops(self) -> int:
        return self.game.max_inheritance_ground_pops(len(self.team))

    def _reveal_remaining_bubbles(self):
        """Called once the team's pop cap is reached (see _make_bubble_callback/_on_victory) --
        reveals every STILL-hidden bubble's category for display, per explicit request ("have
        all the bubbles show their loot at the end so people can feel bad they missed the
        treasure"). Purely cosmetic: nothing is rolled or granted for a bubble nobody actually
        clicked (self.actually_clicked stays False for those) -- see _build_components/
        _build_phase_embed for how a real find is told apart from a missed one."""
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
            # defer() first -- every branch below does real DB work (loot grants, or settling
            # HP/Qi to start a battle) that can run past Discord's 3s ack window under load,
            # same reasoning as every other bulk-write callback in this codebase.
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

            if category == "treasure":
                results = await asyncio.to_thread(self.game.grant_inheritance_ground_treasure_reward, self.ground_key, self.team)
                summary = "\n".join(f"**{name}**: {reward}" for name, reward in results)
                self.last_bubble_notice = f"💰 **The Treasure!**\n{summary}"
            elif category == "ascension_pill":
                results = await asyncio.to_thread(self.game.grant_inheritance_ground_pill_reward, self.team)
                summary = "\n".join(f"**{name}**: {reward}" for name, reward in results)
                self.last_bubble_notice = f"💊 The bubble held a stash of Qi Ascension Pills!\n{summary}"
            elif category == "essence_crystal":
                results = await asyncio.to_thread(self.game.grant_inheritance_ground_essence_crystal_reward, self.team)
                summary = "\n".join(f"**{name}**: {reward}" for name, reward in results)
                self.last_bubble_notice = f"💎 The bubble held a cache of Primeval Essence Crystals!\n{summary}"
            elif category == "essence_pill":
                results = await asyncio.to_thread(self.game.grant_inheritance_ground_essence_pill_reward, self.team)
                summary = "\n".join(f"**{name}**: {reward}" for name, reward in results)
                self.last_bubble_notice = f"🧪 The bubble held a stash of Essence Restoration Pills!\n{summary}"
            elif category == "materials":
                results = await asyncio.to_thread(self.game.grant_inheritance_ground_material_reward, self.team)
                summary = "\n".join(f"**{name}**: {reward}" for name, reward in results)
                self.last_bubble_notice = f"🌿 The bubble held a cache of rare herbs!\n{summary}"
            elif category == "immortal_notes":
                results = await asyncio.to_thread(self.game.grant_inheritance_ground_immortal_notes_reward, self.team)
                summary = "\n".join(f"**{name}**: {reward}" for name, reward in results)
                self.last_bubble_notice = f"📜 The bubble held a bundle of Immortal Notes!\n{summary}"
            else:  # "nothing" -- a dud, matching BUBBLE_OUTCOME_WEIGHT's own possible outcomes
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
        """Only shown once board_exhausted -- moves on to the Final Trial once the team's
        actually done looking at what they found and missed."""
        self.phase = "pre_trial"
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

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
        if self.phase == "backstab_duel":
            await asyncio.to_thread(self._resolve_duel_round)
        else:
            await asyncio.to_thread(self._resolve_round)
        await asyncio.to_thread(self._build_components)
        await self._refresh_message()
        if self.phase == "battle":
            self._start_battle_round_timer()
        elif self.phase == "betrayal" and phase_before != "betrayal":
            self._start_betrayal_timer()
        elif self.phase == "backstab_duel":
            self._start_duel_round_timer()

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
        loot_summary = "\n".join(f"**{name}**: {text}" for name, text in loot_results)
        if self.is_final_boss_battle:
            self._log(f"🏆 The team brings down {monster.name}! {loot_summary}")
            # Rolled here (not at grant time) so it can be REVEALED to the whole team on the
            # betrayal embed before anyone actually chooses -- see core_gu_preview's own
            # __init__ comment.
            self.core_gu_preview = self.game.roll_inheritance_ground_bonus_gu(self.ground_key)
            self.phase = "betrayal"
            return
        self.last_bubble_notice = f"⚔️ The team defeats {monster.name}!\n{loot_summary}"
        if sum(self.actually_clicked) >= self._max_bubble_pops():
            self._reveal_remaining_bubbles()
        else:
            self._advance_turn()
        self.phase = "bubble_board"

    def _on_wipe(self):
        """Called by TeamBattleEngine._resolve_round (team_battle.py) once every participant
        is down -- ends the run immediately, same stakes as a failed Final Trial, no betrayal."""
        self._log("💀 The team is overwhelmed and forced to retreat!")
        self.game.finish_inheritance_ground_run([uid for uid, _ in self.team], self.leader_id)
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

        # Nobody backstabbed -- the Core Gu doesn't just go unclaimed: every sharer (the whole
        # team, since everyone defaulted/chose share) rolls 1-100, highest roll wins it (ties
        # broken randomly, same discipline as _finish_backstab_duel's own mutual-KO tiebreak).
        # Reuses core_gu_preview (already rolled/shown at the top of the betrayal stage) so the
        # reveal and the real prize always match, never re-rolled here.
        rolls = [(uid, name, random.randint(1, 100)) for uid, name in sharers]
        best_roll = max(roll for _, _, roll in rolls)
        winner_id, winner_name, _ = random.choice([r for r in rolls if r[2] == best_roll])
        gu_name = self.game.grant_inheritance_ground_bonus_gu(winner_id, self.core_gu_preview)
        self.share_dice_result = {
            "rolls": [(name, roll) for _, name, roll in rolls],
            "winner_name": winner_name, "winner_roll": best_roll, "gu_name": gu_name,
        }

        self.game.finish_inheritance_ground_run([uid for uid, _ in self.team], self.leader_id)
        self.phase = "resolved"

    # -- backstab duel (anyone backstabs -- a real live multi-way fight with the FULL raid-
    # parity action set and manual targeting, not a simulation) -- every backstabber is their
    # OWN side, every sharer shares SHARER_SIDE, so a lone backstabber faces the whole sharer
    # group, 2 backstabbers + sharers is a real 3-way, and so on. Reuses self.participants/
    # self.actions/self.round/self.log (see __init__'s own comment) so _validate_actor/
    # _submit_action/_attacker_stats/_on_toggle_empower/_on_open_potion_menu/AllyPickerView/
    # PotionPickerView (all from TeamBattleEngine, team_battle.py) work here unmodified --
    # only targeting (a living PLAYER on a different side, never self.enemies) and round
    # resolution (_resolve_duel_round/_resolve_duel_hit below) are duel-specific. Documented
    # scope gap: the handful of niche physique quirks that only make sense against a fixed
    # RaidEnemy (solar/lunar stack growth, Lunar's hit-everyone AOE, Swift Foot's dodge-
    # momentum, Strong Bone's every-3rd-attack bonus, Fire/Sunfire burn DoTs) are NOT modeled
    # here -- everything else a battle bubble supports (gear/manual/dao path bonuses, crit/
    # lifesteal/armor-pen, Empower, execute-vs-injured, guard/guard-stacks/high-hp reduction,
    # Defend Ally redirect, Frostbinder Freeze, side-scoped Inspire, Soul Projection, fatal-hit
    # negation, ward/escape/death-penalty, Immovable Mountain retaliation) is. asyncio.
    # create_task (via _start_duel_round_timer) requires a running loop on the CURRENT thread,
    # so it's always called directly on the main thread, never from inside a to_thread-
    # dispatched function -- same discipline every other round timer in this view established.

    def _start_backstab_duel(self, backstabbers: list, sharers: list):
        """Sync -- called from within _resolve_betrayal, itself always dispatched via
        asyncio.to_thread. Seeds every duelist via the SAME _build_participant_state a battle
        bubble uses (TeamBattleEngine, team_battle.py) -- full Empower/Gu/Killer Move/Soul
        Projection/physique-trait state, not just base+gear -- this is a real fight with real
        stakes, not a harmless /pvp-style duel, matching "back stab ... for the loot" being a
        genuine risk. self.enemies is cleared (not just left stale) so _build_participant_
        state's own Clear Mind-physique adaptive-stat comparison correctly finds no monster to
        compare against, rather than silently comparing against whatever was last fought."""
        self.phase = "backstab_duel"
        self.enemies = []
        self.participants = {}
        for uid, name in backstabbers:
            player = self.game.get_player_stats(uid, name)
            state = self._build_participant_state(uid, name, player)
            state["side"] = uid  # each backstabber is their own side
            state["frozen_rounds"] = 0
            self.participants[uid] = state
            self.game.apply_encounter_start_bonuses(uid, name)
        for uid, name in sharers:
            player = self.game.get_player_stats(uid, name)
            state = self._build_participant_state(uid, name, player)
            state["side"] = SHARER_SIDE
            state["frozen_rounds"] = 0
            self.participants[uid] = state
            self.game.apply_encounter_start_bonuses(uid, name)
        self.actions = {}
        self.round = 1
        self.inspire_rounds_remaining = 0  # the SHARED global buff must stay off in a duel --
        self.duel_inspire_rounds_remaining = {}  # see _duel_attacker_stats for the real (side-scoped) version
        names_b = ", ".join(name for _, name in backstabbers)
        if sharers:
            names_s = ", ".join(name for _, name in sharers)
            self.log = [f"🗡️ {names_b} backstab the team! {names_s} fight back to defend the loot!"]
        else:
            self.log = [f"🗡️ {names_b} turn on each other for the Core Gu!"]

    def _duel_attacker_stats(self, user_id: int, p: dict) -> tuple:
        """_attacker_stats (TeamBattleEngine) with self.inspire_rounds_remaining forced to 0
        during a duel (see _start_backstab_duel), plus this participant's SIDE-scoped Inspire
        bonus (duel_inspire_rounds_remaining) layered on top -- a normal battle's single shared
        flag would otherwise buff BOTH sides of a duel, which makes no sense for a PvP fight."""
        stats, bonuses, sp = self._attacker_stats(user_id, p)
        if self.duel_inspire_rounds_remaining.get(p["side"], 0) > 0:
            stats["str_stat"] = round(stats["str_stat"] * (1 + INSPIRE_STR_BONUS_PCT))
            stats["def_stat"] = round(stats["def_stat"] * (1 + INSPIRE_DEF_BONUS_PCT))
        return stats, bonuses, sp

    def _resolve_duel_target_uid(self, p: dict) -> Optional[int]:
        """The player user_id a duelist's next action should hit -- their manually-picked
        target if it's still alive and on a hostile side, otherwise the first living duelist
        (by self.participants insertion order -- backstabbers, then sharers) on a different
        side -- mirrors _resolve_target_index's own "preferred pick, else first alive" fallback
        shape. None if nobody hostile is left."""
        hostile = [uid for uid in self._alive_participant_ids() if self.participants[uid]["side"] != p["side"]]
        if not hostile:
            return None
        target_uid = p.get("target_uid")
        return target_uid if target_uid in hostile else hostile[0]

    def _apply_duel_afk_actions(self):
        for uid in self._alive_participant_ids():
            if uid in self.actions:
                continue
            p = self.participants[uid]
            self.actions[uid] = {"type": "attack", "target_uid": self._resolve_duel_target_uid(p), "guaranteed": False}
            self._log(f"⏱️ **{p['name']}** ran out of time and attacks on reflex!")

    def _start_duel_round_timer(self):
        self._duel_round_epoch += 1
        asyncio.create_task(self._duel_round_timeout(self._duel_round_epoch))

    async def _duel_round_timeout(self, epoch: int):
        await asyncio.sleep(DUEL_ROUND_TIMEOUT_SECONDS)
        if self.phase != "backstab_duel" or epoch != self._duel_round_epoch:
            return
        await asyncio.to_thread(self._apply_duel_afk_actions)
        await self._finish_round()

    def _resolve_duel_round(self):
        """Sync -- dispatched via asyncio.to_thread by _finish_round. Mirrors TeamBattleEngine.
        _resolve_round's own Phase 0 (Inspire)/0.5 (Soul Projection)/1 (attack/gu/freeze/
        soul_projection/killer_move) shape, but every target is a living PLAYER on a different
        side (never self.enemies), resolved in SUBMISSION order (not randomized) to match a
        normal battle's own "whoever locked in first resolves first" convention. Ends once at
        most one SIDE still has anyone alive -- not just one person, since the sharer side can
        have several survivors."""
        # Phase 0: Support's Inspire -- side-scoped here (see _duel_attacker_stats), unlike a
        # normal battle's single shared self.inspire_rounds_remaining.
        for user_id, action in self.actions.items():
            if action["type"] != "inspire":
                continue
            p = self.participants.get(user_id)
            if p is None or p["down"]:
                continue
            self.duel_inspire_rounds_remaining[p["side"]] = INSPIRE_DURATION_ROUNDS
            self._log(f"✨ **{p['name']}** inspires their side — STR and DEF surge!")

        # Phase 0.5: Soul Projection -- identical to a normal battle's own handling.
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

        # Defend Ally redirect map (defended_user_id -> defender_user_id) -- mirrors
        # _resolve_round's own Phase 3 defend_map construction.
        defend_map = {}
        for uid, action in self.actions.items():
            if action["type"] != "defend_ally":
                continue
            defender = self.participants.get(uid)
            if defender and not defender["down"]:
                defend_map[action["defended"]] = uid

        # Phase 1: every attack/gu/freeze/soul_projection/killer_move action, in submission order.
        for user_id, action in list(self.actions.items()):
            p = self.participants.get(user_id)
            if p is None or p["down"] or action["type"] not in ("attack", "gu", "freeze", "soul_projection", "killer_move"):
                continue
            if p.get("frozen_rounds", 0) > 0:
                p["frozen_rounds"] -= 1
                self._log(f"🥶 **{p['name']}** is frozen and can't act this round!")
                continue
            target_uid = action.get("target_uid")
            if target_uid is None or target_uid not in self._alive_participant_ids() or self.participants[target_uid]["side"] == p["side"]:
                target_uid = self._resolve_duel_target_uid(p)
            if target_uid is None:
                continue  # nobody hostile left standing -- the round-end check below will catch this

            attacker_stats, bonuses, sp = self._duel_attacker_stats(user_id, p)
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
                str_multiplier = 1.0
                label = avatar.SOUL_PROJECTION_NAME
            elif is_killer_move:
                str_multiplier = action["move"]["effects"]["str_multiplier"]
                label = action["move"]["name"]
            else:
                str_multiplier = 1.0
                label = "Attack"

            damage_pct_bonus = (
                bonuses.get("technique_damage_pct", 0) if (is_gu or is_freeze or is_soul_projection or is_killer_move)
                else bonuses.get("physical_damage_pct", 0)
            ) + bonuses.get("total_damage_pct", 0)
            root_spec = chargen.get_root_spec(p.get("root_name"))
            if action.get("guaranteed"):
                damage_pct_bonus += self._trait_bonus(p, "empower_damage_pct")
            if p.get("fire_str_pending"):
                damage_pct_bonus += root_spec.fire_battle_qi_str_bonus_pct
                p["fire_str_pending"] = False
            target_p = self.participants[target_uid]
            if target_p["hp"] > 0 and target_p["hp"] < target_p["max_hp"] * 0.5:
                damage_pct_bonus += bonuses.get("execute_damage_pct", 0) + sp.get("execute_damage_pct", 0)

            self._resolve_duel_hit(
                user_id, p, attacker_stats, bonuses, sp, target_uid, defend_map,
                str_multiplier, label, damage_pct_bonus, action.get("guaranteed", False), is_freeze,
            )

        self.actions.clear()
        for side in list(self.duel_inspire_rounds_remaining):
            self.duel_inspire_rounds_remaining[side] -= 1
            if self.duel_inspire_rounds_remaining[side] <= 0:
                del self.duel_inspire_rounds_remaining[side]
        for p in self.participants.values():
            if p.get("soul_projection_rounds_remaining", 0) > 0:
                p["soul_projection_rounds_remaining"] -= 1

        still_alive = self._alive_participant_ids()
        alive_sides = {self.participants[uid]["side"] for uid in still_alive}
        if len(alive_sides) <= 1:
            self._finish_backstab_duel(still_alive)
        else:
            self.round += 1

    def _apply_duel_knockout(self, user_id: int, p: dict) -> bool:
        """Ward/Worldly Escape/death-penalty pipeline on an actual duel knockout -- shared by
        both a landed hit and a retaliation kill in _resolve_duel_hit, mirroring how a normal
        battle's Phase 1.65 (bleed) reuses the exact same pipeline as its own Phase 3. Per
        explicit request, only a BACKSTABBER risks losing Qi here -- a defending sharer who
        gets knocked out was only protecting the loot, not the aggressor, so they're simply
        out of the fight with no further penalty. Returns True if actually knocked out, False
        if Essence of the Undying Vow saved them instead -- callers use this to decide whether
        to keep treating the participant as still in the fight."""
        if self._try_undying_vow(user_id, p):
            p["hp"] = 1
            self._persist_hp(user_id, p)
            p["frozen_rounds"] = 0
            self._log(f"🌌 **{p['name']}**'s Undying Vow flares — death itself yields! They stand at 1 HP, primed for a retaliation strike!")
            return False
        p["down"] = True
        self.game.db.set_hp(user_id, 1)
        if p["side"] == SHARER_SIDE:
            self._log(f"💫 **{p['name']}** is knocked out of the fight -- no Qi lost, they were only defending.")
            return True
        ward_name = self.game.check_and_consume_defeat_ward(user_id)
        if ward_name:
            self._log(f"✨ **{ward_name}** activates for **{p['name']}** — knocked out, but the Qi loss is warded away!")
            return True
        escape_gu_name = self.game.check_and_consume_worldly_escape(user_id)
        if escape_gu_name:
            self._log(f"✨ **{escape_gu_name}** activates for **{p['name']}** — knocked out, but the Qi loss is escaped entirely!")
            return True
        reduction = self.game.compute_equipment_bonuses(user_id).get("death_qi_loss_reduction_pct", 0)
        qi_lost, _ = self.game.db.apply_death_penalty(user_id, reduction_pct=reduction)
        p["qi_lost_on_death"] = qi_lost
        self._log(f"💀 **{p['name']}** is knocked out, losing {format_number(qi_lost)} qi!")
        return True

    def _resolve_duel_hit(
        self, attacker_uid: int, attacker_p: dict, attacker_stats: dict, bonuses: dict, sp: dict,
        target_uid: int, defend_map: dict, str_multiplier: float, label: str,
        damage_pct_bonus: float, guaranteed_hit: bool, is_freeze: bool,
    ):
        """One player-vs-player strike -- mirrors TeamBattleEngine._resolve_enemy_hit's own
        mitigation pipeline (Defend Ally redirect, Guard, race/physique reduction, guard-stack
        reduction, high-HP reduction, fatal-hit negation, ward/escape/death-penalty,
        retaliation) but symmetric: BOTH sides are real players with real gear, so the
        DEFENDER's own dodge/ignore-attack bonuses apply here too (a normal battle's Phase 1
        never needs that since a monster target has no gear)."""
        target_p = self.participants[target_uid]
        redirected_from = None
        if target_uid in defend_map and defend_map[target_uid] in self._alive_participant_ids() and defend_map[target_uid] != target_uid:
            redirected_from = target_uid
            target_uid = defend_map[target_uid]
            target_p = self.participants[target_uid]
            self._log(f"🛡️ **{target_p['name']}** steps in to defend **{self.participants[redirected_from]['name']}** from **{attacker_p['name']}**'s {label}!")

        action = self.actions.get(target_uid)
        guard_reduction = DEFEND_ALLY_DAMAGE_REDUCTION if redirected_from is not None else 0.0
        if action and action["type"] == "guard" and action.get("target_uid") == attacker_uid:
            guard_reduction = max(guard_reduction, 1.0 if action.get("full_block") else GUARD_DAMAGE_REDUCTION)

        race_physique_reduction = chargen.race_physique_damage_reduction(
            target_p.get("race"), target_p.get("physique_tier"), target_p["hp"] / target_p["max_hp"],
        )
        total_reduction = 1 - (1 - guard_reduction) * (1 - race_physique_reduction) if race_physique_reduction else guard_reduction
        guard_stack_reduction = self._trait_bonus(target_p, "guard_stack_def_pct") * target_p.get("guard_stacks", 0)
        if guard_stack_reduction:
            total_reduction = 1 - (1 - total_reduction) * (1 - guard_stack_reduction)
        if target_p["hp"] > target_p["max_hp"] * 0.6:
            high_hp_reduction = self._trait_bonus(target_p, "high_hp_damage_reduction_pct")
            if high_hp_reduction:
                total_reduction = 1 - (1 - total_reduction) * (1 - high_hp_reduction)
        if total_reduction >= 1.0:
            self._log(f"🛡️ **{target_p['name']}** fully blocks **{attacker_p['name']}**'s {label}!")
            return

        defender_stats, defender_bonuses, defender_sp = self._duel_attacker_stats(target_uid, target_p)
        result = combat.resolve_attack(
            attacker_stats, defender_stats, str_multiplier=str_multiplier, guaranteed_hit=guaranteed_hit,
            incoming_reduction=total_reduction,
            crit_chance_bonus=bonuses.get("crit_chance_pct", 0) + sp.get("crit_chance_pct", 0),
            crit_damage_bonus=bonuses.get("crit_damage_pct", 0) + sp.get("crit_damage_pct", 0),
            lifesteal_percent=bonuses.get("lifesteal_percent", 0) + sp.get("lifesteal_percent", 0),
            damage_pct_bonus=damage_pct_bonus,
            armor_penetration_pct=bonuses.get("armor_penetration_pct", 0) + sp.get("armor_penetration_pct", 0),
            dodge_chance_bonus=defender_bonuses.get("dodge_chance_pct", 0) + defender_sp.get("dodge_chance_pct", 0),
            ignore_chance=defender_bonuses.get("ignore_attack_chance", 0) + defender_sp.get("ignore_attack_chance", 0),
        )
        if not result.hit:
            self._log(f"❌ **{attacker_p['name']}** uses {label} on **{target_p['name']}** but misses!")
            return
        if result.dodged:
            self._log(f"💨 **{target_p['name']}** dodges **{attacker_p['name']}**'s {label}!")
            return
        if result.ignored:
            self._log(f"🛡️ **{target_p['name']}**'s Gu shrugs off **{attacker_p['name']}**'s attack entirely!")
            return
        if target_p["hp"] - result.damage <= 0 and (self._try_negate_fatal_hit(target_uid, target_p) or self._try_avatar_fatal_block(target_uid, target_p)):
            self._log(f"✨ **{attacker_p['name']}**'s {label} should have finished **{target_p['name']}** — their body refuses to fall!")
            return

        target_p["hp"] = max(0, target_p["hp"] - result.damage)
        self._persist_hp(target_uid, target_p)
        crit = " (Critical!)" if result.crit else ""
        heal_text = ""
        if result.heal:
            attacker_p["hp"] = min(attacker_p["max_hp"], attacker_p["hp"] + result.heal)
            self._persist_hp(attacker_uid, attacker_p)
            heal_text = f" 💚 +{result.heal} HP"
        self._log(f"⚔️ **{attacker_p['name']}** hits **{target_p['name']}** for {result.damage} damage{crit} with {label}.{heal_text}")

        if target_p["hp"] <= 0 and self._apply_duel_knockout(target_uid, target_p):
            return
        if is_freeze and random.random() < FREEZE_PROC_CHANCE:
            target_p["frozen_rounds"] = max(target_p.get("frozen_rounds", 0), 1)
            self._log(f"❄️ **{target_p['name']}** is frozen solid and will miss their next action!")
            return
        retaliation_pct = self._trait_bonus(target_p, "retaliation_damage_pct")
        if retaliation_pct > 0:
            retaliation_damage = max(1, round(result.damage * retaliation_pct))
            attacker_p["hp"] = max(0, attacker_p["hp"] - retaliation_damage)
            self._persist_hp(attacker_uid, attacker_p)
            self._log(f"🪨 **{target_p['name']}** retaliates for {retaliation_damage} damage!")
            if attacker_p["hp"] <= 0:
                self._apply_duel_knockout(attacker_uid, attacker_p)

    def _finish_backstab_duel(self, still_alive: list):
        """still_alive: everyone left on the winning side (could be several sharers at once,
        or a single backstabber) -- possibly empty on a mutual-KO edge case where the last
        two blows land the same round, tiebroken randomly among every original duelist rather
        than leave the Core Gu unclaimed. One random survivor claims the prize either way."""
        winner_id = random.choice(still_alive) if still_alive else random.choice(list(self.participants.keys()))
        winner = self.participants[winner_id]
        # The SAME Gu already rolled (and shown to the whole team) at the top of the betrayal
        # stage -- never re-rolled here, so the reveal and the real prize always match.
        gu_name = self.game.grant_inheritance_ground_bonus_gu(winner_id, self.core_gu_preview)
        self.betrayal_result = {
            "winner_user_id": winner_id, "winner_name": winner["name"],
            "winner_was_backstabber": winner["side"] != SHARER_SIDE,
            "duel": {"events": list(self.log)}, "gu_name": gu_name,
        }
        self.game.finish_inheritance_ground_run([uid for uid, _ in self.team], self.leader_id)
        self.phase = "resolved"

    async def _on_duel_pick_target(self, interaction: discord.Interaction):
        p = self.participants.get(interaction.user.id)
        if p is None:
            await interaction.response.send_message("You're not part of this duel.", ephemeral=True)
            return
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 2)
        try:
            target_uid = int(select.values[0])
        except ValueError:
            await interaction.response.defer()
            return
        target_p = self.participants.get(target_uid)
        if target_p is None or target_p["side"] == p["side"]:
            # The target-select's options list is shared across the whole team (one render,
            # not personalized per viewer), so it still lists everyone including your own
            # side -- this is the actual gate that matters. Sharers are all one shared side
            # and can never fight each other or themselves; a backstabber's own side is just
            # themselves, so this only ever blocks a fellow sharer or self -- other
            # backstabbers stay fair game (see the class docstring's own "2 backstabbers +
            # sharers is a real 3-way" design). _resolve_duel_round already silently
            # redirects a same-side pick away at resolution time regardless, but rejecting it
            # here means a player is never falsely told "Targeting X" for a hit that was
            # never actually going to land on X.
            await interaction.response.send_message("You can't target your own side.", ephemeral=True)
            return
        p["target_uid"] = target_uid
        await interaction.response.send_message(
            f"🎯 Targeting **{target_p['name']}** for your next Attack/Guard/Gu ability/Killer Move.", ephemeral=True,
        )

    async def _on_duel_attack(self, interaction: discord.Interaction):
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        empowered = await asyncio.to_thread(self._consume_empower_cost, interaction.user.id, p)
        p["empowered"] = False
        # An ephemeral confirmation, not a silent defer() -- per explicit request, this fight
        # should feel like a real private choice (mirrors the betrayal vote's own ephemeral
        # confirmations just above), not the quiet background-refresh /raid's battle rounds use.
        await interaction.response.send_message("⚔️ You attack!", ephemeral=True)
        await self._submit_action(interaction.user.id, {"type": "attack", "target_uid": self._resolve_duel_target_uid(p), "guaranteed": empowered})

    async def _on_duel_guard(self, interaction: discord.Interaction):
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        empowered = await asyncio.to_thread(self._consume_empower_cost, interaction.user.id, p)
        p["empowered"] = False
        p["guard_stacks"] = min(2, p.get("guard_stacks", 0) + 1)
        await asyncio.to_thread(self._apply_guard_or_potion_qi_restore, interaction.user.id, p)
        target_uid = self._resolve_duel_target_uid(p)
        await interaction.response.send_message("🛡️ You brace for the next blow.", ephemeral=True)
        await self._submit_action(interaction.user.id, {"type": "guard", "target_uid": target_uid, "full_block": empowered})

    async def _on_duel_class_ability(self, interaction: discord.Interaction):
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        class_name = p.get("character_class")

        if class_name == "Tank":
            alive_allies = [
                (uid, ally) for uid, ally in self.participants.items()
                if not ally["down"] and uid != interaction.user.id and ally["side"] == p["side"]
            ]
            if not alive_allies:
                await interaction.response.send_message("There's no one else on your side alive to defend.", ephemeral=True)
                return
            picker = AllyPickerView(self, interaction.user.id, alive_allies)
            await interaction.response.send_message("Choose who to Defend this round:", view=picker, ephemeral=True)
            return

        if class_name == "Support":
            await interaction.response.send_message("✨ You inspire your side — STR/DEF surge!", ephemeral=True)
            await self._submit_action(interaction.user.id, {"type": "inspire"})
            return

        if class_name == "Frostbinder":
            await interaction.response.send_message("❄️ You attempt to freeze your target!", ephemeral=True)
            await self._submit_action(interaction.user.id, {"type": "freeze", "target_uid": self._resolve_duel_target_uid(p)})
            return

        await interaction.response.send_message("You haven't chosen a class yet — run `/choose_class` to unlock a class ability.", ephemeral=True)

    async def _on_duel_gu_ability(self, interaction: discord.Interaction):
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        gu = await asyncio.to_thread(self._equipped_gu, interaction.user.id)
        ability = gu.active_ability if gu else None
        if not ability:
            await interaction.response.send_message("You have no active Gu ability equipped.", ephemeral=True)
            return
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
        await interaction.response.send_message(f"🐛 You channel {ability.name}!", ephemeral=True)
        await self._submit_action(interaction.user.id, {"type": "gu", "target_uid": self._resolve_duel_target_uid(p), "ability": ability})

    async def _on_duel_killer_move(self, interaction: discord.Interaction):
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
            await interaction.response.send_message(f"Not enough Qi to use {move['name']} (needs {format_number(qi_cost)}).", ephemeral=True)
            return
        p["qi"] -= qi_cost
        await asyncio.to_thread(self._persist_qi, interaction.user.id, p)
        if move["kind"] == "damage":
            await interaction.response.send_message(f"🌀 You unleash {move['name']}!", ephemeral=True)
            await self._submit_action(interaction.user.id, {"type": "killer_move", "target_uid": self._resolve_duel_target_uid(p), "move": move})
        else:
            await asyncio.to_thread(self.game.apply_killer_move_buff, interaction.user.id, player_row, move)
            self._log(f"✨ **{p['name']}**'s {move['name']} surges through them!")
            await interaction.response.send_message(f"✨ {move['name']} surges through you!", ephemeral=True)
            await self._submit_action(interaction.user.id, {"type": "killer_move_buff"})

    async def _on_duel_soul_projection(self, interaction: discord.Interaction):
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        soul = avatar.get_avatar_soul(p.get("avatar_soul"))
        if soul is None:
            await interaction.response.send_message("Your avatar hasn't chosen a soul yet — run `/avatar` to awaken it.", ephemeral=True)
            return
        if p["qi"] < avatar.SOUL_PROJECTION_QI_COST:
            await interaction.response.send_message(f"Not enough battle Qi for Soul Projection (needs {format_number(avatar.SOUL_PROJECTION_QI_COST)}).", ephemeral=True)
            return
        p["qi"] -= avatar.SOUL_PROJECTION_QI_COST
        await asyncio.to_thread(self._persist_qi, interaction.user.id, p)
        await interaction.response.send_message(f"🌀 You channel {avatar.SOUL_PROJECTION_NAME}!", ephemeral=True)
        await self._submit_action(interaction.user.id, {"type": "soul_projection", "target_uid": self._resolve_duel_target_uid(p)})

    # -- display -----------------------------------------------------------------------------

    async def on_timeout(self):
        if self.phase == "resolved":
            return
        # Safety net -- the same "clear everyone's flag" call the betrayal path already makes,
        # covering the case where the view's own 600s idle timeout fires before betrayal ever
        # started (e.g. the team abandons mid-board / mid-battle / mid-trial-decision).
        await asyncio.to_thread(self.game.finish_inheritance_ground_run, [uid for uid, _ in self.team], self.leader_id)
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
            max_pops = self._max_bubble_pops()
            pops_used = sum(self.actually_clicked)
            if self.board_exhausted:
                treasure_index = self.board.index("treasure")
                if self.actually_clicked[treasure_index]:
                    treasure_line = "💰 Your team actually found the Treasure this run!"
                else:
                    treasure_line = "💰 The Treasure was hidden in one of the bubbles your team never got to — it's gone unclaimed."
                embed = discord.Embed(
                    title=f"🗺️ {ground['name']} — The Ruins Fall Silent",
                    description=(
                        f"Your team has used all {max_pops} of its turns here. The rest of the "
                        f"bubbles pop open on their own, revealing what they held.\n\n{treasure_line}"
                    ),
                    color=discord.Color.dark_gold(),
                )
                if self.last_bubble_notice:
                    embed.add_field(name="Last thing your team actually found", value=self.last_bubble_notice[:1024], inline=False)
                embed.set_footer(text=f"{pops_used}/{max_pops} bubbles explored, {len(self.board)} shown. Click Continue when ready.")
                return embed

            current_name = self.team[self.turn_index][1]
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
            embed.set_footer(text=f"{pops_used}/{max_pops} turns used — {len(self.board)} bubbles on the site.")
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
                    f"{'🛡️' if idx == 0 else '🔺'} **{e.monster.name}**{submerged_note} — {format_number(max(0, e.hp), decimals=0)}/{format_number(e.max_hp, decimals=0)} HP ({pct}%)\n`{render_bar(e.hp, e.max_hp)}`"
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
                    f"**{name}** — {format_number(max(0, p['hp']), decimals=0)}/{format_number(p['max_hp'], decimals=0)} HP ({pct}%) • {status}{empower_note}{soul_projection_note}\n"
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
            # Revealed to the WHOLE team up front, per explicit request, so everyone can weigh
            # the temptation before choosing -- see core_gu_preview's own __init__ comment.
            embed.add_field(
                name="🐛 The Core Gu at Stake",
                value=self.core_gu_preview or "A canon Gu (details unknown)",
                inline=False,
            )
            embed.set_footer(text=f"{responded}/{len(self.team)} have decided — resolves once everyone has, or in {BETRAYAL_DECISION_SECONDS}s.")
            return embed

        if self.phase == "backstab_duel":
            lines = []
            for uid, p in self.participants.items():
                pct = int(100 * max(0, p["hp"]) / p["max_hp"]) if p["max_hp"] else 0
                if p["down"]:
                    status = "💀 knocked out"
                elif uid in self.actions:
                    status = "✅ locked in"
                else:
                    status = "⏳ choosing..."
                side_badge = "🤝" if p["side"] == SHARER_SIDE else "🗡️"
                empower_note = " • ✨ Empowered" if p.get("empowered") else ""
                soul_projection_note = (
                    f" • 🌀 Soul Projection ({p['soul_projection_rounds_remaining']})"
                    if p.get("soul_projection_rounds_remaining", 0) > 0 else ""
                )
                frozen_note = f" • 🥶 Frozen ({p['frozen_rounds']})" if p.get("frozen_rounds", 0) > 0 else ""
                inspired_note = " • 💪 Inspired" if self.duel_inspire_rounds_remaining.get(p["side"], 0) > 0 else ""
                lines.append(
                    f"{side_badge} **{p['name']}** — {format_number(max(0, p['hp']), decimals=0)}/{format_number(p['max_hp'], decimals=0)} HP ({pct}%) • {status}{empower_note}{soul_projection_note}{frozen_note}{inspired_note}\n"
                    f"`{render_bar(p['hp'], p['max_hp'])}`"
                )
            embed = discord.Embed(
                title=f"🗡️ {ground['name']} — Backstab Duel!",
                description="The team turns on itself — 🗡️ each backstabber fights alone, 🤝 the sharers defend together. Only one side walks away with the Core Gu.",
                color=discord.Color.dark_red(),
            )
            embed.add_field(name=f"⚔️ Duelists — Round {self.round}", value="\n".join(lines)[:1024], inline=False)
            if self.log:
                embed.add_field(name="📜 Recent Combat", value="\n".join(self.log)[:1024], inline=False)
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
            # Per-player Qi lost (see TeamBattleEngine's qi_lost_on_death, team_battle.py) --
            # the shared "Recent Combat" log already says this too, but it can scroll out of
            # MAX_LOG_LINES well before a longer fight actually ends, so it's worth a clear,
            # permanent callout here per explicit request.
            qi_lines = [f"**{p['name']}**: {format_number(p.get('qi_lost_on_death', 0))} qi lost" for p in self.participants.values()]
            if qi_lines:
                embed.add_field(name="💀 Qi Lost", value="\n".join(qi_lines)[:1024], inline=False)
            return embed

        embed = discord.Embed(
            title=f"🗺️ {ground['name']} — Run Complete!",
            description="The run concludes." if not (self.share_grants or self.betrayal_result) else "Here's how it all shook out.",
            color=discord.Color.gold(),
        )
        # Each kind of outcome gets its OWN field -- a real visual break between "who shared
        # what" and "how the backstab played out", instead of one wall of text.
        if self.share_grants:
            share_lines = [f"🤝 **{name}** shares equally: {reward}" for name, reward in self.share_grants]
            embed.add_field(name="Shared Loot", value="\n".join(share_lines)[:1024], inline=False)
        if self.share_dice_result:
            roll_lines = [
                f"🎲 **{name}**: {roll}" + (" 🏆" if name == self.share_dice_result["winner_name"] and roll == self.share_dice_result["winner_roll"] else "")
                for name, roll in self.share_dice_result["rolls"]
            ]
            embed.add_field(
                name="Core Gu Roll-Off",
                value=(
                    "Nobody backstabbed, so the whole team rolled for the Core Gu instead:\n"
                    + "\n".join(roll_lines)[:900]
                    + f"\n🏆 **{self.share_dice_result['winner_name']}** wins with a **{self.share_dice_result['winner_roll']}** "
                    f"and claims the {self.share_dice_result['gu_name']}!"
                )[:1024],
                inline=False,
            )
        if self.betrayal_result:
            if self.betrayal_result["winner_was_backstabber"]:
                outcome_line = f"🗡️ **{self.betrayal_result['winner_name']}** overcomes the defenders and claims the {self.betrayal_result['gu_name']}!"
            else:
                outcome_line = f"🛡️ The defenders hold! **{self.betrayal_result['winner_name']}** survives the backstab and claims the {self.betrayal_result['gu_name']}!"
            embed.add_field(name="Backstab Outcome", value=outcome_line[:1024], inline=False)
            # Only a defeated BACKSTABBER ever has qi_lost_on_death > 0 here (see
            # _apply_duel_knockout -- a defending sharer never loses any), so this list is
            # naturally just the losing backstabber(s), never the sharers.
            qi_lines = [f"💀 **{p['name']}**: {format_number(p['qi_lost_on_death'])} qi lost" for p in self.participants.values() if p.get("qi_lost_on_death", 0) > 0]
            if qi_lines:
                embed.add_field(name="Qi Lost", value="\n".join(qi_lines)[:1024], inline=False)
            events = self.betrayal_result["duel"]["events"]
            if events:
                embed.add_field(name="Duel — Final Moments", value="\n".join(events[-5:])[:1024], inline=False)
        return embed
