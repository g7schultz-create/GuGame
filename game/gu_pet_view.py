"""
GuPetView -- the /gu_pet menu. Refine tab (Phase 2): sacrifice 1-3 Immortal-quality Gu plus
Soul Nourishing Pill/Soul Crystal catalysts into a blank Gu Pet. Feed tab
(Phase 3): daily feeding during growth. Status tab (Phase 5): browse every owned pet's
species/satiety/stat_bonuses and pick which one is active (players.active_gu_pet_id -- only
the active pet's bonuses actually apply, see GameManager.compute_equipment_bonuses, a later
phase). Mode tab (Phase 5): flips the ACTIVE pet between Combat/Cultivation Mode (see
GameManager.toggle_gu_pet_mode) -- see game/gu_pet.py's own module docstring for the full
lifecycle.

AI portrait reveal (Phase 8, see game/gu_pet_images.py): a successful Crystallize fires a
fire-and-forget asyncio.create_task that generates (or reuses a cached) portrait a few
seconds later and edits the already-sent message in place -- see _resolve_gu_pet_portrait.
Persistent portrait display on the Status tab (a full gallery/codex browser) is a deliberate
scope cut, same as the source spec's own "lower priority" framing.
"""

import asyncio
import time
import discord

from . import equipment, gu_pet, professions
from .base_view import GameView


