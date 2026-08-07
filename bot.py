import os
import shutil
import traceback

import discord
from discord import app_commands
from discord.ext import commands

import config
from config import GUILD_ID, TOKEN

intents = discord.Intents.default()
intents.members = True
# Needed to read message text for the "i <command>" text-command shortcut (see
# game/text_commands.py) — slash commands don't need this, but classic prefix commands do.
intents.message_content = True


def _get_prefix(bot: commands.Bot, message: discord.Message):
    # "i " (and "I ") only — a bare "i" prefix with no trailing space would hijack any
    # ordinary message starting with the letter i ("internet", "if", ...).
    return commands.when_mentioned_or("i ", "I ")(bot, message)


# help_command=None disables discord.py's own built-in "help" command — otherwise it wins
                                    # the "help" name outright and "i help" shows discord.py's generic auto-generated command
# listing instead of our own /tutorial (see game/text_commands.py's ALIASES, which maps
# "help" to "tutorial" once the name is free).
bot = commands.Bot(command_prefix=_get_prefix, intents=intents, case_insensitive=True, help_command=None)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    # Without this, any unhandled exception in a slash command just gets silently printed
    # by discord.py's default handler and the interaction is never acknowledged — Discord
    # shows the user a bare "The application did not respond" with zero diagnostic info on
    # either side. This logs the real traceback AND tells the user something broke.
    original = error.original if isinstance(error, app_commands.CommandInvokeError) else error
    command_name = interaction.command.name if interaction.command else "?"
    print(f"[app command error] /{command_name} raised {type(original).__name__}: {original}")
    traceback.print_exception(type(original), original, original.__traceback__)

    message = f"⚠️ Something went wrong running that command ({type(original).__name__}: {original})."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    # Mirrors on_app_command_error above, but for the "i <command>" text-command path —
    # otherwise a bug hit only through that path fails completely silently in the channel.
    if isinstance(error, (commands.CommandNotFound, commands.CheckFailure)):
        return
    original = error.original if isinstance(error, commands.CommandInvokeError) else error
    print(f"[text command error] i {ctx.command.name if ctx.command else '?'} raised {type(original).__name__}: {original}")
    traceback.print_exception(type(original), original, original.__traceback__)
    try:
        await ctx.send(f"⚠️ Something went wrong running that command ({type(original).__name__}: {original}).")
    except discord.HTTPException:
        pass


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} — Bot ID: {bot.user.id}")
    print("Servers visible to this bot:")

    for server in bot.guilds:
        print(f"{server.name} — {server.id}")

    guild = discord.Object(id=GUILD_ID)
    try:
        synced = await bot.tree.sync(guild=guild)
        print(f"Synced {len(synced)} commands to guild {GUILD_ID}")
    except Exception as e:
        print(f"Failed to sync commands: {e}")


if TOKEN is None:
    raise ValueError("DISCORD_TOKEN was not found. Check your .env file.")


if __name__ == "__main__":
    # One-time Railway Volume seed: on a fresh Volume, config.DB_PATH won't exist yet on first
    # boot. If a bundled game.db.seed is present (committed once, see the deploy setup), copy it
    # in before anything ever opens the DB. Every later boot sees DB_PATH already exists (real
    # player data now lives on the Volume) and skips this -- never overwrites live data.
    if not os.path.exists(config.DB_PATH) and os.path.exists("game.db.seed"):
        shutil.copy("game.db.seed", config.DB_PATH)
        print(f"Seeded {config.DB_PATH} from game.db.seed (first boot against an empty Volume).")

    async def main():
        async with bot:
            await bot.load_extension("game.cog")
            await bot.start(TOKEN)

    import asyncio

    asyncio.run(main())
