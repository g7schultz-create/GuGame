import asyncio
import discord

from . import world_regions
from .base_view import GameView
from .ui_utils import format_duration


class RegionView(GameView):
    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        status = self.game.get_world_region_status(user_id, display_name)
        self.selected_region = status["current"] or world_regions.WORLD_REGION_ORDER[0]
        self.last_message: str = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Run `/region` yourself to choose your own world region.", ephemeral=True)
            return False
        return True

    def _status(self) -> dict:
        return self.game.get_world_region_status(self.user_id, self.display_name)

    def _build_components(self):
        self.clear_items()
        status = self._status()

        region_select = discord.ui.Select(
            placeholder=f"Region: {world_regions.WORLD_REGIONS[self.selected_region].name}",
            options=[
                discord.SelectOption(
                    label=region.name, value=key, emoji=region.emoji, description=region.tagline[:100],
                    default=(key == self.selected_region),
                )
                for key, region in world_regions.WORLD_REGIONS.items()
            ],
            disabled=not status["eligible"],
            row=0,
        )
        region_select.callback = self._on_pick_region
        self.add_item(region_select)

        already_here = status["current"] == self.selected_region
        on_cooldown = status["remaining_seconds"] > 0
        travel_button = discord.ui.Button(
            label="Already Here" if already_here else ("On Cooldown" if on_cooldown else "Travel Here"),
            emoji="🧭", style=discord.ButtonStyle.primary, row=1,
            disabled=not status["eligible"] or already_here or on_cooldown,
        )
        travel_button.callback = self._on_travel
        self.add_item(travel_button)

    async def _on_pick_region(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 0)
        self.selected_region = select.values[0]
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_travel(self, interaction: discord.Interaction):
        result = await asyncio.to_thread(self.game.set_world_region, self.user_id, self.display_name, self.selected_region)
        if not result["ok"]:
            if result["reason"] == "cooldown":
                self.last_message = f"🧭 You just changed regions — travel again in {format_duration(result['remaining_seconds'])}."
            elif result["reason"] == "ineligible":
                self.last_message = "🚫 Only Nascent Soul and below can settle in a mortal region — the immortal areas above it aren't open yet."
            else:
                self.last_message = "❌ Couldn't travel there."
        else:
            self.last_message = f"{result['region'].emoji} You settle into **{result['region'].name}**."
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def build_embed(self) -> discord.Embed:
        status = self._status()
        embed = discord.Embed(title="🗺️ World Region", color=discord.Color.dark_teal())
        current = world_regions.WORLD_REGIONS.get(status["current"]) if status["current"] else None
        embed.description = (
            f"Current region: {f'{current.emoji} **{current.name}**' if current else '*None chosen yet*'}\n"
            + ("" if status["eligible"] else "\n🚫 Only Nascent Soul and below can hold a mortal world region — the immortal areas above it aren't open yet.")
        )
        picked = world_regions.WORLD_REGIONS[self.selected_region]
        embed.add_field(name=f"{picked.emoji} {picked.name}", value=picked.description, inline=False)
        if status["current"] and status["remaining_seconds"] > 0:
            embed.add_field(name="Travel Cooldown", value=f"⏳ {format_duration(status['remaining_seconds'])} until you can move again.", inline=False)
        if self.last_message:
            embed.add_field(name="Result", value=self.last_message, inline=False)
        embed.set_footer(text="Pick a region, then Travel Here. Your region shapes your /mine, /gather, /explore, /hunt, and /raid.")
        return embed
