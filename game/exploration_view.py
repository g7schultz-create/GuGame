import asyncio
import os

import discord

from . import gathering, manual_data, professions, white_heaven
from .base_view import GameView
from .ui_utils import format_number, path_footer

HIGH_BANDS = ("Epic", "Legendary", "Mythic")


def _found_text(node: dict) -> str:
    if node["stones"]:
        main = f"**{format_number(node['stones'])}** spirit stones"
    elif node.get("page_id"):
        page = manual_data.PAGES.get(node["page_id"])
        main = f"**{node.get('page_quantity', 1)}x {page.name if page else node['page_id']}** manual page"
    else:
        main = f"**{node['quantity']}x {node['item_name']}**"
    if node.get("bonus_core"):
        main += f" ...and ✨ **1x {node['bonus_core']}**!"
    if node.get("bonus_essence_pill"):
        pill_name, pill_qty = node["bonus_essence_pill"]
        main += f" ...and ✨ **{pill_qty}x {pill_name}**!"
    if node.get("bonus_qi_ascension_pill"):
        pill_name, pill_qty = node["bonus_qi_ascension_pill"]
        main += f" ...and 🌟 **{pill_qty}x {pill_name}**!"
    if node.get("bonus_white_heaven_gu"):
        main += f" ...and ☁️ **{node['bonus_white_heaven_gu']}**!"
    return main


class ExplorationHuntView(GameView):
    """A /explore session: finds are pre-rolled (with this session's Luck/Explorer-rank
    bonuses already baked in) when the trail opens, then revealed and hunted down one at a
    time — mirrors MiningVeinView/GatheringPatchView exactly, just themed for exploring.
    Leaving early banks whatever was already found and forfeits the rest of the trail."""

    def __init__(self, user_id: int, game, display_name: str, nodes: list, white_heaven: bool = False):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.white_heaven = white_heaven
        self.nodes = nodes
        self.current_index = 0
        self.collected_stones = 0
        self.collected_items: dict = {}
        self.collected_pages: dict = {}  # {page_id: quantity} -- see GameManager.collect_exploration_hunt
        self.finished = False
        self.left_early = False
        self.message: discord.Message = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your trail to hunt.", ephemeral=True)
            return False
        return True

    def _build_components(self):
        self.clear_items()
        if self.finished:
            return
        hunt_button = discord.ui.Button(label="Hunt", emoji="🧭", style=discord.ButtonStyle.primary, row=0)
        hunt_button.callback = self._on_hunt
        self.add_item(hunt_button)

        leave_button = discord.ui.Button(label="Leave Early", emoji="🚪", style=discord.ButtonStyle.secondary, row=0)
        leave_button.callback = self._on_leave
        self.add_item(leave_button)

    def _finish(self):
        self.finished = True
        self.game.collect_exploration_hunt(self.user_id, self.collected_stones, self.collected_items, self.collected_pages)

    async def _on_hunt(self, interaction: discord.Interaction):
        # defer() first, THEN do the DB work -- see MiningVeinView._on_strike's identical
        # comment for why (a chain of asyncio.to_thread hops can exceed Discord's ~3s ACK
        # window under real load).
        await interaction.response.defer()
        node = self.nodes[self.current_index]
        if node["stones"]:
            self.collected_stones += node["stones"]
        elif node.get("page_id"):
            self.collected_pages[node["page_id"]] = self.collected_pages.get(node["page_id"], 0) + node.get("page_quantity", 1)
        else:
            self.collected_items[node["item_name"]] = self.collected_items.get(node["item_name"], 0) + node["quantity"]
        if node.get("bonus_core"):
            self.collected_items[node["bonus_core"]] = self.collected_items.get(node["bonus_core"], 0) + 1
        if node.get("bonus_essence_pill"):
            pill_name, pill_qty = node["bonus_essence_pill"]
            self.collected_items[pill_name] = self.collected_items.get(pill_name, 0) + pill_qty
        if node.get("bonus_qi_ascension_pill"):
            pill_name, pill_qty = node["bonus_qi_ascension_pill"]
            self.collected_items[pill_name] = self.collected_items.get(pill_name, 0) + pill_qty
        if node.get("bonus_white_heaven_gu"):
            gu_name = node["bonus_white_heaven_gu"]
            self.collected_items[gu_name] = self.collected_items.get(gu_name, 0) + 1
        self.current_index += 1
        if self.current_index >= len(self.nodes):
            await asyncio.to_thread(self._finish)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.edit_original_response(embed=embed, view=self)

    async def _on_leave(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.left_early = True
        await asyncio.to_thread(self._finish)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.edit_original_response(embed=embed, view=self)

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
        rank_index = player["explorer_rank"]
        return f"🍀 Luck: {effective_luck:.0f} • 🧭 Explorer: {professions.rank_name(rank_index)}"

    def _collected_text(self) -> str:
        # collected_pages is page_id-keyed (what the real grant needs -- see
        # GameManager.collect_exploration_hunt); merged into a name-keyed copy here purely
        # for display, reusing format_collected rather than duplicating its sort/formatting.
        display_items = dict(self.collected_items)
        for page_id, quantity in self.collected_pages.items():
            page = manual_data.PAGES.get(page_id)
            display_items[page.name if page else page_id] = display_items.get(page.name if page else page_id, 0) + quantity
        items_text = gathering.format_collected(display_items)
        if not self.collected_stones:
            return items_text
        stones_part = f"{format_number(self.collected_stones)} 🪙 spirit stones"
        if items_text == "Nothing yet":
            return stones_part
        return f"{stones_part}, {items_text}"

    def build_embed(self) -> discord.Embed:
        player = self.game.get_player_stats(self.user_id, self.display_name)
        embed = discord.Embed(color=discord.Color.dark_purple())

        if not self.finished:
            node = self.nodes[self.current_index]
            embed.title = "🧭 Trail Discovered!"
            embed.description = "_You pick up a promising trail through the wilds..._"
            if node.get("bonus_core") or node.get("bonus_essence_pill") or node.get("bonus_qi_ascension_pill") or node.get("bonus_white_heaven_gu") or node["band"] in HIGH_BANDS:
                embed.color = discord.Color.gold()
            embed.add_field(
                name=f"🔍 Hunt {self.current_index + 1}/{len(self.nodes)}",
                value=f"You sense {_found_text(node)} nearby ({node['band']}).",
                inline=False,
            )
            embed.add_field(name="📦 Collected", value=self._collected_text(), inline=True)
            embed.add_field(name="🧭 Finds Remaining", value=str(len(self.nodes) - self.current_index), inline=True)
        else:
            if self.left_early:
                embed.title = "🧭 Trail Abandoned"
                embed.description = "_You leave the rest of the trail behind and pocket what you've already found._"
            else:
                embed.title = "🧭 Trail Exhausted!"
                embed.description = "_The trail runs cold — you've claimed everything it had to give._"
            embed.add_field(name="📦 Total Collected", value=self._collected_text(), inline=False)

        embed.add_field(name="Stats", value=self._stats_line(player), inline=False)
        embed.set_footer(text=path_footer(player))
        # Same "attach once at send, keep pointing every later embed at it" convention as
        # hunt.py's identical block -- see its own comment for why.
        if self.white_heaven and os.path.exists(white_heaven.WHITE_HEAVEN_IMAGE_PATH):
            embed.set_image(url=f"attachment://{os.path.basename(white_heaven.WHITE_HEAVEN_IMAGE_PATH)}")
        return embed
