import discord

from . import chargen, manual_data, manual_gen
from .base_view import GameView
from .ui_utils import NAV_PREV_VALUE as _NAV_PREV, NAV_NEXT_VALUE as _NAV_NEXT, paginate_select_options as _paginate_options

EFFECT_LABELS = {
    "cultivation_gain_pct": "Cultivation Gain", "cultivation_speed_pct": "Cultivation Speed",
    "essence_recovery_pct": "Essence Recovery", "essence_purity_pct": "Essence Purity",
    "breakthrough_success_pct": "Breakthrough Success", "hp_pct": "Max HP",
    "dodge_chance_pct": "Dodge Chance", "technique_damage_pct": "Technique Damage",
    "physical_damage_pct": "Physical Damage", "insight_gain_pct": "Insight Gain",
    "cooldown_reduction_pct": "Cooldown Reduction", "deviation_resistance_pct": "Deviation Resistance",
}


def _format_effects(effects: dict) -> str:
    if not effects:
        return "No effects."
    lines = []
    for key, value in effects.items():
        label = EFFECT_LABELS.get(key, key.replace("_", " ").title())
        lines.append(f"+{value:.2f}% {label}" if "pct" in key else f"+{value:.2f} {label}")
    return "\n".join(lines)


def _format_flaws(flaw_ids: list) -> str:
    if not flaw_ids:
        return "None."
    return "\n".join(f"⚠️ **{manual_data.FLAWS[fid].severity}**: {manual_data.FLAWS[fid].text}" for fid in flaw_ids if fid in manual_data.FLAWS)


