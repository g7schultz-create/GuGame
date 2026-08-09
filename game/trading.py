import asyncio
import discord

from . import accessories_data
from . import blacksmith
from . import equipment as equipment_module
from . import manual_data
from .base_view import GameView
from .equipment import EQUIPMENT, describe_stat_bonuses, gear_power_score
from .items import CATEGORY_EMOJI as _ITEM_CATEGORY_EMOJI
from .items import SUBCATEGORY_EMOJI as _ITEM_SUBCATEGORY_EMOJI
from .items import ITEM_CATEGORIES, item_emoji, items_in_category, subcategories_in_category
from .ui_utils import NAV_NEXT_VALUE, NAV_PREV_VALUE, paginate_select_options
from .views import _default_subcategory

# Weapons/armor/Gu/etc live in a separate catalog from ITEMS (see equipment.py's own
# docstring) — "Equipment" is a 4th top-level category alongside the regular ITEMS ones,
# with its own slot_type-based subcategories, so they're tradeable the same way potions and
# materials already are without disturbing /inventory or /profile's unrelated item browsers.
# "Pages" is a 5th, for manual_data.PAGES — a third separate catalog, quantity-stacked per
# player like ITEMS rather than an owned-instance table like Equipment's Manual/Gu/etc, but
# with its own 10-category/7-rank shape that doesn't fit either existing pattern cleanly
# enough to reuse it outright.
TRADE_CATEGORIES = ITEM_CATEGORIES + ["Equipment", "Pages"]
EQUIPMENT_SLOT_TYPES = ["Weapon", "Head", "Body", "Ring", "Earring", "Necklace", "Bracelet", "Artifact", "Manual", "Gu"]
CATEGORY_EMOJI = {**_ITEM_CATEGORY_EMOJI, "Equipment": "⚔️", "Pages": "📄"}
# Crafted_gear instances (rolled Weapon/Head/Body pieces — see blacksmith.py) aren't
# quantity-tracked catalog items, so a trade Select option's value is prefixed to tell a
# unique instance apart from an ordinary item_name — same convention as equipment_view.py's
# own INSTANCE_VALUE_PREFIX (kept as a separate constant since each view only ever
# interprets its own Select's values, never the other's).
INSTANCE_VALUE_PREFIX = "gear:"
# Same convention for manuals (see manual_view.py) and accessory/artifact instances (see
# accessories_view.py) — each is its own owned-instance table, not a quantity-tracked
# catalog item, so they get their own value prefixes alongside crafted_gear's.
MANUAL_VALUE_PREFIX = "manual:"
ACCESSORY_VALUE_PREFIX = "accessory:"
# Pages ARE quantity-stacked like plain ITEMS (see player_pages), but still get their own
# prefix -- unlike an item_name, a page_id alone doesn't tell _remaining/_make_add_callback
# which catalog/table to look the candidate up in, so it needs the same disambiguation the
# three instance kinds above already use.
PAGE_VALUE_PREFIX = "page:"
# Subcategories with a real tier/rank concept worth offering a "Tier" filter dropdown for.
# Weapon/Head/Body are deliberately excluded — they already sort strongest-first by
# gear_power_score, a richer multi-stat measure than a single tier number would be.
TIER_SORTABLE_SUBCATEGORIES = {"Ring", "Earring", "Necklace", "Bracelet", "Artifact", "Manual", "Gu"}
ALL_TIERS_VALUE = "__all_tiers__"
# (emoji, label) per flat currency offerable in a trade — keys match
# GameDatabase.TRADE_CURRENCIES exactly. Manual Ink gets its own 🖋️ rather than reusing
# Spirit Stones' 🪙 (which manual_view.py's single-currency displays share) since here
# they can appear stacked in the same offer line-by-line, where a shared coin emoji would
# be genuinely ambiguous at a glance.
CURRENCY_LABELS = {
    "spirit_stones": ("🪙", "Spirit Stones"),
    "manual_ink": ("🖋️", "Manual Ink"),
    "insight_dust": ("✨", "Insight Dust"),
}


def _item_emoji(item_name: str) -> str:
    """Works for both ITEMS and Equipment names — see items.item_emoji /
    equipment.SLOT_TYPE_EMOJI, the two separate catalogs this pulls from."""
    gear = EQUIPMENT.get(item_name)
    if gear is not None:
        return equipment_module.SLOT_TYPE_EMOJI.get(gear.slot_type, "🎒")
    return item_emoji(item_name)


def _gu_tier(item_name: str) -> tuple:
    """(tier_key, tier_label) for the Gu tier-filter dropdown — higher key = rarer. Derived
    from equipment_view.EquipmentView._gu_rarity_rank's logic (a @staticmethod there, not a
    standalone helper) rather than importing the whole view class for one small piece of
    logic. A handful of named Gu (Battle Intent Gu, Flying Sword Gu, ...) never got a tiered
    (Family (Quality)) name at all — parse_gu_name can't place them on the Common..Immortal
    ladder, so they get their own 'Unique' tier bucket rather than being folded into
    Immortal or the bottom."""
    _, quality = equipment_module.parse_gu_name(item_name)
    if quality is None:
        return len(equipment_module.GU_QUALITY_ORDER), "Unique"
    return equipment_module.GU_QUALITY_STARS[quality], quality


