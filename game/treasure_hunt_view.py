import discord

from . import treasure_hunt
from .base_view import GameView

UNREVEALED_EMOJI = "🫧"


class TreasureHuntView(GameView):
    def __init__(self, user_id: int, game, display_name: str, board: list):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.board = board  # 25 tile categories, index -> row-major grid position
        self.revealed = [False] * len(board)
        self.revealed_emoji = [None] * len(board)
        self.revealed_labels = [None] * len(board)
        self.found: list = []  # (emoji, label) for every tile clicked so far, in click order
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your Blessed Land site.", ephemeral=True)
            return False
        return True

    def _build_components(self):
        self.clear_items()
        for index, category in enumerate(self.board):
            row = index // 5
            if self.revealed[index]:
                button = discord.ui.Button(
                    label=self.revealed_labels[index], emoji=self.revealed_emoji[index],
                    style=discord.ButtonStyle.secondary, row=row, disabled=True,
                )
            else:
                button = discord.ui.Button(label="?", emoji=UNREVEALED_EMOJI, style=discord.ButtonStyle.primary, row=row)
                button.callback = self._make_tile_callback(index)
            self.add_item(button)

    def _make_tile_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            category = self.board[index]
            emoji, label = treasure_hunt.grant_tile_reward(self.game, self.user_id, self.display_name, category)
            self.revealed[index] = True
            self.revealed_emoji[index] = emoji
            self.revealed_labels[index] = category.title()
            self.found.append((emoji, label))
            self._build_components()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

        return callback

    def build_embed(self) -> discord.Embed:
        all_revealed = all(self.revealed)
        embed = discord.Embed(
            title="🗺️ Forgotten Blessed Land",
            description=(
                "The site has been fully excavated!" if all_revealed else
                "A hidden site brimming with buried treasure. Click a bubble to dig it up — "
                "one tile always hides a real treasure."
            ),
            color=discord.Color.gold(),
        )
        if self.found:
            lines = [f"{emoji} {label}" for emoji, label in self.found]
            embed.add_field(name=f"Found so far ({len(self.found)}/{len(self.board)})", value="\n".join(lines)[:1024], inline=False)
        else:
            embed.add_field(name="Found so far (0/25)", value="Nothing dug up yet — click a bubble!", inline=False)
        return embed
