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
        ok, message = self.accept_callback(
            self.offerer.id, self.offerer.display_name, self.target.id, self.target.display_name,
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
