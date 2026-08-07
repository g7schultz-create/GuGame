import discord

from . import realms
from .base_view import GameView

MEDALS = ["🥇", "🥈", "🥉"]

# (key, board_key, title, emoji, value_fn) — key drives the button/active-tab state,
# board_key indexes GameManager.get_leaderboard()'s returned dict.
CATEGORIES = [
    ("realm", "by_realm", "Highest Realm", "🏔️", lambda e: realms.realm_name(e["realm_index"])),
    ("stones", "by_stones", "Most Spirit Stones", "🪙", lambda e: f"{e['spirit_stones']:,}"),
    ("power", "by_power", "Highest Combat Power", "⚔️", lambda e: f"{e['combat_power']:,}"),
    ("speed", "by_speed", "Fastest Cultivation Speed", "⚡", lambda e: f"{e['qi_rate']:,.2f} qi/min"),
    ("boss_damage", "by_boss_damage", "World Boss Damage", "🐉", lambda e: f"{e['damage_dealt']:,} damage ({e['attacks']} strikes)"),
]


def _format_entries(entries, value_fn) -> str:
    if not entries:
        return "No confirmed cultivators yet."
    lines = []
    for i, e in enumerate(entries):
        rank = MEDALS[i] if i < len(MEDALS) else f"`#{i + 1}`"
        lines.append(f"{rank} **{e['name']}** — {value_fn(e)}")
    return "\n".join(lines)[:1024]


class LeaderboardView(GameView):
    """One category shown at a time (a button per category) rather than all three squeezed
    into a single embed — lets each list show a lot more than 5 entries without fighting the
    other two categories for the embed's total character budget."""

    def __init__(self, game, top_n: int = None):
        super().__init__(timeout=180)
        self.game = game
        self.top_n = top_n or game.LEADERBOARD_TOP_N
        self.active_category = CATEGORIES[0][0]
        self._build_components()

    def _build_components(self):
        self.clear_items()
        for key, _, title, emoji, _ in CATEGORIES:
            button = discord.ui.Button(label=title, emoji=emoji, row=0)
            is_active = key == self.active_category
            button.style = discord.ButtonStyle.primary if is_active else discord.ButtonStyle.secondary
            button.disabled = is_active
            button.callback = self._make_callback(key)
            self.add_item(button)

    def _make_callback(self, key: str):
        async def callback(interaction: discord.Interaction):
            self.active_category = key
            self._build_components()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

        return callback

    def build_embed(self) -> discord.Embed:
        # Fetched fresh on every tab switch (not cached at construction) so the numbers stay
        # current if this view gets left open while other players keep playing.
        board = self.game.get_leaderboard(self.top_n)
        _, board_key, title, emoji, value_fn = next(c for c in CATEGORIES if c[0] == self.active_category)
        embed = discord.Embed(title=f"🏆 Leaderboard — {emoji} {title}", color=discord.Color.gold())

        if self.active_category == "boss_damage":
            ctx = board["boss_damage_context"]
            if ctx["active"]:
                pct = 100 * max(0, ctx["current_hp"]) / ctx["max_hp"]
                embed.description = (
                    f"{ctx['boss_emoji']} **{ctx['boss_name']}** — {ctx['current_hp']:,} / {ctx['max_hp']:,} HP ({pct:.1f}%)\n"
                    "_Resets automatically whenever a new World Boss spawns._\n\n"
                    + _format_entries(board[board_key], value_fn)
                )
            else:
                embed.description = "No World Boss is currently active — check `/raidboss`.\n\nDamage rankings appear here once one spawns."
        else:
            embed.description = _format_entries(board[board_key], value_fn)

        embed.set_footer(
            text=f"Top {self.top_n} shown. Combat power is a rough composite "
            "(STR/ATK/DEF/SPD, plus gear/buffs) — not used in actual combat math."
        )
        return embed
