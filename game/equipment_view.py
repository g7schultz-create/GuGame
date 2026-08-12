import asyncio
import traceback

import discord

from . import accessories_data
from . import blacksmith
from . import equipment as equipment_module
from .base_view import GameView
from .equipment import EQUIPMENT, SLOT_LABEL_BY_KEY, SLOT_TYPE_BY_KEY, SLOTS, describe_stat_bonuses, gear_power_score
from .manual_view import EFFECT_LABELS
from .ui_utils import NAV_PREV_VALUE, NAV_NEXT_VALUE, paginate_select_options

# Short sort-dropdown labels for every stat_bonuses key any Gu-slot item can carry (see the
# Gu Ability picker's "Sort: Stat" mode) — falls back to an auto title-cased key for anything
# added later that isn't listed here, so this never needs to be kept perfectly in sync.
GU_STAT_LABELS = {
    "str_pct": "STR %", "atk_pct": "ATK %", "def_pct": "DEF %", "spd_pct": "SPD %",
    "hp_pct": "HP %", "qi_pct": "QI %",
    "str_stat": "STR", "def_stat": "DEF", "spd_stat": "SPD", "hp": "HP", "luck_stat": "LCK",
    "dodge_chance_pct": "Dodge Chance", "crit_chance_pct": "Crit Chance", "crit_damage_pct": "Crit Damage",
    "lifesteal_percent": "Lifesteal", "beast_damage_reduction_pct": "Beast Dmg Reduction",
    "beast_damage_pct": "Beast Damage", "physical_damage_pct": "Physical Damage",
    "technique_damage_pct": "Technique Damage", "ignore_attack_chance": "Ignore Attack %",
    "low_hp_atk_bonus": "Low-HP ATK Bonus", "loot_chance_bonus_pct": "Loot Luck",
    "stone_reward_bonus_pct": "Stone Rewards", "essence_regen_pct": "Essence Recovery",
    "cultivation_speed_pct": "Cultivation Speed", "insight_gain_pct": "Insight Gain",
    "cooldown_reduction_pct": "Cooldown Reduction", "essence_purity_pct": "Essence Purity",
    "boss_damage_bonus_pct": "Boss Damage Bonus", "discovery_quality_bias_pct": "Discovery Quality Bias",
    "dream_realm_bias_pct": "Dream Realm Bias", "death_qi_loss_reduction_pct": "Death Qi Loss Reduction",
    "explore_luck_bonus_flat": "Explore Luck",
}
GU_SORT_MODES = [("power", "Power", "⚡"), ("rarity", "Rarity", "💎"), ("stat", "Stat", "📊")]

# Select option values for crafted_gear instances are prefixed so _on_pick_item can tell
# them apart from a catalog item_name (which is just the raw name) — see equip_crafted_gear
# vs equip_item in manager.py, the two different equip paths this branches into.
INSTANCE_VALUE_PREFIX = "gear:"
# Same idea for accessory/artifact instances (see accessories_data.py) — the Ring/Earring/
# Necklace/Bracelet/Artifact slots are, like Weapon/Head/Body, dual-nature: either an
# ordinary catalog item (Rusty Jade Ring, Basic Flying Artifact) or a rolled instance.
ACCESSORY_VALUE_PREFIX = "acc:"
ACCESSORY_SLOT_TYPES = {"Ring", "Earring", "Necklace", "Bracelet", "Artifact"}
# Assembled manuals (see /manual, manual_data.py) live entirely outside the `equipped`
# table/equipment.SLOTS system this view is otherwise built around — GameManager.
# equip_manual writes straight to players.equipped_primary_manual_id/
# equipped_auxiliary_manual_id instead, and (unlike every catalog/crafted_gear slot) a
# manual can be equipped in ONE of two independent slots that both feed the same
# cultivation bonus at different weights (primary 100%, auxiliary 35% — see
# GameDatabase._qi_rate_components). So these two are handled as local virtual slots
# rather than added to the shared equipment.SLOTS list, which would ripple into every
# other consumer of that list (compute_equipment_bonuses, unequip_all, starter equipment,
# ...) for something that was never really "one more slot_key" the same way Head/Body/
# Weapon are.
MANUAL_VALUE_PREFIX = "manual:"
MANUAL_VIRTUAL_SLOTS = [("manual_primary", "Primary Manual", "📘"), ("manual_auxiliary", "Auxiliary Manual", "📗")]
MANUAL_SLOT_NAME = {"manual_primary": "primary", "manual_auxiliary": "auxiliary"}
MANUAL_PLAYER_COLUMN = {"manual_primary": "equipped_primary_manual_id", "manual_auxiliary": "equipped_auxiliary_manual_id"}

