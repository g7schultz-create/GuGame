import asyncio
import discord

from . import gathering, professions
from .base_view import GameView
from .ui_utils import path_footer


class MiningVeinView(GameView):
    """A /mine session: nodes are pre-rolled (with this session's Luck/Miner-rank bonuses
    already baked in) when the vein opens, then revealed and struck one at a time. Leaving
    early banks whatever was already struck and forfeits the rest of the vein."""

    def __init__(self, user_id: int, game, display_name: str, nodes: list):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.nodes = nodes
        self.current_index = 0
        self.collected: dict = {}
        self.finished = False
        self.left_early = False
        self.message: discord.Message = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your mining vein.", ephemeral=True)
            return False
        return True

    def _build_components(self):
        self.clear_items()
        if self.finished:
            return
        strike_button = discord.ui.Button(label="Strike", emoji="⛏️", style=discord.ButtonStyle.primary, row=0)
        strike_button.callback = self._on_strike
        self.add_item(strike_button)

        leave_button = discord.ui.Button(label="Leave Early", emoji="🚪", style=discord.ButtonStyle.secondary, row=0)
        leave_button.callback = self._on_leave
        self.add_item(leave_button)

    def _finish(self):
        self.finished = True
        self.game.collect_mining_vein(self.user_id, self.collected)

    async def _on_strike(self, interaction: discord.Interaction):
        node = self.nodes[self.current_index]
        self.collected[node["item_name"]] = self.collected.get(node["item_name"], 0) + node["quantity"]
        self.current_index += 1
        if self.current_index >= len(self.nodes):
            await asyncio.to_thread(self._finish)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_leave(self, interaction: discord.Interaction):
        self.left_early = True
        await asyncio.to_thread(self._finish)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        if not self.finished:
            await asyncio.to_thread(self._finish)
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                embed = await asyncio.to_thread(self.build_embed)
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass

    def _stats_line(self, player: dict) -> str:
        bonuses = self.game.compute_equipment_bonuses(self.user_id)
        effective_luck = player["luck_stat"] + bonuses["stats"]["luck_stat"]
        rank_index = player["miner_rank"]
        return (
            f"🍀 Luck: {effective_luck:.0f} • ⛏️ Miner: {professions.rank_name(rank_index)} "
            f"(x{professions.yield_multiplier(rank_index):.2f} yield)"
        )

    def build_embed(self) -> discord.Embed:
        player = self.game.get_player_stats(self.user_id, self.display_name)
        embed = discord.Embed(color=discord.Color.dark_gold())

        collected_text = gathering.format_collected(self.collected)

        if not self.finished:
            embed.title = "⛏️ Vein Discovered!"
            embed.description = "_Your spiritual sense leads you to a hidden ore vein deep within the mountain..._"
            node = self.nodes[self.current_index]
            rarity = gathering.TIER_RARITY_NAMES[node["tier"]]
            embed.add_field(
                name=f"⛏️ Node {self.current_index + 1}/{len(self.nodes)}",
                value=f"You detect **{node['item_name']}** ({rarity}) embedded in the rock face.",
                inline=False,
            )
            embed.add_field(name="📦 Collected", value=collected_text, inline=True)
            embed.add_field(name="🪨 Nodes Remaining", value=str(len(self.nodes) - self.current_index), inline=True)
        else:
            if self.left_early:
                embed.title = "⛏️ Vein Abandoned"
                embed.description = "_You leave the rest of the vein behind and pocket what you've already struck._"
            else:
                embed.title = "⛏️ Vein Exhausted!"
                embed.description = "_The vein runs dry — you've claimed everything it had to give._"
            embed.add_field(name="📦 Total Collected", value=collected_text, inline=False)

        embed.add_field(name="Stats", value=self._stats_line(player), inline=False)
        embed.set_footer(text=path_footer(player))
        return embed
