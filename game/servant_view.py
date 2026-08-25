"""
ServantView -- the /servant menu (admin-only preview, see cog.py). Summon tab: roll for new
servants (see GameManager.summon_servant). Roster tab: browse owned instances + the collection
bonus. Star Up tab: consume exact-name duplicates to advance a servant's star level, or evolve a
maxed T5/T6 servant into a fresh T6/T7 named identity (see GameManager.star_up_servant/
evolve_servant). Equip tab: assign a servant to the Support or Combat slot (see
GameManager.equip_servant/unequip_servant). Automation tab: assign a servant to auto-run mining/
gathering/farming on a daily tick (see GameManager.assign_servant_duty/unassign_servant_duty).
"""

import asyncio

import discord

from . import servants
from .base_view import GameView
from .equipment import SPECIAL_STAT_TEXT
from .ui_utils import format_number

PAGE_SIZE = 25

STAT_LABELS = {
    "str_stat": "STR", "atk_stat": "ATK", "hp": "HP", "spd_stat": "SPD",
    "def_stat": "DEF", "qi_stat": "QI", "luck_stat": "Luck",
}

CURRENCY_LABELS = {
    servants.CURRENCY_STONES: "Spirit Stones",
    servants.CURRENCY_ESSENCE_CRYSTALS: "Primeval Essence Crystals",
    servants.CURRENCY_ESSENCE_PILLS: "Essence Restoration Pills (any tier)",
    servants.CURRENCY_MANUAL_PAGES: "Manual Pages (any rank)",
}

DUTY_LABELS = {servants.DUTY_MINE: "Mine", servants.DUTY_GATHER: "Gather", servants.DUTY_FARM: "Farm"}


def _format_bonus_line(key: str, value: float) -> str:
    formatter = SPECIAL_STAT_TEXT.get(key)
    return formatter(value) if formatter else f"{key}: {value:g}"


def _instance_label(instance: dict) -> str:
    return f"{servants.TIER_EMOJI.get(instance['tier'], '')} #{instance['instance_id']} {instance['name']} (T{instance['tier']} ★{instance['star_level']} Lv{instance['level']})"


def _stats_text(servant, star_level: int, level: int = 1, affinity_seconds: int = 0) -> str:
    bonuses = servants.scaled_stat_bonuses(servant, star_level, level, affinity_seconds)
    return ", ".join(f"{STAT_LABELS.get(k, k)} +{v:g}" for k, v in bonuses.items()) or "—"


