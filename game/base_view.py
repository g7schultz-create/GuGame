import traceback

import discord


class GameView(discord.ui.View):
    """Base class for every interactive view in this bot. discord.py's default
    View.on_error just prints the traceback to the console and leaves the interaction
    hanging — from the user's side, clicking a broken button looks like it does nothing at
    all. This is the View-level equivalent of bot.py's on_app_command_error/
    on_command_error: those only cover a slash/text command's own initial invocation, not a
    button or select click inside a View afterward, which goes through this completely
    separate error hook instead. Every custom View in this codebase should subclass this
    (instead of discord.ui.View directly) so a bug anywhere always surfaces a real message."""

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        item_label = getattr(item, "label", None) or getattr(item, "placeholder", None) or type(item).__name__
        print(f"[view error] {type(self).__name__} / {item_label!r} raised {type(error).__name__}: {error}")
        traceback.print_exception(type(error), error, error.__traceback__)

        message = f"⚠️ Something went wrong ({type(error).__name__}: {error})."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass
