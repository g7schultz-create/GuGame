"""
Lets players type `i <command> ...` in an ordinary message instead of using Discord's
`/<command>` slash-command picker — same behavior, just a different way to trigger the
exact same code. See bot.py for the "i " prefix setup (also accepts "I ", or @mentioning
the bot).

Implemented as a thin discord.Interaction-shaped shim around a classic prefix
commands.Context (ShimInteraction below), so every text command forwards straight into
the existing slash command's own callback rather than duplicating any game logic. Slash
commands only ever read interaction.user / interaction.response.send_message /
interaction.original_response() at their entry point — everything after that (button
clicks inside a View) always runs on a real discord.Interaction regardless of how the
message was first sent, so the shim only needs to cover that entry point.
"""

import discord
from discord.ext import commands

from . import realms
from .character_class import CLASSES

REALM_NAMES = [great_realm["name"] for great_realm in realms.GREAT_REALMS]


class _ShimResponse:
    def __init__(self, ctx: commands.Context):
        self._ctx = ctx
        self.message: discord.Message = None

    async def send_message(self, content=None, embed=None, view=None, file=None, ephemeral: bool = False):
        # ephemeral has no equivalent for a plain text message — just post normally.
        kwargs = {}
        if content is not None:
            kwargs["content"] = content
        if embed is not None:
            kwargs["embed"] = embed
        if view is not None:
            kwargs["view"] = view
        if file is not None:
            kwargs["file"] = file
        self.message = await self._ctx.send(**kwargs)

    async def defer(self):
        pass


class _ShimFollowup:
    """interaction.followup.send's shim counterpart — a slash command's entry point
    sometimes sends one extra message AFTER its initial response (see /mine, /gather,
    /explore, /hunt, /raid's world-region discovery notice in cog.py); a plain text message
    has no separate "followup" channel, so this just posts a second ordinary message."""

    def __init__(self, ctx: commands.Context):
        self._ctx = ctx

    async def send(self, content=None, embed=None, view=None, file=None, ephemeral: bool = False):
        kwargs = {}
        if content is not None:
            kwargs["content"] = content
        if embed is not None:
            kwargs["embed"] = embed
        if view is not None:
            kwargs["view"] = view
        if file is not None:
            kwargs["file"] = file
        await self._ctx.send(**kwargs)


class ShimInteraction:
    """Just enough of discord.Interaction's surface for a slash command's entry point to
    run unmodified when triggered by a text command instead."""

    def __init__(self, ctx: commands.Context):
        self.user = ctx.author
        self.guild = ctx.guild
        self.channel = ctx.channel
        self.response = _ShimResponse(ctx)
        self.followup = _ShimFollowup(ctx)

    async def original_response(self):
        return self.response.message


# Slash commands that take no parameters — every one of these gets an identical `i <name>`
# text equivalent.
_NO_ARG_COMMANDS = [
    "join", "tutorial", "shop", "premium", "upgrade_gu", "gu", "cultivate", "qi", "breakthrough",
    "inventory", "equipment", "mine", "gather", "explore", "cd", "farm",
    "alchemy", "blacksmith", "pvp", "leaderboard", "rest", "meditate", "study",
    "search", "search_status", "discovery", "manual", "weapons", "accessories", "sell", "region",
    "battlefield", "raidboss", "raidboss_attack", "raidboss_spawn", "balance", "preset_list",
    "sect", "sect_list", "avatar", "split_body", "tournament",
    "master", "sect_master", "dao_path", "transmute", "killer_move", "use_support_move", "verify",
    "companion", "search_forgotten_blessed_land", "teach", "essence_exchange", "white_heaven",
    "black_heaven", "gu_pet",
]

