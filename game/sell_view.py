import discord

from . import accessories_data, avatar_gear, blacksmith
from . import equipment as equipment_module
from .base_view import GameView
from .equipment import EQUIPMENT, SLOT_TYPE_EMOJI, gear_power_score
from .gathering import TIER_EMOJI, item_tier
from .items import CATEGORY_EMOJI as _ITEM_CATEGORY_EMOJI
from .items import SUBCATEGORY_EMOJI as _ITEM_SUBCATEGORY_EMOJI
from .items import item_emoji, items_in_category, sell_value, subcategories_in_category

# /sell: a single NPC vendor spanning every domain that has no liquidation path of its own
# (plain stackable Materials/Pills/Healing, catalog Gu) PLUS a thin front end onto the three
# domains that already have their own tuned dismantle/salvage mechanic (crafted_gear,
# accessory/artifact instances, avatar gear instances) — see the /sell design plan for why
# each of those routes into its existing GameManager method rather than a new one.
SELL_CATEGORIES = ["Healing", "Pills", "Materials", "Equipment", "Avatar Gear"]
CATEGORY_EMOJI = {**_ITEM_CATEGORY_EMOJI, "Equipment": "⚔️", "Avatar Gear": "🌀"}

# Manual/other slot types deliberately excluded — see the plan's scope decisions (manuals pay
# a different currency, non-Gu catalog gear isn't a real clutter problem).
EQUIPMENT_SLOT_TYPES = ["Weapon", "Head", "Body", "Ring", "Earring", "Necklace", "Bracelet", "Artifact", "Gu"]
AVATAR_GEAR_SLOT_TYPES = [slot_type for _, _, slot_type, _ in avatar_gear.AVATAR_GEAR_SLOTS]
AVATAR_GEAR_SLOT_TYPE_EMOJI = {slot_type: emoji for _, _, slot_type, emoji in avatar_gear.AVATAR_GEAR_SLOTS}

# Rolled unique instances aren't quantity-tracked catalog items, so a Select option's value is
# prefixed to tell one apart from an ordinary item_name — same convention as
# trading.INSTANCE_VALUE_PREFIX/equipment_view.INSTANCE_VALUE_PREFIX (kept as separate
# constants per that same precedent, since each view only ever interprets its own values).
GEAR_INSTANCE_PREFIX = "gear:"
ACCESSORY_INSTANCE_PREFIX = "accessory:"
AVATAR_INSTANCE_PREFIX = "avatar:"

SELL_BATCH_COUNT = 10


def _item_emoji(item_name: str) -> str:
    """Works for both ITEMS and Equipment names — see items.item_emoji / equipment.SLOT_TYPE_EMOJI."""
    tier = item_tier(item_name)
    if tier:
        return TIER_EMOJI[tier]
    gear = EQUIPMENT.get(item_name)
    if gear is not None:
        return equipment_module.SLOT_TYPE_EMOJI.get(gear.slot_type, "🎒")
    return item_emoji(item_name)


def _subcategories_for(category: str):
    if category == "Equipment":
        return EQUIPMENT_SLOT_TYPES
    if category == "Avatar Gear":
        return AVATAR_GEAR_SLOT_TYPES
    return subcategories_in_category(category)


def _default_sell_subcategory(category: str):
    subs = _subcategories_for(category)
    return subs[0] if subs else None


def _build_category_buttons(active_category: str, callback_factory):
    buttons = []
    for category in SELL_CATEGORIES:
        button = discord.ui.Button(label=category, emoji=CATEGORY_EMOJI.get(category), row=0)
        is_active = category == active_category
        button.style = discord.ButtonStyle.primary if is_active else discord.ButtonStyle.secondary
        button.disabled = is_active
        button.callback = callback_factory(category)
        buttons.append(button)
    return buttons


