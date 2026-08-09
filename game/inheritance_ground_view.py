"""
/inheritance_ground -- a 3-4 player INVITED team explores a named inheritance site through a
few branching-choice stages, a Final Trial, and a betrayal twist. See
game/inheritance_ground_data.py for content and GameManager's own inheritance-ground methods
(manager.py, right after the /raid gate section) for the business logic this view only ever
calls into, never duplicates.

Three views:
  InheritanceGroundLobbyView   -- invite/accept flow (leader + up to 3 invitees).
  InheritanceGroundView        -- the run itself: intro -> 2 stages -> trial -> betrayal -> resolution.
  AbandonInheritanceGroundView -- self-service escape hatch, same shape as AbandonRaidView/
                                   AbandonDiscoveryView, shipped from day one rather than added
                                   reactively (see the raid flee bug fixed in commit 0b6b712).
"""

import asyncio
import random

import discord

from . import inheritance_ground_data
from .base_view import GameView
from .ui_utils import format_duration

BETRAYAL_DECISION_SECONDS = 60


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
        # before someone clicks Accept, long enough to start another run or fall on cooldown
        # in the meantime. "You" phrasing since this is the clicking player's own eligibility,
        # unlike cog.py's invite-time check which is third-person about an invitee.
        ok, reason_code, remaining = await asyncio.to_thread(self.game.check_inheritance_ground_eligibility, interaction.user.id, interaction.user.display_name)
        if not ok:
            messages = {
                "not_confirmed": "You need to `/join` and confirm a character first.",
                "already_active": "You're already in another inheritance ground run — finish or abandon it first.",
                "on_cooldown": f"You're still recovering from your last run — try again in **{format_duration(remaining)}**.",
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


class InheritanceGroundView(GameView):
    def __init__(self, game, ground_key: str, team: list):
        super().__init__(timeout=600)
        self.game = game
        self.ground_key = ground_key
        self.team = team  # [(user_id, name), ...]
        self.phase = "intro"
        self.stage_index = 0
        self.power_modifier = 0.0
        self.stage_log: list = []
        self.stage_resolving = False
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

    # -- components ----------------------------------------------------------------------

    def _build_components(self):
        self.clear_items()
        if self.phase == "intro":
            button = discord.ui.Button(label="Continue", emoji="➡️", style=discord.ButtonStyle.primary)
            button.callback = self._on_intro_continue
            self.add_item(button)
        elif self.phase == "stage":
            stage = self._ground()["stages"][self.stage_index]
            for option in stage["options"]:
                button = discord.ui.Button(label=option["label"], emoji=option["emoji"], style=discord.ButtonStyle.primary)
                button.callback = self._make_stage_option_callback(option["id"])
                self.add_item(button)
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
        self.phase = "stage"
        self.stage_index = 0
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    # -- stages (group decision -- first team member to click decides for everyone) --------

    def _make_stage_option_callback(self, option_id: str):
        async def callback(interaction: discord.Interaction):
            if self.stage_resolving:
                await interaction.response.defer()
                return
            self.stage_resolving = True
            # defer() first -- resolve_inheritance_ground_stage does real DB work (spending
            # every team member's spirit stones) that can run past Discord's 3s ack window
            # under load, same reasoning as every other bulk-write callback in this codebase.
            await interaction.response.defer()
            result = await asyncio.to_thread(
                self.game.resolve_inheritance_ground_stage, self.ground_key, self.stage_index, option_id, self.team,
            )
            self.power_modifier += result["power_delta"]
            self.stage_log.append((self._ground()["stages"][self.stage_index]["title"], result["option_label"], result["flavor"]))
            if self.stage_index + 1 < len(self._ground()["stages"]):
                self.stage_index += 1
            else:
                self.phase = "pre_trial"
            self.stage_resolving = False
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.edit_original_response(embed=embed, view=self)

        return callback

    # -- final trial -------------------------------------------------------------------------

    async def _on_face_trial(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.trial_result = await asyncio.to_thread(
            self.game.resolve_inheritance_ground_trial, self.ground_key, self.team, self.power_modifier,
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
        # started (e.g. the team abandons mid-stage / mid-trial-decision).
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

        if self.phase == "stage":
            stage = ground["stages"][self.stage_index]
            embed = discord.Embed(
                title=f"🗺️ {ground['name']} — {stage['title']}",
                description=stage["prompt"],
                color=discord.Color.dark_gold(),
            )
            for option in stage["options"]:
                embed.add_field(name=f"{option['emoji']} {option['label']}", value=option["description"], inline=False)
            if self.stage_log:
                log_text = "\n".join(f"**{title}** — {label}: {flavor}" for title, label, flavor in self.stage_log)
                embed.add_field(name="So far", value=log_text[:1024], inline=False)
            embed.set_footer(text="Any team member can decide for the group.")
            return embed

        if self.phase == "pre_trial":
            log_text = "\n".join(f"**{title}** — {label}: {flavor}" for title, label, flavor in self.stage_log)
            embed = discord.Embed(
                title=f"🗺️ {ground['name']} — {ground['guardian_name']} Awaits",
                description=f"The team stands before the Final Trial.\n\n{log_text}",
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