class ServantView(GameView):
    TABS = [
        ("summon", "Summon", "🎴"), ("roster", "Roster", "📜"), ("star_up", "Star Up", "⭐"),
        ("equip", "Equip", "⚔️"), ("automation", "Automation", "⚙️"),
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

        self.selected_slot = servants.SLOT_KEY_SUPPORT
        self.selected_equip_id: int = None
        self.equip_page = 0

        self.selected_duty = servants.DUTY_MINE
        self.selected_automation_id: int = None
        self.automation_page = 0

        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Run `/servant` yourself to manage your own servants.", ephemeral=True)
            return False
        return True

    # -- component building ------------------------------------------------------------------

    def _build_components(self):
        self.clear_items()
        for key, label, emoji in self.TABS:
            button = discord.ui.Button(label=label, emoji=emoji, row=0)
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
        elif self.active_tab == "equip":
            self._build_equip_components()
        elif self.active_tab == "automation":
            self._build_automation_components()

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
        currency_select = discord.ui.Select(placeholder="Choose a currency...", options=currency_options, row=1)
        currency_select.callback = self._on_pick_currency
        self.add_item(currency_select)

        summon_one = discord.ui.Button(label="Summon x1", emoji="🎴", style=discord.ButtonStyle.success, row=2)
        summon_one.callback = self._make_summon_callback(1)
        self.add_item(summon_one)

        summon_ten = discord.ui.Button(label="Summon x10", emoji="🎴", style=discord.ButtonStyle.success, row=2)
        summon_ten.callback = self._make_summon_callback(10)
        self.add_item(summon_ten)

    def _build_roster_components(self):
        instances = self.game.get_player_servants(self.user_id)
        counts = {t: 0 for t in range(1, 8)}
        for i in instances:
            counts[i["tier"]] = counts.get(i["tier"], 0) + 1

        # Tier-browse buttons (row1: T7-T3, row2: T2/T1/All) -- same "tier + count" layout
        # requested, so the whole roster is scannable/filterable at a glance instead of one
        # long flat list.
        for t in (7, 6, 5, 4, 3):
            self._add_tier_filter_button(t, counts.get(t, 0), row=1)
        for t in (2, 1):
            self._add_tier_filter_button(t, counts.get(t, 0), row=2)
        all_button = discord.ui.Button(
            label=f"All — {len(instances)}", row=2,
            style=discord.ButtonStyle.primary if self.roster_tier_filter is None else discord.ButtonStyle.secondary,
        )
        all_button.callback = self._make_roster_tier_callback(None)
        self.add_item(all_button)

        filtered = self._roster_filtered(instances)
        _, self.roster_page, total_pages = self._paginate(filtered, self.roster_page, page_size=15)
        if total_pages > 1:
            prev_button = discord.ui.Button(label="◀ Prev", row=3, disabled=self.roster_page == 0)
            prev_button.callback = self._make_roster_page_callback(-1)
            self.add_item(prev_button)
            next_button = discord.ui.Button(label="Next ▶", row=3, disabled=self.roster_page >= total_pages - 1)
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

        # Only list servants with an actionable power-up path right now: ready to evolve, has
        # enough duplicates owned to star up immediately, or still has Level headroom (fed with
        # materials, so it's available almost always) -- a servant fully maxed on both Star AND
        # Level with no evolution/dupes available is the only thing excluded.
        def has_action(i):
            return (
                servants.can_evolve(i["tier"], i["star_level"])
                or self._has_dupes_for_star_up(i, name_counts)
                or i["level"] < servants.SERVANT_MAX_LEVEL
            )

        keep_candidates = sorted((i for i in instances if has_action(i)), key=lambda i: (i["tier"], i["name"], -i["star_level"]))
        shown, self.starup_page, total_pages = self._paginate(keep_candidates, self.starup_page)
        if self.selected_keep_id not in by_id:
            self.selected_keep_id = None
            self.selected_consume_ids = []

        keep_options = [
            discord.SelectOption(
                label=(_instance_label(i) + (" (ready to evolve)" if servants.can_evolve(i["tier"], i["star_level"]) else ""))[:100],
                value=str(i["instance_id"]), default=(i["instance_id"] == self.selected_keep_id),
            )
            for i in shown
        ]
        keep_select = discord.ui.Select(
            placeholder="Choose a servant to power up..." + (f" (page {self.starup_page + 1}/{total_pages})" if total_pages > 1 else ""),
            options=keep_options or [discord.SelectOption(label="Nothing left to advance", value="none")],
            disabled=not keep_options, row=1,
        )
        keep_select.callback = self._on_pick_keep
        self.add_item(keep_select)
        if total_pages > 1:
            prev_button = discord.ui.Button(label="◀ Prev", row=2, disabled=self.starup_page == 0)
            prev_button.callback = self._make_starup_page_callback(-1)
            self.add_item(prev_button)
            next_button = discord.ui.Button(label="Next ▶", row=2, disabled=self.starup_page >= total_pages - 1)
            next_button.callback = self._make_starup_page_callback(1)
            self.add_item(next_button)

        keep = by_id.get(self.selected_keep_id)
        if keep is None:
            return

        if servants.can_evolve(keep["tier"], keep["star_level"]):
            evolve_button = discord.ui.Button(label=f"Evolve {keep['name']}", emoji="🌟", style=discord.ButtonStyle.success, row=3)
            evolve_button.callback = self._on_evolve
            self.add_item(evolve_button)
        elif self._has_dupes_for_star_up(keep, name_counts):
            required = servants.STAR_UP_DUPLICATES_REQUIRED[keep["star_level"]]
            dupes = [i for i in instances if i["name"] == keep["name"] and i["instance_id"] != keep["instance_id"]]
            dupe_options = [discord.SelectOption(label=_instance_label(i)[:100], value=str(i["instance_id"])) for i in dupes[:PAGE_SIZE]]
            dupe_select = discord.ui.Select(
                placeholder=f"Choose exactly {required} duplicate(s) to consume...",
                options=dupe_options, min_values=required, max_values=required, row=3,
            )
            dupe_select.callback = self._on_pick_consume
            self.add_item(dupe_select)

            star_up_button = discord.ui.Button(
                label="Star Up", emoji="⭐", style=discord.ButtonStyle.success, row=4,
                disabled=len(self.selected_consume_ids) != required,
            )
            star_up_button.callback = self._on_star_up
            self.add_item(star_up_button)

        if keep["level"] < servants.SERVANT_MAX_LEVEL:
            level_up_button = discord.ui.Button(
                label=f"Level Up ({keep['level']}→{keep['level'] + 1})", emoji="🔺", style=discord.ButtonStyle.primary, row=4,
            )
            level_up_button.callback = self._on_level_up
            self.add_item(level_up_button)

    def _build_equip_components(self):
        slot_options = [
            discord.SelectOption(label="Support", value=servants.SLOT_KEY_SUPPORT, default=(self.selected_slot == servants.SLOT_KEY_SUPPORT)),
            discord.SelectOption(label="Combat", value=servants.SLOT_KEY_COMBAT, default=(self.selected_slot == servants.SLOT_KEY_COMBAT)),
        ]
        slot_select = discord.ui.Select(placeholder="Choose a slot...", options=slot_options, row=1)
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
            disabled=not instance_options, row=2,
        )
        instance_select.callback = self._on_pick_equip_instance
        self.add_item(instance_select)
        if total_pages > 1:
            prev_button = discord.ui.Button(label="◀ Prev", row=3, disabled=self.equip_page == 0)
            prev_button.callback = self._make_equip_page_callback(-1)
            self.add_item(prev_button)
            next_button = discord.ui.Button(label="Next ▶", row=3, disabled=self.equip_page >= total_pages - 1)
            next_button.callback = self._make_equip_page_callback(1)
            self.add_item(next_button)

        equip_button = discord.ui.Button(label="Equip", emoji="⚔️", style=discord.ButtonStyle.success, row=4, disabled=not instance_options)
        equip_button.callback = self._on_equip
        self.add_item(equip_button)
        unequip_button = discord.ui.Button(label="Unequip Slot", emoji="🗑️", style=discord.ButtonStyle.danger, row=4)
        unequip_button.callback = self._on_unequip
        self.add_item(unequip_button)

    def _build_automation_components(self):
        duty_options = [discord.SelectOption(label=label, value=key, default=(key == self.selected_duty)) for key, label in DUTY_LABELS.items()]
        duty_select = discord.ui.Select(placeholder="Choose a duty...", options=duty_options, row=1)
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
            disabled=not instance_options, row=2,
        )
        instance_select.callback = self._on_pick_automation_instance
        self.add_item(instance_select)
        if total_pages > 1:
            prev_button = discord.ui.Button(label="◀ Prev", row=3, disabled=self.automation_page == 0)
            prev_button.callback = self._make_automation_page_callback(-1)
            self.add_item(prev_button)
            next_button = discord.ui.Button(label="Next ▶", row=3, disabled=self.automation_page >= total_pages - 1)
            next_button.callback = self._make_automation_page_callback(1)
            self.add_item(next_button)

        assigned = [i for i in instances if i["automation_duty"] is not None]
        assign_button = discord.ui.Button(
            label="Assign", emoji="📌", style=discord.ButtonStyle.success, row=4,
            disabled=not instance_options or len(assigned) >= servants.MAX_AUTOMATION_SERVANTS,
        )
        assign_button.callback = self._on_assign_duty
        self.add_item(assign_button)
        for instance in assigned[:4]:
            stop_button = discord.ui.Button(label=f"Stop #{instance['instance_id']}", style=discord.ButtonStyle.danger, row=4)
            stop_button.callback = self._make_unassign_callback(instance["instance_id"])
            self.add_item(stop_button)

    # -- callbacks: summon ----------------------------------------------------------------------

    async def _on_pick_currency(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select) and child.row == 1)
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

    # -- callbacks: star up / evolve ---------------------------------------------------------

    async def _on_pick_keep(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select) and child.row == 1)
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

    async def _on_evolve(self, interaction: discord.Interaction):
        if self.selected_keep_id:
            _, self.last_result = await asyncio.to_thread(self.game.evolve_servant, self.user_id, self.selected_keep_id)
        self.selected_keep_id = None
        self.selected_consume_ids = []
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_level_up(self, interaction: discord.Interaction):
        if self.selected_keep_id:
            _, self.last_result = await asyncio.to_thread(self.game.level_up_servant, self.user_id, self.selected_keep_id)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    # -- callbacks: equip -------------------------------------------------------------------

    async def _on_pick_slot(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select) and child.row == 1)
        self.selected_slot = select.values[0]
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_equip_instance(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select) and child.row == 2)
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
        select = next(child for child in self.children if isinstance(child, discord.ui.Select) and child.row == 1)
        self.selected_duty = select.values[0]
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_automation_instance(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select) and child.row == 2)
        self.selected_automation_id = int(select.values[0])
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def _make_automation_page_callback(self, delta: int):
        async def callback(interaction: discord.Interaction):
            self.automation_page += delta
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

    # -- embed --------------------------------------------------------------------------------

    def build_embed(self) -> discord.Embed:
        if self.active_tab == "summon":
            embed = self._summon_embed()
        elif self.active_tab == "roster":
            embed = self._roster_embed()
        elif self.active_tab == "star_up":
            embed = self._star_up_embed()
        elif self.active_tab == "equip":
            embed = self._equip_embed()
        else:
            embed = self._automation_embed()
        if self.last_result:
            embed.add_field(name="Result", value=self.last_result, inline=False)
        return embed

    def _summon_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"🎴 {self.display_name}'s Servant Summon",
            description=(
                "**[Admin Preview]** Roll for a servant across 7 tiers "
                "(T1 36.9% · T2 26% · T3 18% · T4 12% · T5 6% · T6 1% · T7 0.1%).\n\n"
                f"Currency: **{CURRENCY_LABELS[self.selected_currency]}** "
                f"({servants.SUMMON_CURRENCY_COST[self.selected_currency]}/summon)"
            ),
            color=discord.Color.gold(),
        )
        if self.last_rolled:
            lines = "\n".join(f"{servants.TIER_EMOJI.get(tier, '')} **{name}** (Tier {tier})" for name, tier in self.last_rolled)
            embed.add_field(name="Pull Results", value=lines, inline=False)
        return embed

    def _roster_embed(self) -> discord.Embed:
        instances = self.game.get_player_servants(self.user_id)
        filtered = self._roster_filtered(instances)
        shown, page, total_pages = self._paginate(filtered, self.roster_page, page_size=15)
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
                lines.append(_instance_label(i) + (f" — {', '.join(tags)}" if tags else ""))
            embed.add_field(name=field_name, value="\n".join(lines), inline=False)
        else:
            embed.add_field(name=field_name, value="No servants yet — summon one!" if not instances else "None of this tier.", inline=False)
        return embed

    def _star_up_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"⭐ {self.display_name}'s Star Up",
            description=(
                "Consume exact-name duplicates to advance a servant's star level (1★→7★), or feed "
                "materials to Level it up (1-10, independent of duplicates). A maxed Tier 5/6 "
                "servant at ★7 can evolve into a fresh Tier 6/7 named identity instead."
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
                lines.append(f"✅ Ready to evolve into a random Tier {keep['tier'] + 1} servant!")
            elif keep["star_level"] < servants.MAX_STAR_LEVEL:
                required = servants.STAR_UP_DUPLICATES_REQUIRED[keep["star_level"]]
                dupes_owned = len([i for i in instances if i["name"] == keep["name"] and i["instance_id"] != keep["instance_id"]])
                if dupes_owned >= required:
                    lines.append(f"★{keep['star_level']} → ★{keep['star_level'] + 1}: choose **{required}** duplicate(s) below.")
                else:
                    lines.append(f"★{keep['star_level']} → ★{keep['star_level'] + 1} needs **{required}** duplicate(s) (you own {dupes_owned}).")
            else:
                lines.append("Star level maxed.")

            if keep["level"] < servants.SERVANT_MAX_LEVEL:
                recipe = servants.level_up_recipe(keep["tier"], keep["level"])
                stones_cost = servants.level_up_stones_cost(keep["tier"], keep["level"])
                recipe_text = ", ".join(f"{qty}x {item}" for item, qty in recipe.items())
                lines.append(f"Level {keep['level']} → {keep['level'] + 1}: {format_number(stones_cost)} Spirit Stones + {recipe_text}")
            else:
                lines.append("Level maxed.")

            embed.add_field(name=keep["name"], value="\n".join(lines), inline=False)
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
        return embed

    def _automation_embed(self) -> discord.Embed:
        instances = self.game.get_player_servants(self.user_id)
        assigned = [i for i in instances if i["automation_duty"] is not None]
        embed = discord.Embed(
            title=f"⚙️ {self.display_name}'s Servant Automation",
            description=(
                f"**{len(assigned)} / {servants.MAX_AUTOMATION_SERVANTS}** servants on duty. Each assigned servant "
                "triggers one mine/gather/farm cycle per real day on your behalf."
            ),
            color=discord.Color.gold(),
        )
        if assigned:
            lines = [f"{_instance_label(i)} — {DUTY_LABELS.get(i['automation_duty'], i['automation_duty'])} duty" for i in assigned]
            embed.add_field(name="On Duty", value="\n".join(lines), inline=False)
        return embed
