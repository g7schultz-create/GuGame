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

    def _max_affordable_batches(self, tier: int) -> int:
        """How many pills at this tier can actually be made right now -- every required herb
        (see alchemy.herb_requirements -- a full Tier 1-8 ladder at Tier 8, not just the top
        tier) AND every bonus ingredient (see alchemy.bonus_ingredients, real for Tier 8 only)
        all have to clear, so this is the MINIMUM across all of them."""
        inventory = self.game.get_inventory(self.user_id)
        needed = {**alchemy.herb_requirements(self.selected_type, tier), **alchemy.bonus_ingredients(tier)}
        limits = [inventory.get(mat, 0) // qty if qty > 0 else 0 for mat, qty in needed.items()]
        return min(limits) if limits else 0

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
        tier_options = []
        for tier in range(alchemy.MIN_TIER, alchemy.MAX_TIER + 1):
            required = alchemy.rank_required_for_tier(tier)
            locked = rank < required
            herb_needs = alchemy.herb_requirements(self.selected_type, tier)
            if len(herb_needs) > 1:
                # Tier 8's real ladder (1x each of Tier 1-7 Herb plus 1x Tier 8 Herb) is too
                # long to spell out herb-by-herb and still fit Discord's 100-char option label
                # alongside the bonus-ingredient/lock text below -- build_embed's own recipe
                # lines (further down) list every herb individually instead.
                label = f"Tier {tier} — needs 1x each of Tier 1-{tier} Herb"
            else:
                herb, cost = next(iter(herb_needs.items()))
                label = f"Tier {tier} — needs {cost}x {herb} (have {inventory.get(herb, 0)})"
            bonus = alchemy.bonus_ingredients(tier)
            if bonus:
                label += " + " + ", ".join(f"{qty}x {mat}" for mat, qty in bonus.items())
            if locked:
                label += f" 🔒 needs {professions.rank_name(required)}"
            tier_options.append(discord.SelectOption(label=label[:100], value=str(tier), default=(tier == self.selected_tier)))
        tier_select = discord.ui.Select(placeholder="Tier...", options=tier_options, row=1)
        tier_select.callback = self._on_pick_tier
        self.add_item(tier_select)

        max_batch = self._max_affordable_batches(self.selected_tier)
        locked = self._is_locked()

        craft1 = discord.ui.Button(
            label="Make 1", emoji="⚗️", style=discord.ButtonStyle.success, row=2, disabled=locked or max_batch < 1,
        )
        craft1.callback = self._make_craft_callback(1)
        self.add_item(craft1)

        craft10 = discord.ui.Button(
            label="Make 10", emoji="⏩", style=discord.ButtonStyle.success, row=2, disabled=locked or max_batch < 10,
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
            materials_text = ", ".join(f"{qty}x {mat}" for mat, qty in last_result["materials"].items())
            message = f"💥 The brew failed — {materials_text} was lost in the attempt."
            if last_result.get("materials_refunded"):
                refund_text = ", ".join(f"{qty}x {mat}" for mat, qty in last_result["materials_refunded"].items())
                message += f" ✨ Salvaged {refund_text} back."
            return message
        failures = attempted - successes
        return f"Attempted {attempted}x **{item_name}** — ✅ {successes} succeeded, 💥 {failures} failed."

    def build_embed(self) -> discord.Embed:
        player = self.game.get_player_stats(self.user_id, self.display_name)
        # Mirrors craft_pill's own chance calculation exactly (base rank chance + any
        # equipped alchemy_success_pct bonus) so this preview never drifts from what a
        # craft attempt actually rolls against.
        bonus_pct = self.game.compute_equipment_bonuses(self.user_id).get("alchemy_success_pct", 0)
        chance = min(1.0, professions.craft_success_chance(player["alchemist_rank"]) + bonus_pct)
        item_name = items.alchemy_pill_name(self.selected_type, self.selected_tier)
        inventory = self.game.get_inventory(self.user_id)

        effect = items.alchemy_pill_effect_text(self.selected_type, self.selected_tier)

        herb_needs = alchemy.herb_requirements(self.selected_type, self.selected_tier)
        recipe_lines = [
            f"🌿 Recipe: {qty}x {herb} (you have {inventory.get(herb, 0)})" if i == 0
            else f"　+ {qty}x {herb} (you have {inventory.get(herb, 0)})"
            for i, (herb, qty) in enumerate(herb_needs.items())
        ]
        for mat, qty in alchemy.bonus_ingredients(self.selected_tier).items():
            recipe_lines.append(f"　+ {qty}x {mat} (you have {inventory.get(mat, 0)})")

        embed = discord.Embed(title="⚗️ Alchemy", color=discord.Color.dark_green())
        embed.description = (
            f"**{item_name}**\n"
            f"✨ {effect}\n"
            + "\n".join(recipe_lines) + "\n"
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
