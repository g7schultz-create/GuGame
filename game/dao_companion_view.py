import asyncio

import discord

from .base_view import GameView


class DaoCompanionRequestView(GameView):
    """Sent when a player offers Dao Companionship — mirrors mentor_view.MentorRequestView's
    shape exactly (target-only Accept, either-side Decline, 5-min timeout auto-declines) but
    with its own embed text, since a companion bond is a mutual peer pairing rather than a
    mentorship. Like MentorRequestView, there's no persistent DB row behind the pending
    request itself (nothing to negotiate, just a yes/no) — accepting calls accept_callback
    directly (GameManager.dao_companion_accept), which re-validates every condition fresh in
    case anything changed while the request sat waiting."""

    def __init__(self, game, offerer: discord.abc.User, target: discord.abc.User, accept_callback):
        super().__init__(timeout=300)
        self.game = game
        self.offerer = offerer
        self.target = target
        self.accept_callback = accept_callback
        self.message: discord.Message = None

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="💞 Dao Companion Offer",
            description=f"{self.target.mention} — **{self.offerer.display_name}** offers to become your Dao Companion!",
            color=discord.Color.gold(),
        )
        embed.set_footer(text="Accept to bond your Dao together. Expires in 5 min.")
        return embed

    @discord.ui.button(label="Accept", emoji="✅", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("Only the invited player can accept this.", ephemeral=True)
            return
        ok, message = await asyncio.to_thread(
            self.accept_callback, self.offerer.id, self.offerer.display_name, self.target.id, self.target.display_name,
        )
        for child in self.children:
            child.disabled = True
        embed = discord.Embed(
            title="💞 Dao Companion Offer" + (" Accepted!" if ok else " Failed"),
            description=message,
            color=discord.Color.green() if ok else discord.Color.red(),
        )
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="Decline", emoji="❌", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in (self.offerer.id, self.target.id):
            await interaction.response.send_message("This isn't your companionship offer.", ephemeral=True)
            return
        for child in self.children:
            child.disabled = True
        embed = discord.Embed(title="💞 Dao Companion Offer Declined", color=discord.Color.dark_grey())
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            embed = discord.Embed(title="💞 Dao Companion Offer Expired", color=discord.Color.dark_grey())
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass


class EssenceExchangeRequestView(GameView):
    """Sent when a player proposes an Essence Exchange to their Dao Companion (see
    /essence_exchange) -- target-only Accept, either-side Decline, same shape as
    DaoCompanionRequestView above EXCEPT the pending request is a real DB row (see
    GameManager.essence_exchange_propose/accept/decline), not purely in-memory: a 3-hour
    confirm window is far more likely to overlap a redeploy than a 5-minute one, so
    GameCog.essence_exchange_timeout_tick's periodic sweep is the actual expiry authority --
    this view's own on_timeout is just a best-effort visual grey-out if the process happens
    to survive the whole window uninterrupted, not something depended on for correctness."""

    def __init__(self, game, request_id: int, proposer: discord.abc.User, partner: discord.abc.User):
        super().__init__(timeout=game.ESSENCE_EXCHANGE_TIMEOUT_SECONDS)
        self.game = game
        self.request_id = request_id
        self.proposer = proposer
        self.partner = partner
        self.message: discord.Message = None

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="💧 Essence Exchange Offer",
            description=(
                f"{self.partner.mention} — **{self.proposer.display_name}** wants to exchange primeval "
                f"essence with you! Accepting fills **both** of your essence by "
                f"**{self.game.ESSENCE_EXCHANGE_PERCENT * 100:.0f}%** of your max."
            ),
            color=discord.Color.blue(),
        )
        embed.set_footer(text="Accept to exchange essence together. Expires in 3 hours.")
        return embed

    @discord.ui.button(label="Accept", emoji="✅", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.partner.id:
            await interaction.response.send_message("Only the invited companion can accept this.", ephemeral=True)
            return
        result = await asyncio.to_thread(self.game.essence_exchange_accept, self.request_id, interaction.user.id)
        for child in self.children:
            child.disabled = True
        if result["ok"]:
            embed = discord.Embed(
                title="💧 Essence Exchange Accepted!",
                description=(
                    f"**{result['proposer_name']}**: +{result['proposer_restored']:,} essence "
                    f"({result['proposer_essence']:,}/{result['proposer_max']:,})\n"
                    f"**{result['partner_name']}**: +{result['partner_restored']:,} essence "
                    f"({result['partner_essence']:,}/{result['partner_max']:,})"
                ),
                color=discord.Color.green(),
            )
        else:
            embed = discord.Embed(title="💧 Essence Exchange Failed", description=result["reason"], color=discord.Color.red())
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="Decline", emoji="❌", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in (self.proposer.id, self.partner.id):
            await interaction.response.send_message("This isn't your Essence Exchange offer.", ephemeral=True)
            return
        await asyncio.to_thread(self.game.essence_exchange_decline, self.request_id, interaction.user.id)
        for child in self.children:
            child.disabled = True
        embed = discord.Embed(title="💧 Essence Exchange Declined", color=discord.Color.dark_grey())
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            embed = discord.Embed(title="💧 Essence Exchange Expired", color=discord.Color.dark_grey())
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass
