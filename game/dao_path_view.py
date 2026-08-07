from typing import Optional

import discord

from . import dao_paths
from .base_view import GameView
from .equipment import SPECIAL_STAT_TEXT

PATH_EMOJI = {
    "Strength": "💪", "Sword": "⚔️", "Fire": "🔥", "Blood": "🩸", "Soul": "👻",
    "Wisdom": "📖", "Luck": "🍀", "Refinement": "⚗️", "Formation": "🔯",
    "Enslavement": "⛓️", "Time": "⏳", "Space": "🌌", "Food": "🍲", "Transformation": "🔄",
}

ALLOCATE_AMOUNTS = [10, 100, 500]


def _format_bonus_line(key: str, value: float) -> str:
    formatter = SPECIAL_STAT_TEXT.get(key)
    return formatter(value) if formatter else f"{key}: {value:g}"


class DaoPathView(GameView):
    """/dao_path -- view banked Dao Marks and allocate them into any of the 14 Dao Paths (see
    game/dao_paths.py). A single-row Select for the path picker (14 options comfortably fits
    Discord's 25-option cap in exactly one row -- deliberately chosen over 14 buttons, the same
    fix views.py's _build_subcategory_select already applies for exactly this "too many options
    for button rows" shape) plus a row of allocate-amount buttons for whichever path is picked."""

    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.selected_path = next(iter(dao_paths.DAO_PATHS))
        self.last_result: Optional[str] = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your Dao Path allocation.", ephemeral=True)
            return False
        return True

    def _current_marks(self):
        player = self.game.get_player_stats(self.user_id, self.display_name)
        invested = self.game.db.get_dao_path_marks(self.user_id).get(self.selected_path, 0)
        return player["dao_marks_banked"], invested

    def _build_components(self):
        self.clear_items()
        options = [
            discord.SelectOption(
                label=path_name, value=path_name, emoji=PATH_EMOJI.get(path_name),
                default=(path_name == self.selected_path), description=spec.tagline[:100],
            )
            for path_name, spec in dao_paths.DAO_PATHS.items()
        ]
        select = discord.ui.Select(placeholder="Choose a Dao Path...", options=options, row=0)
        select.callback = self._on_select_path
        self.add_item(select)

        banked, invested = self._current_marks()
        maxed = invested >= dao_paths.DAO_MARKS_CAP_PER_PATH
        for amount in ALLOCATE_AMOUNTS:
            button = discord.ui.Button(
                label=f"+{amount:,}", style=discord.ButtonStyle.success, row=1,
                disabled=maxed or banked <= 0,
            )
            button.callback = self._make_allocate_callback(amount)
            self.add_item(button)
        max_button = discord.ui.Button(label="Max", style=discord.ButtonStyle.primary, row=1, disabled=maxed or banked <= 0)
        max_button.callback = self._make_allocate_callback(None)
        self.add_item(max_button)

    async def _on_select_path(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select))
        self.selected_path = select.values[0]
        self.last_result = None
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    def _make_allocate_callback(self, amount: Optional[int]):
        async def callback(interaction: discord.Interaction):
            banked, invested = self._current_marks()
            room = dao_paths.DAO_MARKS_CAP_PER_PATH - invested
            spend = min(banked, room) if amount is None else min(amount, banked, room)
            if spend <= 0:
                self.last_result = "Nothing to allocate — you're either out of banked Dao Marks or this path is already maxed."
            else:
                _, self.last_result = self.game.allocate_dao_marks(self.user_id, self.selected_path, spend)
            self._build_components()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

        return callback

    def build_embed(self) -> discord.Embed:
        banked, invested = self._current_marks()
        spec = dao_paths.DAO_PATHS[self.selected_path]
        current_bonus = dao_paths.scaled_bonus(self.selected_path, invested)
        embed = discord.Embed(
            title=f"🌀 {self.display_name}'s Dao Paths",
            description=(
                f"**Banked Dao Marks:** {banked:,}\n\n"
                "Allocate marks into any Dao Path below — once spent, they can never be reclaimed "
                "or moved to a different path, but you're free to invest in as many paths as you like."
            ),
            color=discord.Color.dark_purple(),
        )
        embed.add_field(
            name=f"{PATH_EMOJI.get(self.selected_path, '')} {self.selected_path} — {spec.tagline}",
            value=f"{spec.description}\n**Invested:** {invested:,} / {dao_paths.DAO_MARKS_CAP_PER_PATH:,}",
            inline=False,
        )
        if self.selected_path == "Transformation":
            embed.add_field(
                name="Daily /transmute Charges",
                value=f"**{dao_paths.transmute_charges(invested)}** / day",
                inline=False,
            )
        elif current_bonus:
            bonus_lines = "\n".join(f"{_format_bonus_line(key, value)}" for key, value in current_bonus.items())
            embed.add_field(name="Current Bonus", value=bonus_lines, inline=False)
        if self.last_result:
            embed.add_field(name="Result", value=self.last_result, inline=False)
        embed.set_footer(text="Dao Marks are earned from /hunt, /raid, /explore, /battlefield, /world_boss, and tournaments once you reach Spirit Severing — plus a lump sum on each Spirit Severing breakthrough.")
        return embed
