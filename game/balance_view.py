import traceback

import discord

from .base_view import GameView
from .ui_utils import render_bar


async def _modal_error(interaction: discord.Interaction, error: Exception, modal_name: str):
    """Modal has its own separate error hook from View.on_error (see base_view.py) — same
    "surface a real message instead of silently hanging" treatment every other Modal in this
    codebase gets (see join_view.CharacterNameModal / sect_view._modal_error)."""
    print(f"[modal error] {modal_name} raised {type(error).__name__}: {error}")
    traceback.print_exception(type(error), error, error.__traceback__)
    message = f"⚠️ Something went wrong ({type(error).__name__}: {error})."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass


class ConvertEssenceModal(discord.ui.Modal, title="Convert Stones to Essence"):
    amount_input = discord.ui.TextInput(label="Spirit Stones to Spend", placeholder="e.g. 100")

    def __init__(self, balance_view: "BalanceView"):
        super().__init__()
        self.balance_view = balance_view

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.amount_input.value).strip()
        try:
            amount = int(raw)
        except ValueError:
            await interaction.response.send_message(f"'{raw}' isn't a whole number.", ephemeral=True)
            return
        if amount < 1:
            await interaction.response.send_message("Amount must be at least 1.", ephemeral=True)
            return

        game = self.balance_view.game
        stones_spent, essence_gained, new_stones, new_essence, max_essence = game.exchange_stones_for_essence(
            self.balance_view.user_id, self.balance_view.display_name, amount,
        )
        if essence_gained == 0:
            reason = "your primeval essence is already full" if new_essence >= max_essence else "you don't have enough spirit stones"
            self.balance_view.last_result = f"No essence gained — {reason}."
        else:
            self.balance_view.last_result = f"💠 Spent **{stones_spent:,}** spirit stones to gain **{essence_gained:,}** primeval essence."
        self.balance_view._build_components()
        await interaction.response.edit_message(embed=self.balance_view.build_embed(), view=self.balance_view)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await _modal_error(interaction, error, "ConvertEssenceModal")


class BalanceView(GameView):
    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.last_result: str = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Run `/balance` yourself to manage your own wallet.", ephemeral=True)
            return False
        return True

    def _player(self) -> dict:
        return self.game.get_player_stats(self.user_id, self.display_name)

    def _build_components(self):
        self.clear_items()
        p = self._player()
        db = self.game.db

        convert_btn = discord.ui.Button(
            label="Convert Stones", emoji="💠", style=discord.ButtonStyle.primary, row=0,
            disabled=p["primeval_essence"] >= p["max_primeval_essence"] or p["spirit_stones"] < db.SPIRIT_STONES_PER_ESSENCE,
        )
        convert_btn.callback = self._on_open_convert
        self.add_item(convert_btn)

        absorb_btn = discord.ui.Button(
            label="Absorb All Essence", emoji="🌀", style=discord.ButtonStyle.success, row=0,
            disabled=p["primeval_essence"] < 1,
        )
        absorb_btn.callback = self._on_absorb_all
        self.add_item(absorb_btn)

    async def _on_open_convert(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ConvertEssenceModal(self))

    async def _on_absorb_all(self, interaction: discord.Interaction):
        p = self._player()
        essence_spent, qi_gained, new_essence, new_qi = self.game.consume_essence_for_qi(
            self.user_id, self.display_name, p["primeval_essence"],
        )
        if essence_spent == 0:
            self.last_result = "You don't have any primeval essence to absorb."
        else:
            self.last_result = f"🌀 Absorbed **{essence_spent:,.0f}** primeval essence for **{qi_gained:,.0f}** qi."
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    def build_embed(self) -> discord.Embed:
        db = self.game.db
        db.settle_qi(self.user_id)  # bank latest accrual before reporting
        status = self.game.get_qi_status(self.user_id, self.display_name)
        p = status["player"]

        embed = discord.Embed(title=f"💰 {self.display_name}'s Balance", color=discord.Color.dark_purple())
        embed.add_field(
            name="💎 Primeval Essence", value=f"{p['primeval_essence']:,.0f}/{p['max_primeval_essence']:,.0f}", inline=False,
        )

        if status["at_max_realm"]:
            embed.add_field(name="⚡ Qi to Next Realm", value="🏔️ Peak realm reached", inline=False)
        else:
            percent = min(100, p["qi"] / status["qi_required"] * 100)
            embed.add_field(
                name="⚡ Qi to Next Realm",
                value=f"{p['qi']:,.2f} / {status['qi_required']:,.2f}\n`{render_bar(p['qi'], status['qi_required'])}` {percent:.1f}%",
                inline=False,
            )

        embed.add_field(name="🪙 Spirit Stones", value=f"{p['spirit_stones']:,}", inline=False)
        if self.last_result:
            embed.add_field(name="Result", value=self.last_result[:1024], inline=False)
        embed.set_footer(
            text=f"{db.SPIRIT_STONES_PER_ESSENCE} spirit stones = 1 essence • 1 essence = {db.ESSENCE_TO_QI_RATE} qi (+ any essence purity bonus)",
        )
        return embed
