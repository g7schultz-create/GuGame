"""
RegionDreamRealmView -- the "region_dream_realm" discovery type found via /region actions
(see GameManager.maybe_trigger_region_discovery). "Stat checks checking if the cultivator's
speed, attack, defense, or luck is good enough for the reward." Single-shot: unlike the
existing narrative-stage /search dream realm (DiscoveryView's room-by-room loop, untouched by
this), there's nothing to walk through room-by-room -- one Attempt rolls the trial and ends it.
"""

import asyncio
import discord

from . import search_data
from .base_view import GameView
from .equipment import FOUNDATION_STAT_LABELS


class RegionDreamRealmView(GameView):
    def __init__(self, user_id: int, game, display_name: str, discovery: dict):
        super().__init__(timeout=600)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.discovery = discovery
        self.finished = False
        self.abandoned = False
        self.result: dict = None
        self.message: discord.Message = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Run `/discovery` yourself to attempt your own trial.", ephemeral=True)
            return False
        return True

    def _build_components(self):
        self.clear_items()
        active = not self.finished and not self.abandoned

        attempt_button = discord.ui.Button(label="Attempt the Trial", emoji="💤", style=discord.ButtonStyle.primary, row=0, disabled=not active)
        attempt_button.callback = self._on_attempt
        self.add_item(attempt_button)

        leave_button = discord.ui.Button(label="Leave", emoji="🚪", style=discord.ButtonStyle.secondary, row=0, disabled=not active)
        leave_button.callback = self._on_leave
        self.add_item(leave_button)

        back_button = discord.ui.Button(label="Back to Search", emoji="🔙", style=discord.ButtonStyle.secondary, row=0)
        back_button.callback = self._on_back_to_search
        self.add_item(back_button)

    async def _on_attempt(self, interaction: discord.Interaction):
        self.result = await asyncio.to_thread(self.game.resolve_region_dream_realm, self.user_id, self.display_name, self.discovery)
        self.finished = True
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_leave(self, interaction: discord.Interaction):
        await asyncio.to_thread(self.game.abandon_discovery, self.user_id, self.discovery["discovery_id"])
        self.abandoned = True
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_back_to_search(self, interaction: discord.Interaction):
        """Returns to the Search hub on this same message — see DiscoveryView's identical
        handler for why self.stop() and reopen_discovery both matter here. Only reachable
        before attempting the trial (the button's disabled once self.finished), so this never
        lets a completed trial be re-attempted."""
        from .search_view import SearchView  # local import: search_view imports this module
        self.stop()
        await asyncio.to_thread(self.game.reopen_discovery, self.discovery["discovery_id"])
        new_view = SearchView( self.user_id, self.game, self.display_name)
        embed = await asyncio.to_thread(new_view.build_embed)
        await interaction.response.edit_message(embed=embed, view=new_view)
        new_view.message = await interaction.original_response()

    async def on_timeout(self):
        if not self.finished and not self.abandoned:
            await asyncio.to_thread(self.game.abandon_discovery, self.user_id, self.discovery["discovery_id"])
            self.abandoned = True
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                embed = await asyncio.to_thread(self.build_embed)
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass

    def build_embed(self) -> discord.Embed:
        d = self.discovery
        theme = next((t for t in search_data.REGION_DREAM_REALM_THEMES if t["name"] == d["theme"]), None)
        stat_label = FOUNDATION_STAT_LABELS.get(theme["stat"], theme["stat"]) if theme else "?"

        if self.finished:
            status_text = "Passed!" if self.result["passed"] else "Failed"
            color = discord.Color.green() if self.result["passed"] else discord.Color.dark_red()
        elif self.abandoned:
            status_text = "Left"
            color = discord.Color.greyple()
        else:
            status_text = "Awaiting Attempt"
            color = discord.Color.dark_purple()

        embed = discord.Embed(title=f"💤 {d['theme']} • {status_text}", color=color)
        embed.description = f"Rank **{d['rank']}** • Difficulty **{d['difficulty']}** • Checks your **{stat_label}**."

        if self.finished:
            r = self.result
            embed.add_field(
                name="Result",
                value=f"Your {stat_label}: **{r['effective_stat']}** vs. threshold **{r['threshold']}**\n{r['reward_text']}",
                inline=False,
            )
            embed.set_footer(text="This trial is complete — run /search to find another.")
        elif self.abandoned:
            embed.set_footer(text="You walked away before attempting the trial.")
        else:
            embed.set_footer(text="Attempt the trial once you're ready — there's no going back mid-attempt.")
        return embed
