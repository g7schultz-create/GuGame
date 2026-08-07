import discord

from . import accessories_data
from .base_view import GameView
from .equipment import SLOT_TYPE_EMOJI, describe_stat_bonuses

SLOT_TYPE_ORDER = ["Ring", "Earring", "Necklace", "Bracelet", "Artifact"]


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

        owned = self._filtered_owned()
        options = [
            discord.SelectOption(
                label=f"{e['affix'].name} #{e['instance_id']}"[:100],
                value=str(e["instance_id"]),
                description=f"Rank {e['affix'].rank} {e['affix'].rarity} • {e['affix'].effect_key.replace('_', ' ')}"[:100],
                default=(e["instance_id"] == self.selected_instance_id),
            )
            for e in owned[:25]
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

        entry = self._selected_entry()
        equipped_ids = self._equipped_ids()
        can_attune = bool(entry) and entry["affix"].rarity in accessories_data.ATTUNEMENT_REQUIRED_RARITIES and not entry["attuned"]
        can_unattune = bool(entry) and entry["attuned"] and entry["instance_id"] not in equipped_ids
        can_salvage = bool(entry) and entry["instance_id"] not in equipped_ids and entry["affix"].rarity != "Unique"
        can_activate = bool(entry) and entry["instance_id"] in equipped_ids and entry["affix"].effect_key not in (
            "stat", "encounter_shield", "post_action_buff", "extra_loot_roll_daily", "loot_duplicate_daily", "defeat_ward_daily",
        )

        attune_button = discord.ui.Button(label="Attune", emoji="🔓", style=discord.ButtonStyle.primary, row=2, disabled=not can_attune)
        attune_button.callback = self._on_attune
        self.add_item(attune_button)

        unattune_button = discord.ui.Button(label="Unattune", emoji="🔒", style=discord.ButtonStyle.secondary, row=2, disabled=not can_unattune)
        unattune_button.callback = self._on_unattune
        self.add_item(unattune_button)

        activate_button = discord.ui.Button(label="Activate", emoji="✨", style=discord.ButtonStyle.success, row=2, disabled=not can_activate)
        activate_button.callback = self._on_activate
        self.add_item(activate_button)

        salvage_button = discord.ui.Button(label="Salvage", emoji="🔨", style=discord.ButtonStyle.danger, row=2, disabled=not can_salvage)
        salvage_button.callback = self._on_salvage
        self.add_item(salvage_button)

    async def _on_pick_type(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 0)
        value = select.values[0]
        self.slot_type_filter = None if value == "all" else value
        self.selected_instance_id = None
        self.last_result = None
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_pick_item(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 1)
        value = select.values[0]
        self.selected_instance_id = int(value) if value != "none" else None
        self.last_result = None
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_attune(self, interaction: discord.Interaction):
        ok, message = self.game.attune_accessory_artifact(self.user_id, self.display_name, self.selected_instance_id)
        self.last_result = message
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_unattune(self, interaction: discord.Interaction):
        ok, message = self.game.unattune_accessory_artifact(self.user_id, self.display_name, self.selected_instance_id)
        self.last_result = message
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_salvage(self, interaction: discord.Interaction):
        ok, message = self.game.salvage_accessory_artifact(self.user_id, self.display_name, self.selected_instance_id)
        self.last_result = message
        if ok:
            self.selected_instance_id = None
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_activate(self, interaction: discord.Interaction):
        ok, message = self.game.activate_accessory_artifact(self.user_id, self.display_name, self.selected_instance_id)
        self.last_result = message
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    def build_embed(self) -> discord.Embed:
        owned = self._filtered_owned()
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

        if not owned:
            embed.description = (
                f"You don't own any {self.slot_type_filter} accessories/artifacts yet."
                if self.slot_type_filter else
                "You don't own any accessories or artifacts yet — try `/hunt`, `/raid`, or `/search`!"
            )
        else:
            slot_types_shown = [self.slot_type_filter] if self.slot_type_filter else SLOT_TYPE_ORDER
            by_slot = {slot_type: [] for slot_type in slot_types_shown}
            for entry in owned:
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

        if self.last_result:
            embed.add_field(name="Result", value=self.last_result, inline=False)
        embed.set_footer(text="✅ = equipped (via /equipment). Legendary+ items need Attune before they can be equipped. Salvage returns spirit stones for ones you don't want.")
        return embed
