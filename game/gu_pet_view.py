"""
GuPetView -- the /gu_pet menu. Refine tab (Phase 2): sacrifice 10-20 identical copies of one
owned Gu plus Soul Nourishing Pill/Soul Crystal catalysts into a blank Gu Pet. Feed/Status/
Mode tabs are declared now (so the tab bar's shape stays stable across phases) but are filled
in by their own later phases -- see game/gu_pet.py's own module docstring for the full
lifecycle.
"""

import asyncio
import discord

from . import gu_pet, professions
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
            placeholder="Choose a Gu to sacrifice (needs 10+ identical copies)",
            options=item_options[:25] or [discord.SelectOption(label="No eligible Gu owned", value="none")],
            disabled=not item_options, row=1,
        )
        item_select.callback = self._on_pick_sacrifice_item
        self.add_item(item_select)

        max_eligible_rank = 1
        for rank in range(gu_pet.MIN_RANK, gu_pet.MAX_RANK + 1):
            if player["gu_refiner_rank"] >= gu_pet.gu_refiner_rank_required(rank):
                max_eligible_rank = rank
        if self.selected_target_rank is None or self.selected_target_rank > max_eligible_rank:
            self.selected_target_rank = max_eligible_rank

        rank_options = [
            discord.SelectOption(
                label=f"Rank {rank} ({gu_pet.rank_to_rarity(rank)})", value=str(rank),
                default=(rank == self.selected_target_rank),
            )
            for rank in range(gu_pet.MIN_RANK, max_eligible_rank + 1)
        ]
        rank_select = discord.ui.Select(placeholder="Target Gu Pet rank", options=rank_options, row=2)
        rank_select.callback = self._on_pick_target_rank
        self.add_item(rank_select)

        catalysts = gu_pet.refine_catalyst_recipe(self.selected_target_rank)
        inventory = self.game.get_inventory(self.user_id)
        can_afford_catalysts = all(inventory.get(mat, 0) >= qty for mat, qty in catalysts.items())
        owned_sacrifice = dict(candidates).get(self.selected_sacrifice_item, 0)
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
        button = discord.ui.Button(
            label="Feed", emoji="🍖", style=discord.ButtonStyle.success, row=3,
            disabled=not (pet_options and item_options and feedable_by_name.get(self.selected_feed_item, 0) > 0),
        )
        button.callback = self._on_feed
        self.add_item(button)

        selected_pet = next((p for p in growing_pets if p["pet_id"] == self.selected_feed_pet_id), None)
        ready = selected_pet is not None and selected_pet["growth_days_fed"] >= selected_pet["growth_days_required"]
        crystallize_button = discord.ui.Button(
            label="Crystallize", emoji="💎", style=discord.ButtonStyle.primary, row=3, disabled=not ready,
        )
        crystallize_button.callback = self._on_crystallize
        self.add_item(crystallize_button)

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
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_feed(self, interaction: discord.Interaction):
        result = await asyncio.to_thread(
            self.game.feed_gu_pet, self.user_id, self.display_name, self.selected_feed_pet_id, self.selected_feed_item, 1,
        )
        self.last_result = result.get("reason") or result.get("message")
        self.selected_feed_item = None  # owned quantity just changed, re-pick fresh
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_crystallize(self, interaction: discord.Interaction):
        result = await asyncio.to_thread(
            self.game.crystallize_gu_pet, self.user_id, self.display_name, self.selected_feed_pet_id,
        )
        self.last_result = result.get("reason") or result.get("message")
        self.selected_feed_pet_id = None  # this pet just left the "growing" list entirely
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
        else:
            label = next(lbl for key, lbl, _ in self.TABS if key == self.active_tab)
            embed.description = f"The **{label}** tab arrives in a later update — for now, use the **Refine**/**Feed** tabs to acquire and grow a Gu Pet."
        if self.last_result:
            embed.add_field(name="Result", value=self.last_result[:1024], inline=False)
        return embed

    def _fill_refine_embed(self, embed: discord.Embed):
        player = self.game.get_player_stats(self.user_id, self.display_name)
        embed.description = (
            "Sacrifice **10-20 identical copies** of one owned Gu (pure energy mass — its own stats/identity "
            "never carry over) plus catalysts to hatch a blank Gu Pet, then feed it daily through the **Feed** "
            "tab to grow it.\n\n"
            f"Your Gu Refiner rank: **{professions.rank_name(player['gu_refiner_rank'])}**"
        )
        if self.selected_target_rank is not None:
            catalysts = gu_pet.refine_catalyst_recipe(self.selected_target_rank)
            inventory = self.game.get_inventory(self.user_id)
            catalyst_lines = "\n".join(f"**{mat}**: {inventory.get(mat, 0)}/{qty}" for mat, qty in catalysts.items())
            embed.add_field(name=f"Catalysts (Rank {self.selected_target_rank})", value=catalyst_lines, inline=False)
        owned_pets = self.game.get_player_gu_pets(self.user_id)
        if owned_pets:
            lines = [
                f"{'⭐ ' if pet['pet_id'] == player['active_gu_pet_id'] else ''}"
                f"Rank {pet['rank']} ({gu_pet.rank_to_rarity(pet['rank'])}) — {pet['species'] or 'still growing'}"
                for pet in owned_pets
            ]
            embed.add_field(name=f"Owned Gu Pets ({len(owned_pets)})", value="\n".join(lines)[:1024], inline=False)
        embed.set_footer(text="Higher Gu Refiner rank unlocks higher pet ranks and improves your success chance.")

    def _fill_feed_embed(self, embed: discord.Embed):
        growing_pets = [p for p in self.game.get_player_gu_pets(self.user_id) if p["stage"] == gu_pet.STAGE_GROWTH]
        embed.description = (
            "One feed per real day per Gu Pet. Ore/Herb/Beast Material/Beast Core/Pills all grow different "
            "stats — the RATIO of everything fed decides its species once it's done growing (see the "
            "**Status** tab once that's ready). A Qi Multiplier Pill doubles that single feed's yield."
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