# Short aliases for the text-command interface (e.g. `i h` == `i hunt`) — every command gets
# one except cd/qi/gu, which are already as short as an alias would make them anyway. Picked
# by usage frequency (the core gathering/combat loop gets single letters) and checked by hand
# for collisions — every alias here must be globally unique across ALL commands' names AND
# aliases, since discord.py's prefix-command registry is one flat namespace.
ALIASES = {
    "join": ["j"], "tutorial": ["t", "help"], "shop": ["sh"], "premium": ["pr"], "upgrade_gu": ["ug"],
    "profile": ["p"], "cultivate": ["c"], "breakthrough": ["b", "bt"],
    "inventory": ["inv"], "equipment": ["eq"], "mine": ["m"], "gather": ["g"],
    "explore": ["ex", "exp"], "farm": ["f"], "alchemy": ["a", "alch"], "blacksmith": ["bs"],
    "pvp": ["pv"], "leaderboard": ["lb"],
    "hunt": ["h"], "raid": ["r"], "solo_raid": ["sr"], "choose_class": ["cc"], "trade": ["tr"],
    "exchange_essence": ["ee"], "absorb_essence": ["ae"], "study": ["st"],
    "grant_item": ["gi"], "grant_stones": ["gs"], "rest": ["rs"], "meditate": ["me"],
    "search": ["se"], "search_status": ["ss"], "discovery": ["d"], "manual": ["ma"],
    "weapons": ["we"], "accessories": ["ac"], "sell": ["sl"], "region": ["rg"], "battlefield": ["bf"],
    "raidboss": ["rb", "wb"], "raidboss_attack": ["rba"], "raidboss_spawn": ["rbs"], "balance": ["bal"],
    "preset_save": ["ps"], "preset_load": ["pl"], "preset_list": ["plist"], "preset_delete": ["pd"],
    "sect": ["sc"], "sect_list": ["scl"], "sect_join": ["scj"],
    "companion": ["dc"],
    "avatar": ["av"], "split_body": ["sb"], "tournament": ["tn"],
    "master": ["mst"], "sect_master": ["scmst"], "dao_path": ["dp"], "transmute": ["tm"],
    "killer_move": ["km"], "use_support_move": ["usm"], "verify": ["v"],
    "search_forgotten_blessed_land": ["sfbl", "sf"],
    "teach": ["te"],
    "gu_pet": ["gp"],
    "inheritance_ground": ["ig"],
    "white_heaven": ["wh"],
    "black_heaven": ["bh"],
    "search_black_heaven": ["sbh"],
}


def _resolve_realm_choice(realm_name: str):
    """Returns (choice, error) — choice is None (meaning "use the command's own default")
    if no realm text was given at all; error is set only if text WAS given but didn't
    match any real Great Realm."""
    if not realm_name:
        return None, None
    match = next((i for i, name in enumerate(REALM_NAMES) if name.lower() == realm_name.strip().lower()), None)
    if match is None:
        return None, f"Unknown realm `{realm_name}`. Choose one of: {', '.join(REALM_NAMES)}"
    return discord.app_commands.Choice(name=REALM_NAMES[match], value=str(match)), None


def _resolve_class_choice(class_name: str):
    """Returns (choice, error) — mirrors _resolve_realm_choice above but for /choose_class."""
    match = next((cls for cls in CLASSES.values() if cls.name.lower() == (class_name or "").strip().lower()), None)
    if match is None:
        return None, f"Unknown class `{class_name}`. Choose one of: {', '.join(CLASSES.keys())}"
    return discord.app_commands.Choice(name=match.name, value=match.name), None


