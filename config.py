import os

from dotenv import load_dotenv

load_dotenv()

GUILD_ID = 1529945910837117169
TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = os.getenv("DB_PATH", "game.db")

# World Boss spawn/defeat announcements (see GameCog.world_boss_tick in cog.py) -- optional;
# if unset, world bosses still spawn/respawn on schedule, they just don't get a proactive
# channel announcement. Set WORLD_BOSS_ANNOUNCE_CHANNEL_ID in the environment to a real
# channel ID to enable it.
_world_boss_channel_env = os.getenv("WORLD_BOSS_ANNOUNCE_CHANNEL_ID")
WORLD_BOSS_ANNOUNCE_CHANNEL_ID = int(_world_boss_channel_env) if _world_boss_channel_env else None

# PvP Tournament announcements (see GameCog.tournament_tick in cog.py) -- optional, same shape
# as WORLD_BOSS_ANNOUNCE_CHANNEL_ID above; kept as its own separate var rather than reusing the
# World Boss channel since it's a different audience/cadence.
_tournament_channel_env = os.getenv("TOURNAMENT_ANNOUNCE_CHANNEL_ID")
TOURNAMENT_ANNOUNCE_CHANNEL_ID = int(_tournament_channel_env) if _tournament_channel_env else None

# World Boss damage ranking (see GameCog._announce_world_boss_defeat) -- user's explicit
# channel, defaulted here rather than left env-only since it was given as a specific ID
# directly; still env-overridable like the other announce channels above without a code push.
# If this happens to match WORLD_BOSS_ANNOUNCE_CHANNEL_ID, the defeat announcement is only
# ever sent once there, not duplicated.
_world_boss_ranking_channel_env = os.getenv("WORLD_BOSS_DAMAGE_RANKING_CHANNEL_ID")
WORLD_BOSS_DAMAGE_RANKING_CHANNEL_ID = int(_world_boss_ranking_channel_env) if _world_boss_ranking_channel_env else 1534820947708870758
