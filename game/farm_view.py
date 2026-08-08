import asyncio

import discord

from . import professions
from .base_view import GameView
from .ui_utils import format_duration, render_bar


def _slot_summary(slot: dict) -> str:
    if slot["state"] == "empty":
        return "Empty"
    if slot["state"] == "growing":
        pct = min(100, slot["elapsed_hours"] / slot["grow_hours"] * 100)
        return f"🌱 Growing Tier {slot['tier']} Herb ({pct:.0f}%)"
    return f"✅ Ready — Tier {slot['tier']} Herb"


class FarmView(GameView):
    """Multiple simultaneous plots (see GameManager.farm_slot_count — 1 base slot, +2 per
    Great Realm) — a Select picks which plot slot to act on, then Plant/Check Progress/
    Harvest controls apply to whichever slot is currently selected."""

    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.selected_slot = 0
        self.last_result: str = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your farm.", ephemeral=True)
            return False
        return True

    def _current_slot(self, overview: dict) -> dict:
        return next(s for s in overview["slots"] if s["slot_index"] == self.selected_slot)

    def _build_components(self):
        self.clear_items()
        overview = self.game.get_farm_overview(self.user_id, self.display_name)
        slots = overview["slots"]
        if self.selected_slot >= len(slots):
            self.selected_slot = 0

        slot_options = [
            discord.SelectOption(
                label=f"Plot {slot['slot_index'] + 1} — {_slot_summary(slot)}",
                value=str(slot["slot_index"]),
                default=(slot["slot_index"] == self.selected_slot),
            )
            for slot in slots
        ]
        slot_select = discord.ui.Select(placeholder="Choose a plot...", options=slot_options, row=0)
        slot_select.callback = self._on_pick_slot
        self.add_item(slot_select)

        slot = self._current_slot(overview)
        if slot["state"] == "empty":
            inventory = self.game.get_inventory(self.user_id)
            options = [
                discord.SelectOption(label=f"Tier {t} Herb x{inventory[f'Tier {t} Herb']}", value=str(t))
                for t in range(1, 8) if inventory.get(f"Tier {t} Herb", 0) > 0
            ]
            plant_select = discord.ui.Select(
                placeholder="Plant a herb..." if options else "No herbs to plant — try /gather",
                options=options or [discord.SelectOption(label="None", value="none")],
                disabled=not options,
                row=1,
            )
            plant_select.callback = self._on_plant
            self.add_item(plant_select)
        elif slot["state"] == "growing":
            refresh_button = discord.ui.Button(label="Check Progress", emoji="🔄", style=discord.ButtonStyle.secondary, row=1)
            refresh_button.callback = self._on_refresh
            self.add_item(refresh_button)
        else:  # ready
            harvest_button = discord.ui.Button(label="Harvest", emoji="🌾", style=discord.ButtonStyle.success, row=1)
            harvest_button.callback = self._on_harvest
            self.add_item(harvest_button)

        ready_count = sum(1 for s in slots if s["state"] == "ready")
        harvest_all_button = discord.ui.Button(
            label=f"Claim All ({ready_count})", emoji="🧺", style=discord.ButtonStyle.success, row=2,
            disabled=ready_count == 0,
        )
        harvest_all_button.callback = self._on_harvest_all
        self.add_item(harvest_all_button)

        empty_count = sum(1 for s in slots if s["state"] == "empty")
        inventory = self.game.get_inventory(self.user_id)
        plant_all_options = [
            discord.SelectOption(label=f"Tier {t} Herb x{inventory[f'Tier {t} Herb']}", value=str(t))
            for t in range(1, 8) if inventory.get(f"Tier {t} Herb", 0) > 0
        ]
        plant_all_select = discord.ui.Select(
            placeholder=f"Plant All ({empty_count} empty plot{'s' if empty_count != 1 else ''})..." if plant_all_options else "Plant All — no herbs to plant",
            options=plant_all_options or [discord.SelectOption(label="None", value="none")],
            disabled=empty_count == 0 or not plant_all_options,
            row=3,
        )
        plant_all_select.callback = self._on_plant_all
        self.add_item(plant_all_select)

    async def _on_pick_slot(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 0)
        self.selected_slot = int(select.values[0])
        self.last_result = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_plant(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 1)
        choice = select.values[0]
        if choice == "none":
            await interaction.response.defer()
            return
        ok, message = await asyncio.to_thread(self.game.plant_farm, self.user_id, self.display_name, self.selected_slot, int(choice))
        self.last_result = message
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_refresh(self, interaction: discord.Interaction):
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_harvest(self, interaction: discord.Interaction):
        ok, item_name, quantity, error = await asyncio.to_thread(self.game.harvest_farm, self.user_id, self.display_name, self.selected_slot)
        self.last_result = f"🌾 Harvested **{quantity}x {item_name}**!" if ok else error
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_harvest_all(self, interaction: discord.Interaction):
        result = await asyncio.to_thread(self.game.harvest_all_farm, self.user_id, self.display_name)
        if result["plots_harvested"] == 0:
            self.last_result = "Nothing is ready to harvest yet."
        else:
            items_text = ", ".join(f"{qty}x {name}" for name, qty in result["harvested"].items())
            plot_word = "plot" if result["plots_harvested"] == 1 else "plots"
            self.last_result = f"🧺 Claimed {result['plots_harvested']} {plot_word}: **{items_text}**!"
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_plant_all(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 3)
        choice = select.values[0]
        if choice == "none":
            await interaction.response.defer()
            return
        result = await asyncio.to_thread(self.game.plant_all_farm, self.user_id, self.display_name, int(choice))
        if result["planted"] == 0:
            self.last_result = f"You don't have any **{result['item_name']}** to plant."
        else:
            plot_word = "plot" if result["planted"] == 1 else "plots"
            shortfall = f" ({result['empty_slots'] - result['planted']} plot(s) left empty — out of herb)" if result["planted"] < result["empty_slots"] else ""
            self.last_result = f"🌱 Planted **{result['planted']}x {result['item_name']}** across {result['planted']} {plot_word}{shortfall}."
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def build_embed(self) -> discord.Embed:
        overview = self.game.get_farm_overview(self.user_id, self.display_name)
        slot = self._current_slot(overview)
        embed = discord.Embed(title=f"🌾 Farm — Plot {self.selected_slot + 1}/{overview['max_slots']}", color=discord.Color.dark_green())

        if slot["state"] == "empty":
            embed.description = "This plot is empty. Plant a herb (from `/gather`) to grow more of it."
        elif slot["state"] == "growing":
            elapsed_seconds = slot["elapsed_hours"] * 3600
            total_seconds = slot["grow_hours"] * 3600
            remaining = max(0, total_seconds - elapsed_seconds)
            pct = min(100, slot["elapsed_hours"] / slot["grow_hours"] * 100)
            embed.description = (
                f"🌱 Growing **Tier {slot['tier']} Herb**\n"
                f"`{render_bar(elapsed_seconds, total_seconds)}` {pct:.0f}%\n"
                f"⏱️ {format_duration(remaining)} remaining"
            )
        else:
            embed.description = f"✅ **Tier {slot['tier']} Herb** is ready to harvest!"

        if self.last_result:
            embed.add_field(name="Result", value=self.last_result, inline=False)

        overview_text = "\n".join(f"Plot {s['slot_index'] + 1}: {_slot_summary(s)}" for s in overview["slots"])
        embed.add_field(name=f"🪴 All Plots ({overview['max_slots']})", value=overview_text, inline=False)

        farmer_rank = overview["player"]["farmer_rank"]
        embed.set_footer(
            text=f"Farmer: {professions.rank_name(farmer_rank)} "
            f"(x{professions.yield_multiplier(farmer_rank):.2f} harvest yield) • "
            f"+{self.game.FARM_SLOTS_PER_GREAT_REALM} plots per Great Realm reached."
        )
        return embed
