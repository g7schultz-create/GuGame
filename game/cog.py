import asyncio
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import GUILD_ID, TOURNAMENT_ANNOUNCE_CHANNEL_ID, WORLD_BOSS_ANNOUNCE_CHANNEL_ID, WORLD_BOSS_DAMAGE_RANKING_CHANNEL_ID
from . import blacksmith, chargen, equipment, professions, realms, sects, tournament, world_boss
from .character_class import CLASSES
from .character_data import PATHS
from .database import GameDatabase
from .manager import GameManager
from .items import ITEMS
from .views import ProfileView, InventoryView
from .join_view import JoinView
from .trading import TradeRequestView
from .equipment_view import EquipmentView
from .avatar_view import AvatarView
from .split_body_view import SplitBodyView
from .hunt import HuntView
from .pvp_view import PvPView
from .leaderboard_view import LeaderboardView
from .monsters import hunt_monster_name_for_realm, raid_boss_name_for_realm
from .shop import ShopView
from .premium_view import PremiumView
from .gu_upgrade import GuUpgradeView
from .gu_view import GuCollectionView
from .weapons_view import WeaponsView
from .accessories_view import AccessoriesView
from .sell_view import SellView
from .tournament_view import TournamentView, _placement_label, cooldown_remaining_seconds, rest_placement_fields
from .dao_path_view import DaoPathView
from .transmute_view import TransmuteView
from .killer_move_view import KillerMoveView
from .raid import AbandonRaidView, RaidView
from .farm_view import FarmView
from .alchemy_view import AlchemyView
from .blacksmith_view import BlacksmithView
from .mining_view import MiningVeinView
from .gathering_view import GatheringPatchView
from .exploration_view import ExplorationHuntView
from .tutorial_view import TutorialView
from .study_view import StudyView
from .search_view import SearchView
from .treasure_hunt_view import TreasureHuntView
from .discovery_view import AbandonDiscoveryView, build_discovery_entry_view
from .inheritance_ground_view import (
    AbandonInheritanceGroundView, InheritanceGroundLobbyView, InheritanceGroundView, build_intro_image_file,
)
from .region_view import RegionView
from .battlefield_view import BattlefieldView
from .world_boss_view import WorldBossView
from .manual_view import ManualView
from .mentor_view import MentorRequestView
from .dao_companion_view import DaoCompanionRequestView
from .sect_view import SectView
from .balance_view import BalanceView
from .breakthrough_view import BreakthroughConfirmView
from .text_commands import REALM_NAMES, register_text_commands
from .ui_utils import format_duration, path_footer, render_bar

GUILD = discord.Object(id=GUILD_ID)
NOT_CONFIRMED_MESSAGE = "You haven't created a character yet — run `/join` first!"

# Shared by /hunt and /raid's optional `realm` parameter — one Choice per Great Realm.
REALM_CHOICES = [app_commands.Choice(name=great_realm["name"], value=str(i)) for i, great_realm in enumerate(realms.GREAT_REALMS)]

# /grant_gear's gear_type choices — precomputed at module level rather than inline in the
# @app_commands.choices(...) decorator: GameCog's own class body defines methods literally
# named `equipment`/`blacksmith` (the /equipment and /blacksmith commands), which shadow
# those module imports for any decorator-argument code evaluated later in the SAME class body
# (methods themselves are unaffected -- only class-body-evaluated expressions like this one).
GRANT_GEAR_TYPE_CHOICES = [app_commands.Choice(name=name, value=name) for name in equipment.BLACKSMITH_GEAR_TYPES]

# /verify's auto-created rank roles (see REALM_NAMES) — a simple ascending-prestige palette,
# grey at the bottom to red at the top, one color per Great Realm.
GREAT_REALM_ROLE_COLOR = {
    "Qi Condensation": discord.Color.light_grey(),
    "Foundation Establishment": discord.Color.green(),
    "Core Formation": discord.Color.blue(),
    "Nascent Soul": discord.Color.purple(),
    "Spirit Severing": discord.Color.dark_purple(),
    "Dao Seeking": discord.Color.gold(),
    "Ancient Realm": discord.Color.red(),
}


def _default_great_realm_index(player) -> int:
    return realms.STAGES[player["realm_index"]].great_realm_index


DISCOVERY_KIND_LABEL = {"inheritance": "an inheritance", "battlefield": "a battlefield", "region_dream_realm": "a dream realm"}


def _region_find_notice(region_find: Optional[dict]) -> Optional[str]:
    """/mine, /gather, /explore, /hunt, and /raid all surface a world-region discovery find
    (see GameManager.maybe_trigger_region_discovery) as a follow-up notice rather than
    cluttering their own embed — this is the shared text for that notice."""
    if not region_find:
        return None
    kind_label = DISCOVERY_KIND_LABEL.get(region_find["type"], "a discovery")
    return f"🗺️ Your surroundings shift — you sense **{kind_label}** nearby: **{region_find['theme']}** (Rank {region_find['rank']}). Run `/discovery` to enter it!"


class GameCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = GameDatabase()
        self.game = GameManager(self.db)

    async def cog_load(self):
        self.db.setup()
        register_text_commands(self.bot, self)
        self.world_boss_tick.start()
        self.split_body_tick.start()
        self.tournament_tick.start()
        self.trade_timeout_tick.start()
        self.study_tick.start()

    async def cog_unload(self):
        self.world_boss_tick.cancel()
        self.split_body_tick.cancel()
        self.tournament_tick.cancel()
        self.trade_timeout_tick.cancel()
        self.study_tick.cancel()

    # World Boss respawn scheduler (see world_boss.py's own module docstring) -- checks every
    # 5 minutes whether the current boss expired and/or a fresh one is due; GameManager.
    # maybe_spawn_world_boss is idempotent (returns None if nothing needs to change), so
    # calling it this often is cheap and just makes the 3h respawn timer feel responsive.
    WORLD_BOSS_TICK_INTERVAL_SECONDS = 300

    @tasks.loop(seconds=WORLD_BOSS_TICK_INTERVAL_SECONDS)
    async def world_boss_tick(self):
        spawned = await asyncio.to_thread(self.game.maybe_spawn_world_boss)
        if spawned:
            await self._announce_world_boss_spawn(spawned)

    @world_boss_tick.before_loop
    async def _before_world_boss_tick(self):
        await self.bot.wait_until_ready()

    # Nascent Soul Avatar's /split_body mission scheduler (see game/split_body.py) -- scans
    # for missions that finished but haven't been DM'd yet, same 5-minute cadence as
    # world_boss_tick. Only sends the notification -- loot itself is rolled and granted when
    # the player next runs /split_body to claim it (GameManager.progress_split_body), never by
    # this loop directly.
    SPLIT_BODY_TICK_INTERVAL_SECONDS = 300

    @tasks.loop(seconds=SPLIT_BODY_TICK_INTERVAL_SECONDS)
    async def split_body_tick(self):
        for player in await asyncio.to_thread(self.game.get_ready_split_body_players):
            await self._dm_split_body_ready(player)

    @split_body_tick.before_loop
    async def _before_split_body_tick(self):
        await self.bot.wait_until_ready()

    async def _dm_split_body_ready(self, player):
        """Best-effort, same shape as _dm_world_boss_loot below -- a player with DMs closed
        just silently doesn't get one. Always marks notified afterward regardless of send
        success, so a closed-DMs player isn't retried every tick forever."""
        try:
            user = self.bot.get_user(player["user_id"]) or await self.bot.fetch_user(player["user_id"])
            embed = discord.Embed(
                title="🌀 Your Nascent Soul Avatar Has Returned!",
                description="Your avatar's Split Body mission is complete — run `/split_body` to collect its loot.",
                color=discord.Color.dark_purple(),
            )
            await user.send(embed=embed)
        except discord.HTTPException:
            pass
        finally:
            await asyncio.to_thread(self.game.db.mark_split_body_notified, player["user_id"])

    async def _announce_world_boss_spawn(self, boss: dict):
        if WORLD_BOSS_ANNOUNCE_CHANNEL_ID is None:
            return
        channel = self.bot.get_channel(WORLD_BOSS_ANNOUNCE_CHANNEL_ID)
        if channel is None:
            return
        roster = world_boss.WORLD_BOSSES[boss["boss_key"]]
        embed = discord.Embed(
            title=f"{roster['emoji']} A World Boss Has Awakened!",
            description=f"**{roster['name']}** ({roster['theme']})\n_{roster['description']}_",
            color=discord.Color.dark_red(),
        )
        embed.add_field(name="HP", value=f"{boss['max_hp']:,} / {boss['max_hp']:,}", inline=True)
        embed.add_field(name="Time Limit", value=format_duration(world_boss.WORLD_BOSS_LIFETIME_SECONDS), inline=True)
        embed.set_footer(text="Use /raidboss to join the fight!")
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    async def _announce_world_boss_defeat(self, end_summary: dict):
        roster = world_boss.WORLD_BOSSES[end_summary["boss"]["boss_key"]]
        await self._dm_world_boss_loot(end_summary, roster)

        lines = [f"**{end_summary['total_damage']:,}** total damage from **{len(end_summary['contributors'])}** cultivator(s)."]
        for winner in end_summary["lottery_winners"]:
            lines.append(f"🎁 Lottery drop goes to **{winner['name']}**: {winner['reward_text']}!")
        pill_finders = [c["name"] for c in end_summary["contributors"] if c.get("essence_pill")]
        if pill_finders:
            lines.append(f"💧 A rare Essence Restoration Pill also turned up for: **{', '.join(pill_finders)}**!")
        qi_ascension_finders = [c["name"] for c in end_summary["contributors"] if c.get("qi_ascension_pill")]
        if qi_ascension_finders:
            lines.append(f"🌟 A rare Qi Ascension Pill also turned up for: **{', '.join(qi_ascension_finders)}**!")
        page_finders = [c for c in end_summary["contributors"] if c.get("manual_page")]
        if page_finders:
            page_lines = [f"**{c['name']}** ({c['manual_page']['name']}, Rank {c['manual_page']['rank']})" for c in page_finders]
            lines.append(f"📜 A rare manual page also turned up for: {', '.join(page_lines)}!")
        embed = discord.Embed(
            title=f"{roster['emoji']} {roster['name']} Has Fallen!",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        # end_summary["contributors"] is already damage-sorted DESC (see
        # GameDatabase.get_world_boss_contributors) -- top 10 shown, medals for the top 3.
        contributors = end_summary["contributors"]
        if contributors:
            medals = ["🥇", "🥈", "🥉"]
            ranking_lines = [
                f"{medals[i] if i < 3 else f'{i + 1}.'} **{c['name']}** — {c['damage_dealt']:,} damage"
                for i, c in enumerate(contributors[:10])
            ]
            if len(contributors) > 10:
                ranking_lines.append(f"...and {len(contributors) - 10} more cultivator(s).")
            embed.add_field(name="🏆 Damage Ranking", value="\n".join(ranking_lines), inline=False)

        # Sent to every configured channel that isn't None, deduplicated so a shared channel
        # ID (WORLD_BOSS_ANNOUNCE_CHANNEL_ID happening to equal WORLD_BOSS_DAMAGE_RANKING_
        # CHANNEL_ID) only gets the announcement once.
        for channel_id in {WORLD_BOSS_ANNOUNCE_CHANNEL_ID, WORLD_BOSS_DAMAGE_RANKING_CHANNEL_ID} - {None}:
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                continue
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass

    async def _dm_world_boss_loot(self, end_summary: dict, roster: dict):
        """Privately tells every contributor exactly what THEY personally got — the channel
        announcement above only ever surfaces the lottery winner and who found a pill, never
        each player's own guaranteed stones/damage dealt. Best-effort: not gated behind
        WORLD_BOSS_ANNOUNCE_CHANNEL_ID (DMs are per-player, independent of any channel setup),
        and a player with DMs closed or who's blocked the bot just silently doesn't get one —
        one failed DM must never stop the rest of the loop or the channel announcement after it."""
        for c in end_summary["contributors"]:
            lines = [f"⚔️ You dealt **{c['damage_dealt']:,}** damage to **{roster['name']}** before it fell."]
            if c["stones"] > 0:
                lines.append(f"🪙 You received **{c['stones']:,}** spirit stones.")
            if c.get("essence_pill"):
                qty = c.get("essence_pill_quantity", 1)
                lines.append(f"💧 You also found {qty}x rare **{c['essence_pill']}**!")
            if c.get("qi_ascension_pill"):
                qty = c.get("qi_ascension_pill_quantity", 1)
                lines.append(f"🌟 You also found {qty}x rare **{c['qi_ascension_pill']}**!")
            if c.get("manual_page"):
                lines.append(f"📜 You also found a rare **{c['manual_page']['name']}** (Rank {c['manual_page']['rank']} page)!")
            for winner in end_summary["lottery_winners"]:
                if winner["user_id"] == c["user_id"]:
                    lines.append(f"🎁 You won a damage-weighted lottery drop: {winner['reward_text']}!")
            embed = discord.Embed(
                title=f"{roster['emoji']} {roster['name']} Has Fallen!",
                description="\n".join(lines),
                color=discord.Color.gold(),
            )
            try:
                user = self.bot.get_user(c["user_id"]) or await self.bot.fetch_user(c["user_id"])
                await user.send(embed=embed)
            except discord.HTTPException:
                pass

    # PvP Tournament countdown/resolution scheduler (see game/tournament.py / /tournament) --
    # same 5-minute cadence as the other two loops. GameManager.get_pending_tournament_
    # announcements (NOT resolve_tournament_if_ready's own return value -- see its docstring)
    # is what actually guarantees a post/DM even when a player's own /tournament, /cd, or Join
    # action was the thing that resolved the tournament in the gap between two ticks, instead
    # of this loop. maybe_open_tournament is idempotent (returns falsy when nothing needs to
    # change), so calling it this often is cheap; it immediately reopens a fresh signup right
    # after a tournament ends (TOURNAMENT_COOLDOWN_SECONDS is 0), so signup stays open
    # continuously between one tournament and the next, mirroring world_boss_tick's own
    # auto-respawn shape.
    TOURNAMENT_TICK_INTERVAL_SECONDS = 300

    @tasks.loop(seconds=TOURNAMENT_TICK_INTERVAL_SECONDS)
    async def tournament_tick(self):
        for result in await asyncio.to_thread(self.game.get_pending_tournament_announcements):
            if result["outcome"] == "completed":
                await self._announce_tournament_result(result)
            else:
                await self._announce_tournament_cancelled(result)
            await asyncio.to_thread(self.game.mark_tournament_announced, result["tournament_id"])
        opened = await asyncio.to_thread(self.game.maybe_open_tournament)
        if opened:
            await self._announce_tournament_signup_open(opened)

    @tournament_tick.before_loop
    async def _before_tournament_tick(self):
        await self.bot.wait_until_ready()

    # Same 5-minute cadence as the other three loops -- catches a trade/gamble whose View died
    # (most commonly a bot restart/redeploy mid-negotiation) well before a player would think
    # to ask for help, without needing to poll any faster than that.
    TRADE_TIMEOUT_TICK_INTERVAL_SECONDS = 300

    @tasks.loop(seconds=TRADE_TIMEOUT_TICK_INTERVAL_SECONDS)
    async def trade_timeout_tick(self):
        for trade in await asyncio.to_thread(self.game.expire_stale_trades):
            await self._dm_trade_timeout(trade)

    @trade_timeout_tick.before_loop
    async def _before_trade_timeout_tick(self):
        await self.bot.wait_until_ready()

    async def _dm_trade_timeout(self, trade):
        """Best-effort, same shape as _dm_tournament_placements/_dm_world_boss_loot -- a
        player with DMs closed just silently doesn't get one, and one failed DM must never
        stop the other side's or the rest of the sweep."""
        noun = "gamble" if trade["mode"] == "gamble" else "trade"
        message = (
            f"⏱️ Your {noun} (request #{trade['id']}) sat unconfirmed too long and was "
            f"automatically cancelled — nothing was taken from your inventory, feel free to "
            f"start a fresh one."
        )
        for user_id in (trade["initiator_id"], trade["target_id"]):
            try:
                user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                await user.send(message)
            except discord.HTTPException:
                pass

    # Same 5-minute cadence as the other loops -- profession study takes at least an hour per
    # rank (see professions.STUDY_HOURS_PER_STEP), so there's no need to poll any faster.
    # Auto-completes any study that's crossed 100% progress instead of leaving it sitting at
    # "ready to complete" until the player happens to run /study again (per explicit request).
    STUDY_TICK_INTERVAL_SECONDS = 300

    @tasks.loop(seconds=STUDY_TICK_INTERVAL_SECONDS)
    async def study_tick(self):
        for completed in await asyncio.to_thread(self.game.check_and_complete_ready_studies):
            await self._dm_study_complete(completed)

    @study_tick.before_loop
    async def _before_study_tick(self):
        await self.bot.wait_until_ready()

    async def _dm_study_complete(self, completed: dict):
        """Best-effort, same shape as _dm_trade_timeout/_dm_split_body_ready -- a player with
        DMs closed just silently doesn't get one, and one failed DM must never stop the rest
        of the sweep."""
        rank_name = professions.rank_name(completed["new_rank"])
        emoji = professions.PROFESSION_EMOJI.get(completed["profession"], "📖")
        message = (
            f"{emoji} Your **{completed['profession']}** study is complete — you've advanced "
            f"to **{rank_name}**! Run `/study` to start your next rank."
        )
        try:
            user = self.bot.get_user(completed["user_id"]) or await self.bot.fetch_user(completed["user_id"])
            await user.send(message)
        except discord.HTTPException:
            pass

    async def _announce_tournament_signup_open(self, opened: dict):
        """Best-effort channel ping when maybe_open_tournament auto-opens a fresh signup --
        mirrors _announce_world_boss_spawn's own shape. Without this, nobody would know a
        signup window is open until someone happened to run /tournament themselves."""
        if TOURNAMENT_ANNOUNCE_CHANNEL_ID is None:
            return
        channel = self.bot.get_channel(TOURNAMENT_ANNOUNCE_CHANNEL_ID)
        if channel is None:
            return
        embed = discord.Embed(
            title="🏆 Tournament Sign-Ups Are Open!",
            description=(
                f"A new PvP tournament is accepting sign-ups until <t:{opened['signup_ends_ts']}:R> — "
                "use `/tournament` to join!"
            ),
            color=discord.Color.gold(),
        )
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    async def _announce_tournament_result(self, result: dict):
        await self._dm_tournament_placements(result)

        if TOURNAMENT_ANNOUNCE_CHANNEL_ID is None:
            return
        channel = self.bot.get_channel(TOURNAMENT_ANNOUNCE_CHANNEL_ID)
        if channel is None:
            return
        placements = result["placements"]
        top_lines = [f"{_placement_label(p['rank'])} **{p['name']}** — {p['reward_summary']}" for p in placements[:3]]
        embed = discord.Embed(title="🏆 Tournament Results!", description="\n".join(top_lines), color=discord.Color.gold())
        for field_name, field_value in rest_placement_fields(placements[3:]):
            embed.add_field(name=field_name, value=field_value, inline=False)
        embed.set_footer(text=f"{len(placements)} cultivators competed.")
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    async def _dm_tournament_placements(self, result: dict):
        """Best-effort, same shape as _dm_world_boss_loot -- a player with DMs closed just
        silently doesn't get one, and one failed DM must never stop the rest of the loop."""
        for p in result["placements"]:
            embed = discord.Embed(
                title="🏆 Tournament Complete!",
                description=f"You placed **#{p['rank']}** of {len(result['placements'])}.\n🎁 {p['reward_summary']}",
                color=discord.Color.gold(),
            )
            try:
                user = self.bot.get_user(p["user_id"]) or await self.bot.fetch_user(p["user_id"])
                await user.send(embed=embed)
            except discord.HTTPException:
                pass

    async def _announce_tournament_cancelled(self, result: dict):
        if TOURNAMENT_ANNOUNCE_CHANNEL_ID is None:
            return
        channel = self.bot.get_channel(TOURNAMENT_ANNOUNCE_CHANNEL_ID)
        if channel is None:
            return
        try:
            await channel.send(
                f"🏆 Tournament sign-ups closed with only {result['participant_count']} — "
                f"needs {tournament.TOURNAMENT_MIN_PARTICIPANTS}+ to run. Try `/tournament` again!"
            )
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.guild.id != GUILD_ID:
            return

        player = await asyncio.to_thread(self.db.get_or_create_player, member.id, member.display_name)
        welcome_message = (
            f"Welcome to the game, {member.display_name}! "
            f"Your aptitude is **{player['aptitude']}**/100 — the higher it is, the faster you gain Qi.\n"
            "Run `/join` to create your character before doing anything else! "
            "Run `/tutorial` any time for a guided tour of the commands."
        )

        try:
            await member.send(welcome_message)
        except Exception:
            if member.guild.system_channel is not None:
                await member.guild.system_channel.send(welcome_message)

    @app_commands.command(name="join", description="Create or view your character")
    @app_commands.guilds(GUILD)
    async def join(self, interaction: discord.Interaction):
        view = JoinView( interaction.user.id, self.game, interaction.user.display_name, interaction.user.display_avatar.url,
        )
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="choose_class", description="One-time: pick your combat class, if your character predates classes")
    @app_commands.describe(class_name="Tank, Support, or Frostbinder")
    @app_commands.choices(class_name=[app_commands.Choice(name=f"{cls.emoji} {cls.name} ({cls.role})", value=cls.name) for cls in CLASSES.values()])
    @app_commands.guilds(GUILD)
    async def choose_class(self, interaction: discord.Interaction, class_name: app_commands.Choice[str]):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message("Choose your class as part of `/join` character creation instead.", ephemeral=True)
            return
        ok, message = await asyncio.to_thread(self.game.set_class, interaction.user.id, interaction.user.display_name, class_name.value)
        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="change_path", description="Switch cultivation path (Righteous/Demonic/Rogue) — costs qi and limited uses")
    @app_commands.describe(path_name="The cultivation path to switch to")
    @app_commands.choices(path_name=[app_commands.Choice(name=path.name, value=path.name) for path in PATHS.values()])
    @app_commands.guilds(GUILD)
    async def change_path(self, interaction: discord.Interaction, path_name: app_commands.Choice[str]):
        ok, message = await asyncio.to_thread(
            self.game.change_cultivation_path, interaction.user.id, interaction.user.display_name, path_name.value,
        )
        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="tutorial", description="Learn how to play — a guided tour of all the commands")
    @app_commands.guilds(GUILD)
    async def tutorial(self, interaction: discord.Interaction):
        view = TutorialView(interaction.user.id, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="shop", description="Spend spirit stones on Root/Physique rerolls")
    @app_commands.guilds(GUILD)
    async def shop(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        view = ShopView( interaction.user.id, self.game, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="premium", description="Auto-reroll Root/Physique until you hit your target tier, or spend spirit stones to change your Race")
    @app_commands.guilds(GUILD)
    async def premium(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        view = PremiumView( interaction.user.id, self.game, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="upgrade_gu", description="Fuse duplicate Gu into a higher quality, or break unwanted ones down for spirit stones")
    @app_commands.guilds(GUILD)
    async def upgrade_gu(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        view = GuUpgradeView( interaction.user.id, self.game, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="gu", description="View the Gu you own, their quality, and their effect")
    @app_commands.guilds(GUILD)
    async def gu(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        view = GuCollectionView( interaction.user.id, self.game, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="verify", description="Assign yourself a Discord role matching your current cultivation rank")
    @app_commands.guilds(GUILD)
    async def verify(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("`/verify` only works inside the server, not in DMs.", ephemeral=True)
            return

        great_realm_name = realms.STAGES[player["realm_index"]].great_realm_name
        member = interaction.user
        current_rank_roles = [r for r in member.roles if r.name in REALM_NAMES]
        if len(current_rank_roles) == 1 and current_rank_roles[0].name == great_realm_name:
            await interaction.response.send_message(f"✅ You're already verified as **{great_realm_name}**.", ephemeral=True)
            return

        target_role = discord.utils.get(guild.roles, name=great_realm_name)
        try:
            if target_role is None:
                target_role = await guild.create_role(
                    name=great_realm_name,
                    color=GREAT_REALM_ROLE_COLOR.get(great_realm_name, discord.Color.default()),
                    reason="Gu cultivation rank role (auto-created by /verify)",
                )
            stale_roles = [r for r in current_rank_roles if r.id != target_role.id]
            if stale_roles:
                await member.remove_roles(*stale_roles, reason="Cultivation rank updated via /verify")
            await member.add_roles(target_role, reason="Cultivation rank verified via /verify")
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to manage roles here — I need the **Manage Roles** permission, "
                "and my own top role needs to sit ABOVE the rank roles in Server Settings → Roles.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(f"✅ Verified! You've been given the **{great_realm_name}** role.", ephemeral=False)

    @app_commands.command(name="killer_move", description="Assemble a core Gu + 10 Gu into a procedurally-generated Killer Move")
    @app_commands.guilds(GUILD)
    async def killer_move(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        view = KillerMoveView( interaction.user.id, self.game, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="use_support_move", description="Activate your equipped Support Killer Move (essence/cultivation/loot boost)")
    @app_commands.guilds(GUILD)
    async def use_support_move(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        ok, message = await asyncio.to_thread(self.game.activate_support_killer_move, interaction.user.id, interaction.user.display_name)
        await interaction.response.send_message(message, ephemeral=not ok)

    @app_commands.command(name="profile", description="Show your profile, or someone else's")
    @app_commands.describe(user="Whose profile to view (leave blank for your own)")
    @app_commands.guilds(GUILD)
    async def profile(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        target = user or interaction.user
        player = await asyncio.to_thread(self.game.get_player_stats, target.id, target.display_name)
        if not player["character_confirmed"]:
            message = NOT_CONFIRMED_MESSAGE if target.id == interaction.user.id else f"{target.display_name} hasn't finished character creation yet."
            await interaction.response.send_message(message, ephemeral=True)
            return
        player, _ = await asyncio.to_thread(self.db.settle_qi, target.id)
        player = await asyncio.to_thread(self.db.settle_hp_regen, target.id)
        view = ProfileView(
            target.id,
            self.game,
            player,
            target.display_name,
            target.display_avatar.url,
            viewer_id=interaction.user.id,
        )
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="cultivate", description="Cultivate to gain Qi")
    @app_commands.guilds(GUILD)
    async def cultivate(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        player, gained = await asyncio.to_thread(self.game.cultivate, interaction.user.id, interaction.user.display_name)
        embed = discord.Embed(
            title=f"{interaction.user.display_name} cultivates...",
            description="You circulate your qi, drawing in the ambient energy around you.",
            color=discord.Color.dark_purple(),
        )
        embed.add_field(name="⚡ Qi Gained", value=f"+{gained:,.2f}", inline=True)
        embed.add_field(name="💠 Total Qi", value=f"{player['qi']:,.2f}", inline=True)
        embed.add_field(name="✨ Qi Multiplier", value=f"x{player['qi_multiplier']:.2f}", inline=True)

        if realms.is_max_realm(player["realm_index"]):
            progress_text = f"`{render_bar(1, 1)}` 100% — peak realm reached"
        else:
            qi_required = realms.qi_required_for_next(player["realm_index"])
            percent = min(100, player["qi"] / qi_required * 100)
            progress_text = (
                f"`{render_bar(player['qi'], qi_required)}` {percent:.1f}%\n"
                f"{player['qi']:,.2f} / {qi_required:,.2f} qi toward **{realms.realm_name(player['realm_index'] + 1)}**"
            )
        embed.add_field(name="🌟 Next Realm Progress", value=progress_text, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="qi", description="Show your Qi progress, rate, and breakthrough estimate")
    @app_commands.guilds(GUILD)
    async def qi(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return

        await asyncio.to_thread(self.db.settle_qi, interaction.user.id)  # bank latest accrual before reporting
        status = await asyncio.to_thread(self.game.get_qi_status, interaction.user.id, interaction.user.display_name)
        p = status["player"]

        if status["at_max_realm"]:
            subtitle = "🏔️ Peak realm reached"
        elif status["ready"]:
            subtitle = "✨ Ready for breakthrough!"
        else:
            subtitle = "🔒 Still cultivating..."

        embed = discord.Embed(
            title="💠 Qi Status",
            description=f"**{status['realm_name']}**\n{subtitle}",
            color=discord.Color.gold() if status["ready"] else discord.Color.dark_purple(),
        )

        if status["at_max_realm"]:
            embed.add_field(name="🔮 Current Qi", value=f"{p['qi']:,.2f}", inline=True)
        else:
            percent = min(100, p["qi"] / status["qi_required"] * 100)
            embed.add_field(name="🔮 Current Qi", value=f"{p['qi']:,.2f}", inline=True)
            embed.add_field(name="🎯 Required", value=f"{status['qi_required']:,.2f}", inline=True)
            embed.add_field(name="📊 Progress", value=f"{percent:.1f}%", inline=True)

            time_text = "Ready!" if status["ready"] else (
                format_duration(status["seconds_remaining"]) if status["seconds_remaining"] is not None else "∞ (no qi rate)"
            )
            embed.add_field(name="⚡ Qi Rate", value=f"{status['effective_rate_per_minute']:,.2f}/min", inline=True)
            embed.add_field(name="⏱️ Time to Breakthrough", value=time_text, inline=True)
            embed.add_field(name="📶 Status", value="✅ Ready" if status["ready"] else "⏳ Cultivating", inline=True)
            embed.add_field(name="📈 Progress Bar", value=f"`{render_bar(p['qi'], status['qi_required'])}` {percent:.1f}%", inline=False)

        multiplier_lines = [
            f"Base Rate: {p['aptitude']} aptitude × {self.db.BASE_QI_PER_MINUTE_PER_APTITUDE}/min = **{status['base_rate_per_minute']:,.2f}/min**",
            f"Qi Multiplier (elixirs/pellets): **x{p['qi_multiplier']:.2f}**",
        ]
        if status["character_bonus"]:
            multiplier_lines.append(f"Race/Root/Physique/Path Bonus: **+{status['character_bonus'] * 100:.1f}%**")
        if status["manual_bonus"]:
            multiplier_lines.append(f"Manual ({status['manual_name']}): **+{status['manual_bonus'] * 100:.1f}%**")
        multiplier_lines.append(f"**Total Multiplier: x{status['total_multiplier']:.2f}**")
        embed.add_field(name="🔢 Multipliers", value="\n".join(multiplier_lines), inline=False)

        if status["active_buffs"]:
            # Each pill use inserts its own buff row rather than stacking into an existing
            # one, so spamming the same pill many times used to mean one embed line per use —
            # easily enough to blow past Discord's 1024-char field limit and 400 the whole
            # command. Grouping same-named buffs into a single "xN" line fixes that at the
            # source; the [:1024] is just a defensive backstop against many *different* buffs.
            now_ts = int(time.time())
            grouped = {}
            for b in status["active_buffs"]:
                entry = grouped.setdefault(b["name"], {"count": 0, "bonus_each": b["qi_multiplier_bonus"], "max_remaining": 0})
                entry["count"] += 1
                entry["max_remaining"] = max(entry["max_remaining"], b["expires_at"] - now_ts)
            buff_lines = []
            for name, entry in grouped.items():
                minutes_left = max(0, entry["max_remaining"] // 60)
                if entry["count"] > 1:
                    total_bonus = entry["bonus_each"] * entry["count"]
                    buff_lines.append(
                        f"✨ **{name}** x{entry['count']} — +{entry['bonus_each']:.2f} each "
                        f"(+{total_bonus:.2f} total), up to {minutes_left}m left"
                    )
                else:
                    buff_lines.append(f"✨ **{name}** — +{entry['bonus_each']:.2f} multiplier ({minutes_left}m left)")
            embed.add_field(name="🧪 Active Buffs", value="\n".join(buff_lines)[:1024], inline=False)
        else:
            embed.add_field(name="🧪 Active Buffs", value="None — try a pill from `/inventory`!", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="balance", description="Show your primeval essence, Qi progress to your next realm, and spirit stones")
    @app_commands.guilds(GUILD)
    async def balance(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        view = BalanceView( interaction.user.id, self.game, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        view.message = await interaction.original_response()

    @app_commands.command(name="breakthrough", description="Attempt a breakthrough to the next cultivation realm")
    @app_commands.guilds(GUILD)
    async def breakthrough(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return

        status = await asyncio.to_thread(self.game.breakthrough_status, interaction.user.id, interaction.user.display_name)

        if status["at_max_realm"]:
            await interaction.response.send_message("You've reached the peak of known cultivation... for now.", ephemeral=True)
            return
        if status["player"]["qi"] < status["qi_required"]:
            await interaction.response.send_message(
                f"Not enough Qi to attempt this breakthrough. Need **{status['qi_required']:,.2f}**, have **{status['player']['qi']:,.2f}**.",
                ephemeral=True,
            )
            return

        view = BreakthroughConfirmView(interaction.user.id, self.game, interaction.user.display_name, status)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        view.message = await interaction.original_response()

    @app_commands.command(name="inventory", description="View and use your items")
    @app_commands.guilds(GUILD)
    async def inventory(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        view = InventoryView( interaction.user.id, self.game, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="equipment", description="View and manage your equipped gear")
    @app_commands.guilds(GUILD)
    async def equipment(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        player = await asyncio.to_thread(self.db.settle_hp_regen, interaction.user.id)
        view = EquipmentView( interaction.user.id, self.game, player, interaction.user.display_name, interaction.user.display_avatar.url,
        )
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="avatar", description="View and manage your Nascent Soul avatar")
    @app_commands.guilds(GUILD)
    async def avatar(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        if not await asyncio.to_thread(self.game.is_avatar_unlocked, interaction.user.id, interaction.user.display_name):
            await interaction.response.send_message(
                "🔒 Your Nascent Soul avatar awakens once you reach **Nascent Soul** realm — keep cultivating!",
                ephemeral=True,
            )
            return
        view = AvatarView( interaction.user.id, self.game, interaction.user.display_name, interaction.user.display_avatar.url)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        view.message = await interaction.original_response()

    @app_commands.command(name="split_body", description="Send your Nascent Soul avatar to search for loot for 3 hours")
    @app_commands.guilds(GUILD)
    async def split_body(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        if not await asyncio.to_thread(self.game.is_avatar_unlocked, interaction.user.id, interaction.user.display_name):
            await interaction.response.send_message(
                "🔒 Your Nascent Soul avatar awakens once you reach **Nascent Soul** realm — keep cultivating!",
                ephemeral=True,
            )
            return
        if not player["avatar_soul"]:
            await interaction.response.send_message(
                "Your avatar hasn't chosen a soul yet — run `/avatar` to awaken it before sending it out.",
                ephemeral=True,
            )
            return
        view = SplitBodyView( interaction.user.id, self.game, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        view.message = await interaction.original_response()

    @app_commands.command(
        name="search_forgotten_blessed_land",
        description="Dig through a hidden 5x5 treasure site (Core Formation realm and above, one board every 2 hours)",
    )
    @app_commands.guilds(GUILD)
    async def search_forgotten_blessed_land(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        ok, message, board = await asyncio.to_thread(self.game.start_treasure_hunt, interaction.user.id, interaction.user.display_name)
        if not ok:
            await interaction.response.send_message(message, ephemeral=True)
            return
        view = TreasureHuntView( interaction.user.id, self.game, interaction.user.display_name, board)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(content=message, embed=embed, view=view, ephemeral=False)
        view.message = await interaction.original_response()

    # -- Equipment presets (save/restore a full loadout by name — /preset_save afk, /preset_load
    # raid, etc.) -----------------------------------------------------------------------------

    async def _preset_name_autocomplete(self, interaction: discord.Interaction, current: str):
        presets = await asyncio.to_thread(self.game.get_equipment_presets, interaction.user.id)
        return [
            app_commands.Choice(name=p["display_name"], value=p["display_name"])
            for p in presets
            if current.lower() in p["display_name"].lower()
        ][:25]

    @app_commands.command(name="preset_save", description="Save your currently equipped gear + manuals as a named preset")
    @app_commands.guilds(GUILD)
    @app_commands.describe(preset_name="A name for this preset, e.g. afk / raid / farm")
    async def preset_save(self, interaction: discord.Interaction, preset_name: str):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        ok, message = await asyncio.to_thread(self.game.save_equipment_preset, interaction.user.id, interaction.user.display_name, preset_name)
        await interaction.response.send_message(message, ephemeral=not ok)

    @app_commands.command(name="preset_load", description="Re-equip a saved gear + manual preset")
    @app_commands.guilds(GUILD)
    @app_commands.describe(preset_name="Which saved preset to load")
    @app_commands.autocomplete(preset_name=_preset_name_autocomplete)
    async def preset_load(self, interaction: discord.Interaction, preset_name: str):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        result = await asyncio.to_thread(self.game.apply_equipment_preset, interaction.user.id, interaction.user.display_name, preset_name)
        if not result["ok"]:
            await interaction.response.send_message(f"No preset named **{result['display_name']}** — check `/preset_list`.", ephemeral=True)
            return

        embed = discord.Embed(title=f"🧳 Loaded preset: {result['display_name']}", color=discord.Color.dark_teal())
        if result["applied"]:
            embed.add_field(name="Applied", value="\n".join(result["applied"])[:1024], inline=False)
        if result["skipped"]:
            embed.add_field(name="Skipped", value="\n".join(result["skipped"])[:1024], inline=False)
        if result["manual_note"]:
            embed.add_field(name="Manuals", value=result["manual_note"][:1024], inline=False)
        if not result["applied"] and not result["skipped"] and not result["manual_note"]:
            embed.description = "Already matched this preset — nothing to change."
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="preset_list", description="List your saved equipment presets")
    @app_commands.guilds(GUILD)
    async def preset_list(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        presets = await asyncio.to_thread(self.game.get_equipment_presets, interaction.user.id)
        if not presets:
            await interaction.response.send_message("You haven't saved any presets yet — try `/preset_save afk`.", ephemeral=True)
            return
        lines = [
            f"**{p['display_name']}** — {len(p['slots'])} gear slot(s)" + (" + manuals" if p["primary_manual_id"] or p["auxiliary_manual_id"] else "")
            for p in presets
        ]
        embed = discord.Embed(title="🧳 Your Equipment Presets", description="\n".join(lines)[:4000], color=discord.Color.dark_teal())
        embed.set_footer(text=f"{len(presets)}/{self.game.MAX_EQUIPMENT_PRESETS} presets used • /preset_load <name> to apply one")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="preset_delete", description="Delete a saved equipment preset")
    @app_commands.guilds(GUILD)
    @app_commands.describe(preset_name="Which saved preset to delete")
    @app_commands.autocomplete(preset_name=_preset_name_autocomplete)
    async def preset_delete(self, interaction: discord.Interaction, preset_name: str):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        ok, message = await asyncio.to_thread(self.game.delete_equipment_preset, interaction.user.id, preset_name)
        await interaction.response.send_message(message, ephemeral=not ok)

    @app_commands.command(name="hunt", description="Hunt a spirit beast")
    @app_commands.describe(realm="Which realm of beast to hunt (defaults to your own realm)")
    @app_commands.choices(realm=REALM_CHOICES)
    @app_commands.guilds(GUILD)
    async def hunt(self, interaction: discord.Interaction, realm: Optional[app_commands.Choice[str]] = None):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        if self.game.has_active_hunt(player):
            await interaction.response.send_message("🐾 Finish your current hunt first!", ephemeral=True)
            return
        great_realm_index = int(realm.value) if realm else _default_great_realm_index(player)
        monster_name = hunt_monster_name_for_realm(great_realm_index)
        region_modifiers = await asyncio.to_thread(self.game.region_encounter_modifiers, interaction.user.id, interaction.user.display_name)
        # Constructed directly, NOT via asyncio.to_thread -- HuntView.__init__ itself calls
        # asyncio.create_task (to start the round timer), which requires a running loop on the
        # CURRENT thread; a to_thread worker thread never has one. The __init__ DB reads are
        # brief single-row lookups, not a bulk loop, so this doesn't reintroduce the hang this
        # migration targeted.
        view = HuntView(
            interaction.user.id, self.game, player, interaction.user.display_name, interaction.user.display_avatar.url,
            monster_name, region_modifiers,
        )
        await asyncio.to_thread(self.game.start_active_hunt, interaction.user.id)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        view.message = await interaction.original_response()
        region_find = await asyncio.to_thread(self.game.maybe_trigger_region_discovery, interaction.user.id, interaction.user.display_name)
        notice = _region_find_notice(region_find)
        if notice:
            await interaction.followup.send(notice, ephemeral=True)

    @app_commands.command(name="pvp", description="Duel another cultivator (30m cooldown) — a nominal spirit stone reward for winning")
    @app_commands.guilds(GUILD)
    async def pvp(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        result = await asyncio.to_thread(self.game.start_pvp, interaction.user.id, interaction.user.display_name)
        if not result["ok"]:
            if result.get("reason") == "no_opponents":
                await interaction.response.send_message(
                    "🗡️ No other cultivators have created a character yet — there's no one to duel.",
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                f"🗡️ You're still recovering from your last duel — try again in **{format_duration(result['remaining_seconds'])}**.",
                ephemeral=True,
            )
            return
        # Constructed directly, NOT via asyncio.to_thread -- see the identical note on
        # HuntView's construction above (PvPView.__init__ also calls asyncio.create_task).
        view = PvPView(
            interaction.user.id, self.game, player, interaction.user.display_name, interaction.user.display_avatar.url,
            result["opponent_name"], result["opponent_stats"], result["is_real"],
        )
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        view.message = await interaction.original_response()

    @app_commands.command(name="rest", description="Heal up and pick up a few spirit stones (30m cooldown)")
    @app_commands.guilds(GUILD)
    async def rest(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        result = await asyncio.to_thread(self.game.rest, interaction.user.id, interaction.user.display_name)
        if not result["ok"]:
            await interaction.response.send_message(
                f"🛌 You're not tired yet — try again in **{format_duration(result['remaining_seconds'])}**.",
                ephemeral=True,
            )
            return
        embed = discord.Embed(title="🛌 Resting", color=discord.Color.dark_blue())
        embed.description = (
            f"You take a moment to rest, healing **{result['healed']:.0f}** HP "
            f"({result['hp']:.0f}/{result['max_hp']:.0f}) and finding **{result['stones']}** 🪙 spirit stones along the way."
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="meditate", description="Restore essence and HP, and gain a bit of qi (30m cooldown)")
    @app_commands.guilds(GUILD)
    async def meditate(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        result = await asyncio.to_thread(self.game.meditate, interaction.user.id, interaction.user.display_name)
        if not result["ok"]:
            await interaction.response.send_message(
                f"🧘 Your mind is still settling — try again in **{format_duration(result['remaining_seconds'])}**.",
                ephemeral=True,
            )
            return
        embed = discord.Embed(title="🧘 Meditating", color=discord.Color.dark_purple())
        embed.description = (
            f"You settle into stillness, healing **{result['healed']:.0f}** HP ({result['hp']:.0f}/{result['max_hp']:.0f}), "
            f"restoring **{result['essence_restored']:.0f}** primeval essence ({result['essence']:.0f}/{result['max_essence']:.0f}), "
            f"and banking **{result['qi_gained']:,.2f}** qi."
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="raid", description="Start a boss raid — multiple players can join")
    @app_commands.describe(realm="Which realm of boss to raid (defaults to your own realm)")
    @app_commands.choices(realm=REALM_CHOICES)
    @app_commands.guilds(GUILD)
    async def raid(self, interaction: discord.Interaction, realm: Optional[app_commands.Choice[str]] = None):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        if self.game.has_active_raid(player):
            abandon_view = AbandonRaidView(interaction.user.id, self.game)
            await interaction.response.send_message("🐉 Finish your current raid first!", view=abandon_view, ephemeral=True)
            return
        great_realm_index = int(realm.value) if realm else _default_great_realm_index(player)
        boss_name = raid_boss_name_for_realm(great_realm_index)
        region_modifiers = await asyncio.to_thread(self.game.region_encounter_modifiers, interaction.user.id, interaction.user.display_name)
        # Constructed directly, NOT via asyncio.to_thread -- see the identical note on
        # HuntView's construction above (RaidView.__init__ also calls asyncio.create_task).
        view = RaidView(self.game, boss_name, stat_multiplier=region_modifiers["stat_multiplier"])
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        view.message = await interaction.original_response()
        region_find = await asyncio.to_thread(self.game.maybe_trigger_region_discovery, interaction.user.id, interaction.user.display_name)
        notice = _region_find_notice(region_find)
        if notice:
            await interaction.followup.send(notice, ephemeral=True)

    @app_commands.command(name="solo_raid", description="Instantly start a raid solo — no join window, no other players")
    @app_commands.describe(realm="Which realm of boss to raid (defaults to your own realm)")
    @app_commands.choices(realm=REALM_CHOICES)
    @app_commands.guilds(GUILD)
    async def solo_raid(self, interaction: discord.Interaction, realm: Optional[app_commands.Choice[str]] = None):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        if self.game.has_active_raid(player):
            abandon_view = AbandonRaidView(interaction.user.id, self.game)
            await interaction.response.send_message("🐉 Finish your current raid first!", view=abandon_view, ephemeral=True)
            return
        great_realm_index = int(realm.value) if realm else _default_great_realm_index(player)
        boss_name = raid_boss_name_for_realm(great_realm_index)
        region_modifiers = await asyncio.to_thread(self.game.region_encounter_modifiers, interaction.user.id, interaction.user.display_name)
        # Constructed directly, NOT via asyncio.to_thread -- see the identical note on /raid
        # above (RaidView.__init__ also calls asyncio.create_task).
        view = RaidView(self.game, boss_name, stat_multiplier=region_modifiers["stat_multiplier"])
        # Skips the whole "starting" join-window countdown -- join the caller immediately and
        # move straight to "fighting". RaidView.__init__ already scheduled its own
        # _start_countdown background task, but that harmlessly no-ops once it eventually
        # fires (it only acts while status is still "starting", see its own check).
        await asyncio.to_thread(view._add_participant, interaction.user.id, interaction.user.display_name, player)
        # _begin_fight_or_abandon starts the round timer (asyncio.create_task) -- must stay
        # un-wrapped on the main thread, same rule as every other round-timer kickoff in this
        # codebase (see commit 45e239a).
        view._begin_fight_or_abandon()
        await asyncio.to_thread(view._build_components)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        view.message = await interaction.original_response()
        region_find = await asyncio.to_thread(self.game.maybe_trigger_region_discovery, interaction.user.id, interaction.user.display_name)
        notice = _region_find_notice(region_find)
        if notice:
            await interaction.followup.send(notice, ephemeral=True)

    @app_commands.command(
        name="inheritance_ground",
        description="[Admin] Invite 2-3 others into an inheritance ground (leave blank to solo-test)",
    )
    @app_commands.describe(
        member1="First required teammate (leave blank along with member2 to start solo, for testing)",
        member2="Second required teammate (leave blank along with member1 to start solo, for testing)",
        member3="Optional 4th teammate (only used alongside member1/member2)",
    )
    @app_commands.guilds(GUILD)
    async def inheritance_ground(
        self, interaction: discord.Interaction, member1: Optional[discord.Member] = None,
        member2: Optional[discord.Member] = None, member3: Optional[discord.Member] = None,
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return
        leader = interaction.user
        # Solo test mode: an admin leaves BOTH member1/member2 blank to skip the invite lobby
        # entirely and start immediately as a 1-person team -- everything downstream (the bubble
        # board, battles, Final Trial, betrayal) already tolerates any team size, so this needs
        # no gameplay changes, just a shortcut around the lobby. Giving exactly one of the two
        # is ambiguous (a real team invite needs both), so that's refused rather than guessed at.
        if member1 is None and member2 is None:
            leader_player = await asyncio.to_thread(self.game.get_player_stats, leader.id, leader.display_name)
            if not leader_player["character_confirmed"]:
                await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
                return
            if self.game.has_active_inheritance_ground(leader_player):
                abandon_view = AbandonInheritanceGroundView(leader.id, self.game)
                await interaction.response.send_message("🗺️ Finish your current inheritance ground run first!", view=abandon_view, ephemeral=True)
                return
            remaining = self.game.inheritance_ground_cooldown_remaining(leader_player)
            if remaining > 0:
                await interaction.response.send_message(
                    f"You're still recovering from your last inheritance ground run — try again in **{format_duration(remaining)}**.",
                    ephemeral=True,
                )
                return

            ground_key = "blood_sea_ancestor"  # only one ground exists so far -- see inheritance_ground_data.GROUNDS
            team = [(leader.id, leader.display_name)]
            # Constructed directly, NOT via asyncio.to_thread -- see InheritanceGroundLobbyView's
            # own construction note in inheritance_ground_view.py for why this is a hard rule for
            # every View/Modal in this codebase.
            view = InheritanceGroundView(self.game, ground_key, team)
            await asyncio.to_thread(self.game.start_active_inheritance_ground, [leader.id])
            embed = await asyncio.to_thread(view.build_embed)
            file = await asyncio.to_thread(build_intro_image_file, ground_key)
            if file:
                await interaction.response.send_message(embed=embed, view=view, file=file)
            else:
                await interaction.response.send_message(embed=embed, view=view)
            view.message = await interaction.original_response()
            return

        if member1 is None or member2 is None:
            await interaction.response.send_message(
                "Pick both `member1` and `member2` for a real team, or leave both blank to start solo for testing.",
                ephemeral=True,
            )
            return

        invitees = [member1, member2] + ([member3] if member3 else [])
        if any(m.bot for m in invitees):
            await interaction.response.send_message("You can't invite a bot.", ephemeral=True)
            return
        if len({leader.id, *[m.id for m in invitees]}) != len(invitees) + 1:
            await interaction.response.send_message("Pick 2-3 different teammates — not yourself, and not each other twice.", ephemeral=True)
            return

        leader_player = await asyncio.to_thread(self.game.get_player_stats, leader.id, leader.display_name)
        if not leader_player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        if self.game.has_active_inheritance_ground(leader_player):
            abandon_view = AbandonInheritanceGroundView(leader.id, self.game)
            await interaction.response.send_message("🗺️ Finish your current inheritance ground run first!", view=abandon_view, ephemeral=True)
            return
        remaining = self.game.inheritance_ground_cooldown_remaining(leader_player)
        if remaining > 0:
            await interaction.response.send_message(
                f"You're still recovering from your last inheritance ground run — try again in **{format_duration(remaining)}**.",
                ephemeral=True,
            )
            return

        # Third-person here (about each invitee), unlike InheritanceGroundLobbyView's own
        # accept-time re-check of this exact same eligibility, which is "you"-phrased since
        # that one's checking the clicking player themselves.
        for m in invitees:
            ok, reason_code, _reason_remaining = await asyncio.to_thread(self.game.check_inheritance_ground_eligibility, m.id, m.display_name)
            if not ok:
                messages = {
                    "not_confirmed": f"**{m.display_name}** hasn't confirmed a character yet.",
                    "already_active": f"**{m.display_name}** is already in another inheritance ground run.",
                }
                await interaction.response.send_message(f"Can't invite them right now: {messages[reason_code]}", ephemeral=True)
                return

        ground_key = "blood_sea_ancestor"  # only one ground exists so far -- see inheritance_ground_data.GROUNDS
        # Constructed directly, NOT via asyncio.to_thread -- see InheritanceGroundLobbyView's
        # own construction note in inheritance_ground_view.py for why this is a hard rule for
        # every View/Modal in this codebase.
        view = InheritanceGroundLobbyView(self.game, leader, invitees, ground_key)
        embed = await asyncio.to_thread(view.build_embed)
        mentions = " ".join(m.mention for m in invitees)
        await interaction.response.send_message(
            content=f"{mentions} — **{leader.display_name}** invites you on an inheritance ground run!",
            embed=embed, view=view, ephemeral=False,
        )
        view.message = await interaction.original_response()

    @app_commands.command(name="mine", description="Strike a 5-node ore vein (15m cooldown, Miner rank boosts yield, Luck boosts tier)")
    @app_commands.guilds(GUILD)
    async def mine(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        result = await asyncio.to_thread(self.game.start_mining_vein, interaction.user.id, interaction.user.display_name)
        if not result["ok"]:
            await interaction.response.send_message(
                f"⛏️ Your last dig is still paying off — try again in **{format_duration(result['remaining_seconds'])}**.",
                ephemeral=True,
            )
            return
        view = MiningVeinView( interaction.user.id, self.game, interaction.user.display_name, result["nodes"])
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        view.message = await interaction.original_response()
        notice = _region_find_notice(result.get("region_find"))
        if notice:
            await interaction.followup.send(notice, ephemeral=True)

    @app_commands.command(name="gather", description="Forage a 5-node herb patch (15m cooldown, Gatherer rank boosts yield, Luck boosts tier)")
    @app_commands.guilds(GUILD)
    async def gather(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        result = await asyncio.to_thread(self.game.start_gathering_patch, interaction.user.id, interaction.user.display_name)
        if not result["ok"]:
            await interaction.response.send_message(
                f"🌿 The undergrowth needs time to recover — try again in **{format_duration(result['remaining_seconds'])}**.",
                ephemeral=True,
            )
            return
        view = GatheringPatchView( interaction.user.id, self.game, interaction.user.display_name, result["nodes"])
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        view.message = await interaction.original_response()
        notice = _region_find_notice(result.get("region_find"))
        if notice:
            await interaction.followup.send(notice, ephemeral=True)

    @app_commands.command(name="explore", description="Hunt down a 5-find trail (15m cooldown — Luck and Explorer rank improve your odds)")
    @app_commands.guilds(GUILD)
    async def explore(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        result = await asyncio.to_thread(self.game.start_exploration_hunt, interaction.user.id, interaction.user.display_name)
        if not result["ok"]:
            await interaction.response.send_message(
                f"🧭 You're still resting up from your last trip — try again in **{format_duration(result['remaining_seconds'])}**.",
                ephemeral=True,
            )
            return
        view = ExplorationHuntView( interaction.user.id, self.game, interaction.user.display_name, result["nodes"])
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        view.message = await interaction.original_response()
        notice = _region_find_notice(result.get("region_find"))
        if notice:
            await interaction.followup.send(notice, ephemeral=True)

    @app_commands.command(name="region", description="Choose where your character is in the world (Nascent Soul and below only)")
    @app_commands.guilds(GUILD)
    async def region(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        view = RegionView( interaction.user.id, self.game, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="cd", description="Show all your active cooldowns and timers")
    @app_commands.guilds(GUILD)
    async def cd(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return

        cooldowns = await asyncio.to_thread(self.game.get_cooldowns_status, interaction.user.id, interaction.user.display_name)
        p = cooldowns["player"]
        embed = discord.Embed(title=f"⏱️ {interaction.user.display_name}'s Timers", color=discord.Color.dark_teal())

        def cd_line(label: str, emoji: str, remaining: int) -> str:
            return f"{emoji} **{label}**: ✅ Ready" if remaining <= 0 else f"{emoji} **{label}**: ⏳ {format_duration(remaining)}"

        embed.add_field(
            name="Gathering Cooldowns",
            value="\n".join([
                cd_line("Mine", "⛏️", cooldowns["mine_remaining"]),
                cd_line("Gather", "🌿", cooldowns["gather_remaining"]),
                cd_line("Explore", "🧭", cooldowns["explore_remaining"]),
            ]),
            inline=False,
        )

        search_status = await asyncio.to_thread(self.game.get_search_status, interaction.user.id, interaction.user.display_name)
        if search_status["charges"] > 0:
            search_line = f"🔍 **Search**: ✅ {search_status['charges']}/{search_status['max_charges']} charges"
        else:
            search_line = (
                f"🔍 **Search**: ⏳ {format_duration(search_status['seconds_to_next_charge'])} to next charge "
                f"(0/{search_status['max_charges']})"
            )
        if search_status["active_discovery"]:
            search_line += " — 🗺️ active discovery waiting, run `/discovery`!"
        if cooldowns["treasure_hunt_eligible"]:
            search_line += "\n" + cd_line("Forgotten Blessed Land", "🗺️", cooldowns["treasure_hunt_remaining"])
        embed.add_field(name="Search", value=search_line, inline=False)

        tournament_phase = cooldowns["tournament_phase"]
        tournament_row = cooldowns["tournament_row"]
        if tournament_phase == "signup":
            signup_remaining = max(0, tournament_row["signup_ends_ts"] - int(time.time()))
            tournament_line = f"🏆 **Tournament**: ✅ Signup open — {format_duration(signup_remaining)} left, run `/tournament`!"
        elif tournament_phase == "running":
            tournament_line = "🏆 **Tournament**: ⚔️ Resolving now!"
        else:
            tournament_remaining = cooldown_remaining_seconds(tournament_row)
            tournament_line = cd_line("Tournament", "🏆", tournament_remaining)

        embed.add_field(
            name="Combat Cooldowns",
            value="\n".join([
                cd_line("PvP", "🗡️", cooldowns["pvp_remaining"]),
                cd_line("Battlefield", "⚔️", cooldowns["battlefield_remaining"]),
                cd_line("World Boss", "🐗", cooldowns["world_boss_remaining"]),
                tournament_line,
            ]),
            inline=False,
        )

        embed.add_field(
            name="Recovery Cooldowns",
            value="\n".join([
                cd_line("Rest", "🛌", cooldowns["rest_remaining"]),
                cd_line("Meditate", "🧘", cooldowns["meditate_remaining"]),
            ]),
            inline=False,
        )

        mentor_lines = []
        if cooldowns["sect_disciple_count"] > 0:
            mentor_lines.append(cd_line(f"Teach (sect, {cooldowns['sect_disciple_count']} disciples)", "📖", cooldowns["teach_remaining"]))
        if cooldowns["personal_disciple_count"] > 0:
            readiness = cooldowns["personal_teach_readiness"]
            if readiness["ready"] > 0:
                personal_line = f"🎓 **Teach All (personal)**: ✅ {readiness['ready']}/{cooldowns['personal_disciple_count']} ready"
            else:
                personal_line = (
                    f"🎓 **Teach All (personal)**: ⏳ all {cooldowns['personal_disciple_count']} on cooldown "
                    f"(next ready in {format_duration(readiness['soonest_remaining'])})"
                )
            mentor_lines.append(personal_line)
        if mentor_lines:
            embed.add_field(name="Mentorship Cooldowns", value="\n".join(mentor_lines), inline=False)

        if cooldowns["has_dao_companion"]:
            embed.add_field(name="Dao Companion", value=cd_line("Burst (i dc)", "💞", cooldowns["dc_burst_remaining"]), inline=False)

        if p["studying_profession"]:
            rank_index = p[professions.RANK_COLUMN[p["studying_profession"]]]
            required = professions.hours_required(rank_index)
            elapsed_hours = (time.time() - p["studying_started_ts"]) / 3600
            if required and elapsed_hours < required:
                pct = min(100, elapsed_hours / required * 100)
                study_text = f"📖 **{p['studying_profession']}**: ⏳ {format_duration((required - elapsed_hours) * 3600)} ({pct:.0f}%)"
            else:
                study_text = f"📖 **{p['studying_profession']}**: ✅ Ready to complete — run `/study`!"
        else:
            study_text = "📖 Not studying anything — try `/study`."
        embed.add_field(name="Profession Study", value=study_text, inline=False)

        # Summarized by state rather than one line per plot — with up to 13 plots unlocked
        # at the highest realms, a full per-plot listing would badly clutter this embed.
        # What actually matters at a glance is whether anything needs attention right now.
        farm_overview = await asyncio.to_thread(self.game.get_farm_overview, interaction.user.id, interaction.user.display_name)
        ready_slots = [slot for slot in farm_overview["slots"] if slot["state"] == "ready"]
        growing_slots = [slot for slot in farm_overview["slots"] if slot["state"] == "growing"]
        empty_slots = [slot for slot in farm_overview["slots"] if slot["state"] == "empty"]

        farm_lines = []
        if ready_slots:
            farm_lines.append(f"✅ **{len(ready_slots)}** ready to harvest — run `/farm`!")
        if growing_slots:
            soonest_remaining = min(max(0, slot["grow_hours"] - slot["elapsed_hours"]) * 3600 for slot in growing_slots)
            farm_lines.append(f"⏳ **{len(growing_slots)}** growing — next ready in {format_duration(soonest_remaining)}")
        if empty_slots:
            farm_lines.append(f"🌱 **{len(empty_slots)}** empty — try `/farm`!")
        if not farm_lines:
            farm_lines.append("No farm plots yet.")
        embed.add_field(name=f"Farm Plots ({farm_overview['max_slots']})", value="\n".join(farm_lines), inline=False)

        buffs = await asyncio.to_thread(self.db.get_active_buffs, interaction.user.id)
        now_ts = int(time.time())
        if buffs:
            # Same grouping as /qi's Active Buffs field (see the comment there) — each pill
            # use is its own buff row, so this avoids one line per use blowing past Discord's
            # 1024-char field limit when someone's stacked a lot of the same pill.
            grouped = {}
            for b in buffs:
                entry = grouped.setdefault(b["name"], {"count": 0, "max_remaining": 0})
                entry["count"] += 1
                entry["max_remaining"] = max(entry["max_remaining"], b["expires_at"] - now_ts)
            buff_lines = []
            for name, entry in grouped.items():
                count_text = f" x{entry['count']}" if entry["count"] > 1 else ""
                buff_lines.append(f"✨ **{name}**{count_text}: ⏳ {format_duration(max(0, entry['max_remaining']))}")
            embed.add_field(name="Active Buffs", value="\n".join(buff_lines)[:1024], inline=False)
        else:
            embed.add_field(name="Active Buffs", value="None active.", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="leaderboard", description="Top cultivators by realm, spirit stones, and combat power")
    @app_commands.guilds(GUILD)
    async def leaderboard(self, interaction: discord.Interaction):
        # No character_confirmed gate, deliberately — unlike almost every other command,
        # looking at the leaderboard doesn't touch your own state, and a brand new player
        # deciding whether to /join might reasonably want to see it first.
        view = LeaderboardView( self.game)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="tournament", description="Sign up for a PvP tournament — top 3 get rewards, everyone else gets stones by rank")
    @app_commands.guilds(GUILD)
    async def tournament(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        view = TournamentView( self.game)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="farm", description="Plant and harvest herbs across your farm plots (more plots unlock at higher realms)")
    @app_commands.guilds(GUILD)
    async def farm(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        view = FarmView( interaction.user.id, self.game, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="alchemy", description="Craft a pill from herbs — choose a type, then a tier")
    @app_commands.guilds(GUILD)
    async def alchemy(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        view = AlchemyView( interaction.user.id, self.game, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="blacksmith", description="Forge a weapon or armor piece from ore, beast material, and a beast core")
    @app_commands.guilds(GUILD)
    async def blacksmith(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        view = BlacksmithView( interaction.user.id, self.game, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="weapons", description="List every weapon, head, and body piece you've forged or found, and dismantle ones you don't want")
    @app_commands.guilds(GUILD)
    async def weapons(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        view = WeaponsView( interaction.user.id, self.game, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="accessories", description="View, attune, activate, or salvage your accessories and artifacts")
    @app_commands.guilds(GUILD)
    async def accessories(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        view = AccessoriesView( interaction.user.id, self.game, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="sell", description="Sell items to an NPC vendor for spirit stones — declutter your inventory")
    @app_commands.guilds(GUILD)
    async def sell(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        view = SellView( interaction.user.id, self.game, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="dao_path", description="View and allocate your Spirit Severing Dao Marks across the 14 Dao Paths")
    @app_commands.guilds(GUILD)
    async def dao_path(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        if not self.game.has_reached_spirit_severing(player):
            await interaction.response.send_message(
                "🔒 Dao Paths awaken once you reach **Spirit Severing** realm — keep cultivating!",
                ephemeral=True,
            )
            return
        view = DaoPathView( interaction.user.id, self.game, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="transmute", description="Convert an item into a random item of the same tier (Transformation Dao Path)")
    @app_commands.guilds(GUILD)
    async def transmute(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        if not self.game.has_reached_spirit_severing(player):
            await interaction.response.send_message(
                "🔒 Transmutation awakens once you reach **Spirit Severing** realm — keep cultivating!",
                ephemeral=True,
            )
            return
        view = TransmuteView( interaction.user.id, self.game, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="study", description="View and manage your profession studies")
    @app_commands.guilds(GUILD)
    async def study(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        view = StudyView( interaction.user.id, self.game, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    # -- Manual/Inheritance/Secret Realm/Dream Realm system -------------------------------

    @app_commands.command(name="search", description="Search your region for clues, encounters, and rare discoveries (charges recharge over time)")
    @app_commands.guilds(GUILD)
    async def search(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        # Same "one at a time" gate /battlefield already uses -- without this, a player could
        # spawn several /search messages that all show the same single pending discovery (it's
        # a one-slot-per-player flag, not per-message) and click "Enter Discovery" on each one.
        # enter_discovery itself now also refuses a second entry (see its own docstring), so
        # this is belt-and-suspenders UX rather than the only thing preventing duplicate
        # rewards -- but it also stops the redundant-message spam at the source.
        if player["active_discovery_id"]:
            abandon_view = AbandonDiscoveryView(interaction.user.id, self.game, player["active_discovery_id"])
            await interaction.response.send_message(
                "You already have an active discovery waiting — resolve it with `/discovery` first.", view=abandon_view, ephemeral=True,
            )
            return
        view = SearchView( interaction.user.id, self.game, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="search_status", description="Show your search charges, momentum, and active discovery")
    @app_commands.guilds(GUILD)
    async def search_status(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        status = await asyncio.to_thread(self.game.get_search_status, interaction.user.id, interaction.user.display_name)
        embed = discord.Embed(title=f"🔍 {interaction.user.display_name}'s Search Status", color=discord.Color.dark_teal())
        recharge_text = f" — next in {format_duration(status['seconds_to_next_charge'])}" if status["charges"] < status["max_charges"] else ""
        embed.add_field(name="Charges", value=f"{status['charges']}/{status['max_charges']}{recharge_text}", inline=False)
        embed.add_field(name="Momentum", value=str(status["momentum"]), inline=True)
        embed.add_field(name="Focus", value=status["focus"], inline=True)
        if status["active_discovery"]:
            d = status["active_discovery"]
            embed.add_field(name="Active Discovery", value=f"**{d['theme']}** (Rank {d['rank']}, {d['difficulty']}) — run `/search` and click Enter Discovery, or `/discovery` directly.", inline=False)
        else:
            embed.add_field(name="Active Discovery", value="None — run `/search` to find one.", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="discovery", description="Enter your active inheritance, secret realm, dream realm, or battlefield")
    @app_commands.guilds(GUILD)
    async def discovery(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        result = await asyncio.to_thread(self.game.enter_discovery, interaction.user.id, interaction.user.display_name)
        if not result["ok"]:
            if result["reason"] == "expired":
                await interaction.response.send_message("That discovery expired before you got to it. Run `/search` to find another.", ephemeral=True)
            elif result["reason"] == "already_entered":
                abandon_view = AbandonDiscoveryView(interaction.user.id, self.game, player["active_discovery_id"])
                await interaction.response.send_message(
                    "You're already inside that discovery somewhere else — finish or abandon it there first.",
                    view=abandon_view, ephemeral=True,
                )
            else:
                await interaction.response.send_message("You don't have an active discovery — run `/search` to find one first.", ephemeral=True)
            return
        # Constructed directly, NOT via asyncio.to_thread -- can return a BattlefieldView,
        # whose __init__ calls asyncio.create_task (see the identical note on HuntView's
        # construction above). The one non-DB-safe branch (BattlefieldView's "player" lookup)
        # is a single brief row read, not a bulk loop.
        view = build_discovery_entry_view(
            interaction.user.id, self.game, interaction.user.display_name, interaction.user.display_avatar.url, result,
        )
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        view.message = await interaction.original_response()

    @app_commands.command(name="battlefield", description="Seek out a battlefield and fight through progressively harder waves (6h cooldown)")
    @app_commands.guilds(GUILD)
    async def battlefield(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        result = await asyncio.to_thread(self.game.start_battlefield, interaction.user.id, interaction.user.display_name)
        if not result["ok"]:
            if result["reason"] == "cooldown":
                await interaction.response.send_message(
                    f"You're still recovering from your last battlefield — try again in **{format_duration(result['remaining_seconds'])}**.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "You already have an active discovery waiting — resolve it with `/discovery` first.", ephemeral=True,
                )
            return
        # Constructed directly, NOT via asyncio.to_thread -- see the identical note on
        # HuntView's construction above (BattlefieldView.__init__ also calls asyncio.create_task).
        view = BattlefieldView(
            interaction.user.id, self.game, player, interaction.user.display_name,
            interaction.user.display_avatar.url, result["discovery"],
        )
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        view.message = await interaction.original_response()

    # -- World Boss (see world_boss.py's own module docstring) -----------------------------

    def _world_boss_status_embed(self, status: dict, user_id: int) -> discord.Embed:
        if not status["active"]:
            embed = discord.Embed(
                title="🗡️ World Boss",
                description="No World Boss is currently active.",
                color=discord.Color.dark_grey(),
            )
            if status["next_spawn_remaining"] > 0:
                embed.add_field(name="Next Spawn", value=f"⏳ {format_duration(status['next_spawn_remaining'])}", inline=False)
            else:
                embed.add_field(name="Next Spawn", value="Any moment now.", inline=False)
            return embed

        boss, roster = status["boss"], status["roster"]
        pct = 100 * max(0, boss["current_hp"]) / boss["max_hp"]
        embed = discord.Embed(
            title=f"{roster['emoji']} {roster['name']}",
            description=f"*{roster['theme']}*\n_{roster['description']}_",
            color=discord.Color.dark_red(),
        )
        embed.add_field(
            name="❤️ HP",
            value=f"`{boss['current_hp']:,} / {boss['max_hp']:,}` ({pct:.2f}%)\n`{render_bar(boss['current_hp'], boss['max_hp'])}`",
            inline=False,
        )
        remaining = max(0, boss["expires_ts"] - int(time.time()))
        embed.add_field(name="⏱️ Time Remaining", value=format_duration(remaining), inline=True)

        mine = self.db.get_world_boss_damage(boss["boss_instance_id"], user_id)
        if mine:
            embed.add_field(name="🗡️ Your Contribution", value=f"{mine['damage_dealt']:,} damage ({mine['attacks']} attacks)", inline=True)
        embed.set_footer(
            text=f"Use /raidboss_attack to join the fight! {world_boss.WORLD_BOSS_ATTACKS_PER_COOLDOWN} strikes every "
                 f"{format_duration(world_boss.WORLD_BOSS_ATTACK_COOLDOWN_SECONDS)}."
        )
        return embed

    @app_commands.command(name="raidboss", description="Show the current World Boss's status")
    @app_commands.guilds(GUILD)
    async def raidboss(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        status = await asyncio.to_thread(self.game.get_world_boss_status)
        embed = await asyncio.to_thread(self._world_boss_status_embed, status, interaction.user.id)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="raidboss_attack", description="Attack the current World Boss — every cultivation realm can safely join in")
    @app_commands.guilds(GUILD)
    async def raidboss_attack(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        result = await asyncio.to_thread(self.game.start_world_boss_attack_session, interaction.user.id, interaction.user.display_name)
        if not result["ok"]:
            if result["reason"] == "cooldown":
                await interaction.response.send_message(
                    f"You're still recovering from your last strike — try again in **{format_duration(result['remaining_seconds'])}**.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message("No World Boss is currently active — check back soon with `/raidboss`.", ephemeral=True)
            return

        view = WorldBossView(
            interaction.user.id, self.game, interaction.user.display_name,
            interaction.user.display_avatar.url, result["boss"], on_defeat=self._announce_world_boss_defeat,
        )
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        view.message = await interaction.original_response()

    @app_commands.command(name="raidboss_spawn", description="[Admin] Force-spawn a fresh World Boss, ending any current one early")
    @app_commands.guilds(GUILD)
    async def raidboss_spawn(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return
        boss = await asyncio.to_thread(self.game.maybe_spawn_world_boss, force=True)
        roster = world_boss.WORLD_BOSSES[boss["boss_key"]]
        await asyncio.to_thread(
            self.db.log_admin_action,
            interaction.user.id, interaction.user.display_name, 0, "World Boss", "raidboss_spawn", roster["name"],
        )
        await interaction.response.send_message(f"{roster['emoji']} Force-spawned **{roster['name']}**.", ephemeral=True)
        await self._announce_world_boss_spawn(boss)

    @app_commands.command(name="manual", description="Study, refine, assemble, equip, and dismantle cultivation manual pages")
    @app_commands.guilds(GUILD)
    async def manual(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        view = ManualView( interaction.user.id, self.game, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="trade", description="Offer another player a trade of items and/or spirit stones")
    @app_commands.guilds(GUILD)
    @app_commands.describe(target="The player to trade with")
    async def trade(self, interaction: discord.Interaction, target: discord.Member):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        if target.bot:
            await interaction.response.send_message("You can't trade with a bot.", ephemeral=True)
            return
        target_player = await asyncio.to_thread(self.game.get_player_stats, target.id, target.display_name)
        if not target_player["character_confirmed"]:
            await interaction.response.send_message(f"{target.display_name} hasn't created a character yet.", ephemeral=True)
            return

        error = await asyncio.to_thread(self.game.can_start_trade, interaction.user.id, target.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        trade_id = await asyncio.to_thread(self.game.start_trade, interaction.user.id, target.id)
        view = TradeRequestView( self.game, trade_id, interaction.user, target)
        # A mention inside an embed alone doesn't ping — it has to be in the actual message
        # content for Discord to notify the target.
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(content=target.mention, embed=embed, view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="gamble", description="Challenge another player to a winner-take-all dice gamble (1-100, high roll takes both pots)")
    @app_commands.guilds(GUILD)
    @app_commands.describe(target="The player to gamble with")
    async def gamble(self, interaction: discord.Interaction, target: discord.Member):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        if target.bot:
            await interaction.response.send_message("You can't gamble with a bot.", ephemeral=True)
            return
        target_player = await asyncio.to_thread(self.game.get_player_stats, target.id, target.display_name)
        if not target_player["character_confirmed"]:
            await interaction.response.send_message(f"{target.display_name} hasn't created a character yet.", ephemeral=True)
            return

        error = await asyncio.to_thread(self.game.can_start_trade, interaction.user.id, target.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        trade_id = await asyncio.to_thread(self.game.start_gamble, interaction.user.id, target.id)
        view = TradeRequestView( self.game, trade_id, interaction.user, target)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(content=target.mention, embed=embed, view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="exchange_essence", description="Convert spirit stones into primeval essence")
    @app_commands.describe(amount="How many spirit stones to spend")
    @app_commands.guilds(GUILD)
    async def exchange_essence(self, interaction: discord.Interaction, amount: int):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        if amount < 1:
            await interaction.response.send_message("Amount must be at least 1.", ephemeral=True)
            return

        stones_spent, essence_gained, new_stones, new_essence, max_essence = await asyncio.to_thread(
            self.game.exchange_stones_for_essence, interaction.user.id, interaction.user.display_name, amount,
        )
        if essence_gained == 0:
            reason = "your primeval essence is already full" if new_essence >= max_essence else "you don't have enough spirit stones"
            await interaction.response.send_message(f"No essence gained — {reason}.", ephemeral=True)
            return

        embed = discord.Embed(
            title="💠 Essence Gathered",
            description=f"Spent **{stones_spent:,}** spirit stones to gain **{essence_gained:,}** primeval essence.",
            color=discord.Color.dark_purple(),
        )
        embed.add_field(name="🪙 Spirit Stones", value=f"{new_stones:,}", inline=True)
        embed.add_field(name="💠 Primeval Essence", value=f"{new_essence}/{max_essence}", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="absorb_essence", description="Consume primeval essence for an instant burst of Qi")
    @app_commands.describe(amount="How much primeval essence to spend")
    @app_commands.guilds(GUILD)
    async def absorb_essence(self, interaction: discord.Interaction, amount: int):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        if amount < 1:
            await interaction.response.send_message("Amount must be at least 1.", ephemeral=True)
            return

        essence_spent, qi_gained, new_essence, new_qi = await asyncio.to_thread(
            self.game.consume_essence_for_qi, interaction.user.id, interaction.user.display_name, amount,
        )
        if essence_spent == 0:
            await interaction.response.send_message("You don't have any primeval essence to absorb.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🌀 Essence Absorbed",
            description=f"Consumed **{essence_spent:,.0f}** primeval essence to gain **{qi_gained:,.0f}** qi.",
            color=discord.Color.dark_purple(),
        )
        embed.add_field(name="💠 Primeval Essence", value=f"{new_essence:,.0f}", inline=True)
        embed.add_field(name="⚡ Total Qi", value=f"{new_qi:,.0f}", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    async def _item_name_autocomplete(self, interaction: discord.Interaction, current: str):
        # ITEMS covers materials/pills/gear catalog entries; tiered Gu (crafted-family AND
        # canon_gu.py's own 26) live in equipment.EQUIPMENT instead, keyed as
        # "{family} ({quality})" (see equipment.gu_item_name) -- offered here too so admins
        # can actually grant one, not just plain catalog items.
        names = list(ITEMS) + [name for name in equipment.EQUIPMENT if equipment.parse_gu_name(name)[0] is not None]
        return [
            app_commands.Choice(name=name, value=name)
            for name in names
            if current.lower() in name.lower()
        ][:25]

    @app_commands.command(name="grant_item", description="[Admin] Grant an item to a player for testing")
    @app_commands.guilds(GUILD)
    @app_commands.describe(item_name="Item to grant", quantity="How many to grant", member="Player to grant it to (defaults to you)")
    @app_commands.autocomplete(item_name=_item_name_autocomplete)
    async def grant_item(self, interaction: discord.Interaction, item_name: str, quantity: int = 1, member: Optional[discord.Member] = None):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return
        is_gu = equipment.parse_gu_name(item_name)[0] is not None
        if item_name not in ITEMS and not is_gu:
            await interaction.response.send_message(f"Unknown item `{item_name}`. Start typing to see valid items/Gu.", ephemeral=True)
            return
        if quantity < 1:
            await interaction.response.send_message("Quantity must be at least 1.", ephemeral=True)
            return

        target = member or interaction.user

        def _do_grant():
            self.game.get_player_stats(target.id, target.display_name)
            self.db.add_item(target.id, item_name, quantity)
            self.db.log_admin_action(
                interaction.user.id, interaction.user.display_name,
                target.id, target.display_name,
                "grant_item", f"{quantity}x {item_name}",
            )

        await asyncio.to_thread(_do_grant)
        await interaction.response.send_message(
            f"Granted **{quantity}x {item_name}** to {target.display_name}.", ephemeral=True
        )

    @app_commands.command(name="grant_stones", description="[Admin] Grant spirit stones to a player for testing")
    @app_commands.guilds(GUILD)
    @app_commands.describe(amount="How many spirit stones to grant", member="Player to grant them to (defaults to you)")
    async def grant_stones(self, interaction: discord.Interaction, amount: int, member: Optional[discord.Member] = None):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return
        if amount < 1:
            await interaction.response.send_message("Amount must be at least 1.", ephemeral=True)
            return

        target = member or interaction.user

        def _do_grant():
            self.game.get_player_stats(target.id, target.display_name)
            self.db.add_spirit_stones(target.id, amount)
            self.db.log_admin_action(
                interaction.user.id, interaction.user.display_name,
                target.id, target.display_name,
                "grant_stones", f"{amount:,} spirit stones",
            )

        await asyncio.to_thread(_do_grant)
        await interaction.response.send_message(
            f"Granted **{amount:,}** spirit stones to {target.display_name}.", ephemeral=True
        )

    @app_commands.command(name="reset_cooldowns", description="[Admin] Reset all of a player's action cooldowns")
    @app_commands.guilds(GUILD)
    @app_commands.describe(member="Player whose cooldowns to reset (defaults to you)")
    async def reset_cooldowns(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return

        target = member or interaction.user

        def _do_reset():
            self.game.get_player_stats(target.id, target.display_name)
            self.db.reset_all_cooldowns(target.id)
            self.db.log_admin_action(
                interaction.user.id, interaction.user.display_name,
                target.id, target.display_name,
                "reset_cooldowns", "all action cooldowns cleared",
            )

        await asyncio.to_thread(_do_reset)
        await interaction.response.send_message(
            f"Reset all cooldowns for **{target.display_name}** — mine, gather, explore, battlefield, pvp, rest, meditate, "
            f"manual change, region change, and teach (sect + personal).",
            ephemeral=True,
        )

    @app_commands.command(name="grant_profession_rank", description="[Admin] Grant a player ranks in a profession")
    @app_commands.guilds(GUILD)
    @app_commands.describe(profession="Which profession to advance", amount="How many ranks to grant (default 1)", member="Player to grant it to (defaults to you)")
    @app_commands.choices(profession=[app_commands.Choice(name=name, value=name) for name in professions.PROFESSIONS])
    async def grant_profession_rank(
        self,
        interaction: discord.Interaction,
        profession: app_commands.Choice[str],
        amount: int = 1,
        member: Optional[discord.Member] = None,
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return
        if amount < 1:
            await interaction.response.send_message("Amount must be at least 1.", ephemeral=True)
            return

        target = member or interaction.user

        def _do_grant():
            result = self.game.grant_profession_rank(target.id, target.display_name, profession.value, amount)
            self.db.log_admin_action(
                interaction.user.id, interaction.user.display_name,
                target.id, target.display_name,
                "grant_profession_rank", f"{profession.value} +{amount} ({professions.rank_name(result['old_rank'])} -> {professions.rank_name(result['new_rank'])})",
            )
            return result

        result = await asyncio.to_thread(_do_grant)
        cap_note = " (capped at Dao Master)" if result["capped"] else ""
        await interaction.response.send_message(
            f"Granted **{target.display_name}** {profession.value} rank: "
            f"**{professions.rank_name(result['old_rank'])}** -> **{professions.rank_name(result['new_rank'])}**{cap_note}.",
            ephemeral=True,
        )

    @app_commands.command(name="grant_gear", description="[Admin] Grant a player a freshly-rolled piece of crafted gear")
    @app_commands.guilds(GUILD)
    @app_commands.describe(
        gear_type="Sword (Weapon), Helm (Head), or Armor (Body)",
        tier="Gear tier (1-7)",
        member="Player to grant it to (defaults to you)",
    )
    @app_commands.choices(gear_type=GRANT_GEAR_TYPE_CHOICES)
    async def grant_gear(
        self,
        interaction: discord.Interaction,
        gear_type: app_commands.Choice[str],
        tier: int,
        member: Optional[discord.Member] = None,
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return
        if not (blacksmith.MIN_TIER <= tier <= blacksmith.MAX_TIER):
            await interaction.response.send_message(f"Tier must be between {blacksmith.MIN_TIER} and {blacksmith.MAX_TIER}.", ephemeral=True)
            return

        target = member or interaction.user

        def _do_grant():
            result = self.game.grant_crafted_gear(target.id, target.display_name, gear_type.value, tier)
            self.db.log_admin_action(
                interaction.user.id, interaction.user.display_name,
                target.id, target.display_name,
                "grant_gear", f"{result['item_name']} (power {result['power_score']:.1f})",
            )
            return result

        result = await asyncio.to_thread(_do_grant)
        await interaction.response.send_message(
            f"Granted **{target.display_name}** a freshly-rolled **{result['item_name']}** "
            f"(power {result['power_score']:.1f}): {equipment.describe_stat_bonuses(result['stat_bonuses'])}.",
            ephemeral=True,
        )

    @app_commands.command(name="backfill_dao_marks", description="[Admin, one-time] Retroactively grant Dao Marks for breakthroughs already completed")
    @app_commands.guilds(GUILD)
    async def backfill_dao_marks(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return
        # Iterates every confirmed player -- defer BEFORE the loop, not after (see the Use All/
        # Make All "Unknown interaction" fix: a chain of DB work across many players can easily
        # exceed Discord's ~3s ACK window).
        await interaction.response.defer(ephemeral=True)

        granted = await asyncio.to_thread(self.game.backfill_dao_marks_for_all_players)
        total_marks = sum(g["marks_granted"] for g in granted)
        self.db.log_admin_action(
            interaction.user.id, interaction.user.display_name,
            interaction.user.id, "everyone",
            "backfill_dao_marks", f"{len(granted)} players granted, {total_marks:,} total marks",
        )

        if not granted:
            await interaction.followup.send("No players needed a backfill (everyone was already covered, or nobody's reached Spirit Severing yet).", ephemeral=True)
            return

        top = sorted(granted, key=lambda g: -g["marks_granted"])[:10]
        top_lines = [f"**{g['name']}**: {g['marks_granted']:,} marks" for g in top]
        more_note = f"\n...and {len(granted) - 10} more." if len(granted) > 10 else ""
        await interaction.followup.send(
            f"Backfilled **{len(granted)}** player(s), **{total_marks:,}** total Dao Marks granted.\n"
            f"Top recipients:\n" + "\n".join(top_lines) + more_note,
            ephemeral=True,
        )

    @app_commands.command(name="audit_log", description="[Admin] Review recent /grant_item, /grant_stones, and /reset_cooldowns activity")
    @app_commands.guilds(GUILD)
    @app_commands.describe(member="Only show entries granted TO this player (defaults to everyone)", limit="How many entries to show (default 20, max 50)")
    async def audit_log(self, interaction: discord.Interaction, member: Optional[discord.Member] = None, limit: int = 20):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return
        limit = max(1, min(50, limit))
        entries = await asyncio.to_thread(self.db.get_audit_log, limit=limit, target_id=member.id if member else None)
        if not entries:
            await interaction.response.send_message("No matching audit log entries.", ephemeral=True)
            return

        lines = []
        for entry in entries:
            when = f"<t:{entry['created_ts']}:R>"
            lines.append(
                f"{when} — **{entry['actor_name']}** ({entry['action']}) → **{entry['target_name']}**: {entry['detail']}"
            )
        embed = discord.Embed(
            title="Admin Audit Log",
            description="\n".join(lines),
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # -- Sects (Phase 1: core structure only — see sects.py's own module docstring for what's
    # deliberately deferred) -----------------------------------------------------------------

    async def _sect_name_autocomplete(self, interaction: discord.Interaction, current: str):
        all_sects = await asyncio.to_thread(self.db.list_sects)
        return [
            app_commands.Choice(name=f"{sect['name']} ({sect['member_count']}/{sects.MAX_MEMBERS})", value=sect["name"])
            for sect in all_sects
            if current.lower() in sect["name"].lower()
        ][:25]

    @app_commands.command(name="sect", description="View and manage your sect — buttons are gated by your rank")
    @app_commands.guilds(GUILD)
    async def sect(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        view = SectView( interaction.user.id, self.game, interaction.user.display_name)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="sect_list", description="Browse every sect")
    @app_commands.guilds(GUILD)
    async def sect_list(self, interaction: discord.Interaction):
        all_sects = await asyncio.to_thread(self.game.sect_list)
        if not all_sects:
            await interaction.response.send_message("No sects exist yet — be the first with `/sect_create`!", ephemeral=True)
            return
        lines = [
            f"{sect['banner']} **{sect['name']}** — {sect['member_count']}/{sects.MAX_MEMBERS} members, "
            f"🪙 {sect['treasury_spirit_stones']:,} treasury"
            for sect in all_sects
        ]
        embed = discord.Embed(title="🏯 Sects", description="\n".join(lines)[:4096], color=discord.Color.dark_teal())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="sect_create", description="Found a new sect and become its Sect Leader")
    @app_commands.guilds(GUILD)
    @app_commands.describe(name="Your sect's name")
    async def sect_create(self, interaction: discord.Interaction, name: str):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        ok, message = await asyncio.to_thread(self.game.sect_create, interaction.user.id, interaction.user.display_name, name)
        await interaction.response.send_message(message, ephemeral=not ok)

    @app_commands.command(name="sect_join", description="Apply to join a sect (needs approval from a Vice Leader or Sect Leader)")
    @app_commands.guilds(GUILD)
    @app_commands.describe(name="The sect's name")
    @app_commands.autocomplete(name=_sect_name_autocomplete)
    async def sect_join(self, interaction: discord.Interaction, name: str):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        ok, message = await asyncio.to_thread(self.game.sect_join, interaction.user.id, interaction.user.display_name, name)
        await interaction.response.send_message(message, ephemeral=not ok)

    @app_commands.command(name="sect_cancel_application", description="Cancel your pending sect application")
    @app_commands.guilds(GUILD)
    async def sect_cancel_application(self, interaction: discord.Interaction):
        ok, message = await asyncio.to_thread(self.game.sect_cancel_application, interaction.user.id, interaction.user.display_name)
        await interaction.response.send_message(message, ephemeral=not ok)

    @app_commands.command(name="sect_leave", description="Leave your current sect")
    @app_commands.guilds(GUILD)
    async def sect_leave(self, interaction: discord.Interaction):
        ok, message = await asyncio.to_thread(self.game.sect_leave, interaction.user.id, interaction.user.display_name)
        await interaction.response.send_message(message, ephemeral=not ok)

    @app_commands.command(name="sect_transfer", description="[Sect Leader] Hand leadership to another member")
    @app_commands.guilds(GUILD)
    @app_commands.describe(member="The member to make Sect Leader")
    async def sect_transfer(self, interaction: discord.Interaction, member: discord.Member):
        ok, message = await asyncio.to_thread(
            self.game.sect_transfer_leadership, interaction.user.id, interaction.user.display_name, member.id, member.display_name,
        )
        await interaction.response.send_message(message, ephemeral=not ok)

    @app_commands.command(name="sect_kick", description="[Sect Leader] Expel a member from the sect")
    @app_commands.guilds(GUILD)
    @app_commands.describe(member="The member to expel")
    async def sect_kick(self, interaction: discord.Interaction, member: discord.Member):
        ok, message = await asyncio.to_thread(
            self.game.sect_kick, interaction.user.id, interaction.user.display_name, member.id, member.display_name,
        )
        await interaction.response.send_message(message, ephemeral=not ok)

    @app_commands.command(name="sect_promote", description="Promote a sect member one rank")
    @app_commands.guilds(GUILD)
    @app_commands.describe(member="The member to promote")
    async def sect_promote(self, interaction: discord.Interaction, member: discord.Member):
        ok, message = await asyncio.to_thread(
            self.game.sect_promote, interaction.user.id, interaction.user.display_name, member.id, member.display_name,
        )
        await interaction.response.send_message(message, ephemeral=not ok)

    @app_commands.command(name="sect_demote", description="[Sect Leader] Demote a sect member one rank")
    @app_commands.guilds(GUILD)
    @app_commands.describe(member="The member to demote")
    async def sect_demote(self, interaction: discord.Interaction, member: discord.Member):
        ok, message = await asyncio.to_thread(
            self.game.sect_demote, interaction.user.id, interaction.user.display_name, member.id, member.display_name,
        )
        await interaction.response.send_message(message, ephemeral=not ok)

    @app_commands.command(name="sect_donate", description="Donate spirit stones to your sect's treasury")
    @app_commands.guilds(GUILD)
    @app_commands.describe(amount="How many spirit stones to donate")
    async def sect_donate(self, interaction: discord.Interaction, amount: int):
        ok, message = await asyncio.to_thread(self.game.sect_donate, interaction.user.id, interaction.user.display_name, amount)
        await interaction.response.send_message(message, ephemeral=not ok)

    @app_commands.command(name="sect_withdraw", description="[Sect Leader/Vice Leader] Withdraw spirit stones from the treasury")
    @app_commands.guilds(GUILD)
    @app_commands.describe(amount="How many spirit stones to withdraw")
    async def sect_withdraw(self, interaction: discord.Interaction, amount: int):
        ok, message = await asyncio.to_thread(self.game.sect_withdraw, interaction.user.id, interaction.user.display_name, amount)
        await interaction.response.send_message(message, ephemeral=not ok)

    @app_commands.command(name="sect_motto", description="[Sect Leader] Set your sect's motto")
    @app_commands.guilds(GUILD)
    @app_commands.describe(motto="The new motto (leave blank to clear it)")
    async def sect_motto(self, interaction: discord.Interaction, motto: str = ""):
        ok, message = await asyncio.to_thread(self.game.sect_set_motto, interaction.user.id, interaction.user.display_name, motto)
        await interaction.response.send_message(message, ephemeral=not ok)

    @app_commands.command(name="sect_banner", description="[Sect Leader] Set your sect's banner emoji")
    @app_commands.guilds(GUILD)
    @app_commands.describe(banner="A single emoji to represent your sect")
    async def sect_banner(self, interaction: discord.Interaction, banner: str):
        ok, message = await asyncio.to_thread(self.game.sect_set_banner, interaction.user.id, interaction.user.display_name, banner)
        await interaction.response.send_message(message, ephemeral=not ok)

    @app_commands.command(name="sect_rename", description="[Sect Leader] Rename your sect")
    @app_commands.guilds(GUILD)
    @app_commands.describe(name="The sect's new name")
    async def sect_rename(self, interaction: discord.Interaction, name: str):
        ok, message = await asyncio.to_thread(self.game.sect_rename, interaction.user.id, interaction.user.display_name, name)
        await interaction.response.send_message(message, ephemeral=not ok)

    # -- Mentor/disciple (Phase 2 — see sects.py's own module docstring for what's simplified
    # or deferred) --------------------------------------------------------------------------

    @app_commands.command(name="accept_disciple", description="[Elder+] Offer to take a fellow sect member as your disciple")
    @app_commands.guilds(GUILD)
    @app_commands.describe(member="The sect member to offer mentorship to")
    async def accept_disciple(self, interaction: discord.Interaction, member: discord.Member):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        if member.id == interaction.user.id:
            await interaction.response.send_message("You can't take yourself as a disciple.", ephemeral=True)
            return
        ok, reason = await asyncio.to_thread(
            self.game.sect_can_offer_disciple, interaction.user.id, interaction.user.display_name, member.id, member.display_name,
        )
        if not ok:
            await interaction.response.send_message(reason, ephemeral=True)
            return
        view = MentorRequestView( self.game, interaction.user, member, self.game.sect_accept_disciple, offer_label="sect disciple",
        )
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="teach", description="Teach every sect AND personal disciple who isn't currently on cooldown, in one go")
    @app_commands.guilds(GUILD)
    async def teach(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        result = await asyncio.to_thread(self.game.teach_all, interaction.user.id, interaction.user.display_name)
        if not result["ok"]:
            await interaction.response.send_message(result["reason"], ephemeral=True)
            return

        embed = discord.Embed(title="📖 Teach — Complete", color=discord.Color.dark_teal())
        footer_bits = []

        # Sect side -- only present at all if the player is in a sect with real disciples (see
        # GameManager.teach_all); a sect-level refusal (e.g. still on the shared cooldown) shows
        # up here as informational content, not as a failure of the whole command.
        sect = result["sect"]
        if sect is not None:
            if not sect["ok"]:
                embed.add_field(name="⚔️ Sect", value=sect["reason"], inline=False)
            else:
                taught, beyond = sect["taught"], sect["beyond_instruction"]
                if taught:
                    lines = [f"**{t['name']}**: +{t['qi_granted']:,.1f} Qi" for t in taught]
                    total_bonus = sum(t["master_bonus"] for t in taught)
                    lines.append(f"_You gain **{total_bonus:,.1f}** Qi of your own from the lessons._")
                else:
                    lines = ["_No one could be taught this time._"]
                embed.add_field(name=f"⚔️ Sect — Taught ({len(taught)})", value="\n".join(lines)[:1024], inline=False)
                if beyond:
                    beyond_lines = [f"**{d['name']}** — {d['reason']}" for d in beyond]
                    embed.add_field(name=f"⚔️ Sect — Beyond Instruction ({len(beyond)})", value="\n".join(beyond_lines)[:1024], inline=False)
            footer_bits.append(f"Sect: shared {format_duration(sects.TEACH_COOLDOWN_SECONDS)} cooldown for the whole lesson")

        # Personal side -- present if the player has any personal disciples at all, regardless
        # of sect membership; each disciple carries their own independent cooldown.
        personal = result["personal"]
        if personal is not None:
            taught, on_cooldown, beyond = personal["taught"], personal["on_cooldown"], personal["beyond_instruction"]
            if taught:
                lines = [f"**{t['name']}**: +{t['qi_granted']:,.1f} Qi" for t in taught]
                total_bonus = sum(t["master_bonus"] for t in taught)
                lines.append(f"_You gain **{total_bonus:,.1f}** Qi of your own from the lessons._")
            else:
                lines = ["_No one was ready this time._"]
            embed.add_field(name=f"🎓 Personal — Taught ({len(taught)})", value="\n".join(lines)[:1024], inline=False)
            if on_cooldown:
                cd_lines = [f"**{d['name']}** — {format_duration(d['remaining'])}" for d in on_cooldown]
                embed.add_field(name=f"🎓 Personal — On Cooldown ({len(on_cooldown)})", value="\n".join(cd_lines)[:1024], inline=False)
            if beyond:
                beyond_lines = [f"**{d['name']}** — {d['reason']}" for d in beyond]
                embed.add_field(name=f"🎓 Personal — Beyond Instruction ({len(beyond)})", value="\n".join(beyond_lines)[:1024], inline=False)
            footer_bits.append(f"Personal: each disciple's own {format_duration(sects.PERSONAL_TEACH_COOLDOWN_SECONDS)} cooldown")

        embed.set_footer(text=" • ".join(footer_bits))
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="release_disciple", description="Release one of your disciples from mentorship")
    @app_commands.guilds(GUILD)
    @app_commands.describe(disciple="Which of your disciples to release")
    async def release_disciple(self, interaction: discord.Interaction, disciple: discord.Member):
        ok, message = await asyncio.to_thread(
            self.game.sect_release_disciple, interaction.user.id, interaction.user.display_name, disciple.id, disciple.display_name,
        )
        await interaction.response.send_message(message, ephemeral=not ok)

    @app_commands.command(name="leave_master", description="Part ways with your current master")
    @app_commands.guilds(GUILD)
    async def leave_master(self, interaction: discord.Interaction):
        ok, message = await asyncio.to_thread(self.game.sect_leave_master, interaction.user.id, interaction.user.display_name)
        await interaction.response.send_message(message, ephemeral=not ok)

    @app_commands.command(name="sect_master", description="See who your sect master is, their realm, and how long you've been their disciple")
    @app_commands.guilds(GUILD)
    async def sect_master(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        info = await asyncio.to_thread(self.game.get_sect_master_info, interaction.user.id, interaction.user.display_name)
        if info is None:
            await interaction.response.send_message(
                "You don't have a sect master right now — an Elder+ in your sect can take you on with `/accept_disciple`.",
                ephemeral=True,
            )
            return
        embed = discord.Embed(title="📜 Your Sect Master", color=discord.Color.dark_gold())
        embed.add_field(name="Master", value=info["master_name"], inline=True)
        embed.add_field(name="Realm", value=info["master_realm"], inline=True)
        embed.add_field(name="Times Taught", value=str(info["times_taught"]), inline=True)
        since_text = format_duration(int(time.time()) - info["since_ts"]) if info["since_ts"] else "unknown"
        embed.add_field(name="Disciple For", value=since_text, inline=True)
        await interaction.response.send_message(embed=embed)

    # -- Personal disciples (no sect required — see sects.py's own module docstring) ------

    @app_commands.command(name="master_offer", description="Offer to take ANY player as your personal disciple — no sect needed (max 3)")
    @app_commands.guilds(GUILD)
    @app_commands.describe(member="The player to offer personal mentorship to")
    async def master_offer(self, interaction: discord.Interaction, member: discord.Member):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        if member.id == interaction.user.id:
            await interaction.response.send_message("You can't take yourself as a disciple.", ephemeral=True)
            return
        ok, reason = await asyncio.to_thread(
            self.game.personal_can_offer_disciple, interaction.user.id, interaction.user.display_name, member.id, member.display_name,
        )
        if not ok:
            await interaction.response.send_message(reason, ephemeral=True)
            return
        view = MentorRequestView( self.game, interaction.user, member, self.game.personal_accept_disciple, offer_label="personal disciple",
        )
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="master_release", description="Release one of your personal disciples")
    @app_commands.guilds(GUILD)
    @app_commands.describe(disciple="Which of your personal disciples to release")
    async def master_release(self, interaction: discord.Interaction, disciple: discord.Member):
        ok, message = await asyncio.to_thread(
            self.game.personal_release_disciple, interaction.user.id, interaction.user.display_name, disciple.id, disciple.display_name,
        )
        await interaction.response.send_message(message, ephemeral=not ok)

    @app_commands.command(name="master_leave", description="Part ways with your personal master")
    @app_commands.guilds(GUILD)
    async def master_leave(self, interaction: discord.Interaction):
        ok, message = await asyncio.to_thread(self.game.personal_leave_master, interaction.user.id, interaction.user.display_name)
        await interaction.response.send_message(message, ephemeral=not ok)

    @app_commands.command(name="master", description="See who your personal master is, their realm, and how long you've been their disciple")
    @app_commands.guilds(GUILD)
    async def master(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        info = await asyncio.to_thread(self.game.get_personal_master_info, interaction.user.id, interaction.user.display_name)
        if info is None:
            await interaction.response.send_message(
                "You don't have a personal master right now — anyone can take you on with `/master_offer`.",
                ephemeral=True,
            )
            return
        embed = discord.Embed(title="🎓 Your Personal Master", color=discord.Color.dark_teal())
        embed.add_field(name="Master", value=info["master_name"], inline=True)
        embed.add_field(name="Realm", value=info["master_realm"], inline=True)
        embed.add_field(name="Times Taught", value=str(info["times_taught"]), inline=True)
        since_text = format_duration(int(time.time()) - info["since_ts"]) if info["since_ts"] else "unknown"
        embed.add_field(name="Disciple For", value=since_text, inline=True)
        await interaction.response.send_message(embed=embed)

    # -- Dao Companion (see game/dao_companion.py / GameManager's dao_companion_* methods) --

    @app_commands.command(name="offer_companion", description="Offer to become another player's Dao Companion — a mutual bond, exclusive to one partner at a time")
    @app_commands.guilds(GUILD)
    @app_commands.describe(member="The player to offer Dao Companionship to")
    async def offer_companion(self, interaction: discord.Interaction, member: discord.Member):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        if member.id == interaction.user.id:
            await interaction.response.send_message("You can't bond with yourself.", ephemeral=True)
            return
        ok, reason = await asyncio.to_thread(
            self.game.dao_companion_can_offer, interaction.user.id, interaction.user.display_name, member.id, member.display_name,
        )
        if not ok:
            await interaction.response.send_message(reason, ephemeral=True)
            return
        view = DaoCompanionRequestView( self.game, interaction.user, member, self.game.dao_companion_accept)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="break_companion", description="End your current Dao Companion bond")
    @app_commands.guilds(GUILD)
    async def break_companion(self, interaction: discord.Interaction):
        ok, message = await asyncio.to_thread(self.game.dao_companion_break, interaction.user.id, interaction.user.display_name)
        await interaction.response.send_message(message, ephemeral=not ok)

    @app_commands.command(name="companion", description="See your Dao Companion, how long you've been bonded, and the stat bonus you're getting from them")
    @app_commands.guilds(GUILD)
    async def companion(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        status = await asyncio.to_thread(self.game.get_dao_companion_status, interaction.user.id, interaction.user.display_name)
        if status is None:
            await interaction.response.send_message(
                "You don't have a Dao Companion right now — use `/offer_companion` to bond with someone.",
                ephemeral=True,
            )
            return
        embed = discord.Embed(title="💞 Your Dao Companion", color=discord.Color.gold())
        embed.add_field(name="Companion", value=status["partner_name"], inline=True)
        embed.add_field(name="Bonded For", value=format_duration(int(time.time()) - status["formed_ts"]), inline=True)
        embed.add_field(name="Times Used", value=str(status["times_used"]), inline=True)
        embed.add_field(name="Total Qi Granted", value=f"{status['total_qi_granted']:,.1f}", inline=True)
        bonus_lines = [
            f"{equipment.FOUNDATION_STAT_LABELS.get(stat, stat)}: +{value:,.1f}"
            for stat, value in status["stat_bonuses"].items() if value
        ]
        embed.add_field(
            name=f"Stat Bonus ({status['stat_share_pct'] * 100:.1f}% of their raw stats)",
            value="\n".join(bonus_lines) if bonus_lines else "Nothing yet.",
            inline=False,
        )
        embed.set_footer(text="Use `i dc` (or /dc) once a day for a qi burst — you both get one, sized off your own qi rate.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="dc", description="Once a day: trigger a qi burst for you AND your Dao Companion")
    @app_commands.guilds(GUILD)
    async def dc(self, interaction: discord.Interaction):
        player = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, interaction.user.display_name)
        if not player["character_confirmed"]:
            await interaction.response.send_message(NOT_CONFIRMED_MESSAGE, ephemeral=True)
            return
        result = await asyncio.to_thread(self.game.dao_companion_burst, interaction.user.id, interaction.user.display_name)
        if not result["ok"]:
            await interaction.response.send_message(result["reason"], ephemeral=True)
            return
        embed = discord.Embed(
            title="💞 Dao Companion Burst!",
            description=(
                f"You gain **{result['qi_to_caller']:,.1f}** Qi, and **{result['partner_name']}** "
                f"gains **{result['qi_to_partner']:,.1f}** Qi from your bond!"
            ),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(GameCog(bot))
