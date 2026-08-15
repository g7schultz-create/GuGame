import asyncio
import discord

from . import accessories_data
from .base_view import GameView
from .equipment import SLOT_TYPE_EMOJI, describe_stat_bonuses
from .ui_utils import format_number

SLOT_TYPE_ORDER = ["Ring", "Earring", "Necklace", "Bracelet", "Artifact"]
PAGE_SIZE = 10  # keeps both the Select (Discord's 25-option cap) and the embed text well clear of any limit


def _item_line(entry: dict, equipped_ids: set) -> str:
    affix = entry["affix"]
    marker = "✅ " if entry["instance_id"] in equipped_ids else "　"
    attune_note = "" if affix.rarity not in accessories_data.ATTUNEMENT_REQUIRED_RARITIES else (" 🔓 attuned" if entry["attuned"] else " 🔒 needs attunement")
    stats_text = describe_stat_bonuses(affix.stat_bonuses) or affix.description
    return f"{marker}**{affix.name} #{entry['instance_id']}** — Rank {affix.rank} {affix.rarity}{attune_note}\n　{stats_text}"


class AccessoriesView(GameView):
    """/accessories: a text-document-style listing of every accessory/artifact instance you
    own (see accessories_data.py, the insanity accessories and artifacts design doc), plus
    attune/salvage/activate controls — the equip/unequip step itself lives on /equipment
    alongside every other gear slot, same as crafted_gear weapons do on /weapons."""

    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.slot_type_filter: str = None  # None == "All Types"
        self.selected_instance_id: int = None
        self.page: int = 0
        self.last_result: str = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Run `/accessories` yourself to manage your own collection.", ephemeral=True)
            return False
        return True

    def _owned(self) -> list:
        return self.game.get_player_accessories_artifacts(self.user_id)

    def _filtered_owned(self) -> list:
        owned = self._owned()
        if self.slot_type_filter is None:
            return owned
        return [e for e in owned if e["affix"].slot_type == self.slot_type_filter]

    def _total_pages(self) -> int:
        return max(1, -(-len(self._filtered_owned()) // PAGE_SIZE))  # ceil div

    def _clamp_page(self):
        self.page = max(0, min(self.page, self._total_pages() - 1))

    def _paged_owned(self) -> list:
        self._clamp_page()
        start = self.page * PAGE_SIZE
        return self._filtered_owned()[start:start + PAGE_SIZE]

    def _equipped_ids(self) -> set:
        return set(self.game.db.get_equipped_accessory_ids(self.user_id).values())

    def _selected_entry(self):
        if self.selected_instance_id is None:
            return None
        return next((e for e in self._owned() if e["instance_id"] == self.selected_instance_id), None)

    def _build_components(self):
        self.clear_items()

        # Type filter -- a Select (not 6 buttons: "All" + the 5 slot types would spill past
        # Discord's 5-per-row button cap) so it fits in exactly one row regardless of option
        # count, same fix views.py's _build_subcategory_select already applies for this shape.
        filter_options = [
            discord.SelectOption(label="All Types", value="all", emoji="💍", default=self.slot_type_filter is None),
        ]
        for slot_type in SLOT_TYPE_ORDER:
            filter_options.append(discord.SelectOption(
                label=slot_type, value=slot_type, emoji=SLOT_TYPE_EMOJI.get(slot_type),
                default=(slot_type == self.slot_type_filter),
            ))
        filter_select = discord.ui.Select(placeholder="Filter by type...", options=filter_options, row=0)
        filter_select.callback = self._on_pick_type
        self.add_item(filter_select)

        self._clamp_page()
        paged = self._paged_owned()
        options = [
            discord.SelectOption(
                label=f"{e['affix'].name} #{e['instance_id']}"[:100],
                value=str(e["instance_id"]),
                description=f"Rank {e['affix'].rank} {e['affix'].rarity} • {e['affix'].effect_key.replace('_', ' ')}"[:100],
                default=(e["instance_id"] == self.selected_instance_id),
            )
            for e in paged
        ]
        no_items_text = "Nothing owned in this type yet" if self.slot_type_filter else "Nothing owned yet — try /hunt, /raid, or /search"
        select = discord.ui.Select(
            placeholder="Choose an item..." if options else no_items_text,
            options=options or [discord.SelectOption(label="None", value="none")],
            disabled=not options,
            row=1,
        )
        select.callback = self._on_pick_item
        self.add_item(select)

        total_pages = self._total_pages()
        prev_button = discord.ui.Button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=2, disabled=self.page <= 0)
        prev_button.callback = self._on_prev_page
        self.add_item(prev_button)

        page_label = discord.ui.Button(label=f"Page {self.page + 1}/{total_pages}", style=discord.ButtonStyle.secondary, row=2, disabled=True)
        self.add_item(page_label)

        next_button = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary, row=2, disabled=self.page >= total_pages - 1)
        next_button.callback = self._on_next_page
        self.add_item(next_button)

        entry = self._selected_entry()
        equipped_ids = self._equipped_ids()
        can_attune = bool(entry) and entry["affix"].rarity in accessories_data.ATTUNEMENT_REQUIRED_RARITIES and not entry["attuned"]
        can_unattune = bool(entry) and entry["attuned"] and entry["instance_id"] not in equipped_ids
        can_salvage = bool(entry) and entry["instance_id"] not in equipped_ids and entry["affix"].rarity != "Unique"
        can_activate = bool(entry) and entry["instance_id"] in equipped_ids and entry["affix"].effect_key not in (
            "stat", "encounter_shield", "post_action_buff", "extra_loot_roll_daily", "loot_duplicate_daily", "defeat_ward_daily",
        )
        duplicate_salvageable_count = 0
        if entry:
            duplicate_salvageable_count = sum(
                1 for e in self._owned()
                if e["affix"].item_id == entry["affix"].item_id and e["instance_id"] not in equipped_ids
            ) if entry["affix"].rarity != "Unique" else 0
        can_salvage_all = duplicate_salvageable_count > 0

        attune_button = discord.ui.Button(label="Attune", emoji="🔓", style=discord.ButtonStyle.primary, row=3, disabled=not can_attune)
        attune_button.callback = self._on_attune
        self.add_item(attune_button)

        unattune_button = discord.ui.Button(label="Unattune", emoji="🔒", style=discord.ButtonStyle.secondary, row=3, disabled=not can_unattune)
        unattune_button.callback = self._on_unattune
        self.add_item(unattune_button)

        activate_button = discord.ui.Button(label="Activate", emoji="✨", style=discord.ButtonStyle.success, row=3, disabled=not can_activate)
        activate_button.callback = self._on_activate
        self.add_item(activate_button)

        salvage_button = discord.ui.Button(label="Salvage", emoji="🔨", style=discord.ButtonStyle.danger, row=3, disabled=not can_salvage)
        salvage_button.callback = self._on_salvage
        self.add_item(salvage_button)

        salvage_all_button = discord.ui.Button(
            label=f"Salvage All ({duplicate_salvageable_count})" if duplicate_salvageable_count else "Salvage All",
            emoji="🧺", style=discord.ButtonStyle.danger, row=3, disabled=not can_salvage_all,
        )
        salvage_all_button.callback = self._on_salvage_all
        self.add_item(salvage_all_button)

    async def _on_pick_type(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 0)
        value = select.values[0]
        self.slot_type_filter = None if value == "all" else value
        self.selected_instance_id = None
        self.page = 0
        self.last_result = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_item(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 1)
        value = select.values[0]
        self.selected_instance_id = int(value) if value != "none" else None
        self.last_result = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_prev_page(self, interaction: discord.Interaction):
        self.page -= 1
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_next_page(self, interaction: discord.Interaction):
        self.page += 1
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_attune(self, interaction: discord.Interaction):
        ok, message = await asyncio.to_thread(self.game.attune_accessory_artifact, self.user_id, self.display_name, self.selected_instance_id)
        self.last_result = message
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_unattune(self, interaction: discord.Interaction):
        ok, message = await asyncio.to_thread(self.game.unattune_accessory_artifact, self.user_id, self.display_name, self.selected_instance_id)
        self.last_result = message
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_salvage(self, interaction: discord.Interaction):
        ok, message = await asyncio.to_thread(self.game.salvage_accessory_artifact, self.user_id, self.display_name, self.selected_instance_id)
        self.last_result = message
        if ok:
            self.selected_instance_id = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_salvage_all(self, interaction: discord.Interaction):
        entry = self._selected_entry()
        item_id = entry["affix"].item_id if entry else None
        result = await asyncio.to_thread(self.game.salvage_all_accessory_artifact_duplicates, self.user_id, self.display_name, item_id)
        if result["ok"]:
            note = f" ({result['skipped_equipped']} equipped copy skipped)" if result["skipped_equipped"] else ""
            self.last_result = f"Salvaged {result['count']}x **{result['name']}** for {format_number(result['stones'])} 🪙 spirit stones total.{note}"
            self.selected_instance_id = None
        else:
            self.last_result = result["reason"]
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_activate(self, interaction: discord.Interaction):
        ok, message = await asyncio.to_thread(self.game.activate_accessory_artifact, self.user_id, self.display_name, self.selected_instance_id)
        self.last_result = message
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def build_embed(self) -> discord.Embed:
        total_owned = self._filtered_owned()
        paged = self._paged_owned()  # clamps self.page as a side effect
        equipped_ids = self._equipped_ids()
        player = self.game.get_player_stats(self.user_id, self.display_name)

        title_suffix = f" — {self.slot_type_filter}" if self.slot_type_filter else ""
        embed = discord.Embed(title=f"💍 {self.display_name}'s Accessories & Artifacts{title_suffix}", color=discord.Color.dark_teal())
        embed.add_field(
            name="Attunement",
            value=f"{player['attunement_points_used']}/{self.game.max_attunement_points(player)} points used "
                  "(Legendary/Mythic cost 1, Rank 6-7 Unique-tier cost 2)",
            inline=False,
        )

        if not total_owned:
            embed.description = (
                f"You don't own any {self.slot_type_filter} accessories/artifacts yet."
                if self.slot_type_filter else
                "You don't own any accessories or artifacts yet — try `/hunt`, `/raid`, or `/search`!"
            )
        else:
            slot_types_shown = [self.slot_type_filter] if self.slot_type_filter else SLOT_TYPE_ORDER
            by_slot = {slot_type: [] for slot_type in slot_types_shown}
            for entry in paged:
                by_slot.setdefault(entry["affix"].slot_type, []).append(entry)

            sections = []
            for slot_type in slot_types_shown:
                entries = by_slot.get(slot_type, [])
                if not entries:
                    continue
                emoji = SLOT_TYPE_EMOJI.get(slot_type, "•")
                lines = [f"{emoji} **{slot_type}**"]
                lines.extend(_item_line(e, equipped_ids) for e in entries)
                sections.append("\n".join(lines))
            embed.description = "\n\n".join(sections)[:4000]

            start = self.page * PAGE_SIZE
            embed.add_field(
                name="Showing",
                value=f"{start + 1}–{start + len(paged)} of {len(total_owned)}",
                inline=False,
            )

        if self.last_result:
            embed.add_field(name="Result", value=self.last_result, inline=False)
        embed.set_footer(text="✅ = equipped (via /equipment). Legendary+ items need Attune before they can be equipped. Salvage returns spirit stones for ones you don't want.")
        return embed
