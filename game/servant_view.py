"""
ServantView -- the /servant menu. Summon tab: roll for new
servants (see GameManager.summon_servant). Roster tab: browse owned instances by tier + the
collection bonus. Star Up tab: consume exact-name duplicates to advance a servant's star level
(1★→7★) via GameManager.star_up_servant. Evolve tab: once a Tier 5/6 servant is maxed at ★7, it
shows up here to transform into a fresh, randomly-rolled Tier 6/7 named identity, then displays
exactly what it became (see GameManager.evolve_servant) -- deliberately its own tab rather than a
button buried in Star Up, since the two are conceptually different actions (fuel duplicates in,
vs. a one-way identity swap out). Level tab: feed materials to advance a servant's Level,
independent of Star/duplicates, via its own separate servant picker (see GameManager.
level_up_servant). Equip tab: assign a servant to the Support or Combat slot (see
GameManager.equip_servant/unequip_servant). Automation tab: assign a servant to auto-run mining/
gathering/farming on a daily tick (see GameManager.assign_servant_duty/unassign_servant_duty).
Collected tab: read-only lifetime per-item totals gained from that automation tick (see
GameManager.get_servant_automation_totals) -- separate from `inventory` itself, so it stays a
clean record of what the automated system specifically has produced.

Tabs span 2 rows (4+4) since there are 8 of them -- Discord caps a single ActionRow at 5
buttons. Every tab's own content is squeezed into the 3 rows left (2-4), so pagination buttons
usually share a row with their tab's action button(s) rather than getting a dedicated row.
"""

import asyncio

import discord

from . import servants
from .base_view import GameView
from .equipment import SPECIAL_STAT_TEXT, FOUNDATION_STAT_LABELS
from .ui_utils import format_number, format_duration

PAGE_SIZE = 25
# Smaller than PAGE_SIZE -- Roster lines now include a stat summary per entry (see
# _roster_embed), so fewer fit per page before risking Discord's 1024-char field value cap.
ROSTER_PAGE_SIZE = 8
COLLECTED_PAGE_SIZE = 15

CURRENCY_LABELS = {
    servants.CURRENCY_STONES: "Spirit Stones",
    servants.CURRENCY_ESSENCE_CRYSTALS: "Primeval Essence Crystals",
    servants.CURRENCY_BEAST_CORES: "Beast Cores (any tier)",
}

DUTY_LABELS = {servants.DUTY_MINE: "Mine", servants.DUTY_GATHER: "Gather", servants.DUTY_FARM: "Farm"}


def _format_bonus_line(key: str, value: float) -> str:
    formatter = SPECIAL_STAT_TEXT.get(key)
    if formatter:
        return formatter(value)
    if key in FOUNDATION_STAT_LABELS:
        return f"{FOUNDATION_STAT_LABELS[key]} +{value:g}"
    return f"{key}: {value:g}"


def _instance_label(instance: dict) -> str:
    return f"{servants.TIER_EMOJI.get(instance['tier'], '')} #{instance['instance_id']} {instance['name']} (T{instance['tier']} ★{instance['star_level']} Lv{instance['level']})"


def _maybe_set_image(embed: discord.Embed, name: str):
    """Sets the embed's large image (not the small corner thumbnail) to this servant's
    image_url, if the catalog entry has one filled in."""
    servant = servants.SERVANT_CATALOG.get(name)
    if servant and servant.image_url:
        embed.set_image(url=servant.image_url)


def _stats_text(servant, star_level: int, level: int = 1, affinity_seconds: int = 0) -> str:
    bonuses = servants.scaled_stat_bonuses(servant, star_level, level, affinity_seconds)
    return ", ".join(_format_bonus_line(k, v) for k, v in bonuses.items()) or "—"


