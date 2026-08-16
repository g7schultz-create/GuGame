"""
/breakthrough's confirm step -- shows the player their computed success chance and Qi cost
before they commit, rather than attempting immediately on command invocation. The actual
attempt (GameManager.attempt_breakthrough) only ever runs from the Confirm button's callback;
Cancel/timeout never touch it, so declining costs nothing.
"""

import asyncio

import discord

from . import chargen
from .base_view import GameView
from .ui_utils import format_number


def build_breakthrough_result_embed(display_name: str, result: dict, game) -> discord.Embed:
    """Same result rendering /breakthrough always used before the confirm step existed --
    moved here so BreakthroughConfirmView's own build_embed can reuse it once Confirm is
    clicked, rather than duplicating it."""
    # cog.py's /breakthrough already refuses to even show the confirm prompt for these two
    # cases (checked against breakthrough_status right before constructing the view), but
    # attempt_breakthrough re-derives both fresh and can still legitimately return either
    # shape if something changed in the gap between that check and the player clicking
    # Confirm (e.g. a breakthrough finished elsewhere raising realm_index past max, or Qi
    # spent by another action in between) -- neither has old_realm_name/new_realm_name, so
    # this must be handled before the success/failure branch below ever touches those keys.
    if result["outcome"] == "max_realm":
        return discord.Embed(
            title="🏔️ Peak Reached",
            description=f"{display_name} has reached the peak of known cultivation... for now.",
            color=discord.Color.dark_purple(),
        )
    if result["outcome"] == "insufficient_qi":
        return discord.Embed(
            title="💠 Not Enough Qi",
            description=(
                f"{display_name} no longer has enough Qi for this breakthrough — "
                f"needs **{format_number(result['qi_required'])}**, has **{format_number(result['player']['qi'])}**."
            ),
            color=discord.Color.dark_red(),
        )
    success = result["outcome"] == "success"
    great_realm_crossing = result.get("great_realm_crossing", False)

    if success and great_realm_crossing:
        title = "🌌 GREAT REALM BREAKTHROUGH!"
    elif success:
        title = "⚡ Breakthrough!"
    else:
        title = "💥 Breakthrough Failed"

    description = (
        f"{display_name} broke through from **{result['old_realm_name']}** to **{result['new_realm_name']}**!"
        if success
        else f"{display_name} failed to break through from **{result['old_realm_name']}**."
    )
    if success and result.get("new_realm_description"):
        description += f"\n_{result['new_realm_description']}_"

    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.gold() if success else discord.Color.dark_red(),
    )
    embed.add_field(name="🎲 Chance", value=f"{result['chance'] * 100:.1f}%", inline=True)
    embed.add_field(name="💠 Qi Spent", value=format_number(result['qi_cost']), inline=True)
    if success:
        growth_text = " • ".join(
            f"{chargen.STAT_LABELS[key]} +{format_number(amount)}" for key, amount in result["power_growth"].items()
        )
        embed.add_field(name="💪 Power Growth", value=growth_text, inline=False)
    if success and result["comprehension_proc"]:
        embed.add_field(name="📚 Dao Comprehension", value=f"Bonus insight refunded +{format_number(result['bonus_qi'])} qi!", inline=False)
    if success and result["stat_grown"]:
        embed.add_field(name="✨ Bonus Stat Growth", value=f"+1 {chargen.STAT_LABELS[result['stat_grown']]}!", inline=False)
    if success and result.get("godly_stat_grown"):
        embed.add_field(
            name="👑 Godly Growth",
            value=f"+{format_number(result['godly_stat_bonus'])} {chargen.STAT_LABELS[result['godly_stat_grown']]} (2% of current)!",
            inline=False,
        )
    if success and result.get("epic_vigor_granted"):
        minutes = game.EPIC_PHYSIQUE_BREAKTHROUGH_BUFF_DURATION_SECONDS // 60
        embed.add_field(
            name="💪 Breakthrough Vigor",
            value=f"Your Epic Physique surges with power — +{game.EPIC_PHYSIQUE_BREAKTHROUGH_BUFF_PCT * 100:.0f}% STR/ATK/DEF/SPD for {minutes} minutes!",
            inline=False,
        )
    if success and result.get("dao_marks_granted"):
        embed.add_field(
            name="🌀 Dao Marks",
            value=f"Sundering deeper into Spirit Severing grants **{format_number(result['dao_marks_granted'])}** Dao Marks! Allocate them with `/dao_path`.",
            inline=False,
        )
    if success and result.get("dao_essence_pick_available"):
        embed.add_field(
            name="🌌 Dao Essence",
            value="A Dao Essence awaits your choice — pick one with `/dao_essence`!",
            inline=False,
        )
    return embed


class BreakthroughConfirmView(GameView):
    def __init__(self, user_id: int, game, display_name: str, status: dict):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.status = status
        self.result: dict = None
        self.cancelled = False
        self.message: discord.Message = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your breakthrough attempt.", ephemeral=True)
            return False
        return True

    def _build_components(self):
        self.clear_items()
        active = self.result is None and not self.cancelled
        confirm_button = discord.ui.Button(label="Confirm Breakthrough", emoji="⚡", style=discord.ButtonStyle.success, disabled=not active)
        confirm_button.callback = self._on_confirm
        self.add_item(confirm_button)
        cancel_button = discord.ui.Button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.secondary, disabled=not active)
        cancel_button.callback = self._on_cancel
        self.add_item(cancel_button)

    async def _on_confirm(self, interaction: discord.Interaction):
        self.result = await asyncio.to_thread(self.game.attempt_breakthrough, self.user_id, self.display_name)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_cancel(self, interaction: discord.Interaction):
        self.cancelled = True
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        if self.result is None and not self.cancelled:
            self.cancelled = True
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                embed = await asyncio.to_thread(self.build_embed)
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass

    def build_embed(self) -> discord.Embed:
        if self.result is not None:
            return build_breakthrough_result_embed(self.display_name, self.result, self.game)
        if self.cancelled:
            embed = discord.Embed(
                title="Breakthrough Cancelled",
                description=f"{self.display_name} decided against attempting the breakthrough — no Qi spent.",
                color=discord.Color.greyple(),
            )
            return embed
        s = self.status
        embed = discord.Embed(
            title="⚡ Confirm Breakthrough",
            description=f"Attempt to break through from **{s['realm_name']}** to **{s['next_realm_name']}**?",
            color=discord.Color.dark_gold(),
        )
        embed.add_field(name="🎲 Success Chance", value=f"{s['chance'] * 100:.1f}%", inline=True)
        embed.add_field(name="💠 Qi Cost", value=format_number(s['qi_required']), inline=True)
        embed.set_footer(text="Failure still costs Qi (reduced by any deviation resistance) — this can't be undone once confirmed.")
        return embed
