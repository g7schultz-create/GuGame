import asyncio
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

    def _digs_used(self) -> int:
        return len(self.found)

    def _digs_exhausted(self) -> bool:
        return self._digs_used() >= treasure_hunt.MAX_CLICKS_PER_BOARD

    def _build_components(self):
        self.clear_items()
        exhausted = self._digs_exhausted()
        for index, category in enumerate(self.board):
            row = index // 5
            if self.revealed[index]:
                button = discord.ui.Button(
                    label=self.revealed_labels[index], emoji=self.revealed_emoji[index],
                    style=discord.ButtonStyle.secondary, row=row, disabled=True,
                )
            else:
                # The board still has 25 tiles, but only MAX_CLICKS_PER_BOARD digs are allowed
                # per visit -- once that's used up, every remaining bubble locks unrevealed.
                button = discord.ui.Button(label="?", emoji=UNREVEALED_EMOJI, style=discord.ButtonStyle.primary, row=row, disabled=exhausted)
                if not exhausted:
                    button.callback = self._make_tile_callback(index)
            self.add_item(button)

    def _make_tile_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            if self._digs_exhausted():  # guards a race between two near-simultaneous clicks
                return
            category = self.board[index]
            # defer() above, THEN the DB work -- see MiningVeinView._on_strike's identical
            # comment for why (a chain of asyncio.to_thread hops can exceed Discord's ~3s ACK
            # window under real load).
            emoji, label = await asyncio.to_thread(treasure_hunt.grant_tile_reward, self.game, self.user_id, self.display_name, category)
            self.revealed[index] = True
            self.revealed_emoji[index] = emoji
            self.revealed_labels[index] = category.title()
            self.found.append((emoji, label))
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.edit_original_response(embed=embed, view=self)

        return callback

    def build_embed(self) -> discord.Embed:
        max_digs = treasure_hunt.MAX_CLICKS_PER_BOARD
        embed = discord.Embed(
            title="🗺️ Forgotten Blessed Land",
            description=(
                "You've used up all your digs at this site!" if self._digs_exhausted() else
                f"A hidden site brimming with buried treasure. You get {max_digs} digs — click a "
                "bubble to spend one. One tile somewhere on the site hides a real treasure."
            ),
            color=discord.Color.gold(),
        )
        if self.found:
            lines = [f"{emoji} {label}" for emoji, label in self.found]
            embed.add_field(name=f"Dug up ({self._digs_used()}/{max_digs})", value="\n".join(lines)[:1024], inline=False)
        else:
            embed.add_field(name=f"Dug up (0/{max_digs})", value="Nothing dug up yet — click a bubble!", inline=False)
        return embed