class ServantView(GameView):
    TABS = [
        ("summon", "Summon", "🎴", 0), ("roster", "Roster", "📜", 0), ("star_up", "Star Up", "⭐", 0), ("evolve", "Evolve", "🌟", 0),
        ("level", "Level", "🔺", 1), ("equip", "Equip", "⚔️", 1), ("automation", "Automation", "⚙️", 1), ("collected", "Collected", "📦", 1),
    ]

    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.active_tab = "summon"
        self.last_result: str = None
        self.last_rolled: list = None

        self.selected_currency = servants.CURRENCY_STONES

        self.roster_page = 0
        self.roster_tier_filter: int = None

        self.selected_keep_id: int = None
        self.selected_consume_ids: list = []
        self.starup_page = 0

        self.selected_evolve_id: int = None
        self.evolve_page = 0

        self.selected_level_id: int = None
        self.level_page = 0
        self.level_tier_filter: int = None

        self.selected_slot = servants.SLOT_KEY_SUPPORT
        self.selected_equip_id: int = None
        self.equip_page = 0

        self.selected_duty = servants.DUTY_MINE
        self.selected_automation_id: int = None
        self.automation_page = 0

        self.collected_page = 0

        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Run `/servant` yourself to manage your own servants.", ephemeral=True)
            return False
        return True

    # -- component building ------------------------------------------------------------------

    def _build_components(self):
        self.clear_items()
        for key, label, emoji, row in self.TABS:
            button = discord.ui.Button(label=label, emoji=emoji, row=row)
            is_active = key == self.active_tab
            button.style = discord.ButtonStyle.primary if is_active else discord.ButtonStyle.secondary
            button.disabled = is_active
            button.callback = self._make_tab_callback(key)
            self.add_item(button)

        if self.active_tab == "summon":
            self._build_summon_components()
        elif self.active_tab == "roster":
            self._build_roster_components()
        elif self.active_tab == "star_up":
            self._build_star_up_components()
        elif self.active_tab == "evolve":
            self._build_evolve_components()
        elif self.active_tab == "level":
            self._build_level_components()
        elif self.active_tab == "equip":
            self._build_equip_components()
        elif self.active_tab == "automation":
            self._build_automation_components()
        elif self.active_tab == "collected":
            self._build_collected_components()

    def _make_tab_callback(self, key: str):
        async def callback(interaction: discord.Interaction):
            self.active_tab = key
            self.last_result = None
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)
        return callback

    @staticmethod
    def _paginate(items: list, page: int, page_size: int = PAGE_SIZE):
        total_pages = max(1, -(-len(items) // page_size))
        page = max(0, min(page, total_pages - 1))
        return items[page * page_size:(page + 1) * page_size], page, total_pages

    def _build_summon_components(self):
        currency_options = [
            discord.SelectOption(label=CURRENCY_LABELS[c], value=c, default=(c == self.selected_currency))
            for c in servants.SUMMON_CURRENCIES
        ]
        currency_select = discord.ui.Select(placeholder="Choose a currency...", options=currency_options, row=2)
        currency_select.callback = self._on_pick_currency
        self.add_item(currency_select)

        summon_one = discord.ui.Button(label="Summon x1", emoji="🎴", style=discord.ButtonStyle.success, row=3)
        summon_one.callback = self._make_summon_callback(1)
        self.add_item(summon_one)

        summon_ten = discord.ui.Button(label="Summon x10", emoji="🎴", style=discord.ButtonStyle.success, row=3)
        summon_ten.callback = self._make_summon_callback(10)
        self.add_item(summon_ten)

    def _build_roster_components(self):
        instances = self.game.get_player_servants(self.user_id)
        counts = {t: 0 for t in range(1, 8)}
        for i in instances:
            counts[i["tier"]] = counts.get(i["tier"], 0) + 1

        # Tier-browse buttons (row2: T7-T3, row3: T2/T1/All) -- "tier + count" layout, so the
        # whole roster is scannable/filterable at a glance instead of one long flat list.
        for t in (7, 6, 5, 4, 3):
            self._add_tier_filter_button(t, counts.get(t, 0), row=2)
        for t in (2, 1):
            self._add_tier_filter_button(t, counts.get(t, 0), row=3)
        all_button = discord.ui.Button(
            label=f"All — {len(instances)}", row=3,
            style=discord.ButtonStyle.primary if self.roster_tier_filter is None else discord.ButtonStyle.secondary,
        )
        all_button.callback = self._make_roster_tier_callback(None)
        self.add_item(all_button)

        filtered = self._roster_filtered(instances)
        _, self.roster_page, total_pages = self._paginate(filtered, self.roster_page, page_size=ROSTER_PAGE_SIZE)
        if total_pages > 1:
            prev_button = discord.ui.Button(label="◀ Prev", row=4, disabled=self.roster_page == 0)
            prev_button.callback = self._make_roster_page_callback(-1)
            self.add_item(prev_button)
            next_button = discord.ui.Button(label="Next ▶", row=4, disabled=self.roster_page >= total_pages - 1)
            next_button.callback = self._make_roster_page_callback(1)
            self.add_item(next_button)

    def _add_tier_filter_button(self, tier: int, count: int, row: int):
        is_active = self.roster_tier_filter == tier
        button = discord.ui.Button(
            label=f"T{tier} — {count}", emoji=servants.TIER_EMOJI[tier], row=row,
            style=discord.ButtonStyle.primary if is_active else discord.ButtonStyle.secondary,
        )
        button.callback = self._make_roster_tier_callback(tier)
        self.add_item(button)

    def _roster_filtered(self, instances: list) -> list:
        if self.roster_tier_filter is None:
            return instances
        return [i for i in instances if i["tier"] == self.roster_tier_filter]

    @staticmethod
    def _has_dupes_for_star_up(instance: dict, name_counts: dict) -> bool:
        if instance["star_level"] >= servants.MAX_STAR_LEVEL:
            return False
        required = servants.STAR_UP_DUPLICATES_REQUIRED[instance["star_level"]]
        return name_counts.get(instance["name"], 0) - 1 >= required

    def _build_star_up_components(self):
        instances = self.game.get_player_servants(self.user_id)
        by_id = {i["instance_id"]: i for i in instances}
        name_counts = {}
        for i in instances:
            name_counts[i["name"]] = name_counts.get(i["name"], 0) + 1

        # Only list servants that can ACTUALLY be starred up right now -- once a servant is
        # maxed at ★7, star-up has nothing left to do with it (evolve-eligible T5/T6 servants
        # move to their own **Evolve** tab; Leveling has its own separate tab/picker too, see
        # _build_level_components).
        keep_candidates = sorted(
            (i for i in instances if self._has_dupes_for_star_up(i, name_counts)),
            key=lambda i: (-i["tier"], i["name"], -i["star_level"]),
        )
        shown, self.starup_page, total_pages = self._paginate(keep_candidates, self.starup_page)
        if self.selected_keep_id not in by_id:
            self.selected_keep_id = None
            self.selected_consume_ids = []

        keep_options = [
            discord.SelectOption(
                label=_instance_label(i)[:100], value=str(i["instance_id"]), default=(i["instance_id"] == self.selected_keep_id),
            )
            for i in shown
        ]
        keep_select = discord.ui.Select(
            placeholder="Choose a servant to star up..." + (f" (page {self.starup_page + 1}/{total_pages})" if total_pages > 1 else ""),
            options=keep_options or [discord.SelectOption(label="No servants ready to star up", value="none")],
            disabled=not keep_options, row=2,
        )
        keep_select.callback = self._on_pick_keep
        self.add_item(keep_select)

        keep = by_id.get(self.selected_keep_id)
        star_up_viable = keep is not None and self._has_dupes_for_star_up(keep, name_counts)

        if star_up_viable:
            required = servants.STAR_UP_DUPLICATES_REQUIRED[keep["star_level"]]
            dupes = [i for i in instances if i["name"] == keep["name"] and i["instance_id"] != keep["instance_id"]]
            dupe_options = [discord.SelectOption(label=_instance_label(i)[:100], value=str(i["instance_id"])) for i in dupes[:PAGE_SIZE]]
            dupe_select = discord.ui.Select(
                placeholder=f"Choose exactly {required} duplicate(s) to consume...",
                options=dupe_options, min_values=required, max_values=required, row=3,
            )
            dupe_select.callback = self._on_pick_consume
            self.add_item(dupe_select)

        if total_pages > 1:
            prev_button = discord.ui.Button(label="◀ Prev", row=4, disabled=self.starup_page == 0)
            prev_button.callback = self._make_starup_page_callback(-1)
            self.add_item(prev_button)
            next_button = discord.ui.Button(label="Next ▶", row=4, disabled=self.starup_page >= total_pages - 1)
            next_button.callback = self._make_starup_page_callback(1)
            self.add_item(next_button)
        if star_up_viable:
            required = servants.STAR_UP_DUPLICATES_REQUIRED[keep["star_level"]]
            star_up_button = discord.ui.Button(
                label="Star Up", emoji="⭐", style=discord.ButtonStyle.success, row=4,
                disabled=len(self.selected_consume_ids) != required,
            )
            star_up_button.callback = self._on_star_up
            self.add_item(star_up_button)

            star_up_all_button = discord.ui.Button(label="Star Up All", emoji="⏫", style=discord.ButtonStyle.primary, row=4)
            star_up_all_button.callback = self._on_star_up_all
            self.add_item(star_up_all_button)

    def _build_evolve_components(self):
        instances = self.game.get_player_servants(self.user_id)
        by_id = {i["instance_id"]: i for i in instances}

        # A maxed T5/T6 servant lands here the moment Star Up brings it to ★7 -- this is the
        # ONLY place evolution happens now (moved out of the Star Up tab, which just handles
        # duplicate-fueled star advancement).
        candidates = sorted(
            (i for i in instances if servants.can_evolve(i["tier"], i["star_level"])),
            key=lambda i: (-i["tier"], i["name"]),
        )
        shown, self.evolve_page, total_pages = self._paginate(candidates, self.evolve_page)
        if self.selected_evolve_id not in by_id:
            self.selected_evolve_id = None

        evolve_options = [
            discord.SelectOption(label=_instance_label(i)[:100], value=str(i["instance_id"]), default=(i["instance_id"] == self.selected_evolve_id))
            for i in shown
        ]
        evolve_select = discord.ui.Select(
            placeholder="Choose a maxed servant to evolve..." + (f" (page {self.evolve_page + 1}/{total_pages})" if total_pages > 1 else ""),
            options=evolve_options or [discord.SelectOption(label="No ★7 Tier 5/6 servants ready to evolve", value="none")],
            disabled=not evolve_options, row=2,
        )
        evolve_select.callback = self._on_pick_evolve
        self.add_item(evolve_select)

        if total_pages > 1:
            prev_button = discord.ui.Button(label="◀ Prev", row=3, disabled=self.evolve_page == 0)
            prev_button.callback = self._make_evolve_page_callback(-1)
            self.add_item(prev_button)
            next_button = discord.ui.Button(label="Next ▶", row=3, disabled=self.evolve_page >= total_pages - 1)
            next_button.callback = self._make_evolve_page_callback(1)
            self.add_item(next_button)

        keep = by_id.get(self.selected_evolve_id)
        if keep is not None and servants.can_evolve(keep["tier"], keep["star_level"]):
            evolve_button = discord.ui.Button(label=f"Evolve {keep['name']}", emoji="🌟", style=discord.ButtonStyle.success, row=4)
            evolve_button.callback = self._on_evolve
            self.add_item(evolve_button)

    def _level_filtered(self, instances: list) -> list:
        candidates = [i for i in instances if i["level"] < servants.SERVANT_MAX_LEVEL]
        if self.level_tier_filter is not None:
            candidates = [i for i in candidates if i["tier"] == self.level_tier_filter]
        return sorted(candidates, key=lambda i: (-i["tier"], i["name"], i["level"]))

    def _build_level_components(self):
        """Level's own independent servant picker -- deliberately NOT shared with Star Up's
        keep select, so any owned servant with Level headroom is reachable here regardless of
        whether it also happens to be star-up/evolve eligible. A tier filter (row2, a compact
        Select rather than Roster's button-grid -- this tab already needs 2 more rows for the
        instance picker itself and its actions, no room left for a 2-row tier grid too) narrows
        the picker below it."""
        instances = self.game.get_player_servants(self.user_id)
        by_id = {i["instance_id"]: i for i in instances}

        tier_counts = {t: 0 for t in range(1, 8)}
        for i in instances:
            if i["level"] < servants.SERVANT_MAX_LEVEL:
                tier_counts[i["tier"]] += 1
        tier_options = [discord.SelectOption(label=f"All Tiers — {sum(tier_counts.values())}", value="all", default=self.level_tier_filter is None)]
        for t in range(1, 8):
            tier_options.append(discord.SelectOption(
                label=f"T{t} — {tier_counts[t]}", value=str(t), emoji=servants.TIER_EMOJI[t], default=(self.level_tier_filter == t),
            ))
        tier_select = discord.ui.Select(placeholder="Filter by tier...", options=tier_options, row=2)
        tier_select.callback = self._on_pick_level_tier
        self.add_item(tier_select)

        candidates = self._level_filtered(instances)
        shown, self.level_page, total_pages = self._paginate(candidates, self.level_page)
        if self.selected_level_id not in by_id:
            self.selected_level_id = None

        level_options = [
            discord.SelectOption(label=_instance_label(i)[:100], value=str(i["instance_id"]), default=(i["instance_id"] == self.selected_level_id))
            for i in shown
        ]
        level_select = discord.ui.Select(
            placeholder="Choose a servant to level up..." + (f" (page {self.level_page + 1}/{total_pages})" if total_pages > 1 else ""),
            options=level_options or [discord.SelectOption(label="Nothing at this filter to level up", value="none")],
            disabled=not level_options, row=3,
        )
        level_select.callback = self._on_pick_level_instance
        self.add_item(level_select)

        if total_pages > 1:
            prev_button = discord.ui.Button(label="◀ Prev", row=4, disabled=self.level_page == 0)
            prev_button.callback = self._make_level_page_callback(-1)
            self.add_item(prev_button)
            next_button = discord.ui.Button(label="Next ▶", row=4, disabled=self.level_page >= total_pages - 1)
            next_button.callback = self._make_level_page_callback(1)
            self.add_item(next_button)

        keep = by_id.get(self.selected_level_id)
        if keep is not None:
            level_up_button = discord.ui.Button(
                label=f"Level Up ({keep['level']}→{keep['level'] + 1})", emoji="🔺", style=discord.ButtonStyle.success, row=4,
            )
            level_up_button.callback = self._on_level_up
            self.add_item(level_up_button)

    def _build_equip_components(self):
        slot_options = [
            discord.SelectOption(label="Support", value=servants.SLOT_KEY_SUPPORT, default=(self.selected_slot == servants.SLOT_KEY_SUPPORT)),
            discord.SelectOption(label="Combat", value=servants.SLOT_KEY_COMBAT, default=(self.selected_slot == servants.SLOT_KEY_COMBAT)),
        ]
        slot_select = discord.ui.Select(placeholder="Choose a slot...", options=slot_options, row=2)
        slot_select.callback = self._on_pick_slot
        self.add_item(slot_select)

        instances = self.game.get_player_servants(self.user_id)
        shown, self.equip_page, total_pages = self._paginate(instances, self.equip_page)
        instance_options = [
            discord.SelectOption(label=_instance_label(i)[:100], value=str(i["instance_id"]), default=(i["instance_id"] == self.selected_equip_id))
            for i in shown
        ]
        instance_select = discord.ui.Select(
            placeholder="Choose a servant to equip..." + (f" (page {self.equip_page + 1}/{total_pages})" if total_pages > 1 else ""),
            options=instance_options or [discord.SelectOption(label="No servants owned", value="none")],
            disabled=not instance_options, row=3,
        )
        instance_select.callback = self._on_pick_equip_instance
        self.add_item(instance_select)

        equip_button = discord.ui.Button(label="Equip", emoji="⚔️", style=discord.ButtonStyle.success, row=4, disabled=not instance_options)
        equip_button.callback = self._on_equip
        self.add_item(equip_button)
        unequip_button = discord.ui.Button(label="Unequip Slot", emoji="🗑️", style=discord.ButtonStyle.danger, row=4)
        unequip_button.callback = self._on_unequip
        self.add_item(unequip_button)
        if total_pages > 1:
            prev_button = discord.ui.Button(label="◀ Prev", row=4, disabled=self.equip_page == 0)
            prev_button.callback = self._make_equip_page_callback(-1)
            self.add_item(prev_button)
            next_button = discord.ui.Button(label="Next ▶", row=4, disabled=self.equip_page >= total_pages - 1)
            next_button.callback = self._make_equip_page_callback(1)
            self.add_item(next_button)

    def _build_automation_components(self):
        duty_options = [discord.SelectOption(label=label, value=key, default=(key == self.selected_duty)) for key, label in DUTY_LABELS.items()]
        duty_select = discord.ui.Select(placeholder="Choose a duty...", options=duty_options, row=2)
        duty_select.callback = self._on_pick_duty
        self.add_item(duty_select)

        instances = self.game.get_player_servants(self.user_id)
        idle = [i for i in instances if i["automation_duty"] is None]
        shown, self.automation_page, total_pages = self._paginate(idle, self.automation_page)
        instance_options = [
            discord.SelectOption(label=_instance_label(i)[:100], value=str(i["instance_id"]), default=(i["instance_id"] == self.selected_automation_id))
            for i in shown
        ]
        instance_select = discord.ui.Select(
            placeholder="Choose an idle servant to assign..." + (f" (page {self.automation_page + 1}/{total_pages})" if total_pages > 1 else ""),
            options=instance_options or [discord.SelectOption(label="No idle servants owned", value="none")],
            disabled=not instance_options, row=3,
        )
        instance_select.callback = self._on_pick_automation_instance
        self.add_item(instance_select)

        assigned = [i for i in instances if i["automation_duty"] is not None]
        assign_button = discord.ui.Button(
            label="Assign", emoji="📌", style=discord.ButtonStyle.success, row=4,
            disabled=not instance_options or len(assigned) >= servants.MAX_AUTOMATION_SERVANTS,
        )
        assign_button.callback = self._on_assign_duty
        self.add_item(assign_button)
        for instance in assigned[:servants.MAX_AUTOMATION_SERVANTS]:
            stop_button = discord.ui.Button(label=f"Stop #{instance['instance_id']}", style=discord.ButtonStyle.danger, row=4)
            stop_button.callback = self._make_unassign_callback(instance["instance_id"])
            self.add_item(stop_button)
        # A single wraparound cycle button instead of separate Prev/Next -- row4 is already at
        # assign(1) + up to MAX_AUTOMATION_SERVANTS(3) stop buttons, leaving only 1 slot free,
        # not the 2 a Prev/Next pair would need.
        if total_pages > 1:
            cycle_button = discord.ui.Button(label=f"Next Page ({self.automation_page + 1}/{total_pages})", row=4)
            cycle_button.callback = self._make_automation_cycle_callback(total_pages)
            self.add_item(cycle_button)

    def _build_collected_components(self):
        """Read-only -- just a paginated tally, no picker/action buttons needed."""
        totals = self.game.get_servant_automation_totals(self.user_id)
        _, self.collected_page, total_pages = self._paginate(list(totals.items()), self.collected_page, page_size=COLLECTED_PAGE_SIZE)
        if total_pages > 1:
            prev_button = discord.ui.Button(label="◀ Prev", row=2, disabled=self.collected_page == 0)
            prev_button.callback = self._make_collected_page_callback(-1)
            self.add_item(prev_button)
            next_button = discord.ui.Button(label="Next ▶", row=2, disabled=self.collected_page >= total_pages - 1)
            next_button.callback = self._make_collected_page_callback(1)
            self.add_item(next_button)

    # -- callbacks: summon ----------------------------------------------------------------------

    async def _on_pick_currency(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select) and child.row == 2)
        self.selected_currency = select.values[0]
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def _make_summon_callback(self, count: int):
        async def callback(interaction: discord.Interaction):
            ok, message, rolled = await asyncio.to_thread(self.game.summon_servant, self.user_id, self.selected_currency, count)
            self.last_result = message
            self.last_rolled = rolled if ok else None
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)
        return callback

    # -- callbacks: roster ------------------------------------------------------------------

    def _make_roster_page_callback(self, delta: int):
        async def callback(interaction: discord.Interaction):
            self.roster_page += delta
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)
        return callback

    def _make_roster_tier_callback(self, tier):
        async def callback(interaction: discord.Interaction):
            self.roster_tier_filter = tier
            self.roster_page = 0
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)
        return callback

    # -- callbacks: star up -------------------------------------------------------------------

    async def _on_pick_keep(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select) and child.row == 2)
        self.selected_keep_id = int(select.values[0])
        self.selected_consume_ids = []
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def _make_starup_page_callback(self, delta: int):
        async def callback(interaction: discord.Interaction):
            self.starup_page += delta
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)
        return callback

    async def _on_pick_consume(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select) and child.row == 3)
        self.selected_consume_ids = [int(v) for v in select.values]
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_star_up(self, interaction: discord.Interaction):
        if self.selected_keep_id and self.selected_consume_ids:
            _, self.last_result = await asyncio.to_thread(self.game.star_up_servant, self.user_id, self.selected_keep_id, self.selected_consume_ids)
        self.selected_consume_ids = []
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_star_up_all(self, interaction: discord.Interaction):
        if self.selected_keep_id:
            _, self.last_result = await asyncio.to_thread(self.game.star_up_all, self.user_id, self.selected_keep_id)
        self.selected_consume_ids = []
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    # -- callbacks: evolve ----------------------------------------------------------------------

    async def _on_pick_evolve(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select) and child.row == 2)
        self.selected_evolve_id = int(select.values[0])
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def _make_evolve_page_callback(self, delta: int):
        async def callback(interaction: discord.Interaction):
            self.evolve_page += delta
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)
        return callback

    async def _on_evolve(self, interaction: discord.Interaction):
        new_instance_id = None
        if self.selected_evolve_id:
            _, self.last_result, new_instance_id = await asyncio.to_thread(self.game.evolve_servant, self.user_id, self.selected_evolve_id)
        # Select the FRESHLY EVOLVED instance (not None) so the rebuilt embed immediately shows
        # exactly what the servant turned into -- name, tier, stats, and its own portrait --
        # instead of going blank right after such a dramatic identity change.
        self.selected_evolve_id = new_instance_id
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    # -- callbacks: level -------------------------------------------------------------------

    async def _on_pick_level_tier(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select) and child.row == 2)
        value = select.values[0]
        self.level_tier_filter = None if value == "all" else int(value)
        self.level_page = 0
        self.selected_level_id = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_level_instance(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select) and child.row == 3)
        self.selected_level_id = int(select.values[0])
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def _make_level_page_callback(self, delta: int):
        async def callback(interaction: discord.Interaction):
            self.level_page += delta
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)
        return callback

    async def _on_level_up(self, interaction: discord.Interaction):
        if self.selected_level_id:
            _, self.last_result = await asyncio.to_thread(self.game.level_up_servant, self.user_id, self.selected_level_id)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    # -- callbacks: equip -------------------------------------------------------------------

    async def _on_pick_slot(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select) and child.row == 2)
        self.selected_slot = select.values[0]
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_equip_instance(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select) and child.row == 3)
        self.selected_equip_id = int(select.values[0])
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def _make_equip_page_callback(self, delta: int):
        async def callback(interaction: discord.Interaction):
            self.equip_page += delta
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)
        return callback

    async def _on_equip(self, interaction: discord.Interaction):
        if self.selected_equip_id:
            _, self.last_result = await asyncio.to_thread(self.game.equip_servant, self.user_id, self.selected_slot, self.selected_equip_id)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_unequip(self, interaction: discord.Interaction):
        _, self.last_result = await asyncio.to_thread(self.game.unequip_servant, self.user_id, self.selected_slot)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    # -- callbacks: automation ----------------------------------------------------------------

    async def _on_pick_duty(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select) and child.row == 2)
        self.selected_duty = select.values[0]
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_automation_instance(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select) and child.row == 3)
        self.selected_automation_id = int(select.values[0])
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def _make_automation_cycle_callback(self, total_pages: int):
        async def callback(interaction: discord.Interaction):
            self.automation_page = (self.automation_page + 1) % total_pages
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)
        return callback

    async def _on_assign_duty(self, interaction: discord.Interaction):
        if self.selected_automation_id:
            _, self.last_result = await asyncio.to_thread(self.game.assign_servant_duty, self.user_id, self.selected_automation_id, self.selected_duty)
        self.selected_automation_id = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def _make_unassign_callback(self, instance_id: int):
        async def callback(interaction: discord.Interaction):
            _, self.last_result = await asyncio.to_thread(self.game.unassign_servant_duty, self.user_id, instance_id)
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)
        return callback

    # -- callbacks: collected -------------------------------------------------------------------

    def _make_collected_page_callback(self, delta: int):
        async def callback(interaction: discord.Interaction):
            self.collected_page += delta
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)
        return callback

    # -- embed --------------------------------------------------------------------------------

    def build_embed(self) -> discord.Embed:
        if self.active_tab == "summon":
            embed = self._summon_embed()
        elif self.active_tab == "roster":
            embed = self._roster_embed()
        elif self.active_tab == "star_up":
            embed = self._star_up_embed()
        elif self.active_tab == "evolve":
            embed = self._evolve_embed()
        elif self.active_tab == "level":
            embed = self._level_embed()
        elif self.active_tab == "equip":
            embed = self._equip_embed()
        elif self.active_tab == "collected":
            embed = self._collected_embed()
        else:
            embed = self._automation_embed()
        if self.last_result:
            embed.add_field(name="Result", value=self.last_result, inline=False)
        return embed

    def _summon_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"🎴 {self.display_name}'s Servant Summon",
            description=(
                "Roll for a servant across 7 tiers "
                "(T1 36.9% · T2 26% · T3 18% · T4 12% · T5 6% · T6 1% · T7 0.1%).\n\n"
                f"Currency: **{CURRENCY_LABELS[self.selected_currency]}** "
                f"({servants.SUMMON_CURRENCY_COST[self.selected_currency]}/summon)"
            ),
            color=discord.Color.gold(),
        )
        if self.last_rolled:
            lines = "\n".join(f"{servants.TIER_EMOJI.get(tier, '')} **{name}** (Tier {tier})" for name, tier in self.last_rolled)
            embed.add_field(name="Pull Results", value=lines, inline=False)
            if len(self.last_rolled) == 1:
                _maybe_set_image(embed, self.last_rolled[0][0])
        return embed

    def _roster_embed(self) -> discord.Embed:
        instances = self.game.get_player_servants(self.user_id)
        filtered = self._roster_filtered(instances)
        shown, page, total_pages = self._paginate(filtered, self.roster_page, page_size=ROSTER_PAGE_SIZE)
        collection_pct = self.game.get_servant_collection_bonus_pct(self.user_id)
        distinct = len({i["name"] for i in instances})
        embed = discord.Embed(
            title=f"📜 {self.display_name}'s Servants",
            description=(
                f"**{len(instances)}** owned, **{distinct}** distinct names.\n"
                f"Collection bonus: {_format_bonus_line('stone_reward_bonus_pct', collection_pct)} / "
                f"{_format_bonus_line('loot_chance_bonus_pct', collection_pct)}"
            ),
            color=discord.Color.gold(),
        )
        filter_label = servants.tier_label(self.roster_tier_filter) if self.roster_tier_filter else "All Tiers"
        field_name = f"Roster — {filter_label}" + (f" (page {page + 1}/{total_pages})" if total_pages > 1 else "")
        if shown:
            lines = []
            for i in shown:
                tags = []
                if i["automation_duty"]:
                    tags.append(f"on {DUTY_LABELS.get(i['automation_duty'], i['automation_duty'])} duty")
                servant = servants.SERVANT_CATALOG.get(i["name"])
                stat_text = (
                    _stats_text(servant, i["star_level"], i["level"], i.get("current_affinity_seconds", 0))
                    if servant else ""
                )
                line = _instance_label(i)
                if stat_text and stat_text != "—":
                    line += f" — {stat_text}"
                if tags:
                    line += f" ({', '.join(tags)})"
                lines.append(line)
            embed.add_field(name=field_name, value="\n".join(lines), inline=False)
        else:
            embed.add_field(name=field_name, value="No servants yet — summon one!" if not instances else "None of this tier.", inline=False)
        return embed

    def _star_up_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"⭐ {self.display_name}'s Star Up",
            description=(
                "Consume exact-name duplicates to advance a servant's star level (1★→7★). Once "
                "a Tier 5/6 servant maxes at ★7, find it on the **Evolve** tab to transform it "
                "into a fresh named identity. Leveling (materials, no duplicates needed) lives "
                "on its own **Level** tab."
            ),
            color=discord.Color.gold(),
        )
        instances = self.game.get_player_servants(self.user_id)
        keep = next((i for i in instances if i["instance_id"] == self.selected_keep_id), None)
        if keep:
            lines = [f"{servants.tier_label(keep['tier'])} · ★{keep['star_level']} · Level {keep['level']}/{servants.SERVANT_MAX_LEVEL}"]
            affinity_seconds = keep.get("current_affinity_seconds", 0)
            if affinity_seconds:
                mult = servants.affinity_multiplier(affinity_seconds)
                lines.append(f"Affinity: {affinity_seconds / 86400:.1f}d equipped (+{(mult - 1) * 100:.1f}% bonus)")

            if servants.can_evolve(keep["tier"], keep["star_level"]):
                lines.append(f"✅ Maxed and ready to evolve! Switch to the **Evolve** tab to turn it into a random Tier {keep['tier'] + 1} servant.")
            elif keep["star_level"] >= servants.MAX_STAR_LEVEL:
                # Maxed at ★7 with nowhere further to go -- either a non-evolvable tier (T1-4,
                # T7) or a T5/6 that already evolved. STAR_UP_DUPLICATES_REQUIRED only has keys
                # 1-6 (there's no "star up from 7"), so this branch MUST come before the dict
                # lookup below or it KeyErrors (the exact bug this fixes).
                lines.append("Star level maxed.")
            else:
                required = servants.STAR_UP_DUPLICATES_REQUIRED[keep["star_level"]]
                dupes_owned = len([i for i in instances if i["name"] == keep["name"] and i["instance_id"] != keep["instance_id"]])
                lines.append(f"★{keep['star_level']} → ★{keep['star_level'] + 1}: choose **{required}** duplicate(s) below (you own {dupes_owned}).")

            embed.add_field(name=keep["name"], value="\n".join(lines), inline=False)
            _maybe_set_image(embed, keep["name"])
        return embed

    def _evolve_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"🌟 {self.display_name}'s Servant Evolution",
            description=(
                "A Tier 5 or Tier 6 servant maxed to ★7 shows up here, ready to transform into a "
                "fresh, randomly-rolled Tier 6/7 named servant -- a full identity swap, not just a "
                "stat boost. The new servant starts back at ★1 (its Level and Affinity carry over "
                "unchanged), so you'll need duplicates of its NEW name to star it up again."
            ),
            color=discord.Color.gold(),
        )
        instances = self.game.get_player_servants(self.user_id)
        keep = next((i for i in instances if i["instance_id"] == self.selected_evolve_id), None)
        if keep:
            lines = [f"{servants.tier_label(keep['tier'])} · ★{keep['star_level']} · Level {keep['level']}/{servants.SERVANT_MAX_LEVEL}"]
            if servants.can_evolve(keep["tier"], keep["star_level"]):
                lines.append(f"✅ Ready to evolve into a random Tier {keep['tier'] + 1} servant!")
            else:
                lines.append(f"This is what it evolved into: **{keep['name']}**.")
            embed.add_field(name=keep["name"], value="\n".join(lines), inline=False)
            _maybe_set_image(embed, keep["name"])
        else:
            embed.add_field(
                name="No servant selected",
                value="Star a Tier 5 or Tier 6 servant up to ★7 first (see the **Star Up** tab), then pick it here to evolve it.",
                inline=False,
            )
        return embed

    def _level_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"🔺 {self.display_name}'s Servant Leveling",
            description=(
                "Feed Soul Nourishing Pill + Soul Crystal + Spirit Stones to advance a servant's "
                "Level (1-10) -- the same materials/curve Nascent Soul Avatar leveling uses, scaled "
                "by the servant's own tier. Independent of Star -- works even on a lone, dupe-less copy."
            ),
            color=discord.Color.gold(),
        )
        instances = self.game.get_player_servants(self.user_id)
        keep = next((i for i in instances if i["instance_id"] == self.selected_level_id), None)
        if keep:
            lines = [f"{servants.tier_label(keep['tier'])} · ★{keep['star_level']} · Level {keep['level']}/{servants.SERVANT_MAX_LEVEL}"]
            recipe = servants.level_up_recipe(keep["tier"], keep["level"])
            if recipe is not None:
                stones_cost = servants.level_up_stones_cost(keep["tier"], keep["level"])
                recipe_text = ", ".join(f"{qty}x {item}" for item, qty in recipe.items())
                lines.append(f"Level {keep['level']} → {keep['level'] + 1}: {format_number(stones_cost)} Spirit Stones + {recipe_text}")
            else:
                lines.append("Level maxed.")
            embed.add_field(name=keep["name"], value="\n".join(lines), inline=False)
            _maybe_set_image(embed, keep["name"])
        else:
            filter_label = servants.tier_label(self.level_tier_filter) if self.level_tier_filter else "All Tiers"
            embed.add_field(name="Filter", value=f"Showing **{filter_label}** — pick a servant below.", inline=False)
        return embed

    def _equip_embed(self) -> discord.Embed:
        equipped = self.game.get_equipped_servants(self.user_id)
        embed = discord.Embed(title=f"⚔️ {self.display_name}'s Servant Slots", color=discord.Color.gold())
        for slot_key, label in (("servant_combat", "Combat"), ("servant_support", "Support")):
            instance = equipped.get(slot_key)
            if instance is None:
                embed.add_field(name=label, value="Empty", inline=False)
                continue
            servant = servants.SERVANT_CATALOG.get(instance["name"])
            affinity_seconds = instance.get("current_affinity_seconds", 0)
            lines = [f"**{instance['name']}** ({servants.tier_label(instance['tier'])} ★{instance['star_level']} Lv{instance['level']})"]
            if affinity_seconds:
                mult = servants.affinity_multiplier(affinity_seconds)
                lines.append(f"Affinity: {affinity_seconds / 86400:.1f}d equipped (+{(mult - 1) * 100:.1f}% bonus)")
            if servant:
                stats_text = _stats_text(servant, instance["star_level"], instance["level"], affinity_seconds)
                if slot_key == servants.SLOT_KEY_SUPPORT:
                    lines.append(f"Stats (half): {stats_text}")
                    lines.append(_format_bonus_line(servant.support_bonus_key, servants.support_special_pct(servant, instance["star_level"], instance["level"], affinity_seconds)))
                else:
                    lines.append(f"Stats: {stats_text}")
            embed.add_field(name=label, value="\n".join(lines), inline=False)
        # An embed only has ONE thumbnail slot -- Combat wins when both are filled, since it's
        # listed first and is the more "battle-facing" of the two.
        primary = equipped.get(servants.SLOT_KEY_COMBAT) or equipped.get(servants.SLOT_KEY_SUPPORT)
        if primary:
            _maybe_set_image(embed, primary["name"])
        return embed

    def _automation_embed(self) -> discord.Embed:
        instances = self.game.get_player_servants(self.user_id)
        assigned = [i for i in instances if i["automation_duty"] is not None]
        embed = discord.Embed(
            title=f"⚙️ {self.display_name}'s Servant Automation",
            description=(
                f"**{len(assigned)} / {servants.MAX_AUTOMATION_SERVANTS}** servants on duty. Each assigned servant "
                "triggers one mine/gather/farm cycle per real day on your behalf, boosted by that "
                "servant's own Tier/Star/Level/Affinity -- a higher-tier, more-invested servant is a "
                "meaningfully better worker, not just eligible to work."
            ),
            color=discord.Color.gold(),
        )
        if assigned:
            lines = []
            for i in assigned:
                servant = servants.SERVANT_CATALOG.get(i["name"])
                bonus_text = ""
                if servant:
                    bonus_pct = servants.automation_yield_bonus_pct(servant, i["star_level"], i["level"], i.get("current_affinity_seconds", 0))
                    bonus_text = f" (+{bonus_pct * 100:.0f}% yield)"
                lines.append(f"{_instance_label(i)} — {DUTY_LABELS.get(i['automation_duty'], i['automation_duty'])} duty{bonus_text}")
            embed.add_field(name="On Duty", value="\n".join(lines), inline=False)
        return embed

    def _collected_embed(self) -> discord.Embed:
        totals = self.game.get_servant_automation_totals(self.user_id)
        items = list(totals.items())
        embed = discord.Embed(
            title=f"📦 {self.display_name}'s Automated Collection",
            description=(
                "Lifetime totals gained from servants on Mine/Gather/Farm duty (see the "
                "**Automation** tab) -- every automated tick's yield is tallied here, separate "
                "from anything you collect manually."
            ),
            color=discord.Color.gold(),
        )
        if not items:
            embed.add_field(
                name="Nothing collected yet",
                value="Assign a servant to a duty on the **Automation** tab to start.",
                inline=False,
            )
            return embed
        shown, page, total_pages = self._paginate(items, self.collected_page, page_size=COLLECTED_PAGE_SIZE)
        lines = [f"{item} — **{format_number(qty)}**" for item, qty in shown]
        field_name = "Totals" + (f" (page {page + 1}/{total_pages})" if total_pages > 1 else "")
        embed.add_field(name=field_name, value="\n".join(lines), inline=False)
        embed.set_footer(text=f"{format_number(sum(totals.values()))} items total across {len(items)} kinds")
        return embed


