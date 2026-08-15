import asyncio
import time
from typing import Optional

import discord

from . import avatar, chargen, combat, equipment, gathering, professions, realms
from .base_view import GameView
from .character_class import get_character_class
from .character_data import PHYSIQUE_TIERS, ROOT_TIERS
from .items import ITEM_CATEGORIES, item_emoji, items_in_category, subcategories_in_category
from .manual_view import EFFECT_LABELS
from .ui_utils import format_number, render_bar


def _inventory_item_emoji(item_name: str) -> str:
    """Tiered materials (Ore/Herb/Beast Core/Beast Material — anything "Tier N ...") get the
    same rarity-color emoji /mine and /gather already show in their collected-haul summary
    (see gathering.TIER_EMOJI); everything else falls back to items.item_emoji's
    category/subcategory emoji."""
    tier = gathering.item_tier(item_name)
    return gathering.TIER_EMOJI[tier] if tier else item_emoji(item_name)


def _default_subcategory(category: str) -> Optional[str]:
    subs = subcategories_in_category(category)
    return subs[0] if subs else None


def _build_category_buttons(active_category: str, row: int, callback_factory, categories=None):
    buttons = []
    for category in (categories if categories is not None else ITEM_CATEGORIES):
        button = discord.ui.Button(label=category, custom_id=f"cat:{category}", row=row)
        is_active = category == active_category
        button.style = discord.ButtonStyle.primary if is_active else discord.ButtonStyle.secondary
        button.disabled = is_active
        button.callback = callback_factory(category)
        buttons.append(button)
    return buttons