# Label/emoji lookup covering every real slot_key (equipment.SLOTS) AND the two virtual
# manual slots above, keyed the same way self.selected_slot already is — one dict instead of
# branching on "is this a real or virtual slot" every time something just needs a name.
SLOT_INFO = {slot_key: (label, emoji) for slot_key, label, _, emoji in SLOTS}
SLOT_INFO.update({virtual_slot: (label, emoji) for virtual_slot, label, emoji in MANUAL_VIRTUAL_SLOTS})

# Groups equipment.SLOTS' 13 real slot_keys (plus the 2 virtual manual ones) into the 10
# category buttons /equipment now shows up front, instead of one giant "Slots" field for
# every piece at once. Single-slot categories jump straight to that slot's manage screen;
# multi-slot ones (Rings, Earrings, Artifacts, Manual) show a small picker for which of
# their slots to manage. (category_key, label, emoji, [slot_keys]).
CATEGORY_GROUPS = [
    ("head", "Head", "🪖", ["head"]),
    ("body", "Body", "🛡️", ["body"]),
    ("weapon", "Weapon", "⚔️", ["weapon"]),
    ("necklace", "Necklace", "⛓️", ["necklace"]),
    ("bracelet", "Bracelet/Belt", "🪢", ["bracelet"]),
    ("ring", "Rings", "💍", ["ring_1", "ring_2"]),
    ("earring", "Earrings", "📿", ["earring_1", "earring_2"]),
    ("artifact", "Artifacts", "💠", ["artifact_1", "artifact_2"]),
    ("manual", "Manual", "📖", ["manual_primary", "manual_auxiliary", "manual"]),
    # gu_ability_2 (Twin Gu Sovereign Physique's second slot) is listed here so
    # CATEGORY_FOR_SLOT/SLOT_INFO cover it, but it's never actually OFFERED to a player
    # without that physique -- see _effective_slot_keys below, which every real usage of a
    # category's slot_keys goes through instead of reading CATEGORY_BY_KEY directly.
    ("gu_ability", "Gu", "🐛", ["gu_ability", "gu_ability_2"]),
]
CATEGORY_BY_KEY = {key: (label, emoji, slot_keys) for key, label, emoji, slot_keys in CATEGORY_GROUPS}
CATEGORY_FOR_SLOT = {slot_key: key for key, _, _, slot_keys in CATEGORY_GROUPS for slot_key in slot_keys}


def _format_manual_line(manual: dict) -> str:
    parts = []
    for key, value in manual["effects"].items():
        label = EFFECT_LABELS.get(key, key.replace("_", " ").title())
        parts.append(f"+{value:.1f}% {label}" if "pct" in key else f"+{value:.1f} {label}")
    effects_text = " • ".join(parts) if parts else "No effects"
    return f"**{manual['name']}** — Rank {manual['rank']} {manual['rarity']} • {manual['coherence_band']}\n　{effects_text}"


def _format_gear_stats(gear) -> str:
    return describe_stat_bonuses(gear.stat_bonuses)


def _describe_gear_for_select(gear) -> str:
    """What a piece of gear actually does, for the equip dropdown — stat bonuses plus its
    active ability (Gu only), falling back to the flavor rank only if it has neither."""
    parts = []
    stats_text = _format_gear_stats(gear)
    if stats_text:
        parts.append(stats_text)
    if gear.active_ability:
        parts.append(f"⚔️ {gear.active_ability.name} (Qi {gear.active_ability.qi_cost})")
    return " • ".join(parts) or gear.rank