def _offer_is_empty(offer: dict) -> bool:
    """True when a side's trade_offers rows amount to nothing at all -- used by /gamble's
    Confirm-button gate (game/manager.py's confirm_gamble/execute_gamble also re-check this
    server-side; this is just the view's own immediate feedback)."""
    currencies_empty = all(offer[currency] == 0 for currency in ("spirit_stones", "manual_ink", "insight_dust"))
    return (
        currencies_empty and not offer["items"] and not offer["pages"]
        and not offer["crafted_gear"] and not offer["manuals"] and not offer["accessories"]
    )


def _default_trade_subcategory(category: str):
    if category == "Equipment":
        return EQUIPMENT_SLOT_TYPES[0]
    if category == "Pages":
        return manual_data.PAGE_CATEGORIES[0]
    return _default_subcategory(category)


def _build_trade_category_buttons(active_category: str, row: int, callback_factory):
    buttons = []
    for category in TRADE_CATEGORIES:
        button = discord.ui.Button(label=category, emoji=CATEGORY_EMOJI.get(category), row=row)
        is_active = category == active_category
        button.style = discord.ButtonStyle.primary if is_active else discord.ButtonStyle.secondary
        button.disabled = is_active
        button.callback = callback_factory(category)
        buttons.append(button)
    return buttons


