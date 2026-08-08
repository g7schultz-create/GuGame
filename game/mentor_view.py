import asyncio

import discord

from .base_view import GameView


class MentorRequestView(GameView):
    """Sent when a master offers mentorship — "Disciple must accept" (design doc's own
    requirement for the sect track; kept the same for the personal track since a disciple
    consenting shouldn't depend on which track it's on). Unlike /trade's TradeRequestView
    there's no persistent DB row behind the pending request itself (nothing to negotiate,
    just a yes/no) — accepting calls `accept_callback` directly (GameManager.
    sect_accept_disciple for /accept_disciple, GameManager.personal_accept_disciple for
    /master_offer), which re-validates every condition fresh in case anything changed while
    the request sat waiting."""

    def __init__(self, game, master: discord.abc.User, target: discord.abc.User, accept_callback, offer_label: str = "disciple"):
        super().__init__(timeout=300)
        self.game = game
        self.master = master
        self.target = target
        self.accept_callback = accept_callback
        self.offer_label = offer_label
        self.message: discord.Message = None

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🎓 Mentorship Offer",
            description=f"{self.target.mention} — **{self.master.display_name}** offers to take you as their {self.offer_label}!",
            color=discord.Color.gold(),
        )
        embed.set_footer(text="Accept to begin the mentorship. Expires in 5 min.")
        return embed

    @discord.ui.button(label="Accept", emoji="✅", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("Only the invited player can accept this.", ephemeral=True)
            return
        ok, message = await asyncio.to_thread(
            self.accept_callback, self.master.id, self.master.display_name, self.target.id, self.target.display_name,
        )
        for child in self.children:
            child.disabled = True
        embed = discord.Embed(
            title="🎓 Mentorship Offer" + (" Accepted!" if ok else " Failed"),
            description=message,
            color=discord.Color.green() if ok else discord.Color.red(),
        )
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="Decline", emoji="❌", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in (self.master.id, self.target.id):
            await interaction.response.send_message("This isn't your mentorship offer.", ephemeral=True)
            return
        for child in self.children:
            child.disabled = True
        embed = discord.Embed(title="🎓 Mentorship Offer Declined", color=discord.Color.dark_grey())
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            embed = discord.Embed(title="🎓 Mentorship Offer Expired", color=discord.Color.dark_grey())
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass
