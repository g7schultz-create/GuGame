"""
One-off maintenance utility: wipes every slash command Discord has stored for
GUILD_ID, so leftover/renamed commands from an old session stop showing up
(including client-side ghost duplicates a normal sync won't clear, since sync
does a diff-free bulk overwrite but stale client caches can still show stale
entries until the list is dropped to empty and rebuilt).

Run this, then start bot.py once so its normal on_ready sync repopulates the
guild with the current command set.
"""

import asyncio

import discord

from config import GUILD_ID, TOKEN


async def main():
    if TOKEN is None:
        raise ValueError("DISCORD_TOKEN was not found. Check your .env file.")

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        try:
            await client.http.bulk_upsert_guild_commands(client.application_id, GUILD_ID, [])
            print(f"Cleared all commands for guild {GUILD_ID}.")
        finally:
            await client.close()

    await client.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
