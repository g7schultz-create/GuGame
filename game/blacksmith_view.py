import asyncio
import discord

from . import blacksmith, equipment, professions
from .base_view import GameView


class BlacksmithView(GameView):
    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.selected_type = equipment.BLACKSMITH_GEAR_TYPES[0]
        self.selected_tier = blacksmith.MIN_TIER
        self.last_result: str = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your forge.", ephemeral=True)
            return False
        return True

    def _rank(self) -> int:
        return self.game.get_player_stats(self.user_id, self.display_name)["blacksmith_rank"]

    def _is_locked(self) -> bool:
        return self._rank() < blacksmith.rank_required_for_tier(self.selected_tier)

    def _can_afford(self) -> bool:
        inventory = self.game.get_inventory(self.user_id)
        needed = blacksmith.recipe(self.selected_tier)
        return all(inventory.get(mat, 0) >= qty for mat, qty in needed.items())

    def _build_components(self):
        self.clear_items()
        rank = self._rank()

        type_options = [
            discord.SelectOption(
                label=f"{gear_type} ({equipment.BLACKSMITH_GEAR_SLOT_TYPE[gear_type]})",
                value=gear_type, default=(gear_type == self.selected_type),
            )
            for gear_type in equipment.BLACKSMITH_GEAR_TYPES
        ]
        type_select = discord.ui.Select(placeholder="Gear type...", options=type_options, row=0)
        type_select.callback = self._on_pick_type
        self.add_item(type_select)

        tier_options = []
        for tier in range(blacksmith.MIN_TIER, blacksmith.MAX_TIER + 1):
            required = blacksmith.rank_required_for_tier(tier)
            locked = rank < required
            label = f"Tier {tier}" + (f" 🔒 needs {professions.rank_name(required)}" if locked else "")
            tier_options.append(discord.SelectOption(label=label[:100], value=str(tier), default=(tier == self.selected_tier)))
        tier_select = discord.ui.Select(placeholder="Tier...", options=tier_options, row=1)
        tier_select.callback = self._on_pick_tier
        self.add_item(tier_select)

        craft_button = discord.ui.Button(
            label="Craft", emoji="🔨", style=discord.ButtonStyle.success, row=2,
            disabled=self._is_locked() or not self._can_afford(),
        )
        craft_button.callback = self._on_craft
        self.add_item(craft_button)

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

    async def _on_craft(self, interaction: discord.Interaction):
        result = await asyncio.to_thread(self.game.craft_gear, self.user_id, self.display_name, self.selected_type, self.selected_tier)
        if not result["ok"]:
            self.last_result = result["reason"]
        elif result["success"]:
            stats_text = equipment.describe_stat_bonuses(result["stat_bonuses"])
            self.last_result = f"✅ Success! Forged **{result['item_name']}** — {stats_text} (Power {result['power_score']:.1f})."
        else:
            materials_text = ", ".join(f"{qty}x {mat}" for mat, qty in result["materials"].items())
            self.last_result = f"💥 The forging failed — {materials_text} was lost in the attempt."
        if result.get("materials_refunded"):
            refund_text = ", ".join(f"{qty}x {mat}" for mat, qty in result["materials_refunded"].items())
            self.last_result += f" ✨ Your root salvaged {refund_text} back."
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def build_embed(self) -> discord.Embed:
        player = self.game.get_player_stats(self.user_id, self.display_name)
        # Space Dao Path's crafting_success_pct -- mirrors craft_gear's own chance calculation
        # so this preview doesn't drift from what a craft attempt actually rolls against.
        space_bonus = self.game.get_dao_path_totals(self.user_id).get("crafting_success_pct", 0)
        chance = min(1.0, professions.craft_success_chance(player["blacksmith_rank"]) + space_bonus)
        needed = blacksmith.recipe(self.selected_tier)
        inventory = self.game.get_inventory(self.user_id)
        budget = blacksmith.TIER_PCT_BUDGET[self.selected_tier]
        stat_names = ", ".join(equipment.FOUNDATION_STAT_LABELS[equipment.CRAFTED_GEAR_PCT_TO_FLAT[key]] for key in blacksmith.STAT_KEYS)

        recipe_lines = "\n".join(f"• {qty}x {mat} (have {inventory.get(mat, 0)})" for mat, qty in needed.items())

        embed = discord.Embed(title="🔨 Blacksmith", color=discord.Color.dark_grey())
        embed.description = (
            f"**{self.selected_type}** (T{self.selected_tier}) — {equipment.BLACKSMITH_GEAR_SLOT_TYPE[self.selected_type]} slot\n"
            f"🎲 Rolls **{budget}%** total, split across 2-4 random stats ({stat_names}) — every forged piece is unique, "
            "and scales with your own stats no matter how strong you get.\n\n"
            f"Recipe:\n{recipe_lines}\n\n"
            f"Success chance: **{chance * 100:.0f}%** — Blacksmith: {professions.rank_name(player['blacksmith_rank'])}"
        )
        required_rank = blacksmith.rank_required_for_tier(self.selected_tier)
        if self._is_locked():
            embed.add_field(
                name="🔒 Locked",
                value=f"Tier {self.selected_tier} needs Blacksmith rank **{professions.rank_name(required_rank)}** — study Blacksmith with `/study` to advance.",
                inline=False,
            )
        if self.last_result:
            embed.add_field(name="Result", value=self.last_result, inline=False)
        embed.set_footer(text="Materials are consumed whether the forging succeeds or not — see /weapons for everything you've forged.")
        return embed
