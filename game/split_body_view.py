import time

import discord

from . import manual_data, split_body
from .base_view import GameView
from .gathering import format_collected
from .ui_utils import format_duration, render_bar


def _format_result(result: dict) -> str:
    outcome = result["outcome"]
    if outcome == "no_soul":
        return "Your avatar hasn't chosen a soul yet — run `/avatar` to awaken it before sending it out."
    if outcome == "started":
        return (
            f"Your avatar splits off and departs to search for loot. Come back in "
            f"**{format_duration(split_body.SPLIT_BODY_DURATION_SECONDS)}** and click again to collect it."
        )
    if outcome == "in_progress":
        elapsed = result["elapsed_seconds"]
        remaining = result["remaining_seconds"]
        pct = min(100, elapsed / split_body.SPLIT_BODY_DURATION_SECONDS * 100)
        return (
            f"Your avatar is still out searching.\n"
            f"`{render_bar(elapsed, split_body.SPLIT_BODY_DURATION_SECONDS)}` {pct:.0f}%\n"
            f"⏱️ {format_duration(remaining)} remaining."
        )
    if outcome == "claimed":
        lines = [f"🌀 Your avatar returns with its haul: {format_collected(result['loot'])}"]
        if result["accessory"]:
            lines.append(f"✨ It also found an accessory: **{result['accessory']['affix'].name}**!")
        for page_id in result["pages"]:
            page = manual_data.PAGES.get(page_id)
            if page:
                lines.append(f"📜 It also recovered a manual page: **{page.name}**!")
        return "\n".join(lines)
    return ""


class SplitBodyView(GameView):
    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.last_result: str = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your avatar's mission.", ephemeral=True)
            return False
        return True

    def _build_components(self):
        self.clear_items()
        player = self.game.get_player_stats(self.user_id, self.display_name)
        started_ts = player["split_body_started_ts"]
        if started_ts == 0:
            label, style = "Send Avatar (3h)", discord.ButtonStyle.primary
        elif time.time() - started_ts >= split_body.SPLIT_BODY_DURATION_SECONDS:
            label, style = "Claim Loot", discord.ButtonStyle.success
        else:
            label, style = "Check Progress", discord.ButtonStyle.secondary
        button = discord.ui.Button(label=label, emoji="🌀", style=style, row=0)
        button.callback = self._on_progress
        self.add_item(button)

    async def _on_progress(self, interaction: discord.Interaction):
        result = self.game.progress_split_body(self.user_id, self.display_name)
        self.last_result = _format_result(result)
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    def build_embed(self) -> discord.Embed:
        player = self.game.get_player_stats(self.user_id, self.display_name)
        embed = discord.Embed(title="🌀 Split Body", color=discord.Color.dark_purple())

        started_ts = player["split_body_started_ts"]
        if started_ts == 0:
            status = "Your avatar is home, ready to be sent out to search for loot."
        else:
            elapsed = time.time() - started_ts
            if elapsed >= split_body.SPLIT_BODY_DURATION_SECONDS:
                status = "Your avatar has returned and is waiting for you to collect its loot!"
            else:
                pct = min(100, elapsed / split_body.SPLIT_BODY_DURATION_SECONDS * 100)
                remaining = split_body.SPLIT_BODY_DURATION_SECONDS - elapsed
                status = (
                    f"Your avatar is out searching for loot.\n"
                    f"`{render_bar(elapsed, split_body.SPLIT_BODY_DURATION_SECONDS)}` {pct:.0f}%\n"
                    f"⏱️ {format_duration(remaining)} remaining."
                )
        embed.add_field(name="Status", value=status, inline=False)

        if self.last_result:
            embed.add_field(name="Result", value=self.last_result, inline=False)

        embed.set_footer(text="Sends your Nascent Soul avatar out for 3 hours; it returns with essence crystals, essence pills, herbs, beast cores, Soul Nourishing Pills, Soul Crystals, and semi-rare equipment/manual pages.")
        return embed
