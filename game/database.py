import json
import random
import sqlite3
import time
from typing import Dict, Optional

from config import DB_PATH
from . import dao_paths, sects


class GameDatabase:
    # Aptitude is a 0-100 roll — the higher it is, the faster Qi accrues (see
    # settle_qi). Weighted so a top-tier roll near 100 is genuinely rare;
    # (weight, min, max) bands, picked by weight then rolled uniformly within.
    APTITUDE_BANDS = [
        (60, 1, 30),
        (25, 31, 55),
        (10, 56, 75),
        (4, 76, 90),
        (1, 91, 100),
    ]

    # Base qi accrual, in qi per minute, before qi_multiplier is applied.
    BASE_QI_PER_MINUTE_PER_APTITUDE = 0.1

    # Flat currencies tradeable via /trade (see get_trade_offer/set_trade_currency/
    # execute_trade) — each is just a `players` column, offered the same way spirit_stones
    # always has been. Only ever populated from this fixed tuple, never from raw user text.
    TRADE_CURRENCIES = ("spirit_stones", "manual_ink", "insight_dust")

    # Free Root/Physique rerolls granted at first contact. Set explicitly at INSERT
    # time rather than relying on the column's SQLite default, since ALTER TABLE's
    # DEFAULT is frozen at whatever it was when the column was first added — bumping
    # this constant later wouldn't retroactively change it for already-migrated DBs.
    STARTER_REROLLS = 15

    # Primeval Essence starting cap for a brand-new character — set explicitly at INSERT
    # time (same reasoning as STARTER_REROLLS above), since apply_breakthrough scales this
    # multiplicatively on every later breakthrough, so a bigger base carries through every
    # realm rather than just the first one. New characters start full, same ratio as before.
    STARTER_MAX_PRIMEVAL_ESSENCE = 1000
    STARTER_PRIMEVAL_ESSENCE = 1000

    # One-time multiplier applied to every already-existing player's essence cap (and banked
    # essence, to preserve their existing fill %) when the base above was raised from the old
    # 100 default — see the essence_cap_migrated column/migration in setup().
    PRIMEVAL_ESSENCE_CAP_SCALE = STARTER_MAX_PRIMEVAL_ESSENCE // 100

    # Renamed for clarity — old name: new name. Applied once at setup() to any existing
    # inventory/equipped/trade_offers rows so previously-granted items keep working.
    ITEM_RENAMES = {
        "Healing Herb": "Minor Recovery Pill",
        "Essence Gathering Pill": "Lesser Foundation Pill",
        "Green Leaf Qi Pill": "Minor Cultivation Pill",
        "Aperture Opening Pellet": "Cracked Aptitude Pill",
        "Jade Spring Pill": "Mortal Breakthrough Pill",
    }

    # All player columns besides the user_id/name primary key, added via
    # migration so existing rows pick up new fields without a rebuild.
    PLAYER_COLUMNS = {
        "realm_index": "INTEGER DEFAULT 0",
        "primeval_essence": "INTEGER DEFAULT 1000",
        "aptitude": "INTEGER DEFAULT 50",
        "spirit_stones": "INTEGER DEFAULT 0",
        "cultivation_points": "INTEGER DEFAULT 0",
        "hp": "INTEGER DEFAULT 100",
        "aptitude_reroll_ts": "INTEGER DEFAULT 0",
        "last_restore_ts": "INTEGER DEFAULT 0",
        "qi": "REAL DEFAULT 0",
        "qi_multiplier": "REAL DEFAULT 1.0",
        # Qi Ascension Pill (see items.py / use_qi_ascension_pill) -- a LIFETIME counter per
        # TIER (not a single shared, per-realm-resetting pool like the old design) -- each of
        # the 7 tiers gets its own independent QI_ASCENSION_MAX_USES_PER_TIER (5) budget that
        # never resets. Tier N additionally requires great_realm_index + 1 >= N to even
        # attempt (Tier 5 needs Spirit Severing, matching realm rank == tier number), so a
        # player's total usable pool grows as they climb realms: 5 uses at Qi Condensation
        # (Tier 1 only) up to 35 by Ancient Realm (Tiers 1-7, 5 each).
        "qi_ascension_uses_t1": "INTEGER DEFAULT 0",
        "qi_ascension_uses_t2": "INTEGER DEFAULT 0",
        "qi_ascension_uses_t3": "INTEGER DEFAULT 0",
        "qi_ascension_uses_t4": "INTEGER DEFAULT 0",
        "qi_ascension_uses_t5": "INTEGER DEFAULT 0",
        "qi_ascension_uses_t6": "INTEGER DEFAULT 0",
        "qi_ascension_uses_t7": "INTEGER DEFAULT 0",
        "last_qi_ts": "INTEGER DEFAULT 0",
        "max_hp": "INTEGER DEFAULT 100",
        "max_primeval_essence": "INTEGER DEFAULT 1000",
        # Guards the one-time essence-cap migration in setup() — 0 for rows that predate the
        # cap increase and still need to be scaled up, 1 for everyone else (set explicitly at
        # INSERT time for new rows, since they're already created with the new higher cap).
        "essence_cap_migrated": "INTEGER DEFAULT 0",
        # Character creation (/join)
        "character_name": "TEXT DEFAULT NULL",
        "character_confirmed": "INTEGER DEFAULT 0",
        "race": "TEXT DEFAULT NULL",
        "root_tier": "TEXT DEFAULT NULL",
        "root_name": "TEXT DEFAULT NULL",
        "root_rerolls_remaining": "INTEGER DEFAULT 15",
        "physique_tier": "TEXT DEFAULT NULL",
        "physique_name": "TEXT DEFAULT NULL",
        "physique_rerolls_remaining": "INTEGER DEFAULT 15",
        "cultivation_path": "TEXT DEFAULT NULL",
        "path_rank": "INTEGER DEFAULT 1",
        "path_changes_remaining": "INTEGER DEFAULT 1",
        # Combat class (Tank/Support/Frostbinder) — see game/character_class.py. Chosen at
        # /join like race/path for new characters; NULL for characters confirmed before
        # this existed until they run /choose_class.
        "character_class": "TEXT DEFAULT NULL",
        "str_stat": "INTEGER DEFAULT 0",
        "spd_stat": "INTEGER DEFAULT 0",
        "def_stat": "INTEGER DEFAULT 0",
        "luck_stat": "INTEGER DEFAULT 0",
        "qi_stat": "INTEGER DEFAULT 0",
        "atk_stat": "INTEGER DEFAULT 0",
        # In-combat Qi resource (see settle_battle_qi) — separate from the qi_stat foundation
        # stat (its cap) and from the `qi` cultivation currency.
        "battle_qi": "REAL DEFAULT 0",
        "battle_qi_last_ts": "INTEGER DEFAULT 0",
        # Professions (see game/professions.py) — one rank column per profession, plus a
        # single shared "what am I studying right now" pair since only one can be studied
        # at a time.
        "miner_rank": "INTEGER DEFAULT 0",
        "gatherer_rank": "INTEGER DEFAULT 0",
        "alchemist_rank": "INTEGER DEFAULT 0",
        "blacksmith_rank": "INTEGER DEFAULT 0",
        "gu_refiner_rank": "INTEGER DEFAULT 0",
        "explorer_rank": "INTEGER DEFAULT 0",
        "farmer_rank": "INTEGER DEFAULT 0",
        "studying_profession": "TEXT DEFAULT NULL",
        "studying_started_ts": "INTEGER DEFAULT 0",
        # Farming (see GameManager.plant_farm/harvest_farm) — a single plot per player for
        # now; farm_plot_tier 0 means empty.
        "farm_plot_tier": "INTEGER DEFAULT 0",
        "farm_planted_ts": "INTEGER DEFAULT 0",
        # Per-action cooldowns for /mine, /gather, /explore (see GameManager's *_COOLDOWN_SECONDS).
        "last_mine_ts": "INTEGER DEFAULT 0",
        "last_gather_ts": "INTEGER DEFAULT 0",
        "last_explore_ts": "INTEGER DEFAULT 0",
        # /battlefield (see GameManager.start_battlefield) — a direct, cooldown-gated entry
        # point into BattlefieldView's wave combat, independent of the RNG-triggered version
        # found via /search or /region actions.
        "last_battlefield_ts": "INTEGER DEFAULT 0",
        # /raidboss attack (see world_boss.py / GameManager.attack_world_boss) — per-player
        # rate limit on hitting the current shared world boss, independent of everything else.
        "last_world_boss_attack_ts": "INTEGER DEFAULT 0",
        # /pvp (see GameManager.find_pvp_opponent) — also doubles as "recently searching for a
        # PvP match": anyone whose last_pvp_ts falls within the cooldown window is a candidate
        # real opponent for someone else's /pvp, instead of falling back to a random clone.
        "last_pvp_ts": "INTEGER DEFAULT 0",
        "last_rest_ts": "INTEGER DEFAULT 0",
        "last_meditate_ts": "INTEGER DEFAULT 0",
        # Mythic Physique's "ignore the first fatal hit each day" passive (see
        # try_use_daily_fatal_hit_negation) — the UTC calendar date (YYYY-MM-DD) it was last
        # used, so a fresh date means the negation is available again.
        "last_fatal_hit_negated_date": "TEXT DEFAULT NULL",
        # Nascent Soul Avatar's own once-daily fatal-blow shield (see
        # try_use_daily_avatar_fatal_block) — same daily-flag pattern as above, but a fully
        # independent charge: a player with both Mythic Physique AND a chosen avatar soul
        # gets two separate saves, not a shared one.
        "last_avatar_fatal_block_date": "TEXT DEFAULT NULL",
        # Void Star Root's "once daily, a search that would give nothing is upgraded to a
        # minor find" (see try_use_daily_search_upgrade) — same daily-flag pattern as above.
        "last_search_upgrade_date": "TEXT DEFAULT NULL",
        # Worldly Escape Gu's "once per day, ignore the penalty from one PvP defeat or failed
        # dangerous exploration" (see world_boss.py's Gu catalog / try_use_daily_gu_penalty_
        # negation) — same daily-flag pattern as above, its own dedicated column since a Gu
        # isn't mutually exclusive with a root's own daily charge.
        "last_gu_penalty_negated_date": "TEXT DEFAULT NULL",

        # Unique-root shared mechanic state (see character_data.py's Unique section for which
        # root uses which slot) — generic rather than one column per root, safe because a
        # player only ever HAS one root at a time, so there's no collision risk between e.g.
        # Giant Sun Inheritor Root's daily charge and Thieving Heaven Inheritor Root's.
        "unique_daily_charge_date": "TEXT DEFAULT NULL",   # one-per-UTC-day charges
        "unique_weekly_charge_key": "TEXT DEFAULT NULL",   # one-per-ISO-week charges (e.g. "2026-W30")
        "unique_resource_amount": "INTEGER DEFAULT 0",     # a weekly-capped earn-then-payout currency
        "unique_resource_week": "TEXT DEFAULT NULL",       # which ISO week unique_resource_amount belongs to
        "unique_permanent_counter": "INTEGER DEFAULT 0",   # a capped lifetime counter (e.g. Boundless Foundation grants)
        "unique_choice": "TEXT DEFAULT NULL",               # a persistent player-made choice (e.g. a totem/scheme name)

        # -- Manual/Inheritance/Secret Realm/Dream Realm system (see search.py, manuals.py,
        # discovery.py) — a separate, slower discovery loop alongside /explore, not a
        # replacement for it. Assembled manuals are their own per-player-generated objects
        # (see the `manuals` table below), so they're equipped via these two dedicated
        # columns rather than the existing single-item `equipped` "manual" slot — that slot
        # (see equipment.py's STARTER_EQUIPMENT) is untouched and keeps contributing its own
        # flat cultivation_speed_pct on top, same as always.
        "search_charges": "INTEGER DEFAULT 3",
        "search_charges_last_ts": "INTEGER DEFAULT 0",
        "discovery_momentum": "INTEGER DEFAULT 0",
        "search_focus": "TEXT DEFAULT 'Balanced'",
        "active_discovery_id": "INTEGER DEFAULT NULL",
        "equipped_primary_manual_id": "INTEGER DEFAULT NULL",
        "equipped_auxiliary_manual_id": "INTEGER DEFAULT NULL",
        "last_manual_change_ts": "INTEGER DEFAULT 0",
        "manual_ink": "INTEGER DEFAULT 0",
        "insight_dust": "INTEGER DEFAULT 0",
        "deviation_stress": "INTEGER DEFAULT 0",
        # Accessories/artifacts (see accessories_data.py) -- attunement_points_used is a
        # shared budget (mortal attunement costs 1, immortal costs 2, cap 2 — "two mortal
        # attunements or one immortal attunement" per the design doc's section 2).
        # pending_breakthrough_boost holds a JSON {"chance_pct"/"cost_reduction_pct": x}
        # from an activated breakthrough-boost accessory/artifact, consumed by the next
        # attempt_breakthrough call.
        "attunement_points_used": "INTEGER DEFAULT 0",
        "pending_breakthrough_boost": "TEXT DEFAULT NULL",
        # /search_forgotten_blessed_land's treasure-hunt board (see game/treasure_hunt.py) --
        # simple per-player cooldown timestamp, same shape as search_charges_last_ts above.
        "treasure_hunt_last_ts": "INTEGER DEFAULT 0",
        # /hunt's own "one at a time" gate (see GameManager.has_active_hunt/start_active_hunt/
        # clear_active_hunt) -- 0 means no active hunt. Mirrors active_discovery_id's shape,
        # but as a timestamp rather than a foreign key since a hunt has no DB row of its own
        # (it's a pure in-memory HuntView session, see HuntView.__init__'s own docstring) --
        # storing WHEN it started, not just a boolean, lets a stale flag (e.g. from a bot
        # restart mid-hunt, before HuntView.on_timeout ever got to fire and clear it) self-heal
        # after ACTIVE_HUNT_STALE_SECONDS instead of blocking that player forever.
        "active_hunt_started_ts": "INTEGER DEFAULT 0",
        # /raid's own "one at a time" gate -- same shape and reasoning as active_hunt_started_ts
        # above (see GameManager.has_active_raid/start_active_raid/clear_active_raid), just
        # per-PARTICIPANT rather than per-creator since a raid is a shared multi-player
        # encounter -- every joiner gets their own timestamp set at _on_join, and every
        # participant's flag gets cleared together at whichever terminal state the raid ends on
        # (victory/wiped/abandoned), not just the player who ran /raid.
        "active_raid_started_ts": "INTEGER DEFAULT 0",
        # /inheritance_ground's own "one at a time" gate -- same shape/reasoning as
        # active_raid_started_ts above (shared multi-player encounter, invited team rather than
        # an open join, cleared for every team member together at whichever terminal state the
        # run ends on: lobby cancelled, trial failed, or the betrayal stage resolves). Shipped
        # with GameManager.abandon_active_inheritance_ground + a UI escape hatch from day one
        # (see AbandonInheritanceGroundView) rather than added reactively -- see the raid flee
        # bug fixed in commit 0b6b712 for why that matters.
        "active_inheritance_ground_started_ts": "INTEGER DEFAULT 0",
        # Per-player cooldown, set on every team member once a run ends (complete OR abandoned)
        # -- same "last_x_ts + GameManager._check_cooldown" convention as
        # last_battlefield_ts/BATTLEFIELD_COOLDOWN_SECONDS.
        "last_inheritance_ground_ts": "INTEGER DEFAULT 0",

        # World region (see world_regions.py / /region) -- a character's chosen geographic
        # zone, separate from search_data.REGIONS' per-realm danger tiers. NULL until a player
        # runs /region for the first time. Nascent Soul and below switch instantly (stamping
        # last_world_region_change_ts); Spirit Severing and above instead go through the two
        # travel columns below -- world_region itself only updates once that journey completes,
        # same "destination column separate from the settled column" shape as white_heaven's
        # own status/travel_started_ts pair.
        "world_region": "TEXT DEFAULT NULL",
        "last_world_region_change_ts": "INTEGER DEFAULT 0",
        "world_region_travel_destination": "TEXT DEFAULT NULL",
        "world_region_travel_started_ts": "INTEGER DEFAULT 0",

        # White Heaven (see white_heaven.py / /white_heaven) -- a Dao Seeking+ endgame region
        # with a real 1h wall-clock travel delay each way, unlike world_region's instant switch.
        # status cycles 'away' -> 'traveling_there' -> 'present' -> 'traveling_back' -> 'away'.
        # travel_started_ts is 0 unless a trip is currently in progress. No separate
        # "notified" guard is needed the way split_body has one -- see complete_white_heaven_
        # travel's own docstring for why the status transition itself is a sufficient guard.
        "white_heaven_status": "TEXT DEFAULT 'away'",
        "white_heaven_travel_started_ts": "INTEGER DEFAULT 0",

        # Black Heaven (see black_heaven.py / /black_heaven) -- a second, deadlier Dao Seeking+
        # endgame region alongside White Heaven, with a real 2h wall-clock travel delay each way
        # (double White Heaven's own 1h). Same 'away' -> 'traveling_there' -> 'present' ->
        # 'traveling_back' -> 'away' cycle and the same "status transition alone is a sufficient
        # completion guard" reasoning as white_heaven_status above -- see complete_black_heaven_
        # travel's own docstring. Independent of white_heaven_status: a player can in principle
        # be present in both regions at once, mirroring how world_region/white_heaven_status
        # already coexist as separate, non-unified location flags.
        "black_heaven_status": "TEXT DEFAULT 'away'",
        "black_heaven_travel_started_ts": "INTEGER DEFAULT 0",
        # Search Black Heaven's own "one at a time" busy flag + leader-only cooldown -- same
        # active_inheritance_ground_started_ts/last_inheritance_ground_ts shape (2h stale-guard,
        # 4h leader-only cooldown), including its own AbandonBlackHeavenSearchView from day one.
        "active_black_heaven_started_ts": "INTEGER DEFAULT 0",
        "last_black_heaven_search_ts": "INTEGER DEFAULT 0",

        # Sect membership (see sects.py / /sect) -- a player belongs to at most one sect at a
        # time, so this lives directly on the player row rather than a separate membership
        # table, the same convention world_region/root_name/physique_name already use for
        # "exactly one of these at a time" state. NULL/NULL until they create or join one.
        "sect_id": "INTEGER DEFAULT NULL",
        "sect_rank": "TEXT DEFAULT NULL",
        "sect_joined_ts": "INTEGER DEFAULT 0",

        # Mentor/disciple (see sects.py's mentor section / GameManager's sect_* mentor
        # methods / /accept_disciple, /teach). A disciple points at their one master here;
        # a master's disciples are just every row with master_id == their user_id, so no
        # separate join table is needed (mirrors sect_id/sect_rank's own reasoning above).
        # last_teach_ts is the MASTER's cooldown — one teaching action per cooldown window,
        # not per disciple, so a master with several disciples can't just spam-teach all of
        # them back to back for free qi.
        "master_id": "INTEGER DEFAULT NULL",
        "last_teach_ts": "INTEGER DEFAULT 0",

        # When this disciple's CURRENT sect master relationship began, and how many times
        # that master has taught them since -- both reset to a fresh start (now/0) whenever
        # set_master() points this disciple at a new master (or clears one), so switching
        # masters doesn't carry over a stale count/date from a previous relationship. See
        # /master, /sect_master (game/cog.py) -- the disciple-side "who is my master" lookup
        # this powers.
        "master_since_ts": "INTEGER DEFAULT NULL",
        "times_taught_by_master": "INTEGER DEFAULT 0",

        # Personal disciples (see sects.py's mentor section / /master_offer, /master_teach_all)
        # -- a second, independent mentor track that needs no sect membership or Elder+ rank
        # at all, capped lower (sects.MAX_PERSONAL_DISCIPLES) and taught in one bulk action
        # instead of one at a time. Deliberately separate columns from master_id/last_teach_ts
        # above rather than reusing them, since a player can hold both a sect mentorship and a
        # personal one at the same time -- they're unrelated pools, not one generalized system.
        "personal_master_id": "INTEGER DEFAULT NULL",
        "last_personal_teach_ts": "INTEGER DEFAULT 0",  # superseded by personal_last_taught_ts below (kept, unused, to avoid a schema drop)

        # Per-disciple teach cooldown for the personal track: unlike last_personal_teach_ts
        # above (one shared timer on the MASTER, gating the whole /master_teach_all roster at
        # once), this lives on the DISCIPLE's own row -- when THEY were last taught, regardless
        # of who else the master taught in the same or a different run. Lets each disciple have
        # their own independent timer instead of the whole batch sharing one clock.
        "personal_last_taught_ts": "INTEGER DEFAULT 0",

        # Personal-track siblings of master_since_ts/times_taught_by_master above -- same
        # reset-on-new-master semantics, separate columns for the same reason the rest of the
        # personal track is separate (see this table's own personal_master_id comment).
        "personal_master_since_ts": "INTEGER DEFAULT NULL",
        "personal_times_taught": "INTEGER DEFAULT 0",

        # Dao Companion (see game/dao_companion.py / /offer_companion, /companion's Daily Burst
        # button) -- the once-per-day burst cooldown. Lives on the PLAYER, not the
        # dao_companions relationship row, since each partner can independently trigger their
        # own daily burst (both sides still receive qi either way -- see GameManager.
        # dao_companion_burst). Column name predates the /dc command's 2026-08-14 retirement.
        "last_dc_burst_ts": "INTEGER DEFAULT 0",

        # Nascent Soul Avatar (see game/avatar.py) -- NULL/1 until the player reaches Nascent
        # Soul realm AND runs /avatar for the first time. No rerolls_remaining counter (unlike
        # root_tier/physique_tier above): the first soul pick is free, every later change is a
        # paid DIRECT pick from the named soul list (see GameManager.choose_avatar_soul), not
        # an RNG reroll, so there's no "count" to track -- just spend spirit stones each time.
        "avatar_soul": "TEXT DEFAULT NULL",
        "avatar_level": "INTEGER DEFAULT 1",
        # Nascent Soul Avatar's /split_body mission (see game/split_body.py) -- single
        # pending-job pair, same idiom as studying_profession/studying_started_ts above (one
        # avatar per player, so no separate table needed). 0 = idle. split_body_notified
        # tracks whether the background DM tick has already told the player their mission
        # finished, so it fires exactly once per completed mission regardless of how many
        # ticks pass before they actually claim it.
        "split_body_started_ts": "INTEGER DEFAULT 0",
        "split_body_notified": "INTEGER DEFAULT 0",

        # Spirit Severing Dao Paths (see game/dao_paths.py / /dao_path) -- dao_marks_banked is
        # unallocated marks waiting to be spent; dao_path_marks is a JSON dict {path_name: marks
        # invested}, same "one JSON blob column" idiom as pending_breakthrough_boost/unique_choice
        # above rather than 14 separate columns, since a player can invest in any subset of the
        # 14 paths at once. Allocation only ever adds -- there's no DB-layer way to remove marks
        # from a path once spent (see GameDatabase.allocate_dao_marks).
        "dao_marks_banked": "INTEGER DEFAULT 0",
        "dao_path_marks": "TEXT DEFAULT NULL",
        # Guards GameManager.backfill_dao_marks_for_all_players (the retroactive one-time grant
        # for breakthroughs completed before Spirit Severing/Dao Seeking/Ancient Realm's own
        # dao_paths.breakthrough_marks lump sums existed for them) -- 0 until backfilled, then 1
        # forever, so /backfill_dao_marks is safe to run more than once by accident without
        # double-granting anyone.
        "dao_marks_backfill_applied": "INTEGER DEFAULT 0",
        # Transformation path's /transmute daily charges -- same UTC-date-string reset idiom as
        # last_fatal_hit_negated_date above, except this tracks a use COUNT against the day
        # rather than a single yes/no flag, since charges scale 1-5/day with marks invested.
        "transmute_uses_today": "INTEGER DEFAULT 0",
        "transmute_reset_date": "TEXT DEFAULT NULL",

        # Killer Move (see game/killer_move_gen.py / /killer_move) -- additive alongside the
        # existing gu_ability equipment slot, not a replacement of it. Two independent slots,
        # same "single ID column per slot" idiom as equipped_primary_manual_id/
        # equipped_auxiliary_manual_id above, rather than a weighted-both-at-once pattern --
        # a Killer Move is an ACTIVE ability you trigger, not a passive stat pool, so only one
        # of each kind is ever "the" one that fires.
        "equipped_combat_killer_move_id": "INTEGER DEFAULT NULL",
        "equipped_support_killer_move_id": "INTEGER DEFAULT NULL",
        "last_killer_move_swap_ts": "INTEGER DEFAULT 0",

        # Gu Pet (see game/gu_pet.py / /gu_pet) -- a player has at most one ACTIVE Gu Pet at a
        # time (they may own several, dormant ones sit in gu_pets unaffected -- see
        # GameDatabase.get_player_gu_pets), so a single pointer column here is enough, same
        # "exactly one of these at a time" idiom world_region/sect_id/master_id above already
        # use. last_gu_pet_mode_switch_ts gates the Combat/Cultivation toggle's own 10-minute
        # cooldown -- deliberately its own column rather than routed through GameManager.
        # _check_cooldown, since that helper's cooldown_reduction_pct fold-in is for player-
        # action cooldowns (mine/gather/explore/...), not something either Gu Pet spec asked
        # to apply here.
        "active_gu_pet_id": "INTEGER DEFAULT NULL",
        "last_gu_pet_mode_switch_ts": "INTEGER DEFAULT 0",
    }

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def connect(self):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        # busy_timeout alone makes a genuinely contended write retry for up to 5s instead of
        # raising "database is locked" immediately -- the actual problem this migration set
        # out to fix. journal_mode=WAL was tried alongside it but reverted the same day: WAL
        # needs proper mmap-based shared-memory locking from the filesystem for its -shm
        # sidecar file, which Railway's persistent Volume doesn't reliably provide, and every
        # single command touches the DB via this connect() -- so a WAL failure here broke
        # every command/button in the bot at once, not just the ones this migration touched.
        # busy_timeout has no such filesystem requirement, so it's kept on its own.
        con.execute("PRAGMA busy_timeout=5000")
        return con

    def setup(self):
        con = self.connect()
        cur = con.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            name TEXT
        )
        """)

        existing_columns = {row[1] for row in cur.execute("PRAGMA table_info(players)").fetchall()}
        for column, definition in self.PLAYER_COLUMNS.items():
            if column not in existing_columns:
                cur.execute(f"ALTER TABLE players ADD COLUMN {column} {definition}")

        # One-time backfill for master_since_ts/personal_master_since_ts: both columns are
        # brand new, so any disciple relationship that already existed before this migration
        # would otherwise show a NULL "since" forever. There's no way to recover the real
        # start date, so this backfills "now" -- tracking starts today for pre-existing
        # relationships, rather than displaying nothing. Guarded by the IS NULL check, so it
        # only ever touches a given row once (a relationship formed AFTER this migration
        # already gets a real since_ts from set_master/set_personal_master directly).
        now = int(time.time())
        cur.execute("UPDATE players SET master_since_ts = ? WHERE master_id IS NOT NULL AND master_since_ts IS NULL", (now,))
        cur.execute(
            "UPDATE players SET personal_master_since_ts = ? WHERE personal_master_id IS NOT NULL AND personal_master_since_ts IS NULL",
            (now,),
        )

        cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item_name TEXT,
            quantity INTEGER DEFAULT 1
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS buffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            qi_multiplier_bonus REAL DEFAULT 0,
            expires_at INTEGER
        )
        """)
        # Flat combat-stat bonus columns (e.g. Epic Physique's post-breakthrough vigor buff) —
        # added alongside the original qi_multiplier_bonus rather than replacing it, so every
        # existing qi-multiplier buff (pills, etc.) keeps working unchanged.
        buffs_columns = {row[1] for row in cur.execute("PRAGMA table_info(buffs)").fetchall()}
        for column in ("str_bonus", "atk_bonus", "def_bonus", "spd_bonus"):
            if column not in buffs_columns:
                cur.execute(f"ALTER TABLE buffs ADD COLUMN {column} REAL DEFAULT 0")
        # Killer Move (see game/killer_move_gen.py) needs a buff-kind combat move to be able to
        # grant lifesteal, and a loot-kind support move to grant a temporary loot_chance_bonus_pct
        # -- neither fits the fixed str/atk/def/spd columns above. One generic JSON blob (same
        # idiom as pending_breakthrough_boost) instead of adding a bespoke column per new bonus
        # key, so any future SPECIAL_BONUS_KEYS-shaped buff can reuse this without more schema.
        if "special_bonuses" not in buffs_columns:
            cur.execute("ALTER TABLE buffs ADD COLUMN special_bonuses TEXT DEFAULT NULL")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            initiator_id INTEGER,
            target_id INTEGER,
            status TEXT DEFAULT 'pending',
            initiator_confirmed INTEGER DEFAULT 0,
            target_confirmed INTEGER DEFAULT 0,
            created_at INTEGER
        )
        """)
        # 'trade' (default, swap offers) or 'gamble' (winner-take-all dice roll — see
        # GameManager.start_gamble/confirm_gamble, GameDatabase.execute_gamble). Read by
        # trading.py's TradeWindowView/TradeRequestView to render the right UI/wording for
        # the same underlying request/offer/confirm machinery either way.
        trades_columns = {row[1] for row in cur.execute("PRAGMA table_info(trades)").fetchall()}
        if "mode" not in trades_columns:
            cur.execute("ALTER TABLE trades ADD COLUMN mode TEXT DEFAULT 'trade'")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS trade_offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER,
            user_id INTEGER,
            kind TEXT,
            item_name TEXT,
            quantity INTEGER DEFAULT 0
        )
        """)
        # Nullable pointer into crafted_gear, set only on kind='crafted_gear' rows (a unique
        # rolled instance offered for trade — see the crafted_gear table below). item_name is
        # still populated as a display-only cache, same convention as equipped.gear_id.
        trade_offers_columns = {row[1] for row in cur.execute("PRAGMA table_info(trade_offers)").fetchall()}
        if "gear_id" not in trade_offers_columns:
            cur.execute("ALTER TABLE trade_offers ADD COLUMN gear_id INTEGER")
        # Same idea as gear_id above, one nullable pointer column per instance-based kind —
        # manuals/accessories are tradeable now too (see GameManager.add_trade_manual/
        # add_trade_accessory), the same "static catalog + owned instance with its own id"
        # shape crafted_gear already used.
        if "manual_id" not in trade_offers_columns:
            cur.execute("ALTER TABLE trade_offers ADD COLUMN manual_id INTEGER")
        if "accessory_instance_id" not in trade_offers_columns:
            cur.execute("ALTER TABLE trade_offers ADD COLUMN accessory_instance_id INTEGER")

        # Dao Companion (see game/dao_companion.py / /offer_companion) -- one row per bonded
        # pair, looked up via "WHERE partner_a_id = ? OR partner_b_id = ?" (get_dao_companion).
        # Exclusivity (one companion at a time) is enforced in GameManager at offer/accept
        # time, not a DB constraint -- same validate-before-insert style as sect mentorship.
        cur.execute("""
        CREATE TABLE IF NOT EXISTS dao_companions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partner_a_id INTEGER NOT NULL,
            partner_b_id INTEGER NOT NULL,
            formed_ts INTEGER NOT NULL,
            times_used INTEGER NOT NULL DEFAULT 0,
            total_qi_granted REAL NOT NULL DEFAULT 0,
            last_essence_exchange_ts INTEGER NOT NULL DEFAULT 0
        )
        """)
        dao_companions_columns = {row[1] for row in cur.execute("PRAGMA table_info(dao_companions)").fetchall()}
        if "last_essence_exchange_ts" not in dao_companions_columns:
            cur.execute("ALTER TABLE dao_companions ADD COLUMN last_essence_exchange_ts INTEGER NOT NULL DEFAULT 0")

        # Essence Exchange (see /essence_exchange) -- a mutual, CONFIRMED action between Dao
        # Companions (unlike "i dc"'s instant/unilateral burst), so a pending request needs a
        # real DB row + periodic sweep to survive a redeploy mid-window -- a 3-hour confirm
        # window is far more likely to overlap a restart than the 5-minute companion-offer
        # window, which is why THAT one gets away with a pure in-memory View timeout and this
        # one deliberately doesn't (see the trade-timeout incident this same lesson came from).
        # Only one 'pending' row per companion_id at a time (enforced in GameManager before
        # insert, same validate-before-insert style as dao_companions itself).
        cur.execute("""
        CREATE TABLE IF NOT EXISTS essence_exchange_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            companion_id INTEGER NOT NULL,
            proposer_id INTEGER NOT NULL,
            partner_id INTEGER NOT NULL,
            created_ts INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS equipped (
            user_id INTEGER,
            slot_key TEXT,
            item_name TEXT,
            PRIMARY KEY (user_id, slot_key)
        )
        """)
        # Nullable pointer into crafted_gear (see below) — set only when this slot holds a
        # unique rolled instance instead of a catalog EQUIPMENT item. item_name is still kept
        # in sync as a display-only cache (see set_equipped_instance) so every existing call
        # site that just prints equipped[...] keeps working unmodified; gear_id is the
        # authoritative signal for anything that needs the real rolled stats.
        equipped_columns = {row[1] for row in cur.execute("PRAGMA table_info(equipped)").fetchall()}
        if "gear_id" not in equipped_columns:
            cur.execute("ALTER TABLE equipped ADD COLUMN gear_id INTEGER")

        # The Nascent Soul Avatar's OWN independent gear slots (see game/avatar_gear.py) --
        # a second, separate equip table from `equipped` above. item_name is kept as a
        # display-only cache (same convention as `equipped`'s own item_name -- see
        # set_equipped_instance) even for instance-backed rows, so any old code that just
        # prints get_avatar_equipped()[...] keeps working unmodified.
        cur.execute("""
        CREATE TABLE IF NOT EXISTS avatar_equipped (
            user_id INTEGER,
            slot_key TEXT,
            item_name TEXT,
            PRIMARY KEY (user_id, slot_key)
        )
        """)
        # Nullable pointer into avatar_gear_instances (see below) -- set only when this slot
        # holds a rolled instance instead of a legacy avatar_gear.AVATAR_GEAR catalog item.
        # Exact same additive-migration idiom already used for `equipped`.gear_id/
        # accessory_instance_id above -- guarded ALTER TABLE, not the PLAYER_COLUMNS dict
        # (that's players-table-specific).
        avatar_equipped_columns = {row[1] for row in cur.execute("PRAGMA table_info(avatar_equipped)").fetchall()}
        if "instance_id" not in avatar_equipped_columns:
            cur.execute("ALTER TABLE avatar_equipped ADD COLUMN instance_id INTEGER")

        # Unique rolled Nascent Soul Avatar gear instances (see game/avatar_gear.py) --
        # same "ownership IS the row, no separate inventory quantity" shape as crafted_gear/
        # accessory_artifact_instances above. Replaces Phase 1's flat item_name+quantity
        # avatar gear entirely for anything granted from here on; a legacy-equipped flat
        # item (instance_id NULL on avatar_equipped) is untouched and keeps working.
        cur.execute("""
        CREATE TABLE IF NOT EXISTS avatar_gear_instances (
            instance_id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            slot_type TEXT,
            tier INTEGER,
            stat_bonuses TEXT,
            power_score REAL,
            created_ts INTEGER
        )
        """)

        # Gu Pet (see game/gu_pet.py / /gu_pet) -- ownership IS the row, same shape as
        # avatar_gear_instances/crafted_gear above (a rolled, per-instance entity, not a
        # flat item_name+quantity stack). A player may own several (players.active_gu_pet_id
        # picks which one is currently active) -- growth-phase state (fed_totals,
        # growth_days_fed/required, feed_streak_days, last_fed_ts) is only ever read/written
        # while stage='growth'; satiety/last_satiety_update_ts only matter once stage='mature'
        # (see GameManager._settle_gu_pet_satiety). species/path/mode are NULL until
        # crystallization locks them in -- see GameManager.crystallize_gu_pet.
        cur.execute("""
        CREATE TABLE IF NOT EXISTS gu_pets (
            pet_id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            rank INTEGER,
            stage TEXT DEFAULT 'growth',
            species TEXT DEFAULT NULL,
            path TEXT DEFAULT NULL,
            mode TEXT DEFAULT 'cultivation',
            name TEXT DEFAULT NULL,
            stat_bonuses TEXT DEFAULT '{}',
            fed_totals TEXT DEFAULT '{}',
            growth_days_required INTEGER,
            growth_days_fed INTEGER DEFAULT 0,
            feed_streak_days INTEGER DEFAULT 0,
            last_fed_ts INTEGER DEFAULT 0,
            satiety REAL DEFAULT 100.0,
            last_satiety_update_ts INTEGER DEFAULT 0,
            image_path TEXT DEFAULT NULL,
            created_ts INTEGER
        )
        """)
        # name is generated at crystallization time (see gu_pet.generate_pet_name), same as
        # species/path -- NULL until then, same as those two. Guarded ALTER TABLE (not the
        # PLAYER_COLUMNS dict, which only covers the players table) since this table already
        # existed on the live DB before this column did.
        gu_pets_columns = {row[1] for row in cur.execute("PRAGMA table_info(gu_pets)").fetchall()}
        if "name" not in gu_pets_columns:
            cur.execute("ALTER TABLE gu_pets ADD COLUMN name TEXT DEFAULT NULL")
        # One-time backfill: any pet that crystallized BEFORE the name column existed gets a
        # real generated name now (the same gu_pet.generate_pet_name/pet_flavor_seed a
        # freshly-crystallized pet already gets) instead of staying nameless forever. Local
        # import, same idiom _qi_rate_components already uses to pull in gu_pet -- avoids a
        # module-level dependency edge for the one function here that needs it.
        unnamed_mature = cur.execute("SELECT pet_id, rank FROM gu_pets WHERE stage = 'mature' AND name IS NULL").fetchall()
        if unnamed_mature:
            from . import gu_pet as _gu_pet
            for row in unnamed_mature:
                pet_stub = {"pet_id": row["pet_id"], "rank": row["rank"]}
                name = _gu_pet.generate_pet_name(random.Random(_gu_pet.pet_flavor_seed(pet_stub)))
                cur.execute("UPDATE gu_pets SET name = ? WHERE pet_id = ?", (name, row["pet_id"]))
        # Shared-art cache for Common/Uncommon/Rare Gu Pets (see game/gu_pet_images.py's
        # get_pet_cache_key) -- Epic+ pets never touch this table, their portrait is unique
        # and lives on the gu_pets row's own image_path instead (see GameManager.
        # should_generate_unique_image).
        cur.execute("""
        CREATE TABLE IF NOT EXISTS gu_pet_image_cache (
            cache_key TEXT PRIMARY KEY,
            image_path TEXT,
            created_ts INTEGER
        )
        """)

        # Unique rolled Weapon/Head/Body instances forged by /blacksmith (and, since it's the
        # same underlying loot, "weapon"/"armor" discovery rewards — see discovery_gen.py) —
        # unlike the rest of this game's equipment (a flat item_name+quantity in `inventory`,
        # looked up against the static equipment.EQUIPMENT catalog), each of these is its own
        # row with its own randomly-rolled stat_bonuses, so two Tier 3 Swords can have
        # completely different stats. Ownership IS the row (no separate inventory quantity
        # to track); ordinary catalog gear (starter items, the Heaven-Severing Blade drop)
        # is unaffected and still works exactly as before.
        cur.execute("""
        CREATE TABLE IF NOT EXISTS crafted_gear (
            gear_id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            base_type TEXT,
            slot_type TEXT,
            tier INTEGER,
            stat_bonuses TEXT,
            power_score REAL,
            created_ts INTEGER
        )
        """)

        # Accessory/artifact instances (see accessories_data.py — the insanity accessories
        # and artifacts design doc). item_id points into the static accessories_data.ITEMS
        # catalog (same "static catalog + owned-instance row" split as crafted_gear/manuals),
        # with per-instance attunement/binding/refinement/charge/cooldown state — a Ring of
        # the Ten-Thousand-Trial Survivor you own is a specific instance with its own
        # Failure Insight progress, not just a stack count of "how many you have."
        cur.execute("""
        CREATE TABLE IF NOT EXISTS accessory_artifact_instances (
            instance_id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            item_id TEXT,
            attuned INTEGER DEFAULT 0,
            bound_until INTEGER DEFAULT 0,
            refinement_level INTEGER DEFAULT 0,
            charges_used INTEGER DEFAULT 0,
            charges_reset_ts INTEGER DEFAULT 0,
            last_activation_ts INTEGER DEFAULT 0,
            state_json TEXT DEFAULT '{}',
            created_ts INTEGER
        )
        """)
        # Nullable pointer into accessory_artifact_instances, parallel to (and separate
        # from) equipped.gear_id -- kept as its own column rather than reusing gear_id so
        # "which instance table does this slot's equipped row point into" is never
        # ambiguous: gear_id is always crafted_gear, accessory_instance_id is always this.
        equipped_columns = {row[1] for row in cur.execute("PRAGMA table_info(equipped)").fetchall()}
        if "accessory_instance_id" not in equipped_columns:
            cur.execute("ALTER TABLE equipped ADD COLUMN accessory_instance_id INTEGER")

        # Named snapshots of a player's full loadout (see GameManager.save_equipment_preset/
        # apply_equipment_preset) — /preset_save afk, /preset_load raid, etc. slots_json is
        # {slot_key: {"item_name", "gear_id", "accessory_instance_id"}} for every OCCUPIED
        # real equipment.SLOTS slot at save time (an absent slot_key means it was empty, and
        # applying the preset later empties it again rather than leaving it alone) — the
        # legacy "manual" slot_key is never included, see equipment.py's own note on it being
        # dead. primary/auxiliary_manual_id snapshot the two dedicated players columns
        # instead, since manuals aren't tracked in the `equipped` table at all.
        cur.execute("""
        CREATE TABLE IF NOT EXISTS equipment_presets (
            user_id INTEGER,
            preset_key TEXT,
            display_name TEXT,
            slots_json TEXT,
            primary_manual_id INTEGER,
            auxiliary_manual_id INTEGER,
            created_ts INTEGER,
            updated_ts INTEGER,
            PRIMARY KEY (user_id, preset_key)
        )
        """)

        # Multiple simultaneous farm plots (see GameManager.farm_slot_count — 1 base slot,
        # +2 per Great Realm) — replaces the old single-plot players.farm_plot_tier/
        # farm_planted_ts columns. Only occupied plots get a row; an unlocked-but-empty slot
        # simply has none.
        cur.execute("""
        CREATE TABLE IF NOT EXISTS farm_plots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            slot_index INTEGER,
            tier INTEGER DEFAULT 0,
            planted_ts INTEGER DEFAULT 0
        )
        """)

        # -- Manual/Inheritance/Secret Realm/Dream Realm system --------------------------
        # Manual pages themselves are a static catalog (see manual_data.PAGES, same pattern
        # as items.ITEMS/equipment.EQUIPMENT) — only what a player OWNS lives in the DB.
        # Composite fields (page lists, effect dicts, flaw lists) are stored as JSON text
        # rather than fully normalized into their own tables (manual_components,
        # manual_flaws, loot_instances in the original design doc) — this codebase already
        # keeps its schema flat/simple (see inventory/buffs/trades above), and a manual's
        # page list/effects/flaws are never queried piecemeal, only read and written whole.
        cur.execute("""
        CREATE TABLE IF NOT EXISTS player_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            page_id TEXT,
            quantity INTEGER DEFAULT 1,
            refinement_level TEXT DEFAULT 'Unstudied',
            studied INTEGER DEFAULT 0,
            discovered_hidden_line INTEGER DEFAULT 0
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS manuals (
            manual_id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            name TEXT,
            rank INTEGER,
            rarity TEXT,
            primary_path TEXT,
            secondary_paths TEXT,
            page_ids TEXT,
            coherence INTEGER,
            coherence_band TEXT,
            stability INTEGER,
            comprehension INTEGER DEFAULT 0,
            effects TEXT,
            flaws TEXT,
            generation_seed INTEGER,
            bound INTEGER DEFAULT 0,
            created_ts INTEGER
        )
        """)

        # How much assembling this manual benefited from the refinement level of the specific
        # page copies spent on it (see manual_data.REFINEMENT_SPEC / manual_gen.
        # refinement_bonus_totals) -- baked in once at assemble time since the source pages are
        # consumed immediately and their refinement level can't be looked up again later, then
        # replayed on every comprehension reroll (manual_gen.reroll_effects_for_comprehension)
        # so a comprehension bump never quietly erases the refinement bonus. Default 1.0 (no
        # change) covers every pre-existing manual and every loot-generated one (generate_manual
        # has no player-owned pages to refine in the first place).
        manuals_columns = {row[1] for row in cur.execute("PRAGMA table_info(manuals)").fetchall()}
        if "refinement_effect_mult" not in manuals_columns:
            cur.execute("ALTER TABLE manuals ADD COLUMN refinement_effect_mult REAL DEFAULT 1.0")

        # Self-healing guard: at least one live deployment already had a `killer_moves` table
        # under a completely different, older shape (id/user_id/move_name/power) predating
        # this feature -- CREATE TABLE IF NOT EXISTS silently no-ops against it, so every real
        # assemble_killer_move insert crashed with "table killer_moves has no column named
        # owner_id". Only auto-repair an EMPTY mismatched table (never discard real rows under
        # the old shape -- if that ever happens, leave it alone and let the mismatch surface
        # loudly instead of silently destroying data).
        existing_killer_move_columns = {row["name"] for row in cur.execute("PRAGMA table_info(killer_moves)").fetchall()}
        if existing_killer_move_columns and "owner_id" not in existing_killer_move_columns:
            if cur.execute("SELECT COUNT(*) FROM killer_moves").fetchone()[0] == 0:
                cur.execute("DROP TABLE killer_moves")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS killer_moves (
            killer_move_id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            slot TEXT,
            kind TEXT,
            name TEXT,
            move_tier TEXT,
            primary_type TEXT,
            harmony INTEGER,
            qi_cost_pct REAL,
            effects TEXT,
            created_ts INTEGER
        )
        """)

        # A player has at most one row here at a time (see search.py) — the currently open
        # (not yet entered, or entered but not resolved) inheritance/secret realm/dream
        # realm from their last search. Resolved/expired discoveries are deleted, not kept
        # as history — same "in-memory session, commit final results only" pattern /hunt,
        # /raid, /mine etc. already use, just with the discovery itself persisted across
        # the gap between finding it and choosing to enter it.
        cur.execute("""
        CREATE TABLE IF NOT EXISTS discoveries (
            discovery_id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            type TEXT,
            theme TEXT,
            rank INTEGER,
            difficulty TEXT,
            seed INTEGER,
            status TEXT DEFAULT 'open',
            created_ts INTEGER,
            expires_at INTEGER
        )
        """)
        # How many "steps" kind rewards (see GameManager.resolve_discovery_step) have already
        # been granted for this discovery -- the authoritative resume point. DiscoveryView's
        # own step_index is just an in-memory loop counter for a single view instance; without
        # this, re-entering the SAME still-open discovery (e.g. via SearchView's Back to
        # Search -> Enter Discovery round trip) would spin up a brand new view starting back
        # at step 0 and hand out its already-granted rewards a second time.
        discoveries_columns = {row[1] for row in cur.execute("PRAGMA table_info(discoveries)").fetchall()}
        if "steps_completed" not in discoveries_columns:
            cur.execute("ALTER TABLE discoveries ADD COLUMN steps_completed INTEGER DEFAULT 0")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS clue_tracks (
            track_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            discovery_type TEXT,
            theme TEXT,
            fragments INTEGER DEFAULT 0,
            fragments_required INTEGER DEFAULT 3,
            guaranteed_rank INTEGER DEFAULT 1
        )
        """)

        # Every /grant_item and /grant_stones call (see cog.py) — who ran it, on whom, and
        # what was granted, so an out-of-place item (a Unique/event-only canon Gu, an
        # obviously-miscounted quantity, ...) showing up in someone's inventory can be traced
        # back to a specific admin/action instead of pure guesswork. Append-only; nothing
        # ever updates or deletes a row here.
        cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER,
            actor_name TEXT,
            target_id INTEGER,
            target_name TEXT,
            action TEXT,
            detail TEXT,
            created_ts INTEGER
        )
        """)

        # Sects (see sects.py / /sect) -- Phase 1 of the design doc's sect system: core
        # structure (create/join/leave, the 5-rank hierarchy, a basic spirit-stone treasury)
        # only. Mentor/disciple teaching, contribution points, region wars, sect buildings,
        # missions, and leaderboards are all explicitly deferred to later phases -- nothing
        # below fakes any of those. Membership itself lives on the player row (sect_id/
        # sect_rank above), not a separate join table, since a player is in at most one sect.
        cur.execute("""
        CREATE TABLE IF NOT EXISTS sects (
            sect_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            motto TEXT DEFAULT '',
            banner TEXT DEFAULT '🏯',
            leader_id INTEGER,
            treasury_spirit_stones INTEGER DEFAULT 0,
            created_ts INTEGER
        )
        """)

        # Pending join requests (see sects.can_approve_applications / GameManager.sect_join) --
        # /sect_join no longer seats someone directly, it queues a row here for a Vice Leader+
        # to accept or reject via /sect's Applications screen. A real table (not an in-memory
        # accept/decline view like MentorRequestView's) since a reviewer needs to see a QUEUE
        # of applicants whenever they next check /sect, not just react to one offer in the
        # moment -- same 'status' + created_ts shape as the trades table, the closest existing
        # precedent for a persisted pending-approval row in this codebase. Resolved rows are
        # kept (not deleted) as a light history trail rather than instantly vanishing.
        cur.execute("""
        CREATE TABLE IF NOT EXISTS sect_applications (
            application_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sect_id INTEGER,
            applicant_id INTEGER,
            applicant_name TEXT,
            status TEXT DEFAULT 'pending',
            created_ts INTEGER,
            resolved_ts INTEGER DEFAULT 0,
            resolved_by_name TEXT DEFAULT ''
        )
        """)

        # World Boss (see world_boss.py / /raidboss) -- a recurring, server-wide encounter
        # with one shared HP pool multiple players deplete over its lifetime (unlike /raid,
        # whose "boss" is a fresh per-session in-memory fight). Only ever one row with
        # status='alive' at a time; old rows are kept (not deleted) as history once
        # defeated/expired, since "when did the last one end" drives the 3h respawn timer
        # (see GameManager.maybe_spawn_world_boss) and a history table costs nothing extra
        # here, unlike discoveries' deliberately-ephemeral one-row-per-player design.
        cur.execute("""
        CREATE TABLE IF NOT EXISTS world_boss (
            boss_instance_id INTEGER PRIMARY KEY AUTOINCREMENT,
            boss_key TEXT,
            max_hp INTEGER,
            current_hp INTEGER,
            spawned_ts INTEGER,
            expires_ts INTEGER,
            status TEXT DEFAULT 'alive',
            ended_ts INTEGER DEFAULT NULL
        )
        """)

        # Per-player contribution to a given world_boss instance -- doc's own "boss_damage /
        # total_boss_damage" weight formula reads straight off damage_dealt here. One row per
        # (boss_instance_id, user_id), incremented in place on every attack rather than one
        # row per attack, since only the running total/count/best-hit matter for rewards, not
        # a full attack-by-attack log.
        cur.execute("""
        CREATE TABLE IF NOT EXISTS world_boss_damage (
            boss_instance_id INTEGER,
            user_id INTEGER,
            name TEXT,
            damage_dealt INTEGER DEFAULT 0,
            attacks INTEGER DEFAULT 0,
            highest_hit INTEGER DEFAULT 0,
            rewarded INTEGER DEFAULT 0,
            PRIMARY KEY (boss_instance_id, user_id)
        )
        """)

        # PvP Tournament (see game/tournament.py / /tournament) -- a timed signup window
        # followed by a battle-royale simulation among frozen character "copies" (see
        # tournament_participants.snapshot). Mirrors world_boss's own shape exactly: only ever
        # one row with status IN ('signup','running') at a time (enforced in Python, same
        # convention every table here already follows), old rows kept as history.
        cur.execute("""
        CREATE TABLE IF NOT EXISTS tournament (
            tournament_id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT DEFAULT 'signup',
            signup_started_ts INTEGER,
            signup_ends_ts INTEGER,
            started_ts INTEGER DEFAULT NULL,
            ended_ts INTEGER DEFAULT NULL,
            result_log TEXT DEFAULT NULL,
            announced_ts INTEGER DEFAULT NULL
        )
        """)
        tournament_columns = {row[1] for row in cur.execute("PRAGMA table_info(tournament)").fetchall()}
        if "announced_ts" not in tournament_columns:
            cur.execute("ALTER TABLE tournament ADD COLUMN announced_ts INTEGER DEFAULT NULL")
            # Backfill so this migration doesn't retroactively re-announce every tournament
            # that already finished before announced_ts existed -- see
            # GameManager.get_pending_tournament_announcements's own docstring for why this
            # column exists at all (a player's /tournament, /cd, or join action can resolve a
            # tournament via resolve_tournament_if_ready() before the tick loop gets to it,
            # which used to mean it finished with zero channel post and zero DMs).
            cur.execute("UPDATE tournament SET announced_ts = COALESCE(ended_ts, 0) WHERE status IN ('completed', 'cancelled') AND announced_ts IS NULL")

        # One row per (tournament, signed-up player) -- unlike world_boss_damage's running
        # contribution total, snapshot is written ONCE at signup and never updated again (the
        # entire point is a frozen copy of the player's stats at that moment, immune to any
        # later re-gearing -- see GameManager._tournament_combat_snapshot).
        cur.execute("""
        CREATE TABLE IF NOT EXISTS tournament_participants (
            tournament_id INTEGER,
            user_id INTEGER,
            name TEXT,
            snapshot TEXT,
            joined_ts INTEGER,
            placement INTEGER DEFAULT NULL,
            rewarded INTEGER DEFAULT 0,
            PRIMARY KEY (tournament_id, user_id)
        )
        """)

        # One-time copy of whatever was already growing in the old single-plot columns into
        # slot 0 of the new table, so nobody's in-progress crop is lost by this migration.
        # Guarded by a slot-0-already-exists check so it's a no-op on every later setup().
        cur.execute("SELECT user_id, farm_plot_tier, farm_planted_ts FROM players WHERE farm_plot_tier > 0")
        for row in cur.fetchall():
            cur.execute("SELECT id FROM farm_plots WHERE user_id = ? AND slot_index = 0", (row["user_id"],))
            if cur.fetchone() is None:
                cur.execute(
                    "INSERT INTO farm_plots (user_id, slot_index, tier, planted_ts) VALUES (?, 0, ?, ?)",
                    (row["user_id"], row["farm_plot_tier"], row["farm_planted_ts"]),
                )

        # One-time renames for items whose display name changed after players may have
        # already picked some up — keeps existing inventory/equipped/trade rows pointing
        # at a name that still resolves in the current ITEMS/EQUIPMENT catalogs.
        # Inventory needs a merge (not a blind rename) since a player can already own a
        # row under the new name (e.g. from a fresh starter grant) — a plain UPDATE would
        # leave two same-named rows behind, and get_inventory/add_item/remove_item only
        # ever look at one of them, silently losing the other's quantity.
        for old_name, new_name in self.ITEM_RENAMES.items():
            cur.execute("SELECT user_id, quantity FROM inventory WHERE item_name = ?", (old_name,))
            for row in cur.fetchall():
                cur.execute(
                    "SELECT id, quantity FROM inventory WHERE user_id = ? AND item_name = ?",
                    (row["user_id"], new_name),
                )
                existing = cur.fetchone()
                if existing:
                    cur.execute(
                        "UPDATE inventory SET quantity = quantity + ? WHERE id = ?",
                        (row["quantity"], existing["id"]),
                    )
                    cur.execute(
                        "DELETE FROM inventory WHERE user_id = ? AND item_name = ?",
                        (row["user_id"], old_name),
                    )
                else:
                    cur.execute(
                        "UPDATE inventory SET item_name = ? WHERE user_id = ? AND item_name = ?",
                        (new_name, row["user_id"], old_name),
                    )
            cur.execute("UPDATE equipped SET item_name = ? WHERE item_name = ?", (new_name, old_name))
            cur.execute("UPDATE trade_offers SET item_name = ? WHERE item_name = ?", (new_name, old_name))

        # One-time slot rename: the old 2 generic "Accessory" slots (accessory_1/
        # accessory_2) were split into 6 typed slots (ring_1/ring_2/earring_1/earring_2/
        # necklace/bracelet — see equipment.py's SLOTS) once the accessories/artifacts
        # system landed. Every accessory ever grantable so far (starter "Rusty Jade Ring")
        # is a ring, so accessory_1 -> ring_1 and accessory_2 -> ring_2 is a lossless
        # like-for-like rename, not a real re-sort. Guarded against a PRIMARY KEY collision
        # (user_id, slot_key) in case a later run already migrated a given user.
        for old_slot, new_slot in (("accessory_1", "ring_1"), ("accessory_2", "ring_2")):
            cur.execute("SELECT user_id, item_name FROM equipped WHERE slot_key = ?", (old_slot,))
            for row in cur.fetchall():
                cur.execute("SELECT 1 FROM equipped WHERE user_id = ? AND slot_key = ?", (row["user_id"], new_slot))
                if cur.fetchone() is None:
                    cur.execute(
                        "UPDATE equipped SET slot_key = ? WHERE user_id = ? AND slot_key = ?",
                        (new_slot, row["user_id"], old_slot),
                    )
                else:
                    cur.execute("DELETE FROM equipped WHERE user_id = ? AND slot_key = ?", (row["user_id"], old_slot))

        # One-time essence-cap bump — the primeval essence cap's base was raised (old default
        # 100), and apply_breakthrough scales it multiplicatively on every breakthrough since,
        # so scaling every pre-existing player's current cap AND banked essence by the same
        # factor reproduces exactly what they'd have if they'd started with the new base,
        # preserving their existing fill % instead of resetting it. Guarded by
        # essence_cap_migrated so this only ever touches each row once — new rows are already
        # inserted migrated (see get_or_create_player).
        cur.execute("SELECT user_id, primeval_essence, max_primeval_essence FROM players WHERE essence_cap_migrated = 0")
        for row in cur.fetchall():
            cur.execute(
                "UPDATE players SET primeval_essence = ?, max_primeval_essence = ?, essence_cap_migrated = 1 WHERE user_id = ?",
                (
                    row["primeval_essence"] * self.PRIMEVAL_ESSENCE_CAP_SCALE,
                    row["max_primeval_essence"] * self.PRIMEVAL_ESSENCE_CAP_SCALE,
                    row["user_id"],
                ),
            )

        # One-time conversion of the old stackable Sword/Helm/Armor (Tn) catalog items into
        # crafted_gear instances, now that /blacksmith grants unique rolled pieces instead
        # (see GameManager.craft_gear). Existing owned/equipped pieces get an instance row
        # carrying their old FIXED stats (equipment.BLACKSMITH_GEAR_STATS) rather than a
        # fresh random roll — reproduces exactly what they already had instead of silently
        # reshuffling or deleting it. Self-guarding/idempotent like the renames above: once a
        # row is converted it no longer matches "item_name LIKE '% (T_)'" and won't be picked
        # up again on a later setup() call.
        from . import blacksmith as _blacksmith  # local import: avoids a module-load-order dependency
        from . import equipment as equipment_module

        legacy_names = {
            equipment_module.blacksmith_gear_name(gear_type, tier): (gear_type, tier)
            for gear_type in ("Sword", "Helm", "Armor")
            for tier in range(_blacksmith.MIN_TIER, _blacksmith.MAX_TIER + 1)
        }
        if legacy_names:
            placeholders = ", ".join("?" for _ in legacy_names)
            cur.execute(f"SELECT id, user_id, item_name, quantity FROM inventory WHERE item_name IN ({placeholders})", tuple(legacy_names))
            for row in cur.fetchall():
                gear_type, tier = legacy_names[row["item_name"]]
                stat_bonuses = equipment_module.BLACKSMITH_GEAR_STATS[gear_type][tier]
                slot_type = equipment_module.BLACKSMITH_GEAR_SLOT_TYPE[gear_type]
                for _ in range(row["quantity"]):
                    cur.execute(
                        "INSERT INTO crafted_gear (owner_id, base_type, slot_type, tier, stat_bonuses, power_score, created_ts) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            row["user_id"], gear_type, slot_type, tier, json.dumps(stat_bonuses),
                            equipment_module.gear_power_score_from_stats(stat_bonuses), int(time.time()),
                        ),
                    )
                cur.execute("DELETE FROM inventory WHERE id = ?", (row["id"],))

            cur.execute(f"SELECT user_id, slot_key, item_name FROM equipped WHERE item_name IN ({placeholders})", tuple(legacy_names))
            for row in cur.fetchall():
                gear_type, tier = legacy_names[row["item_name"]]
                stat_bonuses = equipment_module.BLACKSMITH_GEAR_STATS[gear_type][tier]
                slot_type = equipment_module.BLACKSMITH_GEAR_SLOT_TYPE[gear_type]
                cur.execute(
                    "INSERT INTO crafted_gear (owner_id, base_type, slot_type, tier, stat_bonuses, power_score, created_ts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        row["user_id"], gear_type, slot_type, tier, json.dumps(stat_bonuses),
                        equipment_module.gear_power_score_from_stats(stat_bonuses), int(time.time()),
                    ),
                )
                gear_id = cur.lastrowid
                display_name = _blacksmith.crafted_gear_display_name(gear_type, tier, gear_id)
                cur.execute(
                    "UPDATE equipped SET item_name = ?, gear_id = ? WHERE user_id = ? AND slot_key = ?",
                    (display_name, gear_id, row["user_id"], row["slot_key"]),
                )

        con.commit()
        con.close()

    def _generate_aptitude(self) -> int:
        weights = [weight for weight, _, _ in self.APTITUDE_BANDS]
        _, lo, hi = random.choices(self.APTITUDE_BANDS, weights=weights, k=1)[0]
        return random.randint(lo, hi)

    def get_or_create_player(self, user_id: int, name: str):
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
        player = cur.fetchone()
        if player is None:
            aptitude_score = self._generate_aptitude()
            cur.execute(
                "INSERT INTO players (user_id, name, aptitude, last_qi_ts, root_rerolls_remaining, physique_rerolls_remaining, "
                "primeval_essence, max_primeval_essence, essence_cap_migrated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
                (
                    user_id, name, aptitude_score, int(time.time()), self.STARTER_REROLLS, self.STARTER_REROLLS,
                    self.STARTER_PRIMEVAL_ESSENCE, self.STARTER_MAX_PRIMEVAL_ESSENCE,
                ),
            )
            con.commit()
            cur.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
            player = cur.fetchone()
        if player["name"] != name:
            cur.execute("UPDATE players SET name = ? WHERE user_id = ?", (name, user_id))
            con.commit()
            cur.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
            player = cur.fetchone()
        con.close()
        return player

    def get_player_row(self, user_id: int) -> Optional[dict]:
        """Read-only lookup by user_id -- unlike get_or_create_player, never creates a row
        and never touches the stored name. Use this (not get_or_create_player) when looking
        up someone ELSE's row where the caller doesn't reliably know that other player's
        current Discord display name -- passing a placeholder name into get_or_create_player
        would silently overwrite their real one (see its own name != name sync check)."""
        con = self.connect()
        row = con.execute("SELECT * FROM players WHERE user_id = ?", (user_id,)).fetchone()
        con.close()
        return dict(row) if row else None

    def get_recent_pvp_players(self, exclude_user_id: int, since_ts: int) -> list:
        """Other confirmed characters whose last_pvp_ts is within the cooldown window —
        candidates for /pvp to match against as a "real opponent" instead of a random clone."""
        con = self.connect()
        cur = con.execute(
            "SELECT * FROM players WHERE character_confirmed = 1 AND user_id != ? AND last_pvp_ts >= ?",
            (exclude_user_id, since_ts),
        )
        rows = cur.fetchall()
        con.close()
        return rows

    def get_confirmed_players(self, exclude_user_id: int) -> list:
        """Every other confirmed character — the full fallback pool /pvp draws a random
        "clone" opponent from when nobody's recently searched for a match."""
        con = self.connect()
        cur = con.execute("SELECT * FROM players WHERE character_confirmed = 1 AND user_id != ?", (exclude_user_id,))
        rows = cur.fetchall()
        con.close()
        return rows

    def get_all_confirmed_players(self) -> list:
        """Every confirmed character, no exclusion — /leaderboard's source pool."""
        con = self.connect()
        cur = con.execute("SELECT * FROM players WHERE character_confirmed = 1")
        rows = cur.fetchall()
        con.close()
        return rows

    def _essence_capacity_multiplier(self, cur, user_id: int, player) -> float:
        """1 + this player's total essence_capacity_pct from their equipped primary/auxiliary
        manuals (same primary-100%/auxiliary-35% weighting _qi_rate_components uses for every
        other manual effect). Self-contained here — reading manuals directly off `player`
        rather than being threaded down from a manager.py compute_equipment_bonuses call, the
        way essence_purity_pct is — so it's automatically picked up by every essence-cap site
        below, INCLUDING items.py's Primeval Essence Crystal restore, which only ever calls
        into this file as restore_essence_percent(db, user_id) with no equipment-bonus context
        of its own."""
        total_pct = 0.0
        for manual_id, weight in ((player["equipped_primary_manual_id"], 1.0), (player["equipped_auxiliary_manual_id"], 0.35)):
            if not manual_id:
                continue
            row = cur.execute("SELECT effects FROM manuals WHERE manual_id = ? AND owner_id = ?", (manual_id, user_id)).fetchone()
            if not row:
                continue
            total_pct += json.loads(row["effects"]).get("essence_capacity_pct", 0) * weight
        return 1 + total_pct / 100.0

    def get_effective_max_essence(self, user_id: int) -> int:
        """Read-only effective essence cap (base max_primeval_essence plus any equipped
        manuals' essence_capacity_pct) for display sites (balance_view.py, views.py) that
        aren't already going through one of the cap-enforcing methods below."""
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "SELECT max_primeval_essence, equipped_primary_manual_id, equipped_auxiliary_manual_id "
            "FROM players WHERE user_id = ?", (user_id,),
        )
        row = cur.fetchone()
        result = round(row["max_primeval_essence"] * self._essence_capacity_multiplier(cur, user_id, row))
        con.close()
        return result

    def _qi_rate_components(self, cur, user_id: int, player, now: int) -> dict:
        """Every source of qi-rate bonus besides the base aptitude rate and the permanent
        qi_multiplier column — shared by settle_qi (which applies it) and get_qi_status
        (which just reports it), so the two can never drift apart."""
        cur.execute(
            "SELECT name, qi_multiplier_bonus, expires_at FROM buffs WHERE user_id = ? AND expires_at > ? ORDER BY expires_at",
            (user_id, now),
        )
        active_buffs = cur.fetchall()
        buff_bonus = sum(b["qi_multiplier_bonus"] for b in active_buffs)

        from . import chargen  # local import: avoids a hard dependency for callers that don't need chargen
        from .equipment import EQUIPMENT

        character_bonus = chargen.effective_qi_rate_bonus(
            chargen.get_race(player["race"]),
            chargen.get_root_tier(player["root_tier"]),
            chargen.get_physique_tier(player["physique_tier"]),
            chargen.get_path(player["cultivation_path"]),
        )
        # Ancient Solar/Moon Spiritual Root (Unique) -- a flat +15% cultivation speed for only
        # half the day, which doesn't fit the always-on additive stat_bonuses pool
        # effective_qi_rate_bonus reads from, so it's a localized root_name check here instead
        # (same "Unique mechanics check name directly" precedent as Giant Sun Inheritor Root's
        # Luck Tide -- see character_data.py's own root-spec comment). Doubled to +30% if this
        # player's Dao Companion (see dao_companions) holds the OPPOSITE root -- Solar+Moon
        # paired together, per explicit request -- checked directly via the shared cursor
        # rather than GameDatabase.get_dao_companion, since that would open a second connection.
        solar_active = player["root_name"] == "Ancient Solar Spiritual Root" and chargen.is_daytime()
        moon_active = player["root_name"] == "Ancient Moon Spiritual Root" and not chargen.is_daytime()
        if solar_active or moon_active:
            bonus = 0.15
            opposite_root = "Ancient Moon Spiritual Root" if solar_active else "Ancient Solar Spiritual Root"
            companion_row = cur.execute(
                "SELECT partner_a_id, partner_b_id FROM dao_companions WHERE partner_a_id = ? OR partner_b_id = ?",
                (user_id, user_id),
            ).fetchone()
            if companion_row:
                partner_id = companion_row["partner_b_id"] if companion_row["partner_a_id"] == user_id else companion_row["partner_a_id"]
                partner_row = cur.execute("SELECT root_name FROM players WHERE user_id = ?", (partner_id,)).fetchone()
                if partner_row and partner_row["root_name"] == opposite_root:
                    bonus *= 2
            character_bonus += bonus

        cur.execute("SELECT item_name FROM equipped WHERE user_id = ? AND slot_key = 'manual'", (user_id,))
        manual_row = cur.fetchone()
        manual = EQUIPMENT.get(manual_row["item_name"]) if manual_row else None
        manual_bonus = manual.stat_bonuses.get("cultivation_speed_pct", 0) if manual else 0
        # Every manual actually contributing to manual_bonus below, by name -- used to be just
        # the legacy slot's own name, which reported "None" for anyone using ONLY the newer
        # primary/auxiliary assembled-manual system (the intended path going forward) even
        # though their manual_bonus was correctly nonzero, a misleading "Manual (None): +18.5%"
        # style display. Built up alongside the primary/auxiliary loop just below.
        manual_names = [manual.name] if manual else []

        # New page-assembled manual system (see manual_data.py/manual_gen.py) — coexists
        # with the old single-item equipped "manual" slot above rather than replacing it,
        # but the soft/hard cap safeguard (design doc section 18) has to bound the COMBINED
        # cultivation bonus from every manual source, old and new alike, or the old slot's
        # small uncapped 2% would just be an unbounded side door around the cap. Primary
        # manual contributes 100% of its cultivation effects, auxiliary 35% (section 5).
        # Effects are stored as percent numbers (5.0 == +5%, matching the design doc), so
        # /100 converts to the same fraction units this whole function works in.
        from . import realms as _realms
        from . import search_data as _search_data

        total_manual_pct = manual_bonus * 100
        # Every OTHER effect a manual can roll (breakthrough_success_pct, hp_pct,
        # dodge_chance_pct, technique/physical_damage_pct, insight_gain_pct,
        # cooldown_reduction_pct, deviation_resistance_pct, essence_recovery/purity_pct —
        # see manual_view.EFFECT_LABELS) — weighted the same as cultivation (primary 100%,
        # auxiliary 35%) but summed separately, since the soft/hard cultivation cap below
        # only ever applied to the two cultivation keys and has no business touching these.
        other_effect_totals: Dict[str, float] = {}
        for manual_id, weight in ((player["equipped_primary_manual_id"], 1.0), (player["equipped_auxiliary_manual_id"], 0.35)):
            if not manual_id:
                continue
            row = cur.execute("SELECT name, effects FROM manuals WHERE manual_id = ? AND owner_id = ?", (manual_id, user_id)).fetchone()
            if not row:
                continue
            manual_names.append(row["name"])
            effects = json.loads(row["effects"])
            total_manual_pct += (effects.get("cultivation_gain_pct", 0) + effects.get("cultivation_speed_pct", 0)) * weight
            for key, value in effects.items():
                if key in ("cultivation_gain_pct", "cultivation_speed_pct"):
                    continue
                other_effect_totals[key] = other_effect_totals.get(key, 0.0) + value * weight

        manual_name = " + ".join(manual_names) if manual_names else None

        # Accessories/artifacts (see accessories_data.py) with a passive cultivation_speed_pct
        # stat_bonus fold into this same capped total too — same reasoning as the old manual
        # slot above: a per-item cultivation bonus left uncapped would be a side door around
        # the design doc's own "cultivation bonuses from equipment cap at +35%" rule.
        from . import accessories_data as _accessories_data

        cur.execute(
            "SELECT accessory_instance_id FROM equipped WHERE user_id = ? AND accessory_instance_id IS NOT NULL",
            (user_id,),
        )
        for row in cur.fetchall():
            inst_row = cur.execute(
                "SELECT item_id FROM accessory_artifact_instances WHERE instance_id = ?", (row["accessory_instance_id"],)
            ).fetchone()
            if not inst_row:
                continue
            affix = _accessories_data.ITEMS.get(inst_row["item_id"])
            if affix:
                total_manual_pct += affix.stat_bonuses.get("cultivation_speed_pct", 0) * 100

        # Regular equipment.EQUIPMENT catalog items (Gu included — see world_boss.py's Human
        # Qi Gu / Dragon Bone Ring, the first non-manual, non-accessory items to carry this
        # key) with a cultivation_speed_pct stat_bonus fold in the same way, same reasoning.
        # slot_key != 'manual' excludes the legacy manual slot, already counted above via
        # manual_bonus — including it again here would double-count it.
        cur.execute("SELECT slot_key, item_name FROM equipped WHERE user_id = ? AND slot_key != 'manual'", (user_id,))
        for row in cur.fetchall():
            gear = EQUIPMENT.get(row["item_name"])
            if gear:
                total_manual_pct += gear.stat_bonuses.get("cultivation_speed_pct", 0) * 100

        # Nascent Soul Avatar's own rolled gear (see avatar_gear.py's UTILITY_KEYS) and its
        # soul passive (see avatar.py's scaled_bonus) can both carry cultivation_speed_pct --
        # this was previously ONLY folded into GameManager.compute_equipment_bonuses' generic
        # display pool, which is read by combat views but NEVER by settle_qi/get_qi_status, so
        # equipping avatar gear rolled with Cultivation Speed silently did nothing to actual
        # qi gain (same class of bug the Solar/Moon root special case above exists to avoid).
        from . import avatar as _avatar

        cur.execute("SELECT instance_id FROM avatar_equipped WHERE user_id = ? AND instance_id IS NOT NULL", (user_id,))
        for row in cur.fetchall():
            inst_row = cur.execute(
                "SELECT stat_bonuses FROM avatar_gear_instances WHERE instance_id = ?", (row["instance_id"],)
            ).fetchone()
            if not inst_row:
                continue
            total_manual_pct += json.loads(inst_row["stat_bonuses"]).get("cultivation_speed_pct", 0) * 100
        total_manual_pct += _avatar.scaled_bonus(player["avatar_soul"], player["avatar_level"], "cultivation_speed_pct") * 100

        # Gu Pet (see game/gu_pet.py / /gu_pet) -- an active MATURE pet in Cultivation Mode
        # can carry cultivation_speed_pct too (see gu_pet.CATEGORY_STAT_KEYS' "pill" category
        # and gu_pet.roll_specialty_bonus's Unbound fallback). This is the REAL hook for it --
        # this exact "only folded into GameManager.compute_equipment_bonuses' generic display
        # pool, never read by settle_qi/get_qi_status" mistake has already bitten avatar
        # gear/soul cultivation speed TWICE in this codebase (see the avatar-gear/avatar-soul
        # comments just above), so this rides _qi_rate_components from the start instead.
        # Computed READ-ONLY here (current satiety live off last_satiety_update_ts, the same
        # lazy-settlement math GameManager._settle_gu_pet_satiety uses, just without the
        # write-back -- that write-back is a pure optimization owned by that method, not a
        # correctness requirement for this read).
        from . import gu_pet as _gu_pet

        if player["active_gu_pet_id"]:
            pet_row = cur.execute("SELECT * FROM gu_pets WHERE pet_id = ?", (player["active_gu_pet_id"],)).fetchone()
            if pet_row and pet_row["stage"] == _gu_pet.STAGE_MATURE and pet_row["mode"] == _gu_pet.MODE_CULTIVATION:
                elapsed_hours = max(0, now - (pet_row["last_satiety_update_ts"] or now)) / 3600.0
                current_satiety = max(0.0, pet_row["satiety"] - elapsed_hours * _gu_pet.SATIETY_DRAIN_PER_CULTIVATION_HOUR)
                satiety_mult, _ = _gu_pet.satiety_band(current_satiety)
                pet_cultivation_pct = json.loads(pet_row["stat_bonuses"]).get("cultivation_speed_pct", 0)
                total_manual_pct += pet_cultivation_pct * satiety_mult * 100

        player_rank = _realms.STAGES[player["realm_index"]].great_realm_index + 1
        soft_cap = _search_data.CULTIVATION_SOFT_CAP_BY_PLAYER_RANK.get(player_rank, 100)
        hard_cap = _search_data.CULTIVATION_HARD_CAP_BY_PLAYER_RANK.get(player_rank, 100)
        if total_manual_pct > soft_cap:
            total_manual_pct = soft_cap + (total_manual_pct - soft_cap) * _search_data.EFFECTIVE_PCT_ABOVE_SOFT_CAP
        total_manual_pct = min(total_manual_pct, hard_cap)
        manual_bonus = total_manual_pct / 100.0
        manual_effect_bonuses = {key: value / 100.0 for key, value in other_effect_totals.items()}

        return {
            "active_buffs": active_buffs,
            "buff_bonus": buff_bonus,
            "character_bonus": character_bonus,
            "manual_bonus": manual_bonus,
            "manual_name": manual_name,
            "manual_effect_bonuses": manual_effect_bonuses,
        }

    def settle_qi(self, user_id: int):
        """Bank any qi accrued since the last settlement and return (player, gained)."""
        con = self.connect()
        cur = con.cursor()
        now = int(time.time())

        cur.execute("DELETE FROM buffs WHERE user_id = ? AND expires_at <= ?", (user_id, now))

        cur.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
        player = cur.fetchone()

        last_ts = player["last_qi_ts"] or 0
        # A missing/zero timestamp means this is the first settlement (e.g. a
        # column added after the row existed) — don't pay out for that gap.
        elapsed_seconds = max(0, now - last_ts) if last_ts else 0

        components = self._qi_rate_components(cur, user_id, player, now)
        # manual_bonus AND buff_bonus are both multiplicative against the permanent base
        # (qi_multiplier + character_bonus) instead of folded into the same additive sum --
        # pills/root/physique stacking can reach the double digits at high power, which used
        # to drown out even a maxed-coherence manual or a strong timed buff to a rounding
        # error. This way a manual's or buff's printed bonus always means "+X% cultivation
        # rate", full stop, regardless of how stacked the rest of a player's build is. A no-op
        # for a fresh character (qi_multiplier=1, character_bonus=0, no buff active), so this
        # only changes anything once a player has real permanent stacking to get diluted by.
        permanent_multiplier = player["qi_multiplier"] + components["character_bonus"]
        total_multiplier = permanent_multiplier * (1 + components["buff_bonus"]) * (1 + components["manual_bonus"])

        rate_per_minute = player["aptitude"] * self.BASE_QI_PER_MINUTE_PER_APTITUDE
        gained = (elapsed_seconds / 60.0) * rate_per_minute * total_multiplier

        new_qi = player["qi"] + gained
        cur.execute(
            "UPDATE players SET qi = ?, last_qi_ts = ? WHERE user_id = ?",
            (new_qi, now, user_id),
        )
        con.commit()
        cur.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
        player = cur.fetchone()
        con.close()
        return player, gained

    def get_qi_status(self, user_id: int) -> dict:
        """Read-only snapshot for /qi: progress, rate breakdown, and time-to-breakthrough estimate."""
        from . import realms

        con = self.connect()
        cur = con.cursor()
        now = int(time.time())

        cur.execute("DELETE FROM buffs WHERE user_id = ? AND expires_at <= ?", (user_id, now))
        con.commit()

        cur.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
        player = cur.fetchone()
        components = self._qi_rate_components(cur, user_id, player, now)
        con.close()

        # Mirrors settle_qi's identical multiplicative-manual/buff formula exactly -- see that
        # method's own comment for why manual_bonus and buff_bonus are no longer folded into
        # the same additive sum as qi_multiplier/character_bonus.
        permanent_multiplier = player["qi_multiplier"] + components["character_bonus"]
        total_multiplier = permanent_multiplier * (1 + components["buff_bonus"]) * (1 + components["manual_bonus"])
        base_rate_per_minute = player["aptitude"] * self.BASE_QI_PER_MINUTE_PER_APTITUDE
        effective_rate_per_minute = base_rate_per_minute * total_multiplier

        at_max_realm = realms.is_max_realm(player["realm_index"])
        qi_required = None if at_max_realm else realms.qi_required_for_next(player["realm_index"])
        ready = (not at_max_realm) and player["qi"] >= qi_required

        seconds_remaining = None
        if not at_max_realm and not ready and effective_rate_per_minute > 0:
            seconds_remaining = ((qi_required - player["qi"]) / effective_rate_per_minute) * 60

        return {
            "player": player,
            "realm_name": realms.realm_name(player["realm_index"]),
            "next_realm_name": None if at_max_realm else realms.realm_name(player["realm_index"] + 1),
            "at_max_realm": at_max_realm,
            "qi_required": qi_required,
            "ready": ready,
            "base_rate_per_minute": base_rate_per_minute,
            "total_multiplier": total_multiplier,
            "effective_rate_per_minute": effective_rate_per_minute,
            "seconds_remaining": seconds_remaining,
            **components,
        }

    def apply_breakthrough(
        self,
        user_id: int,
        qi_cost: float,
        success: bool,
        bonus_qi: float = 0,
        stat_growth_key: Optional[str] = None,
        power_multiplier: float = 1.0,
    ):
        """Spend qi_cost regardless of outcome; on success also advance realm_index,
        refund bonus_qi, scale STR/ATK/SPD/DEF/QI(stat)/max primeval essence by
        power_multiplier, and grow stat_growth_key by 1 extra if given. LCK is
        untouched — it's fortune, not power. Current HP and essence scale with
        their caps so the player's existing percentage is preserved, not reset."""
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT qi FROM players WHERE user_id = ?", (user_id,))
        new_qi = max(0.0, cur.fetchone()["qi"] - qi_cost)

        if success:
            new_qi += bonus_qi
            # 15 placeholders total: qi, 13x power_multiplier (one per ? below, in column
            # order), user_id — the tuple previously supplied only 12 power_multiplier
            # values (missing the second half of the primeval_essence MIN(...) pair), which
            # raised sqlite3.ProgrammingError on every successful breakthrough (failed
            # attempts use the simpler branch below and were unaffected, which is why this
            # looked like "sometimes it just doesn't work" rather than a hard, visible bug).
            cur.execute(
                """UPDATE players SET
                    qi = ?,
                    realm_index = realm_index + 1,
                    str_stat = MAX(1, ROUND(str_stat * ?)),
                    atk_stat = MAX(1, ROUND(atk_stat * ?)),
                    spd_stat = MAX(1, ROUND(spd_stat * ?)),
                    def_stat = MAX(1, ROUND(def_stat * ?)),
                    qi_stat = MAX(1, ROUND(qi_stat * ?)),
                    max_hp = MAX(1, ROUND(max_hp * ?)),
                    hp = MIN(MAX(1, ROUND(max_hp * ?)), MAX(1, ROUND(hp * ?))),
                    max_primeval_essence = MAX(1, ROUND(max_primeval_essence * ?)),
                    primeval_essence = MIN(MAX(1, ROUND(max_primeval_essence * ?)), MAX(1, ROUND(primeval_essence * ?))),
                    battle_qi = MIN(MAX(1, ROUND(qi_stat * ?)), ROUND(battle_qi * ?))
                WHERE user_id = ?""",
                (
                    new_qi,
                    power_multiplier,  # str_stat
                    power_multiplier,  # atk_stat
                    power_multiplier,  # spd_stat
                    power_multiplier,  # def_stat
                    power_multiplier,  # qi_stat
                    power_multiplier,  # max_hp
                    power_multiplier,  # hp: MIN bound (max_hp * ?)
                    power_multiplier,  # hp: current (hp * ?)
                    power_multiplier,  # max_primeval_essence
                    power_multiplier,  # primeval_essence: MIN bound (max_primeval_essence * ?)
                    power_multiplier,  # primeval_essence: current (primeval_essence * ?)
                    power_multiplier,  # battle_qi: MIN bound (qi_stat * ?)
                    power_multiplier,  # battle_qi: current (battle_qi * ?)
                    user_id,
                ),
            )
            if stat_growth_key:
                # stat_growth_key only ever comes from chargen.STAT_GROWTH_KEYS, never user input.
                cur.execute(f"UPDATE players SET {stat_growth_key} = {stat_growth_key} + 1 WHERE user_id = ?", (user_id,))
        else:
            cur.execute("UPDATE players SET qi = ? WHERE user_id = ?", (new_qi, user_id))

        con.commit()
        cur.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
        player = cur.fetchone()
        con.close()
        return player

    def add_permanent_stat_bonus(self, user_id: int, stat_key: str, amount: int):
        """Limitless Inheritor Root's Boundless Foundation — a flat, permanent addition to
        one foundation stat column, same whitelisted-key dynamic-SQL pattern
        apply_breakthrough's own stat_growth_key already uses. stat_key must come from
        chargen.STAT_GROWTH_KEYS, never user input."""
        con = self.connect()
        con.execute(f"UPDATE players SET {stat_key} = {stat_key} + ? WHERE user_id = ?", (amount, user_id))
        con.commit()
        con.close()

    def get_active_buffs(self, user_id: int):
        con = self.connect()
        cur = con.cursor()
        now = int(time.time())
        cur.execute("DELETE FROM buffs WHERE user_id = ? AND expires_at <= ?", (user_id, now))
        con.commit()
        cur.execute(
            "SELECT * FROM buffs WHERE user_id = ? AND expires_at > ? ORDER BY expires_at",
            (user_id, now),
        )
        buffs = cur.fetchall()
        con.close()
        return buffs

    def add_buff(
        self, user_id: int, name: str, qi_multiplier_bonus: float, duration_seconds: int,
        str_bonus: float = 0, atk_bonus: float = 0, def_bonus: float = 0, spd_bonus: float = 0,
        special_bonuses: Optional[dict] = None,
    ):
        con = self.connect()
        cur = con.cursor()
        expires_at = int(time.time()) + duration_seconds
        cur.execute(
            "INSERT INTO buffs (user_id, name, qi_multiplier_bonus, expires_at, str_bonus, atk_bonus, def_bonus, spd_bonus, special_bonuses) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id, name, qi_multiplier_bonus, expires_at, str_bonus, atk_bonus, def_bonus, spd_bonus,
                json.dumps(special_bonuses) if special_bonuses else None,
            ),
        )
        con.commit()
        con.close()

    def add_or_extend_cultivation_boost_buff(self, user_id: int, name: str, qi_multiplier_bonus: float, duration_seconds: int):
        """Cultivation Boost pills stack per-TIER, not globally -- per explicit request, a
        player can have every tier's buff (T1 through T7) running at once, each contributing
        its own qi_multiplier_bonus. _qi_rate_components already sums qi_multiplier_bonus
        across EVERY active buff row unconditionally, and the Active Buffs displays (cog.py's
        /qi and /cd, views.py's ProfileView) already group by the buff's own `name` -- since
        `name` already encodes the tier (see items.alchemy_pill_name, "Cultivation Boost Pill
        (T{tier})"), tiers naturally render as separate lines with zero display changes needed.
        This method's only job is per-tier consolidation: using ANOTHER pill of the SAME tier
        while that tier's buff is already active EXTENDS its remaining time by this pill's own
        duration rather than starting a second independently-expiring row for that same tier
        -- per the original "the timer goes up" request, now scoped to one tier at a time
        instead of any Cultivation Boost Pill. A different tier never touches this tier's row
        at all (or vice versa) -- no cross-tier interaction of any kind anymore. Returns
        (qi_multiplier_bonus, new_total_remaining_seconds)."""
        con = self.connect()
        cur = con.cursor()
        now = int(time.time())
        cur.execute(
            "SELECT id, expires_at FROM buffs WHERE user_id = ? AND name = ? AND expires_at > ?",
            (user_id, name, now),
        )
        existing = cur.fetchone()
        if existing:
            new_expires_at = existing["expires_at"] + duration_seconds
            cur.execute(
                "UPDATE buffs SET qi_multiplier_bonus = ?, expires_at = ? WHERE id = ?",
                (qi_multiplier_bonus, new_expires_at, existing["id"]),
            )
        else:
            new_expires_at = now + duration_seconds
            cur.execute(
                "INSERT INTO buffs (user_id, name, qi_multiplier_bonus, expires_at) VALUES (?, ?, ?, ?)",
                (user_id, name, qi_multiplier_bonus, new_expires_at),
            )
        con.commit()
        con.close()
        return qi_multiplier_bonus, new_expires_at - now

    def get_active_combat_buff_totals(self, user_id: int) -> dict:
        """Summed flat str/atk/def/spd bonuses from currently-active buffs (e.g. Epic
        Physique's post-breakthrough vigor) — combat code folds this in alongside equipment
        bonuses. Most buffs are qi_multiplier-only (str/atk/def/spd_bonus default 0), so this
        is 0 for everyone except while that specific buff is active."""
        buffs = self.get_active_buffs(user_id)
        return {
            "str_stat": sum(b["str_bonus"] for b in buffs),
            "atk_stat": sum(b["atk_bonus"] for b in buffs),
            "def_stat": sum(b["def_bonus"] for b in buffs),
            "spd_stat": sum(b["spd_bonus"] for b in buffs),
        }

    def get_active_buff_special_bonuses(self, user_id: int) -> dict:
        """Summed SPECIAL_BONUS_KEYS-shaped bonuses (e.g. a buff-kind Killer Move's lifesteal,
        a loot-kind one's temporary loot_chance_bonus_pct) from currently-active buffs' JSON
        special_bonuses blob — kept separate from get_active_combat_buff_totals above since
        those keys fold into the `special` pool, not `stats`, in compute_equipment_bonuses."""
        totals: dict = {}
        for buff in self.get_active_buffs(user_id):
            blob = buff["special_bonuses"]
            if not blob:
                continue
            for key, value in json.loads(blob).items():
                totals[key] = totals.get(key, 0.0) + value
        return totals

    def try_use_daily_fatal_hit_negation(self, user_id: int) -> bool:
        """Mythic Physique's "ignore the first fatal hit each day" — returns True (and
        consumes it) the first time this is called on a given UTC calendar date; False every
        other time until the date rolls over."""
        today = time.strftime("%Y-%m-%d", time.gmtime())
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT last_fatal_hit_negated_date FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row and row["last_fatal_hit_negated_date"] == today:
            con.close()
            return False
        cur.execute("UPDATE players SET last_fatal_hit_negated_date = ? WHERE user_id = ?", (today, user_id))
        con.commit()
        con.close()
        return True

    def try_use_daily_avatar_fatal_block(self, user_id: int) -> bool:
        """Nascent Soul Avatar's own once-daily fatal-blow shield — same one-per-UTC-day
        pattern as try_use_daily_fatal_hit_negation just above, on its own separate column
        so the two daily charges (Mythic Physique's and the avatar's) never share or steal
        from each other."""
        today = time.strftime("%Y-%m-%d", time.gmtime())
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT last_avatar_fatal_block_date FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row and row["last_avatar_fatal_block_date"] == today:
            con.close()
            return False
        cur.execute("UPDATE players SET last_avatar_fatal_block_date = ? WHERE user_id = ?", (today, user_id))
        con.commit()
        con.close()
        return True

    def try_use_daily_search_upgrade(self, user_id: int) -> bool:
        """Void Star Root's "once daily, a search that would give nothing is upgraded to a
        minor find" — same one-per-UTC-day pattern as try_use_daily_fatal_hit_negation just
        above, on its own separate column so the two daily charges never share or steal from
        each other."""
        today = time.strftime("%Y-%m-%d", time.gmtime())
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT last_search_upgrade_date FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row and row["last_search_upgrade_date"] == today:
            con.close()
            return False
        cur.execute("UPDATE players SET last_search_upgrade_date = ? WHERE user_id = ?", (today, user_id))
        con.commit()
        con.close()
        return True

    # -- Unique-root shared mechanic state (see character_data.py's Unique section) ----------

    def try_use_unique_daily_charge(self, user_id: int) -> bool:
        """Generic one-per-UTC-day charge shared by several Unique roots' own daily
        mechanics — same pattern as try_use_daily_search_upgrade, just not tied to one
        specific root, since a player only ever has one root active at a time."""
        today = time.strftime("%Y-%m-%d", time.gmtime())
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT unique_daily_charge_date FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row and row["unique_daily_charge_date"] == today:
            con.close()
            return False
        cur.execute("UPDATE players SET unique_daily_charge_date = ? WHERE user_id = ?", (today, user_id))
        con.commit()
        con.close()
        return True

    def try_use_unique_weekly_charge(self, user_id: int) -> bool:
        """Same idea as try_use_unique_daily_charge, gated by ISO calendar week instead of
        day — Red Lotus Inheritor Root's "once every seven days" retry."""
        week = time.strftime("%G-W%V", time.gmtime())
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT unique_weekly_charge_key FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row and row["unique_weekly_charge_key"] == week:
            con.close()
            return False
        cur.execute("UPDATE players SET unique_weekly_charge_key = ? WHERE user_id = ?", (week, user_id))
        con.commit()
        con.close()
        return True

    def add_unique_weekly_resource(self, user_id: int, amount: int, cap: int) -> int:
        """Adds to a weekly-capped resource pool (Spectral Soul Inheritor Root's Soul
        Fragments, Paradise Earth Inheritor Root's Merit, Genesis Lotus Inheritor Root's
        Karma) — resets to 0 the moment a new ISO week is detected, so the cap is a true "at
        most N per week," not an ever-growing total. Returns the new (capped) amount."""
        week = time.strftime("%G-W%V", time.gmtime())
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT unique_resource_amount, unique_resource_week FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        current = row["unique_resource_amount"] if row and row["unique_resource_week"] == week else 0
        new_amount = min(cap, current + amount)
        cur.execute(
            "UPDATE players SET unique_resource_amount = ?, unique_resource_week = ? WHERE user_id = ?",
            (new_amount, week, user_id),
        )
        con.commit()
        con.close()
        return new_amount

    def peek_unique_weekly_resource(self, user_id: int) -> int:
        """Read-only version of pop_unique_weekly_resource — doesn't zero it. Used by
        mechanics that auto-convert as they earn (see raid.py's Spectral Soul/Genesis Lotus
        handling) and need to know how much of a just-added amount was actually NEW versus
        already capped out this week."""
        week = time.strftime("%G-W%V", time.gmtime())
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT unique_resource_amount, unique_resource_week FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        con.close()
        return row["unique_resource_amount"] if row and row["unique_resource_week"] == week else 0

    def pop_unique_weekly_resource(self, user_id: int) -> int:
        """Reads and zeroes the current weekly resource pool in one step — an automatic
        weekly payout (see GameManager's own per-root spend logic). Returns 0 if it's stale
        (a prior week's leftover, which should never be paid out) or was never earned."""
        week = time.strftime("%G-W%V", time.gmtime())
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT unique_resource_amount, unique_resource_week FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        current = row["unique_resource_amount"] if row and row["unique_resource_week"] == week else 0
        if current:
            cur.execute("UPDATE players SET unique_resource_amount = 0 WHERE user_id = ?", (user_id,))
            con.commit()
        con.close()
        return current

    def try_increment_unique_permanent_counter(self, user_id: int, cap: int) -> bool:
        """Limitless Inheritor Root's "capped at five selections" lifetime counter (Boundless
        Foundation) — returns True (and increments) only while under cap."""
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT unique_permanent_counter FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        current = row["unique_permanent_counter"] if row else 0
        if current >= cap:
            con.close()
            return False
        cur.execute("UPDATE players SET unique_permanent_counter = ? WHERE user_id = ?", (current + 1, user_id))
        con.commit()
        con.close()
        return True

    def get_unique_choice(self, user_id: int) -> Optional[str]:
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT unique_choice FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        con.close()
        return row["unique_choice"] if row else None

    def set_unique_choice(self, user_id: int, value: str):
        con = self.connect()
        con.execute("UPDATE players SET unique_choice = ? WHERE user_id = ?", (value, user_id))
        con.commit()
        con.close()

    def spend_path_change(self, user_id: int) -> bool:
        """Decrements path_changes_remaining — a long-dormant column (see
        GameManager.change_cultivation_path, the first thing to actually consume it).
        Returns False without changing anything if none are left."""
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "UPDATE players SET path_changes_remaining = path_changes_remaining - 1 "
            "WHERE user_id = ? AND path_changes_remaining > 0",
            (user_id,),
        )
        con.commit()
        spent = cur.rowcount > 0
        con.close()
        return spent

    def heal_percent(self, user_id: int, percent: float):
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT hp, max_hp FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        new_hp = min(row["max_hp"], row["hp"] + round(row["max_hp"] * percent))
        healed = new_hp - row["hp"]
        cur.execute("UPDATE players SET hp = ? WHERE user_id = ?", (new_hp, user_id))
        con.commit()
        con.close()
        return healed, new_hp, row["max_hp"]

    def restore_essence_percent(self, user_id: int, percent: float, allow_overflow: bool = False):
        """allow_overflow=True (essence pills/crystals -- see items.py's essence-restoring
        use() callbacks) lets primeval_essence exceed effective_max rather than clamping and
        discarding the excess, so a pill used near a full essence bar is never partly wasted.
        Every other caller (equipment-bonus top-ups, essence exchange, etc.) leaves this False,
        unchanged."""
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "SELECT primeval_essence, max_primeval_essence, equipped_primary_manual_id, equipped_auxiliary_manual_id "
            "FROM players WHERE user_id = ?", (user_id,),
        )
        row = cur.fetchone()
        effective_max = round(row["max_primeval_essence"] * self._essence_capacity_multiplier(cur, user_id, row))
        uncapped = row["primeval_essence"] + round(effective_max * percent)
        # The max() guards a player who's already over cap (a prior overflow-allowed pill use)
        # from getting silently clamped back down by an unrelated capped call -- the cap only
        # ever limits how much THIS call can raise essence by, never retroactively shrinks a
        # balance that was already higher coming in.
        new_essence = uncapped if allow_overflow else min(max(effective_max, row["primeval_essence"]), uncapped)
        restored = new_essence - row["primeval_essence"]
        cur.execute("UPDATE players SET primeval_essence = ? WHERE user_id = ?", (new_essence, user_id))
        con.commit()
        con.close()
        return restored, new_essence, effective_max

    def add_qi(self, user_id: int, amount: float):
        """Flat qi grant (no cap — unlike HP/essence, qi has no max, just breakthrough
        thresholds), for things like /meditate's small qi bonus."""
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT qi FROM players WHERE user_id = ?", (user_id,))
        new_qi = cur.fetchone()["qi"] + amount
        cur.execute("UPDATE players SET qi = ? WHERE user_id = ?", (new_qi, user_id))
        con.commit()
        con.close()
        return new_qi

    def add_primeval_essence(self, user_id: int, amount: int, allow_overflow: bool = False):
        """allow_overflow -- see restore_essence_percent's own docstring; same deal, just for
        a flat amount (Dew Spirit Pellet) instead of a percent."""
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "SELECT primeval_essence, max_primeval_essence, equipped_primary_manual_id, equipped_auxiliary_manual_id "
            "FROM players WHERE user_id = ?", (user_id,),
        )
        row = cur.fetchone()
        effective_max = round(row["max_primeval_essence"] * self._essence_capacity_multiplier(cur, user_id, row))
        uncapped = row["primeval_essence"] + amount
        # See restore_essence_percent's own comment -- the cap only limits how much THIS call
        # can raise essence by, it never retroactively shrinks an already-higher balance.
        new_essence = uncapped if allow_overflow else min(max(effective_max, row["primeval_essence"]), uncapped)
        added = new_essence - row["primeval_essence"]
        cur.execute("UPDATE players SET primeval_essence = ? WHERE user_id = ?", (new_essence, user_id))
        con.commit()
        con.close()
        return added, new_essence, effective_max

    def add_qi_multiplier(self, user_id: int, amount: float):
        con = self.connect()
        cur = con.cursor()
        cur.execute("UPDATE players SET qi_multiplier = qi_multiplier + ? WHERE user_id = ?", (amount, user_id))
        con.commit()
        cur.execute("SELECT qi_multiplier FROM players WHERE user_id = ?", (user_id,))
        new_multiplier = cur.fetchone()["qi_multiplier"]
        con.close()
        return new_multiplier

    # Qi Ascension Pill (see items.py) -- unlike add_qi_multiplier above (a flat, unlimited-use
    # PERMANENT ADD), this MULTIPLIES qi_multiplier, so repeated uses compound exponentially
    # instead of stacking flat. That makes it far stronger per use, so each of the 7 tiers is
    # independently capped to QI_ASCENSION_MAX_USES_PER_TIER lifetime uses, AND tier N
    # additionally requires the player's own Great Realm rank (1=Qi Condensation ... 7=Ancient
    # Realm) to be >= N -- per explicit request, this replaced an earlier single shared
    # per-realm-resetting pool (5 uses total, any tier, refreshed on every realm-up) with a
    # per-tier lifetime budget instead, so a Spirit Severing cultivator (rank 5) can use up to
    # 5x each of Tiers 1-5 (25 uses total) rather than just 5 uses total regardless of tier.
    # Deliberately self-contained here (not in GameManager) since items.py's use() callback
    # only ever receives (db, user_id), no GameManager access -- same constraint noted on
    # essence_capacity_pct in database.py's own history.
    QI_ASCENSION_MAX_USES_PER_TIER = 5
    QI_ASCENSION_PCT_PER_TIER = 0.03
    QI_ASCENSION_TIER_COLUMN = {t: f"qi_ascension_uses_t{t}" for t in range(1, 8)}

    def get_qi_ascension_pill_status(self, user_id: int, tier: int) -> dict:
        """Read-only realm/cap check for a Tier `tier` Qi Ascension Pill -- mutates nothing,
        so callers (see GameManager.use_item's pre-removal guard) can find out a use would be
        refused BEFORE the pill is removed from inventory, instead of consuming it for
        nothing. Returns {"can_use", "reason", "uses", "max_uses", "player_rank",
        "qi_multiplier"} -- "reason" is None when can_use is True, else "realm_locked" (realm
        rank hasn't reached this tier yet) or "cap_reached" (this tier's lifetime cap is hit)."""
        from . import realms as _realms

        column = self.QI_ASCENSION_TIER_COLUMN[tier]
        con = self.connect()
        cur = con.cursor()
        cur.execute(f"SELECT realm_index, qi_multiplier, {column} FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        con.close()
        player_rank = _realms.STAGES[row["realm_index"]].great_realm_index + 1
        uses = row[column]

        reason = None
        if player_rank < tier:
            reason = "realm_locked"
        elif uses >= self.QI_ASCENSION_MAX_USES_PER_TIER:
            reason = "cap_reached"
        return {
            "can_use": reason is None, "reason": reason, "uses": uses,
            "max_uses": self.QI_ASCENSION_MAX_USES_PER_TIER, "player_rank": player_rank,
            "qi_multiplier": row["qi_multiplier"],
        }

    def use_qi_ascension_pill(self, user_id: int, tier: int) -> dict:
        """Returns {"used", "reason", "new_multiplier", "uses", "max_uses", "player_rank"} --
        "used" is False (nothing changed) either because the player's realm rank hasn't
        reached this tier yet ("reason": "realm_locked") or this tier's own lifetime cap is
        already hit ("reason": "cap_reached"). See get_qi_ascension_pill_status above for a
        non-mutating version of this same check."""
        status = self.get_qi_ascension_pill_status(user_id, tier)
        if not status["can_use"]:
            return {
                "used": False, "reason": status["reason"], "new_multiplier": status["qi_multiplier"],
                "uses": status["uses"], "max_uses": status["max_uses"], "player_rank": status["player_rank"],
            }

        column = self.QI_ASCENSION_TIER_COLUMN[tier]
        new_multiplier = status["qi_multiplier"] * (1 + self.QI_ASCENSION_PCT_PER_TIER * tier)
        uses = status["uses"] + 1
        con = self.connect()
        con.execute(f"UPDATE players SET qi_multiplier = ?, {column} = ? WHERE user_id = ?", (new_multiplier, uses, user_id))
        con.commit()
        con.close()
        return {"used": True, "reason": None, "new_multiplier": new_multiplier, "uses": uses, "max_uses": status["max_uses"], "player_rank": status["player_rank"]}

    def maybe_gain_aptitude(self, user_id: int, chance: float, amount: int = 1):
        con = self.connect()
        cur = con.cursor()
        gained = random.random() < chance
        if gained:
            cur.execute("UPDATE players SET aptitude = MIN(100, aptitude + ?) WHERE user_id = ?", (amount, user_id))
            con.commit()
        cur.execute("SELECT aptitude FROM players WHERE user_id = ?", (user_id,))
        new_aptitude = cur.fetchone()["aptitude"]
        con.close()
        return gained, new_aptitude

    def add_spirit_stones(self, user_id: int, amount: int):
        con = self.connect()
        con.execute("UPDATE players SET spirit_stones = spirit_stones + ? WHERE user_id = ?", (amount, user_id))
        con.commit()
        con.close()

    def spend_spirit_stones(self, user_id: int, amount: int) -> bool:
        """Atomic: only deducts if the player can actually afford it. Returns whether it happened."""
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "UPDATE players SET spirit_stones = spirit_stones - ? WHERE user_id = ? AND spirit_stones >= ?",
            (amount, user_id, amount),
        )
        con.commit()
        success = cur.rowcount > 0
        con.close()
        return success

    def set_hp(self, user_id: int, hp: int) -> int:
        """Clamped to [1, max_hp] — there's no death/respawn system, so combat can knock you down but not out."""
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT max_hp FROM players WHERE user_id = ?", (user_id,))
        max_hp = cur.fetchone()["max_hp"]
        clamped = max(1, min(max_hp, hp))
        cur.execute("UPDATE players SET hp = ? WHERE user_id = ?", (clamped, user_id))
        con.commit()
        con.close()
        return clamped

    # In-combat Qi regenerates slowly in real time, independent of any single hunt.
    BATTLE_QI_REGEN_PERCENT_PER_HOUR = 0.20  # full recovery in ~5 hours
    DEATH_QI_LOSS_PERCENT = 0.10  # fraction of cultivation `qi` lost on defeat in combat

    def settle_battle_qi(self, user_id: int, regen_rate_bonus_pct: float = 0.0):
        """Bank any real-time battle Qi regen since the last settlement and return the fresh
        player row. regen_rate_bonus_pct is a Sturdy Frame-family physique's own
        battle_qi_regen_bonus_pct (see character_data.CharacterTraitSpec) — a multiplier on
        the regen RATE itself, not a flat top-up."""
        con = self.connect()
        cur = con.cursor()
        now = int(time.time())
        cur.execute("SELECT battle_qi, battle_qi_last_ts, qi_stat FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        max_qi = row["qi_stat"]
        last_ts = row["battle_qi_last_ts"] or 0
        elapsed_seconds = max(0, now - last_ts) if last_ts else 0
        regen = (elapsed_seconds / 3600.0) * max_qi * self.BATTLE_QI_REGEN_PERCENT_PER_HOUR * (1 + regen_rate_bonus_pct)
        new_battle_qi = min(max_qi, row["battle_qi"] + regen)
        cur.execute("UPDATE players SET battle_qi = ?, battle_qi_last_ts = ? WHERE user_id = ?", (new_battle_qi, now, user_id))
        con.commit()
        cur.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
        player = cur.fetchone()
        con.close()
        return player

    def set_battle_qi(self, user_id: int, value: float) -> float:
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT qi_stat FROM players WHERE user_id = ?", (user_id,))
        max_qi = cur.fetchone()["qi_stat"]
        clamped = max(0.0, min(max_qi, value))
        cur.execute("UPDATE players SET battle_qi = ?, battle_qi_last_ts = ? WHERE user_id = ?", (clamped, int(time.time()), user_id))
        con.commit()
        con.close()
        return clamped

    # HP regenerates slowly in real time, faster the further you've progressed —
    # reuses the long-unused `last_restore_ts` column rather than adding a new one.
    BASE_HP_REGEN_PERCENT_PER_HOUR = 0.05  # 5%/hour at Body Tempering (Early)
    HP_REGEN_PERCENT_PER_REALM = 0.01  # +1%/hour per realm_index step reached
    MAX_HP_REGEN_PERCENT_PER_HOUR = 0.50  # cap so max realm isn't an instant full heal

    def settle_hp_regen(self, user_id: int):
        """Bank any real-time HP regen since the last settlement and return the fresh player row."""
        con = self.connect()
        cur = con.cursor()
        now = int(time.time())
        cur.execute("SELECT hp, max_hp, realm_index, last_restore_ts FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        last_ts = row["last_restore_ts"] or 0
        elapsed_seconds = max(0, now - last_ts) if last_ts else 0
        rate = min(self.MAX_HP_REGEN_PERCENT_PER_HOUR, self.BASE_HP_REGEN_PERCENT_PER_HOUR + row["realm_index"] * self.HP_REGEN_PERCENT_PER_REALM)
        regen = (elapsed_seconds / 3600.0) * row["max_hp"] * rate
        new_hp = min(row["max_hp"], row["hp"] + regen)
        cur.execute("UPDATE players SET hp = ?, last_restore_ts = ? WHERE user_id = ?", (round(new_hp), now, user_id))
        con.commit()
        cur.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
        player = cur.fetchone()
        con.close()
        return player

    def apply_death_penalty(self, user_id: int, reduction_pct: float = 0.0):
        """Losing a fight costs a fraction of your banked cultivation qi. Returns (qi_lost, new_qi).
        reduction_pct is a Heavenly Spirit-family root's own death_qi_loss_reduction_pct (see
        character_data.CharacterTraitSpec), capped so it can soften the loss but never zero
        it out entirely — same floor convention attempt_breakthrough's own deviation
        resistance already uses for the same reason."""
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT qi FROM players WHERE user_id = ?", (user_id,))
        current_qi = cur.fetchone()["qi"]
        qi_lost = current_qi * self.DEATH_QI_LOSS_PERCENT * (1 - min(0.8, max(0.0, reduction_pct)))
        new_qi = max(0.0, current_qi - qi_lost)
        cur.execute("UPDATE players SET qi = ? WHERE user_id = ?", (new_qi, user_id))
        con.commit()
        con.close()
        return qi_lost, new_qi

    def get_inventory(self, user_id: int):
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT item_name, quantity FROM inventory WHERE user_id = ? AND quantity > 0", (user_id,))
        rows = cur.fetchall()
        con.close()
        return {row["item_name"]: row["quantity"] for row in rows}

    def get_item_quantity(self, user_id: int, item_name: str) -> int:
        """Single-item counterpart to get_inventory -- used by GameManager.use_item_multiple's
        Use All loop, which needs to check ONE item's count after every single use; fetching
        (and re-parsing) the player's WHOLE inventory dict for that would be wasted work."""
        con = self.connect()
        row = con.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item_name = ?", (user_id, item_name)).fetchone()
        con.close()
        return row["quantity"] if row else 0

    def log_admin_action(self, actor_id: int, actor_name: str, target_id: int, target_name: str, action: str, detail: str):
        con = self.connect()
        con.execute(
            "INSERT INTO admin_audit_log (actor_id, actor_name, target_id, target_name, action, detail, created_ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (actor_id, actor_name, target_id, target_name, action, detail, int(time.time())),
        )
        con.commit()
        con.close()

    def get_audit_log(self, limit: int = 20, target_id: Optional[int] = None):
        con = self.connect()
        cur = con.cursor()
        if target_id is None:
            cur.execute("SELECT * FROM admin_audit_log ORDER BY id DESC LIMIT ?", (limit,))
        else:
            cur.execute(
                "SELECT * FROM admin_audit_log WHERE target_id = ? ORDER BY id DESC LIMIT ?",
                (target_id, limit),
            )
        rows = cur.fetchall()
        con.close()
        return [dict(row) for row in rows]

    # -- World Boss (see world_boss.py / GameManager's world-boss methods / /raidboss) --------

    def create_world_boss(self, boss_key: str, max_hp: int, expires_ts: int) -> int:
        con = self.connect()
        cur = con.cursor()
        now = int(time.time())
        cur.execute(
            "INSERT INTO world_boss (boss_key, max_hp, current_hp, spawned_ts, expires_ts, status) "
            "VALUES (?, ?, ?, ?, ?, 'alive')",
            (boss_key, max_hp, max_hp, now, expires_ts),
        )
        con.commit()
        boss_instance_id = cur.lastrowid
        con.close()
        return boss_instance_id

    def get_world_boss(self, boss_instance_id: int) -> Optional[dict]:
        con = self.connect()
        row = con.execute("SELECT * FROM world_boss WHERE boss_instance_id = ?", (boss_instance_id,)).fetchone()
        con.close()
        return dict(row) if row else None

    def get_active_world_boss(self) -> Optional[dict]:
        con = self.connect()
        row = con.execute("SELECT * FROM world_boss WHERE status = 'alive' ORDER BY boss_instance_id DESC LIMIT 1").fetchone()
        con.close()
        return dict(row) if row else None

    def get_latest_world_boss(self) -> Optional[dict]:
        """Most recent boss instance regardless of status — used to time the 3h respawn
        delay off whichever one ended last, or spawn immediately if none has ever existed."""
        con = self.connect()
        row = con.execute("SELECT * FROM world_boss ORDER BY boss_instance_id DESC LIMIT 1").fetchone()
        con.close()
        return dict(row) if row else None

    def apply_world_boss_damage(self, boss_instance_id: int, damage: int) -> int:
        """Subtracts damage from current_hp (floored at 0) and returns the new value."""
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT current_hp FROM world_boss WHERE boss_instance_id = ?", (boss_instance_id,))
        row = cur.fetchone()
        new_hp = max(0, row["current_hp"] - damage)
        cur.execute("UPDATE world_boss SET current_hp = ? WHERE boss_instance_id = ?", (new_hp, boss_instance_id))
        con.commit()
        con.close()
        return new_hp

    def set_world_boss_status(self, boss_instance_id: int, status: str):
        con = self.connect()
        con.execute(
            "UPDATE world_boss SET status = ?, ended_ts = ? WHERE boss_instance_id = ?",
            (status, int(time.time()), boss_instance_id),
        )
        con.commit()
        con.close()

    def record_world_boss_attack(self, boss_instance_id: int, user_id: int, name: str, damage: int) -> dict:
        """Upserts this player's running contribution row for boss_instance_id — one row per
        (boss, player) rather than one row per attack (see world_boss_damage's own table
        comment). Returns the row's new state (damage_dealt/attacks/highest_hit)."""
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "SELECT damage_dealt, attacks, highest_hit FROM world_boss_damage WHERE boss_instance_id = ? AND user_id = ?",
            (boss_instance_id, user_id),
        )
        row = cur.fetchone()
        if row:
            new_damage = row["damage_dealt"] + damage
            new_attacks = row["attacks"] + 1
            new_highest = max(row["highest_hit"], damage)
            cur.execute(
                "UPDATE world_boss_damage SET damage_dealt = ?, attacks = ?, highest_hit = ?, name = ? "
                "WHERE boss_instance_id = ? AND user_id = ?",
                (new_damage, new_attacks, new_highest, name, boss_instance_id, user_id),
            )
        else:
            new_damage, new_attacks, new_highest = damage, 1, damage
            cur.execute(
                "INSERT INTO world_boss_damage (boss_instance_id, user_id, name, damage_dealt, attacks, highest_hit) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                (boss_instance_id, user_id, name, damage, damage),
            )
        con.commit()
        con.close()
        return {"damage_dealt": new_damage, "attacks": new_attacks, "highest_hit": new_highest}

    def get_world_boss_damage(self, boss_instance_id: int, user_id: int) -> Optional[dict]:
        con = self.connect()
        row = con.execute(
            "SELECT * FROM world_boss_damage WHERE boss_instance_id = ? AND user_id = ?",
            (boss_instance_id, user_id),
        ).fetchone()
        con.close()
        return dict(row) if row else None

    def get_world_boss_contributors(self, boss_instance_id: int) -> list:
        con = self.connect()
        rows = con.execute(
            "SELECT * FROM world_boss_damage WHERE boss_instance_id = ? ORDER BY damage_dealt DESC",
            (boss_instance_id,),
        ).fetchall()
        con.close()
        return [dict(row) for row in rows]

    def mark_world_boss_contributor_rewarded(self, boss_instance_id: int, user_id: int):
        con = self.connect()
        con.execute(
            "UPDATE world_boss_damage SET rewarded = 1 WHERE boss_instance_id = ? AND user_id = ?",
            (boss_instance_id, user_id),
        )
        con.commit()
        con.close()

    # -- PvP Tournament (see game/tournament.py / /tournament) -----------------------------

    @staticmethod
    def _tournament_row_to_dict(row) -> dict:
        d = dict(row)
        d["result_log"] = json.loads(d["result_log"]) if d["result_log"] else None
        return d

    @staticmethod
    def _tournament_participant_row_to_dict(row) -> dict:
        d = dict(row)
        d["snapshot"] = json.loads(d["snapshot"]) if d["snapshot"] else None
        return d

    def create_tournament(self, signup_started_ts: int, signup_ends_ts: int) -> int:
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "INSERT INTO tournament (status, signup_started_ts, signup_ends_ts) VALUES ('signup', ?, ?)",
            (signup_started_ts, signup_ends_ts),
        )
        con.commit()
        tournament_id = cur.lastrowid
        con.close()
        return tournament_id

    def get_tournament(self, tournament_id: int) -> Optional[dict]:
        con = self.connect()
        row = con.execute("SELECT * FROM tournament WHERE tournament_id = ?", (tournament_id,)).fetchone()
        con.close()
        return self._tournament_row_to_dict(row) if row else None

    def get_active_tournament(self) -> Optional[dict]:
        con = self.connect()
        row = con.execute(
            "SELECT * FROM tournament WHERE status IN ('signup', 'running') ORDER BY tournament_id DESC LIMIT 1"
        ).fetchone()
        con.close()
        return self._tournament_row_to_dict(row) if row else None

    def get_latest_tournament(self) -> Optional[dict]:
        con = self.connect()
        row = con.execute("SELECT * FROM tournament ORDER BY tournament_id DESC LIMIT 1").fetchone()
        con.close()
        return self._tournament_row_to_dict(row) if row else None

    def start_tournament(self, tournament_id: int):
        con = self.connect()
        con.execute(
            "UPDATE tournament SET status = 'running', started_ts = ? WHERE tournament_id = ?",
            (int(time.time()), tournament_id),
        )
        con.commit()
        con.close()

    def complete_tournament(self, tournament_id: int, result_log: dict):
        con = self.connect()
        con.execute(
            "UPDATE tournament SET status = 'completed', ended_ts = ?, result_log = ? WHERE tournament_id = ?",
            (int(time.time()), json.dumps(result_log), tournament_id),
        )
        con.commit()
        con.close()

    def cancel_tournament(self, tournament_id: int):
        con = self.connect()
        con.execute(
            "UPDATE tournament SET status = 'cancelled', ended_ts = ? WHERE tournament_id = ?",
            (int(time.time()), tournament_id),
        )
        con.commit()
        con.close()

    def get_unannounced_tournament_results(self) -> list:
        """Every completed/cancelled tournament that hasn't been posted/DMed yet -- see
        GameManager.get_pending_tournament_announcements's docstring for why a tournament can
        finish without the tick loop being the one that resolved it."""
        con = self.connect()
        rows = con.execute(
            "SELECT * FROM tournament WHERE status IN ('completed', 'cancelled') AND announced_ts IS NULL "
            "ORDER BY tournament_id ASC"
        ).fetchall()
        con.close()
        return [self._tournament_row_to_dict(row) for row in rows]

    def mark_tournament_announced(self, tournament_id: int):
        con = self.connect()
        con.execute("UPDATE tournament SET announced_ts = ? WHERE tournament_id = ?", (int(time.time()), tournament_id))
        con.commit()
        con.close()

    def add_tournament_participant(self, tournament_id: int, user_id: int, name: str, snapshot: dict):
        con = self.connect()
        con.execute(
            "INSERT INTO tournament_participants (tournament_id, user_id, name, snapshot, joined_ts) VALUES (?, ?, ?, ?, ?)",
            (tournament_id, user_id, name, json.dumps(snapshot), int(time.time())),
        )
        con.commit()
        con.close()

    def get_tournament_participant(self, tournament_id: int, user_id: int) -> Optional[dict]:
        con = self.connect()
        row = con.execute(
            "SELECT * FROM tournament_participants WHERE tournament_id = ? AND user_id = ?",
            (tournament_id, user_id),
        ).fetchone()
        con.close()
        return self._tournament_participant_row_to_dict(row) if row else None

    def get_tournament_participants(self, tournament_id: int) -> list:
        con = self.connect()
        rows = con.execute(
            "SELECT * FROM tournament_participants WHERE tournament_id = ? ORDER BY joined_ts", (tournament_id,)
        ).fetchall()
        con.close()
        return [self._tournament_participant_row_to_dict(row) for row in rows]

    def remove_tournament_participant(self, tournament_id: int, user_id: int):
        con = self.connect()
        con.execute(
            "DELETE FROM tournament_participants WHERE tournament_id = ? AND user_id = ?",
            (tournament_id, user_id),
        )
        con.commit()
        con.close()

    def set_tournament_participant_result(self, tournament_id: int, user_id: int, placement: int):
        con = self.connect()
        con.execute(
            "UPDATE tournament_participants SET placement = ?, rewarded = 1 WHERE tournament_id = ? AND user_id = ?",
            (placement, tournament_id, user_id),
        )
        con.commit()
        con.close()

    def try_use_daily_gu_penalty_negation(self, user_id: int) -> bool:
        """Worldly Escape Gu's "once per day, ignore the penalty from one PvP defeat or
        failed dangerous exploration" — same today-compare/UPDATE/return-bool pattern as
        try_use_daily_fatal_hit_negation, its own dedicated column since a Gu isn't
        mutually exclusive with a root's own daily charge."""
        today = time.strftime("%Y-%m-%d", time.gmtime())
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT last_gu_penalty_negated_date FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row and row["last_gu_penalty_negated_date"] == today:
            con.close()
            return False
        cur.execute("UPDATE players SET last_gu_penalty_negated_date = ? WHERE user_id = ?", (today, user_id))
        con.commit()
        con.close()
        return True

    # -- Sects (see sects.py / GameManager's sect_* methods / /sect) ---------------------------

    def create_sect(self, leader_id: int, name: str) -> Optional[int]:
        """Creates the sect and immediately seats leader_id as its Sect Leader. Returns the
        new sect_id, or None if the name is already taken (UNIQUE constraint)."""
        con = self.connect()
        cur = con.cursor()
        try:
            cur.execute(
                "INSERT INTO sects (name, leader_id, created_ts) VALUES (?, ?, ?)",
                (name, leader_id, int(time.time())),
            )
        except sqlite3.IntegrityError:
            con.close()
            return None
        sect_id = cur.lastrowid
        cur.execute(
            "UPDATE players SET sect_id = ?, sect_rank = ?, sect_joined_ts = ? WHERE user_id = ?",
            (sect_id, sects.SECT_LEADER, int(time.time()), leader_id),
        )
        con.commit()
        con.close()
        return sect_id

    def get_sect(self, sect_id: int) -> Optional[dict]:
        con = self.connect()
        row = con.execute("SELECT * FROM sects WHERE sect_id = ?", (sect_id,)).fetchone()
        con.close()
        return dict(row) if row else None

    def get_sect_by_name(self, name: str) -> Optional[dict]:
        con = self.connect()
        row = con.execute("SELECT * FROM sects WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
        con.close()
        return dict(row) if row else None

    def list_sects(self) -> list:
        """Every sect, most members first -- see GameManager.sect_list."""
        con = self.connect()
        cur = con.cursor()
        sects_rows = [dict(row) for row in cur.execute("SELECT * FROM sects ORDER BY name COLLATE NOCASE").fetchall()]
        for sect in sects_rows:
            sect["member_count"] = cur.execute(
                "SELECT COUNT(*) FROM players WHERE sect_id = ?", (sect["sect_id"],)
            ).fetchone()[0]
        con.close()
        sects_rows.sort(key=lambda s: -s["member_count"])
        return sects_rows

    def get_sect_members(self, sect_id: int) -> list:
        """Every member of a sect, in rank order (Sect Leader first) then by join date --
        see sects.SECT_RANKS for the rank ordering used here."""
        con = self.connect()
        rows = con.execute(
            "SELECT user_id, name, sect_rank, sect_joined_ts, realm_index FROM players WHERE sect_id = ?",
            (sect_id,),
        ).fetchall()
        con.close()
        members = [dict(row) for row in rows]
        rank_order = {rank: i for i, rank in enumerate(sects.SECT_RANKS)}
        members.sort(key=lambda m: (-rank_order.get(m["sect_rank"], 0), m["sect_joined_ts"]))
        return members

    def count_sect_members(self, sect_id: int) -> int:
        con = self.connect()
        count = con.execute("SELECT COUNT(*) FROM players WHERE sect_id = ?", (sect_id,)).fetchone()[0]
        con.close()
        return count

    def count_sect_rank(self, sect_id: int, rank: str) -> int:
        con = self.connect()
        count = con.execute(
            "SELECT COUNT(*) FROM players WHERE sect_id = ? AND sect_rank = ?", (sect_id, rank)
        ).fetchone()[0]
        con.close()
        return count

    def set_player_sect(self, user_id: int, sect_id: Optional[int], rank: Optional[str]):
        con = self.connect()
        con.execute(
            "UPDATE players SET sect_id = ?, sect_rank = ?, sect_joined_ts = ? WHERE user_id = ?",
            (sect_id, rank, int(time.time()) if sect_id else 0, user_id),
        )
        con.commit()
        con.close()

    def set_sect_rank(self, user_id: int, rank: str):
        con = self.connect()
        con.execute("UPDATE players SET sect_rank = ? WHERE user_id = ?", (rank, user_id))
        con.commit()
        con.close()

    def set_sect_leader(self, sect_id: int, new_leader_id: int):
        con = self.connect()
        con.execute("UPDATE sects SET leader_id = ? WHERE sect_id = ?", (new_leader_id, sect_id))
        con.commit()
        con.close()

    def set_sect_motto(self, sect_id: int, motto: str):
        con = self.connect()
        con.execute("UPDATE sects SET motto = ? WHERE sect_id = ?", (motto, sect_id))
        con.commit()
        con.close()

    def set_sect_banner(self, sect_id: int, banner: str):
        con = self.connect()
        con.execute("UPDATE sects SET banner = ? WHERE sect_id = ?", (banner, sect_id))
        con.commit()
        con.close()

    def rename_sect(self, sect_id: int, new_name: str) -> bool:
        """False (no-op) if new_name is already taken by another sect."""
        con = self.connect()
        cur = con.cursor()
        try:
            cur.execute("UPDATE sects SET name = ? WHERE sect_id = ?", (new_name, sect_id))
        except sqlite3.IntegrityError:
            con.close()
            return False
        con.commit()
        con.close()
        return True

    def delete_sect(self, sect_id: int):
        """Disbands a sect outright -- only ever called once its last member has left (see
        GameManager.sect_leave), so there's nobody left whose sect_id/sect_rank needs
        clearing here."""
        con = self.connect()
        con.execute("DELETE FROM sects WHERE sect_id = ?", (sect_id,))
        con.commit()
        con.close()

    # -- Sect join applications (see sect_applications table docstring in setup()) -----------

    def create_sect_application(self, sect_id: int, applicant_id: int, applicant_name: str) -> int:
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "INSERT INTO sect_applications (sect_id, applicant_id, applicant_name, created_ts) VALUES (?, ?, ?, ?)",
            (sect_id, applicant_id, applicant_name, int(time.time())),
        )
        con.commit()
        application_id = cur.lastrowid
        con.close()
        return application_id

    def get_sect_application(self, application_id: int) -> Optional[dict]:
        con = self.connect()
        row = con.execute("SELECT * FROM sect_applications WHERE application_id = ?", (application_id,)).fetchone()
        con.close()
        return dict(row) if row else None

    def get_pending_application_for_player(self, applicant_id: int) -> Optional[dict]:
        """A player may only have one open application at a time -- see GameManager.sect_join."""
        con = self.connect()
        row = con.execute(
            "SELECT * FROM sect_applications WHERE applicant_id = ? AND status = 'pending'", (applicant_id,)
        ).fetchone()
        con.close()
        return dict(row) if row else None

    def get_pending_applications_for_sect(self, sect_id: int) -> list:
        con = self.connect()
        rows = con.execute(
            "SELECT * FROM sect_applications WHERE sect_id = ? AND status = 'pending' ORDER BY created_ts", (sect_id,)
        ).fetchall()
        con.close()
        return [dict(row) for row in rows]

    def set_application_status(self, application_id: int, status: str, resolved_by_name: str):
        con = self.connect()
        con.execute(
            "UPDATE sect_applications SET status = ?, resolved_ts = ?, resolved_by_name = ? WHERE application_id = ?",
            (status, int(time.time()), resolved_by_name, application_id),
        )
        con.commit()
        con.close()

    def delete_pending_applications_for_sect(self, sect_id: int):
        """Called when a sect disbands (see GameManager.sect_leave) so no application is left
        pointing at a sect_id that no longer exists."""
        con = self.connect()
        con.execute("DELETE FROM sect_applications WHERE sect_id = ? AND status = 'pending'", (sect_id,))
        con.commit()
        con.close()

    def add_sect_treasury(self, sect_id: int, amount: int):
        con = self.connect()
        con.execute(
            "UPDATE sects SET treasury_spirit_stones = treasury_spirit_stones + ? WHERE sect_id = ?",
            (amount, sect_id),
        )
        con.commit()
        con.close()

    def spend_sect_treasury(self, sect_id: int, amount: int) -> bool:
        """Atomic: only deducts if the treasury can actually afford it. Returns whether it
        happened -- mirrors spend_spirit_stones' own atomic pattern above."""
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "UPDATE sects SET treasury_spirit_stones = treasury_spirit_stones - ? "
            "WHERE sect_id = ? AND treasury_spirit_stones >= ?",
            (amount, sect_id, amount),
        )
        con.commit()
        success = cur.rowcount > 0
        con.close()
        return success

    # -- Mentor/disciple (see sects.py's mentor section / GameManager's sect_* mentor
    # methods / /accept_disciple, /teach) -------------------------------------------------

    def set_master(self, disciple_id: int, master_id: Optional[int]):
        """Setting a real master_id always resets master_since_ts/times_taught_by_master to a
        fresh start (now/0) -- switching masters (or being released and later re-accepted,
        even by the same master) begins a new relationship, not a continuation of the old
        one's count/date. Clearing (master_id=None) resets both back to NULL/0 too, so a
        released disciple doesn't carry stale numbers into whatever comes next."""
        con = self.connect()
        if master_id is not None:
            con.execute(
                "UPDATE players SET master_id = ?, master_since_ts = ?, times_taught_by_master = 0 WHERE user_id = ?",
                (master_id, int(time.time()), disciple_id),
            )
        else:
            con.execute(
                "UPDATE players SET master_id = NULL, master_since_ts = NULL, times_taught_by_master = 0 WHERE user_id = ?",
                (disciple_id,),
            )
        con.commit()
        con.close()

    def increment_times_taught_by_master(self, disciple_id: int):
        con = self.connect()
        con.execute("UPDATE players SET times_taught_by_master = times_taught_by_master + 1 WHERE user_id = ?", (disciple_id,))
        con.commit()
        con.close()

    def get_disciples(self, master_id: int) -> list:
        con = self.connect()
        rows = con.execute(
            "SELECT user_id, name, realm_index, sect_joined_ts FROM players WHERE master_id = ?", (master_id,)
        ).fetchall()
        con.close()
        return [dict(row) for row in rows]

    def count_disciples(self, master_id: int) -> int:
        con = self.connect()
        count = con.execute("SELECT COUNT(*) FROM players WHERE master_id = ?", (master_id,)).fetchone()[0]
        con.close()
        return count

    def release_all_disciples(self, master_id: int):
        """Called when a master leaves/is kicked from the sect (see GameManager.sect_leave/
        sect_kick) -- the mentor relationship can't survive the master no longer sharing a
        sect with them, per the design doc's own "Relationship remains until... Master
        leaves sect" rule."""
        con = self.connect()
        con.execute(
            "UPDATE players SET master_id = NULL, master_since_ts = NULL, times_taught_by_master = 0 WHERE master_id = ?",
            (master_id,),
        )
        con.commit()
        con.close()

    def set_last_teach_ts(self, master_id: int, ts: int):
        con = self.connect()
        con.execute("UPDATE players SET last_teach_ts = ? WHERE user_id = ?", (ts, master_id))
        con.commit()
        con.close()

    # -- Personal disciples (see sects.py's mentor section / /master_offer, /master_teach_all
    # -- an independent mentor track, no sect involved -- see this table's own comment) -----

    def set_personal_master(self, disciple_id: int, master_id: Optional[int]):
        """Personal-track sibling of set_master above -- same fresh-start-on-change semantics
        for personal_master_since_ts/personal_times_taught."""
        con = self.connect()
        if master_id is not None:
            con.execute(
                "UPDATE players SET personal_master_id = ?, personal_master_since_ts = ?, personal_times_taught = 0 WHERE user_id = ?",
                (master_id, int(time.time()), disciple_id),
            )
        else:
            con.execute(
                "UPDATE players SET personal_master_id = NULL, personal_master_since_ts = NULL, personal_times_taught = 0 WHERE user_id = ?",
                (disciple_id,),
            )
        con.commit()
        con.close()

    def increment_personal_times_taught(self, disciple_id: int):
        con = self.connect()
        con.execute("UPDATE players SET personal_times_taught = personal_times_taught + 1 WHERE user_id = ?", (disciple_id,))
        con.commit()
        con.close()

    def get_personal_disciples(self, master_id: int) -> list:
        con = self.connect()
        rows = con.execute(
            "SELECT user_id, name, realm_index, personal_last_taught_ts FROM players WHERE personal_master_id = ?",
            (master_id,),
        ).fetchall()
        con.close()
        return [dict(row) for row in rows]

    def count_personal_disciples(self, master_id: int) -> int:
        con = self.connect()
        count = con.execute("SELECT COUNT(*) FROM players WHERE personal_master_id = ?", (master_id,)).fetchone()[0]
        con.close()
        return count

    def set_last_personal_teach_ts(self, master_id: int, ts: int):
        con = self.connect()
        con.execute("UPDATE players SET last_personal_teach_ts = ? WHERE user_id = ?", (ts, master_id))
        con.commit()
        con.close()

    def set_personal_last_taught_ts(self, disciple_id: int, ts: int):
        con = self.connect()
        con.execute("UPDATE players SET personal_last_taught_ts = ? WHERE user_id = ?", (ts, disciple_id))
        con.commit()
        con.close()

    def add_item(self, user_id: int, item_name: str, quantity: int = 1):
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT id, quantity FROM inventory WHERE user_id = ? AND item_name = ?", (user_id, item_name))
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, ?)",
                (user_id, item_name, quantity),
            )
        else:
            cur.execute("UPDATE inventory SET quantity = quantity + ? WHERE id = ?", (quantity, row["id"]))
        con.commit()
        con.close()

    def remove_item(self, user_id: int, item_name: str, quantity: int = 1) -> bool:
        """Remove quantity of an item the player owns. Returns False if they don't have enough."""
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT id, quantity FROM inventory WHERE user_id = ? AND item_name = ?", (user_id, item_name))
        row = cur.fetchone()
        if row is None or row["quantity"] < quantity:
            con.close()
            return False
        remaining = row["quantity"] - quantity
        if remaining > 0:
            cur.execute("UPDATE inventory SET quantity = ? WHERE id = ?", (remaining, row["id"]))
        else:
            cur.execute("DELETE FROM inventory WHERE id = ?", (row["id"],))
        con.commit()
        con.close()
        return True

    # -- Character creation (/join) --------------------------------------

    def get_claimed_names(self, name_column: str, tier_column: str) -> set:
        """Names already taken by a confirmed character at the Unique or Godly tier, for
        uniqueness checks (see chargen.SCARCE_TIER_NAMES -- Godly only ever appears on the
        physique side, so this IN clause is a harmless no-op when called for root columns)."""
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            f"SELECT DISTINCT {name_column} AS name FROM players "
            f"WHERE {tier_column} IN ('Unique', 'Godly') AND {name_column} IS NOT NULL AND character_confirmed = 1"
        )
        names = {row["name"] for row in cur.fetchall()}
        con.close()
        return names

    def save_character_name(self, user_id: int, character_name: str):
        con = self.connect()
        con.execute("UPDATE players SET character_name = ? WHERE user_id = ?", (character_name, user_id))
        con.commit()
        con.close()

    def save_race(self, user_id: int, race: str):
        con = self.connect()
        con.execute("UPDATE players SET race = ? WHERE user_id = ?", (race, user_id))
        con.commit()
        con.close()

    def save_path(self, user_id: int, path: str):
        con = self.connect()
        con.execute("UPDATE players SET cultivation_path = ? WHERE user_id = ?", (path, user_id))
        con.commit()
        con.close()

    def save_class(self, user_id: int, class_name: str):
        con = self.connect()
        con.execute("UPDATE players SET character_class = ? WHERE user_id = ?", (class_name, user_id))
        con.commit()
        con.close()

    def get_character_class(self, user_id: int) -> Optional[str]:
        con = self.connect()
        cur = con.execute("SELECT character_class FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        con.close()
        return row["character_class"] if row else None

    def save_avatar_soul(self, user_id: int, soul_name: str):
        """Unlike save_class (a one-time pick), this is called on every soul change — see
        GameManager.choose_avatar_soul's free-first-pick/paid-reroll-after logic."""
        con = self.connect()
        con.execute("UPDATE players SET avatar_soul = ? WHERE user_id = ?", (soul_name, user_id))
        con.commit()
        con.close()

    def set_avatar_level(self, user_id: int, level: int) -> int:
        """Clamps to [1, avatar.AVATAR_MAX_LEVEL's 10] and returns the level actually stored,
        so callers never have to separately re-read it back."""
        level = max(1, min(10, level))
        con = self.connect()
        con.execute("UPDATE players SET avatar_level = ? WHERE user_id = ?", (level, user_id))
        con.commit()
        con.close()
        return level

    def get_player_realm_index(self, user_id: int) -> int:
        """Read-only realm_index lookup for callers (like compute_equipment_bonuses) that
        don't have the player's display name handy — unlike get_or_create_player, never
        touches the `name` column, so it's safe to call without a real name in hand."""
        con = self.connect()
        cur = con.execute("SELECT realm_index FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        con.close()
        return row["realm_index"] if row else 0

    def get_player_row(self, user_id: int) -> Optional[dict]:
        """Read-only full-row lookup, same "never touches `name`, safe without a real name
        in hand" reasoning as get_player_realm_index — for callers (like
        compute_equipment_bonuses, resolving a percentage-based crafted_gear bonus against
        the player's own gear-independent base stats) that need more than just one column."""
        con = self.connect()
        cur = con.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        con.close()
        return row

    # Foundation-stat pct keys a class's stat_bonuses can carry, and which column(s) each
    # one nudges — same convention chargen.compute_final_stats uses for race/root/physique/
    # path, but applied retroactively (multiplicatively, on CURRENT stats) since a character
    # confirmed before classes existed has no "base roll" left to re-bake from.
    _CLASS_STAT_PCT_COLUMNS = {
        "str_pct": ("str_stat",), "atk_pct": ("atk_stat",), "hp_pct": ("hp", "max_hp"),
        "spd_pct": ("spd_stat",), "def_pct": ("def_stat",), "qi_pct": ("qi_stat",),
    }

    def apply_class_stat_bonuses(self, user_id: int, stat_bonuses: dict):
        if not stat_bonuses:
            return
        con = self.connect()
        cur = con.cursor()
        for pct_key, value in stat_bonuses.items():
            for column in self._CLASS_STAT_PCT_COLUMNS.get(pct_key, ()):
                cur.execute(
                    f"UPDATE players SET {column} = MAX(1, ROUND({column} * (1 + ?))) WHERE user_id = ?",
                    (value, user_id),
                )
        con.commit()
        con.close()

    def reroll_root(self, user_id: int, tier: str, name: str) -> bool:
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "UPDATE players SET root_tier = ?, root_name = ?, root_rerolls_remaining = root_rerolls_remaining - 1 "
            "WHERE user_id = ? AND root_rerolls_remaining > 0",
            (tier, name, user_id),
        )
        con.commit()
        updated = cur.rowcount > 0
        con.close()
        return updated

    def reroll_physique(self, user_id: int, tier: str, name: str) -> bool:
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "UPDATE players SET physique_tier = ?, physique_name = ?, physique_rerolls_remaining = physique_rerolls_remaining - 1 "
            "WHERE user_id = ? AND physique_rerolls_remaining > 0",
            (tier, name, user_id),
        )
        con.commit()
        updated = cur.rowcount > 0
        con.close()
        return updated

    def set_root(self, user_id: int, tier: str, name: str):
        """Unlike reroll_root, doesn't touch root_rerolls_remaining — for the /shop paid reroll."""
        con = self.connect()
        con.execute("UPDATE players SET root_tier = ?, root_name = ? WHERE user_id = ?", (tier, name, user_id))
        con.commit()
        con.close()

    def set_physique(self, user_id: int, tier: str, name: str):
        """Unlike reroll_physique, doesn't touch physique_rerolls_remaining — for the /shop paid reroll."""
        con = self.connect()
        con.execute("UPDATE players SET physique_tier = ?, physique_name = ? WHERE user_id = ?", (tier, name, user_id))
        con.commit()
        con.close()

    def confirm_character(self, user_id: int, stats: dict):
        con = self.connect()
        con.execute(
            """UPDATE players SET
                character_confirmed = 1,
                str_stat = ?, atk_stat = ?, spd_stat = ?, def_stat = ?, luck_stat = ?, qi_stat = ?,
                hp = ?, max_hp = ?,
                battle_qi = ?, battle_qi_last_ts = ?
            WHERE user_id = ?""",
            (
                stats["str_stat"], stats["atk_stat"], stats["spd_stat"], stats["def_stat"], stats["luck_stat"], stats["qi_stat"],
                stats["hp"], stats["hp"],
                stats["qi_stat"], int(time.time()),
                user_id,
            ),
        )
        con.commit()
        cur = con.cursor()
        cur.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
        player = cur.fetchone()
        con.close()
        return player


    # -- Economy: converting spirit stones -> primeval essence -> qi ------

    SPIRIT_STONES_PER_ESSENCE = 2  # cost in spirit stones for 1 primeval essence
    ESSENCE_TO_QI_RATE = 10        # qi gained per 1 primeval essence consumed

    def exchange_stones_for_essence(self, user_id: int, stones_to_spend: int):
        """Spend up to stones_to_spend spirit stones on primeval essence, capped by
        both what the player can afford and remaining essence capacity. Returns
        (stones_spent, essence_gained, new_stones, new_essence, max_essence)."""
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "SELECT spirit_stones, primeval_essence, max_primeval_essence, equipped_primary_manual_id, "
            "equipped_auxiliary_manual_id FROM players WHERE user_id = ?", (user_id,),
        )
        row = cur.fetchone()
        effective_max = round(row["max_primeval_essence"] * self._essence_capacity_multiplier(cur, user_id, row))

        affordable = min(stones_to_spend, row["spirit_stones"]) // self.SPIRIT_STONES_PER_ESSENCE
        room = effective_max - row["primeval_essence"]
        essence_gained = max(0, min(affordable, room))
        stones_spent = essence_gained * self.SPIRIT_STONES_PER_ESSENCE

        new_stones = row["spirit_stones"] - stones_spent
        new_essence = row["primeval_essence"] + essence_gained
        cur.execute("UPDATE players SET spirit_stones = ?, primeval_essence = ? WHERE user_id = ?", (new_stones, new_essence, user_id))
        con.commit()
        con.close()
        return stones_spent, essence_gained, new_stones, new_essence, effective_max

    def consume_essence_for_qi(self, user_id: int, essence_to_spend: int, purity_bonus_pct: float = 0.0):
        """Spend up to essence_to_spend primeval essence for an instant qi gain.
        purity_bonus_pct (a manual's essence_purity_pct effect — see manual_view.EFFECT_LABELS)
        boosts how much qi each point of essence converts to, on top of the flat
        ESSENCE_TO_QI_RATE. Returns (essence_spent, qi_gained, new_essence, new_qi)."""
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT primeval_essence, qi FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()

        essence_spent = max(0, min(essence_to_spend, row["primeval_essence"]))
        qi_gained = essence_spent * self.ESSENCE_TO_QI_RATE * (1 + purity_bonus_pct)

        new_essence = row["primeval_essence"] - essence_spent
        new_qi = row["qi"] + qi_gained
        cur.execute("UPDATE players SET primeval_essence = ?, qi = ? WHERE user_id = ?", (new_essence, new_qi, user_id))
        con.commit()
        con.close()
        return essence_spent, qi_gained, new_essence, new_qi

    # -- Player-to-player trading ------------------------------------------

    def has_active_trade(self, user_id: int) -> bool:
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "SELECT 1 FROM trades WHERE (initiator_id = ? OR target_id = ?) AND status IN ('pending', 'active') LIMIT 1",
            (user_id, user_id),
        )
        found = cur.fetchone() is not None
        con.close()
        return found

    def create_trade(self, initiator_id: int, target_id: int, mode: str = "trade") -> int:
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "INSERT INTO trades (initiator_id, target_id, status, created_at, mode) VALUES (?, ?, 'pending', ?, ?)",
            (initiator_id, target_id, int(time.time()), mode),
        )
        con.commit()
        trade_id = cur.lastrowid
        con.close()
        return trade_id

    def get_trade(self, trade_id: int):
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))
        trade = cur.fetchone()
        con.close()
        return trade

    def get_stale_trades(self, cutoff_ts: int) -> list:
        """Every trade/gamble still 'pending' or 'active' whose created_at is older than
        cutoff_ts -- for GameManager.expire_stale_trades' timeout sweep. A trade sitting this
        old with no resolution almost always means whatever View was tracking it died (e.g. a
        bot restart/redeploy mid-negotiation), not that the players are still genuinely using
        it -- see the live incident this was built for."""
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT * FROM trades WHERE status IN ('pending', 'active') AND created_at < ?", (cutoff_ts,))
        rows = cur.fetchall()
        con.close()
        return rows

    def set_trade_status(self, trade_id: int, status: str):
        con = self.connect()
        con.execute("UPDATE trades SET status = ? WHERE id = ?", (status, trade_id))
        con.commit()
        con.close()

    def set_trade_confirmed(self, trade_id: int, user_id: int, confirmed: bool):
        trade = self.get_trade(trade_id)
        column = "initiator_confirmed" if trade["initiator_id"] == user_id else "target_confirmed"
        con = self.connect()
        con.execute(f"UPDATE trades SET {column} = ? WHERE id = ?", (1 if confirmed else 0, trade_id))
        con.commit()
        con.close()

    def reset_trade_confirmations(self, trade_id: int):
        con = self.connect()
        con.execute("UPDATE trades SET initiator_confirmed = 0, target_confirmed = 0 WHERE id = ?", (trade_id,))
        con.commit()
        con.close()

    def get_trade_offer(self, trade_id: int, user_id: int) -> dict:
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "SELECT kind, item_name, quantity, gear_id, manual_id, accessory_instance_id "
            "FROM trade_offers WHERE trade_id = ? AND user_id = ?", (trade_id, user_id),
        )
        rows = cur.fetchall()
        con.close()
        offer = {currency: 0 for currency in self.TRADE_CURRENCIES}
        offer["items"] = {}
        offer["pages"] = {}
        offer["crafted_gear"] = []
        offer["manuals"] = []
        offer["accessories"] = []
        for row in rows:
            if row["kind"] in self.TRADE_CURRENCIES:
                offer[row["kind"]] = row["quantity"]
            elif row["kind"] == "crafted_gear":
                offer["crafted_gear"].append(row["gear_id"])
            elif row["kind"] == "manual":
                offer["manuals"].append(row["manual_id"])
            elif row["kind"] == "accessory":
                offer["accessories"].append(row["accessory_instance_id"])
            elif row["kind"] == "page":
                offer["pages"][row["item_name"]] = row["quantity"]
            else:
                offer["items"][row["item_name"]] = row["quantity"]
        return offer

    def set_trade_currency(self, trade_id: int, user_id: int, currency: str, amount: int):
        """currency must be one of TRADE_CURRENCIES (see the class constant's own docstring)
        — always passed in directly from that fixed tuple, never raw user text."""
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT id FROM trade_offers WHERE trade_id = ? AND user_id = ? AND kind = ?", (trade_id, user_id, currency))
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO trade_offers (trade_id, user_id, kind, item_name, quantity) VALUES (?, ?, ?, NULL, ?)",
                (trade_id, user_id, currency, amount),
            )
        else:
            cur.execute("UPDATE trade_offers SET quantity = ? WHERE id = ?", (amount, row["id"]))
        con.commit()
        con.close()

    def add_trade_item(self, trade_id: int, user_id: int, item_name: str, quantity: int = 1):
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "SELECT id, quantity FROM trade_offers WHERE trade_id = ? AND user_id = ? AND kind = 'item' AND item_name = ?",
            (trade_id, user_id, item_name),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO trade_offers (trade_id, user_id, kind, item_name, quantity) VALUES (?, ?, 'item', ?, ?)",
                (trade_id, user_id, item_name, quantity),
            )
        else:
            cur.execute("UPDATE trade_offers SET quantity = quantity + ? WHERE id = ?", (quantity, row["id"]))
        con.commit()
        con.close()

    def add_trade_page(self, trade_id: int, user_id: int, page_id: str, quantity: int = 1):
        """Same quantity-accumulating shape as add_trade_item — a page stack is a flat
        (user_id, page_id) -> quantity row (player_pages), not a unique instance, so it
        reuses item_name/quantity rather than needing its own pointer column like
        gear_id/manual_id/accessory_instance_id do."""
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "SELECT id, quantity FROM trade_offers WHERE trade_id = ? AND user_id = ? AND kind = 'page' AND item_name = ?",
            (trade_id, user_id, page_id),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO trade_offers (trade_id, user_id, kind, item_name, quantity) VALUES (?, ?, 'page', ?, ?)",
                (trade_id, user_id, page_id, quantity),
            )
        else:
            cur.execute("UPDATE trade_offers SET quantity = quantity + ? WHERE id = ?", (quantity, row["id"]))
        con.commit()
        con.close()

    def add_trade_crafted_gear(self, trade_id: int, user_id: int, gear_id: int, item_name: str):
        """Offers a unique crafted_gear instance — unlike add_trade_item there's no quantity
        to accumulate (a gear_id can only ever be offered once), so this is a no-op if it's
        already in this side's offer rather than inserting a duplicate row."""
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "SELECT 1 FROM trade_offers WHERE trade_id = ? AND user_id = ? AND kind = 'crafted_gear' AND gear_id = ?",
            (trade_id, user_id, gear_id),
        )
        if cur.fetchone() is None:
            cur.execute(
                "INSERT INTO trade_offers (trade_id, user_id, kind, item_name, quantity, gear_id) VALUES (?, ?, 'crafted_gear', ?, 1, ?)",
                (trade_id, user_id, item_name, gear_id),
            )
        con.commit()
        con.close()

    def add_trade_manual(self, trade_id: int, user_id: int, manual_id: int, item_name: str):
        """Offers a unique assembled manual — same one-of-a-kind shape as
        add_trade_crafted_gear (a manual_id can only ever be offered once)."""
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "SELECT 1 FROM trade_offers WHERE trade_id = ? AND user_id = ? AND kind = 'manual' AND manual_id = ?",
            (trade_id, user_id, manual_id),
        )
        if cur.fetchone() is None:
            cur.execute(
                "INSERT INTO trade_offers (trade_id, user_id, kind, item_name, quantity, manual_id) VALUES (?, ?, 'manual', ?, 1, ?)",
                (trade_id, user_id, item_name, manual_id),
            )
        con.commit()
        con.close()

    def add_trade_accessory(self, trade_id: int, user_id: int, instance_id: int, item_name: str):
        """Offers a unique accessory/artifact instance — same one-of-a-kind shape as
        add_trade_crafted_gear (an instance_id can only ever be offered once)."""
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "SELECT 1 FROM trade_offers WHERE trade_id = ? AND user_id = ? AND kind = 'accessory' AND accessory_instance_id = ?",
            (trade_id, user_id, instance_id),
        )
        if cur.fetchone() is None:
            cur.execute(
                "INSERT INTO trade_offers (trade_id, user_id, kind, item_name, quantity, accessory_instance_id) VALUES (?, ?, 'accessory', ?, 1, ?)",
                (trade_id, user_id, item_name, instance_id),
            )
        con.commit()
        con.close()

    def clear_trade_offer(self, trade_id: int, user_id: int):
        con = self.connect()
        con.execute("DELETE FROM trade_offers WHERE trade_id = ? AND user_id = ?", (trade_id, user_id))
        con.commit()
        con.close()

    def delete_trade(self, trade_id: int):
        con = self.connect()
        con.execute("DELETE FROM trade_offers WHERE trade_id = ?", (trade_id,))
        con.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
        con.commit()
        con.close()

    def execute_trade(self, trade_id: int) -> bool:
        """Atomically swap both sides' offers. Returns False (making no changes) if
        either side can no longer afford what they offered."""
        con = self.connect()
        trade = con.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        initiator_id, target_id = trade["initiator_id"], trade["target_id"]

        offers = {}
        for uid in (initiator_id, target_id):
            rows = con.execute(
                "SELECT kind, item_name, quantity, gear_id, manual_id, accessory_instance_id "
                "FROM trade_offers WHERE trade_id = ? AND user_id = ?", (trade_id, uid),
            ).fetchall()
            offers[uid] = {currency: 0 for currency in self.TRADE_CURRENCIES}
            offers[uid]["items"] = {}
            offers[uid]["pages"] = {}
            offers[uid]["crafted_gear"] = []
            offers[uid]["manuals"] = []
            offers[uid]["accessories"] = []
            for row in rows:
                if row["kind"] in self.TRADE_CURRENCIES:
                    offers[uid][row["kind"]] = row["quantity"]
                elif row["kind"] == "crafted_gear":
                    offers[uid]["crafted_gear"].append(row["gear_id"])
                elif row["kind"] == "manual":
                    offers[uid]["manuals"].append(row["manual_id"])
                elif row["kind"] == "accessory":
                    offers[uid]["accessories"].append(row["accessory_instance_id"])
                elif row["kind"] == "page":
                    offers[uid]["pages"][row["item_name"]] = row["quantity"]
                else:
                    offers[uid]["items"][row["item_name"]] = row["quantity"]

        for uid in (initiator_id, target_id):
            player = con.execute(
                "SELECT spirit_stones, manual_ink, insight_dust, equipped_primary_manual_id, "
                "equipped_auxiliary_manual_id FROM players WHERE user_id = ?", (uid,),
            ).fetchone()
            for currency in self.TRADE_CURRENCIES:
                if player[currency] < offers[uid][currency]:
                    con.close()
                    return False
            for item_name, qty in offers[uid]["items"].items():
                inv_row = con.execute(
                    "SELECT quantity FROM inventory WHERE user_id = ? AND item_name = ?", (uid, item_name)
                ).fetchone()
                if inv_row is None or inv_row["quantity"] < qty:
                    con.close()
                    return False
            for page_id, qty in offers[uid]["pages"].items():
                page_row = con.execute(
                    "SELECT quantity FROM player_pages WHERE user_id = ? AND page_id = ?", (uid, page_id)
                ).fetchone()
                if page_row is None or page_row["quantity"] < qty:
                    con.close()
                    return False
            for gear_id in offers[uid]["crafted_gear"]:
                # Re-verified here, not just at offer time — the item could have been
                # dismantled, re-equipped, or (impossible under normal UI use, but cheap to
                # guard) already traded away in the time since it was added to this offer.
                gear_row = con.execute("SELECT owner_id FROM crafted_gear WHERE gear_id = ?", (gear_id,)).fetchone()
                if gear_row is None or gear_row["owner_id"] != uid:
                    con.close()
                    return False
                equipped_elsewhere = con.execute(
                    "SELECT 1 FROM equipped WHERE user_id = ? AND gear_id = ?", (uid, gear_id)
                ).fetchone()
                if equipped_elsewhere is not None:
                    con.close()
                    return False
            for manual_id in offers[uid]["manuals"]:
                # Re-verified here too — manuals equip through players.equipped_*_manual_id,
                # not the generic `equipped` table crafted_gear uses.
                manual_row = con.execute("SELECT owner_id FROM manuals WHERE manual_id = ?", (manual_id,)).fetchone()
                if manual_row is None or manual_row["owner_id"] != uid:
                    con.close()
                    return False
                if manual_id in (player["equipped_primary_manual_id"], player["equipped_auxiliary_manual_id"]):
                    con.close()
                    return False
            for instance_id in offers[uid]["accessories"]:
                accessory_row = con.execute(
                    "SELECT owner_id FROM accessory_artifact_instances WHERE instance_id = ?", (instance_id,)
                ).fetchone()
                if accessory_row is None or accessory_row["owner_id"] != uid:
                    con.close()
                    return False
                equipped_elsewhere = con.execute(
                    "SELECT 1 FROM equipped WHERE user_id = ? AND accessory_instance_id = ?", (uid, instance_id)
                ).fetchone()
                if equipped_elsewhere is not None:
                    con.close()
                    return False

        def _transfer(from_id, to_id, offer):
            # Written as static per-column queries (no interpolated column name) even
            # though `currency` only ever comes from the fixed TRADE_CURRENCIES tuple —
            # cheap to keep the SQL itself free of any dynamic identifiers at all.
            if offer["spirit_stones"] > 0:
                con.execute("UPDATE players SET spirit_stones = spirit_stones - ? WHERE user_id = ?", (offer["spirit_stones"], from_id))
                con.execute("UPDATE players SET spirit_stones = spirit_stones + ? WHERE user_id = ?", (offer["spirit_stones"], to_id))
            if offer["manual_ink"] > 0:
                con.execute("UPDATE players SET manual_ink = manual_ink - ? WHERE user_id = ?", (offer["manual_ink"], from_id))
                con.execute("UPDATE players SET manual_ink = manual_ink + ? WHERE user_id = ?", (offer["manual_ink"], to_id))
            if offer["insight_dust"] > 0:
                con.execute("UPDATE players SET insight_dust = insight_dust - ? WHERE user_id = ?", (offer["insight_dust"], from_id))
                con.execute("UPDATE players SET insight_dust = insight_dust + ? WHERE user_id = ?", (offer["insight_dust"], to_id))
            for item_name, qty in offer["items"].items():
                row = con.execute(
                    "SELECT id, quantity FROM inventory WHERE user_id = ? AND item_name = ?", (from_id, item_name)
                ).fetchone()
                remaining = row["quantity"] - qty
                if remaining > 0:
                    con.execute("UPDATE inventory SET quantity = ? WHERE id = ?", (remaining, row["id"]))
                else:
                    con.execute("DELETE FROM inventory WHERE id = ?", (row["id"],))
                existing = con.execute(
                    "SELECT id, quantity FROM inventory WHERE user_id = ? AND item_name = ?", (to_id, item_name)
                ).fetchone()
                if existing is None:
                    con.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, ?)", (to_id, item_name, qty))
                else:
                    con.execute("UPDATE inventory SET quantity = quantity + ? WHERE id = ?", (qty, existing["id"]))
            # A page stack's refinement_level/studied/discovered_hidden_line are per-stack
            # state, same as dismantle_page/remove_player_page already discard on a
            # fully-depleted stack -- a partial trade leaves the sender's own leftover stack's
            # state untouched (its row is just quantity-decremented), and the recipient's
            # stack always starts fresh, same as any other newly-acquired page copies would.
            for page_id, qty in offer["pages"].items():
                row = con.execute(
                    "SELECT id, quantity FROM player_pages WHERE user_id = ? AND page_id = ?", (from_id, page_id)
                ).fetchone()
                remaining = row["quantity"] - qty
                if remaining > 0:
                    con.execute("UPDATE player_pages SET quantity = ? WHERE id = ?", (remaining, row["id"]))
                else:
                    con.execute("DELETE FROM player_pages WHERE id = ?", (row["id"],))
                existing = con.execute(
                    "SELECT id, quantity FROM player_pages WHERE user_id = ? AND page_id = ?", (to_id, page_id)
                ).fetchone()
                if existing is None:
                    con.execute("INSERT INTO player_pages (user_id, page_id, quantity) VALUES (?, ?, ?)", (to_id, page_id, qty))
                else:
                    con.execute("UPDATE player_pages SET quantity = quantity + ? WHERE id = ?", (qty, existing["id"]))
            # A crafted_gear instance is 1-of-1 — trading it is just a straight ownership
            # handoff on its one existing row, no inventory quantity math needed. Manuals and
            # accessory/artifact instances are the exact same shape.
            for gear_id in offer["crafted_gear"]:
                con.execute("UPDATE crafted_gear SET owner_id = ? WHERE gear_id = ?", (to_id, gear_id))
            for manual_id in offer["manuals"]:
                con.execute("UPDATE manuals SET owner_id = ? WHERE manual_id = ?", (to_id, manual_id))
            for instance_id in offer["accessories"]:
                # An attuned item's attunement is personal to the OLD owner -- giving it up
                # frees the capacity it used and leaves it unattuned for whoever gets it next
                # (they attune it themselves, same as any other newly-acquired item), per
                # explicit bug report ("attune isn't giving its points back").
                inst_row = con.execute(
                    "SELECT item_id, attuned FROM accessory_artifact_instances WHERE instance_id = ?", (instance_id,)
                ).fetchone()
                if inst_row and inst_row["attuned"]:
                    affix = _accessories_data.ITEMS.get(inst_row["item_id"])
                    if affix:
                        con.execute(
                            "UPDATE players SET attunement_points_used = MAX(0, attunement_points_used - ?) WHERE user_id = ?",
                            (_accessories_data.attunement_cost(affix), from_id),
                        )
                    con.execute("UPDATE accessory_artifact_instances SET attuned = 0 WHERE instance_id = ?", (instance_id,))
                con.execute("UPDATE accessory_artifact_instances SET owner_id = ? WHERE instance_id = ?", (to_id, instance_id))

        from . import accessories_data as _accessories_data

        _transfer(initiator_id, target_id, offers[initiator_id])
        _transfer(target_id, initiator_id, offers[target_id])

        con.execute("UPDATE trades SET status = 'completed' WHERE id = ?", (trade_id,))
        con.execute("DELETE FROM trade_offers WHERE trade_id = ?", (trade_id,))
        con.commit()
        con.close()
        return True

    def execute_gamble(self, trade_id: int) -> Optional[dict]:
        """Winner-take-all sibling of execute_trade (see /gamble) -- same offer-collection
        and re-validation shape (ownership/affordability/not-equipped, re-checked here rather
        than trusted from offer time), plus one more requirement: both sides' pots must be
        non-empty (backs the Confirm-button gate in trading.py's TradeWindowView with a real
        server-side guarantee, same "never trust the UI alone" principle execute_trade already
        follows). Rolls 1-100 for each side, re-rolling both on an exact tie (~1% of rolls)
        until they differ, then hands EVERYTHING from both pots to the winner via the same
        _transfer shape execute_trade uses -- called twice, both times targeting the winner,
        so the winner's own side is just a same-id no-op and the loser's side moves over,
        with no special-casing needed for which side actually won. Returns None (making no
        changes) if either side can no longer afford/own what they offered, or either pot is
        empty; otherwise {"winner_id", "initiator_roll", "target_roll"}."""
        con = self.connect()
        trade = con.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        initiator_id, target_id = trade["initiator_id"], trade["target_id"]

        offers = {}
        for uid in (initiator_id, target_id):
            rows = con.execute(
                "SELECT kind, item_name, quantity, gear_id, manual_id, accessory_instance_id "
                "FROM trade_offers WHERE trade_id = ? AND user_id = ?", (trade_id, uid),
            ).fetchall()
            offers[uid] = {currency: 0 for currency in self.TRADE_CURRENCIES}
            offers[uid]["items"] = {}
            offers[uid]["pages"] = {}
            offers[uid]["crafted_gear"] = []
            offers[uid]["manuals"] = []
            offers[uid]["accessories"] = []
            for row in rows:
                if row["kind"] in self.TRADE_CURRENCIES:
                    offers[uid][row["kind"]] = row["quantity"]
                elif row["kind"] == "crafted_gear":
                    offers[uid]["crafted_gear"].append(row["gear_id"])
                elif row["kind"] == "manual":
                    offers[uid]["manuals"].append(row["manual_id"])
                elif row["kind"] == "accessory":
                    offers[uid]["accessories"].append(row["accessory_instance_id"])
                elif row["kind"] == "page":
                    offers[uid]["pages"][row["item_name"]] = row["quantity"]
                else:
                    offers[uid]["items"][row["item_name"]] = row["quantity"]

        for uid in (initiator_id, target_id):
            offer = offers[uid]
            is_empty = (
                all(offer[currency] == 0 for currency in self.TRADE_CURRENCIES)
                and not offer["items"] and not offer["pages"] and not offer["crafted_gear"]
                and not offer["manuals"] and not offer["accessories"]
            )
            if is_empty:
                con.close()
                return None
            player = con.execute(
                "SELECT spirit_stones, manual_ink, insight_dust, equipped_primary_manual_id, "
                "equipped_auxiliary_manual_id FROM players WHERE user_id = ?", (uid,),
            ).fetchone()
            for currency in self.TRADE_CURRENCIES:
                if player[currency] < offer[currency]:
                    con.close()
                    return None
            for item_name, qty in offer["items"].items():
                inv_row = con.execute(
                    "SELECT quantity FROM inventory WHERE user_id = ? AND item_name = ?", (uid, item_name)
                ).fetchone()
                if inv_row is None or inv_row["quantity"] < qty:
                    con.close()
                    return None
            for page_id, qty in offer["pages"].items():
                page_row = con.execute(
                    "SELECT quantity FROM player_pages WHERE user_id = ? AND page_id = ?", (uid, page_id)
                ).fetchone()
                if page_row is None or page_row["quantity"] < qty:
                    con.close()
                    return None
            for gear_id in offer["crafted_gear"]:
                gear_row = con.execute("SELECT owner_id FROM crafted_gear WHERE gear_id = ?", (gear_id,)).fetchone()
                if gear_row is None or gear_row["owner_id"] != uid:
                    con.close()
                    return None
                equipped_elsewhere = con.execute(
                    "SELECT 1 FROM equipped WHERE user_id = ? AND gear_id = ?", (uid, gear_id)
                ).fetchone()
                if equipped_elsewhere is not None:
                    con.close()
                    return None
            for manual_id in offer["manuals"]:
                manual_row = con.execute("SELECT owner_id FROM manuals WHERE manual_id = ?", (manual_id,)).fetchone()
                if manual_row is None or manual_row["owner_id"] != uid:
                    con.close()
                    return None
                if manual_id in (player["equipped_primary_manual_id"], player["equipped_auxiliary_manual_id"]):
                    con.close()
                    return None
            for instance_id in offer["accessories"]:
                accessory_row = con.execute(
                    "SELECT owner_id FROM accessory_artifact_instances WHERE instance_id = ?", (instance_id,)
                ).fetchone()
                if accessory_row is None or accessory_row["owner_id"] != uid:
                    con.close()
                    return None
                equipped_elsewhere = con.execute(
                    "SELECT 1 FROM equipped WHERE user_id = ? AND accessory_instance_id = ?", (uid, instance_id)
                ).fetchone()
                if equipped_elsewhere is not None:
                    con.close()
                    return None

        initiator_roll = random.randint(1, 100)
        target_roll = random.randint(1, 100)
        while initiator_roll == target_roll:
            initiator_roll = random.randint(1, 100)
            target_roll = random.randint(1, 100)
        winner_id = initiator_id if initiator_roll > target_roll else target_id

        def _transfer(from_id, to_id, offer):
            if offer["spirit_stones"] > 0:
                con.execute("UPDATE players SET spirit_stones = spirit_stones - ? WHERE user_id = ?", (offer["spirit_stones"], from_id))
                con.execute("UPDATE players SET spirit_stones = spirit_stones + ? WHERE user_id = ?", (offer["spirit_stones"], to_id))
            if offer["manual_ink"] > 0:
                con.execute("UPDATE players SET manual_ink = manual_ink - ? WHERE user_id = ?", (offer["manual_ink"], from_id))
                con.execute("UPDATE players SET manual_ink = manual_ink + ? WHERE user_id = ?", (offer["manual_ink"], to_id))
            if offer["insight_dust"] > 0:
                con.execute("UPDATE players SET insight_dust = insight_dust - ? WHERE user_id = ?", (offer["insight_dust"], from_id))
                con.execute("UPDATE players SET insight_dust = insight_dust + ? WHERE user_id = ?", (offer["insight_dust"], to_id))
            for item_name, qty in offer["items"].items():
                row = con.execute(
                    "SELECT id, quantity FROM inventory WHERE user_id = ? AND item_name = ?", (from_id, item_name)
                ).fetchone()
                remaining = row["quantity"] - qty
                if remaining > 0:
                    con.execute("UPDATE inventory SET quantity = ? WHERE id = ?", (remaining, row["id"]))
                else:
                    con.execute("DELETE FROM inventory WHERE id = ?", (row["id"],))
                existing = con.execute(
                    "SELECT id, quantity FROM inventory WHERE user_id = ? AND item_name = ?", (to_id, item_name)
                ).fetchone()
                if existing is None:
                    con.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, ?)", (to_id, item_name, qty))
                else:
                    con.execute("UPDATE inventory SET quantity = quantity + ? WHERE id = ?", (qty, existing["id"]))
            # Guarded on from_id != to_id -- unlike items, a fully-offered page stack's
            # refinement_level/studied/discovered_hidden_line would otherwise be lost to a
            # delete+reinsert round-trip on the winner's OWN pot (a same-id "transfer" that
            # should be a true no-op), same reasoning as the accessories guard just below.
            if from_id != to_id:
                for page_id, qty in offer["pages"].items():
                    row = con.execute(
                        "SELECT id, quantity FROM player_pages WHERE user_id = ? AND page_id = ?", (from_id, page_id)
                    ).fetchone()
                    remaining = row["quantity"] - qty
                    if remaining > 0:
                        con.execute("UPDATE player_pages SET quantity = ? WHERE id = ?", (remaining, row["id"]))
                    else:
                        con.execute("DELETE FROM player_pages WHERE id = ?", (row["id"],))
                    existing = con.execute(
                        "SELECT id, quantity FROM player_pages WHERE user_id = ? AND page_id = ?", (to_id, page_id)
                    ).fetchone()
                    if existing is None:
                        con.execute("INSERT INTO player_pages (user_id, page_id, quantity) VALUES (?, ?, ?)", (to_id, page_id, qty))
                    else:
                        con.execute("UPDATE player_pages SET quantity = quantity + ? WHERE id = ?", (qty, existing["id"]))
            for gear_id in offer["crafted_gear"]:
                con.execute("UPDATE crafted_gear SET owner_id = ? WHERE gear_id = ?", (to_id, gear_id))
            for manual_id in offer["manuals"]:
                con.execute("UPDATE manuals SET owner_id = ? WHERE manual_id = ?", (to_id, manual_id))
            for instance_id in offer["accessories"]:
                # Same refund-and-reset as execute_trade's own _transfer above, but guarded
                # on from_id != to_id -- when the winner is being "transferred" their own
                # side (a same-id no-op everywhere else), an attuned item of THEIRS must not
                # get de-attuned/refunded just because _transfer touched it.
                if from_id != to_id:
                    inst_row = con.execute(
                        "SELECT item_id, attuned FROM accessory_artifact_instances WHERE instance_id = ?", (instance_id,)
                    ).fetchone()
                    if inst_row and inst_row["attuned"]:
                        affix = _accessories_data.ITEMS.get(inst_row["item_id"])
                        if affix:
                            con.execute(
                                "UPDATE players SET attunement_points_used = MAX(0, attunement_points_used - ?) WHERE user_id = ?",
                                (_accessories_data.attunement_cost(affix), from_id),
                            )
                        con.execute("UPDATE accessory_artifact_instances SET attuned = 0 WHERE instance_id = ?", (instance_id,))
                con.execute("UPDATE accessory_artifact_instances SET owner_id = ? WHERE instance_id = ?", (to_id, instance_id))

        from . import accessories_data as _accessories_data

        _transfer(initiator_id, winner_id, offers[initiator_id])
        _transfer(target_id, winner_id, offers[target_id])

        con.execute("UPDATE trades SET status = 'completed' WHERE id = ?", (trade_id,))
        con.execute("DELETE FROM trade_offers WHERE trade_id = ?", (trade_id,))
        con.commit()
        con.close()
        return {"winner_id": winner_id, "initiator_roll": initiator_roll, "target_roll": target_roll}

    # -- Dao Companion (see game/dao_companion.py / GameManager's dao_companion_* methods /
    # /offer_companion, /companion -- the latter's Daily Burst/Break Bond buttons absorbed the
    # old standalone /dc and /break_companion commands, retired 2026-08-14) -----------------

    def create_dao_companion(self, partner_a_id: int, partner_b_id: int, formed_ts: int) -> int:
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "INSERT INTO dao_companions (partner_a_id, partner_b_id, formed_ts) VALUES (?, ?, ?)",
            (partner_a_id, partner_b_id, formed_ts),
        )
        con.commit()
        companion_id = cur.lastrowid
        con.close()
        return companion_id

    def get_dao_companion(self, user_id: int) -> Optional[dict]:
        con = self.connect()
        row = con.execute(
            "SELECT * FROM dao_companions WHERE partner_a_id = ? OR partner_b_id = ?", (user_id, user_id),
        ).fetchone()
        con.close()
        return dict(row) if row else None

    def delete_dao_companion(self, companion_id: int):
        con = self.connect()
        con.execute("DELETE FROM dao_companions WHERE id = ?", (companion_id,))
        con.commit()
        con.close()

    def record_dao_companion_burst(self, companion_id: int, qi_granted_total: float):
        con = self.connect()
        con.execute(
            "UPDATE dao_companions SET times_used = times_used + 1, total_qi_granted = total_qi_granted + ? WHERE id = ?",
            (qi_granted_total, companion_id),
        )
        con.commit()
        con.close()

    def set_dao_companion_essence_exchange_ts(self, companion_id: int, ts: int):
        con = self.connect()
        con.execute("UPDATE dao_companions SET last_essence_exchange_ts = ? WHERE id = ?", (ts, companion_id))
        con.commit()
        con.close()

    # -- Essence Exchange (see /essence_exchange, GameManager.essence_exchange_*) -----------

    def create_essence_exchange_request(self, companion_id: int, proposer_id: int, partner_id: int, created_ts: int) -> int:
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "INSERT INTO essence_exchange_requests (companion_id, proposer_id, partner_id, created_ts) VALUES (?, ?, ?, ?)",
            (companion_id, proposer_id, partner_id, created_ts),
        )
        con.commit()
        request_id = cur.lastrowid
        con.close()
        return request_id

    def get_pending_essence_exchange_for_companion(self, companion_id: int) -> Optional[dict]:
        con = self.connect()
        row = con.execute(
            "SELECT * FROM essence_exchange_requests WHERE companion_id = ? AND status = 'pending'", (companion_id,),
        ).fetchone()
        con.close()
        return dict(row) if row else None

    def get_essence_exchange_request(self, request_id: int) -> Optional[dict]:
        con = self.connect()
        row = con.execute("SELECT * FROM essence_exchange_requests WHERE id = ?", (request_id,)).fetchone()
        con.close()
        return dict(row) if row else None

    def set_essence_exchange_status(self, request_id: int, status: str):
        con = self.connect()
        con.execute("UPDATE essence_exchange_requests SET status = ? WHERE id = ?", (status, request_id))
        con.commit()
        con.close()

    def get_stale_essence_exchange_requests(self, cutoff: int) -> list:
        con = self.connect()
        rows = con.execute(
            "SELECT * FROM essence_exchange_requests WHERE status = 'pending' AND created_ts < ?", (cutoff,),
        ).fetchall()
        con.close()
        return [dict(row) for row in rows]

    # -- Equipment -----------------------------------------------------------

    def get_equipped(self, user_id: int) -> dict:
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT slot_key, item_name FROM equipped WHERE user_id = ?", (user_id,))
        rows = cur.fetchall()
        con.close()
        return {row["slot_key"]: row["item_name"] for row in rows}

    def set_equipped(self, user_id: int, slot_key: str, item_name: str):
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT 1 FROM equipped WHERE user_id = ? AND slot_key = ?", (user_id, slot_key))
        if cur.fetchone() is None:
            cur.execute(
                "INSERT INTO equipped (user_id, slot_key, item_name, gear_id, accessory_instance_id) VALUES (?, ?, ?, NULL, NULL)",
                (user_id, slot_key, item_name),
            )
        else:
            # gear_id/accessory_instance_id are reset to NULL here too — equipping an
            # ordinary catalog item over a slot that previously held a rolled crafted_gear
            # or accessory/artifact instance must stop that instance's effects from
            # counting (see compute_equipment_bonuses), not just change the display name.
            cur.execute(
                "UPDATE equipped SET item_name = ?, gear_id = NULL, accessory_instance_id = NULL WHERE user_id = ? AND slot_key = ?",
                (item_name, user_id, slot_key),
            )
        con.commit()
        con.close()

    def set_equipped_instance(self, user_id: int, slot_key: str, gear_id: int, display_name: str):
        """Like set_equipped, but for a unique crafted_gear row instead of a catalog
        EQUIPMENT name — see the crafted_gear table's docstring in setup()."""
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT 1 FROM equipped WHERE user_id = ? AND slot_key = ?", (user_id, slot_key))
        if cur.fetchone() is None:
            cur.execute("INSERT INTO equipped (user_id, slot_key, item_name, gear_id) VALUES (?, ?, ?, ?)", (user_id, slot_key, display_name, gear_id))
        else:
            cur.execute("UPDATE equipped SET item_name = ?, gear_id = ? WHERE user_id = ? AND slot_key = ?", (display_name, gear_id, user_id, slot_key))
        con.commit()
        con.close()

    def clear_equipped(self, user_id: int, slot_key: str):
        con = self.connect()
        con.execute("DELETE FROM equipped WHERE user_id = ? AND slot_key = ?", (user_id, slot_key))
        con.commit()
        con.close()

    # -- Nascent Soul Avatar's own gear slots (see game/avatar_gear.py) — a second, separate
    # equip table from `equipped` above.
    def get_avatar_equipped(self, user_id: int) -> dict:
        con = self.connect()
        cur = con.execute("SELECT slot_key, item_name FROM avatar_equipped WHERE user_id = ?", (user_id,))
        rows = cur.fetchall()
        con.close()
        return {row["slot_key"]: row["item_name"] for row in rows}

    def set_avatar_equipped(self, user_id: int, slot_key: str, item_name: str):
        """Legacy catalog path -- kept only so any surviving Phase-1 flat item can still be
        equipped/displayed. New grants always go through set_avatar_equipped_instance."""
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT 1 FROM avatar_equipped WHERE user_id = ? AND slot_key = ?", (user_id, slot_key))
        if cur.fetchone() is None:
            cur.execute(
                "INSERT INTO avatar_equipped (user_id, slot_key, item_name, instance_id) VALUES (?, ?, ?, NULL)",
                (user_id, slot_key, item_name),
            )
        else:
            cur.execute(
                "UPDATE avatar_equipped SET item_name = ?, instance_id = NULL WHERE user_id = ? AND slot_key = ?",
                (item_name, user_id, slot_key),
            )
        con.commit()
        con.close()

    def set_avatar_equipped_instance(self, user_id: int, slot_key: str, instance_id: int, display_name: str):
        """Like set_avatar_equipped, but for a rolled avatar_gear_instances row -- item_name
        is kept in sync as a display-only cache (mirrors set_equipped_instance)."""
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT 1 FROM avatar_equipped WHERE user_id = ? AND slot_key = ?", (user_id, slot_key))
        if cur.fetchone() is None:
            cur.execute(
                "INSERT INTO avatar_equipped (user_id, slot_key, item_name, instance_id) VALUES (?, ?, ?, ?)",
                (user_id, slot_key, display_name, instance_id),
            )
        else:
            cur.execute(
                "UPDATE avatar_equipped SET item_name = ?, instance_id = ? WHERE user_id = ? AND slot_key = ?",
                (display_name, instance_id, user_id, slot_key),
            )
        con.commit()
        con.close()

    def get_avatar_equipped_instance_ids(self, user_id: int) -> dict:
        """{slot_key: instance_id} for only the slots currently holding a rolled instance
        (mirrors get_equipped_accessory_ids)."""
        con = self.connect()
        rows = con.execute(
            "SELECT slot_key, instance_id FROM avatar_equipped WHERE user_id = ? AND instance_id IS NOT NULL", (user_id,)
        ).fetchall()
        con.close()
        return {row["slot_key"]: row["instance_id"] for row in rows}

    def clear_avatar_equipped(self, user_id: int, slot_key: str):
        con = self.connect()
        con.execute("DELETE FROM avatar_equipped WHERE user_id = ? AND slot_key = ?", (user_id, slot_key))
        con.commit()
        con.close()

    @staticmethod
    def _avatar_gear_instance_row_to_dict(row) -> dict:
        return {
            "instance_id": row["instance_id"], "owner_id": row["owner_id"], "slot_type": row["slot_type"],
            "tier": row["tier"], "stat_bonuses": json.loads(row["stat_bonuses"]),
            "power_score": row["power_score"], "created_ts": row["created_ts"],
        }

    def create_avatar_gear_instance(self, owner_id: int, slot_type: str, tier: int, stat_bonuses: dict, power_score: float) -> int:
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "INSERT INTO avatar_gear_instances (owner_id, slot_type, tier, stat_bonuses, power_score, created_ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (owner_id, slot_type, tier, json.dumps(stat_bonuses), power_score, int(time.time())),
        )
        con.commit()
        instance_id = cur.lastrowid
        con.close()
        return instance_id

    def get_avatar_gear_instance(self, instance_id: int) -> Optional[dict]:
        con = self.connect()
        row = con.execute("SELECT * FROM avatar_gear_instances WHERE instance_id = ?", (instance_id,)).fetchone()
        con.close()
        return self._avatar_gear_instance_row_to_dict(row) if row else None

    def get_player_avatar_gear_instances(self, owner_id: int) -> list:
        con = self.connect()
        rows = con.execute("SELECT * FROM avatar_gear_instances WHERE owner_id = ? ORDER BY instance_id", (owner_id,)).fetchall()
        con.close()
        return [self._avatar_gear_instance_row_to_dict(row) for row in rows]

    def delete_avatar_gear_instance(self, instance_id: int):
        con = self.connect()
        con.execute("DELETE FROM avatar_gear_instances WHERE instance_id = ?", (instance_id,))
        con.commit()
        con.close()

    # -- Gu Pet (see game/gu_pet.py / /gu_pet) -----------------------------------------------

    @staticmethod
    def _gu_pet_row_to_dict(row) -> dict:
        return {
            "pet_id": row["pet_id"], "owner_id": row["owner_id"], "rank": row["rank"],
            "stage": row["stage"], "species": row["species"], "path": row["path"], "mode": row["mode"],
            "name": row["name"],
            "stat_bonuses": json.loads(row["stat_bonuses"]), "fed_totals": json.loads(row["fed_totals"]),
            "growth_days_required": row["growth_days_required"], "growth_days_fed": row["growth_days_fed"],
            "feed_streak_days": row["feed_streak_days"], "last_fed_ts": row["last_fed_ts"],
            "satiety": row["satiety"], "last_satiety_update_ts": row["last_satiety_update_ts"],
            "image_path": row["image_path"], "created_ts": row["created_ts"],
        }

    def create_gu_pet(self, owner_id: int, rank: int, growth_days_required: int) -> int:
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "INSERT INTO gu_pets (owner_id, rank, growth_days_required, created_ts) VALUES (?, ?, ?, ?)",
            (owner_id, rank, growth_days_required, int(time.time())),
        )
        con.commit()
        pet_id = cur.lastrowid
        con.close()
        return pet_id

    def get_gu_pet(self, pet_id: int) -> Optional[dict]:
        con = self.connect()
        row = con.execute("SELECT * FROM gu_pets WHERE pet_id = ?", (pet_id,)).fetchone()
        con.close()
        return self._gu_pet_row_to_dict(row) if row else None

    def get_player_gu_pets(self, owner_id: int) -> list:
        con = self.connect()
        rows = con.execute("SELECT * FROM gu_pets WHERE owner_id = ? ORDER BY pet_id", (owner_id,)).fetchall()
        con.close()
        return [self._gu_pet_row_to_dict(row) for row in rows]

    # Whitelist of real gu_pets columns a caller may set -- same "column comes from a fixed
    # known-name list, never built from raw user input" guard set_timestamp_column already
    # uses for the players table, generalized here to one column-set updater instead of a
    # bespoke setter per field, since this table's many independent phases (Feed/Crystallize/
    # Satiety-settle/Mode-toggle) each touch a different subset of columns together.
    _GU_PET_UPDATABLE_COLUMNS = {
        "rank", "stage", "species", "path", "mode", "name", "stat_bonuses", "fed_totals",
        "growth_days_required", "growth_days_fed", "feed_streak_days", "last_fed_ts",
        "satiety", "last_satiety_update_ts", "image_path",
    }

    def update_gu_pet(self, pet_id: int, **fields):
        if not fields:
            return
        unknown = set(fields) - self._GU_PET_UPDATABLE_COLUMNS
        if unknown:
            raise ValueError(f"update_gu_pet: unknown column(s) {unknown}")
        set_clause = ", ".join(f"{col} = ?" for col in fields)
        values = [json.dumps(v) if col in ("stat_bonuses", "fed_totals") else v for col, v in fields.items()]
        con = self.connect()
        con.execute(f"UPDATE gu_pets SET {set_clause} WHERE pet_id = ?", (*values, pet_id))
        con.commit()
        con.close()

    def delete_gu_pet(self, pet_id: int):
        con = self.connect()
        con.execute("DELETE FROM gu_pets WHERE pet_id = ?", (pet_id,))
        con.commit()
        con.close()

    def set_active_gu_pet(self, user_id: int, pet_id: Optional[int]):
        con = self.connect()
        con.execute("UPDATE players SET active_gu_pet_id = ? WHERE user_id = ?", (pet_id, user_id))
        con.commit()
        con.close()

    def set_last_gu_pet_mode_switch_ts(self, user_id: int, ts: int):
        con = self.connect()
        con.execute("UPDATE players SET last_gu_pet_mode_switch_ts = ? WHERE user_id = ?", (ts, user_id))
        con.commit()
        con.close()

    # -- Gu Pet image cache (see game/gu_pet_images.py) --------------------------------------
    # Shared-art cache only -- Epic+ (unique-image) pets store their own path directly on
    # their gu_pets row instead, see should_generate_unique_image.

    def get_cached_gu_pet_image(self, cache_key: str) -> Optional[str]:
        con = self.connect()
        row = con.execute("SELECT image_path FROM gu_pet_image_cache WHERE cache_key = ?", (cache_key,)).fetchone()
        con.close()
        return row["image_path"] if row else None

    def set_cached_gu_pet_image(self, cache_key: str, image_path: str):
        con = self.connect()
        con.execute(
            "INSERT INTO gu_pet_image_cache (cache_key, image_path, created_ts) VALUES (?, ?, ?) "
            "ON CONFLICT(cache_key) DO UPDATE SET image_path = excluded.image_path",
            (cache_key, image_path, int(time.time())),
        )
        con.commit()
        con.close()

    def get_equipped_gear_ids(self, user_id: int) -> dict:
        """{slot_key: gear_id} for only the slots currently holding a rolled crafted_gear
        instance (see get_equipped for the display-name-keyed version of every slot)."""
        con = self.connect()
        cur = con.execute("SELECT slot_key, gear_id FROM equipped WHERE user_id = ? AND gear_id IS NOT NULL", (user_id,))
        rows = cur.fetchall()
        con.close()
        return {row["slot_key"]: row["gear_id"] for row in rows}

    # -- Crafted gear: unique rolled Weapon/Head/Body instances (see setup()'s crafted_gear
    # table docstring) ---------------------------------------------------------------------

    @staticmethod
    def _crafted_gear_row_to_dict(row) -> dict:
        return {
            "gear_id": row["gear_id"], "owner_id": row["owner_id"], "base_type": row["base_type"],
            "slot_type": row["slot_type"], "tier": row["tier"],
            "stat_bonuses": json.loads(row["stat_bonuses"]), "power_score": row["power_score"],
            "created_ts": row["created_ts"],
        }

    def create_crafted_gear(self, owner_id: int, base_type: str, slot_type: str, tier: int, stat_bonuses: dict, power_score: float) -> int:
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "INSERT INTO crafted_gear (owner_id, base_type, slot_type, tier, stat_bonuses, power_score, created_ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (owner_id, base_type, slot_type, tier, json.dumps(stat_bonuses), power_score, int(time.time())),
        )
        con.commit()
        gear_id = cur.lastrowid
        con.close()
        return gear_id

    def get_crafted_gear(self, gear_id: int) -> Optional[dict]:
        con = self.connect()
        row = con.execute("SELECT * FROM crafted_gear WHERE gear_id = ?", (gear_id,)).fetchone()
        con.close()
        return self._crafted_gear_row_to_dict(row) if row else None

    def get_player_crafted_gear(self, owner_id: int) -> list:
        con = self.connect()
        rows = con.execute("SELECT * FROM crafted_gear WHERE owner_id = ? ORDER BY gear_id", (owner_id,)).fetchall()
        con.close()
        return [self._crafted_gear_row_to_dict(row) for row in rows]

    def delete_crafted_gear(self, gear_id: int):
        con = self.connect()
        con.execute("DELETE FROM crafted_gear WHERE gear_id = ?", (gear_id,))
        con.commit()
        con.close()

    # -- Accessories/artifacts (see accessories_data.py) -----------------------------------

    @staticmethod
    def _accessory_instance_row_to_dict(row) -> dict:
        return {
            "instance_id": row["instance_id"], "owner_id": row["owner_id"], "item_id": row["item_id"],
            "attuned": bool(row["attuned"]), "bound_until": row["bound_until"],
            "refinement_level": row["refinement_level"], "charges_used": row["charges_used"],
            "charges_reset_ts": row["charges_reset_ts"], "last_activation_ts": row["last_activation_ts"],
            "state": json.loads(row["state_json"]), "created_ts": row["created_ts"],
        }

    def create_accessory_instance(self, owner_id: int, item_id: str) -> int:
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            "INSERT INTO accessory_artifact_instances (owner_id, item_id, created_ts) VALUES (?, ?, ?)",
            (owner_id, item_id, int(time.time())),
        )
        con.commit()
        instance_id = cur.lastrowid
        con.close()
        return instance_id

    def get_accessory_instance(self, instance_id: int) -> Optional[dict]:
        con = self.connect()
        row = con.execute("SELECT * FROM accessory_artifact_instances WHERE instance_id = ?", (instance_id,)).fetchone()
        con.close()
        return self._accessory_instance_row_to_dict(row) if row else None

    def get_player_accessory_instances(self, owner_id: int) -> list:
        con = self.connect()
        rows = con.execute("SELECT * FROM accessory_artifact_instances WHERE owner_id = ? ORDER BY instance_id", (owner_id,)).fetchall()
        con.close()
        return [self._accessory_instance_row_to_dict(row) for row in rows]

    def delete_accessory_instance(self, instance_id: int):
        con = self.connect()
        con.execute("DELETE FROM accessory_artifact_instances WHERE instance_id = ?", (instance_id,))
        con.commit()
        con.close()

    def set_accessory_instance_attuned(self, instance_id: int):
        con = self.connect()
        con.execute("UPDATE accessory_artifact_instances SET attuned = 1 WHERE instance_id = ?", (instance_id,))
        con.commit()
        con.close()

    def set_accessory_instance_unattuned(self, instance_id: int):
        con = self.connect()
        con.execute("UPDATE accessory_artifact_instances SET attuned = 0 WHERE instance_id = ?", (instance_id,))
        con.commit()
        con.close()

    def set_accessory_instance_activation(self, instance_id: int, ts: int):
        con = self.connect()
        con.execute("UPDATE accessory_artifact_instances SET last_activation_ts = ? WHERE instance_id = ?", (ts, instance_id))
        con.commit()
        con.close()

    def set_accessory_instance_charges(self, instance_id: int, charges_used: int, reset_ts: int):
        con = self.connect()
        con.execute(
            "UPDATE accessory_artifact_instances SET charges_used = ?, charges_reset_ts = ? WHERE instance_id = ?",
            (charges_used, reset_ts, instance_id),
        )
        con.commit()
        con.close()

    def set_accessory_instance_state(self, instance_id: int, state: dict):
        con = self.connect()
        con.execute("UPDATE accessory_artifact_instances SET state_json = ? WHERE instance_id = ?", (json.dumps(state), instance_id))
        con.commit()
        con.close()

    def set_equipped_accessory(self, user_id: int, slot_key: str, instance_id: int, display_name: str):
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT 1 FROM equipped WHERE user_id = ? AND slot_key = ?", (user_id, slot_key))
        if cur.fetchone() is None:
            cur.execute(
                "INSERT INTO equipped (user_id, slot_key, item_name, accessory_instance_id) VALUES (?, ?, ?, ?)",
                (user_id, slot_key, display_name, instance_id),
            )
        else:
            cur.execute(
                "UPDATE equipped SET item_name = ?, accessory_instance_id = ?, gear_id = NULL WHERE user_id = ? AND slot_key = ?",
                (display_name, instance_id, user_id, slot_key),
            )
        con.commit()
        con.close()

    def get_equipped_accessory_ids(self, user_id: int) -> dict:
        """{slot_key: instance_id} for only the slots currently holding an accessory/artifact
        instance — parallel to get_equipped_gear_ids for crafted_gear."""
        con = self.connect()
        cur = con.execute(
            "SELECT slot_key, accessory_instance_id FROM equipped WHERE user_id = ? AND accessory_instance_id IS NOT NULL",
            (user_id,),
        )
        rows = cur.fetchall()
        con.close()
        return {row["slot_key"]: row["accessory_instance_id"] for row in rows}

    # -- Equipment presets (see setup()'s equipment_presets table docstring) ----------------

    @staticmethod
    def _equipment_preset_row_to_dict(row) -> dict:
        return {
            "preset_key": row["preset_key"], "display_name": row["display_name"],
            "slots": json.loads(row["slots_json"]),
            "primary_manual_id": row["primary_manual_id"], "auxiliary_manual_id": row["auxiliary_manual_id"],
            "created_ts": row["created_ts"], "updated_ts": row["updated_ts"],
        }

    def save_equipment_preset(
        self, user_id: int, preset_key: str, display_name: str, slots: dict,
        primary_manual_id: Optional[int], auxiliary_manual_id: Optional[int],
    ):
        con = self.connect()
        cur = con.cursor()
        now = int(time.time())
        slots_json = json.dumps(slots)
        cur.execute("SELECT created_ts FROM equipment_presets WHERE user_id = ? AND preset_key = ?", (user_id, preset_key))
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO equipment_presets "
                "(user_id, preset_key, display_name, slots_json, primary_manual_id, auxiliary_manual_id, created_ts, updated_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, preset_key, display_name, slots_json, primary_manual_id, auxiliary_manual_id, now, now),
            )
        else:
            cur.execute(
                "UPDATE equipment_presets SET display_name = ?, slots_json = ?, primary_manual_id = ?, "
                "auxiliary_manual_id = ?, updated_ts = ? WHERE user_id = ? AND preset_key = ?",
                (display_name, slots_json, primary_manual_id, auxiliary_manual_id, now, user_id, preset_key),
            )
        con.commit()
        con.close()

    def get_equipment_preset(self, user_id: int, preset_key: str) -> Optional[dict]:
        con = self.connect()
        row = con.execute("SELECT * FROM equipment_presets WHERE user_id = ? AND preset_key = ?", (user_id, preset_key)).fetchone()
        con.close()
        return self._equipment_preset_row_to_dict(row) if row else None

    def get_equipment_presets(self, user_id: int) -> list:
        con = self.connect()
        rows = con.execute("SELECT * FROM equipment_presets WHERE user_id = ? ORDER BY created_ts", (user_id,)).fetchall()
        con.close()
        return [self._equipment_preset_row_to_dict(row) for row in rows]

    def delete_equipment_preset(self, user_id: int, preset_key: str) -> bool:
        con = self.connect()
        cur = con.cursor()
        cur.execute("DELETE FROM equipment_presets WHERE user_id = ? AND preset_key = ?", (user_id, preset_key))
        deleted = cur.rowcount > 0
        con.commit()
        con.close()
        return deleted

    def set_pending_breakthrough_boost(self, user_id: int, boost: Optional[dict]):
        con = self.connect()
        con.execute(
            "UPDATE players SET pending_breakthrough_boost = ? WHERE user_id = ?",
            (json.dumps(boost) if boost else None, user_id),
        )
        con.commit()
        con.close()

    def add_attunement_points(self, user_id: int, points: int):
        """points is usually positive (spending capacity to attune) but callers also pass a
        negative delta to refund it (see GameManager._release_attunement and this module's
        own execute_trade/execute_gamble transfer logic) -- clamped at 0 so a refund can
        never push the counter negative regardless of call order."""
        con = self.connect()
        con.execute("UPDATE players SET attunement_points_used = MAX(0, attunement_points_used + ?) WHERE user_id = ?", (points, user_id))
        con.commit()
        con.close()

    # -- Spirit Severing Dao Paths (see game/dao_paths.py) ---------------------

    def add_dao_marks(self, user_id: int, amount: int):
        con = self.connect()
        con.execute("UPDATE players SET dao_marks_banked = dao_marks_banked + ? WHERE user_id = ?", (amount, user_id))
        con.commit()
        con.close()

    def get_players_pending_dao_marks_backfill(self) -> list:
        """Every confirmed player who hasn't been through /backfill_dao_marks yet -- see
        dao_marks_backfill_applied's own column comment."""
        con = self.connect()
        rows = con.execute(
            "SELECT * FROM players WHERE character_confirmed = 1 AND dao_marks_backfill_applied = 0"
        ).fetchall()
        con.close()
        return [dict(row) for row in rows]

    def mark_dao_marks_backfill_applied(self, user_id: int):
        con = self.connect()
        con.execute("UPDATE players SET dao_marks_backfill_applied = 1 WHERE user_id = ?", (user_id,))
        con.commit()
        con.close()

    def get_dao_path_marks(self, user_id: int) -> Dict[str, int]:
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT dao_path_marks FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        con.close()
        if not row or not row["dao_path_marks"]:
            return {}
        return json.loads(row["dao_path_marks"])

    def allocate_dao_marks(self, user_id: int, path_name: str, amount: int) -> bool:
        """Atomic: moves `amount` from the banked pool into `path_name`'s invested total, only if
        the player actually has that much banked AND it doesn't push the path over
        dao_paths.DAO_MARKS_CAP_PER_PATH. Once invested, marks can never move back out or over to
        a different path — there is no corresponding "deallocate" method anywhere in this class."""
        if amount <= 0:
            return False
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT dao_marks_banked, dao_path_marks FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if not row or row["dao_marks_banked"] < amount:
            con.close()
            return False
        path_marks = json.loads(row["dao_path_marks"]) if row["dao_path_marks"] else {}
        invested = path_marks.get(path_name, 0)
        if invested + amount > dao_paths.DAO_MARKS_CAP_PER_PATH:
            con.close()
            return False
        path_marks[path_name] = invested + amount
        cur.execute(
            "UPDATE players SET dao_marks_banked = dao_marks_banked - ?, dao_path_marks = ? WHERE user_id = ?",
            (amount, json.dumps(path_marks), user_id),
        )
        con.commit()
        con.close()
        return True

    def try_use_transmute_charge(self, user_id: int, max_charges: int) -> bool:
        """Same UTC-date-string reset idiom as try_use_daily_fatal_hit_negation, except this
        tracks a use COUNT against the day (transmute_uses_today) rather than a single flag,
        since charges scale 1-5/day with marks invested in the Transformation path. Returns
        whether a charge was available and consumed."""
        today = time.strftime("%Y-%m-%d", time.gmtime())
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT transmute_uses_today, transmute_reset_date FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        uses_today = row["transmute_uses_today"] if row and row["transmute_reset_date"] == today else 0
        if uses_today >= max_charges:
            con.close()
            return False
        cur.execute(
            "UPDATE players SET transmute_uses_today = ?, transmute_reset_date = ? WHERE user_id = ?",
            (uses_today + 1, today, user_id),
        )
        con.commit()
        con.close()
        return True

    def get_transmute_uses_today(self, user_id: int) -> int:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT transmute_uses_today, transmute_reset_date FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        con.close()
        return row["transmute_uses_today"] if row and row["transmute_reset_date"] == today else 0

    # -- Professions (see game/professions.py) --------------------------------

    def start_study(self, user_id: int, profession: str) -> bool:
        """Begins studying `profession`. Returns False if something else is already being
        studied (only one profession can be in progress at a time)."""
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT studying_profession FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row and row["studying_profession"]:
            con.close()
            return False
        cur.execute(
            "UPDATE players SET studying_profession = ?, studying_started_ts = ? WHERE user_id = ?",
            (profession, int(time.time()), user_id),
        )
        con.commit()
        con.close()
        return True

    def set_timestamp_column(self, user_id: int, column: str, ts: int):
        """Sets an arbitrary INTEGER timestamp column (e.g. last_mine_ts) — column must come
        from a fixed whitelist of known column names, never built from raw user input."""
        con = self.connect()
        con.execute(f"UPDATE players SET {column} = ? WHERE user_id = ?", (ts, user_id))
        con.commit()
        con.close()

    # Every real action-gating cooldown timestamp (see manager.py's *_COOLDOWN_SECONDS /
    # sects.py's TEACH_COOLDOWN_SECONDS/PERSONAL_TEACH_COOLDOWN_SECONDS / world_regions.py's
    # REGION_CHANGE_COOLDOWN_SECONDS) — zeroing these makes _check_cooldown's remaining-time
    # math report 0 (ready) immediately, the same "clear it" trick this file's own tests use.
    # Deliberately excludes last_qi_ts/last_restore_ts (passive qi/HP regen accrual clocks,
    # not action cooldowns — zeroing those would falsely credit a huge burst of "elapsed"
    # regen instead of just clearing a gate) and search_charges_last_ts (a charge-refill
    # clock with the same accrual reasoning, not a hard on/off cooldown).
    COOLDOWN_RESET_COLUMNS = [
        "last_mine_ts", "last_gather_ts", "last_explore_ts", "last_battlefield_ts",
        "last_pvp_ts", "last_rest_ts", "last_meditate_ts", "last_manual_change_ts",
        "last_world_region_change_ts", "last_teach_ts", "last_personal_teach_ts",
        "personal_last_taught_ts", "last_world_boss_attack_ts", "treasure_hunt_last_ts",
    ]

    def reset_all_cooldowns(self, user_id: int):
        """/reset_cooldowns (admin) — clears every action cooldown a player can be gated by,
        including personal_last_taught_ts, which lives on THIS row even when it's someone
        else's personal disciple teaching them (see GameManager.personal_teach_all)."""
        con = self.connect()
        set_clause = ", ".join(f"{col} = 0" for col in self.COOLDOWN_RESET_COLUMNS)
        con.execute(f"UPDATE players SET {set_clause} WHERE user_id = ?", (user_id,))
        con.commit()
        con.close()

    def set_world_region(self, user_id: int, region_key: str):
        """/region (see world_regions.py) — Nascent-Soul-and-below instant switch (also used
        by Fixed Immortal Travel Gu's high-realm bypass): sets the player's chosen world
        region and stamps the change cooldown in one write."""
        con = self.connect()
        con.execute(
            "UPDATE players SET world_region = ?, last_world_region_change_ts = ? WHERE user_id = ?",
            (region_key, int(time.time()), user_id),
        )
        con.commit()
        con.close()

    def start_world_region_travel(self, user_id: int, destination_key: str):
        """/region (see world_regions.py) — Spirit Severing+ real travel path: stamps the
        destination and start time; world_region itself doesn't change until
        complete_world_region_travel fires (see GameManager.check_and_complete_world_region_
        travel), mirroring white_heaven's own start_white_heaven_travel."""
        con = self.connect()
        con.execute(
            "UPDATE players SET world_region_travel_destination = ?, world_region_travel_started_ts = ? WHERE user_id = ?",
            (destination_key, int(time.time()), user_id),
        )
        con.commit()
        con.close()

    def complete_world_region_travel(self, user_id: int, destination_key: str):
        """Clearing world_region_travel_destination is itself a sufficient completion guard —
        once cleared, the row no longer matches get_players_with_pending_world_region_travel's
        own WHERE clause, so a sweep can never double-complete the same trip (same reasoning
        as complete_white_heaven_travel's own docstring)."""
        con = self.connect()
        con.execute(
            "UPDATE players SET world_region = ?, world_region_travel_destination = NULL, "
            "world_region_travel_started_ts = 0, last_world_region_change_ts = ? WHERE user_id = ?",
            (destination_key, int(time.time()), user_id),
        )
        con.commit()
        con.close()

    def get_players_with_pending_world_region_travel(self) -> list:
        """Periodic sweep source (see GameManager.check_and_complete_world_region_travel),
        matching get_players_with_pending_white_heaven_travel's own shape."""
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT * FROM players WHERE world_region_travel_destination IS NOT NULL")
        rows = [dict(row) for row in cur.fetchall()]
        con.close()
        return rows

    def complete_study(self, user_id: int, rank_column: str):
        """Clears the studying state and bumps rank_column by 1. rank_column must be one of
        professions.RANK_COLUMN's values — never build it from raw user input."""
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            f"UPDATE players SET {rank_column} = {rank_column} + 1, studying_profession = NULL, studying_started_ts = 0 "
            "WHERE user_id = ?",
            (user_id,),
        )
        con.commit()
        cur.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
        player = cur.fetchone()
        con.close()
        return player

    def cancel_study(self, user_id: int):
        """/study's cancel option — clears the studying state WITHOUT bumping rank, unlike
        complete_study. All progress toward the in-progress rank is lost; the player can
        start that (or a different) profession fresh afterward."""
        con = self.connect()
        con.execute(
            "UPDATE players SET studying_profession = NULL, studying_started_ts = 0 WHERE user_id = ?",
            (user_id,),
        )
        con.commit()
        con.close()

    def get_players_currently_studying(self) -> list:
        """Every player with a profession currently being studied — used by GameManager's
        periodic auto-complete sweep (see GameCog.study_tick) to find who's crossed 100%
        progress since their last /study check-in, per explicit request that study no longer
        needs a manual re-run to actually claim the rank-up once it's done."""
        con = self.connect()
        rows = con.execute("SELECT * FROM players WHERE studying_profession IS NOT NULL").fetchall()
        con.close()
        return [dict(row) for row in rows]

    def add_profession_rank(self, user_id: int, rank_column: str, amount: int, max_rank: int) -> int:
        """/grant_profession_rank (admin) — flat +amount to rank_column, clamped at max_rank.
        Deliberately does NOT touch studying_profession/studying_started_ts at all, unlike
        complete_study, which clears those as part of a study session naturally finishing —
        an admin grant must never silently cancel unrelated in-progress study. rank_column
        must be one of professions.RANK_COLUMN's values — never built from raw user input.
        Returns the new rank index."""
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            f"UPDATE players SET {rank_column} = MIN({rank_column} + ?, ?) WHERE user_id = ?",
            (amount, max_rank, user_id),
        )
        con.commit()
        cur.execute(f"SELECT {rank_column} FROM players WHERE user_id = ?", (user_id,))
        new_rank = cur.fetchone()[rank_column]
        con.close()
        return new_rank

    # -- Nascent Soul Avatar's /split_body mission (see game/split_body.py) -----------------
    # Same single-pending-job idiom as start_study/complete_study/cancel_study above.

    def start_split_body(self, user_id: int):
        con = self.connect()
        con.execute(
            "UPDATE players SET split_body_started_ts = ?, split_body_notified = 0 WHERE user_id = ?",
            (int(time.time()), user_id),
        )
        con.commit()
        con.close()

    def clear_split_body(self, user_id: int):
        """Resets both columns to idle — called on claim (progress_split_body's own
        elapsed-time check already confirmed the mission was ready before calling this)."""
        con = self.connect()
        con.execute(
            "UPDATE players SET split_body_started_ts = 0, split_body_notified = 0 WHERE user_id = ?",
            (user_id,),
        )
        con.commit()
        con.close()

    def mark_split_body_notified(self, user_id: int):
        con = self.connect()
        con.execute("UPDATE players SET split_body_notified = 1 WHERE user_id = ?", (user_id,))
        con.commit()
        con.close()

    def get_players_with_unnotified_split_body(self) -> list:
        """Candidates only -- does NOT filter by elapsed time (that's done in Python by
        GameManager.get_ready_split_body_players, matching how every other timed mechanic in
        this codebase avoids doing time math in SQL)."""
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT * FROM players WHERE split_body_started_ts > 0 AND split_body_notified = 0")
        rows = cur.fetchall()
        con.close()
        return rows

    # -- White Heaven (see game/white_heaven.py / /white_heaven) -- a real 1h travel delay each
    # way, auto-completed by a background tick (see GameManager.check_and_complete_white_heaven_
    # travel) rather than manually claimed, since there's nothing to claim -- just a location
    # flip. Same single-pending-job idiom as split_body above.

    def start_white_heaven_travel(self, user_id: int, status: str):
        """status is 'traveling_there' or 'traveling_back' -- the direction of this trip."""
        con = self.connect()
        con.execute(
            "UPDATE players SET white_heaven_status = ?, white_heaven_travel_started_ts = ? WHERE user_id = ?",
            (status, int(time.time()), user_id),
        )
        con.commit()
        con.close()

    def complete_white_heaven_travel(self, user_id: int, status: str):
        """status is 'present' (arrival) or 'away' (return) -- called once the tick confirms
        the travel delay has elapsed. No separate "notified" guard needed the way split_body
        has one: completion itself flips white_heaven_status away from 'traveling_*', which
        already excludes the row from get_players_with_pending_white_heaven_travel's own
        WHERE clause on the very next tick -- unlike split_body, which deliberately leaves
        its "ready" state sitting there until the player manually claims it."""
        con = self.connect()
        con.execute(
            "UPDATE players SET white_heaven_status = ?, white_heaven_travel_started_ts = 0 WHERE user_id = ?",
            (status, user_id),
        )
        con.commit()
        con.close()

    def get_players_with_pending_white_heaven_travel(self) -> list:
        """Candidates only -- does NOT filter by elapsed time (done in Python by GameManager.
        check_and_complete_white_heaven_travel, matching get_players_currently_studying's own
        "let Python do time math" convention)."""
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT * FROM players WHERE white_heaven_status IN ('traveling_there', 'traveling_back')")
        rows = cur.fetchall()
        con.close()
        return rows

    # -- Black Heaven (see game/black_heaven.py / /black_heaven) -- a real 2h travel delay each
    # way, auto-completed the same way White Heaven's own travel is above. Search Black Heaven's
    # own busy-flag/cooldown pair mirrors Inheritance Ground's active/cooldown methods further
    # below (start_active_inheritance_ground_bulk et al) rather than being duplicated here.

    def start_black_heaven_travel(self, user_id: int, status: str):
        """status is 'traveling_there' or 'traveling_back' -- the direction of this trip."""
        con = self.connect()
        con.execute(
            "UPDATE players SET black_heaven_status = ?, black_heaven_travel_started_ts = ? WHERE user_id = ?",
            (status, int(time.time()), user_id),
        )
        con.commit()
        con.close()

    def complete_black_heaven_travel(self, user_id: int, status: str):
        """status is 'present' (arrival) or 'away' (return) -- same no-separate-notified-guard
        reasoning as complete_white_heaven_travel's own docstring."""
        con = self.connect()
        con.execute(
            "UPDATE players SET black_heaven_status = ?, black_heaven_travel_started_ts = 0 WHERE user_id = ?",
            (status, user_id),
        )
        con.commit()
        con.close()

    def get_players_with_pending_black_heaven_travel(self) -> list:
        """Candidates only -- elapsed-time filtering done in Python, same convention as
        get_players_with_pending_white_heaven_travel."""
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT * FROM players WHERE black_heaven_status IN ('traveling_there', 'traveling_back')")
        rows = cur.fetchall()
        con.close()
        return rows

    def start_active_black_heaven_bulk(self, user_ids: list, ts: int):
        if not user_ids:
            return
        con = self.connect()
        placeholders = ",".join("?" for _ in user_ids)
        con.execute(f"UPDATE players SET active_black_heaven_started_ts = ? WHERE user_id IN ({placeholders})", [ts, *user_ids])
        con.commit()
        con.close()

    def clear_active_black_heaven_bulk(self, user_ids: list):
        if not user_ids:
            return
        con = self.connect()
        placeholders = ",".join("?" for _ in user_ids)
        con.execute(f"UPDATE players SET active_black_heaven_started_ts = 0 WHERE user_id IN ({placeholders})", user_ids)
        con.commit()
        con.close()

    def set_black_heaven_search_cooldown_bulk(self, user_ids: list, ts: int):
        if not user_ids:
            return
        con = self.connect()
        placeholders = ",".join("?" for _ in user_ids)
        con.execute(f"UPDATE players SET last_black_heaven_search_ts = ? WHERE user_id IN ({placeholders})", [ts, *user_ids])
        con.commit()
        con.close()

    # -- Farming -----------------------------------------------------------------

    def get_farm_plots(self, user_id: int) -> dict:
        """{slot_index: {"tier": ..., "planted_ts": ...}} — only occupied slots have an entry."""
        con = self.connect()
        cur = con.execute("SELECT slot_index, tier, planted_ts FROM farm_plots WHERE user_id = ?", (user_id,))
        rows = cur.fetchall()
        con.close()
        return {row["slot_index"]: {"tier": row["tier"], "planted_ts": row["planted_ts"]} for row in rows}

    def plant_farm_plot(self, user_id: int, slot_index: int, tier: int) -> bool:
        """Plants tier into slot_index. Returns False if that slot is already occupied."""
        con = self.connect()
        cur = con.cursor()
        cur.execute("SELECT id FROM farm_plots WHERE user_id = ? AND slot_index = ?", (user_id, slot_index))
        if cur.fetchone() is not None:
            con.close()
            return False
        cur.execute(
            "INSERT INTO farm_plots (user_id, slot_index, tier, planted_ts) VALUES (?, ?, ?, ?)",
            (user_id, slot_index, tier, int(time.time())),
        )
        con.commit()
        con.close()
        return True

    def clear_farm_plot_slot(self, user_id: int, slot_index: int):
        con = self.connect()
        con.execute("DELETE FROM farm_plots WHERE user_id = ? AND slot_index = ?", (user_id, slot_index))
        con.commit()
        con.close()

    # -- Manual/Inheritance/Secret Realm/Dream Realm system -----------------------------

    def get_player_pages(self, user_id: int) -> dict:
        """{page_id: {"quantity", "refinement_level", "studied", "discovered_hidden_line"}}."""
        con = self.connect()
        rows = con.execute(
            "SELECT page_id, quantity, refinement_level, studied, discovered_hidden_line FROM player_pages WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        con.close()
        return {
            row["page_id"]: {
                "quantity": row["quantity"], "refinement_level": row["refinement_level"],
                "studied": bool(row["studied"]), "discovered_hidden_line": bool(row["discovered_hidden_line"]),
            }
            for row in rows
        }

    def add_player_page(self, user_id: int, page_id: str, quantity: int = 1):
        con = self.connect()
        cur = con.cursor()
        row = cur.execute("SELECT id, quantity FROM player_pages WHERE user_id = ? AND page_id = ?", (user_id, page_id)).fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO player_pages (user_id, page_id, quantity) VALUES (?, ?, ?)",
                (user_id, page_id, quantity),
            )
        else:
            cur.execute("UPDATE player_pages SET quantity = quantity + ? WHERE id = ?", (quantity, row["id"]))
        con.commit()
        con.close()

    def remove_player_page(self, user_id: int, page_id: str, quantity: int = 1) -> bool:
        con = self.connect()
        cur = con.cursor()
        row = cur.execute("SELECT id, quantity FROM player_pages WHERE user_id = ? AND page_id = ?", (user_id, page_id)).fetchone()
        if row is None or row["quantity"] < quantity:
            con.close()
            return False
        remaining = row["quantity"] - quantity
        if remaining > 0:
            cur.execute("UPDATE player_pages SET quantity = ? WHERE id = ?", (remaining, row["id"]))
        else:
            cur.execute("DELETE FROM player_pages WHERE id = ?", (row["id"],))
        con.commit()
        con.close()
        return True

    def set_page_studied(self, user_id: int, page_id: str):
        con = self.connect()
        con.execute("UPDATE player_pages SET studied = 1 WHERE user_id = ? AND page_id = ?", (user_id, page_id))
        con.commit()
        con.close()

    def set_page_refinement(self, user_id: int, page_id: str, refinement_level: str):
        con = self.connect()
        con.execute("UPDATE player_pages SET refinement_level = ? WHERE user_id = ? AND page_id = ?", (refinement_level, user_id, page_id))
        con.commit()
        con.close()

    def set_page_hidden_line(self, user_id: int, page_id: str):
        con = self.connect()
        con.execute("UPDATE player_pages SET discovered_hidden_line = 1 WHERE user_id = ? AND page_id = ?", (user_id, page_id))
        con.commit()
        con.close()

    @staticmethod
    def _manual_row_to_dict(row) -> dict:
        return {
            "manual_id": row["manual_id"], "owner_id": row["owner_id"], "name": row["name"],
            "rank": row["rank"], "rarity": row["rarity"], "primary_path": row["primary_path"],
            "secondary_paths": json.loads(row["secondary_paths"]), "page_ids": json.loads(row["page_ids"]),
            "coherence": row["coherence"], "coherence_band": row["coherence_band"], "stability": row["stability"],
            "comprehension": row["comprehension"], "effects": json.loads(row["effects"]), "flaws": json.loads(row["flaws"]),
            "generation_seed": row["generation_seed"], "bound": bool(row["bound"]),
            "refinement_effect_mult": row["refinement_effect_mult"],
        }

    def create_manual(self, owner_id: int, manual: dict) -> int:
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            """INSERT INTO manuals
                (owner_id, name, rank, rarity, primary_path, secondary_paths, page_ids, coherence,
                 coherence_band, stability, comprehension, effects, flaws, generation_seed, bound, created_ts,
                 refinement_effect_mult)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                owner_id, manual["name"], manual["rank"], manual["rarity"], manual["primary_path"],
                json.dumps(manual["secondary_paths"]), json.dumps(manual["page_ids"]), manual["coherence"],
                manual["coherence_band"], manual["stability"], manual.get("comprehension", 0),
                json.dumps(manual["effects"]), json.dumps(manual["flaws"]), manual["generation_seed"],
                int(manual.get("bound", False)), int(time.time()), manual.get("refinement_effect_mult", 1.0),
            ),
        )
        con.commit()
        manual_id = cur.lastrowid
        con.close()
        return manual_id

    def get_manual(self, manual_id: int) -> Optional[dict]:
        con = self.connect()
        row = con.execute("SELECT * FROM manuals WHERE manual_id = ?", (manual_id,)).fetchone()
        con.close()
        return self._manual_row_to_dict(row) if row else None

    def get_player_manuals(self, owner_id: int) -> list:
        con = self.connect()
        rows = con.execute("SELECT * FROM manuals WHERE owner_id = ? ORDER BY manual_id", (owner_id,)).fetchall()
        con.close()
        return [self._manual_row_to_dict(row) for row in rows]

    def is_manual_equipped(self, user_id: int, manual_id: int) -> bool:
        con = self.connect()
        row = con.execute(
            "SELECT 1 FROM players WHERE user_id = ? AND (equipped_primary_manual_id = ? OR equipped_auxiliary_manual_id = ?)",
            (user_id, manual_id, manual_id),
        ).fetchone()
        con.close()
        return row is not None

    def delete_manual(self, manual_id: int):
        con = self.connect()
        con.execute("DELETE FROM manuals WHERE manual_id = ?", (manual_id,))
        con.commit()
        con.close()

    def set_manual_comprehension(self, manual_id: int, comprehension: int):
        con = self.connect()
        con.execute("UPDATE manuals SET comprehension = ? WHERE manual_id = ?", (comprehension, manual_id))
        con.commit()
        con.close()

    def set_manual_bound(self, manual_id: int):
        con = self.connect()
        con.execute("UPDATE manuals SET bound = 1 WHERE manual_id = ?", (manual_id,))
        con.commit()
        con.close()

    def update_manual_fields(self, manual_id: int, **fields):
        """Generic field updater for refine/repair operations — fields must be a subset of
        the manuals table's own columns (name/coherence/coherence_band/stability/effects/
        flaws), never built from raw user input."""
        json_fields = {"secondary_paths", "page_ids", "effects", "flaws"}
        columns = ", ".join(f"{key} = ?" for key in fields)
        values = [json.dumps(value) if key in json_fields else value for key, value in fields.items()]
        con = self.connect()
        con.execute(f"UPDATE manuals SET {columns} WHERE manual_id = ?", (*values, manual_id))
        con.commit()
        con.close()

    # -- Killer Move (see game/killer_move_gen.py / /killer_move) -----------------------------

    @staticmethod
    def _killer_move_row_to_dict(row) -> dict:
        return {
            "killer_move_id": row["killer_move_id"], "owner_id": row["owner_id"], "slot": row["slot"],
            "kind": row["kind"], "name": row["name"], "move_tier": row["move_tier"],
            "primary_type": row["primary_type"], "harmony": row["harmony"], "qi_cost_pct": row["qi_cost_pct"],
            "effects": json.loads(row["effects"]), "created_ts": row["created_ts"],
        }

    def create_killer_move(self, owner_id: int, move: dict) -> int:
        # qi_cost is stored as a % of max qi_stat (killer_move_gen.QI_COST_PCT_BY_TIER), not a
        # flat number -- qi_stat keeps multiplying with every later breakthrough (same curve as
        # STR/HP/DEF/SPD), so a flat cost fixed at assembly time would quietly become trivial
        # by the time the player's realm has climbed further. The flat amount is computed fresh
        # against the player's CURRENT qi_stat at activation time instead (see
        # GameManager.use_killer_move/activate_support_killer_move).
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            """INSERT INTO killer_moves
                (owner_id, slot, kind, name, move_tier, primary_type, harmony, qi_cost_pct, effects, created_ts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                owner_id, move["slot"], move["kind"], move["name"], move["move_tier"],
                move["primary_type"], move["harmony"], move["qi_cost_pct"], json.dumps(move["effects"]),
                int(time.time()),
            ),
        )
        con.commit()
        killer_move_id = cur.lastrowid
        con.close()
        return killer_move_id

    def get_killer_move(self, killer_move_id: int) -> Optional[dict]:
        con = self.connect()
        row = con.execute("SELECT * FROM killer_moves WHERE killer_move_id = ?", (killer_move_id,)).fetchone()
        con.close()
        return self._killer_move_row_to_dict(row) if row else None

    def get_player_killer_moves(self, owner_id: int) -> list:
        con = self.connect()
        rows = con.execute("SELECT * FROM killer_moves WHERE owner_id = ? ORDER BY killer_move_id", (owner_id,)).fetchall()
        con.close()
        return [self._killer_move_row_to_dict(row) for row in rows]

    def set_equipped_killer_move(self, user_id: int, slot: str, killer_move_id: Optional[int]):
        column = "equipped_combat_killer_move_id" if slot == "combat" else "equipped_support_killer_move_id"
        con = self.connect()
        con.execute(f"UPDATE players SET {column} = ? WHERE user_id = ?", (killer_move_id, user_id))
        con.commit()
        con.close()

    # -- Search / discoveries / clues ----------------------------------------------------

    def get_search_status(self, user_id: int) -> dict:
        """Settles recharge (see GameManager.SEARCH_RECHARGE_SECONDS) and returns the
        current charge count, capped at the stored maximum."""
        con = self.connect()
        cur = con.cursor()
        row = cur.execute(
            "SELECT search_charges, search_charges_last_ts, discovery_momentum, search_focus, active_discovery_id "
            "FROM players WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        con.close()
        return dict(row) if row else None

    def set_search_charges(self, user_id: int, charges: int, last_ts: int):
        con = self.connect()
        con.execute("UPDATE players SET search_charges = ?, search_charges_last_ts = ? WHERE user_id = ?", (charges, last_ts, user_id))
        con.commit()
        con.close()

    def set_treasure_hunt_last_ts(self, user_id: int, ts: int):
        con = self.connect()
        con.execute("UPDATE players SET treasure_hunt_last_ts = ? WHERE user_id = ?", (ts, user_id))
        con.commit()
        con.close()

    def start_active_hunt(self, user_id: int, ts: int):
        con = self.connect()
        con.execute("UPDATE players SET active_hunt_started_ts = ? WHERE user_id = ?", (ts, user_id))
        con.commit()
        con.close()

    def clear_active_hunt(self, user_id: int):
        con = self.connect()
        con.execute("UPDATE players SET active_hunt_started_ts = 0 WHERE user_id = ?", (user_id,))
        con.commit()
        con.close()

    def start_active_raid(self, user_id: int, ts: int):
        con = self.connect()
        con.execute("UPDATE players SET active_raid_started_ts = ? WHERE user_id = ?", (ts, user_id))
        con.commit()
        con.close()

    def clear_active_raid_bulk(self, user_ids: list):
        """Clears active_raid_started_ts for every participant at once -- a raid is a shared
        multi-player encounter, unlike /hunt's single-player clear_active_hunt, so every
        terminal-state hook needs to release every joiner's flag together, not just one."""
        if not user_ids:
            return
        con = self.connect()
        placeholders = ",".join("?" for _ in user_ids)
        con.execute(f"UPDATE players SET active_raid_started_ts = 0 WHERE user_id IN ({placeholders})", user_ids)
        con.commit()
        con.close()

    def start_active_inheritance_ground_bulk(self, user_ids: list, ts: int):
        if not user_ids:
            return
        con = self.connect()
        placeholders = ",".join("?" for _ in user_ids)
        con.execute(f"UPDATE players SET active_inheritance_ground_started_ts = ? WHERE user_id IN ({placeholders})", [ts, *user_ids])
        con.commit()
        con.close()

    def clear_active_inheritance_ground_bulk(self, user_ids: list):
        if not user_ids:
            return
        con = self.connect()
        placeholders = ",".join("?" for _ in user_ids)
        con.execute(f"UPDATE players SET active_inheritance_ground_started_ts = 0 WHERE user_id IN ({placeholders})", user_ids)
        con.commit()
        con.close()

    def set_inheritance_ground_cooldown_bulk(self, user_ids: list, ts: int):
        if not user_ids:
            return
        con = self.connect()
        placeholders = ",".join("?" for _ in user_ids)
        con.execute(f"UPDATE players SET last_inheritance_ground_ts = ? WHERE user_id IN ({placeholders})", [ts, *user_ids])
        con.commit()
        con.close()

    def set_discovery_momentum(self, user_id: int, momentum: int):
        con = self.connect()
        con.execute("UPDATE players SET discovery_momentum = ? WHERE user_id = ?", (momentum, user_id))
        con.commit()
        con.close()

    def set_search_focus(self, user_id: int, focus: str):
        con = self.connect()
        con.execute("UPDATE players SET search_focus = ? WHERE user_id = ?", (focus, user_id))
        con.commit()
        con.close()

    def create_discovery(self, owner_id: int, discovery: dict) -> int:
        con = self.connect()
        cur = con.cursor()
        cur.execute(
            """INSERT INTO discoveries (owner_id, type, theme, rank, difficulty, seed, status, created_ts, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?)""",
            (
                owner_id, discovery["type"], discovery["theme"], discovery["rank"], discovery["difficulty"],
                discovery["seed"], int(time.time()), discovery["expires_at"],
            ),
        )
        con.commit()
        discovery_id = cur.lastrowid
        con.execute("UPDATE players SET active_discovery_id = ? WHERE user_id = ?", (discovery_id, owner_id))
        con.commit()
        con.close()
        return discovery_id

    def get_discovery(self, discovery_id: int) -> Optional[dict]:
        con = self.connect()
        row = con.execute("SELECT * FROM discoveries WHERE discovery_id = ?", (discovery_id,)).fetchone()
        con.close()
        return dict(row) if row else None

    def set_discovery_status(self, discovery_id: int, status: str):
        con = self.connect()
        con.execute("UPDATE discoveries SET status = ? WHERE discovery_id = ?", (status, discovery_id))
        con.commit()
        con.close()

    def try_enter_discovery(self, discovery_id: int) -> bool:
        """Atomically transitions status 'open' -> 'entered', returning True only for whichever
        caller actually wins the race -- see GameManager.enter_discovery's own comment. A
        single UPDATE...WHERE is atomic with respect to other writers regardless of journal
        mode, unlike a separate SELECT-then-UPDATE, which leaves a real (if small) window for
        two near-simultaneous callers to both read 'open' before either writes 'entered'."""
        con = self.connect()
        cur = con.execute("UPDATE discoveries SET status = 'entered' WHERE discovery_id = ? AND status = 'open'", (discovery_id,))
        con.commit()
        won = cur.rowcount > 0
        con.close()
        return won

    def increment_discovery_steps_completed(self, discovery_id: int):
        """Called once per real resolve_discovery_step grant — see the steps_completed
        column comment above setup()'s discoveries table for why this exists."""
        con = self.connect()
        con.execute("UPDATE discoveries SET steps_completed = steps_completed + 1 WHERE discovery_id = ?", (discovery_id,))
        con.commit()
        con.close()

    def clear_active_discovery(self, user_id: int, discovery_id: int):
        """Deletes the discovery and clears the player's pointer to it — called once it's
        resolved (entered and finished/abandoned) or expired, matching the "in-memory
        session, no history table" pattern the rest of this file uses."""
        con = self.connect()
        con.execute("DELETE FROM discoveries WHERE discovery_id = ?", (discovery_id,))
        con.execute("UPDATE players SET active_discovery_id = NULL WHERE user_id = ? AND active_discovery_id = ?", (user_id, discovery_id))
        con.commit()
        con.close()

    def get_clue_track(self, user_id: int, discovery_type: str, theme: str) -> Optional[dict]:
        con = self.connect()
        row = con.execute(
            "SELECT * FROM clue_tracks WHERE user_id = ? AND discovery_type = ? AND theme = ?",
            (user_id, discovery_type, theme),
        ).fetchone()
        con.close()
        return dict(row) if row else None

    def add_clue_fragment(self, user_id: int, discovery_type: str, theme: str, fragments_required: int, guaranteed_rank: int) -> dict:
        """Creates the track if it doesn't exist yet, then adds 1 fragment. Returns the
        resulting row as a dict."""
        con = self.connect()
        cur = con.cursor()
        row = cur.execute(
            "SELECT track_id, fragments FROM clue_tracks WHERE user_id = ? AND discovery_type = ? AND theme = ?",
            (user_id, discovery_type, theme),
        ).fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO clue_tracks (user_id, discovery_type, theme, fragments, fragments_required, guaranteed_rank) "
                "VALUES (?, ?, ?, 1, ?, ?)",
                (user_id, discovery_type, theme, fragments_required, guaranteed_rank),
            )
        else:
            cur.execute("UPDATE clue_tracks SET fragments = fragments + 1 WHERE track_id = ?", (row["track_id"],))
        con.commit()
        result = cur.execute(
            "SELECT * FROM clue_tracks WHERE user_id = ? AND discovery_type = ? AND theme = ?",
            (user_id, discovery_type, theme),
        ).fetchone()
        con.close()
        return dict(result)

    def clear_clue_track(self, track_id: int):
        con = self.connect()
        con.execute("DELETE FROM clue_tracks WHERE track_id = ?", (track_id,))
        con.commit()
        con.close()

    # -- Manual crafting currency & deviation --------------------------------------------

    def add_manual_ink(self, user_id: int, amount: int):
        con = self.connect()
        con.execute("UPDATE players SET manual_ink = manual_ink + ? WHERE user_id = ?", (amount, user_id))
        con.commit()
        con.close()

    def spend_manual_ink(self, user_id: int, amount: int) -> bool:
        con = self.connect()
        cur = con.cursor()
        cur.execute("UPDATE players SET manual_ink = manual_ink - ? WHERE user_id = ? AND manual_ink >= ?", (amount, user_id, amount))
        con.commit()
        success = cur.rowcount > 0
        con.close()
        return success

    def add_insight_dust(self, user_id: int, amount: int):
        con = self.connect()
        con.execute("UPDATE players SET insight_dust = insight_dust + ? WHERE user_id = ?", (amount, user_id))
        con.commit()
        con.close()

    def spend_insight_dust(self, user_id: int, amount: int) -> bool:
        con = self.connect()
        cur = con.cursor()
        cur.execute("UPDATE players SET insight_dust = insight_dust - ? WHERE user_id = ? AND insight_dust >= ?", (amount, user_id, amount))
        con.commit()
        success = cur.rowcount > 0
        con.close()
        return success

    def add_deviation_stress(self, user_id: int, amount: int) -> int:
        con = self.connect()
        cur = con.cursor()
        cur.execute("UPDATE players SET deviation_stress = MAX(0, MIN(100, deviation_stress + ?)) WHERE user_id = ?", (amount, user_id))
        con.commit()
        new_value = cur.execute("SELECT deviation_stress FROM players WHERE user_id = ?", (user_id,)).fetchone()["deviation_stress"]
        con.close()
        return new_value

    def set_deviation_stress(self, user_id: int, amount: int):
        con = self.connect()
        con.execute("UPDATE players SET deviation_stress = MAX(0, MIN(100, ?)) WHERE user_id = ?", (amount, user_id))
        con.commit()
        con.close()

    def set_equipped_manual(self, user_id: int, slot: str, manual_id: Optional[int]):
        """slot is 'primary' or 'auxiliary' — never built from raw user input."""
        column = "equipped_primary_manual_id" if slot == "primary" else "equipped_auxiliary_manual_id"
        con = self.connect()
        con.execute(f"UPDATE players SET {column} = ? WHERE user_id = ?", (manual_id, user_id))
        con.commit()
        con.close()