class ManualView(GameView):
    TABS = [("pages", "Pages", "📜"), ("assemble", "Assemble", "🧬"), ("manuals", "My Manuals", "📖")]
    ASSEMBLE_MAX_PAGES = 10

    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.active_tab = "pages"
        self.selected_page_id: str = None
        self.selected_manual_id: int = None
        self.assemble_selection: list = []
        self.last_result: str = None
        self.page_studied_filter = "all"  # "all" | "studied" | "unstudied"
        self.page_type_filter: tuple = None  # None (all types), or (rank, category)
        self.page_type_filter_page = 0
        self.page_list_page = 0
        self.assemble_studied_filter = "all"  # "all" | "studied" | "unstudied"
        self.assemble_type_filter: tuple = None  # None (all types), or (rank, category)
        self.assemble_type_filter_page = 0
        self.assemble_list_page = 0
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Run `/manual` yourself to manage your own collection.", ephemeral=True)
            return False
        return True

    # -- shared helpers -----------------------------------------------------------------

    def _owned_pages(self) -> dict:
        return self.game.get_player_pages(self.user_id)

    def _passes_studied_filter(self, info: dict, studied_filter: str) -> bool:
        if studied_filter == "studied":
            return bool(info["studied"])
        if studied_filter == "unstudied":
            return not info["studied"]
        return True

    def _type_filter_combos(self, studied_filter: str) -> list:
        """(rank, category) pairs present among owned pages that pass the given studied
        filter — options for a type-filter dropdown, independent of any type already picked.
        Shared by the Pages and Assemble tabs, each with their own independent filter state."""
        combos = set()
        for page_id, info in self._owned_pages().items():
            page = manual_data.PAGES.get(page_id)
            if page is None or not self._passes_studied_filter(info, studied_filter):
                continue
            combos.add((page.rank, page.category))
        return sorted(combos)

    def _filtered_pages(self, studied_filter: str, type_filter: tuple) -> dict:
        filtered = {}
        for page_id, info in self._owned_pages().items():
            page = manual_data.PAGES.get(page_id)
            if page is None or not self._passes_studied_filter(info, studied_filter):
                continue
            if type_filter is not None and (page.rank, page.category) != type_filter:
                continue
            filtered[page_id] = info
        return filtered

    def _sorted_filtered_pages(self, studied_filter: str, type_filter: tuple) -> list:
        return sorted(
            self._filtered_pages(studied_filter, type_filter).items(),
            key=lambda kv: (manual_data.PAGES[kv[0]].rank, manual_data.PAGES[kv[0]].category, manual_data.PAGES[kv[0]].name),
        )

    def _owned_manuals(self) -> list:
        return self.game.get_player_manuals(self.user_id)

    def _player(self) -> dict:
        return self.game.get_player_stats(self.user_id, self.display_name)

    # -- component building ---------------------------------------------------------------

    def _build_components(self):
        self.clear_items()
        for key, label, emoji in self.TABS:
            button = discord.ui.Button(label=label, emoji=emoji, row=0)
            is_active = key == self.active_tab
            button.style = discord.ButtonStyle.primary if is_active else discord.ButtonStyle.secondary
            button.disabled = is_active
            button.callback = self._make_tab_callback(key)
            self.add_item(button)

        if self.active_tab == "pages":
            self._build_pages_tab()
        elif self.active_tab == "assemble":
            self._build_assemble_tab()
        else:
            self._build_manuals_tab()

    def _make_tab_callback(self, key: str):
        async def callback(interaction: discord.Interaction):
            self.active_tab = key
            self.last_result = None
            self._build_components()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

        return callback

    def _build_pages_tab(self):
        # Row 1: studied/unstudied filter
        for key, label in (("all", "All"), ("studied", "📖 Studied"), ("unstudied", "❓ Unstudied")):
            button = discord.ui.Button(label=label, row=1)
            is_active = key == self.page_studied_filter
            button.style = discord.ButtonStyle.primary if is_active else discord.ButtonStyle.secondary
            button.disabled = is_active
            button.callback = self._make_studied_filter_callback(key)
            self.add_item(button)

        # Row 2: page-type filter (rank + category), nested under whichever studied filter is active
        type_options = [discord.SelectOption(label="All Types", value="all", default=self.page_type_filter is None)]
        for rank, category in self._type_filter_combos(self.page_studied_filter):
            type_options.append(discord.SelectOption(
                label=f"R{rank} - {category}", value=f"{rank}:{category}",
                default=(self.page_type_filter == (rank, category)),
            ))
        type_page_options, type_total_pages, self.page_type_filter_page = _paginate_options(type_options, self.page_type_filter_page)
        type_placeholder = "Filter by page type..."
        if type_total_pages > 1:
            type_placeholder += f" (page {self.page_type_filter_page + 1}/{type_total_pages})"
        type_select = discord.ui.Select(
            placeholder=type_placeholder, options=type_page_options, row=2, disabled=len(type_options) <= 1,
        )
        type_select.callback = self._on_pick_type_filter
        self.add_item(type_select)

        # Row 3: the actual page picker, filtered + paginated
        page_options = []
        for page_id, info in self._sorted_filtered_pages(self.page_studied_filter, self.page_type_filter):
            page = manual_data.PAGES[page_id]
            label = f"{page.name} x{info['quantity']} ({info['refinement_level']})"
            page_options.append(discord.SelectOption(label=label[:100], value=page_id, default=(page_id == self.selected_page_id)))

        if page_options:
            page_page_options, page_total_pages, self.page_list_page = _paginate_options(page_options, self.page_list_page)
            placeholder = "Choose a page..."
            if page_total_pages > 1:
                placeholder += f" (page {self.page_list_page + 1}/{page_total_pages})"
            select = discord.ui.Select(placeholder=placeholder, options=page_page_options, row=3)
        else:
            no_pages_reason = "No pages match this filter" if self._owned_pages() else "You don't own any pages yet"
            select = discord.ui.Select(
                placeholder=no_pages_reason, options=[discord.SelectOption(label="None", value="none")],
                disabled=True, row=3,
            )
        select.callback = self._on_pick_page
        self.add_item(select)

        has_selection = self.selected_page_id is not None
        study_btn = discord.ui.Button(label="Study", emoji="🔎", style=discord.ButtonStyle.primary, row=4, disabled=not has_selection)
        study_btn.callback = self._on_study
        self.add_item(study_btn)

        refine_btn = discord.ui.Button(label="Refine", emoji="✨", style=discord.ButtonStyle.success, row=4, disabled=not has_selection)
        refine_btn.callback = self._on_refine
        self.add_item(refine_btn)

        dismantle_btn = discord.ui.Button(label="Dismantle 1", emoji="🔨", style=discord.ButtonStyle.danger, row=4, disabled=not has_selection)
        dismantle_btn.callback = self._on_dismantle_page
        self.add_item(dismantle_btn)

    def _build_assemble_tab(self):
        # Row 1: studied/unstudied filter
        for key, label in (("all", "All"), ("studied", "📖 Studied"), ("unstudied", "❓ Unstudied")):
            button = discord.ui.Button(label=label, row=1)
            is_active = key == self.assemble_studied_filter
            button.style = discord.ButtonStyle.primary if is_active else discord.ButtonStyle.secondary
            button.disabled = is_active
            button.callback = self._make_assemble_studied_filter_callback(key)
            self.add_item(button)

        # Row 2: page-type filter (rank + category), nested under whichever studied filter is active
        type_options = [discord.SelectOption(label="All Types", value="all", default=self.assemble_type_filter is None)]
        for rank, category in self._type_filter_combos(self.assemble_studied_filter):
            type_options.append(discord.SelectOption(
                label=f"R{rank} - {category}", value=f"{rank}:{category}",
                default=(self.assemble_type_filter == (rank, category)),
            ))
        type_page_options, type_total_pages, self.assemble_type_filter_page = _paginate_options(type_options, self.assemble_type_filter_page)
        type_placeholder = "Filter by page type..."
        if type_total_pages > 1:
            type_placeholder += f" (page {self.assemble_type_filter_page + 1}/{type_total_pages})"
        type_select = discord.ui.Select(
            placeholder=type_placeholder, options=type_page_options, row=2, disabled=len(type_options) <= 1,
        )
        type_select.callback = self._on_pick_assemble_type_filter
        self.add_item(type_select)

        # Row 3: the page multi-select, filtered + paginated. assemble_selection can span
        # pages from OUTSIDE whatever's currently visible here (e.g. a Foundation page picked
        # before switching the type filter to Circulation) — see _on_pick_assemble_pages for
        # how those out-of-view picks get preserved instead of wiped by this select's own submit.
        owned = self._owned_pages()
        page_options = []
        for page_id, info in self._sorted_filtered_pages(self.assemble_studied_filter, self.assemble_type_filter):
            page = manual_data.PAGES[page_id]
            page_options.append(discord.SelectOption(
                label=f"{page.name} ({page.category})"[:100], value=page_id,
                description=f"Rank {page.rank} — {', '.join(page.tags[:3])}"[:100],
                default=(page_id in self.assemble_selection),
            ))

        if page_options:
            page_page_options, page_total_pages, self.assemble_list_page = _paginate_options(page_options, self.assemble_list_page)
            placeholder = "Choose 2+ pages (needs a Foundation + a Circulation)..."
            if page_total_pages > 1:
                placeholder += f" (page {self.assemble_list_page + 1}/{page_total_pages})"
            select = discord.ui.Select(
                placeholder=placeholder, options=page_page_options, row=3, min_values=0,
                max_values=min(self.ASSEMBLE_MAX_PAGES, len(page_page_options)),
            )
        else:
            no_pages_reason = "No pages match this filter" if owned else "You don't own any pages yet"
            select = discord.ui.Select(
                placeholder=no_pages_reason, options=[discord.SelectOption(label="None", value="none")],
                disabled=True, row=3,
            )
        select.callback = self._on_pick_assemble_pages
        self.add_item(select)

        assemble_btn = discord.ui.Button(
            label=f"Assemble ({len(self.assemble_selection)} pages)", emoji="🧬", style=discord.ButtonStyle.success,
            row=4, disabled=len(self.assemble_selection) < 2,
        )
        assemble_btn.callback = self._on_assemble
        self.add_item(assemble_btn)

    def _build_manuals_tab(self):
        manuals = self._owned_manuals()
        player = self._player()
        options = []
        for manual in manuals:
            equipped_note = ""
            if manual["manual_id"] == player["equipped_primary_manual_id"]:
                equipped_note = " [Primary]"
            elif manual["manual_id"] == player["equipped_auxiliary_manual_id"]:
                equipped_note = " [Auxiliary]"
            label = f"{manual['name']} R{manual['rank']} {manual['rarity']}{equipped_note}"
            options.append(discord.SelectOption(label=label[:100], value=str(manual["manual_id"]), default=(manual["manual_id"] == self.selected_manual_id)))
        select = discord.ui.Select(
            placeholder="Choose a manual..." if options else "You haven't assembled or found any manuals yet",
            options=options[:25] or [discord.SelectOption(label="None", value="none")],
            disabled=not options, row=1,
        )
        select.callback = self._on_pick_manual
        self.add_item(select)

        has_selection = self.selected_manual_id is not None
        primary_btn = discord.ui.Button(label="Equip Primary", emoji="📖", style=discord.ButtonStyle.primary, row=2, disabled=not has_selection)
        primary_btn.callback = self._make_equip_callback("primary")
        self.add_item(primary_btn)

        aux_btn = discord.ui.Button(label="Equip Auxiliary", emoji="📗", style=discord.ButtonStyle.primary, row=2, disabled=not has_selection)
        aux_btn.callback = self._make_equip_callback("auxiliary")
        self.add_item(aux_btn)

        unequip_primary_btn = discord.ui.Button(label="Unequip Primary", emoji="🗑️", style=discord.ButtonStyle.secondary, row=3, disabled=not player["equipped_primary_manual_id"])
        unequip_primary_btn.callback = self._make_unequip_callback("primary")
        self.add_item(unequip_primary_btn)

        unequip_aux_btn = discord.ui.Button(label="Unequip Auxiliary", emoji="🗑️", style=discord.ButtonStyle.secondary, row=3, disabled=not player["equipped_auxiliary_manual_id"])
        unequip_aux_btn.callback = self._make_unequip_callback("auxiliary")
        self.add_item(unequip_aux_btn)

        dismantle_btn = discord.ui.Button(label="Dismantle", emoji="🔨", style=discord.ButtonStyle.danger, row=3, disabled=not has_selection)
        dismantle_btn.callback = self._on_dismantle_manual
        self.add_item(dismantle_btn)

    # -- callbacks ------------------------------------------------------------------------

    def _make_studied_filter_callback(self, key: str):
        async def callback(interaction: discord.Interaction):
            self.page_studied_filter = key
            self.page_type_filter = None
            self.page_type_filter_page = 0
            self.page_list_page = 0
            self._build_components()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

        return callback

    async def _on_pick_type_filter(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 2)
        choice = select.values[0]
        if choice == _NAV_PREV:
            self.page_type_filter_page = max(0, self.page_type_filter_page - 1)
        elif choice == _NAV_NEXT:
            self.page_type_filter_page += 1
        elif choice == "all":
            self.page_type_filter = None
            self.page_list_page = 0
        else:
            rank_str, category = choice.split(":", 1)
            self.page_type_filter = (int(rank_str), category)
            self.page_list_page = 0
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_pick_page(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 3)
        choice = select.values[0]
        if choice == _NAV_PREV:
            self.page_list_page = max(0, self.page_list_page - 1)
        elif choice == _NAV_NEXT:
            self.page_list_page += 1
        elif choice == "none":
            await interaction.response.defer()
            return
        else:
            self.selected_page_id = choice
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_study(self, interaction: discord.Interaction):
        ok, message = self.game.study_page(self.user_id, self.display_name, self.selected_page_id)
        self.last_result = message
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_refine(self, interaction: discord.Interaction):
        ok, message = self.game.refine_page(self.user_id, self.display_name, self.selected_page_id)
        self.last_result = message
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_dismantle_page(self, interaction: discord.Interaction):
        ok, message = self.game.dismantle_page(self.user_id, self.display_name, self.selected_page_id, 1)
        self.last_result = message
        if ok and self._owned_pages().get(self.selected_page_id) is None:
            self.selected_page_id = None
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    def _make_assemble_studied_filter_callback(self, key: str):
        async def callback(interaction: discord.Interaction):
            self.assemble_studied_filter = key
            self.assemble_type_filter = None
            self.assemble_type_filter_page = 0
            self.assemble_list_page = 0
            self._build_components()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

        return callback

    async def _on_pick_assemble_type_filter(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 2)
        choice = select.values[0]
        if choice == _NAV_PREV:
            self.assemble_type_filter_page = max(0, self.assemble_type_filter_page - 1)
        elif choice == _NAV_NEXT:
            self.assemble_type_filter_page += 1
        elif choice == "all":
            self.assemble_type_filter = None
            self.assemble_list_page = 0
        else:
            rank_str, category = choice.split(":", 1)
            self.assemble_type_filter = (int(rank_str), category)
            self.assemble_list_page = 0
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_pick_assemble_pages(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 3)
        raw_values = select.values
        if _NAV_PREV in raw_values:
            self.assemble_list_page = max(0, self.assemble_list_page - 1)
        elif _NAV_NEXT in raw_values:
            self.assemble_list_page += 1
        else:
            # The select only shows (and can only report back) pages matching the current
            # filter, so a page picked earlier under a DIFFERENT filter (e.g. a Foundation
            # page, before switching to browse Circulation pages) wouldn't be in this
            # submission's values at all -- preserve anything outside what's visible here,
            # and take this submission as the full truth only for what IS visible.
            visible_ids = {opt.value for opt in select.options if opt.value not in (_NAV_PREV, _NAV_NEXT, "none")}
            checked = [v for v in raw_values if v != "none"]
            preserved = [pid for pid in self.assemble_selection if pid not in visible_ids]
            self.assemble_selection = (preserved + checked)[:self.ASSEMBLE_MAX_PAGES]
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_assemble(self, interaction: discord.Interaction):
        ok, message, manual = self.game.assemble_manual(self.user_id, self.display_name, self.assemble_selection)
        self.last_result = message
        if ok:
            self.assemble_selection = []
            self.selected_manual_id = manual["manual_id"]
            self.active_tab = "manuals"
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_pick_manual(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 1)
        choice = select.values[0]
        if choice == "none":
            await interaction.response.defer()
            return
        self.selected_manual_id = int(choice)
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    def _make_equip_callback(self, slot: str):
        async def callback(interaction: discord.Interaction):
            ok, message = self.game.equip_manual(self.user_id, self.display_name, self.selected_manual_id, slot)
            self.last_result = message
            self._build_components()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

        return callback

    def _make_unequip_callback(self, slot: str):
        async def callback(interaction: discord.Interaction):
            ok, message = self.game.unequip_manual(self.user_id, self.display_name, slot)
            self.last_result = message
            self._build_components()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

        return callback

    async def _on_dismantle_manual(self, interaction: discord.Interaction):
        ok, message = self.game.dismantle_manual(self.user_id, self.display_name, self.selected_manual_id)
        self.last_result = message
        if ok:
            self.selected_manual_id = None
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    # -- embed ------------------------------------------------------------------------------

    def _pages_embed(self, embed: discord.Embed):
        owned = self._owned_pages()
        if not owned:
            embed.description = "You don't own any manual pages yet — /search for inheritances, secret realms, and dream realms to find some."
            return

        filtered = self._sorted_filtered_pages(self.page_studied_filter, self.page_type_filter)
        if not filtered:
            embed.description = "No pages match the current filter."
        else:
            lines = []
            for page_id, info in filtered:
                page = manual_data.PAGES.get(page_id)
                if page is None:
                    continue
                studied_note = "📖" if info["studied"] else "❓"
                lines.append(f"{studied_note} **{page.name}** x{info['quantity']} — R{page.rank} {page.category} ({info['refinement_level']})")
            embed.description = "\n".join(lines)[:4000]

        filter_bits = []
        if self.page_studied_filter != "all":
            filter_bits.append("📖 Studied" if self.page_studied_filter == "studied" else "❓ Unstudied")
        if self.page_type_filter:
            rank, category = self.page_type_filter
            filter_bits.append(f"R{rank} - {category}")
        if filter_bits:
            embed.add_field(name="Active Filter", value=" • ".join(filter_bits), inline=False)

        if self.selected_page_id and self.selected_page_id in manual_data.PAGES:
            page = manual_data.PAGES[self.selected_page_id]
            info = owned.get(self.selected_page_id, {})
            flaw_text = ", ".join(manual_data.FLAWS[f].text for f in page.flaw_pool if f in manual_data.FLAWS) or "None known"
            embed.add_field(
                name=f"🔎 {page.name}",
                value=(
                    f"Category: **{page.category}** • Rank {page.rank} • Tags: {', '.join(page.tags)}\n"
                    f"{page.description or 'No description.'}\n"
                    f"Refinement: **{info.get('refinement_level', 'Unstudied')}** • Owned: {info.get('quantity', 0)}\n"
                    f"Possible flaw: {flaw_text}"
                ),
                inline=False,
            )

    def _assemble_embed(self, embed: discord.Embed):
        embed.description = (
            "Pick 2 or more pages from the dropdown (needs exactly one Foundation and one Circulation page) "
            "and click Assemble. Costs Manual Ink and consumes the pages used.\n"
            "Use the filters below to find the pages you need — your picks are kept even "
            "when you switch filters to browse for more."
        )

        filter_bits = []
        if self.assemble_studied_filter != "all":
            filter_bits.append("📖 Studied" if self.assemble_studied_filter == "studied" else "❓ Unstudied")
        if self.assemble_type_filter:
            rank, category = self.assemble_type_filter
            filter_bits.append(f"R{rank} - {category}")
        if filter_bits:
            embed.add_field(name="Active Filter", value=" • ".join(filter_bits), inline=False)

        if self.assemble_selection:
            pages = [manual_data.PAGES[pid] for pid in self.assemble_selection if pid in manual_data.PAGES]
            embed.add_field(name="Selected Pages", value="\n".join(p.name for p in pages) or "None", inline=False)
            player = self._player()
            embed.add_field(name="🪙 Manual Ink", value=str(player["manual_ink"]), inline=True)

            categories = {p.category for p in pages}
            if len(pages) >= 2 and "Foundation" in categories and "Circulation" in categories:
                # Mirrors GameManager.assemble_manual exactly (same primary_path pick, same
                # Common-rarity assumption) so the preview matches what you'd actually get.
                primary_path = pages[0].tags[0] if pages[0].tags else "qi"
                rank = max(p.rank for p in pages)
                root_spec = chargen.get_root_spec(player["root_name"])
                coherence = manual_gen.calculate_coherence(
                    pages, primary_path,
                    bonus_tags=root_spec.manual_coherence_tags if root_spec else None,
                    bonus_categories=root_spec.manual_coherence_categories if root_spec else None,
                    flat_bonus=root_spec.manual_coherence_flat if root_spec else 0,
                )
                band = manual_data._coherence_band(coherence)
                bonus = manual_gen.refinement_bonus_totals(pages, self._owned_pages())
                effects = manual_gen.resolve_manual_effects(pages, rank, "Common", coherence, effectiveness_mult=bonus["effectiveness_mult"])
                refinement_note = (
                    f"\n🔧 Refinement bonus: +{(bonus['effectiveness_mult'] - 1) * 100:.0f}% effect strength, "
                    f"+{bonus['stability_bonus']} stability, {bonus['flaw_repair_chance'] * 100:.0f}% flaw-repair chance"
                    if bonus["effectiveness_mult"] > 1.0 or bonus["stability_bonus"] or bonus["flaw_repair_chance"]
                    else ""
                )
                embed.add_field(
                    name="🔮 Coherence Preview",
                    value=(
                        f"**{coherence}/100** — {band.label} (x{band.power_multiplier:.2f} power)\n"
                        f"Rank {rank} • Primary path: {primary_path}\n"
                        f"{_format_effects(effects)}"
                        f"{refinement_note}"
                    ),
                    inline=False,
                )
            else:
                embed.add_field(name="🔮 Coherence Preview", value="Needs a Foundation page and a Circulation page to preview.", inline=False)

    def _manuals_embed(self, embed: discord.Embed):
        manuals = self._owned_manuals()
        player = self._player()
        if not manuals:
            embed.description = "You haven't assembled or found any complete manuals yet."
        else:
            lines = []
            for manual in manuals:
                note = ""
                if manual["manual_id"] == player["equipped_primary_manual_id"]:
                    note = " ✅ Primary"
                elif manual["manual_id"] == player["equipped_auxiliary_manual_id"]:
                    note = " ✅ Auxiliary"
                lines.append(f"**{manual['name']}** — Rank {manual['rank']} {manual['rarity']} • {manual['coherence_band']} ({manual['coherence']}/100){note}")
            embed.description = "\n".join(lines)[:4000]

        selected = next((m for m in manuals if m["manual_id"] == self.selected_manual_id), None)
        if selected:
            page_names = ", ".join(manual_data.PAGES[pid].name for pid in selected["page_ids"] if pid in manual_data.PAGES)
            embed.add_field(
                name=f"📖 {selected['name']}",
                value=(
                    f"Rank {selected['rank']} • {selected['rarity']} • Primary path: **{selected['primary_path']}**\n"
                    f"Secondary: {', '.join(selected['secondary_paths']) or 'none'}\n"
                    f"Coherence: **{selected['coherence']}/100** ({selected['coherence_band']}) • Stability: {selected['stability']}/100\n"
                    f"Pages: {page_names}"
                ),
                inline=False,
            )
            embed.add_field(name="Effects", value=_format_effects(selected["effects"])[:1024], inline=False)
            embed.add_field(name="Flaws", value=_format_flaws(selected["flaws"])[:1024], inline=False)

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(title=f"📚 {self.display_name}'s Manuals", color=discord.Color.dark_purple())
        if self.active_tab == "pages":
            self._pages_embed(embed)
        elif self.active_tab == "assemble":
            self._assemble_embed(embed)
        else:
            self._manuals_embed(embed)
        if self.last_result:
            embed.add_field(name="Result", value=self.last_result[:1024], inline=False)
        player = self._player()
        embed.set_footer(text=f"🪙 Manual Ink: {player['manual_ink']} • ✨ Insight Dust: {player['insight_dust']}")
        return embed