def register_text_commands(bot: commands.Bot, cog):
    """Adds an `i <command>` text-message equivalent for every slash command on `cog`."""

    def make_no_arg_handler(slash_command):
        async def handler(ctx: commands.Context):
            await slash_command.callback(cog, ShimInteraction(ctx))

        return handler

    for name in _NO_ARG_COMMANDS:
        slash_command = getattr(cog, name)
        bot.add_command(commands.Command(
            make_no_arg_handler(slash_command), name=name, aliases=ALIASES.get(name, []),
            help=slash_command.description,
        ))

    async def text_profile(ctx: commands.Context, user: discord.Member = None):
        await cog.profile.callback(cog, ShimInteraction(ctx), user)

    bot.add_command(commands.Command(
        text_profile, name="profile", aliases=ALIASES["profile"],
        help=f"{cog.profile.description} Usage: i profile [@user]",
    ))

    async def text_hunt(ctx: commands.Context, *, realm: str = None):
        choice, error = _resolve_realm_choice(realm)
        if error:
            await ctx.send(error)
            return
        await cog.hunt.callback(cog, ShimInteraction(ctx), choice)

    bot.add_command(commands.Command(
        text_hunt, name="hunt", aliases=ALIASES["hunt"],
        help=f"{cog.hunt.description} Usage: i hunt [realm name]",
    ))

    async def text_raid(ctx: commands.Context, *, realm: str = None):
        choice, error = _resolve_realm_choice(realm)
        if error:
            await ctx.send(error)
            return
        await cog.raid.callback(cog, ShimInteraction(ctx), choice)

    bot.add_command(commands.Command(
        text_raid, name="raid", aliases=ALIASES["raid"],
        help=f"{cog.raid.description} Usage: i raid [realm name]",
    ))

    async def text_solo_raid(ctx: commands.Context, *, realm: str = None):
        choice, error = _resolve_realm_choice(realm)
        if error:
            await ctx.send(error)
            return
        await cog.solo_raid.callback(cog, ShimInteraction(ctx), choice)

    bot.add_command(commands.Command(
        text_solo_raid, name="solo_raid", aliases=ALIASES["solo_raid"],
        help=f"{cog.solo_raid.description} Usage: i solo_raid [realm name]",
    ))

    async def text_choose_class(ctx: commands.Context, *, class_name: str = None):
        if not class_name:
            await ctx.send(f"Usage: `i choose_class <name>` — choose one of: {', '.join(CLASSES.keys())}")
            return
        choice, error = _resolve_class_choice(class_name)
        if error:
            await ctx.send(error)
            return
        await cog.choose_class.callback(cog, ShimInteraction(ctx), choice)

    bot.add_command(commands.Command(
        text_choose_class, name="choose_class", aliases=ALIASES["choose_class"],
        help=f"{cog.choose_class.description} Usage: i choose_class <name>",
    ))

    async def text_preset_save(ctx: commands.Context, *, preset_name: str = None):
        if not preset_name:
            await ctx.send("Usage: `i preset_save <name>` — e.g. `i preset_save afk`")
            return
        await cog.preset_save.callback(cog, ShimInteraction(ctx), preset_name)

    bot.add_command(commands.Command(
        text_preset_save, name="preset_save", aliases=ALIASES["preset_save"],
        help=f"{cog.preset_save.description} Usage: i preset_save <name>",
    ))

    async def text_preset_load(ctx: commands.Context, *, preset_name: str = None):
        if not preset_name:
            await ctx.send("Usage: `i preset_load <name>` — e.g. `i preset_load afk`")
            return
        await cog.preset_load.callback(cog, ShimInteraction(ctx), preset_name)

    bot.add_command(commands.Command(
        text_preset_load, name="preset_load", aliases=ALIASES["preset_load"],
        help=f"{cog.preset_load.description} Usage: i preset_load <name>",
    ))

    async def text_preset_delete(ctx: commands.Context, *, preset_name: str = None):
        if not preset_name:
            await ctx.send("Usage: `i preset_delete <name>` — e.g. `i preset_delete afk`")
            return
        await cog.preset_delete.callback(cog, ShimInteraction(ctx), preset_name)

    bot.add_command(commands.Command(
        text_preset_delete, name="preset_delete", aliases=ALIASES["preset_delete"],
        help=f"{cog.preset_delete.description} Usage: i preset_delete <name>",
    ))

    # text_sect_create/text_sect_rename/text_sect_motto/text_sect_banner/text_sect_donate/
    # text_sect_withdraw/text_sect_transfer/text_sect_kick/text_sect_promote/text_sect_demote
    # were removed alongside their slash commands (see cog.py's own removal note) -- every
    # one of those actions is now only reachable via /sect's own buttons/modals. sect_join has
    # no button equivalent, so its text command stays.
    async def text_sect_join(ctx: commands.Context, *, name: str = None):
        if not name:
            await ctx.send("Usage: `i sect_join <name>`")
            return
        await cog.sect_join.callback(cog, ShimInteraction(ctx), name)

    bot.add_command(commands.Command(
        text_sect_join, name="sect_join", aliases=ALIASES["sect_join"],
        help=f"{cog.sect_join.description} Usage: i sect_join <name>",
    ))

    async def text_trade(ctx: commands.Context, target: discord.Member):
        await cog.trade.callback(cog, ShimInteraction(ctx), target)

    bot.add_command(commands.Command(text_trade, name="trade", aliases=ALIASES["trade"], help=cog.trade.description))

    async def text_gamble(ctx: commands.Context, target: discord.Member):
        await cog.gamble.callback(cog, ShimInteraction(ctx), target)

    bot.add_command(commands.Command(text_gamble, name="gamble", aliases=ALIASES.get("gamble", []), help=cog.gamble.description))

    async def text_exchange_essence(ctx: commands.Context, amount: int):
        await cog.exchange_essence.callback(cog, ShimInteraction(ctx), amount)

    bot.add_command(commands.Command(
        text_exchange_essence, name="exchange_essence", aliases=ALIASES["exchange_essence"],
        help=cog.exchange_essence.description,
    ))

    async def text_absorb_essence(ctx: commands.Context, amount: int):
        await cog.absorb_essence.callback(cog, ShimInteraction(ctx), amount)

    bot.add_command(commands.Command(
        text_absorb_essence, name="absorb_essence", aliases=ALIASES["absorb_essence"],
        help=cog.absorb_essence.description,
    ))

    async def text_grant_item(ctx: commands.Context, item_name: str, quantity: int = 1, member: discord.Member = None):
        await cog.grant_item.callback(cog, ShimInteraction(ctx), item_name, quantity, member)

    bot.add_command(commands.Command(
        text_grant_item, name="grant_item", aliases=ALIASES["grant_item"],
        help=f'{cog.grant_item.description} Usage: i grant_item "Item Name" [quantity] [@member]',
    ))

    async def text_grant_stones(ctx: commands.Context, amount: int, member: discord.Member = None):
        await cog.grant_stones.callback(cog, ShimInteraction(ctx), amount, member)

    bot.add_command(commands.Command(
        text_grant_stones, name="grant_stones", aliases=ALIASES["grant_stones"],
        help=cog.grant_stones.description,
    ))

    async def text_inheritance_ground(
        ctx: commands.Context, member1: discord.Member = None, member2: discord.Member = None, member3: discord.Member = None,
    ):
        # Both blank -> solo start (see cog.inheritance_ground's own handling).
        await cog.inheritance_ground.callback(cog, ShimInteraction(ctx), member1, member2, member3)

    bot.add_command(commands.Command(
        text_inheritance_ground, name="inheritance_ground", aliases=ALIASES["inheritance_ground"],
        help=f"{cog.inheritance_ground.description} Usage: i inheritance_ground [@member1 @member2 [@member3]]",
    ))

    async def text_search_black_heaven(
        ctx: commands.Context, member1: discord.Member = None, member2: discord.Member = None, member3: discord.Member = None,
    ):
        # Both blank -> solo start (see cog.search_black_heaven's own handling).
        await cog.search_black_heaven.callback(cog, ShimInteraction(ctx), member1, member2, member3)

    bot.add_command(commands.Command(
        text_search_black_heaven, name="search_black_heaven", aliases=ALIASES["search_black_heaven"],
        help=f"{cog.search_black_heaven.description} Usage: i search_black_heaven [@member1 @member2 [@member3]]",
    ))