class GuPetView(GameView):
    TABS = [("refine", "Refine", "🧪"), ("feed", "Feed", "🍖"), ("status", "Status", "📊"), ("mode", "Mode", "⚔️")]

    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.active_tab = "refine"
        self.selected_sacrifice_item: str = None
        self.selected_target_rank: int = None
        self.selected_feed_pet_id: int = None
        self.selected_feed_item: str = None
        self.selected_feed_quantity: int = 1
        self.selected_status_pet_id: int = None
        self.selected_status_feed_item: str = None
        self.last_result: str = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Run `/gu_pet` yourself to manage your own Gu Pets.", ephemeral=True)
            return False
        return True

    # -- component building -------------------------------------------------------------

    def _build_components(self):
        self.clear_items()
        for key, label, emoji in self.TABS:
            button = discord.ui.Button(label=label, emoji=emoji, row=0)
            is_active = key == self.active_tab
            button.style = discord.ButtonStyle.primary if is_active else discord.ButtonStyle.secondary
            button.disabled = is_active
            button.callback = self._make_tab_callback(key)
            self.add_item(button)

        if self.active_tab == "refine":
            self._build_refine_components()
        elif self.active_tab == "feed":
            self._build_feed_components()
        elif self.active_tab == "status":
            self._build_status_components()
        elif self.active_tab == "mode":
            self._build_mode_components()

    def _make_tab_callback(self, key: str):
        async def callback(interaction: discord.Interaction):
            self.active_tab = key
            self.last_result = None
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    def _build_refine_components(self):
        player = self.game.get_player_stats(self.user_id, self.display_name)
        candidates = self.game.gu_pet_refine_candidates(self.user_id)
        if self.selected_sacrifice_item is None and candidates:
            self.selected_sacrifice_item = candidates[0][0]

        item_options = [
            discord.SelectOption(
                label=item_name[:100], value=item_name,
                description=f"Own {qty} — sacrifices {min(gu_pet.REFINE_MAX_SACRIFICE, qty)}"[:100],
                default=(item_name == self.selected_sacrifice_item),
            )
            for item_name, qty in candidates
        ]
        item_select = discord.ui.Select(
            placeholder=f"Choose a Gu to sacrifice ({gu_pet.REFINE_REQUIRED_GU_QUALITY} quality)",
            options=item_options[:25] or [discord.SelectOption(label="No eligible Gu owned", value="none")],
            disabled=not item_options, row=1,
        )
        item_select.callback = self._on_pick_sacrifice_item
        self.add_item(item_select)

        # No hard Gu Refiner rank gate anymore -- every rank is always selectable, an
        # under-ranked attempt just carries worse (never zero) odds instead of being refused
        # outright (see gu_pet.refine_success_chance). Defaults to the highest rank the player
        # is natively qualified for (gap >= 0) purely as a safe starting suggestion, not a cap.
        owned_sacrifice = dict(candidates).get(self.selected_sacrifice_item, 0)
        preview_quantity = min(gu_pet.REFINE_MAX_SACRIFICE, max(gu_pet.REFINE_MIN_SACRIFICE, owned_sacrifice))
        default_rank = gu_pet.MIN_RANK
        for rank in range(gu_pet.MIN_RANK, gu_pet.MAX_RANK + 1):
            if player["gu_refiner_rank"] >= gu_pet.gu_refiner_rank_required(rank):
                default_rank = rank
        if self.selected_target_rank is None:
            self.selected_target_rank = default_rank

        rank_options = [
            discord.SelectOption(
                label=f"Rank {rank} ({gu_pet.rank_to_rarity(rank)})", value=str(rank),
                description=f"~{gu_pet.refine_success_chance(player['gu_refiner_rank'], rank, preview_quantity) * 100:.0f}% success chance"[:100],
                default=(rank == self.selected_target_rank),
            )
            for rank in range(gu_pet.MIN_RANK, gu_pet.MAX_RANK + 1)
        ]
        rank_select = discord.ui.Select(placeholder="Target Gu Pet rank (any rank -- odds scale with your Gu Refiner rank)", options=rank_options, row=2)
        rank_select.callback = self._on_pick_target_rank
        self.add_item(rank_select)

        catalysts = gu_pet.refine_catalyst_recipe(self.selected_target_rank)
        inventory = self.game.get_inventory(self.user_id)
        can_afford_catalysts = all(inventory.get(mat, 0) >= qty for mat, qty in catalysts.items())
        button = discord.ui.Button(
            label="Refine", emoji="🧪", style=discord.ButtonStyle.success, row=3,
            disabled=not (item_options and can_afford_catalysts and owned_sacrifice >= gu_pet.REFINE_MIN_SACRIFICE),
        )
        button.callback = self._on_refine
        self.add_item(button)

    def _build_feed_components(self):
        growing_pets = [p for p in self.game.get_player_gu_pets(self.user_id) if p["stage"] == gu_pet.STAGE_GROWTH]
        if self.selected_feed_pet_id is None and growing_pets:
            self.selected_feed_pet_id = growing_pets[0]["pet_id"]

        pet_options = [
            discord.SelectOption(
                label=f"Rank {p['rank']} Gu Pet #{p['pet_id']} — day {p['growth_days_fed']}/{p['growth_days_required']}"[:100],
                value=str(p["pet_id"]), default=(p["pet_id"] == self.selected_feed_pet_id),
            )
            for p in growing_pets
        ]
        pet_select = discord.ui.Select(
            placeholder="Choose a growing Gu Pet to feed",
            options=pet_options[:25] or [discord.SelectOption(label="No growing Gu Pets — refine one first", value="none")],
            disabled=not pet_options, row=1,
        )
        pet_select.callback = self._on_pick_feed_pet
        self.add_item(pet_select)

        feedable = self.game.gu_pet_feedable_inventory(self.user_id)
        if self.selected_feed_item is None and feedable:
            self.selected_feed_item = feedable[0][0]
        item_options = [
            discord.SelectOption(
                label=item_name[:100], value=item_name,
                description=f"Own {qty} — {category.replace('_', ' ').title()}, Tier {tier}"[:100],
                default=(item_name == self.selected_feed_item),
            )
            for item_name, qty, category, tier in feedable
        ]
        item_select = discord.ui.Select(
            placeholder="Choose a material to feed (Ore/Herb/Beast Material/Beast Core/Pill)",
            options=item_options[:25] or [discord.SelectOption(label="No feedable materials owned", value="none")],
            disabled=not item_options, row=2,
        )
        item_select.callback = self._on_pick_feed_item
        self.add_item(item_select)

        feedable_by_name = {c[0]: c[1] for c in feedable}
        selected_pet = next((p for p in growing_pets if p["pet_id"] == self.selected_feed_pet_id), None)
        remaining_days = (selected_pet["growth_days_required"] - selected_pet["growth_days_fed"]) if selected_pet else 1
        owned_qty = feedable_by_name.get(self.selected_feed_item, 0)
        # Feeding more in one visit covers more growth-days at once (see GameManager.
        # feed_gu_pet) -- capped at whatever's actually still useful so a big stockpile never
        # gets wasted past the finish line.
        max_useful = max(1, min(owned_qty, remaining_days)) if owned_qty > 0 else 1
        if self.selected_feed_quantity is None or self.selected_feed_quantity > max_useful:
            self.selected_feed_quantity = 1
        quantity_choices = sorted({q for q in (1, 5, 10, max_useful) if q <= max_useful})
        quantity_select = discord.ui.Select(
            placeholder="How much to feed this visit (more = faster growth)",
            options=[
                discord.SelectOption(
                    label=f"Feed {q}" + (" (finishes it!)" if q == max_useful and q >= remaining_days else ""),
                    value=str(q), default=(q == self.selected_feed_quantity),
                )
                for q in quantity_choices
            ] or [discord.SelectOption(label="Feed 1", value="1", default=True)],
            disabled=not item_options, row=4,
        )
        quantity_select.callback = self._on_pick_feed_quantity
        self.add_item(quantity_select)

        button = discord.ui.Button(
            label="Feed", emoji="🍖", style=discord.ButtonStyle.success, row=3,
            disabled=not (pet_options and item_options and owned_qty > 0),
        )
        button.callback = self._on_feed
        self.add_item(button)

        ready = selected_pet is not None and selected_pet["growth_days_fed"] >= selected_pet["growth_days_required"]
        crystallize_button = discord.ui.Button(
            label="Crystallize", emoji="💎", style=discord.ButtonStyle.primary, row=3, disabled=not ready,
        )
        crystallize_button.callback = self._on_crystallize
        self.add_item(crystallize_button)

    def _build_status_components(self):
        pets = self.game.get_player_gu_pets(self.user_id)
        player = self.game.get_player_stats(self.user_id, self.display_name)
        if self.selected_status_pet_id is None or not any(p["pet_id"] == self.selected_status_pet_id for p in pets):
            self.selected_status_pet_id = player["active_gu_pet_id"] if any(p["pet_id"] == player["active_gu_pet_id"] for p in pets) else (pets[0]["pet_id"] if pets else None)

        pet_options = [
            discord.SelectOption(label=self._pet_label(p)[:100], value=str(p["pet_id"]), default=(p["pet_id"] == self.selected_status_pet_id))
            for p in pets
        ]
        pet_select = discord.ui.Select(
            placeholder="Choose a Gu Pet to view",
            options=pet_options[:25] or [discord.SelectOption(label="No Gu Pets owned yet", value="none")],
            disabled=not pet_options, row=1,
        )
        pet_select.callback = self._on_pick_status_pet
        self.add_item(pet_select)

        is_active = self.selected_status_pet_id is not None and self.selected_status_pet_id == player["active_gu_pet_id"]
        button = discord.ui.Button(
            label="Currently Active" if is_active else "Set Active", emoji="⭐",
            style=discord.ButtonStyle.secondary if is_active else discord.ButtonStyle.success,
            row=3, disabled=is_active or self.selected_status_pet_id is None,
        )
        button.callback = self._on_set_active_pet
        self.add_item(button)

        selected_pet = next((p for p in pets if p["pet_id"] == self.selected_status_pet_id), None)
        if selected_pet is not None and selected_pet["stage"] == gu_pet.STAGE_MATURE and selected_pet["satiety"] < gu_pet.SATIETY_MAX:
            required_tier = gu_pet.rank_scaling(selected_pet["rank"])["satiety_material_tier"]
            feedable = [c for c in self.game.gu_pet_feedable_inventory(self.user_id) if c[3] == required_tier]
            if self.selected_status_feed_item is None or not any(c[0] == self.selected_status_feed_item for c in feedable):
                self.selected_status_feed_item = feedable[0][0] if feedable else None
            feed_options = [
                discord.SelectOption(
                    label=item_name[:100], value=item_name,
                    description=f"Own {qty} — {category.replace('_', ' ').title()}, Tier {tier}"[:100],
                    default=(item_name == self.selected_status_feed_item),
                )
                for item_name, qty, category, tier in feedable
            ]
            feed_select = discord.ui.Select(
                placeholder=f"Feed a Tier {required_tier} material to restore Satiety",
                options=feed_options[:25] or [discord.SelectOption(label=f"No Tier {required_tier} materials owned", value="none")],
                disabled=not feed_options, row=2,
            )
            feed_select.callback = self._on_pick_status_feed_item
            self.add_item(feed_select)

            feedable_by_name = {c[0]: c[1] for c in feedable}
            feed_button = discord.ui.Button(
                label="Feed for Satiety", emoji="🍖", style=discord.ButtonStyle.success, row=3,
                disabled=not (feed_options and feedable_by_name.get(self.selected_status_feed_item, 0) > 0),
            )
            feed_button.callback = self._on_feed_satiety
            self.add_item(feed_button)

    def _build_mode_components(self):
        player = self.game.get_player_stats(self.user_id, self.display_name)
        pet = self.game.get_gu_pet(player["active_gu_pet_id"]) if player["active_gu_pet_id"] else None
        can_toggle = pet is not None and pet["stage"] == gu_pet.STAGE_MATURE

        now_remaining = 0
        if can_toggle:
            last_switch = player["last_gu_pet_mode_switch_ts"] or 0
            now_remaining = gu_pet.MODE_SWITCH_COOLDOWN_SECONDS - (int(time.time()) - last_switch)

        switch_label = "Switch Mode"
        if can_toggle:
            other_mode = "Cultivation" if pet["mode"] == gu_pet.MODE_COMBAT else "Combat"
            switch_label = f"Switch to {other_mode} Mode"
        switch_button = discord.ui.Button(
            label=switch_label, emoji="🔄", style=discord.ButtonStyle.primary, row=1,
            disabled=not can_toggle or now_remaining > 0,
        )
        switch_button.callback = self._on_toggle_mode
        self.add_item(switch_button)

        pay_button = discord.ui.Button(
            label=f"Pay {gu_pet.MODE_SWITCH_FEE_SPIRIT_STONES:,} Stones to Switch Now", emoji="💰",
            style=discord.ButtonStyle.secondary, row=1,
            disabled=not can_toggle or now_remaining <= 0,
        )
        pay_button.callback = self._on_pay_toggle_mode
        self.add_item(pay_button)

    def _pet_label(self, p: dict) -> str:
        if p["stage"] == gu_pet.STAGE_GROWTH:
            return f"Rank {p['rank']} Gu Pet #{p['pet_id']} — growing (day {p['growth_days_fed']}/{p['growth_days_required']})"
        species = gu_pet.SPECIES[p["species"]]
        return f"{species.emoji} Rank {p['rank']} {species.name} #{p['pet_id']} — {p['mode'].title()} Mode"

    # -- action handlers ------------------------------------------------------------------

    async def _on_pick_sacrifice_item(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 1)
        value = select.values[0]
        if value != "none":
            self.selected_sacrifice_item = value
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_target_rank(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 2)
        self.selected_target_rank = int(select.values[0])
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_refine(self, interaction: discord.Interaction):
        def _do_refine():
            owned = self.game.gu_pet_refine_candidates(self.user_id)
            quantity = min(gu_pet.REFINE_MAX_SACRIFICE, dict(owned).get(self.selected_sacrifice_item, 0))
            result = self.game.refine_gu_pet(
                self.user_id, self.display_name, self.selected_sacrifice_item, quantity, self.selected_target_rank,
            )
            if result["ok"] and result["outcome"] in ("critical", "standard"):
                # A fresh player has nowhere else to point their new pet -- auto-activate it
                # only if nothing is already active, never silently swapping away a pet the
                # player already chose (see /gu_pet's own Mode tab, a later phase, for the
                # deliberate swap action).
                player = self.game.get_player_stats(self.user_id, self.display_name)
                if player["active_gu_pet_id"] is None:
                    self.game.set_active_gu_pet(self.user_id, result["pet_id"])
            return result

        result = await asyncio.to_thread(_do_refine)
        self.last_result = result.get("reason") or result.get("message")
        self.selected_sacrifice_item = None  # candidate list just changed (item consumed/refunded), re-pick fresh
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_feed_pet(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 1)
        value = select.values[0]
        if value != "none":
            self.selected_feed_pet_id = int(value)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_feed_item(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 2)
        value = select.values[0]
        if value != "none":
            self.selected_feed_item = value
        self.selected_feed_quantity = 1  # owned quantity just changed, re-pick fresh
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_feed_quantity(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 4)
        self.selected_feed_quantity = int(select.values[0])
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_feed(self, interaction: discord.Interaction):
        result = await asyncio.to_thread(
            self.game.feed_gu_pet, self.user_id, self.display_name, self.selected_feed_pet_id,
            self.selected_feed_item, self.selected_feed_quantity,
        )
        self.last_result = result.get("reason") or result.get("message")
        self.selected_feed_item = None  # owned quantity just changed, re-pick fresh
        self.selected_feed_quantity = 1
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_crystallize(self, interaction: discord.Interaction):
        result = await asyncio.to_thread(
            self.game.crystallize_gu_pet, self.user_id, self.display_name, self.selected_feed_pet_id,
        )
        self.last_result = result.get("reason") or result.get("message")
        crystallized_pet_id = self.selected_feed_pet_id if result.get("ok") else None
        self.selected_feed_pet_id = None  # this pet just left the "growing" list entirely
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)
        if crystallized_pet_id is not None:
            # Fire-and-forget AI portrait reveal (see game/gu_pet_images.py) -- species/path
            # only exist from THIS moment on, so crystallization is the earliest a portrait
            # prompt can be built at all. Called from this async handler on the main thread,
            # matching every other asyncio.create_task call site in this codebase (never via
            # asyncio.to_thread, which requires a running loop on the CURRENT thread).
            asyncio.create_task(self._resolve_gu_pet_portrait(crystallized_pet_id))

    async def _resolve_gu_pet_portrait(self, pet_id: int):
        """Resolves a few seconds after _on_crystallize's own response already went out --
        generates (or reuses a cached) AI portrait and edits the message in place via
        attachment://. Silently does nothing if OPENAI_API_KEY is unset, the request fails,
        or the view's message isn't available for any reason -- a missing portrait must never
        surface as an error to the player (see game/gu_pet_images.py's own module docstring)."""
        image_path = await self.game.get_or_create_gu_pet_image(pet_id)
        if image_path is None or self.message is None:
            return
        try:
            embed = self.message.embeds[0] if self.message.embeds else discord.Embed(title="🐛 Gu Pet")
            embed.set_image(url="attachment://gu_pet_portrait.png")
            file = discord.File(image_path, filename="gu_pet_portrait.png")
            await self.message.edit(embed=embed, attachments=[file])
        except discord.HTTPException:
            pass

    async def _on_pick_status_pet(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 1)
        value = select.values[0]
        if value != "none":
            self.selected_status_pet_id = int(value)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_set_active_pet(self, interaction: discord.Interaction):
        await asyncio.to_thread(self.game.set_active_gu_pet, self.user_id, self.selected_status_pet_id)
        self.last_result = "⭐ This Gu Pet is now your active companion — only its bonuses apply."
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_status_feed_item(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 2)
        value = select.values[0]
        if value != "none":
            self.selected_status_feed_item = value
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_feed_satiety(self, interaction: discord.Interaction):
        result = await asyncio.to_thread(
            self.game.feed_gu_pet_satiety, self.user_id, self.display_name, self.selected_status_pet_id, self.selected_status_feed_item, 1,
        )
        self.last_result = result.get("reason") or result.get("message")
        self.selected_status_feed_item = None  # owned quantity just changed, re-pick fresh
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_toggle_mode(self, interaction: discord.Interaction):
        await self._do_toggle_mode(interaction, pay_fee=False)

    async def _on_pay_toggle_mode(self, interaction: discord.Interaction):
        await self._do_toggle_mode(interaction, pay_fee=True)

    async def _do_toggle_mode(self, interaction: discord.Interaction, pay_fee: bool):
        def _do():
            player = self.game.get_player_stats(self.user_id, self.display_name)
            if not player["active_gu_pet_id"]:
                return {"ok": False, "reason": "You have no active Gu Pet — set one from the Status tab first."}
            return self.game.toggle_gu_pet_mode(self.user_id, self.display_name, player["active_gu_pet_id"], pay_fee=pay_fee)

        result = await asyncio.to_thread(_do)
        self.last_result = result.get("reason") or result.get("message")
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    # -- embed building ---------------------------------------------------------------

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(title="🐛 Gu Pet", color=discord.Color.dark_green())
        if self.active_tab == "refine":
            self._fill_refine_embed(embed)
        elif self.active_tab == "feed":
            self._fill_feed_embed(embed)
        elif self.active_tab == "status":
            self._fill_status_embed(embed)
        elif self.active_tab == "mode":
            self._fill_mode_embed(embed)
        if self.last_result:
            embed.add_field(name="Result", value=self.last_result[:1024], inline=False)
        return embed

    def _fill_refine_embed(self, embed: discord.Embed):
        player = self.game.get_player_stats(self.user_id, self.display_name)
        embed.description = (
            f"Sacrifice **1-3 {gu_pet.REFINE_REQUIRED_GU_QUALITY}-quality Gu** (pure energy mass — its own "
            "stats/identity never carry over) plus catalysts to hatch a blank Gu Pet, then feed it through the "
            "**Feed** tab to grow it. Any rank is attemptable at any Gu Refiner rank — reaching above your own "
            "level just costs success chance instead of being blocked outright.\n\n"
            f"Your Gu Refiner rank: **{professions.rank_name(player['gu_refiner_rank'])}**"
        )
        if self.selected_target_rank is not None:
            catalysts = gu_pet.refine_catalyst_recipe(self.selected_target_rank)
            inventory = self.game.get_inventory(self.user_id)
            catalyst_lines = "\n".join(f"**{mat}**: {inventory.get(mat, 0)}/{qty}" for mat, qty in catalysts.items())
            embed.add_field(name=f"Catalysts (Rank {self.selected_target_rank})", value=catalyst_lines, inline=False)
            candidates = self.game.gu_pet_refine_candidates(self.user_id)
            owned_sacrifice = dict(candidates).get(self.selected_sacrifice_item, 0)
            preview_quantity = min(gu_pet.REFINE_MAX_SACRIFICE, max(gu_pet.REFINE_MIN_SACRIFICE, owned_sacrifice))
            chance = gu_pet.refine_success_chance(player["gu_refiner_rank"], self.selected_target_rank, preview_quantity)
            embed.add_field(name="Success Chance", value=f"**~{chance * 100:.0f}%** (sacrificing {preview_quantity})", inline=True)
        owned_pets = self.game.get_player_gu_pets(self.user_id)
        if owned_pets:
            lines = [
                f"{'⭐ ' if pet['pet_id'] == player['active_gu_pet_id'] else ''}"
                f"Rank {pet['rank']} ({gu_pet.rank_to_rarity(pet['rank'])}) — {pet['species'] or 'still growing'}"
                for pet in owned_pets
            ]
            embed.add_field(name=f"Owned Gu Pets ({len(owned_pets)})", value="\n".join(lines)[:1024], inline=False)
        embed.set_footer(text="Higher Gu Refiner rank improves your success chance at every rank, and removes the penalty for reaching above your level.")

    def _fill_feed_embed(self, embed: discord.Embed):
        growing_pets = [p for p in self.game.get_player_gu_pets(self.user_id) if p["stage"] == gu_pet.STAGE_GROWTH]
        embed.description = (
            "One feed visit per real day per Gu Pet, but feeding MORE material in that visit covers more "
            "growth-days at once — a big stockpile finishes it faster. Ore/Herb/Beast Material/Beast Core/Pills "
            "all grow different stats — the RATIO of everything fed decides its species once it's done growing "
            "(see the **Status** tab once that's ready). A Qi Multiplier Pill doubles that single feed's yield."
        )
        if not growing_pets:
            embed.add_field(name="No Growing Gu Pets", value="Refine one first from the **Refine** tab.", inline=False)
            return
        pet = next((p for p in growing_pets if p["pet_id"] == self.selected_feed_pet_id), growing_pets[0])
        streak_bonus = gu_pet.streak_bonus_pct(pet["feed_streak_days"])
        embed.add_field(
            name=f"Rank {pet['rank']} Gu Pet #{pet['pet_id']}",
            value=(
                f"Day **{pet['growth_days_fed']}/{pet['growth_days_required']}** • "
                f"Streak **{pet['feed_streak_days']}** (+{streak_bonus*100:.0f}% yield)"
            ),
            inline=False,
        )
        if pet["fed_totals"]:
            totals_text = ", ".join(f"{cat.replace('_', ' ').title()}: {qty}" for cat, qty in pet["fed_totals"].items())
            embed.add_field(name="Fed So Far", value=totals_text, inline=False)
        if pet["growth_days_fed"] >= pet["growth_days_required"]:
            embed.add_field(
                name="💎 Ready to Crystallize!",
                value="This Gu Pet has been fed enough — click **Crystallize** to lock in its permanent species and Path.",
                inline=False,
            )

    def _fill_status_embed(self, embed: discord.Embed):
        pets = self.game.get_player_gu_pets(self.user_id)
        player = self.game.get_player_stats(self.user_id, self.display_name)
        embed.description = "Only your **active** Gu Pet's bonuses actually apply — the rest sit dormant. Pick which one below."
        if not pets:
            embed.add_field(name="No Gu Pets Owned", value="Refine one first from the **Refine** tab.", inline=False)
            return
        pet = next((p for p in pets if p["pet_id"] == self.selected_status_pet_id), pets[0])
        is_active = pet["pet_id"] == player["active_gu_pet_id"]
        header = f"{'⭐ ' if is_active else ''}Rank {pet['rank']} ({gu_pet.rank_to_rarity(pet['rank'])}) Gu Pet #{pet['pet_id']}"
        if pet["stage"] == gu_pet.STAGE_GROWTH:
            embed.add_field(
                name=header,
                value=f"Still growing — day **{pet['growth_days_fed']}/{pet['growth_days_required']}**. Feed it from the **Feed** tab.",
                inline=False,
            )
            return
        species = gu_pet.SPECIES[pet["species"]]
        multiplier, band_label = gu_pet.satiety_band(pet["satiety"])
        embed.add_field(
            name=header,
            value=f"{species.emoji} **{species.name}** ({pet['path']}) — **{pet['mode'].title()} Mode**\n{species.role_text}",
            inline=False,
        )
        embed.add_field(name="Satiety", value=f"**{pet['satiety']:.0f}/100** — {band_label} ({multiplier*100:.0f}% output)", inline=True)
        if pet["stat_bonuses"]:
            embed.add_field(name="Stat Bonuses", value=equipment.describe_stat_bonuses(pet["stat_bonuses"])[:1024], inline=False)
        if pet["satiety"] < gu_pet.SATIETY_MAX:
            required_tier = gu_pet.rank_scaling(pet["rank"])["satiety_material_tier"]
            embed.set_footer(text=f"Feed it a Tier {required_tier} material below to restore Satiety.")

    def _fill_mode_embed(self, embed: discord.Embed):
        player = self.game.get_player_stats(self.user_id, self.display_name)
        pet = self.game.get_gu_pet(player["active_gu_pet_id"]) if player["active_gu_pet_id"] else None
        embed.description = (
            "Combat Mode drains Satiety per dispatch (/hunt, /raid, /battlefield, /inheritance_ground, "
            "/search_black_heaven) and grants your pet's combat bonuses; Cultivation Mode drains Satiety "
            "slowly over real time and grants its cultivation/crafting bonuses instead."
        )
        if pet is None:
            embed.add_field(name="No Active Gu Pet", value="Set one active from the **Status** tab first.", inline=False)
            return
        if pet["stage"] != gu_pet.STAGE_MATURE:
            embed.add_field(name="Still Growing", value="Your active Gu Pet hasn't crystallized yet — it has no Mode to switch.", inline=False)
            return
        species = gu_pet.SPECIES[pet["species"]]
        multiplier, band_label = gu_pet.satiety_band(pet["satiety"])
        embed.add_field(
            name=f"{species.emoji} {species.name} — **{pet['mode'].title()} Mode**",
            value=f"Satiety **{pet['satiety']:.0f}/100** ({band_label}, {multiplier*100:.0f}% output)",
            inline=False,
        )
        last_switch = player["last_gu_pet_mode_switch_ts"] or 0
        remaining = gu_pet.MODE_SWITCH_COOLDOWN_SECONDS - (int(time.time()) - last_switch)
        if remaining > 0:
            from .ui_utils import format_duration
            embed.set_footer(text=f"Mode can be switched freely again in {format_duration(remaining)}, or pay {gu_pet.MODE_SWITCH_FEE_SPIRIT_STONES:,} spirit stones now.")