class ViewServantView(GameView):
    """/view_servant -- a focused, image-forward display of your Combat and Support servants
    (each its own embed with a large image, since one embed only gets one big image slot) plus
    a Dual Cultivate button (see GameManager.dual_cultivate) for an instant qi + essence burst,
    gated on having a servant equipped in BOTH slots and scaled by their combined investment."""

    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.last_result: str = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Run `/view_servant` yourself to see your own servants.", ephemeral=True)
            return False
        return True

    def _build_components(self):
        self.clear_items()
        button = discord.ui.Button(label="Dual Cultivate", emoji="🌀", style=discord.ButtonStyle.success, row=0)
        button.callback = self._on_dual_cultivate
        self.add_item(button)

    async def _on_dual_cultivate(self, interaction: discord.Interaction):
        result = await asyncio.to_thread(self.game.dual_cultivate, self.user_id, self.display_name)
        if result["ok"]:
            self.last_result = (
                f"🌀 Dual Cultivate! +{format_number(result['qi_gained'])} qi, "
                f"+{format_number(result['essence_restored'])} essence "
                f"({result['essence']}/{result['max_essence']})."
            )
        elif "reason" in result:
            self.last_result = result["reason"]
        else:
            self.last_result = f"Dual Cultivate is on cooldown — {format_duration(result['remaining_seconds'])} remaining."
        await asyncio.to_thread(self._build_components)
        embeds = await asyncio.to_thread(self.build_embeds)
        await interaction.response.edit_message(embeds=embeds, view=self)

    def _slot_embed(self, slot_key: str, label: str, emoji: str, instance) -> discord.Embed:
        if instance is None:
            return discord.Embed(
                title=f"{emoji} {label} — Empty",
                description="Equip a servant via `/servant`'s Equip tab.",
                color=discord.Color.dark_gray(),
            )
        servant = servants.SERVANT_CATALOG.get(instance["name"])
        affinity_seconds = instance.get("current_affinity_seconds", 0)
        lines = [f"{servants.tier_label(instance['tier'])} · ★{instance['star_level']} · Level {instance['level']}/{servants.SERVANT_MAX_LEVEL}"]
        if affinity_seconds:
            mult = servants.affinity_multiplier(affinity_seconds)
            lines.append(f"Affinity: {affinity_seconds / 86400:.1f}d equipped (+{(mult - 1) * 100:.1f}% bonus)")
        if servant:
            lines.append(_stats_text(servant, instance["star_level"], instance["level"], affinity_seconds) if slot_key == servants.SLOT_KEY_COMBAT else "")
            if slot_key == servants.SLOT_KEY_SUPPORT:
                half_text = ", ".join(
                    _format_bonus_line(k, v * servants.SUPPORT_STAT_FRACTION)
                    for k, v in servants.scaled_stat_bonuses(servant, instance["star_level"], instance["level"], affinity_seconds).items()
                )
                lines.append(half_text)
                lines.append(_format_bonus_line(servant.support_bonus_key, servants.support_special_pct(servant, instance["star_level"], instance["level"], affinity_seconds)))
        embed = discord.Embed(title=f"{emoji} {label}: {instance['name']}", description="\n".join(line for line in lines if line), color=discord.Color.gold())
        if servant and servant.image_url:
            embed.set_image(url=servant.image_url)
        return embed

    def build_embeds(self) -> list:
        equipped = self.game.get_equipped_servants(self.user_id)
        combat_embed = self._slot_embed(servants.SLOT_KEY_COMBAT, "Combat", "⚔️", equipped.get(servants.SLOT_KEY_COMBAT))
        support_embed = self._slot_embed(servants.SLOT_KEY_SUPPORT, "Support", "🛡️", equipped.get(servants.SLOT_KEY_SUPPORT))
        embeds = [combat_embed, support_embed]
        if self.last_result:
            embeds[-1].add_field(name="Result", value=self.last_result, inline=False)
        return embeds
