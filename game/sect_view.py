import asyncio
import traceback

import discord

from . import sects
from .base_view import GameView
from .ui_utils import NAV_NEXT_VALUE, NAV_PREV_VALUE, format_number, paginate_select_options

# (label, emoji, verb) for the four member-target actions sharing the "pick a member from a
# select" sub-screen (_build_manage_screen) — Promote/Demote/Kick/Transfer Leadership all take
# exactly one target and nothing else, so one shared screen handles all four rather than
# building four near-identical ones.
_MANAGE_ACTIONS = {
    "promote": {"label": "Promote", "emoji": "⬆️", "verb": "promote"},
    "demote": {"label": "Demote", "emoji": "⬇️", "verb": "demote"},
    "kick": {"label": "Kick", "emoji": "👢", "verb": "kick"},
    "transfer": {"label": "Transfer Leadership", "emoji": "👑", "verb": "make Sect Leader"},
}


def _add_personal_mentor_fields(embed: discord.Embed, personal: dict):
    """Personal disciples need no sect at all, so /sect shows them regardless of whether the
    viewer is currently in a sect."""
    if personal["master"]:
        embed.add_field(name="🎓 Your Personal Master", value=personal["master"]["name"], inline=True)
    if personal["disciples"]:
        lines = [f"**{d['name']}**" for d in personal["disciples"]]
        embed.add_field(
            name=f"📖 Your Personal Disciples ({len(personal['disciples'])}/{sects.MAX_PERSONAL_DISCIPLES})",
            value=", ".join(lines)[:1024], inline=True,
        )
    else:
        embed.add_field(name="📖 Your Personal Disciples", value="*None yet — try `/master_offer` (no sect needed).*", inline=True)


async def _modal_error(interaction: discord.Interaction, error: Exception, modal_name: str):
    """Every Modal in this file shares this — Modal has its own separate error hook from
    View.on_error (see base_view.py), same "surface a real message instead of silently
    hanging" treatment join_view.CharacterNameModal already established."""
    print(f"[modal error] {modal_name} raised {type(error).__name__}: {error}")
    traceback.print_exception(type(error), error, error.__traceback__)
    message = f"⚠️ Something went wrong ({type(error).__name__}: {error})."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass


class CreateSectModal(discord.ui.Modal, title="Found a Sect"):
    name_input = discord.ui.TextInput(label="Sect Name", max_length=sects.MAX_NAME_LENGTH)

    def __init__(self, sect_view: "SectView"):
        super().__init__()
        self.sect_view = sect_view

    async def on_submit(self, interaction: discord.Interaction):
        ok, message = await asyncio.to_thread(
            self.sect_view.game.sect_create, self.sect_view.user_id, self.sect_view.display_name, str(self.name_input.value),
        )
        self.sect_view.last_result = message
        await asyncio.to_thread(self.sect_view.refresh)
        await asyncio.to_thread(self.sect_view._build_components)
        embed = await asyncio.to_thread(self.sect_view.build_embed)
        await interaction.response.edit_message(embed=embed, view=self.sect_view)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await _modal_error(interaction, error, "CreateSectModal")


class TreasuryModal(discord.ui.Modal):
    amount_input = discord.ui.TextInput(label="Amount", placeholder="e.g. 100")

    def __init__(self, sect_view: "SectView", action: str):
        # action: "donate" | "withdraw" — same modal shape either way, just a different title
        # and which manager method the amount gets handed to.
        super().__init__(title="Donate to Treasury" if action == "donate" else "Withdraw from Treasury")
        self.sect_view = sect_view
        self.action = action

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.amount_input.value).strip()
        try:
            amount = int(raw)
        except ValueError:
            await interaction.response.send_message(f"'{raw}' isn't a whole number.", ephemeral=True)
            return
        game = self.sect_view.game
        fn = game.sect_donate if self.action == "donate" else game.sect_withdraw
        ok, message = await asyncio.to_thread(fn, self.sect_view.user_id, self.sect_view.display_name, amount)
        self.sect_view.last_result = message
        await asyncio.to_thread(self.sect_view.refresh)
        await asyncio.to_thread(self.sect_view._build_components)
        embed = await asyncio.to_thread(self.sect_view.build_embed)
        await interaction.response.edit_message(embed=embed, view=self.sect_view)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await _modal_error(interaction, error, "TreasuryModal")


