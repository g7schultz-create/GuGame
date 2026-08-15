import asyncio

import discord

from .base_view import GameView
from .ui_utils import format_number


class GuUpgradeView(GameView):
    BREAKDOWN_BATCH_COUNT = 10

    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.last_result: str = None
        # Separate from the Fuse select — breaking down works on ANY owned Gu (even a
        # single copy, or one with no fusion path left), not just fusion-eligible ones.
        self.selected_breakdown_item: str = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your Gu collection.", ephemeral=True)
            return False
        return True

    def _fuse_candidates(self):
        return self.game.gu_upgrade_candidates(self.user_id)

    def _breakdown_candidates(self):
        return self.game.gu_breakdown_candidates(self.user_id)

    def _remaining_breakdown(self, item_name: str) -> int:
        if not item_name:
            return 0
        return self.game.get_inventory(self.user_id).get(item_name, 0)

    def _build_components(self):
        self.clear_items()

        fuse_candidates = self._fuse_candidates()
        fuse_options = [
            discord.SelectOption(label=name[:100], description=f"You own {qty} — fuses {required} into 1x {next_name}"[:100], value=name)
            for name, next_name, qty, required in fuse_candidates
        ]
        fuse_select = discord.ui.Select(
            placeholder="Fuse a Gu (needs enough copies of the same quality)" if fuse_options else "No fusable Gu yet",
            options=fuse_options[:25] or [discord.SelectOption(label="None available", value="none")],
            disabled=not fuse_options,
            row=0,
        )
        fuse_select.callback = self._on_upgrade
        self.add_item(fuse_select)

        # A Select always occupies its whole row on its own, so Fuse All gets its own row
        # right below the Fuse select rather than sharing row 0 with it.
        fuse_all = discord.ui.Button(
            label="Fuse All", emoji="⏫", style=discord.ButtonStyle.success, row=1, disabled=not fuse_candidates,
        )
        fuse_all.callback = self._on_fuse_all
        self.add_item(fuse_all)

        breakdown_candidates = self._breakdown_candidates()
        breakdown_options = [
            discord.SelectOption(
                label=f"{name} (own {qty})"[:100], value=name,
                description=f"Breaks down for {format_number(stones)} 🪙 each"[:100],
                default=(name == self.selected_breakdown_item),
            )
            for name, qty, stones in breakdown_candidates
        ]
        breakdown_select = discord.ui.Select(
            placeholder="Choose a Gu to break down..." if breakdown_options else "No Gu to break down",
            options=breakdown_options[:25] or [discord.SelectOption(label="None available", value="none")],
            disabled=not breakdown_options,
            row=2,
        )
        breakdown_select.callback = self._on_pick_breakdown
        self.add_item(breakdown_select)

        remaining = self._remaining_breakdown(self.selected_breakdown_item)
        break1 = discord.ui.Button(label="Break Down 1", emoji="🔨", style=discord.ButtonStyle.danger, row=3, disabled=remaining < 1)
        break1.callback = self._make_breakdown_callback(1)
        self.add_item(break1)

        break10 = discord.ui.Button(
            label=f"Break Down {self.BREAKDOWN_BATCH_COUNT}", emoji="⏩", style=discord.ButtonStyle.danger, row=3, disabled=remaining < 1,
        )
        break10.callback = self._make_breakdown_callback(self.BREAKDOWN_BATCH_COUNT)
        self.add_item(break10)

        break_all = discord.ui.Button(label=f"Break Down All ({remaining})", emoji="⏭️", style=discord.ButtonStyle.danger, row=3, disabled=remaining < 1)
        break_all.callback = self._make_breakdown_callback(remaining)
        self.add_item(break_all)

    async def _on_upgrade(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 0)
        choice = select.values[0]
        if choice == "none":
            await interaction.response.defer()
            return
        ok, message, _ = await asyncio.to_thread(self.game.upgrade_gu, self.user_id, self.display_name, choice)
        self.last_result = message
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_fuse_all(self, interaction: discord.Interaction):
        """Fuses everything fusable, cascading -- a fresh batch of duplicates produced by
        one round of fusions (e.g. 4 Common -> 2 Uncommon) may itself become fusable, so this
        loops to exhaustion rather than a single pass like Refine All. Always terminates:
        each successful fusion strictly reduces total Gu owned (consumes >=2, produces 1),
        and the quality ladder is finite (gu_upgrade_candidates naturally stops offering
        Immortal-quality Gu, since GU_UPGRADE_DUPLICATES_REQUIRED has no entry past Mythic).
        Deferred since a long cascade can exceed Discord's 3s ack window, same reasoning as
        weapons_view.py's Dismantle All / manual_view.py's Study All/Refine All."""
        await interaction.response.defer()
        total = 0
        while True:
            candidates = await asyncio.to_thread(self._fuse_candidates)
            if not candidates:
                break
            progressed = False
            for item_name, _next_name, _qty, _required in candidates:
                ok, _message, _ = await asyncio.to_thread(self.game.upgrade_gu, self.user_id, self.display_name, item_name)
                if ok:
                    total += 1
                    progressed = True
            if not progressed:
                break
        self.last_result = f"Fused {total}x." if total else "Nothing left to fuse."
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.edit_original_response(embed=embed, view=self)

    async def _on_pick_breakdown(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 2)
        choice = select.values[0]
        if choice == "none":
            await interaction.response.defer()
            return
        self.selected_breakdown_item = choice
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def _make_breakdown_callback(self, quantity: int):
        async def callback(interaction: discord.Interaction):
            item_name = self.selected_breakdown_item
            ok, message, _ = await asyncio.to_thread(self.game.breakdown_gu, self.user_id, self.display_name, item_name, quantity)
            self.last_result = message
            if ok and await asyncio.to_thread(self._remaining_breakdown, item_name) == 0:
                self.selected_breakdown_item = None  # nothing left of this Gu to keep targeting
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🧬 Gu Fusion & Breakdown",
            description=(
                "**Fuse** duplicate copies of the same Gu at the same quality into 1 copy at the next quality "
                "tier — the number needed grows with quality, 2 at Common through Rare, up to 5 at Mythic.\n"
                "**Break Down** any Gu you don't want instead, for spirit stones — value scales with quality "
                "(or a base amount for the original non-tiered Gu).\n"
                "Both lists show your strongest Gu first."
            ),
            color=discord.Color.dark_teal(),
        )

        fuse_candidates = self._fuse_candidates()
        if fuse_candidates:
            lines = [f"**{name}** x{qty} → 1x {next_name} (needs {required})" for name, next_name, qty, required in fuse_candidates]
            embed.add_field(name="Available Fusions", value="\n".join(lines)[:1024], inline=False)
        else:
            embed.add_field(name="Available Fusions", value="None yet — hunt or raid to collect duplicate Gu.", inline=False)

        breakdown_candidates = self._breakdown_candidates()
        if breakdown_candidates:
            lines = [f"**{name}** x{qty} — {format_number(stones)} 🪙 each" for name, qty, stones in breakdown_candidates]
            embed.add_field(name="Break Down Value", value="\n".join(lines)[:1024], inline=False)
        else:
            embed.add_field(name="Break Down Value", value="You have no Gu to break down.", inline=False)

        if self.last_result:
            embed.add_field(name="Result", value=self.last_result, inline=False)
        return embed
