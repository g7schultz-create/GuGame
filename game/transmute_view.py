import asyncio
from typing import Optional

import discord

from . import items as items_module
from .base_view import GameView
from .views import _build_category_buttons, _build_subcategory_buttons, _default_subcategory

# Only Pills/Materials ever carry a tier (item.rank, or -- for Materials -- the tier baked
# into the item name instead, see items.item_effective_tier) -- the top-level "Healing"
# category is all untiered basic items (see items.py's own ITEM_CATEGORIES comment), so it's
# excluded here rather than shown as a selectable tab with nothing transmutable in it.
TRANSMUTE_CATEGORIES = ["Pills", "Materials"]


def _build_transmutable_item_select(game, user_id: int, category: str, subcategory: Optional[str], row: int, on_select, selected: Optional[str] = None) -> discord.ui.Select:
    inventory = game.get_inventory(user_id)
    options = [
        discord.SelectOption(
            label=f"{item.name} x{inventory[item.name]} (T{items_module.item_effective_tier(item)})", value=item.name,
            description=item.description[:100], default=(item.name == selected),
        )
        for item in items_module.items_in_category(category, subcategory)
        if items_module.item_effective_tier(item) is not None and inventory.get(item.name, 0) > 0
    ]
    select = discord.ui.Select(
        placeholder="Choose an item to transmute..." if options else "No transmutable items here",
        options=options[:25] or [discord.SelectOption(label="None", value="none")],
        disabled=not options, row=row,
    )
    select.callback = on_select
    return select


class TransmuteView(GameView):
    """/transmute (Transformation Dao Path) -- converts 1x a chosen tiered item into 1x random
    item of the SAME tier from a DIFFERENT category (e.g. a Tier 7 Ore into a random Tier 7
    Pill). Daily charges scale with marks invested (see GameManager.get_transmute_status)."""

    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.active_category = TRANSMUTE_CATEGORIES[0]
        self.active_subcategory = _default_subcategory(self.active_category)
        self.selected_item: Optional[str] = None
        self.last_result: Optional[str] = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your Transmutation.", ephemeral=True)
            return False
        return True

    def _build_components(self):
        self.clear_items()
        for button in _build_category_buttons(self.active_category, row=0, callback_factory=self._make_category_callback, categories=TRANSMUTE_CATEGORIES):
            self.add_item(button)
        buttons, rows_used = _build_subcategory_buttons(self.active_category, self.active_subcategory, row_start=1, callback_factory=self._make_subcategory_callback)
        for button in buttons:
            self.add_item(button)
        next_row = 1 + rows_used
        self.add_item(_build_transmutable_item_select(
            self.game, self.user_id, self.active_category, self.active_subcategory, row=next_row,
            on_select=self._on_select_item, selected=self.selected_item,
        ))
        status = self.game.get_transmute_status(self.user_id)
        if self.selected_item and status["remaining"] > 0:
            transmute_button = discord.ui.Button(label="Transmute", emoji="🔄", style=discord.ButtonStyle.success, row=next_row + 1)
            transmute_button.callback = self._on_transmute
            self.add_item(transmute_button)

    def _make_category_callback(self, category: str):
        async def callback(interaction: discord.Interaction):
            self.active_category = category
            self.active_subcategory = _default_subcategory(category)
            self.selected_item = None
            self.last_result = None
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    def _make_subcategory_callback(self, subcategory: str):
        async def callback(interaction: discord.Interaction):
            self.active_subcategory = subcategory
            self.selected_item = None
            self.last_result = None
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    async def _on_select_item(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select))
        value = select.values[0]
        self.selected_item = None if value == "none" else value
        self.last_result = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_transmute(self, interaction: discord.Interaction):
        ok, message = await asyncio.to_thread(self.game.transmute_item, self.user_id, self.display_name, self.selected_item)
        self.last_result = message
        if ok:
            self.selected_item = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def build_embed(self) -> discord.Embed:
        status = self.game.get_transmute_status(self.user_id)
        label = f"{self.active_category} — {self.active_subcategory}" if self.active_subcategory else self.active_category
        embed = discord.Embed(
            title=f"🔄 {self.display_name}'s Transmutation — {label}",
            description=(
                "Convert an item into a random item of the SAME tier from a different category "
                "(e.g. a Tier 7 Ore into a random Tier 7 Pill). Pick an item below, then Transmute."
            ),
            color=discord.Color.dark_purple(),
        )
        embed.add_field(
            name="Daily Charges",
            value=f"**{status['remaining']} / {status['max_charges']}** remaining today (Transformation: {status['marks_invested']:,} marks invested)",
            inline=False,
        )
        if status["marks_invested"] <= 0:
            embed.add_field(
                name="Locked",
                value="Invest Dao Marks in the Transformation path via `/dao_path` to unlock transmuting.",
                inline=False,
            )
        if self.last_result:
            embed.add_field(name="Result", value=self.last_result, inline=False)
        return embed
