import asyncio
import os

import discord

from . import black_heaven
from .base_view import GameView
from .ui_utils import format_duration


class BlackHeavenView(GameView):
    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.last_message: str = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Run `/black_heaven` yourself to travel there.", ephemeral=True)
            return False
        return True

    def _status(self) -> dict:
        return self.game.get_black_heaven_status(self.user_id, self.display_name)

    def _build_components(self):
        self.clear_items()
        status = self._status()
        state = status["status"]

        if state == "away":
            button = discord.ui.Button(
                label="Depart for Black Heaven", emoji="🌑", style=discord.ButtonStyle.primary,
                disabled=not status["eligible"], row=0,
            )
            button.callback = self._on_depart
        elif state == "present":
            button = discord.ui.Button(label="Return Home", emoji="🌑", style=discord.ButtonStyle.primary, row=0)
            button.callback = self._on_return
        else:  # traveling_there / traveling_back -- nothing to click, the tick auto-completes it
            button = discord.ui.Button(
                label=f"{black_heaven.STATUSES[state].label}...", emoji="⏳", style=discord.ButtonStyle.secondary,
                disabled=True, row=0,
            )
        self.add_item(button)

    async def _on_depart(self, interaction: discord.Interaction):
        result = await asyncio.to_thread(self.game.start_black_heaven_travel, self.user_id, self.display_name)
        if not result["ok"]:
            self.last_message = (
                "🚫 Only Dao Seeking realm and above can travel to Black Heaven."
                if result["reason"] == "ineligible"
                else "You're already traveling or already there."
            )
        else:
            remaining = (await asyncio.to_thread(self._status))["remaining_seconds"]
            self.last_message = f"🌑 You set out for Black Heaven — arriving in {format_duration(remaining)}."
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_return(self, interaction: discord.Interaction):
        result = await asyncio.to_thread(self.game.start_black_heaven_return, self.user_id, self.display_name)
        if not result["ok"]:
            self.last_message = (
                "You can't leave mid-Search — finish or abandon your Search Black Heaven run first."
                if result.get("reason") == "active_search"
                else "You're not currently in Black Heaven."
            )
        else:
            remaining = (await asyncio.to_thread(self._status))["remaining_seconds"]
            self.last_message = f"🌑 You start the journey home — arriving in {format_duration(remaining)}."
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def build_embed(self) -> discord.Embed:
        status = self._status()
        state = status["status"]
        info = black_heaven.STATUSES[state]
        embed = discord.Embed(title=f"{info.emoji} Black Heaven", color=discord.Color.from_rgb(20, 20, 26))
        embed.description = black_heaven.FLAVOR_TEXT
        embed.add_field(name="Status", value=f"{info.emoji} **{info.label}**", inline=False)
        if state in ("traveling_there", "traveling_back") and status["remaining_seconds"] > 0:
            embed.add_field(name="Time Remaining", value=f"⏳ {format_duration(status['remaining_seconds'])}", inline=False)
        if not status["eligible"] and state == "away":
            embed.add_field(
                name="Locked",
                value="🚫 Only Dao Seeking realm and above can travel to Black Heaven.",
                inline=False,
            )
        if state == "present":
            embed.add_field(
                name="What To Do Here",
                value="⚔️ Run `/search_black_heaven` to pop bubbles for a chance at 15 new Unique Gu, "
                      "essence crystals, essence pills, and Rank 8 materials — some bubbles hide "
                      "very dangerous guardians instead.",
                inline=False,
            )
        if self.last_message:
            embed.add_field(name="Result", value=self.last_message, inline=False)
        if os.path.exists(black_heaven.BLACK_HEAVEN_IMAGE_PATH):
            embed.set_image(url=f"attachment://{os.path.basename(black_heaven.BLACK_HEAVEN_IMAGE_PATH)}")
        return embed


def build_black_heaven_image_file() -> discord.File:
    """Same os.path.exists-guarded pattern as white_heaven_view.build_white_heaven_image_file
    -- None (no attachment) until the user supplies the actual PNG, never a crash."""
    if os.path.exists(black_heaven.BLACK_HEAVEN_IMAGE_PATH):
        return discord.File(black_heaven.BLACK_HEAVEN_IMAGE_PATH, filename=os.path.basename(black_heaven.BLACK_HEAVEN_IMAGE_PATH))
    return None
