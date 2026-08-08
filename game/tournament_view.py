import asyncio
import time

import discord

from . import tournament
from .base_view import GameView
from .ui_utils import format_duration


def cooldown_remaining_seconds(row) -> int:
    """Seconds until a new tournament can open after `row` (the latest tournament's own row,
    'none'/'completed_recent' phase only) ended -- 0 if it's already eligible or none has ever
    run. Module-level (not just a TournamentView method) so /cd's own tournament line in
    cog.py can share the exact same math instead of re-deriving it."""
    if row is None or not row.get("ended_ts"):
        return 0
    return max(0, tournament.TOURNAMENT_COOLDOWN_SECONDS - (int(time.time()) - row["ended_ts"]))


def _placement_label(rank: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")


def _placement_line(p: dict) -> str:
    return f"#{p['rank']} {p['name']} — {p['reward_summary']}"


# Kept comfortably under Discord's real 1024-char-per-field cap rather than right at it -- a
# fixed-count chunk (e.g. "20 lines per field") can quietly blow past 1024 once display names
# run long, so this packs by actual character length instead.
PLACEMENT_FIELD_CHAR_BUDGET = 1000


def rest_placement_fields(rest: list) -> list:
    """[(field_name, field_value), ...] for every placement beyond the top 3 -- a big
    tournament (up to tournament.TOURNAMENT_MAX_PARTICIPANTS participants) can easily produce
    more text than a single embed field can hold, so this greedily packs entries into as many
    "Ranks X-Y" fields as needed instead of silently truncating at [:1024]. Shared by
    TournamentView's own completed_recent embed and GameCog's channel announcement."""
    fields = []
    chunk, chunk_len = [], 0
    for p in rest:
        line = _placement_line(p)
        added_len = len(line) + (1 if chunk else 0)
        if chunk and chunk_len + added_len > PLACEMENT_FIELD_CHAR_BUDGET:
            fields.append(_field_from_chunk(chunk))
            chunk, chunk_len, added_len = [], 0, len(line)
        chunk.append(p)
        chunk_len += added_len
    if chunk:
        fields.append(_field_from_chunk(chunk))
    return fields


def _field_from_chunk(chunk: list) -> tuple:
    name = f"Ranks {chunk[0]['rank']}–{chunk[-1]['rank']}" if len(chunk) > 1 else f"Rank {chunk[0]['rank']}"
    return name, "\n".join(_placement_line(p) for p in chunk)


class TournamentView(GameView):
    """/tournament: fully stateless -- every render re-reads the DB fresh (no in-memory
    roster like RaidView), since the signup window and battle result need to survive an
    unplanned bot restart. Anyone can click Join/Leave/Start on anyone else's open message
    (no interaction_check owner restriction, unlike a single-player view like WeaponsView) --
    a double-join attempt just gets an ephemeral rejection from GameManager.join_tournament,
    since Discord buttons render identically for every viewer and can't be conditionally
    disabled per-person."""

    def __init__(self, game):
        super().__init__(timeout=None)
        self.game = game
        self._build_components()

    def _state(self):
        """(phase, row) -- see GameManager.get_tournament_status, the shared source of truth
        /cd now also reads from."""
        return self.game.get_tournament_status()

    def _build_components(self):
        self.clear_items()
        phase, row = self._state()
        on_cooldown = phase in ("none", "completed_recent") and cooldown_remaining_seconds(row) > 0

        start_button = discord.ui.Button(
            label="Start Tournament", emoji="🏆", style=discord.ButtonStyle.success,
            disabled=phase not in ("none", "completed_recent") or on_cooldown,
        )
        start_button.callback = self._on_start
        self.add_item(start_button)

        join_button = discord.ui.Button(label="Join", emoji="➕", style=discord.ButtonStyle.primary, disabled=phase != "signup")
        join_button.callback = self._on_join
        self.add_item(join_button)

        leave_button = discord.ui.Button(label="Leave", emoji="➖", style=discord.ButtonStyle.secondary, disabled=phase != "signup")
        leave_button.callback = self._on_leave
        self.add_item(leave_button)

    async def _on_start(self, interaction: discord.Interaction):
        result = await asyncio.to_thread(self.game.open_tournament_signup, interaction.user.id, interaction.user.display_name)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send(result["join_message"], ephemeral=True)

    async def _on_join(self, interaction: discord.Interaction):
        ok, message = await asyncio.to_thread(self.game.join_tournament, interaction.user.id, interaction.user.display_name)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send(message, ephemeral=True)

    async def _on_leave(self, interaction: discord.Interaction):
        ok, message = await asyncio.to_thread(self.game.leave_tournament, interaction.user.id)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send(message, ephemeral=True)

    def build_embed(self) -> discord.Embed:
        phase, row = self._state()

        if phase == "none":
            remaining = cooldown_remaining_seconds(row)
            if remaining > 0:
                description = f"No tournament right now — the next one can start <t:{int(time.time()) + remaining}:R>."
            else:
                description = "No tournament is running right now — click **Start Tournament** to open sign-ups!"
            embed = discord.Embed(title="🏆 PvP Tournament", description=description, color=discord.Color.dark_gold())
            embed.set_footer(text=(
                f"Needs {tournament.TOURNAMENT_MIN_PARTICIPANTS}+ sign-ups within "
                f"{format_duration(tournament.TOURNAMENT_SIGNUP_SECONDS)} to actually run."
            ))
            return embed

        if phase == "signup":
            participants = self.game.db.get_tournament_participants(row["tournament_id"])
            names = "\n".join(f"• {p['name']}" for p in participants) if participants else "_No one has joined yet._"
            embed = discord.Embed(
                title="🏆 PvP Tournament — Signing Up!",
                description=(
                    "A frozen copy of your character enters the moment you Join — your gear and "
                    f"stats at that exact moment are what fights, so gear up first!\nSign-ups close <t:{row['signup_ends_ts']}:R>."
                ),
                color=discord.Color.gold(),
            )
            embed.add_field(name=f"Signed Up ({len(participants)})", value=names[:1024], inline=False)
            embed.set_footer(text=f"Needs {tournament.TOURNAMENT_MIN_PARTICIPANTS}+ sign-ups to run, or it's cancelled.")
            return embed

        if phase == "running":
            return discord.Embed(
                title="🏆 PvP Tournament — Resolving!",
                description="The battle royale is running right now — check back in a moment.",
                color=discord.Color.orange(),
            )

        # completed_recent
        placements = row["result_log"]["placements"] if row["result_log"] else []
        top_lines = [f"{_placement_label(p['rank'])} **{p['name']}** — {p['reward_summary']}" for p in placements[:3]]
        rest = placements[3:]
        embed = discord.Embed(
            title="🏆 PvP Tournament — Results!",
            description="\n".join(top_lines) if top_lines else "_No results to show._",
            color=discord.Color.gold(),
        )
        for field_name, field_value in rest_placement_fields(rest):
            embed.add_field(name=field_name, value=field_value, inline=False)
        remaining = cooldown_remaining_seconds(row)
        if remaining > 0:
            # Footer text renders as plain text, not Discord markdown -- a <t:...:R> timestamp
            # would show up literally, so this uses format_duration instead of description's
            # own markdown timestamp (see the 'none' phase above).
            footer = f"{len(placements)} cultivators competed. Next tournament in {format_duration(remaining)}."
        else:
            footer = f"{len(placements)} cultivators competed. Click Start Tournament to run another!"
        embed.set_footer(text=footer)
        return embed