def _build_trade_subcategory_buttons(active_category: str, active_subcategory: str, row_start: int, callback_factory):
    """Returns (items, rows_used). Equipment's 10 slot types don't fit on one row of buttons
    (Discord caps buttons at 5 per row) the way every ITEMS subcategory list (<=4 entries)
    does, so Equipment collapses to a single Select instead — same fix already applied to
    killer_move_view.py's rarity filter / accessories_view.py's type filter for this exact
    row-budget problem. The Select's callback re-dispatches into callback_factory(chosen
    name) at interaction time so both cases share one "switch subcategory" code path,
    despite a Select's "read .values afterward" shape not matching a button's fixed-target
    callback the way callback_factory was originally built for."""
    if active_category == "Equipment":
        options = [
            discord.SelectOption(label=name, emoji=equipment_module.SLOT_TYPE_EMOJI.get(name), default=(name == active_subcategory))
            for name in EQUIPMENT_SLOT_TYPES
        ]
        select = discord.ui.Select(placeholder=f"Slot type: {active_subcategory}", options=options, row=row_start)

        async def _on_select(interaction: discord.Interaction):
            await callback_factory(select.values[0])(interaction)

        select.callback = _on_select
        return [select], 1

    if active_category == "Pages":
        # Same row-budget problem as Equipment's 10 slot types (Discord caps buttons at 5
        # per row) -- manual_data.PAGE_CATEGORIES is also 10 entries, so this collapses to a
        # Select for the same reason, not a coincidence.
        options = [
            discord.SelectOption(label=name, default=(name == active_subcategory))
            for name in manual_data.PAGE_CATEGORIES
        ]
        select = discord.ui.Select(placeholder=f"Page category: {active_subcategory}", options=options, row=row_start)

        async def _on_select(interaction: discord.Interaction):
            await callback_factory(select.values[0])(interaction)

        select.callback = _on_select
        return [select], 1

    names = subcategories_in_category(active_category)
    emoji_map = _ITEM_SUBCATEGORY_EMOJI
    buttons = []
    for index, name in enumerate(names):
        button = discord.ui.Button(label=name, emoji=emoji_map.get(name), row=row_start + index // 5)
        is_active = name == active_subcategory
        button.style = discord.ButtonStyle.primary if is_active else discord.ButtonStyle.secondary
        button.disabled = is_active
        button.callback = callback_factory(name)
        buttons.append(button)
    rows_used = -(-len(names) // 5) if names else 0  # ceil division
    return buttons, rows_used


def _build_trade_window_embed(game, trade_id, initiator, target) -> discord.Embed:
    trade = game.get_trade(trade_id)
    is_gamble = trade["mode"] == "gamble"
    embed = discord.Embed(title="🎲 Gamble Window" if is_gamble else "🤝 Trade Window", color=discord.Color.gold())
    for index, (member, confirmed) in enumerate(((initiator, trade["initiator_confirmed"]), (target, trade["target_confirmed"]))):
        offer = game.get_trade_offer(trade_id, member.id)
        lines = []
        for currency, (emoji, label) in CURRENCY_LABELS.items():
            if offer[currency]:
                lines.append(f"{emoji} {offer[currency]:,} {label}")
        for item_name, qty in offer["items"].items():
            lines.append(f"{_item_emoji(item_name)} {item_name} x{qty}")
        for page_id, qty in offer["pages"].items():
            page = manual_data.PAGES.get(page_id)
            lines.append(f"📄 {page.name if page else page_id} x{qty}")
        for gear_id in offer["crafted_gear"]:
            gear = game.db.get_crafted_gear(gear_id)
            if gear is None:
                continue
            display_name = blacksmith.crafted_gear_display_name(gear["base_type"], gear["tier"], gear["gear_id"])
            emoji = equipment_module.SLOT_TYPE_EMOJI.get(gear["slot_type"], "🎒")
            lines.append(f"{emoji} {display_name} — {describe_stat_bonuses(gear['stat_bonuses'])}")
        for manual_id in offer["manuals"]:
            manual = game.db.get_manual(manual_id)
            if manual is None:
                continue
            lines.append(f"📖 {manual['name']} (R{manual['rank']} {manual['rarity']})")
        for instance_id in offer["accessories"]:
            instance = game.db.get_accessory_instance(instance_id)
            affix = accessories_data.ITEMS.get(instance["item_id"]) if instance else None
            if affix is None:
                continue
            emoji = equipment_module.SLOT_TYPE_EMOJI.get(affix.slot_type, "🎒")
            lines.append(f"{emoji} {affix.name} #{instance_id} (Rank {affix.rank} {affix.rarity})")
        value = "\n".join(lines) if lines else "*No items added yet*"
        embed.add_field(name=f"🧍 {member.display_name} {'✅' if confirmed else '⏳'}", value=value, inline=False)
        if index == 0:
            # A clear break between the two offers — plain field stacking alone reads as one
            # continuous block, easy to misread which line belongs to whom.
            embed.add_field(name="​", value="▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬", inline=False)
    if is_gamble:
        embed.set_footer(text="Winner takes BOTH pots — add something and Confirm. Both must confirm to roll. Expires after 5 min.")
    else:
        embed.set_footer(text="Click your row's buttons to add items. Both must Confirm to complete. Trade expires after 5 min.")
    return embed


class TradeCurrencyModal(discord.ui.Modal, title="Offer Currency"):
    spirit_stones_input = discord.ui.TextInput(label="🪙 Spirit Stones", placeholder="0", required=False, max_length=12)
    manual_ink_input = discord.ui.TextInput(label="🖋️ Manual Ink", placeholder="0", required=False, max_length=12)
    insight_dust_input = discord.ui.TextInput(label="✨ Insight Dust", placeholder="0", required=False, max_length=12)

    def __init__(self, trade_window: "TradeWindowView", user_id: int, current_offer: dict):
        super().__init__()
        self.trade_window = trade_window
        self.user_id = user_id
        self.spirit_stones_input.default = str(current_offer["spirit_stones"])
        self.manual_ink_input.default = str(current_offer["manual_ink"])
        self.insight_dust_input.default = str(current_offer["insight_dust"])

    async def on_submit(self, interaction: discord.Interaction):
        inputs = {
            "spirit_stones": self.spirit_stones_input, "manual_ink": self.manual_ink_input, "insight_dust": self.insight_dust_input,
        }
        requested = {}
        for currency, field in inputs.items():
            raw = field.value.strip() or "0"
            try:
                value = int(raw)
            except ValueError:
                _, label = CURRENCY_LABELS[currency]
                await interaction.response.send_message(f"'{raw}' isn't a whole number for {label}.", ephemeral=True)
                return
            if value < 0:
                _, label = CURRENCY_LABELS[currency]
                await interaction.response.send_message(f"{label} can't be negative.", ephemeral=True)
                return
            requested[currency] = value

        clamp_notes = []
        for currency, amount in requested.items():
            clamped = await asyncio.to_thread(
                self.trade_window.game.set_trade_currency,
                self.trade_window.trade_id, self.user_id, interaction.user.display_name, currency, amount,
            )
            if clamped != amount:
                _, label = CURRENCY_LABELS[currency]
                clamp_notes.append(f"{label}: offered {clamped} instead of {amount}")

        await asyncio.to_thread(self.trade_window._build_components)

        embed = await asyncio.to_thread(self.trade_window.build_embed)
        await interaction.response.edit_message(embed=embed, view=self.trade_window)
        if clamp_notes:
            await interaction.followup.send("You didn't have enough for some of that — " + "; ".join(clamp_notes) + ".", ephemeral=True)


class TradeAddItemView(GameView):
    ADD_BATCH_COUNT = 10

    def __init__(self, game, trade_id: int, user_id: int, trade_window: "TradeWindowView"):
        super().__init__(timeout=120)
        self.game = game
        self.trade_id = trade_id
        self.user_id = user_id
        self.trade_window = trade_window
        self.category = TRADE_CATEGORIES[0]
        self.subcategory = _default_trade_subcategory(self.category)
        # Picking the select just targets an item now — Add 1/10/All below act on it, so a
        # single click can add more than one at a time instead of re-opening the select
        # repeatedly.
        self.selected_item: str = None
        # Only meaningful for the 7 TIER_SORTABLE_SUBCATEGORIES — resets alongside
        # selected_item whenever category/subcategory changes, same lifetime. None means
        # "All Tiers" (no filter); item_page resets to 0 whenever the candidate pool
        # changes (category/subcategory/tier_filter), same as equipment_view.py's own
        # gu_item_page convention.
        self.tier_filter: str = None
        self.item_page = 0
        # Direct references to this render's Selects, set in _build_components — reading
        # .values off self.children by isinstance() alone breaks once more than one Select
        # is on screen at once (the tier filter + the item picker, both Selects), since
        # isinstance() can't tell which one the user actually just interacted with.
        self._item_select: discord.ui.Select = None
        self._tier_select: discord.ui.Select = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    def _remaining(self, selected: str) -> int:
        if not selected:
            return 0
        if selected.startswith(INSTANCE_VALUE_PREFIX):
            # A unique instance is either offerable (1) or it isn't (0) — no quantity to
            # speak of. Re-checked live (owned, unequipped, not already offered) rather than
            # trusting whatever built the Select a moment ago, same reasoning as
            # GameManager.add_trade_crafted_gear's own re-check.
            gear_id = int(selected[len(INSTANCE_VALUE_PREFIX):])
            gear = self.game.db.get_crafted_gear(gear_id)
            if gear is None or gear["owner_id"] != self.user_id:
                return 0
            if gear_id in self.game.db.get_equipped_gear_ids(self.user_id).values():
                return 0
            if gear_id in self.game.get_trade_offer(self.trade_id, self.user_id)["crafted_gear"]:
                return 0
            return 1
        if selected.startswith(MANUAL_VALUE_PREFIX):
            manual_id = int(selected[len(MANUAL_VALUE_PREFIX):])
            manual = self.game.db.get_manual(manual_id)
            if manual is None or manual["owner_id"] != self.user_id:
                return 0
            if self.game.db.is_manual_equipped(self.user_id, manual_id):
                return 0
            if manual_id in self.game.get_trade_offer(self.trade_id, self.user_id)["manuals"]:
                return 0
            return 1
        if selected.startswith(ACCESSORY_VALUE_PREFIX):
            instance_id = int(selected[len(ACCESSORY_VALUE_PREFIX):])
            instance = self.game.db.get_accessory_instance(instance_id)
            if instance is None or instance["owner_id"] != self.user_id:
                return 0
            if instance_id in self.game.db.get_equipped_accessory_ids(self.user_id).values():
                return 0
            if instance_id in self.game.get_trade_offer(self.trade_id, self.user_id)["accessories"]:
                return 0
            return 1
        if selected.startswith(PAGE_VALUE_PREFIX):
            page_id = selected[len(PAGE_VALUE_PREFIX):]
            owned = self.game.db.get_player_pages(self.user_id).get(page_id, {}).get("quantity", 0)
            offered = self.game.get_trade_offer(self.trade_id, self.user_id)["pages"].get(page_id, 0)
            return max(0, owned - offered)
        inventory = self.game.get_inventory(self.user_id)
        offered = self.game.get_trade_offer(self.trade_id, self.user_id)["items"]
        return max(0, inventory.get(selected, 0) - offered.get(selected, 0))

    def _build_components(self):
        self.clear_items()
        for button in _build_trade_category_buttons(self.category, row=0, callback_factory=self._make_category_callback):
            self.add_item(button)

        next_row = 1
        if self.category in ("Equipment", "Pages") or subcategories_in_category(self.category):
            items, rows_used = _build_trade_subcategory_buttons(self.category, self.subcategory, row_start=1, callback_factory=self._make_subcategory_callback)
            for item in items:
                self.add_item(item)
            next_row = 1 + rows_used

        candidates = self._gather_candidates()

        tier_filterable = (self.category == "Equipment" and self.subcategory in TIER_SORTABLE_SUBCATEGORIES) or self.category == "Pages"
        if tier_filterable:
            self._tier_select = self._build_tier_filter_select(candidates, row=next_row)
            self.add_item(self._tier_select)
            next_row += 1
        else:
            self._tier_select = None

        self._item_select = self._build_item_select(candidates, row=next_row)
        self.add_item(self._item_select)

        remaining = self._remaining(self.selected_item)
        add_row = next_row + 1
        add1 = discord.ui.Button(label="Add 1", emoji="➕", style=discord.ButtonStyle.primary, row=add_row, disabled=remaining < 1)
        add1.callback = self._make_add_callback(1)
        self.add_item(add1)

        add10 = discord.ui.Button(
            label=f"Add {self.ADD_BATCH_COUNT}", emoji="⏩", style=discord.ButtonStyle.primary, row=add_row, disabled=remaining < 1,
        )
        add10.callback = self._make_add_callback(self.ADD_BATCH_COUNT)
        self.add_item(add10)

        add_all = discord.ui.Button(label=f"Add All ({remaining})", emoji="⏭️", style=discord.ButtonStyle.success, row=add_row, disabled=remaining < 1)
        add_all.callback = self._make_add_callback(remaining)
        self.add_item(add_all)

    def _candidate_names(self):
        """(item_name, description) pairs for whatever's browsable in the current
        category/subcategory — either an ITEMS entry or an Equipment piece of the selected
        slot_type, the two separate catalogs this view now spans."""
        if self.category == "Equipment":
            matches = [(name, gear) for name, gear in EQUIPMENT.items() if gear.slot_type == self.subcategory]
            matches.sort(key=lambda pair: -gear_power_score(pair[1]))
            return [(name, gear.description) for name, gear in matches]
        return [(item.name, item.description) for item in items_in_category(self.category, self.subcategory)]

    def _gather_candidates(self) -> list:
        """Every offerable candidate for the current category/subcategory, each as
        {"sort_key": (float, str), "tier_label": str|None, "option": SelectOption}.
        tier_label is None for anything without a real tier/rank concept (Weapon/Head/Body,
        every non-Equipment category, and legacy flat items at a tiered slot type that
        predate the owned-instance systems) — those simply never match a specific tier
        filter, only ever showing up under "All Tiers"."""
        inventory = self.game.get_inventory(self.user_id)
        current_offer = self.game.get_trade_offer(self.trade_id, self.user_id)
        offered = current_offer["items"]
        candidates = []
        for item_name, description in self._candidate_names():
            remaining = inventory.get(item_name, 0) - offered.get(item_name, 0)
            if remaining <= 0:
                continue
            gear = EQUIPMENT.get(item_name)
            option = discord.SelectOption(
                label=f"{_item_emoji(item_name)} {item_name} ({remaining} left)"[:100], value=item_name, description=description[:100],
                default=(item_name == self.selected_item),
            )
            if self.category == "Equipment" and self.subcategory == "Gu":
                tier_key, tier_label = _gu_tier(item_name)
            else:
                tier_key, tier_label = 0, None
            sort_key = (-tier_key, -gear_power_score(gear) if gear else 0.0, item_name)
            candidates.append({"sort_key": sort_key, "tier_key": tier_key, "tier_label": tier_label, "option": option})

        if self.category == "Equipment" and self.subcategory in ("Weapon", "Head", "Body"):
            # Rolled crafted_gear instances (see /blacksmith, /weapons) — not in the flat
            # inventory table above (ownership IS the row), so they're candidates whenever
            # owned, not currently equipped, and not already sitting in this offer. No tier
            # concept here — see TIER_SORTABLE_SUBCATEGORIES' own docstring for why.
            equipped_gear_ids = set(self.game.db.get_equipped_gear_ids(self.user_id).values())
            offered_gear_ids = set(current_offer["crafted_gear"])
            for gear in self.game.get_player_crafted_gear(self.user_id):
                if gear["slot_type"] != self.subcategory:
                    continue
                if gear["gear_id"] in equipped_gear_ids or gear["gear_id"] in offered_gear_ids:
                    continue
                value = f"{INSTANCE_VALUE_PREFIX}{gear['gear_id']}"
                display_name = blacksmith.crafted_gear_display_name(gear["base_type"], gear["tier"], gear["gear_id"])
                emoji = equipment_module.SLOT_TYPE_EMOJI.get(gear["slot_type"], "🎒")
                option = discord.SelectOption(
                    label=f"{emoji} {display_name} (1 left)"[:100], value=value,
                    description=describe_stat_bonuses(gear["stat_bonuses"])[:100],
                    default=(value == self.selected_item),
                )
                candidates.append({"sort_key": (-gear["power_score"], display_name), "tier_key": 0, "tier_label": None, "option": option})

        if self.category == "Equipment" and self.subcategory == "Manual":
            # Assembled manuals (see /assemble_manual) — owned-instance table, not flat
            # inventory, same shape as crafted_gear above: candidates whenever owned, not
            # currently equipped (players.equipped_primary/auxiliary_manual_id, not the
            # generic `equipped` table), and not already sitting in this offer. Tier =
            # the manual's own literal rank (1-7).
            offered_manual_ids = set(current_offer["manuals"])
            for manual in self.game.db.get_player_manuals(self.user_id):
                if self.game.db.is_manual_equipped(self.user_id, manual["manual_id"]) or manual["manual_id"] in offered_manual_ids:
                    continue
                value = f"{MANUAL_VALUE_PREFIX}{manual['manual_id']}"
                display_name = f"{manual['name']} (R{manual['rank']} {manual['rarity']})"
                option = discord.SelectOption(
                    label=f"📖 {display_name} (1 left)"[:100], value=value,
                    description=f"{manual['coherence_band']} coherence, {manual['primary_path']} path"[:100],
                    default=(value == self.selected_item),
                )
                candidates.append({
                    "sort_key": (-manual["rank"], display_name), "tier_key": manual["rank"],
                    "tier_label": f"Rank {manual['rank']}", "option": option,
                })

        if self.category == "Equipment" and self.subcategory in ("Ring", "Earring", "Necklace", "Bracelet", "Artifact"):
            # Accessory/artifact instances (see /accessories) — owned-instance table, same
            # shape as crafted_gear/manuals: candidates whenever owned, not currently
            # equipped (the generic `equipped` table's accessory_instance_id column), and
            # not already sitting in this offer. Tier = the accessory's own literal rank
            # (1-7), distinct from its rarity string.
            offered_instance_ids = set(current_offer["accessories"])
            equipped_instance_ids = set(self.game.db.get_equipped_accessory_ids(self.user_id).values())
            for entry in self.game.get_player_accessories_artifacts(self.user_id):
                affix = entry["affix"]
                if affix.slot_type != self.subcategory:
                    continue
                if entry["instance_id"] in equipped_instance_ids or entry["instance_id"] in offered_instance_ids:
                    continue
                value = f"{ACCESSORY_VALUE_PREFIX}{entry['instance_id']}"
                display_name = self.game._accessory_display_name(entry, affix)
                option = discord.SelectOption(
                    label=f"{equipment_module.SLOT_TYPE_EMOJI.get(affix.slot_type, '🎒')} {display_name} (1 left)"[:100], value=value,
                    description=f"Rank {affix.rank} {affix.rarity}"[:100],
                    default=(value == self.selected_item),
                )
                candidates.append({
                    "sort_key": (-affix.rank, display_name), "tier_key": affix.rank,
                    "tier_label": f"Rank {affix.rank}", "option": option,
                })

        if self.category == "Pages":
            # Manual pages (see /assemble_manual, manual_view.py) — quantity-stacked per
            # (user_id, page_id) like plain ITEMS, not an owned-instance table, but pages
            # live in their own manual_data.PAGES catalog with a real category/rank shape
            # ITEMS doesn't have, so they get their own block rather than routing through
            # _candidate_names (which harmlessly returns [] for "Pages" as-is).
            offered_pages = current_offer["pages"]
            for page_id, info in self.game.db.get_player_pages(self.user_id).items():
                page = manual_data.PAGES.get(page_id)
                if page is None or page.category != self.subcategory:
                    continue
                remaining = info["quantity"] - offered_pages.get(page_id, 0)
                if remaining <= 0:
                    continue
                value = f"{PAGE_VALUE_PREFIX}{page_id}"
                option = discord.SelectOption(
                    label=f"📄 {page.name} ({remaining} left)"[:100], value=value,
                    description=f"Rank {page.rank} — {', '.join(page.tags[:3])}"[:100],
                    default=(value == self.selected_item),
                )
                candidates.append({
                    "sort_key": (-page.rank, page.name), "tier_key": page.rank,
                    "tier_label": f"Rank {page.rank}", "option": option,
                })

        return candidates

    def _build_tier_filter_select(self, candidates: list, row: int) -> discord.ui.Select:
        """One entry per distinct tier_label actually present among this subcategory's
        candidates (rarest first), plus a leading 'All Tiers' to clear the filter — the
        filter's own menu, so it never lists a tier with nothing in it."""
        tier_keys_by_label = {}
        for c in candidates:
            if c["tier_label"] is not None:
                tier_keys_by_label[c["tier_label"]] = c["tier_key"]
        ordered_labels = sorted(tier_keys_by_label, key=lambda label: -tier_keys_by_label[label])

        options = [discord.SelectOption(label="All Tiers", value=ALL_TIERS_VALUE, default=(self.tier_filter is None))]
        for label in ordered_labels:
            options.append(discord.SelectOption(label=label, value=label, default=(label == self.tier_filter)))

        select = discord.ui.Select(placeholder=f"Tier: {self.tier_filter or 'All Tiers'}"[:150], options=options[:25], row=row)
        select.callback = self._on_pick_tier_filter
        return select

    def _build_item_select(self, candidates: list, row: int) -> discord.ui.Select:
        filtered = [c for c in candidates if self.tier_filter is None or c["tier_label"] == self.tier_filter]
        filtered.sort(key=lambda c: c["sort_key"])
        options = [c["option"] for c in filtered]

        # Gu ownership in particular can realistically exceed Discord's 25-option Select
        # cap for an active player (see raid.py's potion picker, which hit this exact
        # ceiling before it was capped the same way) — paginate_select_options chunks and
        # adds Prev/Next pseudo-options instead of silently truncating the tail off.
        page_options, total_pages, self.item_page = paginate_select_options(options, self.item_page)
        placeholder = "Choose an item, then Add 1/10/All..." if options else "Nothing available to add"
        if total_pages > 1:
            placeholder += f" (page {self.item_page + 1}/{total_pages})"
        select = discord.ui.Select(
            placeholder=placeholder[:150],
            options=page_options or [discord.SelectOption(label="None", value="none")],
            disabled=not options,
            row=row,
        )
        select.callback = self._on_pick_item
        return select

    def _make_category_callback(self, category: str):
        async def callback(interaction: discord.Interaction):
            self.category = category
            self.subcategory = _default_trade_subcategory(category)
            self.selected_item = None
            self.tier_filter = None
            self.item_page = 0
            await asyncio.to_thread(self._build_components)
            await interaction.response.edit_message(view=self)

        return callback

    def _make_subcategory_callback(self, subcategory: str):
        async def callback(interaction: discord.Interaction):
            self.subcategory = subcategory
            self.selected_item = None
            self.tier_filter = None
            self.item_page = 0
            await asyncio.to_thread(self._build_components)
            await interaction.response.edit_message(view=self)

        return callback

    async def _on_pick_tier_filter(self, interaction: discord.Interaction):
        choice = self._tier_select.values[0]
        self.tier_filter = None if choice == ALL_TIERS_VALUE else choice
        self.selected_item = None
        self.item_page = 0
        await asyncio.to_thread(self._build_components)
        await interaction.response.edit_message(view=self)

    async def _on_pick_item(self, interaction: discord.Interaction):
        choice = self._item_select.values[0]
        if choice == NAV_PREV_VALUE:
            self.item_page = max(0, self.item_page - 1)
        elif choice == NAV_NEXT_VALUE:
            self.item_page += 1
        else:
            self.selected_item = choice
        await asyncio.to_thread(self._build_components)
        await interaction.response.edit_message(view=self)

    def _make_add_callback(self, quantity: int):
        async def callback(interaction: discord.Interaction):
            selected = self.selected_item
            if selected and selected.startswith(INSTANCE_VALUE_PREFIX):
                # A unique instance is all-or-nothing (1 or 0) regardless of whether Add
                # 1/10/All was clicked — there's only ever one of it to offer.
                gear_id = int(selected[len(INSTANCE_VALUE_PREFIX):])
                gear = await asyncio.to_thread(self.game.db.get_crafted_gear, gear_id)
                display_name = blacksmith.crafted_gear_display_name(gear["base_type"], gear["tier"], gear["gear_id"]) if gear else "that piece"
                added_ok = await asyncio.to_thread(self.game.add_trade_crafted_gear, self.trade_id, self.user_id, interaction.user.display_name, gear_id)
                if added_ok:
                    self.selected_item = None
                await asyncio.to_thread(self._build_components)
                content = f"Added **{display_name}** to your offer." if added_ok else f"**{display_name}** is no longer available to offer."
                await interaction.response.edit_message(content=content, view=self)
                await self.trade_window.refresh()
                return

            if selected and selected.startswith(MANUAL_VALUE_PREFIX):
                manual_id = int(selected[len(MANUAL_VALUE_PREFIX):])
                manual = await asyncio.to_thread(self.game.db.get_manual, manual_id)
                display_name = f"{manual['name']} (R{manual['rank']} {manual['rarity']})" if manual else "that manual"
                added_ok = await asyncio.to_thread(self.game.add_trade_manual, self.trade_id, self.user_id, interaction.user.display_name, manual_id)
                if added_ok:
                    self.selected_item = None
                await asyncio.to_thread(self._build_components)
                content = f"Added **{display_name}** to your offer." if added_ok else f"**{display_name}** is no longer available to offer."
                await interaction.response.edit_message(content=content, view=self)
                await self.trade_window.refresh()
                return

            if selected and selected.startswith(ACCESSORY_VALUE_PREFIX):
                instance_id = int(selected[len(ACCESSORY_VALUE_PREFIX):])
                instance = await asyncio.to_thread(self.game.db.get_accessory_instance, instance_id)
                affix = accessories_data.ITEMS.get(instance["item_id"]) if instance else None
                display_name = f"{affix.name} #{instance_id}" if affix else "that piece"
                added_ok = await asyncio.to_thread(self.game.add_trade_accessory, self.trade_id, self.user_id, interaction.user.display_name, instance_id)
                if added_ok:
                    self.selected_item = None
                await asyncio.to_thread(self._build_components)
                content = f"Added **{display_name}** to your offer." if added_ok else f"**{display_name}** is no longer available to offer."
                await interaction.response.edit_message(content=content, view=self)
                await self.trade_window.refresh()
                return

            if selected and selected.startswith(PAGE_VALUE_PREFIX):
                # Unlike the three instance branches above, a page stack IS quantity-based
                # (like plain items) — Add 1/10/All all apply here.
                page_id = selected[len(PAGE_VALUE_PREFIX):]
                page = manual_data.PAGES.get(page_id)
                display_name = page.name if page else page_id
                added = await asyncio.to_thread(self.game.add_trade_page, self.trade_id, self.user_id, interaction.user.display_name, page_id, quantity)
                if added and await asyncio.to_thread(self._remaining, selected) == 0:
                    self.selected_item = None
                await asyncio.to_thread(self._build_components)
                content = f"Added {added}x **{display_name}** to your offer." if added else f"You have no more **{display_name}** left to offer."
                await interaction.response.edit_message(content=content, view=self)
                await self.trade_window.refresh()
                return

            item_name = selected
            added = await asyncio.to_thread(self.game.add_trade_item, self.trade_id, self.user_id, interaction.user.display_name, item_name, quantity)
            if added and await asyncio.to_thread(self._remaining, item_name) == 0:
                self.selected_item = None  # nothing left of this item to keep targeting
            await asyncio.to_thread(self._build_components)
            content = f"Added {added}x **{item_name}** to your offer." if added else f"You have no more **{item_name}** left to offer."
            await interaction.response.edit_message(content=content, view=self)
            await self.trade_window.refresh()

        return callback


class TradeWindowView(GameView):
    def __init__(self, game, trade_id: int, initiator: discord.abc.User, target: discord.abc.User):
        super().__init__(timeout=300)
        self.game = game
        self.trade_id = trade_id
        self.initiator = initiator
        self.target = target
        self.message: discord.Message = None
        self.finished = False
        # Read straight from the trades row rather than taking a constructor argument —
        # single source of truth, so every existing TradeWindowView(...) call site (still
        # only ever used for real trades today) needs zero changes; only /gamble's new call
        # path ever produces "gamble" here (see GameManager.start_gamble).
        self.mode = game.get_trade(trade_id)["mode"]
        self._build_components()

    def build_embed(self) -> discord.Embed:
        return _build_trade_window_embed(self.game, self.trade_id, self.initiator, self.target)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in (self.initiator.id, self.target.id):
            await interaction.response.send_message("This isn't your trade.", ephemeral=True)
            return False
        return True

    def _build_components(self):
        self.clear_items()
        for member, row in ((self.initiator, 0), (self.target, 1)):
            add_item_button = discord.ui.Button(label=member.display_name[:32], emoji="📦", row=row)
            add_item_button.callback = self._make_add_item_callback(member)
            self.add_item(add_item_button)

            currency_button = discord.ui.Button(label="Currency", emoji="💰", row=row)
            currency_button.callback = self._make_currency_callback(member)
            self.add_item(currency_button)

            clear_button = discord.ui.Button(emoji="🗑️", style=discord.ButtonStyle.secondary, row=row)
            clear_button.callback = self._make_clear_callback(member)
            self.add_item(clear_button)

            # /gamble requires both sides to actually have something at stake before either
            # can confirm (see _offer_is_empty) -- real trades have no such requirement (a
            # one-sided gift is a legitimate use of /trade), so this only ever disables
            # anything in gamble mode.
            confirm_disabled = self.mode == "gamble" and _offer_is_empty(self.game.get_trade_offer(self.trade_id, member.id))
            confirm_button = discord.ui.Button(
                label="Confirm", emoji="🤝", style=discord.ButtonStyle.success, row=row, disabled=confirm_disabled,
            )
            confirm_button.callback = self._make_confirm_callback(member)
            self.add_item(confirm_button)

        cancel_button = discord.ui.Button(label="Cancel Trade", emoji="❌", style=discord.ButtonStyle.danger, row=2)
        cancel_button.callback = self._on_cancel
        self.add_item(cancel_button)

    def _make_add_item_callback(self, member: discord.abc.User):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != member.id:
                await interaction.response.send_message("That's not your row.", ephemeral=True)
                return
            picker = TradeAddItemView( self.game, self.trade_id, member.id, self)
            await interaction.response.send_message("Choose a category to add an item to your offer:", view=picker, ephemeral=True)

        return callback

    def _make_currency_callback(self, member: discord.abc.User):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != member.id:
                await interaction.response.send_message("That's not your row.", ephemeral=True)
                return
            current_offer = await asyncio.to_thread(self.game.get_trade_offer, self.trade_id, member.id)
            await interaction.response.send_modal(TradeCurrencyModal(self, member.id, current_offer))

        return callback

    def _make_clear_callback(self, member: discord.abc.User):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != member.id:
                await interaction.response.send_message("That's not your row.", ephemeral=True)
                return
            await asyncio.to_thread(self.game.clear_trade_offer, self.trade_id, member.id)
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    def _make_confirm_callback(self, member: discord.abc.User):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != member.id:
                await interaction.response.send_message("That's not your row.", ephemeral=True)
                return

            if self.mode == "gamble":
                result = await asyncio.to_thread(self.game.confirm_gamble, self.trade_id, member.id)
                if result["status"] == "waiting":
                    await asyncio.to_thread(self._build_components)
                    embed = await asyncio.to_thread(self.build_embed)
                    await interaction.response.edit_message(embed=embed, view=self)
                elif result["status"] == "completed":
                    winner = self.initiator if result["winner_id"] == self.initiator.id else self.target
                    loser = self.target if winner is self.initiator else self.initiator
                    winner_roll = result["initiator_roll"] if winner is self.initiator else result["target_roll"]
                    loser_roll = result["target_roll"] if winner is self.initiator else result["initiator_roll"]
                    await self._finish(
                        interaction, "🎲 Gamble Complete!",
                        f"**{winner.display_name}** rolled **{winner_roll}** vs **{loser.display_name}**'s **{loser_roll}** — takes everything!",
                        discord.Color.green(),
                    )
                else:
                    await self._finish(
                        interaction, "⚠️ Gamble Failed",
                        "One of you no longer has what you offered, or a pot was empty, so the gamble was cancelled.",
                        discord.Color.red(),
                    )
                return

            result = await asyncio.to_thread(self.game.confirm_trade, self.trade_id, member.id)
            if result == "waiting":
                await asyncio.to_thread(self._build_components)
                embed = await asyncio.to_thread(self.build_embed)
                await interaction.response.edit_message(embed=embed, view=self)
            elif result == "completed":
                await self._finish(interaction, "✅ Trade Complete", "Both players confirmed — items and spirit stones have been exchanged!", discord.Color.green())
            else:
                await self._finish(interaction, "⚠️ Trade Failed", "One of you no longer has what you offered, so the trade was cancelled.", discord.Color.red())

        return callback

    async def _on_cancel(self, interaction: discord.Interaction):
        await asyncio.to_thread(self.game.cancel_trade, self.trade_id)
        await self._finish(interaction, "❌ Trade Cancelled", f"{interaction.user.display_name} cancelled the trade.", discord.Color.red())

    async def _finish(self, interaction: discord.Interaction, title: str, description: str, color: discord.Color):
        self.finished = True
        for child in self.children:
            child.disabled = True
        embed = discord.Embed(title=title, description=description, color=color)
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def on_timeout(self):
        if self.finished:
            return
        self.finished = True
        await asyncio.to_thread(self.game.cancel_trade, self.trade_id)
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            embed = discord.Embed(title="⌛ Trade Expired", description="This trade window timed out.", color=discord.Color.dark_grey())
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass

    async def refresh(self):
        if self.finished or self.message is None:
            return
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        try:
            await self.message.edit(embed=embed, view=self)
        except discord.HTTPException:
            pass


class TradeRequestView(GameView):
    def __init__(self, game, trade_id: int, initiator: discord.abc.User, target: discord.abc.User):
        super().__init__(timeout=300)
        self.game = game
        self.trade_id = trade_id
        self.initiator = initiator
        self.target = target
        self.message: discord.Message = None
        # See TradeWindowView's own mode comment -- same "read from the DB row, no
        # constructor argument" reasoning.
        self.mode = game.get_trade(trade_id)["mode"]

    def build_embed(self) -> discord.Embed:
        if self.mode == "gamble":
            embed = discord.Embed(
                title="🎲 Gamble Request",
                description=f"{self.target.mention} — **{self.initiator.display_name}** wants to gamble with you — winner takes both pots!",
                color=discord.Color.gold(),
            )
            embed.set_footer(text="Accept to open the gamble window. Both players add a pot and Confirm, then roll 1-100 — winner takes everything. Expires in 5 min.")
        else:
            embed = discord.Embed(
                title="🤝 Trade Request",
                description=f"{self.target.mention} — **{self.initiator.display_name}** wants to trade with you!",
                color=discord.Color.gold(),
            )
            embed.set_footer(text="Accept to open the trade window, then use the buttons to add items or currency. Both players must Confirm to complete. Expires in 5 min.")
        embed.add_field(name=f"🧍 {self.initiator.display_name}'s Offer:", value="*Nothing added yet*", inline=False)
        embed.add_field(name=f"🧍 {self.target.display_name}'s Offer:", value="*Nothing added yet*", inline=False)
        return embed

    @discord.ui.button(label="Accept Trade", emoji="✅", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("Only the invited player can accept this trade.", ephemeral=True)
            return
        await asyncio.to_thread(self.game.accept_trade, self.trade_id)
        window = TradeWindowView( self.game, self.trade_id, self.initiator, self.target)
        embed = await asyncio.to_thread(window.build_embed)
        await interaction.response.edit_message(embed=embed, view=window)
        window.message = await interaction.original_response()
        self.stop()

    @discord.ui.button(label="Decline", emoji="❌", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in (self.initiator.id, self.target.id):
            await interaction.response.send_message("This isn't your trade.", ephemeral=True)
            return
        await asyncio.to_thread(self.game.decline_trade, self.trade_id)
        for child in self.children:
            child.disabled = True
        embed = discord.Embed(title="🤝 Trade Declined", description="This trade request was declined.", color=discord.Color.red())
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def on_timeout(self):
        await asyncio.to_thread(self.game.decline_trade, self.trade_id)
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            embed = discord.Embed(title="🤝 Trade Expired", description="This trade request expired.", color=discord.Color.dark_grey())
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass
