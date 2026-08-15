import discord

from .base_view import GameView
from .database import GameDatabase
from . import world_regions


class TutorialView(GameView):
    TABS = [
        ("start", "Getting Started", "🧭"),
        ("cultivation", "Cultivation", "⚡"),
        ("combat", "Combat", "⚔️"),
        ("equipment", "Equipment & Gu", "🛡️"),
        ("economy", "Economy & Trading", "🪙"),
        ("spirit_stones", "Spirit Stones", "💰"),
        ("gathering", "Gathering", "⛏️"),
        ("professions", "Professions", "🎓"),
        ("farming", "Farming", "🌾"),
        ("manuals", "Manuals & Discoveries", "📚"),
        ("world_regions", "World Regions", "🗺️"),
        ("dao_companion", "Dao Companion", "🤝"),
        ("dao_paths", "Dao Paths", "🌀"),
        ("avatar", "Nascent Soul Avatar", "👤"),
        ("gu_pet", "Gu Pet", "🐛"),
        ("endgame_realms", "Endgame Realms", "☁️"),
        ("dungeons", "Dungeons & Trials", "🏛️"),
        ("pvp_wagers", "PvP & Wagers", "🏆"),
    ]

    def __init__(self, user_id: int, display_name: str):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.display_name = display_name
        self.active_tab = "start"
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Run `/tutorial` yourself to get your own copy of this guide!", ephemeral=True)
            return False
        return True

    def _build_components(self):
        self.clear_items()
        for index, (key, label, emoji) in enumerate(self.TABS):
            button = discord.ui.Button(label=label, emoji=emoji, row=index // 4)
            is_active = key == self.active_tab
            button.style = discord.ButtonStyle.primary if is_active else discord.ButtonStyle.secondary
            button.disabled = is_active
            button.callback = self._make_tab_callback(key)
            self.add_item(button)

    def _make_tab_callback(self, key: str):
        async def callback(interaction: discord.Interaction):
            self.active_tab = key
            self._build_components()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

        return callback

    def build_embed(self) -> discord.Embed:
        return {
            "start": self._start_embed,
            "cultivation": self._cultivation_embed,
            "combat": self._combat_embed,
            "equipment": self._equipment_embed,
            "economy": self._economy_embed,
            "spirit_stones": self._spirit_stones_embed,
            "gathering": self._gathering_embed,
            "professions": self._professions_embed,
            "farming": self._farming_embed,
            "manuals": self._manuals_embed,
            "world_regions": self._world_regions_embed,
            "dao_companion": self._dao_companion_embed,
            "dao_paths": self._dao_paths_embed,
            "avatar": self._avatar_embed,
            "gu_pet": self._gu_pet_embed,
            "endgame_realms": self._endgame_realms_embed,
            "dungeons": self._dungeons_embed,
            "pvp_wagers": self._pvp_wagers_embed,
        }[self.active_tab]()

    def _base_embed(self, title: str, emoji: str) -> discord.Embed:
        embed = discord.Embed(title=f"{emoji} {title}", color=discord.Color.dark_purple())
        embed.set_footer(text="Use /tutorial any time to bring this guide back up.")
        return embed

    def _start_embed(self) -> discord.Embed:
        embed = self._base_embed("Getting Started", "🧭")
        embed.description = (
            "Welcome to the sect! Here's how to begin:\n\n"
            "**1.** Run `/join` to create your character — pick a Race, Cultivation Path, and combat "
            "Class, and roll your Root and Physique (you get several free rerolls on each before you "
            "commit).\n"
            "**2.** Click **Confirm** once you're happy with your rolls. This locks your character in "
            "and grants a starter inventory and starter gear.\n"
            "**3.** Run `/profile` any time to see your full character sheet — it's split into tabs: "
            "Overview, Qi, Combat, Breakthrough, Buffs, Inventory, and Professions.\n\n"
            "**Tip:** every command also works as plain text — type `i <command>` (e.g. `i profile`) "
            "instead of using the `/` picker if that's easier. Most also have a short alias — "
            "`i h`/`i m`/`i g`/`i r`/`i pv` for hunt/mine/gather/raid/pvp, `i c`/`i b`/`i f` for "
            "cultivate/breakthrough/farm, and more.\n\n"
            "Use the buttons below to learn about each system in more depth."
        )
        return embed

    def _cultivation_embed(self) -> discord.Embed:
        embed = self._base_embed("Cultivation", "⚡")
        embed.description = (
            "Qi is your core cultivation currency — the more you bank, the closer you are to your "
            "next realm.\n\n"
            "• `/cultivate` — circulate your Qi to gain some, based on your Aptitude (0-100, rolled once "
            "at creation) and your Qi Multiplier (boosted by pills and buffs).\n"
            "• `/qi` — see your exact accrual rate, active buffs, and an estimated time to your next "
            "breakthrough.\n"
            "• `/breakthrough` — once you have enough Qi, attempt to advance to the next realm. Success "
            "scales your stats up significantly; failure still spends the Qi, so build a buffer before "
            "attempting.\n"
            "• Qi keeps accruing passively in real time, even while you're offline — `/cultivate` and "
            "`/qi` just bank and report what's built up since you last checked.\n"
            "• `/meditate` — a quick, no-cost boost: some HP, some primeval essence, and a bit of qi "
            "all at once (30m cooldown)."
        )
        return embed

    def _combat_embed(self) -> discord.Embed:
        embed = self._base_embed("Combat", "⚔️")
        embed.description = (
            "• `/hunt` — a solo fight against a wild beast. Attack, Guard, Flee, Empower (spend Battle "
            "Qi to guarantee your next hit or fully block the next attack), use your equipped Gu's "
            "active ability, or drink a potion mid-fight.\n"
            "• `/raid` — a tougher boss plus two mini-bosses, built for a group. Anyone can Join at any "
            "time while it's live; each round everyone picks a target and an action at once, then it "
            "all resolves together. AFK too long and you'll auto-attack the boss and lose reward "
            "chance, so stay engaged!\n"
            "• Both take an optional **realm** — pick which of the 7 Great Realms of beast/boss to "
            "fight (defaults to your own realm if you don't specify one).\n"
            "• `/pvp` — duel an AI-controlled opponent built from another cultivator's stats (30m "
            "cooldown). If anyone else has searched for a duel recently, you'll face a snapshot of "
            "their real build; otherwise you get a random cultivator's clone. The opponent mostly "
            "attacks, occasionally braces instead — win for a nominal spirit stone reward. It's purely "
            "for fun: your HP is fully restored the moment the duel ends, win, lose, or flee.\n"
            "• HP and Battle Qi both regenerate slowly in real time between fights — no need to fully "
            "rest before your next hunt.\n"
            "• `/rest` — top off your HP faster and pick up a few spirit stones while you're at it "
            "(30m cooldown).\n\n"
            "**Classes** (chosen once, at `/join` — or `/choose_class` if your character predates this):\n"
            "🛡️ **Tank** — +20% HP/+15% DEF passively. In a raid, **Defend Ally** redirects a chosen "
            "ally's incoming hits onto you this round, at a discount.\n"
            "💚 **Support** — no passive, but **Inspire** buffs the whole party's STR and DEF for a few "
            "rounds (costs your attack that round).\n"
            "❄️ **Frostbinder** — permanently heals 15% of damage dealt. **Freeze** hits for less but "
            "has a chance to make the target skip its next attack.\n"
            "Each class's ability lives behind the **Class Ability** button in both `/hunt` and "
            "`/raid` — solo in a hunt, Tank's ability becomes a self-only Brace and Support's "
            "Inspire just buffs you."
        )
        return embed

    def _equipment_embed(self) -> discord.Embed:
        embed = self._base_embed("Equipment & Gu", "🛡️")
        embed.description = (
            "• `/equipment` — equip or unequip gear across 13 slots (Head, Body, Weapon, 2x Ring, "
            "2x Earring, Necklace, Bracelet, Primary + Support Artifact, Manual, and Gu Ability).\n"
            "• Gu are special: beyond your 3 starter Gu, tiered Gu drop from hunts/raids starting at "
            "**Common** quality. Collect 2 copies of the same Gu at the same quality and run "
            "`/upgrade_gu` to fuse them into 1 copy at the next quality up (Common → Uncommon → Rare → "
            "Epic → Legendary → Mythic → Immortal) — or break any Gu you don't want down for spirit "
            "stones instead, right from the same command.\n"
            "• `/gu` — a quick read-only list of every Gu you own, its quality, and what its effect "
            "actually does, without opening `/equipment`.\n"
            "• `/killer_move` — assemble your equipped core Gu plus 10 more owned Gu into one "
            "procedurally-generated Killer Move: a powerful extra move usable in `/hunt` and `/raid`, "
            "additive alongside your normal Gu Ability, not a replacement for it.\n"
            "• `/blacksmith` — forge a Sword, Helm, or Armor piece (Tier 1-7) from ore, beast material, "
            "and a beast core of the same tier, all from `/mine` and hunting/raiding.\n"
            "• `/weapons` — lists every weapon, head, and body piece you've forged or found, with its "
            "rolled stats, and lets you dismantle ones you don't want for materials back.\n"
            "• `/accessories` — Rings, Earrings, Necklaces, Bracelets, and Artifacts drop from hunts, "
            "raids, and `/search` discoveries. Legendary+ items need **Attune** before they can be "
            "equipped (2 attunement points total — Legendary/Mythic cost 1, Rank 6-7 Unique cost 2). "
            "Some have a manual **Activate** — a daily/weekly effect like restoring essence or boosting "
            "your next breakthrough; others (shields, extra loot rolls, death wards) trigger "
            "automatically. Salvage ones you don't want for spirit stones.\n"
            "• You can also check your full loadout from the **Equipment** tab inside `/inventory`."
        )
        return embed

    def _economy_embed(self) -> discord.Embed:
        embed = self._base_embed("Economy & Trading", "🪙")
        embed.description = (
            "• Spirit Stones are the main currency — earned from hunts, raids, exploring, and PvP wins. "
            "See the **Spirit Stones** tab for how to turn them into cultivation progress.\n"
            "• `/shop` — spend spirit stones to reroll your Root or Physique. You'll see the new roll "
            "before committing anything — keep your old one or take the new one, your choice.\n"
            "• `/premium` — the same Root/Physique rerolls, but automated: pick a target tier and it "
            "keeps rolling on its own until it hits that tier (or better) or you run out of spirit stones.\n"
            "• `/trade` — offer another player items and/or spirit stones; both sides have to confirm "
            "before anything actually changes hands.\n"
            "• `/leaderboard` — see the top cultivators by realm, spirit stones, and combat power. "
            "Works even before you've made a character."
        )
        return embed

    def _spirit_stones_embed(self) -> discord.Embed:
        embed = self._base_embed("Spirit Stones", "💰")
        stones_per_essence = GameDatabase.SPIRIT_STONES_PER_ESSENCE
        qi_per_essence = GameDatabase.ESSENCE_TO_QI_RATE
        embed.description = (
            "Spirit Stones are what you'll earn the most of — from hunts, raids, exploring, and PvP "
            "wins. Left alone they're just currency, but you can convert a stockpile straight into "
            "cultivation progress in two steps:\n\n"
            f"**1.** `/exchange_essence <amount>` — convert Spirit Stones into Primeval Essence "
            f"({stones_per_essence} Spirit Stones = 1 Primeval Essence).\n"
            f"**2.** `/absorb_essence <amount>` — burn Primeval Essence for an instant burst of Qi "
            f"({qi_per_essence} Qi per Primeval Essence).\n\n"
            "So the full pipeline is:\n"
            "**Spirit Stones → `/exchange_essence` → Primeval Essence → `/absorb_essence` → Qi**\n\n"
            "• Check your current Spirit Stones and Primeval Essence any time on `/profile`'s Overview "
            "tab.\n"
            "• `/shop` and `/trade` are other things worth spending Spirit Stones on — see the "
            "**Economy & Trading** tab."
        )
        return embed

    def _gathering_embed(self) -> discord.Embed:
        embed = self._base_embed("Gathering", "⛏️")
        embed.description = (
            "• `/mine` — opens a 5-node ore vein (Tier 1-7 per node — the higher tiers are much "
            "rarer). Strike each node one at a time, or Leave Early to bank what you've struck so "
            "far. Feed the ore into `/blacksmith` along with beast material/cores from hunting and "
            "raiding.\n"
            "• `/gather` — same idea, a 5-node herb patch (Tier 1-7 per node). Forage each node one "
            "at a time, or Leave Early to bank what you've foraged so far. Feed the herbs into "
            "`/alchemy` to brew pills, or into `/farm` to grow more.\n"
            "• `/explore` — scavenge for a random reward: common scraps almost every time, up to an "
            "extremely rare jackpot (100,000 spirit stones, a Mythic-quality Gu, or the one Legendary "
            "weapon in the game).\n"
            "• All three share a **15 minute cooldown each**, tracked independently — check them all at "
            "once with `/cd`.\n"
            "• Your **Luck** stat quietly improves the odds on all three, on top of your profession rank."
        )
        return embed

    def _professions_embed(self) -> discord.Embed:
        embed = self._base_embed("Professions", "🎓")
        embed.description = (
            "Seven professions — Miner, Gatherer, Alchemist, Blacksmith, Gu Refiner, Explorer, Farmer — "
            "each climb the same 8-rank ladder: Novice → Apprentice → Adept → Expert → Master → "
            "Grandmaster → Heavenly Master → Dao Master.\n\n"
            "• `/study` — shows your current level in all 7 professions with a button for each; click "
            "one to start studying it (only one at a time). Come back once the timer's up and click it "
            "again to complete the level-up. Early ranks take about an hour; the highest ranks take weeks.\n"
            "• Miner/Gatherer/Farmer rank boosts gathering/harvest yield; Explorer rank improves "
            "`/explore` odds; Alchemist and Blacksmith rank boost your `/alchemy` and `/blacksmith` "
            "success chance.\n"
            "• Check `/profile`'s Professions tab, or `/cd`, for your current study progress.\n"
            "• Gu Refiner rank gates and boosts `/gu_pet`'s Refine action — see the **Gu Pet** tab."
        )
        return embed

    def _farming_embed(self) -> discord.Embed:
        embed = self._base_embed("Farming", "🌾")
        embed.description = (
            "• `/farm` — plant a Herb you've gathered as a seed in one of your plots. It grows for a "
            "while (longer at higher tiers), then harvest it for several herbs of that same tier.\n"
            "• Your Farmer profession rank increases how much you get back per harvest.\n"
            "• You start with 1 plot and unlock 2 more per Great Realm you reach (7 realms — up to "
            "13 plots total) — `/farm` shows all your plots and lets you pick which one to act on."
        )
        return embed

    def _manuals_embed(self) -> discord.Embed:
        embed = self._base_embed("Manuals & Discoveries", "📚")
        embed.description = (
            "A slower, deeper loop alongside gathering and hunting — search for clues, then risk them "
            "on inheritances, secret realms, and dream realms for manual pages you assemble into your "
            "own cultivation manual.\n\n"
            "• `/search` — spend a charge (3 recharge per day, up to 9 stored) to search a region for "
            "loot, clues, or a rare discovery. Pick a target rarity focus if you're after something "
            "specific — it nudges the odds, never guarantees them.\n"
            "• `/search_status` — check your charges, discovery momentum (search enough with nothing "
            "special and your next one or two finds are guaranteed better), and whether you have a "
            "discovery waiting.\n"
            "• `/discovery` — enter whatever inheritance, secret realm, or dream realm you last found. "
            "Continue through its rooms one at a time for pages, Gu, gear, and materials, or Leave "
            "early to bank what you've got. Battlefields and region dream realms (see the **World "
            "Regions** tab) also open through this same command, with their own resolution instead of "
            "a room-by-room walk.\n"
            "• `/manual` — study and refine pages you've collected, assemble a Foundation + Circulation "
            "page (plus anything else) into a complete manual, then equip it as your Primary or "
            "Auxiliary manual — both slots grant its full effect, so equip two different manuals for "
            "double the bonuses. Manual pieces you don't want can be dismantled for Manual Ink and "
            "Insight Dust, spent on studying/refining/assembling more.\n"
            "• A manual's cultivation bonus stacks on top of everything else that speeds up `/cultivate` "
            "— it scales up fast at first, then tapers off past a soft cap so no single manual can "
            "dominate your whole build.\n"
            "• `/battlefield` — trigger a battlefield directly on its own **6-hour** cooldown, instead "
            "of waiting to stumble into one through `/search` or a world region — same escalating-wave "
            "fight either way."
        )
        return embed

    def _world_regions_embed(self) -> discord.Embed:
        embed = self._base_embed("World Regions", "🗺️")
        bonuses = world_regions.REGION_BONUSES
        cooldown_seconds = world_regions.REGION_CHANGE_COOLDOWN_SECONDS
        cooldown_text = f"{cooldown_seconds // 3600}-hour" if cooldown_seconds % 3600 == 0 else f"{cooldown_seconds // 60}-minute"

        def pct(region_key: str, bonus_key: str) -> str:
            return f"+{round((bonuses[region_key][bonus_key] - 1) * 100)}%"

        southern = bonuses["southern_border"]
        northern = bonuses["northern_plains"]
        eastern = bonuses["eastern_sea"]
        western = bonuses["western_desert"]
        central = bonuses["central_continent"]

        travel_hours = world_regions.WORLD_REGION_TRAVEL_SECONDS // 3600
        embed.description = (
            "`/region` picks where your character stands in the world — open to every realm. "
            f"Nascent Soul and below switch instantly (a {cooldown_text} cooldown between changes); "
            f"Spirit Severing and above instead take a real **{travel_hours}-hour journey** each "
            "time you switch, so pick with intent either way. Your region quietly shapes "
            "`/mine`, `/gather`, `/explore`, `/hunt`, and `/raid`, and can turn up brand new "
            "discoveries you open through `/discovery`.\n\n"
            f"🗺️ **Southern Border** — every `/mine`, `/gather`, `/explore`, `/hunt`, and `/raid` has a "
            f"real {southern['action_discovery_chance']*100:.0f}% chance to turn up a special "
            "discovery, weighted heavily toward inheritances.\n"
            f"🐺 **Northern Plains** — `/hunt` and `/raid` spawn a {pct('northern_plains', 'monster_stat_multiplier')} "
            f"stronger monster with a +{round(northern['loot_chance_bonus_pct']*100)}% loot chance, every time.\n"
            f"🌊 **Eastern Sea** — the richest region for materials: {pct('eastern_sea', 'gather_yield_multiplier')} "
            f"`/mine`/`/gather` yield and {pct('eastern_sea', 'reward_material_multiplier')} to material "
            f"rewards. `/hunt`/`/raid` also have a {eastern['hoard_chance']*100:.0f}% chance of a "
            f"{pct('eastern_sea', 'hoard_stat_multiplier')} stronger **hoard guardian** dropping a bonus "
            "bundle of herbs, ore, or beast material.\n"
            f"🏜️ **Western Desert** — rich in trade: {pct('western_desert', 'explore_stone_multiplier')} "
            f"`/explore` spirit stones, plus {pct('western_desert', 'reward_stone_multiplier')} to spirit "
            f"stone rewards and {pct('western_desert', 'reward_ink_dust_multiplier')} to manual ink/insight "
            f"dust rewards. `/hunt`/`/raid` have a {western['hoard_chance']*100:.0f}% chance of a hoard "
            "guardian dropping a big pile of spirit stones.\n"
            f"🏯 **Central Continent** — the most refined region: {pct('central_continent', 'reward_ink_dust_multiplier')} "
            f"to manual ink/insight dust rewards, plus a real {central['reward_page_bonus_chance']*100:.0f}% chance "
            "of an extra manual page on any page reward. `/hunt`/`/raid` have a "
            f"{central['hoard_chance']*100:.0f}% chance of a hoard guardian dropping a bundle of manual pages.\n\n"
            "**Battlefields and region dream realms** are two discovery types found only this way (not "
            "through `/search`):\n"
            "⚔️ **Battlefield** — endless waves of monsters, each one tougher than the last. Attack, "
            "Guard, Empower, use a potion, or Withdraw at any point — your reward scales with how many "
            "waves you clear before falling or pulling out.\n"
            "💤 **Region Dream Realm** — a single stat check against your Speed, Attack, Defense, or "
            "Luck. Clear the threshold for a real reward; fall short for a small consolation prize."
        )
        return embed

    def _dao_companion_embed(self) -> discord.Embed:
        embed = self._base_embed("Dao Companion", "🤝")
        embed.description = (
            "A mutual peer bond between two players — unlike a sect's master/disciple hierarchy, "
            "both partners benefit equally.\n\n"
            "• `/offer_companion` — propose a bond with another player; they have to accept. You "
            "can only have one companion at a time.\n"
            "• `/companion` — see your current companion, how long you've been bonded, and the "
            "stat bonus that's giving you right now. Also has **Daily Burst** (once a day, a qi "
            "burst for BOTH of you at once) and **Break Bond** (end it any time) buttons.\n"
            "• Bonded partners each gain a slice of the OTHER's raw stats — starts at **5%**, grows "
            "**+1% per week** bonded, capped at **25%** (about 20 weeks to max out).\n"
            "• `/essence_exchange` — propose sharing **33%** of your primeval essence with your "
            "companion (and them with you in return); they have **3 hours** to accept. Once per "
            "pair, per day."
        )
        return embed

    def _dao_paths_embed(self) -> discord.Embed:
        embed = self._base_embed("Dao Paths", "🌀")
        embed.description = (
            "Spirit Severing and above unlock a 14-path skill tree, layered on top of everything "
            "else you've built.\n\n"
            "• `/dao_path` — see your Dao Marks and allocate them across the 14 paths. Each path's "
            "bonus scales linearly from nothing up to its full effect at **2,000 marks invested** "
            "— spreading thin is weaker than committing, so allocate with intent.\n"
            "• Dao Marks come in from combat/exploration activity as you play, plus a one-time "
            "bonus every time you break through to a new realm stage.\n"
            "• `/transmute` — spend a charge to convert an item into a random item of the same "
            "tier (Transformation Dao Path only). You get **1 charge/day** baseline, +1 more per "
            "**500 marks** invested in Transformation, up to **5/day**."
        )
        return embed

    def _avatar_embed(self) -> discord.Embed:
        embed = self._base_embed("Nascent Soul Avatar", "👤")
        embed.description = (
            "Nascent Soul and above can raise a second, independent body alongside your own.\n\n"
            "• `/avatar` — view your avatar's phase, level, and equipped gear; feed it Soul "
            "Nourishing Pills and Soul Crystals to level it up through its own progression, "
            "separate from your main cultivation.\n"
            "• `/split_body` — send your avatar out on its own for a real **3-hour** trip to "
            "search for loot; run the command again once it's back to claim what it found.\n"
            "• The avatar has its own gear tier system, entirely separate from your main "
            "equipment — `/sell` unloads any avatar gear you don't need for spirit stones."
        )
        return embed

    def _gu_pet_embed(self) -> discord.Embed:
        embed = self._base_embed("Gu Pet", "🐛")
        embed.description = (
            "A single-slot Gu-beast companion, grown through your own Gu Refiner profession "
            "(study it with `/study` like any other profession).\n\n"
            "• **Refine** — sacrifice **1-3 Immortal-quality Gu** (pure energy mass — its own "
            "stats never carry over; reaching Immortal already means fusing dozens of raw "
            "copies through `/upgrade_gu`) plus Soul Nourishing Pills and Soul Crystals to "
            "hatch a blank Gu Pet. You don't pick the rank — the ritual randomly rolls it "
            "(Rank I-VII), weighted toward whatever rank your own Gu Refiner rank already "
            "qualifies you for, though any rank is always possible either way. A higher Gu "
            "Refiner rank both shifts the odds toward higher-rank pets AND improves your "
            "success chance at whatever rank the roll lands on.\n"
            "• **Feed** — once a day, feed it Ore, Herb, Beast Material, Beast Core, or Pills "
            "for **7-14 days**' worth of growth — feeding a bigger stack per visit covers "
            "several days at once, so a deep stockpile can finish growth much faster. The "
            "RATIO of everything you fed decides its permanent species and Path once it's "
            "done growing — lean Ore/Herb/Pill for a Cultivation specialist, Beast "
            "Material/Core for a Combat specialist.\n"
            "• **Crystallize** — locks in its species and starts its Satiety upkeep. "
            "**Status** lets you browse every pet you own and choose which one is active — "
            "only your active pet's bonuses actually apply. **Mode** flips it between "
            "**Combat** and **Cultivation** Mode (10-minute cooldown, or pay spirit stones to "
            "switch early); a well-fed pet boosts its output, a starving one barely helps at "
            "all — refeed it from the Status tab using its own rank's material tier.\n"
            "• Rank IV+ (Epic+) pets get their own unique AI-generated portrait; lower ranks "
            "share art with other pets of the same species/Path/rank."
        )
        return embed

    def _endgame_realms_embed(self) -> discord.Embed:
        embed = self._base_embed("Endgame Realms", "☁️")
        embed.description = (
            "Two optional destinations for **Dao Seeking** and above, each reached through a real "
            "journey rather than an instant switch.\n\n"
            "☁️ **White Heaven** — `/white_heaven` (i wh) travels there and back, a real "
            "**1-hour** journey each way. While present, `/hunt`, `/raid`, `/explore`, and "
            "`/search_forgotten_blessed_land` all swap to White Heaven's own much tougher, much "
            "richer fixed content instead of your normal realm-based pools.\n"
            "☠️ **Black Heaven** — `/black_heaven` (i bh) travels there and back, a real "
            "**2-hour** journey each way — deadlier and more remote than White Heaven. `/hunt` "
            "and `/raid` behave normally there; instead run `/search_black_heaven` to pop a "
            "20-bubble board (invite up to 3 others already in Black Heaven, or go solo) for a "
            "shot at rare Gu, essence, and Rank 8 materials — some bubbles hide very dangerous "
            "guardians instead.\n"
            "• Neither region shares a cooldown or travel state with the other, or with `/region`."
        )
        return embed

    def _dungeons_embed(self) -> discord.Embed:
        embed = self._base_embed("Dungeons & Trials", "🏛️")
        embed.description = (
            "Two bubble-board minigames — pop tiles for loot, some hide danger.\n\n"
            "🏛️ **Inheritance Ground** — `/inheritance_ground` invites up to 3 others (or leave "
            "everyone blank to run solo) into a bubble board with real team battles along the "
            "way. Clear the Final Trial and every member privately chooses **Share Loot Equally** "
            "or **Backstab for the Core Gu**. Anyone backstabbing means a real fight — every "
            "backstabber alone against the sharers together. If EVERYONE shares instead, the "
            "Core Gu doesn't go to waste: the whole team rolls 1-100 and the highest roll claims "
            "it. Leader-only **4-hour** cooldown; invited teammates can go again right away.\n"
            "⛏️ **Forgotten Blessed Land** — `/search_forgotten_blessed_land` (i sfbl/sf) opens a "
            "25-tile grid; dig up to **7** tiles per board for spirit stones, materials, and rare "
            "bonus pills. Requires **Core Formation** or above, **1-hour** cooldown between boards."
        )
        return embed

    def _pvp_wagers_embed(self) -> discord.Embed:
        embed = self._base_embed("PvP & Wagers", "🏆")
        embed.description = (
            "• `/tournament` — sign up during an open signup window; once it fills or times out, "
            "every entrant is dropped into a frozen-snapshot battle royale. Top 3 get the best "
            "rewards, everyone else still gets spirit stones scaled to how far they made it.\n"
            "• `/gamble` — challenge another player to a winner-take-all dice duel: both sides put "
            "up spirit stones, roll 1-100, high roll takes the whole pot. Uses the same "
            "confirm-and-accept window as `/trade`.\n"
            "• `/pvp` (see the **Combat** tab) is the free, practice version — no stakes, full HP "
            "restored the moment it ends. `/tournament` and `/gamble` are where the real stakes are."
        )
        return embed
