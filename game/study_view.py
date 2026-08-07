import time

import discord

from . import professions
from .base_view import GameView
from .ui_utils import format_duration, render_bar


def _format_result(result: dict) -> str:
    outcome = result["outcome"]
    if outcome == "maxed":
        return f"**{result['profession']}** is already at **{professions.rank_name(result['rank'])}** — the peak of this profession."
    if outcome == "busy":
        return f"You're already studying **{result['studying']}** — finish that before starting something else."
    if outcome == "started":
        return (
            f"You begin studying **{result['profession']}**. Come back in "
            f"**{format_duration(result['hours_required'] * 3600)}** and click it again to complete it."
        )
    if outcome == "in_progress":
        remaining = max(0, result["hours_required"] - result["hours_elapsed"]) * 3600
        pct = min(100, result["hours_elapsed"] / result["hours_required"] * 100)
        return (
            f"Still studying **{result['profession']}**.\n"
            f"`{render_bar(result['hours_elapsed'], result['hours_required'])}` {pct:.0f}%\n"
            f"⏱️ {format_duration(remaining)} remaining."
        )
    if outcome == "leveled_up":
        return f"🎉 Your studies bear fruit — **{result['profession']}** advances to **{professions.rank_name(result['new_rank'])}**!"
    if outcome == "not_studying":
        return "You're not currently studying anything to cancel."
    if outcome == "cancelled":
        return (
            f"❌ You abandon your studies in **{result['profession']}** — "
            f"**{format_duration(result['hours_lost'] * 3600)}** of progress is lost."
        )
    return ""


class StudyView(GameView):
    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.last_result: str = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your profession study.", ephemeral=True)
            return False
        return True

    def _build_components(self):
        self.clear_items()
        player = self.game.get_player_stats(self.user_id, self.display_name)
        studying = player["studying_profession"]
        for index, profession in enumerate(professions.PROFESSIONS):
            rank_index = player[professions.RANK_COLUMN[profession]]
            maxed = rank_index >= professions.MAX_RANK_INDEX
            is_active = profession == studying
            button = discord.ui.Button(
                label=profession,
                emoji=professions.PROFESSION_EMOJI[profession],
                style=discord.ButtonStyle.success if is_active else discord.ButtonStyle.primary,
                row=index // 4,
                disabled=maxed,
            )
            button.callback = self._make_study_callback(profession)
            self.add_item(button)

        cancel_button = discord.ui.Button(
            label="Cancel Study", emoji="❌", style=discord.ButtonStyle.danger,
            row=2, disabled=not studying,
        )
        cancel_button.callback = self._on_cancel
        self.add_item(cancel_button)

    def _make_study_callback(self, profession: str):
        async def callback(interaction: discord.Interaction):
            result = self.game.study(self.user_id, self.display_name, profession)
            self.last_result = _format_result(result)
            self._build_components()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

        return callback

    async def _on_cancel(self, interaction: discord.Interaction):
        result = self.game.cancel_study(self.user_id, self.display_name)
        self.last_result = _format_result(result)
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    def build_embed(self) -> discord.Embed:
        player = self.game.get_player_stats(self.user_id, self.display_name)
        embed = discord.Embed(title="🎓 Professions", color=discord.Color.dark_purple())

        lines = []
        for profession in professions.PROFESSIONS:
            rank_index = player[professions.RANK_COLUMN[profession]]
            emoji = professions.PROFESSION_EMOJI[profession]
            rank_label = professions.rank_name(rank_index)
            line = f"{emoji} **{profession}**: {rank_label} ({rank_index}/{professions.MAX_RANK_INDEX})"
            if player["studying_profession"] == profession:
                required = professions.hours_required(rank_index)
                elapsed = (time.time() - player["studying_started_ts"]) / 3600
                if required and elapsed < required:
                    pct = min(100, elapsed / required * 100)
                    line += f" — ⏳ studying, {pct:.0f}%"
                else:
                    line += " — ✅ ready to complete!"
            lines.append(line)
        embed.add_field(name="Current Levels", value="\n".join(lines), inline=False)

        if self.last_result:
            embed.add_field(name="Result", value=self.last_result, inline=False)

        embed.set_footer(text="Click a profession to start studying it, check progress, or complete one already in progress. Cancel Study abandons your current study and its progress.")
        return embed
