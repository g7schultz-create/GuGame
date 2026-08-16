import asyncio
from typing import Optional

import discord

from . import dao_essences
from .base_view import GameView
from .equipment import SPECIAL_STAT_TEXT
from .ui_utils import format_number

ESSENCE_EMOJI = {
    "Essence of Genesis": "🌱",
    "Essence of Ruin": "💀",
    "Essence of the Unbroken": "🛡️",
    "Essence of the Endless Now": "⏳",
    "Essence of the Boundless Sea": "🌊",
    "Essence of Fortune's Hand": "🍀",
    "Essence of the Sovereign": "👑",
    "Essence of the Myriad Gu": "🐛",
    dao_essences.UNDYING_VOW_NAME: "♾️",
}


def _format_bonus_line(key: str, value: float) -> str:
    formatter = SPECIAL_STAT_TEXT.get(key)
    return formatter(value) if formatter else f"{key}: {value:g}"


class DaoEssenceView(GameView):
    """/dao_essence -- view permanently-picked Dao Essences and, once a Dao Realm substage
    breakthrough has earned one, choose the next pick from whatever's left of the 9 (see
    game/dao_essences.py). Structurally cloned from dao_path_view.py's Select-picker pattern,
    but simplified -- a pick is a single irrevocable choice, not a repeatable amount allocation,
    so there's no amount-allocation row, just one Select plus one explicit Confirm button."""

    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        status = self._status()
        self.selected_essence: Optional[str] = next(iter(status["available_names"]), None)
        self.last_result: Optional[str] = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your Dao Essence choice.", ephemeral=True)
            return False
        return True

    def _status(self) -> dict:
        return self.game.get_dao_essence_status(self.user_id)

    def _build_components(self):
        self.clear_items()
        status = self._status()
        if not status["pick_available"]:
            return
        if self.selected_essence not in status["available_names"]:
            self.selected_essence = next(iter(status["available_names"]), None)

        options = [
            discord.SelectOption(
                label=name, value=name, emoji=ESSENCE_EMOJI.get(name),
                default=(name == self.selected_essence), description=dao_essences.DAO_ESSENCES[name].tagline[:100],
            )
            for name in status["available_names"]
        ]
        select = discord.ui.Select(placeholder="Choose a Dao Essence...", options=options, row=0)
        select.callback = self._on_select_essence
        self.add_item(select)

        confirm = discord.ui.Button(
            label="Confirm Pick", emoji="✅", style=discord.ButtonStyle.success, row=1,
            disabled=self.selected_essence is None,
        )
        confirm.callback = self._on_confirm_pick
        self.add_item(confirm)

    async def _on_select_essence(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select))
        self.selected_essence = select.values[0]
        self.last_result = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_confirm_pick(self, interaction: discord.Interaction):
        if self.selected_essence:
            _, self.last_result = await asyncio.to_thread(self.game.pick_dao_essence, self.user_id, self.selected_essence)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def build_embed(self) -> discord.Embed:
        status = self._status()
        picked, eligible = status["picked"], status["eligible"]
        embed = discord.Embed(
            title=f"🌌 {self.display_name}'s Dao Essences",
            description=(
                f"**{len(picked)} / {dao_essences.DAO_ESSENCE_PICK_LIMIT}** essences claimed.\n\n"
                "Each Dao Realm substage breakthrough (Early/Middle/Late/Peak) earns one permanent "
                "pick among the 9 Dao Essences below — once chosen, it's yours forever and gone "
                "from the pool for your remaining picks."
            ),
            color=discord.Color.dark_purple(),
        )
        for name in picked:
            spec = dao_essences.DAO_ESSENCES.get(name)
            if not spec:
                continue
            bonus_text = "\n".join(_format_bonus_line(key, value) for key, value in spec.bonus.items()) or spec.description
            embed.add_field(name=f"{ESSENCE_EMOJI.get(name, '')} {name}", value=f"_{spec.tagline}_\n{bonus_text}", inline=False)

        if status["pick_available"] and self.selected_essence:
            spec = dao_essences.DAO_ESSENCES[self.selected_essence]
            preview = "\n".join(_format_bonus_line(key, value) for key, value in spec.bonus.items()) or spec.description
            embed.add_field(
                name=f"Choosing: {ESSENCE_EMOJI.get(self.selected_essence, '')} {self.selected_essence}",
                value=f"_{spec.tagline}_\n{preview}",
                inline=False,
            )
        elif not status["pick_available"] and eligible <= len(picked) and eligible == 0:
            embed.add_field(name="No Pick Available", value="Reach Dao Realm (breakthrough past Ancient Realm Peak) to earn your first pick.", inline=False)
        elif not status["pick_available"]:
            embed.add_field(name="No Pick Available", value="You've claimed everything you've earned so far — the next Dao Realm breakthrough unlocks another pick.", inline=False)

        if self.last_result:
            embed.add_field(name="Result", value=self.last_result, inline=False)
        embed.set_footer(text="Picks are permanent and can never be swapped or reclaimed once confirmed.")
        return embed
