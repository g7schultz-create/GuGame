import asyncio

import discord

from . import alchemy, items, professions
from .base_view import GameView


class AlchemyView(GameView):
    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.selected_type = items.ALCHEMY_PILL_TYPES[0]
        self.selected_tier = alchemy.MIN_TIER
        self.last_result: str = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your alchemy bench.", ephemeral=True)
            return False
        return True

    def _rank(self) -> int:
        return self.game.get_player_stats(self.user_id, self.display_name)["alchemist_rank"]

    def _is_locked(self) -> bool:
        return self._rank() < alchemy.rank_required_for_tier(self.selected_tier)

    def _build_components(self):
        self.clear_items()
        rank = self._rank()

        type_options = [
            discord.SelectOption(label=pill_type, value=pill_type, default=(pill_type == self.selected_type))
            for pill_type in items.ALCHEMY_PILL_TYPES
        ]
        type_select = discord.ui.Select(placeholder="Pill type...", options=type_options, row=0)
        type_select.callback = self._on_pick_type
        self.add_item(type_select)

        inventory = self.game.get_inventory(self.user_id)
        cost = alchemy.herb_cost(self.selected_type)
        tier_options = []
        for tier in range(alchemy.MIN_TIER, alchemy.MAX_TIER + 1):
            required = alchemy.rank_required_for_tier(tier)
            locked = rank < required
            label = f"Tier {tier} — needs {cost}x Tier {tier} Herb (have {inventory.get(alchemy.herb_name(tier), 0)})"
            if locked:
                label += f" 🔒 needs {professions.rank_name(required)}"
            tier_options.append(discord.SelectOption(label=label[:100], value=str(tier), default=(tier == self.selected_tier)))
        tier_select = discord.ui.Select(placeholder="Tier...", options=tier_options, row=1)
        tier_select.callback = self._on_pick_tier
        self.add_item(tier_select)

        owned = inventory.get(alchemy.herb_name(self.selected_tier), 0)
        max_batch = owned // cost if cost > 0 else 0
        locked = self._is_locked()

        craft1 = discord.ui.Button(
            label="Make 1", emoji="⚗️", style=discord.ButtonStyle.success, row=2, disabled=locked or owned < cost,
        )
        craft1.callback = self._make_craft_callback(1)
        self.add_item(craft1)

        craft10 = discord.ui.Button(
            label="Make 10", emoji="⏩", style=discord.ButtonStyle.success, row=2, disabled=locked or owned < cost * 10,
        )
        craft10.callback = self._make_craft_callback(10)
        self.add_item(craft10)

        craft_all = discord.ui.Button(
            label=f"Make All ({max_batch})", emoji="⏭️", style=discord.ButtonStyle.success, row=2, disabled=locked or max_batch < 1,
        )
        craft_all.callback = self._make_craft_callback(max_batch)
        self.add_item(craft_all)

    async def _on_pick_type(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 0)
        self.selected_type = select.values[0]
        self.last_result = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_tier(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 1)
        self.selected_tier = int(select.values[0])
        self.last_result = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def _make_craft_callback(self, attempts: int):
        async def callback(interaction: discord.Interaction):
            # Make All can be many craft_pill calls back-to-back (see
            # GameManager.craft_pill_multiple) -- defer first so we have up to 15 minutes to
            # finish instead of Discord's normal 3-second ack window (same fix as
            # premium_view.py's "until broke" reroll / InventoryView's Use All). Now also off
            # the event loop entirely via asyncio.to_thread.
            await interaction.response.defer()
            attempted, successes, last_result = await asyncio.to_thread(
                self.game.craft_pill_multiple, self.user_id, self.display_name, self.selected_type, self.selected_tier, attempts,
            )
            self.last_result = self._format_craft_result(attempted, successes, last_result)
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.edit_original_response(embed=embed, view=self)

        return callback

    def _format_craft_result(self, attempted: int, successes: int, last_result: dict) -> str:
        if attempted == 0:
            return last_result["reason"] if last_result else "You don't have enough herbs for that."
        item_name = last_result["item_name"]
        if attempted == 1:
            if successes:
                return f"✅ Success! Crafted **{item_name}**."
            refund_text = " (1 was salvaged back)" if last_result.get("herb_refunded") else ""
            return f"💥 The brew failed — {last_result['herb_cost']}x **{last_result['herb_name']}** was lost in the attempt{refund_text}."
        failures = attempted - successes
        return f"Attempted {attempted}x **{item_name}** — ✅ {successes} succeeded, 💥 {failures} failed."

    def build_embed(self) -> discord.Embed:
        player = self.game.get_player_stats(self.user_id, self.display_name)
        # Mirrors craft_pill's own chance calculation exactly (base rank chance + any
        # equipped alchemy_success_pct bonus) so this preview never drifts from what a
        # craft attempt actually rolls against.
        bonus_pct = self.game.compute_equipment_bonuses(self.user_id).get("alchemy_success_pct", 0)
        chance = min(1.0, professions.craft_success_chance(player["alchemist_rank"]) + bonus_pct)
        cost = alchemy.herb_cost(self.selected_type)
        herb = alchemy.herb_name(self.selected_tier)
        item_name = items.alchemy_pill_name(self.selected_type, self.selected_tier)
        owned = self.game.get_inventory(self.user_id).get(herb, 0)

        effect = items.alchemy_pill_effect_text(self.selected_type, self.selected_tier)

        embed = discord.Embed(title="⚗️ Alchemy", color=discord.Color.dark_green())
        embed.description = (
            f"**{item_name}**\n"
            f"✨ {effect}\n"
            f"🌿 Recipe: {cost}x {herb} (you have {owned})\n"
            f"🎯 Success chance: **{chance * 100:.0f}%** — Alchemist: {professions.rank_name(player['alchemist_rank'])}"
        )
        required_rank = alchemy.rank_required_for_tier(self.selected_tier)
        if self._is_locked():
            embed.add_field(
                name="🔒 Locked",
                value=f"Tier {self.selected_tier} needs Alchemist rank **{professions.rank_name(required_rank)}** — study Alchemist with `/study` to advance.",
                inline=False,
            )
        if self.last_result:
            embed.add_field(name="Result", value=self.last_result, inline=False)
        embed.set_footer(text="💡 Herbs are consumed whether the brew succeeds or not — study Alchemist to improve your odds.")
        return embed