def _build_subcategory_buttons(active_category: str, active_subcategory: str, row_start: int, callback_factory):
    """Returns (buttons, rows_used). Materials' subcategory count has grown past 5 (Beast
    Trophy/Alchemy Root were added for /sell) -- Discord caps buttons at 5 per row, so this
    spreads them across as many rows as needed starting at row_start, mirroring
    trading._build_trade_subcategory_buttons' own wrapping (the fix that already protects
    /trade from this exact issue). The caller uses rows_used to know which row is free next."""
    buttons = []
    subcategories = subcategories_in_category(active_category)
    for index, subcategory in enumerate(subcategories):
        button = discord.ui.Button(label=subcategory, custom_id=f"subcat:{subcategory}", row=row_start + index // 5)
        is_active = subcategory == active_subcategory
        button.style = discord.ButtonStyle.primary if is_active else discord.ButtonStyle.secondary
        button.disabled = is_active
        button.callback = callback_factory(subcategory)
        buttons.append(button)
    rows_used = (len(subcategories) - 1) // 5 + 1 if subcategories else 0
    return buttons, rows_used


def _build_subcategory_select(active_category: str, active_subcategory: Optional[str], row: int, on_select) -> discord.ui.Select:
    """Single-row alternative to _build_subcategory_buttons for views with no row headroom to
    spare for wrapping (see ProfileView's inventory tab -- its 2 rows of top-level profile
    tabs plus category/select rows leave exactly zero slack, unlike standalone /inventory)."""
    subcategories = subcategories_in_category(active_category)
    options = [
        discord.SelectOption(label=subcategory, value=subcategory, default=(subcategory == active_subcategory))
        for subcategory in subcategories
    ]
    select = discord.ui.Select(placeholder="Choose a subcategory...", options=options or [discord.SelectOption(label="None", value="none")], disabled=not options, row=row)
    select.callback = on_select
    return select


def _build_item_select(game, user_id: int, active_category: str, active_subcategory: Optional[str], row: int, on_select, selected: Optional[str] = None, placeholder: str = "Use an item..."):
    inventory = game.get_inventory(user_id)
    options = [
        discord.SelectOption(
            label=f"{item.name} x{inventory[item.name]}", value=item.name, description=item.description[:100],
            default=(item.name == selected),
        )
        for item in items_in_category(active_category, active_subcategory)
        if inventory.get(item.name, 0) > 0
    ]
    select = discord.ui.Select(
        placeholder=placeholder if options else "No items here",
        # Capped at Discord's 25-option limit on a Select — see hunt.py's Gu/potion selects
        # for the same fix, hit in practice for an active player's item counts.
        options=options[:25] or [discord.SelectOption(label="None", value="none")],
        disabled=not options,
        row=row,
    )
    select.callback = on_select
    return select


def _build_inventory_embed(title_prefix: str, game, user_id: int, category: str, subcategory: Optional[str], result: Optional[str]) -> discord.Embed:
    inventory = game.get_inventory(user_id)
    owned = [item for item in items_in_category(category, subcategory) if inventory.get(item.name, 0) > 0]
    # Tiered items (Tier 1-7 Ore/Herb/Beast Core/Beast Material) sort ascending by tier
    # first, same order /gather's collected-haul summary uses; anything untiered follows,
    # alphabetically.
    owned.sort(key=lambda item: (gathering.item_tier(item.name) is None, gathering.item_tier(item.name) or 0, item.name))
    lines = []
    for item in owned:
        quantity = inventory[item.name]
        rank_tag = f" (Rank {item.rank})" if item.rank else ""
        lines.append(f"{_inventory_item_emoji(item.name)} **{item.name}**{rank_tag} x{quantity} — {item.description}")
    description = "\n".join(lines) if lines else "You have no items here yet."

    label = f"{category} — {subcategory}" if subcategory else category
    embed = discord.Embed(title=f"{title_prefix} — {label}", description=description, color=discord.Color.dark_purple())
    if result:
        embed.add_field(name="Result", value=result, inline=False)
    return embed


class ProfileView(GameView):
    TABS = [
        ("overview", "Overview", None),
        ("qi", "Qi", "⚡"),
        ("combat", "Combat", "⚔️"),
        ("breakthrough", "Breakthrough", "🌟"),
        ("buffs", "Buffs", "✨"),
        ("inventory", "Inventory", "🎒"),
        ("professions", "Professions", "🎓"),
        ("avatar", "Avatar", "🌌"),
    ]

    def __init__(self, user_id: int, game, player, display_name: str, avatar_url: str, viewer_id: Optional[int] = None):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.game = game
        self.db = game.db
        self.player = player
        self.display_name = display_name
        self.avatar_url = avatar_url
        # viewer_id is whoever is clicking the buttons — normally the profile owner, but
        # /profile @someone lets a different viewer browse a read-only copy of their tabs.
        self.viewer_id = viewer_id if viewer_id is not None else user_id
        self.own_profile = self.viewer_id == self.user_id
        self.active_tab = "overview"
        self.inventory_category = ITEM_CATEGORIES[0]
        self.inventory_subcategory = _default_subcategory(self.inventory_category)
        self.inventory_result: Optional[str] = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.viewer_id:
            await interaction.response.send_message("This isn't your profile to view.", ephemeral=True)
            return False
        return True

    def _selection_objects(self):
        p = self.player
        return (
            chargen.get_race(p["race"]),
            chargen.get_root_tier(p["root_tier"]),
            chargen.get_physique_tier(p["physique_tier"]),
            chargen.get_path(p["cultivation_path"]),
        )

    def _build_components(self):
        self.clear_items()
        for index, (key, label, emoji) in enumerate(self.TABS):
            button = discord.ui.Button(label=label, emoji=emoji, custom_id=key, row=0 if index < 3 else 1)
            is_active = key == self.active_tab
            button.style = discord.ButtonStyle.primary if is_active else discord.ButtonStyle.secondary
            button.disabled = is_active
            button.callback = self._make_tab_callback(key)
            self.add_item(button)

        if self.active_tab == "inventory":
            for button in _build_category_buttons(self.inventory_category, row=2, callback_factory=self._make_inventory_category_callback):
                self.add_item(button)
            next_row = 3
            if subcategories_in_category(self.inventory_category):
                # A Select here, not button rows (contrast InventoryView's own standalone
                # /inventory command) -- the 2 rows of profile tabs above leave zero row
                # headroom to wrap subcategory buttons across multiple rows the way
                # views._build_subcategory_buttons now does, so this needs a layout that
                # always fits in exactly one row regardless of subcategory count.
                self.add_item(_build_subcategory_select(self.inventory_category, self.inventory_subcategory, row=3, on_select=self._on_inventory_subcategory_select))
                next_row = 4
            # Using items only makes sense on your own inventory — someone browsing another
            # player's profile gets a read-only list, no select to act on it.
            if self.own_profile:
                self.add_item(_build_item_select(self.game, self.user_id, self.inventory_category, self.inventory_subcategory, row=next_row, on_select=self._on_use_item))

    def _make_tab_callback(self, key: str):
        async def callback(interaction: discord.Interaction):
            self.active_tab = key
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    def _make_inventory_category_callback(self, category: str):
        async def callback(interaction: discord.Interaction):
            self.inventory_category = category
            self.inventory_subcategory = _default_subcategory(category)
            self.inventory_result = None
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    async def _on_inventory_subcategory_select(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select) and child.row == 3)
        value = select.values[0]
        self.inventory_subcategory = None if value == "none" else value
        self.inventory_result = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_use_item(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select))
        item_name = select.values[0]
        _, self.inventory_result = await asyncio.to_thread(self.game.use_item, self.user_id, self.display_name, item_name)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def build_embed(self) -> discord.Embed:
        return {
            "overview": self._overview_embed,
            "qi": self._qi_embed,
            "combat": self._combat_embed,
            "breakthrough": self._breakthrough_embed,
            "buffs": self._buffs_embed,
            "inventory": self._inventory_embed,
            "professions": self._professions_embed,
            "avatar": self._avatar_embed,
        }[self.active_tab]()

    def _overview_embed(self) -> discord.Embed:
        p = self.player
        embed = discord.Embed(
            title=f"{p['character_name'] or self.display_name}'s Cultivation Profile",
            description=(
                f"🩸 **{p['race']}** • ⚔️ **{p['cultivation_path']}** (Rank {p['path_rank']})\n"
                f"🧬 Aptitude: **{p['aptitude']}**/100"
            ),
            color=discord.Color.dark_purple(),
        )
        embed.set_thumbnail(url=self.avatar_url)
        embed.add_field(
            name="📊 Cultivation Stats",
            value=(
                f"🏔️ **Realm Index:** {p['realm_index']}\n"
                f"💠 **Primeval Essence:** {format_number(p['primeval_essence'])}/{format_number(self.db.get_effective_max_essence(self.user_id))}\n"
                f"🪙 **Spirit Stones:** {format_number(p['spirit_stones'])}\n"
                f"❤️ **HP:** {format_number(p['hp'])}/{format_number(p['max_hp'])}"
            ),
            inline=False,
        )
        embed.set_footer(text="Aptitude assigned on first join")
        return embed

    def _qi_embed(self) -> discord.Embed:
        p = self.player
        race, root_tier, physique_tier, path = self._selection_objects()
        rate_bonus = chargen.effective_qi_rate_bonus(race, root_tier, physique_tier, path)
        description = (
            f"⚡ **Total Qi:** {format_number(p['qi'])}\n"
            f"✨ **Qi Multiplier (elixirs/pellets):** x{p['qi_multiplier']:.2f}\n"
            f"🌿 **Cultivation Speed + Qi Recovery Bonus:** +{rate_bonus * 100:.1f}%\n"
            f"　　_(from race, root, physique, and cultivation path)_\n"
            f"📈 **Base Rate:** {p['aptitude']} aptitude × {self.db.BASE_QI_PER_MINUTE_PER_APTITUDE}/min"
        )
        embed = discord.Embed(title=f"{self.display_name} — ⚡ Qi", description=description, color=discord.Color.dark_purple())
        embed.set_thumbnail(url=self.avatar_url)
        return embed

    def _combat_embed(self) -> discord.Embed:
        p = self.player
        # self.player is the raw base-stat row (see GameManager.get_player_stats) -- equipped
        # gear/Gu bonuses (including Twin Gu Sovereign Physique's second Gu slot, which has NO
        # baseline of its own, only ever shows up as a bonus here) live entirely in
        # compute_equipment_bonuses and must be folded in explicitly, same pattern
        # equipment_view.py's own build_embed already uses for its Total Stats line.
        bonus = self.game.compute_equipment_bonuses(self.user_id)["stats"]
        atk = p["atk_stat"] + bonus["atk_stat"]
        str_ = p["str_stat"] + bonus["str_stat"]
        spd = p["spd_stat"] + bonus["spd_stat"]
        def_ = p["def_stat"] + bonus["def_stat"]
        luck = p["luck_stat"] + bonus["luck_stat"]
        qi = p["qi_stat"] + bonus["qi_stat"]
        # hp is an overlay on both current and max equally (same convention hunt.py/pvp_view.py/
        # raid.py already use for this exact bonus key) rather than a flat add to current HP alone.
        hp = p["hp"] + bonus["hp"]
        max_hp = p["max_hp"] + bonus["hp"]

        embed = discord.Embed(title=f"{self.display_name} — ⚔️ Combat", color=discord.Color.dark_purple())
        embed.set_thumbnail(url=self.avatar_url)

        character_class = get_character_class(p["character_class"])
        if character_class:
            embed.add_field(
                name="🎭 Class",
                value=(
                    f"{character_class.emoji} **{character_class.name}** ({character_class.role})\n"
                    f"Passive — {character_class.passive_name}: {character_class.passive_text}\n"
                    f"Raid Ability — {character_class.ability_name}: {character_class.ability_text}"
                ),
                inline=False,
            )
        else:
            embed.add_field(name="🎭 Class", value="No class chosen yet — run `/choose_class` to unlock a raid ability.", inline=False)

        embed.add_field(
            name="Stats (base + gear/Gu)",
            value=(
                f"❤️ **HP** {format_number(hp, decimals=0)}/{format_number(max_hp, decimals=0)}\n"
                f"🎯 **ATK** {format_number(atk, decimals=0)} ⚔️ **STR** {format_number(str_, decimals=0)}\n"
                f"🏃 **SPD** {format_number(spd, decimals=0)} 🛡️ **DEF** {format_number(def_, decimals=0)}\n"
                f"🍀 **LCK** {format_number(luck, decimals=0)} 💧 **QI** {format_number(qi, decimals=0)}"
            ),
            inline=False,
        )
        embed.add_field(
            name="What they do",
            value=(
                f"🎯 Hit Chance: **{combat.hit_chance(atk) * 100:.0f}%**\n"
                f"🏃 Dodge Chance: **{combat.dodge_chance(spd) * 100:.0f}%**\n"
                f"🍀 Crit Chance: **{combat.crit_chance(luck) * 100:.0f}%** (x{combat.CRIT_DAMAGE_MULTIPLIER:.1f} damage)\n"
                f"⚔️ Damage: **~{format_number(str_ * combat.DAMAGE_PER_STR, decimals=0)}** before enemy DEF\n"
                f"🛡️ Damage Reduction: **{format_number(combat.damage_reduction(def_), decimals=1)}** flat, off incoming hits"
            ),
            inline=False,
        )
        embed.set_footer(text="Includes equipped gear/Gu bonuses (and a 2nd Gu slot's, if Twin Gu Sovereign Physique is active) — these are the formulas combat actually uses.")
        return embed

    def _breakthrough_embed(self) -> discord.Embed:
        p = self.player
        race, root_tier, physique_tier, path = self._selection_objects()
        chance = chargen.effective_breakthrough_chance(race, root_tier, physique_tier, path, p["luck_stat"])
        current_realm = realms.realm_name(p["realm_index"])

        embed = discord.Embed(title=f"{self.display_name} — 🌟 Breakthrough", color=discord.Color.dark_purple())
        embed.set_thumbnail(url=self.avatar_url)

        if realms.is_max_realm(p["realm_index"]):
            embed.description = (
                f"**{current_realm}** — you've reached the peak of known cultivation... for now.\n"
                f"💠 **Qi Banked:** {format_number(p['qi'])} — still accruing, ready to carry over the moment a realm above this one exists."
            )
            return embed

        next_realm = realms.realm_name(p["realm_index"] + 1)
        next_description = realms.realm_description(p["realm_index"] + 1)
        qi_required = realms.qi_required_for_next(p["realm_index"])
        power_multiplier = realms.stat_multiplier_for_next(p["realm_index"])
        crossing_note = " — a Great Realm breakthrough!" if realms.is_great_realm_crossing(p["realm_index"]) else ""
        growth_preview = " • ".join(
            f"{chargen.STAT_LABELS[key]} +{format_number(amount)}" for key, amount in chargen.project_power_growth(p, power_multiplier).items()
        )
        percent = min(100, p["qi"] / qi_required * 100)
        embed.description = (
            f"**{current_realm}** → **{next_realm}**{crossing_note}\n"
            f"_{next_description}_\n"
            f"💠 **Qi:** {format_number(p['qi'])} / {format_number(qi_required)} required\n"
            f"`{render_bar(p['qi'], qi_required)}` {percent:.1f}%\n"
            f"💪 **Power Growth on Success:** {growth_preview}\n"
            "Use `/breakthrough` to attempt it!"
        )

        bonus_lines = [f"Base: {chargen.BASE_BREAKTHROUGH_CHANCE * 100:.0f}%"]
        for label, source in (("Race", race), ("Root", root_tier), ("Physique", physique_tier), ("Path", path)):
            bonus = getattr(source, "stat_bonuses", {}).get("breakthrough_chance_pct", 0) if source else 0
            if bonus:
                bonus_lines.append(f"{label}: +{bonus * 100:.0f}%")
        luck_bonus = p["luck_stat"] * chargen.LUCK_BREAKTHROUGH_CHANCE_PER_POINT
        if luck_bonus:
            bonus_lines.append(f"Luck ({format_number(p['luck_stat'])}): +{luck_bonus * 100:.1f}%")
        bonus_lines.append(f"**Total: {chance * 100:.1f}%**")
        embed.add_field(name="🎲 Breakthrough Chance Buffs", value="\n".join(bonus_lines), inline=False)
        return embed

    def _manual_bonuses_text(self) -> str:
        """What your equipped manual(s) are actually granting right now — the permanent,
        no-expiry counterpart to the Active Buffs list below (see database._qi_rate_
        components for how the underlying numbers are weighted -- both slots equally -- and
        cultivation-capped)."""
        p = self.player
        qi_status = self.db.get_qi_status(self.user_id)
        lines = []
        for manual_id, tag in ((p["equipped_primary_manual_id"], "Primary"), (p["equipped_auxiliary_manual_id"], "Auxiliary")):
            if not manual_id:
                continue
            manual = self.db.get_manual(manual_id)
            if manual:
                lines.append(f"📗 {tag}: **{manual['name']}** — Rank {manual['rank']} {manual['rarity']}")
        # The old legacy "manual" equip slot, checked directly (NOT via qi_status["manual_name"]
        # — that's now every equipped manual's name joined together, primary/auxiliary included,
        # see _qi_rate_components) so this line only ever fires for an actual legacy item.
        legacy_item_name = self.db.get_equipped(self.user_id).get("manual")
        if legacy_item_name:
            lines.append(f"📖 Legacy slot: **{legacy_item_name}**")
        if not lines:
            return "No manual equipped — assemble one with `/manual`!"

        if qi_status["manual_bonus"]:
            lines.append(f"🌿 **Cultivation Speed**: +{qi_status['manual_bonus'] * 100:.1f}%")
        for key, value in qi_status.get("manual_effect_bonuses", {}).items():
            if not value:
                continue
            label = EFFECT_LABELS.get(key, key.replace("_", " ").title())
            lines.append(f"✨ **{label}**: +{value * 100:.2f}%")
        return "\n".join(lines)[:1024]

    def _buffs_embed(self) -> discord.Embed:
        p = self.player
        _, root_tier, physique_tier, _ = self._selection_objects()
        embed = discord.Embed(title=f"{self.display_name} — ✨ Buffs", color=discord.Color.dark_purple())
        embed.set_thumbnail(url=self.avatar_url)

        if root_tier:
            value = f"{root_tier.emoji} **{p['root_name']}** ({root_tier.name})\n" + "\n".join(root_tier.display_bonuses)
            if root_tier.passive:
                value += f"\nPassive: {root_tier.passive}"
            unique = chargen.unique_passive(ROOT_TIERS, p["root_tier"], p["root_name"])
            if unique:
                value += f"\n✨ {unique}"
            root_spec = chargen.get_root_spec(p["root_name"])
            if root_spec:
                value += f"\n🔹 {root_spec.description}"
            embed.add_field(name="🌱 Root", value=value, inline=False)

        if physique_tier:
            value = f"{physique_tier.emoji} **{p['physique_name']}** ({physique_tier.name})\n" + "\n".join(physique_tier.display_bonuses)
            if physique_tier.passive:
                value += f"\nPassive: {physique_tier.passive}"
            unique = chargen.unique_passive(PHYSIQUE_TIERS, p["physique_tier"], p["physique_name"])
            if unique:
                value += f"\n✨ {unique}"
            physique_spec = chargen.get_physique_spec(p["physique_name"])
            if physique_spec:
                value += f"\n🔹 {physique_spec.description}"
            embed.add_field(name="💪 Physique", value=value, inline=False)

        embed.add_field(name="📖 Manual Bonuses", value=self._manual_bonuses_text(), inline=False)

        buffs = self.db.get_active_buffs(self.user_id)
        now = int(time.time())
        if buffs:
            # Grouped by name (same reasoning as /qi and /cd's Active Buffs field) — each pill
            # use is its own buff row, so this avoids one line per use blowing past Discord's
            # 1024-char field limit when someone's stacked a lot of the same pill.
            grouped = {}
            for buff in buffs:
                entry = grouped.setdefault(buff["name"], {"count": 0, "bonus_each": buff["qi_multiplier_bonus"], "max_remaining": 0})
                entry["count"] += 1
                entry["max_remaining"] = max(entry["max_remaining"], buff["expires_at"] - now)
            lines = []
            for name, entry in grouped.items():
                minutes_left = max(0, entry["max_remaining"] // 60)
                if entry["count"] > 1:
                    total_bonus = entry["bonus_each"] * entry["count"]
                    lines.append(
                        f"✨ **{name}** x{entry['count']} — +{entry['bonus_each']:.2f} each "
                        f"(+{total_bonus:.2f} total), up to {minutes_left}m left"
                    )
                else:
                    lines.append(f"✨ **{name}** — +{entry['bonus_each']:.2f} qi multiplier ({minutes_left}m left)")
            value = "\n".join(lines)[:1024]
        else:
            value = "No active timed buffs. Try a pill from the Inventory tab!"
        embed.add_field(name="⏳ Active Buffs", value=value, inline=False)
        return embed

    def _inventory_embed(self) -> discord.Embed:
        embed = _build_inventory_embed(
            f"{self.display_name}'s Inventory", self.game, self.user_id,
            self.inventory_category, self.inventory_subcategory, self.inventory_result,
        )
        embed.set_thumbnail(url=self.avatar_url)
        return embed

    def _professions_embed(self) -> discord.Embed:
        p = self.player
        embed = discord.Embed(title=f"{self.display_name} — 🎓 Professions", color=discord.Color.dark_purple())
        embed.set_thumbnail(url=self.avatar_url)

        lines = []
        for prof in professions.PROFESSIONS:
            rank_index = p[professions.RANK_COLUMN[prof]]
            lines.append(f"**{prof}**: {professions.rank_name(rank_index)} ({rank_index}/{professions.MAX_RANK_INDEX})")
        embed.add_field(name="Ranks", value="\n".join(lines), inline=False)

        if p["studying_profession"]:
            rank_index = p[professions.RANK_COLUMN[p["studying_profession"]]]
            required = professions.hours_required(rank_index)
            elapsed = (time.time() - p["studying_started_ts"]) / 3600
            if required:
                remaining = max(0, required - elapsed)
                pct = min(100, elapsed / required * 100)
                value = f"**{p['studying_profession']}** — `{render_bar(elapsed, required)}` {pct:.0f}% ({remaining:.1f}h left)"
            else:
                value = f"**{p['studying_profession']}**"
        else:
            value = "Nothing — use `/study` to begin advancing a profession."
        embed.add_field(name="📖 Currently Studying", value=value, inline=False)

        embed.set_footer(text="Miner/Gatherer/Farmer ranks boost gathering yield; Explorer rank improves /explore odds; Alchemist/Blacksmith/Gu Refiner rank boosts /alchemy, /blacksmith, and /gu_pet success chance.")
        return embed

    def _avatar_embed(self) -> discord.Embed:
        p = self.player
        embed = discord.Embed(title=f"{self.display_name} — 🌌 Avatar", color=discord.Color.dark_purple())
        embed.set_thumbnail(url=self.avatar_url)

        great_realm_index = realms.STAGES[p["realm_index"]].great_realm_index
        if not avatar.is_realm_eligible(great_realm_index):
            embed.add_field(
                name="🔒 Locked",
                value="Your Nascent Soul avatar awakens once you reach **Nascent Soul** realm — keep cultivating!",
                inline=False,
            )
            return embed

        soul = avatar.get_avatar_soul(p["avatar_soul"])
        if soul is None:
            embed.description = "Your avatar hasn't chosen a soul yet — run `/avatar` to awaken it."
            return embed

        embed.description = f"{soul.emoji} **{soul.name}** — Level **{avatar.level_name(p['avatar_level'])}**"
        embed.add_field(name=f"Passive — {soul.passive_name}", value=soul.passive_text, inline=False)
        embed.add_field(
            name=f"🌀 {avatar.SOUL_PROJECTION_NAME}",
            value=f"{soul.ability_text}\n*Costs {format_number(avatar.SOUL_PROJECTION_QI_COST)} battle Qi, lasts {avatar.SOUL_PROJECTION_DURATION_TURNS} turns — not usable in combat yet, coming in a future update.*",
            inline=False,
        )
        embed.set_footer(text="Run /avatar to manage gear, feeding, and your soul.")
        return embed


class InventoryView(GameView):
    # "Equipment" isn't a real ITEMS category (gear lives in equipment.EQUIPMENT, not
    # ITEMS) — it's a display-only tab bolted on here so equipped gear/Gu are visible
    # without leaving /inventory. Selecting it swaps the item-select+use row for a
    # read-only gear summary plus a shortcut into the full EquipmentView.
    DISPLAY_CATEGORIES = ITEM_CATEGORIES + ["Equipment"]

    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.active_category = ITEM_CATEGORIES[0]
        self.active_subcategory = _default_subcategory(self.active_category)
        self.selected_item: Optional[str] = None
        self.last_result: Optional[str] = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your inventory.", ephemeral=True)
            return False
        return True

    def _build_components(self):
        self.clear_items()
        for button in _build_category_buttons(self.active_category, row=0, callback_factory=self._make_category_callback, categories=self.DISPLAY_CATEGORIES):
            self.add_item(button)

        if self.active_category == "Equipment":
            manage_button = discord.ui.Button(label="Manage Equipment", emoji="🛡️", style=discord.ButtonStyle.primary, row=1)
            manage_button.callback = self._on_manage_equipment
            self.add_item(manage_button)
            return

        next_row = 1
        if subcategories_in_category(self.active_category):
            buttons, rows_used = _build_subcategory_buttons(self.active_category, self.active_subcategory, row_start=1, callback_factory=self._make_subcategory_callback)
            for button in buttons:
                self.add_item(button)
            next_row = 1 + rows_used
        self.add_item(_build_item_select(
            self.game, self.user_id, self.active_category, self.active_subcategory, row=next_row,
            on_select=self._on_select_item, selected=self.selected_item, placeholder="Select an item to use...",
        ))

        owned = self.game.get_inventory(self.user_id).get(self.selected_item, 0) if self.selected_item else 0
        if owned > 0:
            use_row = next_row + 1
            use1 = discord.ui.Button(label="Use x1", emoji="▶️", style=discord.ButtonStyle.success, row=use_row)
            use1.callback = self._make_use_callback(1)
            self.add_item(use1)

            use10 = discord.ui.Button(label="Use x10", emoji="⏩", style=discord.ButtonStyle.success, row=use_row, disabled=owned < 10)
            use10.callback = self._make_use_callback(10)
            self.add_item(use10)

            use_all = discord.ui.Button(label=f"Use All ({owned})", emoji="⏭️", style=discord.ButtonStyle.success, row=use_row)
            use_all.callback = self._make_use_callback(owned, until_stack_empty=True)
            self.add_item(use_all)

    def _make_category_callback(self, category: str):
        async def callback(interaction: discord.Interaction):
            self.active_category = category
            self.active_subcategory = _default_subcategory(category)
            self.selected_item = None
            self.last_result = None
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    def _make_subcategory_callback(self, subcategory: str):
        async def callback(interaction: discord.Interaction):
            self.active_subcategory = subcategory
            self.selected_item = None
            self.last_result = None
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    async def _on_select_item(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select))
        self.selected_item = select.values[0]
        self.last_result = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def _make_use_callback(self, quantity: int, until_stack_empty: bool = False):
        async def callback(interaction: discord.Interaction):
            # Use All can be hundreds of DB round-trips (see GameManager.use_item_multiple) --
            # defer first so we have up to 15 minutes to finish instead of Discord's normal
            # 3-second ack window (same fix as premium_view.py's "until broke" reroll; without
            # this, a big stack's Use All raises "Unknown interaction" 404 on edit_message once
            # the token's already expired). Now also off the event loop entirely via
            # asyncio.to_thread, so hundreds of round-trips no longer freeze every OTHER
            # user's activity for that same window either.
            await interaction.response.defer()
            item_name = self.selected_item
            used, message = await asyncio.to_thread(
                self.game.use_item_multiple, self.user_id, self.display_name, item_name, quantity, until_stack_empty,
            )
            self.last_result = message if used <= 1 else f"Used **{used}x {item_name}**. {message}"
            inventory = await asyncio.to_thread(self.game.get_inventory, self.user_id)
            if inventory.get(item_name, 0) <= 0:
                self.selected_item = None
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.edit_original_response(embed=embed, view=self)

        return callback

    async def _on_manage_equipment(self, interaction: discord.Interaction):
        from .equipment_view import EquipmentView  # local import: avoids a circular import at module load time

        player = await asyncio.to_thread(self.game.get_player_stats, self.user_id, self.display_name)
        view = EquipmentView( self.user_id, self.game, player, self.display_name, interaction.user.display_avatar.url)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.edit_message(embed=embed, view=view)

    def _equipment_embed(self) -> discord.Embed:
        equipped = self.game.get_equipped(self.user_id)
        equipped_gear_ids = self.game.db.get_equipped_gear_ids(self.user_id)
        lines = []
        for slot_key, label, _, emoji in equipment.SLOTS:
            item_name = equipped.get(slot_key)
            if item_name and slot_key in equipped_gear_ids:
                crafted = self.game.db.get_crafted_gear(equipped_gear_ids[slot_key])
                stats_text = equipment.describe_stat_bonuses(crafted["stat_bonuses"]) if crafted else ""
                lines.append(f"{emoji} **{label}**: {item_name}" + (f" — {stats_text}" if stats_text else ""))
            elif item_name:
                gear = equipment.EQUIPMENT.get(item_name)
                stats_text = equipment.describe_stat_bonuses(gear.stat_bonuses) if gear else ""
                lines.append(f"{emoji} **{label}**: {item_name}" + (f" — {stats_text}" if stats_text else ""))
            else:
                lines.append(f"{emoji} **{label}**: *Empty*")
        embed = discord.Embed(
            title=f"{self.display_name}'s Inventory — Equipment",
            description="\n".join(lines),
            color=discord.Color.dark_purple(),
        )
        embed.set_footer(text="Click Manage Equipment to equip/unequip gear (same as /equipment).")
        return embed

    def build_embed(self) -> discord.Embed:
        if self.active_category == "Equipment":
            return self._equipment_embed()
        return _build_inventory_embed(
            f"{self.display_name}'s Inventory", self.game, self.user_id,
            self.active_category, self.active_subcategory, self.last_result,
        )