class SectInfoModal(discord.ui.Modal, title="Edit Sect"):
    name_input = discord.ui.TextInput(label="Name", max_length=sects.MAX_NAME_LENGTH)
    motto_input = discord.ui.TextInput(label="Motto (blank to clear)", max_length=sects.MAX_MOTTO_LENGTH, required=False)
    banner_input = discord.ui.TextInput(label="Banner emoji", max_length=sects.MAX_BANNER_LENGTH)

    def __init__(self, sect_view: "SectView", sect: dict):
        super().__init__()
        self.sect_view = sect_view
        self.name_input.default = sect["name"]
        self.motto_input.default = sect["motto"]
        self.banner_input.default = sect["banner"]

    async def on_submit(self, interaction: discord.Interaction):
        game = self.sect_view.game
        user_id, display_name = self.sect_view.user_id, self.sect_view.display_name
        new_name = str(self.name_input.value).strip()
        new_motto = str(self.motto_input.value)
        new_banner = str(self.banner_input.value).strip()

        def _apply_edits():
            sect = game.sect_status(user_id, display_name)["sect"]
            messages = []
            if new_name and new_name != sect["name"]:
                _, message = game.sect_rename(user_id, display_name, new_name)
                messages.append(message)
            if new_motto != sect["motto"]:
                _, message = game.sect_set_motto(user_id, display_name, new_motto)
                messages.append(message)
            if new_banner and new_banner != sect["banner"]:
                _, message = game.sect_set_banner(user_id, display_name, new_banner)
                messages.append(message)
            return messages

        messages = await asyncio.to_thread(_apply_edits)
        self.sect_view.last_result = "\n".join(messages) if messages else "No changes made."
        await asyncio.to_thread(self.sect_view.refresh)
        await asyncio.to_thread(self.sect_view._build_components)
        embed = await asyncio.to_thread(self.sect_view.build_embed)
        await interaction.response.edit_message(embed=embed, view=self.sect_view)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await _modal_error(interaction, error, "SectInfoModal")


class SectView(GameView):
    """/sect's interactive home screen — which buttons show up is gated by the viewer's own
    sect_rank (see sects.can_kick/can_demote/can_edit_sect_info/can_withdraw_treasury/
    can_approve_applications/promotable_target_ranks, the single source of truth for "who can
    do X" every manager.py sect_* method already re-validates against independently, so a
    stale button here can never grant more than the underlying call itself allows)."""

    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.screen = "main"  # "main" | "manage" | "applications"
        self.manage_action: str = None
        self.manage_page = 0
        self.selected_application_id: int = None
        self.applications_page = 0
        self.last_result: str = None
        self.status = None
        self.refresh()
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Run `/sect` yourself to manage your own sect.", ephemeral=True)
            return False
        return True

    def refresh(self):
        self.status = self.game.sect_status(self.user_id, self.display_name)

    def _pending_application(self):
        return self.game.db.get_pending_application_for_player(self.user_id)

    # -- component building ---------------------------------------------------------------

    def _build_components(self):
        self.clear_items()
        if self.status is None:
            self._build_no_sect_screen()
        elif self.screen == "manage":
            self._build_manage_screen()
        elif self.screen == "applications":
            self._build_applications_screen()
        else:
            self._build_main_screen()

    def _build_no_sect_screen(self):
        if self._pending_application():
            cancel_btn = discord.ui.Button(label="Cancel Application", emoji="🚫", style=discord.ButtonStyle.danger, row=0)
            cancel_btn.callback = self._on_cancel_application
            self.add_item(cancel_btn)
        else:
            create_btn = discord.ui.Button(label="Found a Sect", emoji="🏯", style=discord.ButtonStyle.success, row=0)
            create_btn.callback = self._on_open_create
            self.add_item(create_btn)

    def _build_main_screen(self):
        rank = self.status["player_rank"]
        sect_id = self.status["sect"]["sect_id"]

        buttons = [("donate", "Donate", "💰", discord.ButtonStyle.success, self._on_open_donate)]
        if sects.can_withdraw_treasury(rank):
            buttons.append(("withdraw", "Withdraw", "💸", discord.ButtonStyle.secondary, self._on_open_withdraw))
        if sects.can_approve_applications(rank):
            pending_count = len(self.game.sect_pending_applications(sect_id))
            label = f"Applications ({pending_count})" if pending_count else "Applications"
            style = discord.ButtonStyle.primary if pending_count else discord.ButtonStyle.secondary
            buttons.append(("applications", label, "📋", style, self._on_open_applications))
        if sects.promotable_target_ranks(rank):
            buttons.append(("promote", "Promote", "⬆️", discord.ButtonStyle.secondary, self._make_open_manage("promote")))
        if sects.can_demote(rank):
            buttons.append(("demote", "Demote", "⬇️", discord.ButtonStyle.secondary, self._make_open_manage("demote")))
        if sects.can_kick(rank):
            buttons.append(("kick", "Kick", "👢", discord.ButtonStyle.danger, self._make_open_manage("kick")))
        if rank == sects.SECT_LEADER:
            buttons.append(("transfer", "Transfer Leadership", "👑", discord.ButtonStyle.secondary, self._make_open_manage("transfer")))
        if sects.can_edit_sect_info(rank):
            buttons.append(("edit", "Edit Sect", "🎌", discord.ButtonStyle.secondary, self._on_open_edit))
        buttons.append(("leave", "Leave Sect", "🚪", discord.ButtonStyle.danger, self._on_leave))

        for i, (_, label, emoji, style, callback) in enumerate(buttons):
            button = discord.ui.Button(label=label, emoji=emoji, style=style, row=i // 5)
            button.callback = callback
            self.add_item(button)

    def _build_manage_screen(self):
        members = [m for m in self.status["members"] if m["user_id"] != self.user_id]
        options = [
            discord.SelectOption(label=f"{m['name']} — {m['sect_rank']}"[:100], value=str(m["user_id"]))
            for m in members
        ]
        page_options, total_pages, self.manage_page = paginate_select_options(options, self.manage_page)
        info = _MANAGE_ACTIONS[self.manage_action]
        placeholder = f"Choose who to {info['verb']}..." if page_options else "No eligible members"
        if total_pages > 1:
            placeholder += f" (page {self.manage_page + 1}/{total_pages})"
        select = discord.ui.Select(
            placeholder=placeholder, options=page_options or [discord.SelectOption(label="None", value="none")],
            disabled=not page_options, row=0,
        )
        select.callback = self._on_pick_manage_target
        self.add_item(select)

        back_btn = discord.ui.Button(label="Back", emoji="↩️", row=1)
        back_btn.callback = self._on_back
        self.add_item(back_btn)

    def _build_applications_screen(self):
        applications = self.game.sect_pending_applications(self.status["sect"]["sect_id"])
        options = [
            discord.SelectOption(
                label=a["applicant_name"][:100], value=str(a["application_id"]),
                default=(a["application_id"] == self.selected_application_id),
            )
            for a in applications
        ]
        page_options, total_pages, self.applications_page = paginate_select_options(options, self.applications_page)
        placeholder = "Choose an applicant..." if page_options else "No pending applications"
        if total_pages > 1:
            placeholder += f" (page {self.applications_page + 1}/{total_pages})"
        select = discord.ui.Select(
            placeholder=placeholder, options=page_options or [discord.SelectOption(label="None", value="none")],
            disabled=not page_options, row=0,
        )
        select.callback = self._on_pick_application
        self.add_item(select)

        has_selection = self.selected_application_id is not None
        approve_btn = discord.ui.Button(label="Approve", emoji="✅", style=discord.ButtonStyle.success, row=1, disabled=not has_selection)
        approve_btn.callback = self._on_approve_application
        self.add_item(approve_btn)

        reject_btn = discord.ui.Button(label="Reject", emoji="❌", style=discord.ButtonStyle.danger, row=1, disabled=not has_selection)
        reject_btn.callback = self._on_reject_application
        self.add_item(reject_btn)

        back_btn = discord.ui.Button(label="Back", emoji="↩️", row=2)
        back_btn.callback = self._on_back
        self.add_item(back_btn)

    # -- callbacks --------------------------------------------------------------------------

    async def _on_open_create(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CreateSectModal(self))

    async def _on_open_donate(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TreasuryModal(self, "donate"))

    async def _on_open_withdraw(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TreasuryModal(self, "withdraw"))

    async def _on_open_edit(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SectInfoModal(self, self.status["sect"]))

    def _make_open_manage(self, action: str):
        async def callback(interaction: discord.Interaction):
            self.screen = "manage"
            self.manage_action = action
            self.manage_page = 0
            self.last_result = None
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    async def _on_open_applications(self, interaction: discord.Interaction):
        self.screen = "applications"
        self.selected_application_id = None
        self.applications_page = 0
        self.last_result = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_manage_target(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 0)
        choice = select.values[0]
        if choice == NAV_PREV_VALUE:
            self.manage_page = max(0, self.manage_page - 1)
        elif choice == NAV_NEXT_VALUE:
            self.manage_page += 1
        elif choice != "none":
            target_id = int(choice)
            target = next((m for m in self.status["members"] if m["user_id"] == target_id), None)
            target_name = target["name"] if target else "them"
            method = {
                "promote": self.game.sect_promote, "demote": self.game.sect_demote,
                "kick": self.game.sect_kick, "transfer": self.game.sect_transfer_leadership,
            }[self.manage_action]
            ok, message = await asyncio.to_thread(method, self.user_id, self.display_name, target_id, target_name)
            self.last_result = message
            await asyncio.to_thread(self.refresh)
            # Transfer changes the ACTOR's own rank (Leader -> Vice Leader), so re-picking
            # another target on the same screen no longer makes sense — bounce back to main.
            # Promote/demote/kick stay on this screen so a Leader can work through several
            # members in one sitting without re-opening the button each time.
            if ok and self.manage_action == "transfer":
                self.screen = "main"
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_application(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 0)
        choice = select.values[0]
        if choice == NAV_PREV_VALUE:
            self.applications_page = max(0, self.applications_page - 1)
        elif choice == NAV_NEXT_VALUE:
            self.applications_page += 1
        elif choice != "none":
            self.selected_application_id = int(choice)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_approve_application(self, interaction: discord.Interaction):
        ok, message = await asyncio.to_thread(self.game.sect_approve_application, self.user_id, self.display_name, self.selected_application_id)
        self.last_result = message
        await asyncio.to_thread(self.refresh)
        self.selected_application_id = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_reject_application(self, interaction: discord.Interaction):
        ok, message = await asyncio.to_thread(self.game.sect_reject_application, self.user_id, self.display_name, self.selected_application_id)
        self.last_result = message
        self.selected_application_id = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_cancel_application(self, interaction: discord.Interaction):
        ok, message = await asyncio.to_thread(self.game.sect_cancel_application, self.user_id, self.display_name)
        self.last_result = message
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_leave(self, interaction: discord.Interaction):
        ok, message = await asyncio.to_thread(self.game.sect_leave, self.user_id, self.display_name)
        self.last_result = message
        await asyncio.to_thread(self.refresh)
        self.screen = "main"
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_back(self, interaction: discord.Interaction):
        self.screen = "main"
        self.manage_action = None
        self.selected_application_id = None
        self.last_result = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    # -- embed ------------------------------------------------------------------------------

    def _no_sect_embed(self) -> discord.Embed:
        embed = discord.Embed(title="🏯 Sects", color=discord.Color.dark_grey())
        application = self._pending_application()
        if application:
            sect = self.game.db.get_sect(application["sect_id"])
            sect_name = sect["name"] if sect else "a sect"
            embed.description = (
                f"⏳ You have a pending application to **{sect_name}** — waiting on a Vice Leader "
                "or the Sect Leader to review it."
            )
        else:
            embed.description = (
                "You aren't in a sect yet.\n\n"
                "Found one below, or run `/sect_list` to browse existing sects and "
                "`/sect_join <name>` to apply to one."
            )
        personal = self.game.personal_mentor_status(self.user_id, self.display_name)
        _add_personal_mentor_fields(embed, personal)
        if self.last_result:
            embed.add_field(name="Result", value=self.last_result[:1024], inline=False)
        return embed

    def _main_embed(self) -> discord.Embed:
        status = self.status
        sect_row = status["sect"]
        rank = status["player_rank"]

        embed = discord.Embed(
            title=f"{sect_row['banner']} {sect_row['name']}",
            description=f"*{sect_row['motto']}*" if sect_row["motto"] else None,
            color=discord.Color.gold(),
        )
        embed.add_field(name="Your Rank", value=f"{sects.RANK_EMOJI[rank]} {rank}", inline=True)
        embed.add_field(name="Members", value=f"{len(status['members'])}/{sects.MAX_MEMBERS}", inline=True)
        embed.add_field(name="Treasury", value=f"🪙 {format_number(sect_row['treasury_spirit_stones'])} spirit stones", inline=True)
        roster_lines = [f"{sects.RANK_EMOJI[m['sect_rank']]} **{m['name']}** — {m['sect_rank']}" for m in status["members"]]
        embed.add_field(name="Roster", value="\n".join(roster_lines)[:1024], inline=False)

        if sects.can_approve_applications(rank):
            pending = self.game.sect_pending_applications(sect_row["sect_id"])
            if pending:
                embed.add_field(
                    name="📋 Pending Applications",
                    value=f"{len(pending)} awaiting review — see the Applications button below.",
                    inline=False,
                )

        if status["master"]:
            embed.add_field(name="🎓 Your Sect Master", value=status["master"]["name"], inline=True)
        if status["disciples"]:
            disciple_lines = [f"**{d['name']}**" for d in status["disciples"]]
            embed.add_field(
                name=f"📖 Your Sect Disciples ({len(status['disciples'])}/{sects.MAX_DISCIPLES_PER_MASTER})",
                value=", ".join(disciple_lines)[:1024], inline=True,
            )
        elif sects.can_accept_disciples(rank):
            embed.add_field(name="📖 Your Sect Disciples", value="*None yet — try `/accept_disciple`.*", inline=True)

        personal = self.game.personal_mentor_status(self.user_id, self.display_name)
        _add_personal_mentor_fields(embed, personal)
        if self.last_result:
            embed.add_field(name="Result", value=self.last_result[:1024], inline=False)
        embed.set_footer(text="Buttons below are gated by your sect rank. Contribution, region wars, buildings, and missions are still coming in a later update.")
        return embed

    def _manage_embed(self) -> discord.Embed:
        info = _MANAGE_ACTIONS[self.manage_action]
        embed = discord.Embed(title=f"{info['emoji']} {info['label']}", color=discord.Color.gold())
        embed.description = f"Choose which member to {info['verb']}."
        if self.last_result:
            embed.add_field(name="Result", value=self.last_result[:1024], inline=False)
        return embed

    def _applications_embed(self) -> discord.Embed:
        embed = discord.Embed(title="📋 Sect Applications", color=discord.Color.gold())
        applications = self.game.sect_pending_applications(self.status["sect"]["sect_id"])
        if not applications:
            embed.description = "No pending applications right now."
        else:
            lines = [f"**{a['applicant_name']}** — applied <t:{a['created_ts']}:R>" for a in applications]
            embed.description = "\n".join(lines)[:4000]
        if self.last_result:
            embed.add_field(name="Result", value=self.last_result[:1024], inline=False)
        return embed

    def build_embed(self) -> discord.Embed:
        if self.status is None:
            return self._no_sect_embed()
        if self.screen == "manage":
            return self._manage_embed()
        if self.screen == "applications":
            return self._applications_embed()
        return self._main_embed()