def _build_subcategory_buttons(active_category: str, active_subcategory: str, row_start: int, callback_factory):
    """Returns (buttons, rows_used). Equipment's 9 slot types and Materials' 7 subcategories
    don't fit on one row (Discord caps buttons at 5 per row), so this spreads them across as
    many rows as needed starting at row_start — mirrors trading._build_trade_subcategory_buttons."""
    names = _subcategories_for(active_category)
    if active_category == "Equipment":
        emoji_map = equipment_module.SLOT_TYPE_EMOJI
    elif active_category == "Avatar Gear":
        emoji_map = AVATAR_GEAR_SLOT_TYPE_EMOJI
    else:
        emoji_map = _ITEM_SUBCATEGORY_EMOJI
    buttons = []
    for index, name in enumerate(names):
        button = discord.ui.Button(label=name, emoji=emoji_map.get(name), row=row_start + index // 5)
        is_active = name == active_subcategory
        button.style = discord.ButtonStyle.primary if is_active else discord.ButtonStyle.secondary
        button.disabled = is_active
        button.callback = callback_factory(name)
        buttons.append(button)
    rows_used = (len(names) - 1) // 5 + 1 if names else 0
    return buttons, rows_used


class SellView(GameView):
    """/sell: an NPC vendor "garbage dump" — sells stackable Materials/Pills/Healing items and
    catalog Gu for a new, deliberately modest spirit-stone price (see items.sell_value), and
    provides a single front end onto the game's existing crafted_gear dismantle / accessory-
    artifact salvage / avatar-gear sell mechanics for unique rolled instances, so every kind of
    unwanted item can be liquidated from one command."""

    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.category = SELL_CATEGORIES[0]
        self.subcategory = _default_sell_subcategory(self.category)
        self.selected: str = None
        self.last_result: str = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Run `/sell` yourself to sell your own items.", ephemeral=True)
            return False
        return True

    def _candidates(self):
        """(sort_key, value, name, emoji, price_text, qty) for everything sellable in the
        current category/subcategory — qty is None for a unique instance (there's only ever
        one of it), or the owned stack size for a plain catalog item. Shared by both the
        Select's options and the embed's listing so the two never drift apart."""
        results = []
        if self.category in ("Healing", "Pills", "Materials"):
            inventory = self.game.get_inventory(self.user_id)
            for item in items_in_category(self.category, self.subcategory):
                qty = inventory.get(item.name, 0)
                if qty <= 0:
                    continue
                price = sell_value(item.name)
                results.append((-price, item.name, item.name, _item_emoji(item.name), f"{price:,} 🪙 each", qty))
        elif self.category == "Equipment" and self.subcategory == "Gu":
            inventory = self.game.get_inventory(self.user_id)
            for name, gear in EQUIPMENT.items():
                if gear.slot_type != "Gu":
                    continue
                qty = inventory.get(name, 0)
                if qty <= 0:
                    continue
                price = equipment_module.gu_breakdown_value(name)
                results.append((-gear_power_score(gear), name, name, _item_emoji(name), f"{price:,} 🪙 each", qty))
        elif self.category == "Equipment" and self.subcategory in ("Weapon", "Head", "Body"):
            equipped_ids = set(self.game.db.get_equipped_gear_ids(self.user_id).values())
            for gear in self.game.get_player_crafted_gear(self.user_id):
                if gear["slot_type"] != self.subcategory or gear["gear_id"] in equipped_ids:
                    continue
                display_name = blacksmith.crafted_gear_display_name(gear["base_type"], gear["tier"], gear["gear_id"])
                stones = blacksmith.dismantle_stones(gear["tier"])
                value = f"{GEAR_INSTANCE_PREFIX}{gear['gear_id']}"
                emoji = SLOT_TYPE_EMOJI.get(gear["slot_type"], "🎒")
                results.append((-gear["power_score"], value, display_name, emoji, f"materials + {stones:,} 🪙", None))
        elif self.category == "Equipment" and self.subcategory in ("Ring", "Earring", "Necklace", "Bracelet", "Artifact"):
            equipped_ids = set(self.game.db.get_equipped_accessory_ids(self.user_id).values())
            for entry in self.game.get_player_accessories_artifacts(self.user_id):
                affix = entry["affix"]
                if affix.slot_type != self.subcategory or entry["instance_id"] in equipped_ids or affix.rarity == "Unique":
                    continue
                rarity_star = accessories_data.RARITY_ORDER.index(affix.rarity) + 1
                stones = affix.rank * rarity_star * self.game.SALVAGE_STONES_PER_RANK_RARITY_STAR
                value = f"{ACCESSORY_INSTANCE_PREFIX}{entry['instance_id']}"
                name = f"{affix.name} #{entry['instance_id']}"
                emoji = SLOT_TYPE_EMOJI.get(affix.slot_type, "💍")
                results.append((-affix.rank, value, name, emoji, f"{stones:,} 🪙", None))
        elif self.category == "Avatar Gear":
            equipped_ids = set(self.game.db.get_avatar_equipped_instance_ids(self.user_id).values())
            for inst in self.game.get_player_avatar_gear_instances(self.user_id):
                if inst["slot_type"] != self.subcategory or inst["instance_id"] in equipped_ids:
                    continue
                display_name = f"{avatar_gear.tier_name(inst['tier'])} {inst['slot_type']} #{inst['instance_id']}"
                stones = avatar_gear.sell_stones(inst["tier"])
                value = f"{AVATAR_INSTANCE_PREFIX}{inst['instance_id']}"
                emoji = AVATAR_GEAR_SLOT_TYPE_EMOJI.get(inst["slot_type"], "🔮")
                results.append((-inst["power_score"], value, display_name, emoji, f"{stones:,} 🪙", None))
        results.sort(key=lambda c: c[0])
        return results

    def _build_item_select(self, row: int) -> discord.ui.Select:
        candidates = self._candidates()
        options = [
            discord.SelectOption(
                label=(f"{emoji} {name} x{qty}" if qty is not None else f"{emoji} {name}")[:100],
                value=value,
                description=price_text[:100],
                default=(value == self.selected),
            )
            for _, value, name, emoji, price_text, qty in candidates
        ]
        select = discord.ui.Select(
            placeholder="Choose an item to sell..." if options else "Nothing to sell here",
            options=options[:25] or [discord.SelectOption(label="None", value="none")],
            disabled=not options,
            row=row,
        )
        select.callback = self._on_pick_item
        return select

    def _same_tier_gear_ids(self, slot_type: str, tier: int) -> list:
        equipped_ids = set(self.game.db.get_equipped_gear_ids(self.user_id).values())
        return [
            g["gear_id"] for g in self.game.get_player_crafted_gear(self.user_id)
            if g["slot_type"] == slot_type and g["tier"] == tier and g["gear_id"] not in equipped_ids
        ]

    def _same_tier_avatar_gear_ids(self, slot_type: str, tier: int) -> list:
        equipped_ids = set(self.game.db.get_avatar_equipped_instance_ids(self.user_id).values())
        return [
            i["instance_id"] for i in self.game.get_player_avatar_gear_instances(self.user_id)
            if i["slot_type"] == slot_type and i["tier"] == tier and i["instance_id"] not in equipped_ids
        ]

    def _same_name_accessory_ids(self, item_id: str) -> list:
        """Accessories/artifacts have no tier — every instance of the same item_id already
        shares the same rank+rarity (both live on the static Affix, not the instance row), so
        grouping by name is the accessory equivalent of crafted gear/avatar gear's "same
        tier" bulk sell. Unique-rarity instances are excluded -- salvage_accessory_artifact
        always refuses those individually too."""
        equipped_ids = set(self.game.db.get_equipped_accessory_ids(self.user_id).values())
        return [
            e["instance_id"] for e in self.game.get_player_accessories_artifacts(self.user_id)
            if e["item_id"] == item_id and e["affix"].rarity != "Unique" and e["instance_id"] not in equipped_ids
        ]

    def _build_action_buttons(self, row: int):
        selected = self.selected
        if selected and selected.startswith(ACCESSORY_INSTANCE_PREFIX):
            button = discord.ui.Button(label="Sell", emoji="🔨", style=discord.ButtonStyle.danger, row=row)
            button.callback = self._on_sell_instance
            self.add_item(button)

            instance_id = int(selected[len(ACCESSORY_INSTANCE_PREFIX):])
            entry = next(
                (e for e in self.game.get_player_accessories_artifacts(self.user_id) if e["instance_id"] == instance_id), None,
            )
            same_name = self._same_name_accessory_ids(entry["item_id"]) if entry else []
            name = entry["affix"].name if entry else ""
            sell_all = discord.ui.Button(
                label=f"Sell All {name} ({len(same_name)})"[:80] if entry else "Sell All",
                emoji="🧹", style=discord.ButtonStyle.secondary, row=row, disabled=len(same_name) <= 1,
            )
            sell_all.callback = self._on_sell_all_same_name
            self.add_item(sell_all)
            return
        if selected and (selected.startswith(GEAR_INSTANCE_PREFIX) or selected.startswith(AVATAR_INSTANCE_PREFIX)):
            button = discord.ui.Button(label="Sell", emoji="🔨", style=discord.ButtonStyle.danger, row=row)
            button.callback = self._on_sell_instance
            self.add_item(button)

            # A player can own many duplicate rolls of the same slot_type+tier (crafted gear
            # from repeated /blacksmith attempts, avatar gear from World Boss's high per-kill
            # drop chance) -- selling them one at a time is exactly the friction this command
            # exists to remove, so bulk-sell everything else at the SAME tier+slot in one click.
            if selected.startswith(GEAR_INSTANCE_PREFIX):
                gear = self.game.db.get_crafted_gear(int(selected[len(GEAR_INSTANCE_PREFIX):]))
                same_tier = self._same_tier_gear_ids(gear["slot_type"], gear["tier"]) if gear else []
                tier = gear["tier"] if gear else None
            else:
                inst = self.game.db.get_avatar_gear_instance(int(selected[len(AVATAR_INSTANCE_PREFIX):]))
                same_tier = self._same_tier_avatar_gear_ids(inst["slot_type"], inst["tier"]) if inst else []
                tier = inst["tier"] if inst else None

            sell_all = discord.ui.Button(
                label=f"Sell All T{tier} ({len(same_tier)})" if tier is not None else "Sell All",
                emoji="🧹", style=discord.ButtonStyle.secondary, row=row, disabled=len(same_tier) <= 1,
            )
            sell_all.callback = self._on_sell_all_same_tier
            self.add_item(sell_all)
            return

        remaining = self.game.get_inventory(self.user_id).get(selected, 0) if selected else 0
        sell1 = discord.ui.Button(label="Sell 1", emoji="🪙", style=discord.ButtonStyle.primary, row=row, disabled=remaining < 1)
        sell1.callback = self._make_sell_callback(1)
        self.add_item(sell1)

        sell10 = discord.ui.Button(
            label=f"Sell {SELL_BATCH_COUNT}", emoji="⏩", style=discord.ButtonStyle.primary, row=row, disabled=remaining < 1,
        )
        sell10.callback = self._make_sell_callback(SELL_BATCH_COUNT)
        self.add_item(sell10)

        sell_all = discord.ui.Button(label=f"Sell All ({remaining})", emoji="⏭️", style=discord.ButtonStyle.success, row=row, disabled=remaining < 1)
        sell_all.callback = self._make_sell_callback(remaining)
        self.add_item(sell_all)

    def _build_components(self):
        self.clear_items()
        for button in _build_category_buttons(self.category, callback_factory=self._make_category_callback):
            self.add_item(button)

        next_row = 1
        if _subcategories_for(self.category):
            buttons, rows_used = _build_subcategory_buttons(
                self.category, self.subcategory, row_start=1, callback_factory=self._make_subcategory_callback,
            )
            for button in buttons:
                self.add_item(button)
            next_row = 1 + rows_used

        self.add_item(self._build_item_select(row=next_row))
        self._build_action_buttons(row=next_row + 1)

    def _make_category_callback(self, category: str):
        async def callback(interaction: discord.Interaction):
            self.category = category
            self.subcategory = _default_sell_subcategory(category)
            self.selected = None
            self.last_result = None
            self._build_components()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

        return callback

    def _make_subcategory_callback(self, subcategory: str):
        async def callback(interaction: discord.Interaction):
            self.subcategory = subcategory
            self.selected = None
            self.last_result = None
            self._build_components()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

        return callback

    async def _on_pick_item(self, interaction: discord.Interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select))
        value = select.values[0]
        self.selected = None if value == "none" else value
        self.last_result = None
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    def _make_sell_callback(self, quantity: int):
        async def callback(interaction: discord.Interaction):
            item_name = self.selected
            ok, message, _stones = self.game.sell_item(self.user_id, self.display_name, item_name, quantity)
            self.last_result = message
            if ok and self.game.get_inventory(self.user_id).get(item_name, 0) == 0:
                self.selected = None
            self._build_components()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

        return callback

    async def _on_sell_instance(self, interaction: discord.Interaction):
        selected = self.selected
        if selected.startswith(GEAR_INSTANCE_PREFIX):
            gear_id = int(selected[len(GEAR_INSTANCE_PREFIX):])
            ok, message = self.game.dismantle_crafted_gear(self.user_id, self.display_name, gear_id)
        elif selected.startswith(ACCESSORY_INSTANCE_PREFIX):
            instance_id = int(selected[len(ACCESSORY_INSTANCE_PREFIX):])
            ok, message = self.game.salvage_accessory_artifact(self.user_id, self.display_name, instance_id)
        else:
            instance_id = int(selected[len(AVATAR_INSTANCE_PREFIX):])
            ok, message = self.game.sell_avatar_gear_instance(self.user_id, self.display_name, instance_id)
        self.last_result = message
        if ok:
            self.selected = None
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_sell_all_same_tier(self, interaction: discord.Interaction):
        """Bulk-dismantles/sells every owned, unequipped crafted gear or avatar gear instance
        that shares the selected item's exact slot_type+tier -- reuses the single-instance
        dismantle_crafted_gear/sell_avatar_gear_instance calls one at a time (both already
        re-check ownership/equipped per call) rather than a new bulk backend method, since
        every instance still needs its own row deleted individually either way."""
        selected = self.selected
        if selected.startswith(GEAR_INSTANCE_PREFIX):
            gear = self.game.db.get_crafted_gear(int(selected[len(GEAR_INSTANCE_PREFIX):]))
            if gear is None:
                self.last_result = "That item is no longer available."
            else:
                slot_type, tier = gear["slot_type"], gear["tier"]
                targets = self._same_tier_gear_ids(slot_type, tier)
                count = sum(1 for gid in targets if self.game.dismantle_crafted_gear(self.user_id, self.display_name, gid)[0])
                stones = count * blacksmith.dismantle_stones(tier)
                self.last_result = (
                    f"Dismantled {count}x Tier {tier} {slot_type} pieces — recovered materials + {stones:,} 🪙 total."
                    if count else "Nothing left to sell at that tier."
                )
        else:
            inst = self.game.db.get_avatar_gear_instance(int(selected[len(AVATAR_INSTANCE_PREFIX):]))
            if inst is None:
                self.last_result = "That item is no longer available."
            else:
                slot_type, tier = inst["slot_type"], inst["tier"]
                targets = self._same_tier_avatar_gear_ids(slot_type, tier)
                count = sum(1 for iid in targets if self.game.sell_avatar_gear_instance(self.user_id, self.display_name, iid)[0])
                stones = count * avatar_gear.sell_stones(tier)
                self.last_result = (
                    f"Sold {count}x {avatar_gear.tier_name(tier)} {slot_type} pieces for {stones:,} 🪙 total."
                    if count else "Nothing left to sell at that tier."
                )
        self.selected = None
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_sell_all_same_name(self, interaction: discord.Interaction):
        """Bulk-salvages every owned, unequipped, non-Unique accessory/artifact instance
        sharing the selected item's exact item_id (name) -- salvage_accessory_artifact
        re-checks ownership/equipped/rarity per call, same reasoning as
        _on_sell_all_same_tier."""
        instance_id = int(self.selected[len(ACCESSORY_INSTANCE_PREFIX):])
        entry = next(
            (e for e in self.game.get_player_accessories_artifacts(self.user_id) if e["instance_id"] == instance_id), None,
        )
        if entry is None:
            self.last_result = "That item is no longer available."
        else:
            affix = entry["affix"]
            targets = self._same_name_accessory_ids(entry["item_id"])
            count = sum(1 for iid in targets if self.game.salvage_accessory_artifact(self.user_id, self.display_name, iid)[0])
            rarity_star = accessories_data.RARITY_ORDER.index(affix.rarity) + 1
            stones = count * affix.rank * rarity_star * self.game.SALVAGE_STONES_PER_RANK_RARITY_STAR
            self.last_result = (
                f"Salvaged {count}x **{affix.name}** for {stones:,} 🪙 total."
                if count else "Nothing left to sell with that name."
            )
        self.selected = None
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    def build_embed(self) -> discord.Embed:
        player = self.game.get_player_stats(self.user_id, self.display_name)
        embed = discord.Embed(title=f"🏪 {self.display_name}'s NPC Vendor", color=discord.Color.dark_gold())
        embed.add_field(name="Spirit Stones", value=f"{player['spirit_stones']:,} 🪙", inline=False)

        label = f"{self.category} — {self.subcategory}" if self.subcategory else self.category
        lines = [
            f"{emoji} **{name}**{f' x{qty}' if qty is not None else ''} — {price_text}"
            for _, _, name, emoji, price_text, qty in self._candidates()[:25]
        ]
        # Discord caps a field value at 1024 chars -- a subcategory with many owned unique
        # instances (accessories/artifacts especially, each getting its own long "#id" line)
        # can exceed that and get the whole embed rejected with a 400, same defensive [:1024]
        # truncation every other embed field in this codebase already applies.
        embed.add_field(name=label, value=("\n".join(lines) if lines else "Nothing to sell here.")[:1024], inline=False)

        if self.last_result:
            embed.add_field(name="Result", value=self.last_result, inline=False)
        embed.set_footer(text="Sell items for spirit stones — a quick way to clear out clutter. Equipped and Unique-rarity items can't be sold; unequip them first.")
        return embed