class EquipmentView(GameView):
    def __init__(self, user_id: int, game, player, display_name: str, avatar_url: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.game = game
        self.player = player
        self.display_name = display_name
        self.avatar_url = avatar_url
        self.selected_category = None
        self.selected_slot = None
        self.last_result = None
        self.gu_sort_mode = "power"  # "power" | "rarity" | "stat"
        self.gu_sort_stat: str = None
        self.gu_sort_stat_page = 0
        # Generalized to every slot's item-select (was Gu-only) -- see _add_item_select.
        # Reset to 0 whenever the selected slot/category changes.
        self.item_page = 0
        # Cross-slot search (see EquipmentSearchModal/_search_results) -- lets a player find
        # an item by name without knowing which category it lives under first.
        self.search_active = False
        self.search_query: str = None
        self.search_page = 0
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your equipment.", ephemeral=True)
            return False
        return True

    def refresh(self):
        self.player = self.game.get_player_stats(self.user_id, self.display_name)

    def _effective_slot_keys(self, category_key: str, player: dict) -> list:
        """A category's real slot_keys, except gu_ability_2 is dropped entirely unless the
        player currently holds Twin Gu Sovereign Physique -- per explicit request the second
        Gu slot must be invisible to a non-qualifying player, not just refused on equip (see
        GameManager.equip_item's own backstop refusal for anything that bypasses this UI)."""
        _, _, slot_keys = CATEGORY_BY_KEY[category_key]
        if category_key == "gu_ability" and player["physique_name"] != equipment_module.TWIN_GU_SOVEREIGN_PHYSIQUE_NAME:
            return [slot_key for slot_key in slot_keys if slot_key != equipment_module.GU_SLOT_KEY_2]
        return slot_keys

    def _manual_slot_description(self, player: dict, virtual_slot: str) -> str:
        manual_id = player[MANUAL_PLAYER_COLUMN[virtual_slot]]
        if not manual_id:
            return "Current: Empty"
        manual = self.game.db.get_manual(manual_id)
        return f"Current: {manual['name']}" if manual else "Current: Empty"

    def _build_real_slot_options(self, slot_type: str, current: str) -> list:
        inventory = self.game.get_inventory(self.user_id)
        catalog_candidates = [
            (-gear_power_score(gear), discord.SelectOption(label=item_name, value=item_name, description=_describe_gear_for_select(gear)[:100]))
            for item_name, gear in EQUIPMENT.items()
            if gear.slot_type == slot_type and inventory.get(item_name, 0) > 0
        ]
        # Rolled crafted_gear instances (see /blacksmith, /weapons) — only Weapon/Head/
        # Body ever have any, and only the ones not already sitting in an equipped slot
        # (an instance is "in your bag" simply by not being referenced from `equipped`,
        # there's no separate inventory row to filter on like catalog gear above).
        equipped_gear_ids = set(self.game.db.get_equipped_gear_ids(self.user_id).values())
        instance_candidates = [
            (
                -gear["power_score"],
                discord.SelectOption(
                    label=blacksmith.crafted_gear_display_name(gear["base_type"], gear["tier"], gear["gear_id"])[:100],
                    value=f"{INSTANCE_VALUE_PREFIX}{gear['gear_id']}",
                    description=describe_stat_bonuses(gear["stat_bonuses"])[:100],
                ),
            )
            for gear in self.game.get_player_crafted_gear(self.user_id)
            if gear["slot_type"] == slot_type and gear["gear_id"] not in equipped_gear_ids
        ]

        accessory_candidates = []
        if slot_type in ACCESSORY_SLOT_TYPES:
            equipped_accessory_ids = set(self.game.db.get_equipped_accessory_ids(self.user_id).values())
            rarity_rank = {r: i for i, r in enumerate(accessories_data.RARITY_ORDER)}
            for entry in self.game.get_player_accessories_artifacts(self.user_id):
                affix = entry["affix"]
                if affix.slot_type != slot_type or entry["instance_id"] in equipped_accessory_ids:
                    continue
                needs_attunement = affix.rarity in accessories_data.ATTUNEMENT_REQUIRED_RARITIES and not entry["attuned"]
                label = f"{affix.name} #{entry['instance_id']}" + (" 🔒 needs attunement" if needs_attunement else "")
                desc = f"Rank {affix.rank} {affix.rarity} • {affix.description}"[:100]
                accessory_candidates.append((
                    -rarity_rank.get(affix.rarity, 0),
                    discord.SelectOption(label=label[:100], value=f"{ACCESSORY_VALUE_PREFIX}{entry['instance_id']}", description=desc),
                ))

        return [option for _, option in sorted(catalog_candidates + instance_candidates + accessory_candidates, key=lambda row: row[0])]

    def _build_manual_slot_options(self, player: dict) -> list:
        # Excludes whatever's currently in EITHER manual slot — equip_manual itself rejects
        # putting the same manual in both at once, and re-picking whatever's already in the
        # slot you're looking at is a pointless no-op (it'd just reset the change cooldown).
        occupied = {player["equipped_primary_manual_id"], player["equipped_auxiliary_manual_id"]} - {None}
        candidates = [
            (-manual["coherence"], discord.SelectOption(
                label=manual["name"][:100], value=f"{MANUAL_VALUE_PREFIX}{manual['manual_id']}",
                description=f"Rank {manual['rank']} {manual['rarity']} • {manual['coherence_band']} ({manual['coherence']}/100)"[:100],
            ))
            for manual in self.game.get_player_manuals(self.user_id)
            if manual["manual_id"] not in occupied
        ]
        return [option for _, option in sorted(candidates, key=lambda row: row[0])]

    # -- Gu Ability sorting (the slot with by far the most possible items — 380+ registered
    # across every family/quality — so "just show them" the way every other slot does isn't
    # enough to actually find one; see GU_SORT_MODES) ---------------------------------------

    def _owned_gu_items(self) -> list:
        inventory = self.game.get_inventory(self.user_id)
        return [
            (item_name, gear) for item_name, gear in EQUIPMENT.items()
            if gear.slot_type == "Gu" and inventory.get(item_name, 0) > 0
        ]

    @staticmethod
    def _gu_rarity_rank(item_name: str) -> int:
        """Higher = rarer. A handful of named Gu (Battle Intent Gu, Flying Sword Gu, ...)
        never got a tiered (Family (Quality)) name at all — parse_gu_name can't place them on
        the Common..Immortal ladder, so they rank ABOVE Immortal instead of falling to the
        bottom: these are unique hand-authored rewards, not undercooked Common drops."""
        _, quality = equipment_module.parse_gu_name(item_name)
        if quality is None:
            return len(equipment_module.GU_QUALITY_ORDER)
        return equipment_module.GU_QUALITY_STARS[quality]

    def _gu_available_sort_stats(self) -> list:
        """Every stat_bonuses key present among Gu the player actually OWNS — built fresh
        each render (not a static full-catalog list) so the "Stat" sort dropdown only ever
        offers stats that could actually change something right now."""
        keys = set()
        for _, gear in self._owned_gu_items():
            keys.update(gear.stat_bonuses.keys())
        return sorted(keys, key=lambda k: GU_STAT_LABELS.get(k, k))

    def _build_gu_options(self) -> list:
        entries = self._owned_gu_items()
        if self.gu_sort_mode == "rarity":
            entries.sort(key=lambda e: (-self._gu_rarity_rank(e[0]), e[0]))
        elif self.gu_sort_mode == "stat" and self.gu_sort_stat:
            entries.sort(key=lambda e: (-e[1].stat_bonuses.get(self.gu_sort_stat, 0), -gear_power_score(e[1]), e[0]))
        else:
            entries.sort(key=lambda e: (-gear_power_score(e[1]), e[0]))
        return [
            discord.SelectOption(label=item_name[:100], value=item_name, description=_describe_gear_for_select(gear)[:100])
            for item_name, gear in entries
        ]

    def _add_gu_sort_controls(self, row: int):
        for key, label, emoji in GU_SORT_MODES:
            button = discord.ui.Button(label=f"Sort: {label}", emoji=emoji, row=row)
            is_active = key == self.gu_sort_mode
            button.style = discord.ButtonStyle.primary if is_active else discord.ButtonStyle.secondary
            button.disabled = is_active
            button.callback = self._make_gu_sort_mode_callback(key)
            self.add_item(button)

    def _add_gu_stat_select(self, row: int):
        stat_keys = self._gu_available_sort_stats()
        if self.gu_sort_stat not in stat_keys:
            self.gu_sort_stat = stat_keys[0] if stat_keys else None
        options = [
            discord.SelectOption(label=GU_STAT_LABELS.get(key, key.replace("_", " ").title())[:100], value=key, default=(key == self.gu_sort_stat))
            for key in stat_keys
        ]
        page_options, total_pages, self.gu_sort_stat_page = paginate_select_options(options, self.gu_sort_stat_page)
        placeholder = "Sort by which stat?"
        if total_pages > 1:
            placeholder += f" (page {self.gu_sort_stat_page + 1}/{total_pages})"
        select = discord.ui.Select(
            placeholder=placeholder, options=page_options or [discord.SelectOption(label="None", value="none")],
            disabled=not options, row=row,
        )
        select.callback = self._on_pick_gu_sort_stat
        self.add_item(select)

    def _build_components(self):
        self.clear_items()
        equipped = self.game.get_equipped(self.user_id)
        player = self.game.get_player_stats(self.user_id, self.display_name)

        if self.search_active:
            self._add_search_result_select(equipped, player, row=0)
            back_button = discord.ui.Button(label="Back", emoji="↩️", row=1)
            back_button.callback = self._on_back
            self.add_item(back_button)
            bottom_row = 2
        elif self.selected_slot:
            self._add_item_select(equipped, player, row=0)
            next_row = 1
            if self.selected_slot in ("gu_ability", "gu_ability_2"):
                self._add_gu_sort_controls(row=next_row)
                next_row += 1
                if self.gu_sort_mode == "stat":
                    self._add_gu_stat_select(row=next_row)
                    next_row += 1
            back_button = discord.ui.Button(label="Back", emoji="↩️", row=next_row)
            back_button.callback = self._on_back
            self.add_item(back_button)
            bottom_row = next_row + 1
        elif self.selected_category:
            slot_keys = self._effective_slot_keys(self.selected_category, player)
            picker_options = []
            for slot_key in slot_keys:
                label, emoji = SLOT_INFO[slot_key]
                description = self._manual_slot_description(player, slot_key) if slot_key in MANUAL_SLOT_NAME else f"Current: {equipped.get(slot_key) or 'Empty'}"
                picker_options.append(discord.SelectOption(label=label, value=slot_key, emoji=emoji, description=description[:100]))
            picker = discord.ui.Select(placeholder="Which slot?", options=picker_options, row=0)
            picker.callback = self._on_pick_slot
            self.add_item(picker)
            back_button = discord.ui.Button(label="Back", emoji="↩️", row=1)
            back_button.callback = self._on_back
            self.add_item(back_button)
            bottom_row = 2
        else:
            # Top level — one button per category (10 total, 5 per row) instead of the old
            # single "manage one equipment slot" dropdown listing every slot at once.
            for index, (key, label, emoji, _) in enumerate(CATEGORY_GROUPS):
                button = discord.ui.Button(label=label, emoji=emoji, style=discord.ButtonStyle.primary, row=index // 5)
                button.callback = self._make_category_callback(key)
                self.add_item(button)
            search_button = discord.ui.Button(label="Search", emoji="🔍", style=discord.ButtonStyle.secondary, row=2)
            search_button.callback = self._on_open_search
            self.add_item(search_button)
            bottom_row = 2

        profile_button = discord.ui.Button(label="Profile", emoji="📖", style=discord.ButtonStyle.secondary, row=bottom_row)
        profile_button.callback = self._on_profile
        self.add_item(profile_button)

    def _raw_slot_options(self, slot_key: str, equipped: dict, player: dict) -> list:
        """Every real candidate for slot_key, unpaginated and with no leading 'Unequip'
        entry -- shared by _add_item_select (self.selected_slot, the normal per-slot screen)
        and _build_all_owned_gear_by_slot (every slot at once, for cross-slot search)."""
        if slot_key in MANUAL_SLOT_NAME:
            return self._build_manual_slot_options(player)
        if slot_key in ("gu_ability", "gu_ability_2"):
            return self._build_gu_options()
        slot_type = SLOT_TYPE_BY_KEY[slot_key]
        current = equipped.get(slot_key)
        return self._build_real_slot_options(slot_type, current)

    def _add_item_select(self, equipped: dict, player: dict, row: int):
        """The actual equip/unequip dropdown for self.selected_slot. Paginated (see
        ui_utils.paginate_select_options) for EVERY slot now, not just Gu Ability -- a
        handful of slots (Weapon, accessories, ...) can genuinely exceed Discord's 25-option
        cap once crafted-gear/accessory instances pile up, and used to just silently truncate
        with no way to see the rest."""
        if self.selected_slot in MANUAL_SLOT_NAME:
            current = player[MANUAL_PLAYER_COLUMN[self.selected_slot]]
            placeholder_base = "Choose a manual..."
        elif self.selected_slot in ("gu_ability", "gu_ability_2"):
            current = equipped.get(self.selected_slot)
            placeholder_base = "Choose gear for Gu Ability..."
        else:
            current = equipped.get(self.selected_slot)
            placeholder_base = f"Choose gear for {SLOT_LABEL_BY_KEY[self.selected_slot]}..."

        leading = []
        if current:
            leading.append(discord.SelectOption(label="Unequip (leave empty)", value="__unequip__", emoji="🗑️"))
        raw_options = self._raw_slot_options(self.selected_slot, equipped, player)
        page_options, total_pages, self.item_page = paginate_select_options(raw_options, self.item_page, reserved_slots=len(leading))
        options = leading + page_options
        placeholder = placeholder_base if options else "Nothing available for this slot"
        if total_pages > 1:
            placeholder += f" (page {self.item_page + 1}/{total_pages})"

        item_select = discord.ui.Select(
            placeholder=placeholder[:150],
            options=options[:25] or [discord.SelectOption(label="None", value="none")],
            disabled=not options,
            row=row,
        )
        item_select.callback = self._on_pick_item
        self.add_item(item_select)

    def _build_all_owned_gear_by_slot(self, equipped: dict, player: dict) -> dict:
        """slot_key -> raw options (see _raw_slot_options) for every slot the player could
        equip into right now -- respects the same Twin Gu Sovereign Physique gating as the
        ordinary category picker (_effective_slot_keys) and drops the legacy "manual" slot,
        same as the category summary embed does. Powers global search (EquipmentSearchModal)."""
        slot_keys = []
        for category_key, _, _, _ in CATEGORY_GROUPS:
            for slot_key in self._effective_slot_keys(category_key, player):
                if slot_key == "manual":
                    continue
                slot_keys.append(slot_key)
        return {slot_key: self._raw_slot_options(slot_key, equipped, player) for slot_key in slot_keys}

    def _search_results(self, equipped: dict, player: dict) -> list:
        """Every owned item across every slot whose label contains self.search_query
        (case-insensitive), tagged as "{slot_key}::{value}" so picking one can be equipped
        directly (see _on_pick_search_result/_resolve_equip_choice) without first navigating
        to its slot."""
        query = (self.search_query or "").lower()
        results = []
        for slot_key, raw_options in self._build_all_owned_gear_by_slot(equipped, player).items():
            label, emoji = SLOT_INFO[slot_key]
            for option in raw_options:
                if query and query not in option.label.lower():
                    continue
                description = f"{label} — {option.description}" if option.description else label
                results.append(discord.SelectOption(
                    label=option.label[:100], value=f"{slot_key}::{option.value}",
                    description=description[:100], emoji=emoji,
                ))
        return results

    def _add_search_result_select(self, equipped: dict, player: dict, row: int):
        raw_results = self._search_results(equipped, player)
        page_options, total_pages, self.search_page = paginate_select_options(raw_results, self.search_page)
        placeholder = f"🔍 '{self.search_query}'" if self.search_query else "🔍 Search"
        if not raw_results:
            placeholder += " — no matches"
        elif total_pages > 1:
            placeholder += f" (page {self.search_page + 1}/{total_pages})"

        select = discord.ui.Select(
            placeholder=placeholder[:150],
            options=page_options[:25] or [discord.SelectOption(label="None", value="none")],
            disabled=not raw_results,
            row=row,
        )
        select.callback = self._on_pick_search_result
        self.add_item(select)

    def _make_category_callback(self, category_key: str):
        async def callback(interaction: discord.Interaction):
            self.selected_category = category_key
            player = await asyncio.to_thread(self.game.get_player_stats, self.user_id, self.display_name)
            slot_keys = self._effective_slot_keys(category_key, player)
            # Single-slot categories (Head, Body, Weapon, ... and Gu for anyone without Twin
            # Gu Sovereign Physique) jump straight to slot management — no point showing a
            # "which slot?" picker with exactly one option.
            if len(slot_keys) == 1:
                self.selected_slot = slot_keys[0]
            self.last_result = None
            self.item_page = 0
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    async def _on_pick_slot(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 0)
        self.selected_slot = select.values[0]
        self.last_result = None
        self.item_page = 0
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def _make_gu_sort_mode_callback(self, key: str):
        async def callback(interaction: discord.Interaction):
            self.gu_sort_mode = key
            self.item_page = 0
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    async def _on_pick_gu_sort_stat(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 2)
        choice = select.values[0]
        if choice == NAV_PREV_VALUE:
            self.gu_sort_stat_page = max(0, self.gu_sort_stat_page - 1)
        elif choice == NAV_NEXT_VALUE:
            self.gu_sort_stat_page += 1
        elif choice != "none":
            self.gu_sort_stat = choice
            self.item_page = 0
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def _resolve_equip_choice(self, choice: str) -> str:
        """Actually equips/unequips `choice` (as produced by _raw_slot_options, or the
        slot-tagged half of a global search result -- see _on_pick_search_result) into
        self.selected_slot, returning the result message. Shared so picking a search result
        equips exactly the same way picking that same option from its own slot screen would."""
        if self.selected_slot in MANUAL_SLOT_NAME:
            manual_slot = MANUAL_SLOT_NAME[self.selected_slot]
            if choice == "__unequip__":
                _, result = self.game.unequip_manual(self.user_id, self.display_name, manual_slot)
            else:
                manual_id = int(choice[len(MANUAL_VALUE_PREFIX):])
                _, result = self.game.equip_manual(self.user_id, self.display_name, manual_id, manual_slot)
        elif choice == "__unequip__":
            if self.selected_slot in self.game.ACCESSORY_ARTIFACT_SLOT_TYPES:
                _, result = self.game.unequip_accessory_artifact(self.user_id, self.display_name, self.selected_slot)
            else:
                _, result = self.game.unequip_item(self.user_id, self.display_name, self.selected_slot)
        elif choice.startswith(INSTANCE_VALUE_PREFIX):
            gear_id = int(choice[len(INSTANCE_VALUE_PREFIX):])
            _, result = self.game.equip_crafted_gear(self.user_id, self.display_name, gear_id)
        elif choice.startswith(ACCESSORY_VALUE_PREFIX):
            instance_id = int(choice[len(ACCESSORY_VALUE_PREFIX):])
            _, result = self.game.equip_accessory_artifact(self.user_id, self.display_name, self.selected_slot, instance_id)
        else:
            _, result = self.game.equip_item(self.user_id, self.display_name, self.selected_slot, choice)
        self.refresh()
        return result

    async def _on_pick_item(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 0)
        choice = select.values[0]
        if choice == NAV_PREV_VALUE:
            self.item_page = max(0, self.item_page - 1)
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)
            return
        if choice == NAV_NEXT_VALUE:
            self.item_page += 1
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)
            return
        self.last_result = await asyncio.to_thread(self._resolve_equip_choice, choice)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_open_search(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EquipmentSearchModal(self))

    async def _on_pick_search_result(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 0)
        choice = select.values[0]
        if choice == NAV_PREV_VALUE:
            self.search_page = max(0, self.search_page - 1)
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)
            return
        if choice == NAV_NEXT_VALUE:
            self.search_page += 1
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)
            return
        if choice == "none":
            return
        slot_key, item_choice = choice.split("::", 1)
        self.selected_slot = slot_key
        self.selected_category = CATEGORY_FOR_SLOT[slot_key]
        self.search_active = False
        self.search_query = None
        self.item_page = 0
        self.last_result = await asyncio.to_thread(self._resolve_equip_choice, item_choice)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_back(self, interaction: discord.Interaction):
        if self.search_active:
            # Search is only ever entered from the top level (see _build_components' top-level
            # branch, the only place the Search button appears), so leaving it always lands
            # back at the top level too -- explicit here rather than relying on whatever
            # selected_category/selected_slot happened to be beforehand.
            self.search_active = False
            self.search_query = None
            self.search_page = 0
            self.selected_category = None
            self.selected_slot = None
        elif self.selected_slot:
            # Single-slot categories skipped their own picker screen (see
            # _make_category_callback), so backing out of slot management on one of those
            # goes all the way to the top level instead of a picker with nothing useful on it.
            player = await asyncio.to_thread(self.game.get_player_stats, self.user_id, self.display_name)
            slot_keys = self._effective_slot_keys(self.selected_category, player)
            self.selected_slot = None
            self.item_page = 0
            if len(slot_keys) == 1:
                self.selected_category = None
        else:
            self.selected_category = None
        self.last_result = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_profile(self, interaction: discord.Interaction):
        from .views import ProfileView  # local import: avoids a circular import at module load time

        view = ProfileView( self.user_id, self.game, self.player, self.display_name, self.avatar_url)
        embed = await asyncio.to_thread(view.build_embed)
        await interaction.response.edit_message(embed=embed, view=view)

    def _describe_slot(self, slot_key: str) -> str:
        """One formatted line (or two, for gear with a stats readout) for a single slot's
        current contents — shared by the category-detail and single-slot embed views below,
        same formatting the old all-in-one "Slots" field used per slot."""
        label, emoji = SLOT_INFO[slot_key]
        if slot_key in MANUAL_SLOT_NAME:
            manual_id = self.player[MANUAL_PLAYER_COLUMN[slot_key]]
            manual = self.game.db.get_manual(manual_id) if manual_id else None
            return f"{emoji} **{label}**\n　{_format_manual_line(manual)}" if manual else f"{emoji} **{label}**: *Empty*"

        equipped = self.game.get_equipped(self.user_id)
        item_name = equipped.get(slot_key)
        if not item_name:
            return f"{emoji} **{label}**: *Empty*"
        equipped_gear_ids = self.game.db.get_equipped_gear_ids(self.user_id)
        if slot_key in equipped_gear_ids:
            crafted = self.game.db.get_crafted_gear(equipped_gear_ids[slot_key])
            stats_text = describe_stat_bonuses(crafted["stat_bonuses"]) if crafted else ""
            rank = f"T{crafted['tier']}" if crafted else "?"
            return f"{emoji} **{label}** Rank {rank}\n　{item_name} — {stats_text}"
        equipped_accessory_ids = self.game.db.get_equipped_accessory_ids(self.user_id)
        if slot_key in equipped_accessory_ids:
            instance = self.game.db.get_accessory_instance(equipped_accessory_ids[slot_key])
            affix = self.game._affix_for_instance(instance) if instance else None
            if affix:
                stats_text = describe_stat_bonuses(affix.stat_bonuses) or affix.description
                return f"{emoji} **{label}** Rank {affix.rank} {affix.rarity}\n　{item_name} — {stats_text}"
            return f"{emoji} **{label}**\n　{item_name}"
        gear = EQUIPMENT.get(item_name)
        stats_text = _format_gear_stats(gear) if gear else ""
        return f"{emoji} **{label}** Rank {gear.rank if gear else '?'}\n　{item_name} — {stats_text}"

    def build_embed(self) -> discord.Embed:
        p = self.player
        equipped = self.game.get_equipped(self.user_id)
        bonuses = self.game.compute_equipment_bonuses(self.user_id)
        stat_bonus = bonuses["stats"]

        manual_slots_filled = sum(1 for _, col in MANUAL_PLAYER_COLUMN.items() if p[col])
        # SLOTS always includes gu_ability_2 (Twin Gu Sovereign Physique's second Gu slot),
        # but it doesn't count toward THIS player's own total unless they actually qualify --
        # otherwise everyone else's denominator would be inflated by a slot they can never fill.
        total_slots = len(SLOTS) + len(MANUAL_VIRTUAL_SLOTS)
        if p["physique_name"] != equipment_module.TWIN_GU_SOVEREIGN_PHYSIQUE_NAME:
            total_slots -= 1

        embed = discord.Embed(title="🛡️ Equipment Loadout", description=self.display_name, color=discord.Color.dark_purple())
        embed.set_thumbnail(url=self.avatar_url)
        embed.add_field(name="Slots Equipped", value=f"{len(equipped) + manual_slots_filled}/{total_slots}", inline=False)

        embed.add_field(
            name="Total Stats",
            value=(
                f"🎯 ATK: {p['atk_stat'] + stat_bonus['atk_stat']:.0f} ⚔️ STR: {p['str_stat'] + stat_bonus['str_stat']:.0f} ❤️ HP: {p['hp'] + stat_bonus['hp']:.0f}\n"
                f"🛡️ DEF: {p['def_stat'] + stat_bonus['def_stat']:.0f} 🏃 SPD: {p['spd_stat'] + stat_bonus['spd_stat']:.0f}\n"
                f"💧 QI: {p['qi_stat'] + stat_bonus['qi_stat']:.0f} 🍀 LCK: {p['luck_stat'] + stat_bonus['luck_stat']:.0f}"
            ),
            inline=False,
        )
        embed.add_field(
            name="Equipment Bonuses",
            value=(
                f"🎯 ATK: +{stat_bonus['atk_stat']:.0f} ⚔️ STR: +{stat_bonus['str_stat']:.0f} ❤️ HP: +{stat_bonus['hp']:.0f}\n"
                f"🛡️ DEF: +{stat_bonus['def_stat']:.0f} 🏃 SPD: +{stat_bonus['spd_stat']:.0f}\n"
                f"💧 QI: +{stat_bonus['qi_stat']:.0f} 🍀 LCK: +{stat_bonus['luck_stat']:.0f}"
            ),
            inline=False,
        )
        embed.add_field(name="Manual Bonus", value=f"+{bonuses['cultivation_speed_pct'] * 100:.0f}% cultivation gain", inline=False)

        gu_bonus_lines = [
            equipment_module.SPECIAL_STAT_TEXT[key](bonuses[key])
            for key in equipment_module.SPECIAL_STAT_TEXT
            if key != "cultivation_speed_pct" and bonuses.get(key)
        ]
        if gu_bonus_lines:
            embed.add_field(name="✨ Passive Bonuses", value=" • ".join(gu_bonus_lines), inline=False)

        if self.search_active:
            value = f"Searching for **{self.search_query}**..." if self.search_query else "Searching..."
            embed.add_field(name="🔍 Search", value=value, inline=False)
        elif self.selected_slot:
            # Focused on exactly one slot — the item-equip dropdown below the embed handles
            # changing it, this just shows what's there right now.
            cat_label, cat_emoji, _ = CATEGORY_BY_KEY[self.selected_category]
            embed.add_field(name=f"{cat_emoji} {cat_label}", value=self._describe_slot(self.selected_slot), inline=False)
            if self.selected_slot in ("gu_ability", "gu_ability_2"):
                sort_label = {
                    "power": "⚡ Power", "rarity": "💎 Rarity",
                    "stat": f"📊 {GU_STAT_LABELS.get(self.gu_sort_stat, self.gu_sort_stat) if self.gu_sort_stat else '—'}",
                }[self.gu_sort_mode]
                embed.add_field(name="Sorted By", value=sort_label, inline=True)
        elif self.selected_category:
            cat_label, cat_emoji, _ = CATEGORY_BY_KEY[self.selected_category]
            slot_keys = self._effective_slot_keys(self.selected_category, p)
            # The legacy "manual" slot (superseded by manual_primary/manual_auxiliary) is
            # dropped from this summary when it's empty -- almost nobody has anything there
            # anymore, so an always-"Empty" third line was just noise (per explicit request).
            # Still shown if a player genuinely has something equipped there (from before the
            # newer system existed), and still reachable/manageable via the slot picker either
            # way -- this only trims the summary, not the actual slot.
            if "manual" in slot_keys and not self.game.get_equipped(self.user_id).get("manual"):
                slot_keys = [sk for sk in slot_keys if sk != "manual"]
            detail = "\n".join(self._describe_slot(slot_key) for slot_key in slot_keys)
            embed.add_field(name=f"{cat_emoji} {cat_label}", value=detail[:1024], inline=False)
        else:
            embed.add_field(name="Slots", value="Pick a category below to see what's equipped and change it.", inline=False)

        if self.last_result:
            embed.add_field(name="Result", value=self.last_result, inline=False)

        embed.set_footer(text="These bonuses aren't reflected on /profile's Combat tab yet.")
        return embed


class EquipmentSearchModal(discord.ui.Modal, title="Search Your Gear"):
    query_input = discord.ui.TextInput(label="Item name (or part of it)", placeholder="e.g. Jade, Immortal, Ring...", max_length=100)

    def __init__(self, view: "EquipmentView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        self.view_ref.search_active = True
        self.view_ref.search_query = str(self.query_input.value).strip()
        self.view_ref.search_page = 0
        self.view_ref.last_result = None
        await asyncio.to_thread(self.view_ref._build_components)
        embed = await asyncio.to_thread(self.view_ref.build_embed)
        await interaction.response.edit_message(embed=embed, view=self.view_ref)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        # Modal has its own separate error hook from View.on_error (see base_view.py) — same
        # "surface a real message instead of silently hanging" treatment as CharacterNameModal.
        print(f"[modal error] EquipmentSearchModal raised {type(error).__name__}: {error}")
        traceback.print_exception(type(error), error, error.__traceback__)
        message = f"⚠️ Something went wrong ({type(error).__name__}: {error})."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass
