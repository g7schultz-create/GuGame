"""
GrottoView -- the /grotto menu. Overview tab: current level, live bonus breakdown, Upgrade
button (see GameManager.upgrade_grotto). Ink Men tab: recruit + assign a helper to passively
refine an owned manual page's duplicates over time (see GameManager.recruit_ink_man/
assign_ink_man/check_and_complete_ink_men_work). Hairy Men tab: recruit + assign a helper to
passively bless one specific Legendary+ Gu (see GameManager.recruit_hairy_man/assign_hairy_man/
check_and_complete_hairy_men_work).
"""

import asyncio
import time

import discord

from . import equipment, grotto, manual_data
from .base_view import GameView
from .equipment import SPECIAL_STAT_TEXT
from .ui_utils import format_duration, format_number


def _format_bonus_line(key: str, value: float) -> str:
    formatter = SPECIAL_STAT_TEXT.get(key)
    return formatter(value) if formatter else f"{key}: {value:g}"


class GrottoView(GameView):
    TABS = [("overview", "Overview", "⛩️"), ("ink_men", "Ink Men", "🖋️"), ("hairy_men", "Hairy Men", "🐒")]

    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.active_tab = "overview"
        self.selected_ink_man_id: int = None
        self.selected_page_id: str = None
        self.selected_hairy_man_id: int = None
        self.selected_gu_item: str = None
        self.last_result: str = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Run `/grotto` yourself to manage your own grotto.", ephemeral=True)
            return False
        return True

    # -- component building ------------------------------------------------------------------

    def _build_components(self):
        self.clear_items()
        for key, label, emoji in self.TABS:
            button = discord.ui.Button(label=label, emoji=emoji, row=0)
            is_active = key == self.active_tab
            button.style = discord.ButtonStyle.primary if is_active else discord.ButtonStyle.secondary
            button.disabled = is_active
            button.callback = self._make_tab_callback(key)
            self.add_item(button)

        if self.active_tab == "overview":
            self._build_overview_components()
        elif self.active_tab == "ink_men":
            self._build_ink_men_components()
        elif self.active_tab == "hairy_men":
            self._build_hairy_men_components()

    def _make_tab_callback(self, key: str):
        async def callback(interaction: discord.Interaction):
            self.active_tab = key
            self.last_result = None
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    def _build_overview_components(self):
        status = self.game.get_grotto_status(self.user_id, self.display_name)
        label = "Found Grotto" if status["level"] == 0 else "Deepen Grotto"
        button = discord.ui.Button(
            label=label, emoji="⛩️", style=discord.ButtonStyle.success, row=1,
            disabled=not status["eligible"] or status["maxed"],
        )
        button.callback = self._on_upgrade
        self.add_item(button)

    def _build_ink_men_components(self):
        ink_men = self.game.get_ink_men_status(self.user_id)
        idle_ink_men = [m for m in ink_men if m["idle"]]
        if self.selected_ink_man_id is None and idle_ink_men:
            self.selected_ink_man_id = idle_ink_men[0]["ink_man_id"]

        recruit_button = discord.ui.Button(
            label="Recruit Ink Man", emoji="✨", style=discord.ButtonStyle.success, row=1,
            disabled=len(ink_men) >= grotto.GROTTO_MAX_INK_MEN,
        )
        recruit_button.callback = self._on_recruit_ink_man
        self.add_item(recruit_button)

        if idle_ink_men:
            ink_man_options = [
                discord.SelectOption(label=f"Ink Man #{m['ink_man_id']} (idle)", value=str(m["ink_man_id"]), default=(m["ink_man_id"] == self.selected_ink_man_id))
                for m in idle_ink_men
            ]
            ink_man_select = discord.ui.Select(placeholder="Choose an idle Ink Man...", options=ink_man_options, row=2)
            ink_man_select.callback = self._on_pick_ink_man
            self.add_item(ink_man_select)

            owned_pages = self.game.get_player_pages(self.user_id)
            eligible_pages = [
                (page_id, owned) for page_id, owned in owned_pages.items()
                if manual_data.NEXT_REFINEMENT.get(owned["refinement_level"]) is not None and page_id in manual_data.PAGES
            ]
            if self.selected_page_id is None and eligible_pages:
                self.selected_page_id = eligible_pages[0][0]
            page_options = [
                discord.SelectOption(
                    label=f"{manual_data.PAGES[page_id].name} ({owned['refinement_level']}, x{owned['quantity']})"[:100],
                    value=page_id, default=(page_id == self.selected_page_id),
                )
                for page_id, owned in eligible_pages
            ]
            page_select = discord.ui.Select(
                placeholder="Choose a page to refine...",
                options=page_options[:25] or [discord.SelectOption(label="No eligible pages owned", value="none")],
                disabled=not page_options, row=3,
            )
            page_select.callback = self._on_pick_page
            self.add_item(page_select)

            assign_button = discord.ui.Button(
                label="Assign", emoji="📌", style=discord.ButtonStyle.primary, row=4,
                disabled=not page_options,
            )
            assign_button.callback = self._on_assign_ink_man
            self.add_item(assign_button)

    def _build_hairy_men_components(self):
        hairy_men = self.game.get_hairy_men_status(self.user_id)
        idle_hairy_men = [m for m in hairy_men if m["idle"]]
        if self.selected_hairy_man_id is None and idle_hairy_men:
            self.selected_hairy_man_id = idle_hairy_men[0]["hairy_man_id"]

        recruit_button = discord.ui.Button(
            label="Recruit Hairy Man", emoji="✨", style=discord.ButtonStyle.success, row=1,
            disabled=len(hairy_men) >= grotto.GROTTO_MAX_HAIRY_MEN,
        )
        recruit_button.callback = self._on_recruit_hairy_man
        self.add_item(recruit_button)

        if idle_hairy_men:
            hairy_man_options = [
                discord.SelectOption(label=f"Hairy Man #{m['hairy_man_id']} (idle)", value=str(m["hairy_man_id"]), default=(m["hairy_man_id"] == self.selected_hairy_man_id))
                for m in idle_hairy_men
            ]
            hairy_man_select = discord.ui.Select(placeholder="Choose an idle Hairy Man...", options=hairy_man_options, row=2)
            hairy_man_select.callback = self._on_pick_hairy_man
            self.add_item(hairy_man_select)

            inventory = self.game.get_inventory(self.user_id)
            eligible_gu = [
                (name, qty) for name, qty in inventory.items()
                if qty > 0 and equipment.EQUIPMENT.get(name) and equipment.EQUIPMENT[name].slot_type == "Gu"
                and equipment.gu_quality_for(name) in grotto.GU_LEGENDARY_PLUS_QUALITIES
            ]
            if self.selected_gu_item is None and eligible_gu:
                self.selected_gu_item = eligible_gu[0][0]
            gu_options = [
                discord.SelectOption(label=f"{name} (own {qty})"[:100], value=name, default=(name == self.selected_gu_item))
                for name, qty in eligible_gu
            ]
            gu_select = discord.ui.Select(
                placeholder="Choose a Legendary+ Gu to bless...",
                options=gu_options[:25] or [discord.SelectOption(label="No eligible Gu owned", value="none")],
                disabled=not gu_options, row=3,
            )
            gu_select.callback = self._on_pick_gu
            self.add_item(gu_select)

            assign_button = discord.ui.Button(
                label="Assign", emoji="📌", style=discord.ButtonStyle.primary, row=4,
                disabled=not gu_options,
            )
            assign_button.callback = self._on_assign_hairy_man
            self.add_item(assign_button)

    # -- callbacks ------------------------------------------------------------------------------

    async def _on_upgrade(self, interaction: discord.Interaction):
        _, self.last_result = await asyncio.to_thread(self.game.upgrade_grotto, self.user_id, self.display_name)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_recruit_ink_man(self, interaction: discord.Interaction):
        _, self.last_result = await asyncio.to_thread(self.game.recruit_ink_man, self.user_id, self.display_name)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_ink_man(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select) and child.row == 2)
        self.selected_ink_man_id = int(select.values[0])
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_page(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select) and child.row == 3)
        self.selected_page_id = select.values[0]
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_assign_ink_man(self, interaction: discord.Interaction):
        if self.selected_ink_man_id and self.selected_page_id:
            _, self.last_result = await asyncio.to_thread(self.game.assign_ink_man, self.user_id, self.selected_ink_man_id, self.selected_page_id)
        self.selected_ink_man_id = None
        self.selected_page_id = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_recruit_hairy_man(self, interaction: discord.Interaction):
        _, self.last_result = await asyncio.to_thread(self.game.recruit_hairy_man, self.user_id, self.display_name)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_hairy_man(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select) and child.row == 2)
        self.selected_hairy_man_id = int(select.values[0])
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_gu(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select) and child.row == 3)
        self.selected_gu_item = select.values[0]
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_assign_hairy_man(self, interaction: discord.Interaction):
        if self.selected_hairy_man_id and self.selected_gu_item:
            _, self.last_result = await asyncio.to_thread(self.game.assign_hairy_man, self.user_id, self.selected_hairy_man_id, self.selected_gu_item)
        self.selected_hairy_man_id = None
        self.selected_gu_item = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    # -- embed ------------------------------------------------------------------------------

    def build_embed(self) -> discord.Embed:
        if self.active_tab == "overview":
            embed = self._overview_embed()
        elif self.active_tab == "ink_men":
            embed = self._ink_men_embed()
        else:
            embed = self._hairy_men_embed()
        if self.last_result:
            embed.add_field(name="Result", value=self.last_result, inline=False)
        return embed

    def _overview_embed(self) -> discord.Embed:
        status = self.game.get_grotto_status(self.user_id, self.display_name)
        embed = discord.Embed(
            title=f"⛩️ {self.display_name}'s Grotto",
            description=(
                f"**Level {status['level']} / {grotto.GROTTO_MAX_LEVEL}**\n\n"
                "Invest resources to deepen your grotto for permanent passive buffs to "
                "cultivation, alchemy, blacksmithing, and profession yield."
            ),
            color=discord.Color.dark_green(),
        )
        if status["bonuses"]:
            bonus_lines = "\n".join(_format_bonus_line(key, value) for key, value in status["bonuses"].items())
            embed.add_field(name="Current Bonuses", value=bonus_lines, inline=False)
        else:
            embed.add_field(name="Current Bonuses", value="None yet — found your grotto below.", inline=False)
        if not status["eligible"]:
            embed.add_field(name="Locked", value="Your grotto awakens once you reach **Foundation Establishment**.", inline=False)
        elif status["maxed"]:
            embed.add_field(name="Maxed", value=f"Your grotto is already at its peak — Level {grotto.GROTTO_MAX_LEVEL}.", inline=False)
        else:
            recipe_lines = "\n".join(f"{qty}x {item}" for item, qty in status["next_recipe"].items())
            embed.add_field(
                name=f"Next Level ({status['level'] + 1}) Cost",
                value=f"{format_number(status['next_stones_cost'])} Spirit Stones\n{recipe_lines}",
                inline=False,
            )
        return embed

    def _ink_men_embed(self) -> discord.Embed:
        ink_men = self.game.get_ink_men_status(self.user_id)
        embed = discord.Embed(
            title=f"🖋️ {self.display_name}'s Ink Men",
            description=(
                f"**{len(ink_men)} / {grotto.GROTTO_MAX_INK_MEN}** recruited. Ink Men passively work "
                "through your owned manual page duplicates, advancing their refinement level over time."
            ),
            color=discord.Color.dark_green(),
        )
        if ink_men:
            lines = []
            for m in ink_men:
                if m["idle"]:
                    lines.append(f"Ink Man #{m['ink_man_id']} — idle")
                else:
                    remaining = max(0, m["next_tick_ts"] - int(time.time()))
                    lines.append(f"Ink Man #{m['ink_man_id']} — refining **{m['page_name']}** (next tick in {format_duration(remaining)})")
            embed.add_field(name="Your Ink Men", value="\n".join(lines), inline=False)
        return embed

    def _hairy_men_embed(self) -> discord.Embed:
        hairy_men = self.game.get_hairy_men_status(self.user_id)
        embed = discord.Embed(
            title=f"🐒 {self.display_name}'s Hairy Men",
            description=(
                f"**{len(hairy_men)} / {grotto.GROTTO_MAX_HAIRY_MEN}** recruited. Hairy Men passively "
                "bless one Legendary+ Gu at a time, permanently strengthening that specific copy."
            ),
            color=discord.Color.dark_green(),
        )
        if hairy_men:
            lines = []
            for m in hairy_men:
                if m["idle"]:
                    lines.append(f"Hairy Man #{m['hairy_man_id']} — idle")
                else:
                    remaining = max(0, m["next_tick_ts"] - int(time.time()))
                    lines.append(
                        f"Hairy Man #{m['hairy_man_id']} — blessing **{m['item_name']}** "
                        f"({m['blessing_ticks']}/{grotto.GROTTO_BLESSING_MAX_TICKS}, next tick in {format_duration(remaining)})"
                    )
            embed.add_field(name="Your Hairy Men", value="\n".join(lines), inline=False)
        return embed
